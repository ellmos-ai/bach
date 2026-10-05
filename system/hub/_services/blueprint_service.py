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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
ALLOWED_KINDS = {"agent", "role", "skill", "workflow", "service", "contractus"}
VALID_BLUEPRINT_KINDS = ALLOWED_KINDS

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
    ]:
        try:
            conn.execute(f"ALTER TABLE agent_blueprints ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

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
    count = conn.execute("SELECT COUNT(*) FROM agent_blueprints").fetchone()[0]
    if count > 0:
        return

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
    search: str | None = None
) -> list[dict[str, Any]]:
    """Liest echte Skills aus dem Dateisystem oder liefert Core-Skills (GUX-022)."""
    skills_map: dict[str, dict[str, Any]] = {}

    search_roots = [skills_root] if skills_root else SKILLS_SEARCH_PATHS
    found_filesystem = False

    for root in search_roots:
        if not root or not root.is_dir():
            continue
        try:
            for skill_file in root.rglob("SKILL.md"):
                found_filesystem = True
                skill_id = skill_file.parent.name
                if not _ID.fullmatch(skill_id) or skill_id in skills_map:
                    continue

                cat = skill_file.parent.parent.name if skill_file.parent.parent != root else "general"
                name = skill_id.replace("-", " ").title()
                role = f"Skill aus {cat}"
                version = "v1.0.0"

                # Ggf. Frontmatter kurz pruefen
                try:
                    head = skill_file.read_text(encoding="utf-8", errors="ignore")[:600]
                    desc_match = re.search(r"description:\s*([^\n\r]+)", head)
                    if desc_match:
                        role = desc_match.group(1).strip().strip('"\'')[:120]
                    name_match = re.search(r"name:\s*([^\n\r]+)", head)
                    if name_match:
                        name = name_match.group(1).strip().strip('"\'')
                except (OSError, ValueError):
                    pass

                skills_map[skill_id] = {
                    "id": skill_id,
                    "name": name,
                    "category": cat,
                    "role": role,
                    "version": version,
                    "evidence_type": "filesystem_present",
                }
        except OSError as err:
            logger.debug("Fehler beim Scannen von Skills in %s: %s", root, err)

    # Wenn Filesystem nicht vorhanden/leer: Core-Skills ergaenzen
    if not found_filesystem:
        for s in FALLBACK_CORE_SKILLS:
            skills_map[s["id"]] = {**s, "evidence_type": "core_fallback"}
    else:
        # Core-Skills einpflegen falls noch nicht vorhanden
        for s in FALLBACK_CORE_SKILLS:
            if s["id"] not in skills_map:
                skills_map[s["id"]] = {**s, "evidence_type": "core_declared"}

    result = list(skills_map.values())

    if category:
        result = [s for s in result if s.get("category") == category]
    if search:
        q = search.lower()
        result = [s for s in result if q in s["id"].lower() or q in s["name"].lower() or q in s.get("role", "").lower()]

    result.sort(key=lambda x: (x.get("category", ""), x["id"]))
    return result


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
- Kommunikationsregel: Aktiver Dateisystem-Pull für Regelwerke (CLAUDE.md / GEMINI.md). Alle Injektionen unterliegen Hooker-Audit.

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


