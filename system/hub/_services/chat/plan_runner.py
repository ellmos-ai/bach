# -*- coding: utf-8 -*-
"""Planungsmodus: das Modell zerlegt einen Auftrag selbst in BACH-Tasks.

Der Task-Runner arbeitet Pakete ab - aber jemand muss sie schneiden. Von Hand
geht das einmal; auf Dauer soll das Modell es selbst tun, weil nur es weiss,
wie viel Vorwissen ein Schritt wirklich braucht.

Gemessen, warum das noetig ist: Ein Auftrag "baue die Oberflaeche" fuehrte zu
25 Werkzeugrunden Lesen ohne Ergebnis (das Modell macht das ganze Projekt zum
Vorwissen). Dieselbe Arbeit in drei Paketen mit Lesevorgabe ergab 510 Zeilen
lauffaehige Oberflaeche.

    python -m hub._services.chat.plan_runner --auftrag-datei plan.txt \\
        --category lerncockpit-android --model qwen3.8:27b-mlx

Danach:
    python -m hub._services.chat.task_runner --project lerncockpit-android ...
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sqlite3
import sys
import time
from pathlib import Path

PLAN_PROMPT = """Du planst, du baust noch nicht.

Zerlege den folgenden Auftrag in einzelne Arbeitspakete und lege jedes per
task_manage(action="add") an. Baue in diesem Durchgang NICHTS - kein
write_file, kein execute_command ausser zum Nachsehen.

REGELN FUER DEN SCHNITT:
- {min_tasks} bis {max_tasks} Pakete. Weniger heisst zu grob, mehr heisst zerfasert.
- Jedes Paket muss in einem Zug erledigt werden koennen, ohne dass dafuer das
  ganze Projekt gelesen werden muss. Das ist der eigentliche Zweck: Dein
  Kontextfenster fasst {kontext} Token - ein Paket, das mehr Vorwissen
  verlangt, ist zu gross geschnitten.
- Jedes Paket beginnt mit dem Ergebnis, nicht mit der Taetigkeit:
  "Faecherliste zeigt Noten an", nicht "an der Faecherliste arbeiten".
- In die description gehoert BEIDES: was zu tun ist UND was dafuer zu lesen
  ist ("lies nur core.py Zeilen 1-60"). Ohne Lesevorgabe liest das Modell
  spaeter wieder alles.
- Wo moeglich, nenne einen Pruefbefehl, an dem das Paket als fertig erkennbar ist.
- depends_on setzen, wenn ein Paket ein anderes voraussetzt. Sonst leer lassen -
  eine erfundene Abhaengigkeit blockiert Arbeit, die parallel laufen koennte.
- Reihenfolge ueber priority: P1 zuerst, dann P2, P3, P4.
- category IMMER auf "{category}" setzen, sonst findet der Task-Runner nichts.

Nenne am Ende in einem Satz, warum du so geschnitten hast. Dann FERTIG.

--- AUFTRAG ---
{auftrag}
"""


def _log(out: Path, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with io.open(out, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def tasks_der_kategorie(db: str, category: str) -> list[dict]:
    """Was gerade in dieser Kategorie liegt - read-only."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, title, description, priority, depends_on, status "
            "FROM tasks WHERE category = ? ORDER BY id",
            (category,),
        ).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Auftrag in BACH-Tasks zerlegen")
    ap.add_argument("--auftrag", default="", help="Auftragstext direkt")
    ap.add_argument("--auftrag-datei", default="", help="Datei mit dem Auftragstext")
    ap.add_argument("--category", required=True, help="Projekt-/Themenzuordnung")
    ap.add_argument("--workdir", default="", help="Arbeitsverzeichnis (fuer das Log)")
    ap.add_argument("--model", default="")
    ap.add_argument("--db", default="")
    ap.add_argument("--min-tasks", type=int, default=3)
    ap.add_argument("--max-tasks", type=int, default=8)
    ap.add_argument("--kontext", type=int, default=0,
                    help="Kontextfenster in Token; 0 = aus den Limits lesen")
    args = ap.parse_args(argv)

    bach = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(bach))
    db = args.db or str(bach / "data" / "bach.db")

    workdir = Path(args.workdir).expanduser().resolve() if args.workdir else Path.cwd()
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "plan.log"

    auftrag = args.auftrag
    if args.auftrag_datei:
        try:
            auftrag = Path(args.auftrag_datei).read_text(encoding="utf-8").strip()
        except OSError as e:
            print(f"Auftragsdatei nicht lesbar: {e}", file=sys.stderr)
            return 2
    if not auftrag.strip():
        print("Kein Auftrag angegeben (--auftrag oder --auftrag-datei)", file=sys.stderr)
        return 2

    os.environ.setdefault("BACH_DELEGATION_DEPTH", "2")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("BACH_LLM_TIMEOUT", "1200")

    from hub._services.limits import limit
    from hub._services.chat import telegram_chat as tc

    kontext = args.kontext or limit("BACH_CONTEXT_LIMIT")

    runtime = tc.runtime
    runtime.max_tool_rounds = 0
    runtime.auto_continue = 4          # Planen braucht wenige Runden, nicht viele
    runtime.goal = ""

    # Planen heisst anlegen, nicht bauen - aber task_manage ist ein Werkzeug,
    # also reicht der safe-Modus nicht. Die Grenze setzt der Prompt.
    tc._global_defaults["mode"] = "full"
    chat_id = f"plan-{args.category}"
    session = runtime.get_session(chat_id)
    session.mode = "full"
    session.think = True
    if args.model:
        session.model = args.model

    vorher = {t["id"] for t in tasks_der_kategorie(db, args.category)}
    _log(out, f"Planung fuer {args.category!r}: {len(vorher)} Tasks vorhanden, "
              f"Kontextfenster {kontext} Token")

    prompt = PLAN_PROMPT.format(
        min_tasks=args.min_tasks, max_tasks=args.max_tasks,
        kontext=kontext, category=args.category, auftrag=auftrag,
    )

    t0 = time.time()
    try:
        antwort = asyncio.run(runtime.process(prompt, chat_id))
    except Exception as e:
        import traceback
        _log(out, f"FEHLER: {e!r}")
        _log(out, traceback.format_exc())
        return 1

    nachher = tasks_der_kategorie(db, args.category)
    neu = [t for t in nachher if t["id"] not in vorher]
    _log(out, f"{round(time.time()-t0)}s, {len(neu)} neue Pakete")

    for t in neu:
        beschr = (t.get("description") or "").strip()
        marke = "" if beschr else "  <- OHNE Beschreibung"
        dep = f" (nach {t['depends_on']})" if t.get("depends_on") else ""
        _log(out, f"  #{t['id']} [{t['priority']}]{dep} {t['title'][:64]}{marke}")

    ohne = [t for t in neu if not (t.get("description") or "").strip()]
    if ohne:
        _log(out, f"WARNUNG: {len(ohne)} Pakete ohne Beschreibung - ihnen fehlt "
                  f"die Lesevorgabe, sie werden spaeter wieder alles lesen.")

    with io.open(out, "a", encoding="utf-8") as f:
        f.write("--- Begruendung des Modells ---\n" + (antwort or "(leer)") + "\n")
    print(antwort or "(leer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
