# -*- coding: utf-8 -*-
"""Backend-Instanz: arbeitet Tasks ab, wenn der Chat gerade nichts braucht.

Das Problem hinter der alten delegate-Regel war nie Kompetenz, sondern
Nebenlaeufigkeit: Solange das Modell baut, ist der Telegram-Chat tot. Es
passt aber nur EIN Modell in den Speicher, also koennen Chat und Arbeit
nicht gleichzeitig laufen - sie muessen sich abwechseln.

Der Chat hat Vorrang. Kommt eine Nachricht, waehrend gearbeitet wird, hoert
diese Instanz nach dem laufenden Paket auf und schreibt ihren Stand weg.
Sie wird nicht pausiert: Ein angehaltener Prozess haelt 18 GB fest, und
genau daran sind Laeufe gestorben.

Was gebaut ist, liegt ohnehin im Dateisystem - das ist der eigentliche
Zustand. Der geschriebene State ergaenzt nur, was man den Dateien nicht
ansieht: warum abgebrochen wurde und wo es weitergeht.

    python -m hub._services.chat.worker --category lerncockpit-android \\
        --workdir /Users/lukas/dev/lerncockpit-android --model qwen3.8:27b-mlx
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

#: Sessions des Backends selbst - ihre Speicherung ist KEINE Chat-Aktivitaet.
#: Ohne diese Unterscheidung wuerde sich der Worker durch seine eigene Arbeit
#: dauerhaft selbst zurueckhalten.
EIGENE_PRAEFIXE = ("task-", "plan-", "agent-", "worker-")


def _log(workdir: Path, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with io.open(workdir / "worker.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def chat_still_seit(db: str) -> float | None:
    """Sekunden seit der letzten ECHTEN Chat-Nachricht.

    Gemessen an ``session_snapshots``: Der Chat schreibt bei jeder Nachricht
    einen Schnappschuss. Die eigenen Sessions des Backends werden dabei
    ausgenommen - sonst meldet der Worker seine eigene Arbeit als Chatverkehr
    und laesst sich nie wieder los.

    ``None`` heisst: nicht messbar (kein Schnappschuss, keine DB). Dann wird
    nicht geraten, sondern zurueckgehalten.
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = con.execute(
            "SELECT session_id, created_at FROM session_snapshots "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()

    for session_id, created in rows:
        sid = str(session_id or "")
        if any(sid.startswith(p) for p in EIGENE_PRAEFIXE):
            continue
        try:
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    return None


def ist_fertig(antwort: str | None) -> bool:
    """Der Auftrag verlangt FERTIG am Ende der Antwort; frueher wurde nur der
    Anfang geprueft, lange Abschlussberichte galten dann als offen."""
    text = (antwort or "").upper()
    return "FERTIG" in text[:300] or "FERTIG" in text[-300:]


def state_schreiben(bach_cli: str, category: str, text: str) -> bool:
    """Stand ueber die BACH-CLI ablegen, nicht per Direktschreibzugriff."""
    try:
        r = subprocess.run(
            [sys.executable, bach_cli, "mem", "write", f"[worker:{category}] {text}"],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except Exception:
        return False


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Tasks abarbeiten, wenn der Chat ruht")
    ap.add_argument("--category", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--db", default="")
    ap.add_argument("--mode", default="full", choices=["safe", "full"])
    ap.add_argument("--ruhe", type=int, default=600,
                    help="Sekunden Chat-Stille, bevor gearbeitet wird")
    ap.add_argument("--takt", type=int, default=60, help="Sekunden zwischen zwei Pruefungen")
    ap.add_argument("--max-tasks", type=int, default=0, help="0 = bis nichts mehr offen ist")
    ap.add_argument("--einmal", action="store_true", help="nur eine Runde, dann beenden")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    bach = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(bach))
    os.chdir(bach)
    from hub.bach_paths import BACH_DB
    db = args.db or str(BACH_DB)
    bach_cli = str(bach / "bach.py")

    os.environ.setdefault("BACH_DELEGATION_DEPTH", "2")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    from hub._services.chat.task_runner import offene_tasks, markiere_erledigt
    from hub._services.agents_heart import begin_assignment, finish_assignment
    from hub._services import fackel
    from hub._services.chat import telegram_chat as tc

    try:
        from hub.compute_lock import (
            check_compute_active,
            get_fackel_preference,
            pause_compute_jobs,
            resume_compute_jobs,
        )
        HAS_COMPUTE_LOCK = True
    except ImportError:
        HAS_COMPUTE_LOCK = False
        def get_fackel_preference(): return "compute"
        def check_compute_active(): return False, {}
        def pause_compute_jobs(s): return []
        def resume_compute_jobs(p): pass

    runtime = tc.runtime
    runtime.max_tool_rounds = 0
    runtime.auto_continue = 8
    tc._global_defaults["mode"] = args.mode

    # --model ist optional; ohne Angabe faehrt der Runtime seinen Vorgabewert.
    # Den braucht das Fackel-Gate, sonst gilt ihm das eigene, laengst
    # geladene Modell als fremder Bewerber und der Worker wartet ewig.
    modell = args.model or getattr(runtime.backend, "get_default_model",
                                   lambda: "")()

    _log(workdir, f"Worker startet fuer {args.category!r}: arbeitet nach "
                  f"{args.ruhe}s Chat-Stille, prueft alle {args.takt}s, "
                  f"Modell {modell or '(Vorgabe)'}")

    erledigt_gesamt = 0
    agent_instance_id = f"worker-{uuid.uuid4().hex}"
    while True:
        still = chat_still_seit(db)
        offen = offene_tasks(db, args.category)

        if not offen:
            _log(workdir, "keine bereiten Tasks - Ende")
            return 0

        compute_active, compute_status = (check_compute_active() if HAS_COMPUTE_LOCK else (False, {}))
        fackel_pref = get_fackel_preference() if HAS_COMPUTE_LOCK else "compute"

        if still is None:
            _log(workdir, "Chat-Aktivitaet nicht messbar - halte zurueck")
        elif still < args.ruhe:
            _log(workdir, f"Chat war vor {round(still)}s aktiv (Schwelle {args.ruhe}s) - warte")
        elif compute_active and fackel_pref == "compute":
            _log(workdir, "Rechenjobs aktiv und Fackel steht auf 'compute' - warte")
        elif not fackel.passt(fuer_modell=modell):
            # Still heisst nicht frei: Haelt ein FREMDES Modell den Speicher,
            # wuerde unser Modell in einen vollen Speicher geladen. Das eigene
            # Modell zaehlt nicht mit - ist es schon da, kostet es nichts mehr.
            # Bei nicht messbarer Kapazitaet greift fail-closed; der Worker wartet
            # ebenso, meldet aber die fehlende Messung statt einer Scheinbelegung.
            f = fackel.stand(modell)
            if not f.get("messbar"):
                _log(workdir, "Fackel-Kapazitaet nicht messbar (gesperrt / fail-closed; "
                              "BACH_FACKEL_KAPAZITAET_MB setzen) - warte")
            else:
                _log(workdir, f"Speicher belegt von {', '.join(f['modelle']) or '?'} "
                              f"({f['belegt_gib']} GiB) - {f['frei_fackeln']} von 10 "
                              f"Fackeln frei, warte")
        else:
            gewaehlter_task = None
            for cand in offen:
                cid = cand["id"]
                try:
                    r = subprocess.run(
                        [sys.executable, bach_cli, "task", "claim", str(cid), "--by", f"worker:{args.category}"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if r.returncode == 0:
                        gewaehlter_task = cand
                        break
                    else:
                        _log(workdir, f"Task #{cid} bereits beansprucht, ueberspringe")
                except Exception as ce:
                    _log(workdir, f"Task #{cid} Claim-Fehler: {ce}, ueberspringe")

            if not gewaehlter_task:
                _log(workdir, "alle Kandidaten bereits beansprucht - warte")
                if args.einmal:
                    return 0
                time.sleep(max(5, args.takt))
                continue

            t = gewaehlter_task
            _log(workdir, f"Chat still seit {round(still/60)} min - nehme "
                          f"#{t['id']} {t['title'][:52]}")

            chat_id = f"worker-{args.category}-{t['id']}"
            with tc.legacy_worker_binding(chat_id):
                session = runtime.get_session(chat_id)
            session.mode = args.mode
            session.think = True
            if modell:
                session.model = modell
            runtime.goal = t["title"]

            # Die Modellwahl bleibt unverändert: hier wird nur der tatsächlich
            # aktive Backend-/Modellwert für die Besetzungsquittung gelesen.
            active_backend = getattr(session, "backend", None) or runtime.backend
            try:
                from hub._services.llm.model_backend import backend_identifier
                backend_id = backend_identifier(active_backend)
            except (ImportError, AttributeError):
                backend_id = ""
            backend_id = backend_id or getattr(active_backend, "backend_id", "")
            backend_id = backend_id or type(active_backend).__name__
            model_id = session.model or modell
            if not model_id:
                model_id = getattr(active_backend, "get_default_model", lambda: "")()

            try:
                assignment = begin_assignment(
                    role_id="hintergrund_worker",
                    mode=args.mode,
                    agent_instance_id=agent_instance_id,
                    backend_id=backend_id,
                    model_id=model_id,
                    slot_id="buddha_always_on",
                    task_id=t["id"],
                    session_id=chat_id,
                    initiated_by=f"worker:{args.category}",
                )
            except Exception as assignment_error:
                # Claim ohne belegbare Besetzung darf nicht in eine Ausführung
                # übergehen. Den Task freigeben und fail-closed weiterlaufen.
                _log(workdir, f"Task #{t['id']} Besetzungsprüfung fehlgeschlagen: {assignment_error}")
                try:
                    subprocess.run(
                        [sys.executable, bach_cli, "task", "release", str(t["id"]), "--by", f"worker:{args.category}"],
                        capture_output=True, text=True, timeout=30,
                    )
                except Exception as re:
                    _log(workdir, f"Task #{t['id']} Release-Fehler nach Besetzungsprüfung: {re}")
                if args.einmal:
                    return 1
                time.sleep(max(5, args.takt))
                continue

            auftrag = [f"AUFGABE (Task #{t['id']}): {t['title']}"]
            if t.get("description"):
                auftrag.append(t["description"])
            auftrag.append(
                "Erledige NUR diese Aufgabe. Lies nur, was dafuer noetig ist. "
                "Pruefe dein Ergebnis, bevor du fertig meldest. Was du baust, "
                "bleibt auf der Platte - ein Abbruch verliert nur den Verlauf, "
                "nicht die Arbeit. Antworte am Ende mit FERTIG."
            )

            paused_jobs = []
            if compute_active and fackel_pref == "ollama":
                paused_jobs = pause_compute_jobs(compute_status)
                if paused_jobs:
                    _log(workdir, f"Fackel steht auf 'ollama' - pausiere Rechenjobs ({paused_jobs}) fuer Inferenz")

            t0 = time.time()
            antwort = ""
            interrupted = False
            process_error: Exception | None = None
            try:
                with tc.legacy_worker_binding(chat_id):
                    antwort = asyncio.run(
                        runtime.process("\n\n".join(auftrag), chat_id, skip_compute_gate=True)
                    )
            except KeyboardInterrupt:
                interrupted = True
                _log(workdir, "unterbrochen")
            except Exception as e:
                _log(workdir, f"    FEHLER: {e!r}")
                process_error = e
            finally:
                if paused_jobs:
                    try:
                        resume_compute_jobs(paused_jobs)
                        _log(workdir, f"Rechenjobs ({paused_jobs}) fortgesetzt")
                    except Exception as re:
                        _log(workdir, f"Rechenjobs ({paused_jobs}) konnten nicht fortgesetzt werden: {re}")

            dauer = round(time.time() - t0)
            if interrupted:
                try:
                    subprocess.run(
                        [sys.executable, bach_cli, "task", "release", str(t["id"]), "--by", f"worker:{args.category}"],
                        capture_output=True, text=True, timeout=30,
                    )
                except Exception as re:
                    _log(workdir, f"Task #{t['id']} Release-Fehler bei Abbruch: {re}")
                state_schreiben(bach_cli, args.category,
                                f"Task #{t['id']} unterbrochen nach "
                                f"{dauer}s. Gebautes liegt in {workdir}.")
                try:
                    finish_assignment(
                        assignment, status="interrupted", result="keyboard_interrupt"
                    )
                except Exception as ae:
                    _log(workdir, f"Task #{t['id']} Endeprotokoll fehlgeschlagen: {ae}")
                _log(workdir, "unterbrochen - Stand geschrieben")
                return 130

            if process_error is not None:
                try:
                    subprocess.run(
                        [sys.executable, bach_cli, "task", "release", str(t["id"]), "--by", f"worker:{args.category}"],
                        capture_output=True, text=True, timeout=30,
                    )
                except Exception as re:
                    _log(workdir, f"Task #{t['id']} Release-Fehler nach Fehler: {re}")
                state_schreiben(
                    bach_cli,
                    args.category,
                    f"Task #{t['id']} nach {dauer}s mit Fehler nicht fertig. "
                    f"Gebautes liegt in {workdir}.",
                )
                try:
                    finish_assignment(
                        assignment,
                        status="error",
                        result="runtime_error",
                        reason=type(process_error).__name__,
                    )
                except Exception as ae:
                    _log(workdir, f"Task #{t['id']} Endeprotokoll fehlgeschlagen: {ae}")
                if args.einmal:
                    return 0
                continue

            fertig = ist_fertig(antwort)
            _log(workdir, f"    {dauer}s, {'FERTIG' if fertig else 'offen'}")

            erledigt = False
            if fertig:
                try:
                    erledigt = bool(markiere_erledigt(bach_cli, t["id"]))
                except Exception as me:
                    _log(workdir, f"    #{t['id']} Abschlussmarkierung fehlgeschlagen: {me}")

            if erledigt:
                erledigt_gesamt += 1
                _log(workdir, f"    #{t['id']} abgehakt")
                assignment_status = "completed"
                assignment_result = "task_done"
            else:
                # Der Stand gehoert in die DB, weil man ihm den Dateien nicht
                # ansieht: dass versucht wurde und woran es lag.
                state_schreiben(bach_cli, args.category,
                                f"Task #{t['id']} nach {dauer}s nicht fertig. "
                                f"Letzte Antwort: {(antwort or '')[:200]}")
                try:
                    subprocess.run(
                        [sys.executable, bach_cli, "task", "release", str(t["id"]), "--by", f"worker:{args.category}"],
                        capture_output=True, text=True, timeout=30,
                    )
                except Exception as re:
                    _log(workdir, f"Task #{t['id']} Release-Fehler: {re}")
                assignment_status = "error" if fertig else "released"
                assignment_result = "completion_mark_failed" if fertig else "not_finished"

            try:
                finish_assignment(
                    assignment,
                    status=assignment_status,
                    result=assignment_result,
                )
            except Exception as ae:
                _log(workdir, f"Task #{t['id']} Endeprotokoll fehlgeschlagen: {ae}")

            if args.max_tasks and erledigt_gesamt >= args.max_tasks:
                _log(workdir, f"{erledigt_gesamt} Pakete erledigt - Ende")
                return 0

        if args.einmal:
            return 0
        time.sleep(max(5, args.takt))


if __name__ == "__main__":
    raise SystemExit(main())