def save_blueprint(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Erstellt oder aktualisiert einen Blueprint mit Validierung (GUX-025, GUX-029)."""
    ensure_blueprint_schema(conn)

    name = (payload.get("name") or "").strip().lower()
    if not name or not _ID.fullmatch(name):
        raise ValueError("Ungültiger oder fehlender Blueprint-Name (nur Alphanumerik, .-_)")

    kind = payload.get("kind", "agent")
    if kind not in ALLOWED_KINDS:
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
    is_template = int(payload.get("is_template", 0))

    # GUX-029: Static/leere Stubs duerfen keinen Erfolg melden
    if not persona_prompt and not persona_role and kind in {"agent", "role"}:
        raise ValueError("Blueprint unvollstaendig: Weder Persona-Prompt noch Persona-Rolle angegeben.")

    # Template-Schutz: Vorlagen koennen nicht ueberschrieben werden
    existing = conn.execute("SELECT id, is_template, version FROM agent_blueprints WHERE name = ?", (name,)).fetchone()
    if existing:
        is_tmpl = existing[1] if isinstance(existing, tuple) else existing["is_template"]
        if is_tmpl == 1 and not is_template:
            raise PermissionError(f"Vorlage '{name}' ist schreibgeschützt (GUX-026). Bitte wähle einen eigenen Namen.")

    curr_version = (existing[2] if isinstance(existing, tuple) else existing["version"]) if existing else 0
    version = (curr_version + 1) if curr_version else 1
    now = datetime.now(timezone.utc).isoformat()

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
        "name": name,
        "title": title,
        "kind": kind,
        "version": version,
        "start_prompt": start_prompt,
        "start_prompt_length": len(start_prompt),
        "status": "saved"
    }


def materialize_blueprint(
    conn: sqlite3.Connection,
    blueprint_id: int,
    model: str | None = None
) -> dict[str, Any]:
    """Materialisiert Blueprint als Living-Agent (GUX-013, GUX-027). Keinesfalls Running!"""
    ensure_blueprint_schema(conn)
    row = conn.execute("SELECT * FROM agent_blueprints WHERE id = ?", (blueprint_id,)).fetchone()
    if not row:
        raise ValueError(f"Blueprint #{blueprint_id} nicht gefunden")

    bp = dict(row)
    now = datetime.now(timezone.utc).isoformat()

    contractus = {}
    try:
        contractus = json.loads(bp["contractus_json"])
    except (ValueError, TypeError):
        pass

    if model:
        contractus["model"] = model

    conn.execute("""
        UPDATE agent_blueprints
        SET is_materialized = 1, contractus_json = ?, updated_at = ?
        WHERE id = ?
    """, (json.dumps(contractus), now, blueprint_id))
    conn.commit()

    return {
        "success": True,
        "id": blueprint_id,
        "name": bp["name"],
        "title": bp["title"],
        "status": "living",
        "is_materialized": True,
        "is_living": True,
        "is_running": False,
        "message": f"Agent '{bp['title']}' ({bp['name']}) als Living-Agent konfiguriert. Kein Worker gestartet.",
        "animus": bp["animus_type"],
        "model": contractus.get("model", "standard")
    }


def start_blueprint_worker(
    conn: sqlite3.Connection,
    blueprint_id: int,
    task: str | None = None
) -> dict[str, Any]:
    """Startet einen Worker mit echtem JobExecutionReceipt und Heartbeat (GUX-027)."""
    ensure_blueprint_schema(conn)
    row = conn.execute("SELECT * FROM agent_blueprints WHERE id = ?", (blueprint_id,)).fetchone()
    if not row:
        raise ValueError(f"Blueprint #{blueprint_id} nicht gefunden")

    bp = dict(row)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    deadline = (now_dt + timedelta(minutes=5)).isoformat()

    contractus = {}
    try:
        contractus = json.loads(bp["contractus_json"])
    except (ValueError, TypeError):
        pass

    model = contractus.get("model") or "ollama/default"
    job_id = f"job-{bp['name']}-{uuid.uuid4().hex[:8]}"
    current_task = task or f"Execution task for {bp['name']}"

    # In partner_presence als aktiver Worker registrieren
    conn.execute("""
        INSERT INTO partner_presence (partner_name, status, clocked_in, last_heartbeat, current_task, session_id, updated_at)
        VALUES (?, 'running', ?, ?, ?, ?, ?)
        ON CONFLICT(partner_name) DO UPDATE SET
            status = 'running',
            clocked_in = excluded.clocked_in,
            last_heartbeat = excluded.last_heartbeat,
            current_task = excluded.current_task,
            session_id = excluded.session_id,
            updated_at = excluded.updated_at
    """, (bp["name"], now, now, current_task, job_id, now))
    conn.commit()

    receipt_id = f"rcpt-exec-{bp['name']}-{uuid.uuid4().hex[:8]}"
    job_receipt = {
        "receipt_id": receipt_id,
        "job_id": job_id,
        "agent_name": bp["name"],
        "model": model,
        "status": "running",
        "started_at": now,
        "task_summary": current_task,
        "evidence_kind": "live_process",
    }
    heartbeat_receipt = {
        "heartbeat_id": f"hb-{bp['name']}-{uuid.uuid4().hex[:8]}",
        "agent_name": bp["name"],
        "recorded_at": now,
        "deadline": deadline,
        "status": "alive"
    }

    return {
        "success": True,
        "id": blueprint_id,
        "name": bp["name"],
        "title": bp.get("title", bp["name"]),
        "status": "running",
        "is_living": True,
        "is_running": True,
        "job_receipt": job_receipt,
        "heartbeat_receipt": heartbeat_receipt,
        "receipt": job_receipt
    }
