# -*- coding: utf-8 -*-
"""Anbieterneutrale Startbefehle fuer BACH-Agenten.

Der Launcher startete bisher fest ``claude --model <m>``. Ein Agent war damit
zwangslaeufig ein Claude-Code-Prozess - obwohl weder die Persona noch die
Aufgabe das verlangt. Dieses Modul macht den Startbefehl zu einer Konfiguration.

Ohne eigene Konfiguration verhaelt sich alles wie bisher: der eingebaute
Runner ``claude`` erzeugt exakt den bisherigen Befehl.

Eigene Runner in ~/.config/bach/agent_runners.json:

    {
      "default": "claude",
      "runners": {
        "codex": {
          "match": ["gpt-*", "o3*"],
          "cmd": ["codex", "exec", "--model", "{model}"],
          "full_access": ["--sandbox", "danger-full-access"]
        }
      }
    }

Platzhalter in ``cmd``: {model}, {max_turns}, {allowed_tools}, {workdir}, {prompt_file}
Argumente mit unbelegtem Platzhalter fallen weg - so braucht nicht jeder
Runner jedes Feld zu kennen.
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.path.expanduser("~/.config/bach/agent_runners.json"))

#: Eingebaute Runner. `claude` bildet den bisherigen Befehl 1:1 ab - deshalb
#: aendert sich ohne Konfiguration nichts.
BUILTIN: dict[str, dict] = {
    "claude": {
        "match": ["claude-*", "claude", "opus*", "sonnet*", "haiku*", "fable*"],
        "cmd": ["claude", "--model", "{model}"],
        "max_turns": ["--max-turns", "{max_turns}"],
        "full_access": ["--dangerously-skip-permissions"],
        "restricted": ["--allowedTools", "{allowed_tools}"],
        "plan": ["--plan-mode", "plan"],
    },
    "codex": {
        "match": ["gpt-*", "o1*", "o3*", "codex*"],
        "cmd": ["codex", "exec", "--model", "{model}"],
        "full_access": ["--sandbox", "danger-full-access"],
        "restricted": ["--sandbox", "workspace-write"],
    },
    "agy": {
        "match": ["gemini-*", "agy*"],
        "cmd": ["agy", "--model", "{model}", "--add-dir", "{workdir}"],
        "full_access": ["--dangerously-skip-permissions"],
    },
    # Lokales Modell ueber BACHs eigene Chat-Runtime: derselbe Tool-Loop, den
    # auch der Telegram-Chat benutzt, nur als eigenstaendiger Agentenprozess.
    "local": {
        "match": ["qwen*", "gemma*", "llama*", "mistral*", "deepseek*", "*-mlx"],
        "cmd": ["{python}", "-m", "hub._services.chat.agent_runner",
                "--model", "{model}", "--workdir", "{workdir}"],
        "max_turns": ["--max-rounds", "{max_turns}"],
        "full_access": ["--mode", "full"],
        "restricted": ["--mode", "safe"],
    },
}


def _config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def runners() -> dict[str, dict]:
    """Eingebaute Runner, ueberschrieben von der Nutzerkonfiguration."""
    merged = {k: dict(v) for k, v in BUILTIN.items()}
    for name, spec in (_config().get("runners") or {}).items():
        if isinstance(spec, dict):
            merged.setdefault(name, {}).update(spec)
    return merged


def resolve(model: str, runner: str | None = None) -> tuple[str, dict]:
    """Welcher Runner startet dieses Modell?

    Ausdrueckliche Wahl schlaegt Muster, Muster schlagen den Default. Ist
    nichts passend, bleibt es beim bisherigen Verhalten (claude) - lieber
    der gewohnte Weg als ein Abbruch.
    """
    known = runners()
    if runner and runner in known:
        return runner, known[runner]

    modell = (model or "").lower()
    for name, spec in known.items():
        for muster in spec.get("match") or []:
            if fnmatch.fnmatch(modell, muster.lower()):
                return name, spec

    default = _config().get("default") or "claude"
    return default, known.get(default, BUILTIN["claude"])


def build_command(
    model: str,
    *,
    runner: str | None = None,
    permission_mode: str = "restricted",
    allowed_tools: str = "",
    max_turns: int | None = None,
    mode: str = "",
    workdir: str = "",
    python: str = "",
    prompt_file: str = "",
) -> tuple[str, list[str]]:
    """Baut den Startbefehl. Gibt (Runner-Name, Befehlsliste) zurueck."""
    name, spec = resolve(model, runner)

    werte = {
        "model": model or "",
        "allowed_tools": allowed_tools or "",
        "workdir": workdir or "",
        "python": python or "python3",
        "prompt_file": prompt_file or "",
        "max_turns": "" if max_turns is None else str(max_turns),
    }

    def fuellen(teile: list[str]) -> list[str]:
        raus = []
        for teil in teile:
            try:
                gefuellt = teil.format(**werte)
            except (KeyError, IndexError):
                continue
            # Ein Argument, dessen Platzhalter leer blieb, wird weggelassen -
            # sonst bekaeme der Prozess ein nacktes "--model" ohne Wert.
            if "{" in teil and not gefuellt.strip():
                continue
            raus.append(gefuellt)
        return raus

    cmd = fuellen(spec.get("cmd") or BUILTIN["claude"]["cmd"])

    if max_turns is not None and spec.get("max_turns"):
        cmd.extend(fuellen(spec["max_turns"]))

    if permission_mode == "full":
        cmd.extend(fuellen(spec.get("full_access") or []))
    elif spec.get("restricted"):
        cmd.extend(fuellen(spec["restricted"]))

    if mode == "plan" and spec.get("plan"):
        cmd.extend(fuellen(spec["plan"]))

    return name, cmd


def available() -> dict[str, bool]:
    """Welche Runner sind auf diesem Rechner tatsaechlich startbar?"""
    import shutil

    raus = {}
    for name, spec in runners().items():
        erstes = (spec.get("cmd") or [""])[0]
        if erstes.startswith("{"):
            raus[name] = True          # Interpreter wird zur Laufzeit gesetzt
        else:
            raus[name] = bool(shutil.which(erstes))
    return raus
