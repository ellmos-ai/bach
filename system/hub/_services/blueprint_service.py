# SPDX-License-Identifier: MIT
"""Blueprint- und Fabrika-Service fuer BACH und Ocean.

Erfuellt GUX-020..029:
- GUX-020: Schritt 1 startet beim Standard-Systemprompt.
- GUX-021: Schritt 1 kann fertige Rollen und Personas auswaehlen.
- GUX-022: Schritt 2 zeigt echte Skills/Tools aus einer Capability-Quelle.
- GUX-023: Schritt 3 enthaelt Contractus-, Arbeitsmodus- und Ausloeser-Vorlagen.
- GUX-024: Blueprints-Unterseite (/agenten/blueprints) als Vorlagenkatalog.
- GUX-025: Blueprints koennen Agenten, Rollen, Skills, Workflows, Services und Contractus beschreiben.
- GUX-026: Blueprints und Vorlagen sind in den Schritten 1-3 auswaehlbar.
- GUX-027: Blueprint-Materialisierung ist Living (nicht Running); Start liefert echten Jobbeleg.
- GUX-028: Schritt 4 bindet echte Profile, Whitelist, Hooker-Audit, Pull und Injection an.
- GUX-029: Startprompt-Synthese; leere Stubs melden fail-closed Fehler.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
ALLOWED_KINDS = {"agent", "role", "skill", "workflow", "service", "contractus"}
VALID_BLUEPRINT_KINDS = ALLOWED_KINDS

CONTRACTUS_PROJECTION_VERSION = "bach.contractus-projection.v1"
CONTRACTUS_MODES = frozenset({"casualis", "usus", "impetus_causa", "impetus_temporal"})
CONTRACTUS_ANIMUS_TYPES = frozenset({"api", "cli", "subscription", "local"})
CONTRACTUS_TASK_TYPES = frozenset({
    "allround", "architecture", "audit", "chat", "code", "compliance",
    "hygiene", "maintenance", "recherche", "routine", "routing", "triage",
})
CONTRACTUS_WAKE_BEHAVIORS = frozenset({"always_on", "idle_wake", "manual"})
CONTRACTUS_METADATA_FIELDS = frozenset({"id", "title", "description"})
CONTRACTUS_FIELDS = CONTRACTUS_METADATA_FIELDS | frozenset({
    "turns", "max_turns", "cooldown", "cooldown_seconds", "task_type",
    "task_types", "modus", "wake", "wake_behavior", "animus_type",
})


def _contractus_depth(value: Any, depth: int = 0) -> None:
    if depth > 8:
        raise ValueError("contractus_depth_limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Contractus-Feldname muss Text sein")
            _contractus_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _contractus_depth(item, depth + 1)


def _contractus_alias(values: dict[str, Any], canonical: str, alias: str) -> Any:
    has_canonical = canonical in values
    has_alias = alias in values
    if ((has_canonical and values[canonical] is None)
            or (has_alias and values[alias] is None)):
        raise ValueError("contractus_null_not_allowed")
    if has_canonical and has_alias:
        left, right = values[canonical], values[alias]
        if type(left) is not type(right) or left != right:
            raise ValueError(f"contractus_alias_conflict: {canonical}/{alias}")
        return left
    if has_canonical:
        return values[canonical]
    if has_alias:
        return values[alias]
    return None


def project_contractus(
    value: Any,
    *,
    modus: Any = None,
    animus_type: Any = None,
) -> tuple[dict[str, Any], str, str, dict[str, str]]:
    """Validate native preset/seed variants and return their typed projection.

    The projection is declarative metadata only. Nested execution settings
    remain a separate controller contract and are deliberately not projected.
    """
    if not isinstance(value, dict):
        raise TypeError("Contractus muss eine Zuordnung sein")
    if any(not isinstance(key, str) for key in value):
        raise ValueError("Ungültige Contractus-Zuordnung")
    _contractus_depth(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Contractus-Quelle ist nicht sicher serialisierbar") from None
    if len(encoded) > 32 * 1024:
        raise ValueError("contractus_size_limit")
    if "execution" in value:
        raise ValueError("contractus_execution_not_projected")
    unknown = set(value) - CONTRACTUS_FIELDS
    if unknown:
        raise ValueError("Nicht unterstützte Contractus-Felder")

    preset_metadata: dict[str, str] = {}
    if "id" in value:
        preset_id = value["id"]
        if not isinstance(preset_id, str) or not _ID.fullmatch(preset_id):
            raise ValueError("Contractus-Preset-ID ist ungültig")
        preset_metadata["id"] = preset_id
    for key, limit in (("title", 120), ("description", 2_000)):
        if key in value:
            item = value[key]
            if (not isinstance(item, str) or any(ord(char) < 32 for char in item)
                    or len(item) > limit or not item.strip()):
                raise ValueError(f"Contractus-Preset-{key} ist ungültig")
            preset_metadata[key] = item.strip()

    contractus_values = {
        key: item for key, item in value.items()
        if key not in CONTRACTUS_METADATA_FIELDS
    }
    turns = _contractus_alias(contractus_values, "turns", "max_turns")
    cooldown = _contractus_alias(contractus_values, "cooldown_seconds", "cooldown")
    wake = _contractus_alias(contractus_values, "wake_behavior", "wake")
    for label, item in (("turns", turns), ("cooldown", cooldown)):
        if item is not None and (type(item) is not int or item < 0 or item > 100_000):
            raise ValueError(f"Contractus-{label} muss eine begrenzte Ganzzahl sein")

    normalized: dict[str, Any] = {}
    if turns is not None:
        normalized["turns"] = turns
    if cooldown is not None:
        normalized["cooldown_seconds"] = cooldown
    if "task_type" in contractus_values:
        task_type = contractus_values["task_type"]
        if not isinstance(task_type, str) or task_type not in CONTRACTUS_TASK_TYPES:
            raise ValueError("Contractus-Aufgabentyp ist ungültig")
        normalized["task_type"] = task_type
    if "task_types" in contractus_values:
        task_types = contractus_values["task_types"]
        if (not isinstance(task_types, list) or len(task_types) > 32
                or any(not isinstance(item, str) or item not in CONTRACTUS_TASK_TYPES
                       for item in task_types)
                or len(set(task_types)) != len(task_types)):
            raise ValueError("Contractus-Aufgabentyp-Liste ist ungültig")
        normalized["task_types"] = list(task_types)
    if wake is not None:
        if not isinstance(wake, str) or wake not in CONTRACTUS_WAKE_BEHAVIORS:
            raise ValueError("Contractus-Weckverhalten ist ungültig")
        normalized["wake_behavior"] = wake

    if "modus" in contractus_values:
        nested_modus = contractus_values["modus"]
        if nested_modus is None:
            raise ValueError("contractus_null_not_allowed")
        if not isinstance(nested_modus, str) or nested_modus not in CONTRACTUS_MODES:
            raise ValueError("Contractus-Arbeitsmodus ist ungültig")
        if modus is not None and nested_modus != modus:
            raise ValueError("contractus_alias_conflict: modus")
        modus = nested_modus
    if modus is None:
        modus = "casualis"
    if not isinstance(modus, str) or modus not in CONTRACTUS_MODES:
        raise ValueError("Blueprint-Arbeitsmodus ist ungültig")

    if "animus_type" in contractus_values:
        nested_animus = contractus_values["animus_type"]
        if nested_animus is None:
            raise ValueError("contractus_null_not_allowed")
        if not isinstance(nested_animus, str) or nested_animus not in CONTRACTUS_ANIMUS_TYPES:
            raise ValueError("Contractus-Animus-Typ ist ungültig")
        if animus_type is not None and nested_animus != animus_type:
            raise ValueError("contractus_alias_conflict: animus_type")
        animus_type = nested_animus
    if animus_type is None:
        animus_type = "subscription"
    if not isinstance(animus_type, str) or animus_type not in CONTRACTUS_ANIMUS_TYPES:
        raise ValueError("Blueprint-Animus-Typ ist ungültig")

    return normalized, modus, animus_type, preset_metadata

# Standard-Pfade fuer Skills
SKILLS_SEARCH_PATHS = [
    Path("C:/Users/User/OneDrive/.TOPICS/.AI/.SKILLS/skills"),
    Path(os.path.expanduser("~/OneDrive/.TOPICS/.AI/.SKILLS/skills")),
    Path("C:/Users/User/.agents/skills"),
    Path(os.path.expanduser("~/.agents/skills")),
]

FALLBACK_CORE_SKILLS = [
    {"id": "git-hygiene", "name": "Git Hygiene", "category": "dev", "role": "Fail-Closed Git & Branch Management", "version": "v1.2.0"},
    {"id": "lock-master", "name": "Lock Master", "category": "infrastructure", "role": "Verzeichnis- & Dateisperren-Auditor (P-004)", "version": "v2.0.1"},
    {"id": "pipeline-optimizer", "name": "Pipeline Optimizer", "category": "dev", "role": "6-Schritte Refactoring & Sanierung", "version": "v1.4.0"},
    {"id": "brainstorm", "name": "Brainstorm", "category": "utilities", "role": "Kreativitaetstechniken (SCAMPER, TRIZ)", "version": "v1.0.0"},
    {"id": "decide", "name": "Decide", "category": "utilities", "role": "Entscheidungsmatrizen & Scoring", "version": "v1.0.0"},
    {"id": "bugfix-protocol", "name": "Bugfix Protokoll", "category": "dev", "role": "Systematisches 6-Phasen Debugging", "version": "v1.1.0"},
    {"id": "system-auditor", "name": "System Auditor", "category": "infrastructure", "role": "Integritaets- und Hygiene-Pruefung", "version": "v1.0.0"},
    {"id": "backup", "name": "Backup", "category": "infrastructure", "role": "Fail-closed Snapshot & Mirror", "version": "v1.0.0"},
    {"id": "sync", "name": "Sync", "category": "infrastructure", "role": "Cross-Host Transfer & Inventur", "version": "v2.0.0"},
    {"id": "model-strategy", "name": "Model Strategy", "category": "infrastructure", "role": "Multi-Modell Orchestrierung & Fallbacks", "version": "v1.0.0"},
    {"id": "orchestrator", "name": "Orchestrator", "category": "infrastructure", "role": "Aufgabenzerlegung & Worker-Delegation", "version": "v1.0.0"},
    {"id": "schwarm-operationen", "name": "Schwarm Operationen", "category": "infrastructure", "role": "Multi-Agenten Koordination & Stigmergy", "version": "v1.0.0"},
    {"id": "document-chunker", "name": "Document Chunker", "category": "utilities", "role": "Token-Ueberlappendes Chunking fuer RAG", "version": "v1.0.0"},
    {"id": "gardener-search", "name": "Gardener Search", "category": "research", "role": "FTS5 Wissens- und Notizrecherche", "version": "v1.0.0"},
    {"id": "literature-search-arxiv", "name": "ArXiv Search", "category": "research", "role": "Wissenschaftliche Literatur-Recherche", "version": "v1.0.0"},
]

CONTRACTUS_PRESETS = [
    {
        "id": "standard_casualis",
        "title": "Standard-Casualis (Einzelfall & Ad-hoc)",
        "description": "Fuer typische Aufgaben: Max. 15 Turns, 30s Cooldown, weckt aus Idle auf.",
        "turns": 15,
        "cooldown_seconds": 30,
        "task_type": "allround",
        "modus": "casualis",
        "wake_behavior": "idle_wake",
        "animus_type": "subscription",
    },
    {
        "id": "dauerlaeufer_usus",
        "title": "Dauerläufer / Usus (Hintergrund-Wartung)",
        "description": "Fuer periodische Hygiene und Systemroutinen: Max. 50 Turns, 10s Cooldown, Always-On.",
        "turns": 50,
        "cooldown_seconds": 10,
        "task_type": "routine",
        "modus": "usus",
        "wake_behavior": "always_on",
        "animus_type": "cli",
    },
    {
        "id": "reaktiver_impetus_causa",
        "title": "Reaktiver Causa-Worker (Ereignis-/Trigger-getrieben)",
        "description": "Startet bei spezifischen Events (Git Commit, Hook, Ticket-Eingang): Max. 20 Turns, 60s Cooldown.",
        "turns": 20,
        "cooldown_seconds": 60,
        "task_type": "triage",
        "modus": "impetus_causa",
        "wake_behavior": "idle_wake",
        "animus_type": "api",
    },
    {
        "id": "forschung_analyse",
        "title": "Forschungs- und Literatur-Review",
        "description": "Akademische Recherche und Synthese: Max. 25 Turns, 45s Cooldown, manueller Start.",
        "turns": 25,
        "cooldown_seconds": 45,
        "task_type": "recherche",
        "modus": "casualis",
        "wake_behavior": "manual",
        "animus_type": "subscription",
    },
    {
        "id": "strict_zero_leak",
        "title": "Strict Zero-Leak Gatekeeper (Audit & Governance)",
        "description": "Audit und Sicherheitspruefungen ohne Schreibrechte: Max. 10 Turns, 120s Cooldown, Intervall.",
        "turns": 10,
        "cooldown_seconds": 120,
        "task_type": "audit",
        "modus": "impetus_temporal",
        "wake_behavior": "manual",
        "animus_type": "cli",
    },
]


def ensure_blueprint_schema(conn: sqlite3.Connection) -> None:
    """Stellt sicher, dass das Schema fuer Blueprints alle Spalten besitzt."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_blueprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            title TEXT,
            description TEXT,
            persona_role TEXT,
            persona_prompt TEXT,
            skills_json TEXT DEFAULT '[]',
            animus_type TEXT DEFAULT 'subscription',
            contractus_json TEXT DEFAULT '{}',
            modus TEXT DEFAULT 'casualis',
            is_template INTEGER DEFAULT 0,
            is_materialized INTEGER DEFAULT 0,
            governance_json TEXT DEFAULT '{}',
            kind TEXT DEFAULT 'agent',
            start_prompt TEXT DEFAULT '',
            version INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Additive Spaltenmigrationen
    for col, col_type in [
        ("governance_json", "TEXT DEFAULT '{}'"),
        ("kind", "TEXT DEFAULT 'agent'"),
        ("start_prompt", "TEXT DEFAULT ''"),
        ("version", "INTEGER DEFAULT 1"),
        # Paketgelieferte Systemvorlagen (template_provider_service); NULL = BACH-eigene Zeile.
        ("provider", "TEXT"),
        ("provider_template_id", "TEXT"),
        ("provider_version", "TEXT"),
        ("template_sha256", "TEXT"),
        ("template_status", "TEXT"),
        ("template_status_reason", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE agent_blueprints ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_blueprints_provider_template
        ON agent_blueprints(provider, provider_template_id, provider_version)
        WHERE provider IS NOT NULL
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS partner_presence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_name TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'offline',
            clocked_in TEXT,
            last_heartbeat TEXT,
            current_task TEXT,
            session_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def seed_default_blueprints(conn: sqlite3.Connection) -> None:
    """Befuellt Core-Vorlagen fuer alle Kinds (GUX-015, GUX-023, GUX-025)."""
    ensure_blueprint_schema(conn)
    now = datetime.now(timezone.utc).isoformat()
    seeds = [
        # AGENTS (GUX-015)
        (
            "buddha",
            "Buddha (Allround & Triage Master)",
            "Zentrales Empfangs- und Routing-Modell fuer Aufgaben, Ticketaufnahme und Klientengespraeche.",
            "Allrounder, Routing-Ticket-Master, Assistent",
            "Du bist Buddha, der einfuehlsame, strukturierte Erstkontakt und Ticket-Master im System.",
            json.dumps(["gespraechsfuehrung-basis", "selbstmanagement", "decide"]),
            "subscription",
            json.dumps({"max_turns": 30, "cooldown_seconds": 0, "task_types": ["chat", "routing", "triage"]}),
            "casualis",
            1, 1, json.dumps({"profile": "fail_closed_standard", "tool_whitelist": ["read_files", "search_content"]}),
            "agent", "", 1, now, now
        ),
        (
            "wartungsagent",
            "Wartungs-Agent (Routinen & Hygiene)",
            "Autonome periodische System-Wartung, Log-Rotation, Integritaets- und Hygiene-Checks.",
            "System-Administrator, Hygiene- und Wartungsexperte",
            "Du bist der Wartungsagent. Pruefe Logs, sichere Dateizustaende und melde Fehler praezise.",
            json.dumps(["system-auditor", "backup", "sync", "lock-master"]),
            "cli",
            json.dumps({"max_turns": 10, "cooldown_seconds": 3600, "task_types": ["maintenance", "hygiene"]}),
            "usus",
            1, 1, json.dumps({"profile": "fail_closed_standard", "tool_whitelist": ["read_files", "write_files", "execute_command"]}),
            "agent", "", 1, now, now
        ),
        (
            "ati_architect",
            "Ati (Senior Software-Architekt)",
            "Software-Design, TDD-Implementierung, Code-Reviews und Architektur-Einhaltung.",
            "Software-Architekt & Core-Entwickler",
            "Du bist Ati, der leitende Software-Architekt in BACH. Arbeite testgetrieben und halte Konventionen strikt ein.",
            json.dumps(["pipeline-optimizer", "git-hygiene", "bugfix-protocol"]),
            "cli",
            json.dumps({"max_turns": 25, "cooldown_seconds": 30, "task_types": ["code", "architecture"]}),
            "casualis",
            1, 1, json.dumps({"profile": "full_dev_guarded", "tool_whitelist": ["read_files", "write_files", "execute_command", "run_tests"]}),
            "agent", "", 1, now, now
        ),
        (
            "claude_avatar",
            "Claude Code (CLI Coding Agent)",
            "Repraesentiert die lokale Claude Code CLI Session als steuerbaren Avatar im Taskboard.",
            "Terminal Coding Agent",
            "Verarbeitet komplexe Coding- und Architekturaufgaben im Terminal.",
            json.dumps(["dev-zyklus", "bugfix-protokoll", "git-hygiene"]),
            "subscription",
            json.dumps({"max_turns": 20, "cooldown_seconds": 30, "task_types": ["code"]}),
            "casualis",
            1, 1, json.dumps({"profile": "full_dev_guarded", "tool_whitelist": ["read_files", "write_files", "execute_command"]}),
            "agent", "", 1, now, now
        ),
        # ROLES (GUX-015, GUX-021, GUX-025)
        (
            "role_lawchecker",
            "Law-Checker (Recht & Datenschutz)",
            "Prueft Lizenz-Compliance, Datenschutzvorgaben (DSGVO) und Governance-Richtlinien.",
            "Rechts- und Datenschutz-Auditor",
            "Du bist der Law-Checker. Pruefe Source-Dateien auf Lizenzkonformitaet, PII-Freiheit und Sicherheits-Lecks.",
            json.dumps(["lock-master", "system-auditor"]),
            "api",
            json.dumps({"max_turns": 15, "cooldown_seconds": 60, "task_types": ["audit", "compliance"]}),
            "impetus_causa",
            1, 0, json.dumps({"profile": "read_only_research", "tool_whitelist": ["read_files", "search_content"]}),
            "role", "", 1, now, now
        ),
        (
            "role_security_auditor",
            "Security Auditor (Fail-Closed Gatekeeper)",
            "Ueberwacht Lock-System, Git-Pushes und verhindert unberechtigte Remote-Modifikationen.",
            "Sicherheits- und Gatekeeper-Auditor",
            "Du ueberwachst strikt die Einhaltung von P-001, P-002 und P-004.",
            json.dumps(["lock-master", "system-auditor"]),
            "cli",
            json.dumps({"max_turns": 10, "cooldown_seconds": 120, "task_types": ["audit"]}),
            "impetus_temporal",
            1, 0, json.dumps({"profile": "fail_closed_standard", "tool_whitelist": ["read_files"]}),
            "role", "", 1, now, now
        ),
        # WORKFLOWS & SERVICES (GUX-025)
        (
            "workflow_dev_cycle",
            "8-Phasen Entwicklungszyklus",
            "Strukturierter Ablauf von Feature-Wunsch, Ist-Stand, Planung bis hin zu Backend, Frontend und Tests.",
            "Workflow-Vorlage",
            "Fuehre systematisch durch die 8 Phasen der Feature-Entwicklung.",
            json.dumps(["dev-zyklus", "bugfix-protokoll", "pipeline-optimizer"]),
            "cli",
            json.dumps({"max_turns": 40, "cooldown_seconds": 15, "task_types": ["code"]}),
            "casualis",
            1, 0, json.dumps({"profile": "full_dev_guarded"}),
            "workflow", "", 1, now, now
        ),
        (
            "service_cluster_sync",
            "Cluster-Sync & Replikation",
            "Haelt Mac Studio und Laptop Datenbestaende synchron ueber Tailscale.",
            "Hintergrund-Service",
            "Synchronisiere Repositories, Datenbanken und Regelwerke zwischen Cluster-Knoten.",
            json.dumps(["sync", "backup"]),
            "cli",
            json.dumps({"max_turns": 10, "cooldown_seconds": 600, "task_types": ["routine"]}),
            "usus",
            1, 0, json.dumps({"profile": "fail_closed_standard"}),
            "service", "", 1, now, now
        ),
        # CONTRACTUS (GUX-023, GUX-025)
        (
            "contractus_standard",
            "Standard-Contractus (Casualis)",
            "Universal-Vertrag fuer interaktive und task-gesteuerte Einzelagenten.",
            "Contractus-Vorlage",
            "Arbeitsvertrag: Max. 15 Turns, 30s Cooldown, Idle-Wake.",
            json.dumps([]),
            "subscription",
            json.dumps({"turns": 15, "cooldown": 30, "task_type": "allround", "modus": "casualis", "wake": "idle_wake"}),
            "casualis",
            1, 0, json.dumps({"profile": "fail_closed_standard"}),
            "contractus", "", 1, now, now
        ),
        (
            "contractus_strict_zero_leak",
            "Strict Zero-Leak Contractus",
            "Restriktiver Vertrag fuer vertrauliche Analysen und Audit-Routinen ohne Netz und Push.",
            "Contractus-Vorlage",
            "Arbeitsvertrag: Max. 10 Turns, 120s Cooldown, Manual-Start, Read-Only.",
            json.dumps([]),
            "cli",
            json.dumps({"turns": 10, "cooldown": 120, "task_type": "audit", "modus": "impetus_temporal", "wake": "manual"}),
            "impetus_temporal",
            1, 0, json.dumps({"profile": "read_only_research"}),
            "contractus", "", 1, now, now
        ),
    ]

    from .chat.slots_config import DEFAULT_ROLE_PROMPTS
    for role, title in (("personal-assistant", "Persönlicher Assistent"),
                        ("boss_routing", "Boss · Koordination"),
                        ("task-divider", "Boss · Aufgabenzerlegung"),
                        ("ticket-master", "Boss · Triage"),
                        ("entwickler", "Experte · Entwicklung"),
                        ("recherche", "Experte · Recherche")):
        seeds.append(("template_" + role.replace("-", "_"), title,
            "Instanz aus einer vorhandenen BACH-Rolle erstellen.",
            role, DEFAULT_ROLE_PROMPTS[role], "[]", "api",
            json.dumps({"turns": 20, "cooldown_seconds": 30}), "casualis",
            1, 0, json.dumps({"profile": "fail_closed_standard"}),
            "agent", "", 1, now, now))

    conn.executemany("""
        INSERT OR IGNORE INTO agent_blueprints (
            name, title, description, persona_role, persona_prompt,
            skills_json, animus_type, contractus_json, modus,
            is_template, is_materialized, governance_json,
            kind, start_prompt, version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, seeds)
    conn.commit()


def get_available_skills(
    skills_root: Path | None = None,
    category: str | None = None,
    search: str | None = None,
    requested_locale: str | None = None,
) -> list[dict[str, Any]]:
    """Liest echte Skills aus dem Dateisystem oder liefert Core-Skills (GUX-022)."""
    from .skill_source_service import resolve_requested_locale, source_catalog, skill_roots, user_skills_root
    requested = resolve_requested_locale(requested_locale)
    roots = [user_skills_root(), skills_root] if skills_root else skill_roots()
    catalog = source_catalog(roots, requested_locale=requested)
    skills_map = {key: {k: v for k, v in item.items() if k not in {"path", "root"}}
                  for key, item in catalog.items()}
    for item in FALLBACK_CORE_SKILLS:
        if item["id"] not in skills_map:
            skills_map[item["id"]] = {
                **item, "canonical_skill_id": item["id"], "locale": "en",
                "requested_locale": requested, "resolved_locale": "en",
                "fallback_used": requested != "en",
                "evidence_type": "core_declared", "source_version": None,
            }
    result = list(skills_map.values())
    if category:
        result = [s for s in result if s.get("category") == category]
    if search:
        q = search.lower()
        result = [s for s in result if q in s["id"].lower() or q in s["name"].lower()
                  or q in s.get("role", "").lower()]
    return sorted(result, key=lambda item: (item.get("category", ""), item["id"]))


def synthesize_start_prompt(blueprint: dict[str, Any], task_override: str | None = None) -> str:
    """Synthetisiert einen echten, validierten Startprompt gemaess GUX-029."""
    name = (blueprint.get("name") or "").strip()
    title = (blueprint.get("title") or name).strip()
    role = (blueprint.get("persona_role") or "Agent").strip()
    persona = (blueprint.get("persona_prompt") or "").strip()
    skills = blueprint.get("skills", [])
    contractus = blueprint.get("contractus", {})
    governance = blueprint.get("governance", {})
    modus = blueprint.get("modus", "casualis")

    # GUX-029: Leere / Static Stubs duerfen keinen Erfolg melden
    if not name or len(name) < 2:
        raise ValueError("Name des Blueprints fehlt oder ist ungueltig (mind. 2 Zeichen)")
    if not persona:
        raise ValueError("Persona-Prompt darf nicht leer sein (GUX-029)")

    skills_str = ", ".join(skills) if skills else "Keine spezifischen Zusatzskills zugewiesen (Basis-Capabilities aktiv)"
    turns = contractus.get("turns", contractus.get("max_turns", 15))
    cooldown = contractus.get("cooldown", contractus.get("cooldown_seconds", 30))
    gov_profile = governance.get("profile", "fail_closed_standard")
    tool_whitelist = ", ".join(governance.get("tool_whitelist", ["read_files", "search_content", "directory_list"]))

    task_desc = task_override or f"Arbeite im Modus '{modus}'. Bearbeite anstehende Tasks aus der Lead-TaskDB gemaess Rollenspezifikation."

    prompt = f"""# STARTPROMPT: {title} ({name})

## [Boot:Agent]
- Rolle: {role}
- Persönlichkeit & Identität: {persona}
- Zugewiesene Fähigkeiten (Skills): {skills_str}
- Arbeitsmodus: {modus} (Max. {turns} Turns, {cooldown}s Cooldown)
- Animus-Typ: {blueprint.get('animus_type', 'subscription')}

## [Boot:System]
- Sicherheitsleitplanken & Governance: P-001 (Fail-Closed No Direct Main Push), P-002 (Zwei-Bäume-Regel), P-004 (Lock-Master)
- Governance-Profil: {gov_profile}
- Tool-Whitelist: {tool_whitelist}
- Kommunikationsregel: Vor Änderungen die aktuellen Repository-Regeln und Locks prüfen.
- Ausführungsnachweis: Ein Workerstart zählt erst mit dem korrelierten Beleg des Controllers. Hooker-Audits werden hier nicht bestätigt.

## [Boot:Aufgabe]
{task_desc}
"""
    return prompt.strip()


def list_blueprints(
    conn: sqlite3.Connection,
    kind: str | None = None,
    search: str | None = None,
    is_template: int | None = None
) -> dict[str, Any]:
    """Listet Schablonen und Blueprints gefiltert nach Kind und Suchbegriff (GUX-024, GUX-025)."""
    from .governance_binding import blueprint_sha256
    ensure_blueprint_schema(conn)
    seed_default_blueprints(conn)

    query = "SELECT * FROM agent_blueprints WHERE 1=1"
    params: list[Any] = []

    if kind:
        query += " AND kind = ?"
        params.append(kind)
    if is_template is not None:
        query += " AND is_template = ?"
        params.append(int(is_template))

    query += " ORDER BY is_template DESC, name ASC"
    rows = conn.execute(query, params).fetchall()

    templates = []
    blueprints = []

    for r in rows:
        item = dict(r)
        try:
            item["skills"] = json.loads(item["skills_json"])
        except (ValueError, TypeError):
            item["skills"] = []
        try:
            item["contractus"] = json.loads(item["contractus_json"])
        except (ValueError, TypeError):
            item["contractus"] = {}
        try:
            item["governance"] = json.loads(item.get("governance_json") or "{}")
        except (ValueError, TypeError):
            item["governance"] = {}
        try:  # Pin-Wert für governance.inherits_from (P05 3b)
            item["content_sha256"] = blueprint_sha256(dict(r))
        except (ValueError, TypeError):
            item["content_sha256"] = None

        if not item.get("kind"):
            item["kind"] = "agent"

        # Startprompt sicherstellen
        if not item.get("start_prompt") and (item.get("persona_prompt") or item.get("persona_role")):
            try:
                item["start_prompt"] = synthesize_start_prompt(item)
            except (ValueError, KeyError):
                item["start_prompt"] = ""

        # Suche anwenden falls angegeben
        if search:
            q = search.lower()
            text = f"{item['name']} {item.get('title','')} {item.get('description','')} {item.get('persona_role','')} {' '.join(item['skills'])}".lower()
            if q not in text:
                continue

        if item.get("is_template"):
            templates.append(item)
        else:
            blueprints.append(item)

    return {
        "templates": templates,
        "blueprints": blueprints,
        "total_templates": len(templates),
        "total_blueprints": len(blueprints),
        "total": len(templates) + len(blueprints)
    }


def validate_blueprint_fields(title, desc, persona_role, persona_prompt, animus, modus,
                              skills, contractus, governance) -> None:
    """Feldprüfung für Nutzer-Saves und paketgelieferte Systemvorlagen."""
    if any(not isinstance(text, str) or len(text) > 20000 or "\x00" in text
           for text in (title, desc, persona_role, persona_prompt)):
        raise ValueError("Blueprint enthält ungültigen Text")
    if (len(title) > 120 or not isinstance(animus, str) or animus not in {"api", "cli", "subscription", "local"}
            or not isinstance(modus, str) or modus not in {"casualis", "usus", "impetus_temporal", "impetus_causa"}):
        raise ValueError("Blueprint-Titel oder Arbeitsmodus ist ungültig")
    if (not isinstance(skills, list) or len(skills) > 100
            or any(not isinstance(skill, str) or not _ID.fullmatch(skill) for skill in skills)
            or not isinstance(contractus, dict) or not isinstance(governance, dict)
            or len(json.dumps([contractus, governance])) > 300000):
        raise ValueError("Blueprint-Konfiguration ist ungültig")


def save_blueprint(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Erstellt oder aktualisiert einen Blueprint mit Validierung (GUX-025, GUX-029)."""
    ensure_blueprint_schema(conn)

    if not isinstance(payload.get("name"), str):
        raise ValueError("Blueprint-Name muss Text sein")
    name = payload["name"].strip().lower()
    if not name or not _ID.fullmatch(name):
        raise ValueError("Ungültiger oder fehlender Blueprint-Name (nur Alphanumerik, .-_)")

    kind = payload.get("kind", "agent")
    if not isinstance(kind, str) or kind not in ALLOWED_KINDS:
        raise ValueError(f"Ungültiger Kind '{kind}'. Erlaubt: {', '.join(sorted(ALLOWED_KINDS))}")

    title = payload.get("title") or name.replace("-", " ").title()
    desc = payload.get("description", "")
    persona_role = payload.get("persona_role", "")
    persona_prompt = payload.get("persona_prompt", "")
    skills = payload.get("skills", [])
    animus = payload.get("animus_type", "subscription")
    contractus = payload.get("contractus", {})
    modus = payload.get("modus", "casualis")
    governance = payload.get("governance", {})
    if payload.get("is_template", 0) not in (0, False):
        raise PermissionError("Systemvorlagen werden ausschließlich bei der Initialisierung angelegt")
    is_template = 0

    # GUX-029: Static/leere Stubs duerfen keinen Erfolg melden
    if not persona_prompt and not persona_role and kind in {"agent", "role"}:
        raise ValueError("Blueprint unvollstaendig: Weder Persona-Prompt noch Persona-Rolle angegeben.")

    if isinstance(contractus, dict) and "execution" in contractus:
        execution = contractus["execution"]
        if not isinstance(execution, dict):
            raise ValueError("Blueprint-Ausführungskonfiguration ist ungültig")
        from .chat.slots_config import validate_agent_avatar
        from .display_assets import validate_symbol
        if "avatar" in execution:
            validate_agent_avatar(execution["avatar"])
        if "symbol" in execution:
            validate_symbol(execution["symbol"])

    if isinstance(governance, dict):
        # P05 3b: Pins exakt auflösen, bevor die Schreibsperre genommen wird (Registry-Lesen kann dauern).
        from .governance_binding import resolve
        own = conn.execute("SELECT id FROM agent_blueprints WHERE name = ?", (name,)).fetchone()
        resolve(conn, governance, blueprint_id=own[0] if own else None)

    # Serialize the revision check with its write across SQLite writers.
    conn.execute("BEGIN IMMEDIATE")
    existing = conn.execute("SELECT id, is_template, version, governance_json FROM agent_blueprints WHERE name = ?",
                            (name,)).fetchone()
    if existing:
        is_tmpl = existing[1] if isinstance(existing, tuple) else existing["is_template"]
        if is_tmpl == 1:
            conn.rollback()
            raise PermissionError(f"Vorlage '{name}' ist schreibgeschützt (GUX-026). Bitte wähle einen eigenen Namen.")

    if is_template:
        conn.rollback()
        raise PermissionError("Systemvorlagen werden ausschließlich bei der Initialisierung angelegt")
    curr_version = (existing[2] if isinstance(existing, tuple) else existing["version"]) if existing else 0
    if type(payload.get("expected_version", 0)) is not int or payload.get("expected_version", 0) != curr_version:
        conn.rollback()
        raise RuntimeError("blueprint_version_conflict")
    try:
        validate_blueprint_fields(title, desc, persona_role, persona_prompt, animus, modus,
                                  skills, contractus, governance)
    except ValueError:
        conn.rollback()
        raise
    version = (curr_version + 1) if curr_version else 1
    now = datetime.now(timezone.utc).isoformat()
    from .governance_binding import with_pin_log
    previous = {}
    if existing:
        try:
            previous = json.loads((existing[3] if isinstance(existing, tuple) else existing["governance_json"]) or "{}")
        except ValueError:
            pass
    governance = with_pin_log(previous if isinstance(previous, dict) else {}, governance,
                              blueprint_version=version)

    # Startprompt erzeugen
    item_for_prompt = {
        "name": name,
        "title": title,
        "persona_role": persona_role,
        "persona_prompt": persona_prompt,
        "skills": skills,
        "contractus": contractus,
        "governance": governance,
        "modus": modus,
        "animus_type": animus,
    }
    try:
        start_prompt = synthesize_start_prompt(item_for_prompt)
    except (ValueError, KeyError):
        start_prompt = payload.get("start_prompt", "")

    conn.execute("""
        INSERT INTO agent_blueprints (
            name, title, description, persona_role, persona_prompt,
            skills_json, animus_type, contractus_json, modus, is_template,
            governance_json, kind, start_prompt, version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            persona_role = excluded.persona_role,
            persona_prompt = excluded.persona_prompt,
            skills_json = excluded.skills_json,
            animus_type = excluded.animus_type,
            contractus_json = excluded.contractus_json,
            modus = excluded.modus,
            governance_json = excluded.governance_json,
            kind = excluded.kind,
            start_prompt = excluded.start_prompt,
            version = excluded.version,
            updated_at = excluded.updated_at
    """, (
        name, title, desc, persona_role, persona_prompt,
        json.dumps(skills), animus, json.dumps(contractus), modus, is_template,
        json.dumps(governance), kind, start_prompt, version, now
    ))
    conn.commit()

    return {
        "success": True,
        "id": conn.execute("SELECT id FROM agent_blueprints WHERE name = ?", (name,)).fetchone()[0],
        "name": name,
        "title": title,
        "kind": kind,
        "version": version,
        "start_prompt": start_prompt,
        "start_prompt_length": len(start_prompt),
        "status": "saved"
    }


def _execution_blueprint(conn, blueprint_id, expected_version):
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM agent_blueprints WHERE id = ?", (blueprint_id,)).fetchone()
    if row is None:
        raise KeyError("Blueprint nicht gefunden")
    bp = dict(row)
    if type(expected_version) is not int or expected_version != bp.get("version"):
        raise RuntimeError("blueprint_version_conflict")
    if bp.get("kind", "agent") not in {"agent", "role"}:
        raise ValueError("Dieser Vorlagentyp wird über seinen eigenen Dienst ausgeführt")
    if not isinstance(bp.get("persona_prompt"), str) or not bp["persona_prompt"].strip():
        raise ValueError("Ein Rollenprompt ist erforderlich")
    return bp


TOOL_ALIASES = {"read_files": ["read_file", "list_directory"], "search_content": ["search_text"],
                "directory_list": ["list_directory"], "write_files": ["write_file", "edit_file", "create_directory"],
                "execute_command": ["safe_shell"], "run_tests": ["safe_shell"],
                "git_guarded_p001": ["start_task_worktree", "finish_task"],
                "code_analyze": ["read_file", "search_text"], "web_fetch": ["web_fetch"]}
DEFAULT_TOOL_WHITELIST = ["read_file", "list_directory", "search_text", "task_manage"]


def expand_tool_whitelist(raw_tools) -> set[str]:
    """Real tool names granted by a blueprint whitelist (aliases resolved, None = default)."""
    from .chat.bach_tools import TOOLS_FULL
    known = {tool["function"]["name"] for tool in TOOLS_FULL}
    if raw_tools is None:
        raw_tools = DEFAULT_TOOL_WHITELIST
    if not isinstance(raw_tools, list) or len(raw_tools) > 100:
        raise ValueError("Ungültige Toolfreigabe")
    allowed = set()
    for name in raw_tools:
        if not isinstance(name, str) or name not in known | TOOL_ALIASES.keys():
            raise ValueError("Toolfreigabe enthält ein unbekanntes Werkzeug")
        allowed.update([name] if name in known else TOOL_ALIASES[name])
    return allowed & known


def blueprint_slot_changes(bp: dict, execution: dict, parents: list[dict] = ()) -> dict:
    """Translate the saved role and real tool grants into controller config.

    ``parents`` are the governance dicts of the pinned parent templates; they only narrow.
    """
    from .chat.slots_config import DEFAULT_ROLE_PROMPTS
    if not isinstance(execution, dict) or not execution.get("backend") or not execution.get("model"):
        raise ValueError("Anbieter und konkretes Modell sind erforderlich")
    modus = bp.get("modus", "casualis")
    if modus not in {"casualis", "usus"}:
        raise ValueError("Zeit- und Ereignissteuerung sind noch nicht ausführbar; Ein Arbeitsblock oder Dauerläufer wählen")
    governance = json.loads(bp.get("governance_json") or "{}")
    contractus = json.loads(bp.get("contractus_json") or "{}")
    skills = json.loads(bp.get("skills_json") or "[]")
    if not isinstance(governance, dict) or not isinstance(contractus, dict) or not isinstance(skills, list):
        raise ValueError("Gespeicherte Blueprint-Konfiguration ist ungültig")
    allowed = expand_tool_whitelist(governance.get("tool_whitelist"))
    for parent in parents:
        if parent.get("tool_whitelist") is not None:
            allowed &= expand_tool_whitelist(parent["tool_whitelist"])
    read_only = any(layer.get("profile") == "read_only_research" for layer in [governance, *parents])
    role = bp["persona_role"] if bp["persona_role"] in DEFAULT_ROLE_PROMPTS else "task_worker"
    prompt = bp["persona_prompt"]
    from .skill_source_service import pin_skills
    skill_refs = pin_skills(skills)
    changes = {key: execution[key] for key in ("backend", "model", "mode", "think", "avatar", "symbol",
        "include_system_prompt", "custom_system_prompt", "pause_after", "pause_minutes", "pause_basis") if key in execution}
    changes.update({"name": bp["title"] or bp["name"], "description": bp.get("description") or "",
        "role_id": role, "sub_mode": "boss_routing" if role == "boss_routing" else "expert_role",
        "custom_role_prompt": prompt, "skill_refs": skill_refs,
        "max_tool_rounds": contractus.get("turns", contractus.get("max_turns", 20)),
        "allowed_tools": sorted(allowed), "allow_tools": bool(allowed), "enabled": True,
        "worker_type": "once" if modus == "casualis" else "continuous"})
    if read_only:
        changes["mode"] = "safe"
        changes["allowed_tools"] = sorted(allowed & {"read_file", "list_directory", "search_text", "web_fetch", "system_status", "ollama_info", "task_manage"})
        changes["allow_tools"] = bool(changes["allowed_tools"])
    return changes


def materialize_blueprint(conn: sqlite3.Connection, blueprint_id: int, *,
                          expected_version: int, execution: dict,
                          configuration_version: str, terminal_verified: bool = False,
                          slots_path: str | None = None) -> dict[str, Any]:
    from .chat.slots_config import get_system_slot, materialize_system_blueprint
    from .governance_binding import receipt_binding, resolve_layers
    ensure_blueprint_schema(conn)
    # P05 3b: effektiven Governance-Satz vor der Schreibsperre auflösen; jeder Save
    # erhöht die Version, die CAS-Prüfung unten erkennt also eine Änderung dazwischen.
    governance = json.loads(_execution_blueprint(conn, blueprint_id, expected_version).get("governance_json") or "{}")
    if not isinstance(governance, dict):
        raise ValueError("Gespeicherte Blueprint-Konfiguration ist ungültig")
    binding, parents = resolve_layers(conn, governance, blueprint_id=blueprint_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        bp = _execution_blueprint(conn, blueprint_id, expected_version)
        # Nur neue Konfiguration sperren; bestehende Steckplaetze bleiben startbar.
        if bp.get("provider") and bp.get("template_status") != "available":
            raise RuntimeError("template_unavailable")
        slot_id = f"system-blueprint-{blueprint_id}"
        if get_system_slot(slot_id, slots_path) and not terminal_verified:
            raise RuntimeError("worker_terminal_state_required")
        changes = blueprint_slot_changes(bp, execution, parents)
        changes["governance_binding"] = binding
        result = materialize_system_blueprint(blueprint_id, expected_version,
            changes, configuration_version, path=slots_path)
        conn.execute("UPDATE agent_blueprints SET is_materialized = 1 WHERE id = ? AND version = ?",
                     (blueprint_id, expected_version))
        conn.commit()
        return {"success": True, "id": blueprint_id, "name": bp["name"], "title": bp["title"],
                "status": "configured", "is_materialized": True, "is_living": None,
                "is_running": False, "worker_started": False, "slot_id": slot_id,
                "configuration_version": result["configuration_version"],
                "governance_binding": receipt_binding(binding)}
    except Exception:
        conn.rollback()
        raise


def start_blueprint_worker(conn: sqlite3.Connection, blueprint_id: int, task: str | None = None,
                           *, expected_version: int | None = None,
                           configuration_version: str | None = None, dispatcher=None,
                           slots_path: str | None = None) -> dict[str, Any]:
    """Return only the controller's correlated physical run receipt."""
    if dispatcher is None:
        raise RuntimeError("worker_dispatcher_required")
    if task:
        raise ValueError("Aufträge zuerst über die TaskDB zuweisen")
    bp = _execution_blueprint(conn, blueprint_id, expected_version)
    from .chat.slots_config import get_system_slot
    slot_id = f"system-blueprint-{blueprint_id}"
    slot = get_system_slot(slot_id, slots_path)
    if (not slot or slot.get("blueprint_id") != blueprint_id
            or slot.get("blueprint_version") != expected_version):
        raise RuntimeError("blueprint_instance_not_current")
    modus = bp.get("modus", "casualis")
    if modus not in {"casualis", "usus"}:
        raise ValueError("Zeit- und Ereignissteuerung sind noch nicht ausführbar")
    if slot.get("type") != ("once" if modus == "casualis" else "continuous"):
        raise RuntimeError("blueprint_instance_not_current")
    # P05 3b: gepinnte Bindung vor dem Start erneut exakt auflösen; kein stiller Wechsel.
    from .governance_binding import inheritance, verify_run
    binding = verify_run(slot.get("governance_binding"), slot.get("allowed_tools"))
    if binding is not None and binding["inherits"]:
        inheritance(conn, binding["inherits"][0], self_id=blueprint_id)
    execution = dispatcher(slot_id, configuration_version)
    if (not isinstance(execution, dict) or execution.get("schema") != "bach.worker-execution.v1"
            or execution.get("worker_id") != slot_id
            or type(execution.get("worker_thread_started")) is not bool
            or type(execution.get("terminal")) is not bool):
        raise RuntimeError("worker_execution_not_confirmed")
    running = execution["worker_thread_started"] is True and execution["terminal"] is False
    return {"success": True, "id": blueprint_id, "name": bp["name"], "title": bp["title"],
            "slot_id": slot_id, "status": execution["state"], "is_running": running,
            "runtime_verified": True, "execution": execution, "job_receipt": execution,
            "heartbeat_receipt": None, "receipt": execution}
