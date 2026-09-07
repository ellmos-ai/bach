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


def main(argv: list[str] | None = None) -> int:
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
    args = ap.parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    bach = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(bach))
    os.chdir(bach)
    db = args.db or str(bach / "data" / "bach.db")
    bach_cli = str(bach / "bach.py")

    os.environ.setdefault("BACH_DELEGATION_DEPTH", "2")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    from hub._services.chat.task_runner import offene_tasks, markiere_erledigt
    from hub._services import fackel
    from hub._services.chat import telegram_chat as tc

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
    while True:
        still = chat_still_seit(db)
        offen = offene_tasks(db, args.category)

        if not offen:
            _log(workdir, "keine bereiten Tasks - Ende")
            return 0

        if still is None:
            _log(workdir, "Chat-Aktivitaet nicht messbar - halte zurueck")
        elif still < args.ruhe:
            _log(workdir, f"Chat war vor {round(still)}s aktiv (Schwelle {args.ruhe}s) - warte")
        elif not fackel.passt(fuer_modell=modell):
            # Still heisst nicht frei: Haelt ein FREMDES Modell den Speicher,
            # wuerde unser Modell in einen vollen Speicher geladen. Das eigene
            # Modell zaehlt nicht mit - ist es schon da, kostet es nichts mehr.
            f = fackel.stand(modell)
            _log(workdir, f"Speicher belegt von {', '.join(f['modelle']) or '?'} "
                          f"({f['belegt_gib']} GiB) - {f['frei_fackeln']} von 10 "
                          f"Fackeln frei, warte")
        else:
            t = offen[0]
            _log(workdir, f"Chat still seit {round(still/60)} min - nehme "
                          f"#{t['id']} {t['title'][:52]}")

            chat_id = f"worker-{args.category}-{t['id']}"
            session = runtime.get_session(chat_id)
            session.mode = args.mode
            session.think = True
            if modell:
                session.model = modell
            runtime.goal = t["title"]

            auftrag = [f"AUFGABE (Task #{t['id']}): {t['title']}"]
            if t.get("description"):
                auftrag.append(t["description"])
            auftrag.append(
                "Erledige NUR diese Aufgabe. Lies nur, was dafuer noetig ist. "
                "Pruefe dein Ergebnis, bevor du fertig meldest. Was du baust, "
                "bleibt auf der Platte - ein Abbruch verliert nur den Verlauf, "
                "nicht die Arbeit. Antworte am Ende mit FERTIG."
            )

            t0 = time.time()
            try:
                antwort = asyncio.run(runtime.process("\n\n".join(auftrag), chat_id))
            except KeyboardInterrupt:
                state_schreiben(bach_cli, args.category,
                                f"Task #{t['id']} unterbrochen nach "
                                f"{round(time.time()-t0)}s. Gebautes liegt in {workdir}.")
                _log(workdir, "unterbrochen - Stand geschrieben")
                return 130
            except Exception as e:
                _log(workdir, f"    FEHLER: {e!r}")
                antwort = ""

            dauer = round(time.time() - t0)
            fertig = "FERTIG" in (antwort or "").upper()[:300]
            _log(workdir, f"    {dauer}s, {'FERTIG' if fertig else 'offen'}")

            if fertig and markiere_erledigt(bach_cli, t["id"]):
                erledigt_gesamt += 1
                _log(workdir, f"    #{t['id']} abgehakt")
            else:
                # Der Stand gehoert in die DB, weil man ihm den Dateien nicht
                # ansieht: dass versucht wurde und woran es lag.
                state_schreiben(bach_cli, args.category,
                                f"Task #{t['id']} nach {dauer}s nicht fertig. "
                                f"Letzte Antwort: {(antwort or '')[:200]}")

            if args.max_tasks and erledigt_gesamt >= args.max_tasks:
                _log(workdir, f"{erledigt_gesamt} Pakete erledigt - Ende")
                return 0

        if args.einmal:
            return 0
        time.sleep(max(5, args.takt))


if __name__ == "__main__":
    raise SystemExit(main())
