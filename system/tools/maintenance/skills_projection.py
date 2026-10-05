#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: skills_projection
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version skills_projection

Description:
    Skills/Tools-Projektionsmodul (Task #1446): Projiziert alle Skills
    (skills-Tabelle), Tools (tools-Tabelle) und Handler
    (core/registry.HandlerRegistry, Auto-Discovery über hub/*.py) in ein
    JSON-Artefakt mit provenance-Kennzeichnung je Eintrag.

    Trigger-Provenienz: context_triggers (source='skill', agent_id='default').
    Die Spalte skills.trigger_phrases ist historisch leer (Datenleiche,
    durchgehend NULL) und wird bewusst NICHT gelesen.

    READ-ONLY-VERTRAG: Die Datenbank wird ausschließlich über eine
    sqlite3-URI mit mode=ro geöffnet und nur mit SELECT-Statements
    gelesen. In die BACH-DB wird nichts geschrieben. Einziger
    Schreibzugriff des Tools ist das Output-JSON.

Output-Schema:
    {
      "generated_at": "<ISO-8601 UTC>",
      "db_path": "<Pfad>",
      "counts": {"skills": n, "tools": n, "handlers": n},
      "skills":   [{"name", "type", "category", "version",
                    "trigger_phrases": [...], "provenance": "skills_db"}],
      "tools":    [{"name", "type", "category", "version",
                    "trigger_phrases": [], "provenance": "tools_db"}],
      "handlers": [{"name", "type": "handler", "category": "core",
                    "version", "trigger_phrases": [],
                    "provenance": "handler_registry"}],
      "warnings": [...]
    }

Usage:
    python skills_projection.py [--output PATH] [--db PATH] [--no-handlers] [--stats]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Kanonischer System-Root via Walkup (hub/bach_paths.py als Anker) --
# gleiche Import-Konvention wie tools/trigger_maintainer.py
_SYSTEM_ROOT = next(p for p in Path(__file__).resolve().parents
                    if (p / "hub" / "bach_paths.py").exists())
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB, DATA_DIR  # noqa: E402

PROVENANCE_SKILLS = "skills_db"
PROVENANCE_TOOLS = "tools_db"
PROVENANCE_HANDLERS = "handler_registry"
PROVENANCES = (PROVENANCE_SKILLS, PROVENANCE_TOOLS, PROVENANCE_HANDLERS)

DEFAULT_OUTPUT = DATA_DIR / "projections" / "skills_tools_projection.json"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Oeffnet die SQLite-DB strikt read-only (URI mode=ro, immutable=0)."""
    uri = f"file:{db_path}?mode=ro&immutable=0"
    return sqlite3.connect(uri, uri=True)


def _map_triggers(skill_names, trigger_rows):
    """Mappt context_triggers-Zeilen auf Skill-Namen.

    Primär exakt (trigger_phrase == skills.name), Fallback startswith/
    containment in beide Richtungen (nur bei eindeutigem Kandidaten).
    Nicht zuordenbare Trigger werden in warnings gemeldet.

    Returns:
        (mapping: dict name -> [trigger_phrases], warnings: list)
    """
    names = set(skill_names)
    mapping = {n: [] for n in skill_names}
    warnings = []
    for phrase, _status in trigger_rows:
        if not phrase:
            continue
        if phrase in names:
            mapping[phrase].append(phrase)
            continue
        candidates = [n for n in skill_names
                      if n.startswith(phrase) or phrase in n or n in phrase]
        if len(candidates) == 1:
            mapping[candidates[0]].append(phrase)
        else:
            warnings.append(f"trigger_unmatched:{phrase}")
    return mapping, warnings


def _project_handlers():
    """Projiziert Handler aus der HandlerRegistry (Discovery-Fehler tolerant).

    Handler haben keine DB-Zählparität und keine Trigger-Phrasen;
    Kategorie ist per Konvention 'core'.
    """
    warnings = []
    handlers = []
    try:
        from core.registry import HandlerRegistry
        registry = HandlerRegistry()
        registry.discover(_SYSTEM_ROOT / "hub")
        for name in sorted(getattr(registry, "_handlers", {})):
            handlers.append({
                "name": name,
                "type": "handler",
                "category": "core",
                "version": "1.0.0",
                "trigger_phrases": [],
                "provenance": PROVENANCE_HANDLERS,
            })
    except Exception as exc:  # Discovery darf nie hart fehlschlagen
        warnings.append(f"handler_discovery_failed:{exc}")
    return handlers, warnings


def build_projection(db_path=None, include_handlers: bool = True) -> dict:
    """Baut die komplette Skills/Tools/Handler-Projektion (read-only).

    Args:
        db_path: Optionaler DB-Pfad (default: hub.bach_paths.BACH_DB)
        include_handlers: HandlerRegistry-Projektion einschließen

    Returns:
        Projektions-dict gemäß Schema im Modul-Docstring.
    """
    db_path = Path(db_path) if db_path else Path(BACH_DB)
    warnings = []

    conn = _connect_readonly(db_path)
    try:
        skill_rows = conn.execute(
            "SELECT name, type, category, version FROM skills ORDER BY name"
        ).fetchall()
        tool_rows = conn.execute(
            "SELECT name, type, category, version FROM tools ORDER BY name"
        ).fetchall()
        trigger_rows = conn.execute(
            "SELECT trigger_phrase, status FROM context_triggers "
            "WHERE source = 'skill' AND agent_id = 'default'"
        ).fetchall()
    finally:
        conn.close()

    skill_names = [row[0] for row in skill_rows]
    trigger_map, trigger_warnings = _map_triggers(skill_names, trigger_rows)
    warnings.extend(trigger_warnings)

    skills = [{
        "name": name,
        "type": type_ or "",
        "category": category or "",
        "version": version or "",
        "trigger_phrases": list(dict.fromkeys(trigger_map.get(name, []))),
        "provenance": PROVENANCE_SKILLS,
    } for name, type_, category, version in skill_rows]

    tools = [{
        "name": name,
        "type": type_ or "",
        "category": category or "",
        "version": version or "",
        "trigger_phrases": [],
        "provenance": PROVENANCE_TOOLS,
    } for name, type_, category, version in tool_rows]

    handlers = []
    if include_handlers:
        handlers, handler_warnings = _project_handlers()
        warnings.extend(handler_warnings)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "counts": {
            "skills": len(skills),
            "tools": len(tools),
            "handlers": len(handlers),
        },
        "skills": skills,
        "tools": tools,
        "handlers": handlers,
        "warnings": warnings,
    }


def write_projection(output_path, data: dict) -> Path:
    """Schreibt das Projektions-JSON (einziger Schreibzugriff des Tools)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    output_path.write_text(payload + "\n", encoding="utf-8")
    return output_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Skills/Tools/Handler read-only in ein JSON projizieren.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Ziel-JSON (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--db", default=None,
                        help="Abweichender DB-Pfad (default: hub.bach_paths.BACH_DB)")
    parser.add_argument("--no-handlers", action="store_true",
                        help="Handler-Projektion überspringen")
    parser.add_argument("--stats", action="store_true",
                        help="Zählungen zusätzlich auf stdout ausgeben")
    args = parser.parse_args(argv)

    data = build_projection(db_path=args.db,
                            include_handlers=not args.no_handlers)
    out = write_projection(args.output, data)
    print(f"[OK] Projektion geschrieben: {out}")

    if args.stats:
        for key, value in data["counts"].items():
            print(f"  {key}: {value}")
        if data["warnings"]:
            print(f"  warnings: {len(data['warnings'])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
