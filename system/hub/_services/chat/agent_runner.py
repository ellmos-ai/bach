# -*- coding: utf-8 -*-
"""Agentenprozess auf einem lokalen Modell.

Das Gegenstueck zu ``claude``/``codex``/``agy`` fuer Ollama: derselbe
Tool-Loop, den auch der Chat benutzt, nur als eigenstaendiger Prozess mit
einem Arbeitsverzeichnis und einem Auftrag.

Der Auftrag kommt aus der ``CLAUDE.md``, die der Launcher ohnehin ins
Arbeitsverzeichnis schreibt - so bleibt die Agentendefinition dieselbe,
egal welcher Anbieter sie ausfuehrt.

    python -m hub._services.chat.agent_runner \\
        --model qwen3.8:27b-mlx --workdir /tmp/agent-theodor --mode full
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time
from pathlib import Path


def _log(workdir: Path, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with io.open(workdir / "agent.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _auftrag(workdir: Path) -> str:
    """Agentendefinition aus dem Arbeitsverzeichnis.

    CLAUDE.md ist der Name, den der Launcher schreibt; AGENTS.md und
    PROMPT.md werden mitgelesen, damit der Runner nicht am Dateinamen
    scheitert, wenn ein anderer Anbieter eine andere Konvention setzt.
    """
    for name in ("CLAUDE.md", "AGENTS.md", "PROMPT.md", "SKILL.md"):
        p = workdir / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if text:
                return text
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BACH-Agent auf einem lokalen Modell")
    ap.add_argument("--model", default="", help="Ollama-Modell")
    ap.add_argument("--workdir", required=True, help="Arbeitsverzeichnis des Agenten")
    ap.add_argument("--mode", default="safe", choices=["safe", "full"])
    ap.add_argument("--max-rounds", type=int, default=0,
                    help="Werkzeugrunden je Antwort (0 = unbegrenzt)")
    ap.add_argument("--auto-continue", type=int, default=12,
                    help="wie oft ohne Rueckfrage nachgelegt wird (0 = aus)")
    ap.add_argument("--goal", default="", help="Ziel, gegen das am Ende geprueft wird")
    args = ap.parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(workdir)

    auftrag = _auftrag(workdir)
    if not auftrag:
        _log(workdir, "FEHLER: keine Agentendefinition im Arbeitsverzeichnis "
                      "(CLAUDE.md / AGENTS.md / PROMPT.md / SKILL.md)")
        return 2

    bach = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(bach))
    # Der Loop schreibt und fuehrt aus; ohne Ausweg zu einem anderen Anbieter.
    os.environ.setdefault("BACH_DELEGATION_DEPTH", "2")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        from hub._services.chat import telegram_chat as tc
    except Exception as e:  # pragma: no cover - Umgebungsfehler
        _log(workdir, f"FEHLER beim Laden der Chat-Runtime: {e!r}")
        return 3

    runtime = tc.runtime
    runtime.max_tool_rounds = args.max_rounds
    runtime.auto_continue = args.auto_continue
    if args.goal:
        runtime.goal = args.goal

    # Muss global gesetzt werden: der Session-Patch setzt eine leere Session
    # sonst mitten in process() auf "safe" zurueck - dann fehlen write_file
    # und execute_command, und der Agent kann nur lesen.
    tc._global_defaults["mode"] = args.mode

    chat_id = f"agent-{workdir.name}"
    session = runtime.get_session(chat_id)
    session.mode = args.mode
    session.think = True
    if args.model:
        session.model = args.model

    _log(workdir, f"Agent startet: Modell={session.model or '(Default)'} "
                  f"Modus={session.mode} auto_continue={runtime.auto_continue} "
                  f"max_rounds={runtime.max_tool_rounds}")
    _log(workdir, f"Auftrag: {len(auftrag)} Zeichen aus dem Arbeitsverzeichnis")

    t0 = time.time()
    try:
        antwort = asyncio.run(runtime.process(auftrag, chat_id))
    except KeyboardInterrupt:
        _log(workdir, "abgebrochen")
        return 130
    except Exception as e:
        import traceback
        _log(workdir, f"FEHLER: {e!r}")
        _log(workdir, traceback.format_exc())
        return 1

    _log(workdir, f"fertig nach {round(time.time() - t0)}s")
    try:
        (workdir / "agent_result.md").write_text(antwort or "(leer)", encoding="utf-8")
    except OSError:
        pass
    print(antwort or "(leer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
