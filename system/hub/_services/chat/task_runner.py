# -*- coding: utf-8 -*-
"""Arbeitet BACH-Tasks einzeln ab - jeden mit frischem Kontext.

Ein grosser Auftrag zwingt das Modell, das ganze Projekt zu lesen, bevor es
etwas tun kann. Bei 32k Fenster ist der Kontext dann voll, bevor die erste
Zeile entsteht - gemessen: 25 Werkzeugrunden Lesen, kein Ergebnis.

Ein Task benennt seinen Umfang. Das Modell liest, was dazu gehoert, und
faengt an. Danach beginnt der naechste mit leerem Fenster - keine Uebergabe
noetig, weil nichts mitgeschleppt werden muss.

    python -m hub._services.chat.task_runner --project lerncockpit-android \\
        --workdir /Users/lukas/dev/lerncockpit-android --model qwen3.8:27b-mlx

Schreibt nur ueber bach_api bzw. die CLI - nie direkt in bach.db.
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
from pathlib import Path


def _log(workdir: Path, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with io.open(workdir / "tasks.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def offene_tasks(db: str, project: str) -> list[dict]:
    """Offene Tasks eines Projekts, erfuellte Abhaengigkeiten zuerst.

    Lesend ueber eine read-only-Verbindung: Schreiben laeuft ausschliesslich
    ueber die BACH-CLI, damit der DB-Guard nicht umgangen wird.
    """
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, title, description, depends_on, status, priority "
            "FROM tasks WHERE (project = ? OR category = ?) "
            "AND status NOT IN ('done','cancelled') "
            "ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 "
            "WHEN 'P3' THEN 3 ELSE 4 END, id",
            (project, project),
        ).fetchall()
        erledigt = {
            r[0] for r in con.execute(
                "SELECT id FROM tasks WHERE (project = ? OR category = ?) AND status = 'done'", (project, project)
            )
        }
    finally:
        con.close()

    tasks = [dict(r) for r in rows]
    # Ein Task, dessen Vorgaenger noch offen ist, wartet - sonst baut das
    # Modell auf etwas auf, das es noch gar nicht gibt.
    bereit = []
    for t in tasks:
        dep = (t.get("depends_on") or "").strip()
        if not dep:
            bereit.append(t)
            continue
        try:
            ids = {int(x) for x in dep.replace(";", ",").split(",") if x.strip()}
        except ValueError:
            bereit.append(t)
            continue
        if ids <= erledigt:
            bereit.append(t)
    return bereit


def markiere_erledigt(bach_cli: str, task_id: int) -> bool:
    """Task abhaken - ueber die CLI, nicht per direktem Schreibzugriff."""
    try:
        r = subprocess.run(
            [sys.executable, bach_cli, "task", "done", str(task_id)],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BACH-Tasks paketweise abarbeiten")
    ap.add_argument("--project", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--db", default="")
    ap.add_argument("--mode", default="full", choices=["safe", "full"])
    ap.add_argument("--max-tasks", type=int, default=6)
    ap.add_argument("--auto-continue", type=int, default=8)
    ap.add_argument("--kontext", default="",
                    help="Datei, deren Inhalt jedem Task vorangestellt wird")
    args = ap.parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(workdir)

    bach = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(bach))
    db = args.db or str(bach / "data" / "bach.db")
    bach_cli = str(bach / "bach.py")

    os.environ.setdefault("BACH_DELEGATION_DEPTH", "2")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Ohne diese Zeile gilt der 180s-Default: jedes Paket endet in
    # "Backend-Fehler:" (leerer httpx.ReadTimeout), auch wenn es Arbeit
    # geleistet hat - und wird nie als erledigt gemeldet.
    os.environ.setdefault("BACH_LLM_TIMEOUT", "1200")

    rahmen = ""
    if args.kontext:
        try:
            rahmen = Path(args.kontext).read_text(encoding="utf-8").strip()
        except OSError as e:
            _log(workdir, f"Kontextdatei nicht lesbar: {e}")

    from hub._services.chat import telegram_chat as tc

    runtime = tc.runtime
    runtime.max_tool_rounds = 0
    runtime.auto_continue = args.auto_continue
    tc._global_defaults["mode"] = args.mode

    tasks = offene_tasks(db, args.project)
    _log(workdir, f"{len(tasks)} bereite Tasks im Projekt {args.project!r}")
    if not tasks:
        return 0

    erledigt = 0
    for nr, t in enumerate(tasks[: args.max_tasks], start=1):
        # Frische Sitzung je Task: das ist der Punkt der ganzen Uebung.
        chat_id = f"task-{args.project}-{t['id']}"
        session = runtime.get_session(chat_id)
        session.mode = args.mode
        session.think = True
        if args.model:
            session.model = args.model
        runtime.goal = t["title"]

        auftrag = []
        if rahmen:
            auftrag.append(rahmen)
        auftrag.append(f"AUFGABE (Task #{t['id']}): {t['title']}")
        if t.get("description"):
            auftrag.append(t["description"])
        auftrag.append(
            "Erledige NUR diese eine Aufgabe. Lies nur, was dafuer noetig ist - "
            "nicht das ganze Projekt. Pruefe dein Ergebnis, bevor du fertig "
            "meldest. Antworte am Ende mit FERTIG."
        )

        _log(workdir, f"--- Task {nr}/{min(len(tasks), args.max_tasks)}: "
                      f"#{t['id']} {t['title'][:60]}")
        t0 = time.time()
        try:
            antwort = asyncio.run(runtime.process("\n\n".join(auftrag), chat_id))
        except Exception as e:
            _log(workdir, f"    FEHLER: {e!r}")
            continue

        dauer = round(time.time() - t0)
        fertig = "FERTIG" in (antwort or "").upper()[:300]
        _log(workdir, f"    {dauer}s, {'FERTIG' if fertig else 'offen'}, "
                      f"{len(antwort or '')} Zeichen Antwort")
        if fertig and markiere_erledigt(bach_cli, t["id"]):
            erledigt += 1
            _log(workdir, f"    Task #{t['id']} abgehakt")

    _log(workdir, f"Ende: {erledigt} von {min(len(tasks), args.max_tasks)} erledigt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
