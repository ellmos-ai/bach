"""
skill_capabilities_service.py - Kern-Service für Fähigkeiten, Steckdosenleiste,
MCP-Cookbooks, Wissens-Ebenen, Versionierung, Prompt-Konvertierung und externe Artefakte.

Regel- und Registertreue:
- GUX-030: Skills als eigener Hauptbereich mit Anbindung an Software & Werkzeuge.
- GUX-031: Blueprints referenzieren dieselben Skill-IDs und Versionen (kein Duplikat-Store).
- GUX-063: Clipboard-Kopierfunktion mit bestätigtem Write-Receipt oder geprüftem Fallback.
- GUX-064: Prompt->Skill Konvertierung über standardisierten Creator-Vertrag (YAML-Frontmatter).
- GUX-065: Append-Only Versionierung und Restore: Altes wird als NEUE Version wiederhergestellt.
- GUX-066: ProfiPrompt, PromptBoard und Explorer Pro als belegte importierbare Artefakte.
- CAP-01: MCP-Cookbooks aus autoritativer Quelle (Tools = Zutaten, Prompts = Rezepte).
- CAP-02: Plugin-Steckdosen mit echter Quelle und quittiertem Toggle.
- CAP-03: SentinelFleet Versionierung für Prompts, Skills und Konfigurationen.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("bach.skill_capabilities")

_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

# Suchpfade fuer echte Plugins
PLUGIN_SEARCH_PATHS = [
    Path(os.path.expanduser("~/OneDrive/.TOPICS/.AI/.PLUGINS")),
    Path("C:/Users/User/OneDrive/.TOPICS/.AI/.PLUGINS"),
    Path(os.path.expanduser("~/.gemini/config/plugins")),
    Path("C:/Users/User/.gemini/config/plugins"),
    Path(os.path.expanduser("~/.claude/plugins")),
    Path("C:/Users/User/.claude/plugins"),
]

# Suchpfade fuer MCP Server
MCP_SEARCH_PATHS = [
    Path(os.path.expanduser("~/OneDrive/.TOPICS/.AI/.MCP")),
    Path("C:/Users/User/OneDrive/.TOPICS/.AI/.MCP"),
    Path(os.path.expanduser("~/.gemini/antigravity-cli/mcp")),
    Path("C:/Users/User/.gemini/antigravity-cli/mcp"),
]

# Suchpfade fuer Skills
SKILLS_SEARCH_PATHS = [
    Path(os.path.expanduser("~/OneDrive/.TOPICS/.AI/.SKILLS/skills")),
    Path("C:/Users/User/OneDrive/.TOPICS/.AI/.SKILLS/skills"),
    Path(os.path.expanduser("~/.agents/skills")),
    Path("C:/Users/User/.agents/skills"),
    Path(os.path.expanduser("~/.claude/skills")),
    Path("C:/Users/User/.claude/skills"),
]

# Suchpfade fuer externe Artefakte (GUX-066)
ARTIFACT_SEARCH_PATHS = {
    "profiprompt": [
        Path("C:/Users/User/OneDrive/.TOPICS/.SOFTWARE/DATA/REL_ProfiPrompt"),
        Path(os.path.expanduser("~/OneDrive/.TOPICS/.SOFTWARE/DATA/REL_ProfiPrompt")),
    ],
    "promptboard": [
        Path("C:/Users/User/OneDrive/.TOPICS/.SOFTWARE/DATA/REL-PUB_PromptBoard"),
        Path(os.path.expanduser("~/OneDrive/.TOPICS/.SOFTWARE/DATA/REL-PUB_PromptBoard")),
    ],
    "explorerpro": [
        Path("C:/Users/User/OneDrive/.TOPICS/.SOFTWARE/DATA/REL-PUB_ExplorerPro_SUITE"),
        Path(os.path.expanduser("~/OneDrive/.TOPICS/.SOFTWARE/DATA/REL-PUB_ExplorerPro_SUITE")),
    ]
}

# Standard-Plugins als Basis / Fallback
DEFAULT_PLUGINS = [
    {"name": "science", "title": "Science & Bio-Informatik", "description": "AlphaFold, UniProt, ChEMBL & Gene-Tools", "skills": 18},
    {"name": "open-compute-plugin", "title": "Open-Compute Desktop Engine", "description": "Win32 Fenstermanagement, Screen-Capture & UIA", "skills": 14},
    {"name": "android-cli-plugin", "title": "Android CLI Suite", "description": "AVD Management, UI Inspection & SDK Tools", "skills": 6},
    {"name": "modern-web-guidance", "title": "Modern Web Guidance", "description": "Astro, Tailwind & Modern Frontend Patterns", "skills": 8},
    {"name": "context7", "title": "Context7 Live Docs", "description": "Echtzeit Dokumentations-Resolver für APIs", "skills": 4},
    {"name": "hyperframes-media", "title": "HyperFrames Media OS", "description": "Video-Rendering, Kinetic Motion & Waveform Synthesis", "skills": 16},
]

# Kanonische Core-Skills
CANONICAL_CORE_SKILLS = [
    {"id": "persona-researcher", "name": "Persona: Researcher", "category": "dev", "role": "Strenger empirischer Forscher", "version": "v1.2.0", "tier": "executive", "type": "Persona"},
    {"id": "persona-developer", "name": "Persona: Developer", "category": "dev", "role": "Senior Software Architect (PEP-621 / TS)", "version": "v2.0.1", "tier": "executive", "type": "Persona"},
    {"id": "role-triage-operator", "name": "Rolle: Triage-Operator", "category": "infrastructure", "role": "Task-Triage & Intent-Routing", "version": "v1.1.0", "tier": "executive", "type": "Rolle"},
    {"id": "pipeline-optimizer", "name": "Pipeline Optimizer", "category": "dev", "role": "6-Schritte Refactoring & Sanierung", "version": "v1.4.0", "tier": "process", "type": "Workflow"},
    {"id": "chain-ci-lint-test-build", "name": "CI Lint Test Build", "category": "dev", "role": "Deterministische CI Pipeline (MarbleRun)", "version": "v2.1.0", "tier": "process", "type": "Kette"},
    {"id": "service-win32-window-ops", "name": "Win32 Window Ops", "category": "infrastructure", "role": "Desktop-Isolation & Focus-Management", "version": "v1.3.0", "tier": "service", "type": "Service"},
    {"id": "service-agents-bridge", "name": "Agents Bridge", "category": "infrastructure", "role": "Regelwerk-Spiegelung & AGENTS.md Redirect", "version": "v2.0.0", "tier": "service", "type": "Service"},
    {"id": "git-hygiene", "name": "Git Hygiene", "category": "utilities", "role": "Fail-Closed Git & Branch Management", "version": "v1.2.0", "tier": "capabilities", "type": "Fähigkeit"},
    {"id": "document-chunker", "name": "Document Chunker", "category": "utilities", "role": "Token-Überlappendes Chunking für RAG", "version": "v1.0.0", "tier": "capabilities", "type": "Fähigkeit"},
    {"id": "lock-master", "name": "Lock Master", "category": "utilities", "role": "Verzeichnis- & Dateisperren-Auditor", "version": "v2.0.1", "tier": "capabilities", "type": "Fähigkeit"},
    {"id": "brainstorm", "name": "Brainstorm", "category": "utilities", "role": "Strukturierte Kreativitätsmethoden", "version": "v1.0.0", "tier": "capabilities", "type": "Fähigkeit"},
    {"id": "decide", "name": "Decide", "category": "utilities", "role": "Strukturierte Entscheidungsfindung", "version": "v1.0.0", "tier": "capabilities", "type": "Fähigkeit"},
    {"id": "think", "name": "Think", "category": "utilities", "role": "Strukturierte Problemlösung & Analyse", "version": "v1.0.0", "tier": "capabilities", "type": "Fähigkeit"},
]


# ═══════════════════════════════════════════════════════════════
# 1. PLUGINS / STECKDOSENLEISTE (CAP-02)
# ═══════════════════════════════════════════════════════════════

def ensure_capabilities_schema(conn: sqlite3.Connection) -> None:
    """Stellt Tabellen plugin_sockets und skill_versions sicher."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plugin_sockets (
            name TEXT PRIMARY KEY,
            is_plugged INTEGER DEFAULT 1,
            slot INTEGER DEFAULT 1,
            updated_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,
            version TEXT NOT NULL,
            changelog TEXT,
            author TEXT DEFAULT 'operator',
            content TEXT,
            created_at TEXT
        )
    """)
    conn.commit()


def get_plugin_sockets(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """
    Liefert echte Plugins aus dem Dateisystem und gleicht den Zustand mit der DB ab.
    (CAP-02: Stromstecker an Steckdosenleiste).
    """
    discovered_plugins: dict[str, dict[str, Any]] = {}

    # 1. Aus Default-Plugins vorbefuellen
    for p in DEFAULT_PLUGINS:
        discovered_plugins[p["name"]] = {
            "name": p["name"],
            "title": p["title"],
            "description": p["description"],
            "skills": p["skills"],
            "source_kind": "core_default"
        }

    # 2. Aus .gemini/config/plugins scannen
    for root in PLUGIN_SEARCH_PATHS:
        if not root.exists():
            continue
        try:
            # Ordner-Scan
            for item in root.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    p_name = item.name
                    if p_name not in discovered_plugins:
                        skills_count = len(list(item.rglob("SKILL.md")))
                        discovered_plugins[p_name] = {
                            "name": p_name,
                            "title": p_name.replace("-", " ").title(),
                            "description": f"Lokales Plugin aus {root.name}",
                            "skills": max(1, skills_count),
                            "source_kind": "filesystem_folder"
                        }

            # installed_plugins.json von Claude
            inst_json = root / "installed_plugins.json"
            if inst_json.exists():
                try:
                    data = json.loads(inst_json.read_text(encoding="utf-8"))
                    plugins_dict = data.get("plugins", {})
                    for p_key in plugins_dict:
                        short_name = p_key.split("@")[0]
                        if short_name not in discovered_plugins:
                            discovered_plugins[short_name] = {
                                "name": short_name,
                                "title": short_name.replace("-", " ").title(),
                                "description": f"Claude Marketplace Plugin ({p_key})",
                                "skills": 1,
                                "source_kind": "claude_installed_plugin"
                            }
                except (OSError, json.JSONDecodeError):
                    pass

            # plugins.catalog.json
            cat_json = root / "plugins.catalog.json"
            if cat_json.exists():
                try:
                    cat_data = json.loads(cat_json.read_text(encoding="utf-8"))
                    for m in cat_data.get("materialized", []):
                        m_id = m.get("id")
                        if m_id and m_id not in discovered_plugins:
                            discovered_plugins[m_id] = {
                                "name": m_id,
                                "title": m.get("display_name") or m_id.title(),
                                "description": m.get("host_kind") or "Materialisiertes Plugin",
                                "skills": m.get("contents", {}).get("skills", 1),
                                "source_kind": "materialized_catalog"
                            }
                except (OSError, json.JSONDecodeError):
                    pass
        except OSError as exc:
            logger.debug("Fehler beim Scannen von Plugin-Pfad %s: %s", root, exc)

    # 3. Status aus DB lesen falls vorhanden
    status_map: dict[str, tuple[bool, int]] = {}
    if conn:
        try:
            ensure_capabilities_schema(conn)
            rows = conn.execute("SELECT name, is_plugged, slot FROM plugin_sockets").fetchall()
            status_map = {r[0]: (bool(r[1]), r[2]) for r in rows}
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    sockets = []
    for i, (name, meta) in enumerate(discovered_plugins.items(), 1):
        plugged, slot = status_map.get(name, (True, i))
        sockets.append({
            "slot": slot or i,
            "name": name,
            "title": meta.get("title", name.title()),
            "description": meta.get("description", ""),
            "skills_count": meta.get("skills", 1),
            "is_plugged": plugged,
            "cable_status": "connected" if plugged else "coiled",
            "led_color": "var(--success)" if plugged else "var(--text-muted)",
            "source_kind": meta.get("source_kind", "unknown")
        })

    active_count = sum(1 for s in sockets if s["is_plugged"])
    return {
        "sockets": sockets,
        "active_count": active_count,
        "total_count": len(sockets),
        "source": "filesystem_scan_and_db",
        "live_discovery": True
    }


def toggle_plugin_socket(plugin_name: str, conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Schaltet ein Plugin an der Steckdosenleiste um und speichert den Zustand (CAP-02).
    """
    if not plugin_name:
        raise ValueError("plugin_name erforderlich")

    ensure_capabilities_schema(conn)
    cursor = conn.cursor()
    row = cursor.execute("SELECT is_plugged FROM plugin_sockets WHERE name = ?", (plugin_name,)).fetchone()
    current_state = bool(row[0]) if row else True
    new_state = 0 if current_state else 1
    now = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO plugin_sockets (name, is_plugged, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET is_plugged = excluded.is_plugged, updated_at = excluded.updated_at
    """, (plugin_name, new_state, now))
    conn.commit()

    return {
        "name": plugin_name,
        "is_plugged": bool(new_state),
        "cable_status": "connected" if new_state else "coiled",
        "message": f"Plugin {plugin_name} {'eingesteckt (aktiv)' if new_state else 'ausgesteckt (Kabel eingerollt)'}"
    }


# ═══════════════════════════════════════════════════════════════
# 2. MCP COOKBOOKS (CAP-01)
# ═══════════════════════════════════════════════════════════════

def get_mcp_cookbooks() -> dict[str, Any]:
    """
    Liefert MCP-Server als 3D-Rezeptbücher (CAP-01).
    Zutaten = echte Tools aus MCP_ROOT / Schemas, Rezepte = Einsatz-Prompts.
    """
    cookbooks_map: dict[str, dict[str, Any]] = {}

    # Standard-Cookbooks
    default_cookbooks = [
        {
            "id": "open-compute",
            "title": "Open-Compute Cookbook",
            "subtitle": "Desktop- & UI-Automationsrezepte",
            "cover_color": "linear-gradient(135deg, #1e1e38 0%, #2d1e4e 100%)",
            "ingredients": ["capture", "list_windows", "do", "click_name", "tree", "signal_show"],
            "recipes": [
                {"title": "Screen-Inspektion & Orientierung", "prompt": "capture() -> tree() -> UI-Element lokalisieren"},
                {"title": "Fenster-Aktivierung & BringToFront", "prompt": "list_windows() -> window_token -> do(activate_window)"},
                {"title": "Sicherer 1-Click UI-Tastendruck", "prompt": "invoke(query='Submit', exact=True)"}
            ]
        },
        {
            "id": "filecommander",
            "title": "FileCommander Cookbook",
            "subtitle": "Dateisystem & Dateioperationen",
            "cover_color": "linear-gradient(135deg, #1a2f3b 0%, #0d3b4a 100%)",
            "ingredients": ["fc_read_file", "fc_write_file", "fc_search_files", "fc_check_cloud_lock", "fc_str_replace"],
            "recipes": [
                {"title": "Fail-Closed Cloud-Lock Vorprüfung", "prompt": "fc_check_cloud_lock(path) vor jeder Dateiänderung"},
                {"title": "Punktgenauer String-Ersatz", "prompt": "fc_str_replace(target, old_str, new_str)"},
                {"title": "Föderierte Datei-Inhalts-Suche", "prompt": "fc_search_content(query, extension='.md')"}
            ]
        },
        {
            "id": "controlcenter",
            "title": "ControlCenter Cookbook",
            "subtitle": "Governance, Profile & Bundles",
            "cover_color": "linear-gradient(135deg, #3b2020 0%, #4a1525 100%)",
            "ingredients": ["controlcenter_find_skill", "controlcenter_switch_profile", "controlcenter_list_tools", "controlcenter_check_lock"],
            "recipes": [
                {"title": "Semantischer Skill-Router", "prompt": "controlcenter_find_skill(query='Refactoring')"},
                {"title": "Profil-Switch & Berechtigung", "prompt": "controlcenter_switch_profile(profile='dev')"},
                {"title": "Lock-Master Sicherheitscheck", "prompt": "controlcenter_check_lock(path) vor Commit"}
            ]
        },
        {
            "id": "markitdown",
            "title": "MarkItDown Cookbook",
            "subtitle": "Dokumenten-Konvertierung",
            "cover_color": "linear-gradient(135deg, #1b3826 0%, #15452d 100%)",
            "ingredients": ["convert_to_markdown"],
            "recipes": [
                {"title": "PDF & Office zu Markdown", "prompt": "convert_to_markdown(path='paper.pdf') -> Chunker-Ready"}
            ]
        }
    ]
    for cb in default_cookbooks:
        cookbooks_map[cb["id"]] = cb

    # Echte MCP Server aus Dateisystem scannen
    live_found = False
    for mcp_root in MCP_SEARCH_PATHS:
        if not mcp_root.exists():
            continue
        try:
            # 1. mcps.catalog.v1.json
            cat_file = mcp_root / "mcps.catalog.v1.json"
            if cat_file.exists():
                try:
                    cat_data = json.loads(cat_file.read_text(encoding="utf-8"))
                    for m in cat_data.get("mcps", []):
                        m_id = m.get("id")
                        if not m_id:
                            continue
                        live_found = True
                        clean_id = m_id.removesuffix("-mcp")
                        if clean_id in cookbooks_map:
                            cb = cookbooks_map[clean_id]
                            if m.get("note"):
                                cb["subtitle"] = m["note"][:80]
                        else:
                            cookbooks_map[clean_id] = {
                                "id": clean_id,
                                "title": clean_id.replace("-", " ").title() + " Cookbook",
                                "subtitle": m.get("note") or f"MCP Server ({m.get('namespace', '*')})",
                                "cover_color": "linear-gradient(135deg, #252836 0%, #1a1c24 100%)",
                                "ingredients": [f"{m.get('namespace', 'tool_').replace('*', '')}exec"],
                                "recipes": [
                                    {"title": f"{clean_id.title()} Basis-Rezept", "prompt": f"Verwende {clean_id} gemäß Spezifikation"}
                                ]
                            }
                except (OSError, json.JSONDecodeError):
                    pass

            # 2. Schemas in Unterordnern (z. B. ~/.gemini/antigravity-cli/mcp/<serverName>/*.json)
            for sub in mcp_root.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    schema_files = list(sub.glob("*.json"))
                    if schema_files:
                        live_found = True
                        server_id = sub.name.removesuffix("-mcp")
                        tools = [f.stem for f in schema_files if f.name != "package.json"]
                        if tools:
                            if server_id in cookbooks_map:
                                cookbooks_map[server_id]["ingredients"] = sorted(set(cookbooks_map[server_id]["ingredients"] + tools))
                            else:
                                cookbooks_map[server_id] = {
                                    "id": server_id,
                                    "title": server_id.replace("-", " ").title() + " Cookbook",
                                    "subtitle": f"Dynamisch entdeckter MCP Server ({len(tools)} Tools)",
                                    "cover_color": "linear-gradient(135deg, #1e2638 0%, #201e38 100%)",
                                    "ingredients": tools[:15],
                                    "recipes": [
                                        {"title": f"{tools[0].title()} Rezept", "prompt": f"{tools[0]}() -> Ausführung und Protokollierung"}
                                    ]
                                }
        except OSError as exc:
            logger.debug("Fehler beim Scannen von MCP-Root %s: %s", mcp_root, exc)

    cookbooks = list(cookbooks_map.values())
    return {
        "cookbooks": cookbooks,
        "count": len(cookbooks),
        "source": "authoritative_mcp_root" if live_found else "static_examples",
        "live_discovery": live_found
    }


# ═══════════════════════════════════════════════════════════════
# 3. 4 KOGNITIVE WISSENS-EBENEN / TIERS
# ═══════════════════════════════════════════════════════════════

def get_capabilities_tiers(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """
    Liefert die 4 harmonisierten Wissens-Ebenen:
    1. executive: Selbststeuerung & Metaskills (Persona, Rolle, Framing)
    2. process: Prozess-Skills (Workflow, Pipeline, MarbleRun)
    3. service: Service-Skills (System-Wissen, OS-Bedienung, Brücken)
    4. capabilities: Fähigkeiten-Skills (Werkzeuge, How-Tos, Utilities)
    Reichert die Skills mit realen Einträgen aus dem Dateisystem und DB an.
    """
    tiers_meta = {
        "executive": {
            "id": "executive",
            "name": "1. Selbststeuerungs- & Metaskills (Zentrale Exekutive)",
            "description": "Persona-Skills (Haltung/Charakter), Rollen-Skills (Auftrag & Skill-Dispatching), Semantisches Framing ('Stell dir vor...')",
            "icon": "👑",
            "color": "var(--accent-red)",
            "skills": []
        },
        "process": {
            "id": "process",
            "name": "2. Prozess-Skills (Handlung & Koordination)",
            "description": "Adaptive Workflow-Skills (mit Subagenten) & Deterministische MarbleRun-Ketten",
            "icon": "🔄",
            "color": "var(--accent)",
            "skills": []
        },
        "service": {
            "id": "service",
            "name": "3. Service-Skills (System-Wissen & OS-Bedienung)",
            "description": "Host- & OS-Bedienung (Windows/Mac/Shell), Systemprompts (CLAUDE.md, GEMINI.md) & Cluster-Topologie",
            "icon": "🖥️",
            "color": "var(--accent-blue)",
            "skills": []
        },
        "capabilities": {
            "id": "capabilities",
            "name": "4. Fähigkeiten-Skills (Atomare Werkzeuge)",
            "description": "Konkrete Handwerkszeuge und How-Tos (git-hygiene, doc-chunker, lock-master, decide, think)",
            "icon": "🛠️",
            "color": "var(--success)",
            "skills": []
        }
    }

    # 1. Core-Skills einordnen
    for s in CANONICAL_CORE_SKILLS:
        tier_id = s.get("tier", "capabilities")
        if tier_id in tiers_meta:
            tiers_meta[tier_id]["skills"].append({
                "id": s["id"],
                "name": s["name"],
                "role": s["role"],
                "version": s["version"],
                "type": s["type"],
                "category": s.get("category", "general")
            })

    # 2. Reale Dateisystem-Skills aus SKILLS_SEARCH_PATHS scannen
    fs_seen = {s["id"] for s in CANONICAL_CORE_SKILLS}
    for s_root in SKILLS_SEARCH_PATHS:
        if not s_root.exists():
            continue
        try:
            for skill_md in s_root.rglob("SKILL.md"):
                skill_id = skill_md.parent.name
                if not _ID_PATTERN.fullmatch(skill_id) or skill_id in fs_seen:
                    continue
                fs_seen.add(skill_id)

                cat = skill_md.parent.parent.name if skill_md.parent.parent != s_root else "general"
                # Frontmatter-Auszug
                name = skill_id.replace("-", " ").title()
                role = f"Skill aus {cat}"
                try:
                    text = skill_md.read_text(encoding="utf-8", errors="ignore")[:500]
                    desc_match = re.search(r"description:\s*([^\n\r]+)", text)
                    if desc_match:
                        role = desc_match.group(1).strip().strip('"\'')[:100]
                    name_match = re.search(r"name:\s*([^\n\r]+)", text)
                    if name_match:
                        name = name_match.group(1).strip().strip('"\'')
                except (OSError, ValueError):
                    pass

                # Zuordnung zu Tier
                tier = "capabilities"
                type_label = "Fähigkeit"
                if cat in ("workflow", "dev") or "workflow" in skill_id or "pipeline" in skill_id:
                    tier = "process"
                    type_label = "Workflow"
                elif cat in ("infrastructure", "system", "os") or "service" in skill_id or "bridge" in skill_id:
                    tier = "service"
                    type_label = "Service"
                elif "persona" in skill_id or "role" in skill_id:
                    tier = "executive"
                    type_label = "Rolle"

                tiers_meta[tier]["skills"].append({
                    "id": skill_id,
                    "name": name,
                    "role": role,
                    "version": "v1.0.0",
                    "type": type_label,
                    "category": cat
                })
        except OSError as exc:
            logger.debug("Fehler beim Scannen von Skills %s: %s", s_root, exc)

    # 3. Neueste Versionen aus DB nachschlagen
    if conn:
        try:
            ensure_capabilities_schema(conn)
            cursor = conn.cursor()
            rows = cursor.execute("""
                SELECT skill_name, version, id FROM skill_versions
                ORDER BY id ASC
            """).fetchall()
            version_map = {r[0]: r[1] for r in rows}
            for t in tiers_meta.values():
                for sk in t["skills"]:
                    if sk["id"] in version_map:
                        sk["version"] = version_map[sk["id"]]
                    elif sk["name"] in version_map:
                        sk["version"] = version_map[sk["name"]]
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    return {"tiers": list(tiers_meta.values())}


# ═══════════════════════════════════════════════════════════════
# 4. APPEND-ONLY VERSIONIERUNG & RESTORE (GUX-065, CAP-03)
# ═══════════════════════════════════════════════════════════════

def save_skill_version(
    conn: sqlite3.Connection,
    skill_name: str,
    version: str,
    changelog: str = "Update via Skills-Zentrale",
    author: str = "operator",
    content: str = ""
) -> dict[str, Any]:
    """
    Speichert eine neue Version eines Skills (SentinelFleet-Muster).
    """
    if not skill_name:
        raise ValueError("skill_name erforderlich")
    clean_name = skill_name.strip()
    clean_ver = version.strip() if version else "v1.1.0"

    ensure_capabilities_schema(conn)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO skill_versions (skill_name, version, changelog, author, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (clean_name, clean_ver, changelog, author, content, now))
    conn.commit()

    return {
        "status": "success",
        "skill_name": clean_name,
        "version": clean_ver,
        "changelog": changelog,
        "created_at": now
    }


def restore_skill_version(
    conn: sqlite3.Connection,
    skill_name: str,
    target_version: str
) -> dict[str, Any]:
    """
    Reversibles Append-Only Restore (GUX-065):
    Alte Prompt- und Skill-Versionen werden durch Restore als NEUE Version
    wiederhergestellt (INSERT statt SELECT/UPDATE; History bleibt unberührt).
    """
    if not skill_name or not target_version:
        raise ValueError("skill_name und target_version erforderlich")

    clean_name = skill_name.strip()
    clean_target = target_version.strip()

    ensure_capabilities_schema(conn)
    cursor = conn.cursor()

    # Inhalt der Zielversion suchen
    row = cursor.execute("""
        SELECT content, changelog FROM skill_versions
        WHERE skill_name = ? AND version = ?
        ORDER BY id DESC LIMIT 1
    """, (clean_name, clean_target)).fetchone()

    if not row:
        raise ValueError(f"Version '{clean_target}' für Skill '{clean_name}' nicht gefunden")

    content = row[0]
    
    # Ermittle neue Version (z. B. v1.0.0_restore_<timestamp> oder inkrementell)
    now_ts = int(time.time())
    new_version = f"{clean_target}_restore_{now_ts}"
    now_iso = datetime.now(timezone.utc).isoformat()
    changelog = f"Restored from version {clean_target} (append-only recovery GUX-065)"

    cursor.execute("""
        INSERT INTO skill_versions (skill_name, version, changelog, author, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (clean_name, new_version, changelog, "operator-restore", content, now_iso))
    conn.commit()

    return {
        "status": "success",
        "skill_name": clean_name,
        "active_version": new_version,
        "restored_from": clean_target,
        "append_only": True,
        "message": f"Skill {clean_name} erfolgreich wiederhergestellt als neue Version {new_version} (History unverändert)"
    }


# ═══════════════════════════════════════════════════════════════
# 5. PROMPT -> SKILL KONVERTIERUNG (GUX-064)
# ═══════════════════════════════════════════════════════════════

def convert_prompt_to_skill(
    conn: sqlite3.Connection,
    prompt_id: int | str | None = None,
    prompt_text: str | None = None,
    title: str | None = None,
    category: str | None = None,
    author: str = "prompt-converter"
) -> dict[str, Any]:
    """
    Ueberfuehrt einen Prompt in einen Skill mit Provenienz und korrektem
    Creator-Vertrag (YAML-Frontmatter name, description, category; GUX-064).
    """
    # Falls prompt_id angegeben, versuche Text aus prompt_templates zu laden
    source_title = title or ""
    source_text = prompt_text or ""
    source_cat = category or "utilities"

    if prompt_id is not None and conn is not None:
        try:
            row = conn.execute("SELECT name, purpose, text, category FROM prompt_templates WHERE id = ?", (prompt_id,)).fetchone()
            if row:
                source_title = source_title or row[0]
                source_text = source_text or row[2]
                source_cat = source_cat or (row[3] or "utilities")
        except sqlite3.Error:
            pass

    if not source_text.strip():
        raise ValueError("prompt_text darf nicht leer sein")
    if not source_title.strip():
        source_title = "Prompt Skill"

    # Slug generieren
    slug = re.sub(r"[^a-z0-9_-]", "-", source_title.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug or len(slug) < 2:
        slug = f"skill-{int(time.time())}"
    if len(slug) > 64:
        slug = slug[:64].rstrip("-")

    # Frontmatter nach Creator-Vertrag aufbauen
    now_iso = datetime.now(timezone.utc).isoformat()
    skill_md = f"""---
name: {slug}
description: {source_title}
category: {source_cat}
version: 1.0.0
origin: prompt-library
source_prompt_id: {prompt_id if prompt_id is not None else 'manual'}
converted_at: {now_iso}
---

# {source_title}

## Purpose & Scope
{source_title} - automatisch generierter Skill aus Prompt-Library via Creator-Vertrag (GUX-064).

## Prompt Execution Pattern
```prompt
{source_text.strip()}
```

## Guidelines & Best Practices
- Bei Verwendung dieses Skills die oben genannten Anweisungen präzise befolgen.
- Provenienz: Konvertiert aus Prompt-Vorlage #{prompt_id}.
"""

    # In DB als Version v1.0.0 speichern
    if conn:
        ensure_capabilities_schema(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO skill_versions (skill_name, version, changelog, author, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            slug,
            "v1.0.0",
            f"Initial conversion from prompt '{source_title}' (GUX-064)",
            author,
            skill_md,
            now_iso
        ))
        conn.commit()

    return {
        "success": True,
        "skill_name": slug,
        "title": source_title,
        "category": source_cat,
        "version": "v1.0.0",
        "provenance": {
            "source_prompt_id": prompt_id,
            "author": author,
            "converted_at": now_iso,
            "creator_contract": "v1-frontmatter"
        },
        "skill_md": skill_md
    }


# ═══════════════════════════════════════════════════════════════
# 6. BLUEPRINT-SKILLREFS VALIDIERUNG (GUX-031)
# ═══════════════════════════════════════════════════════════════

def validate_blueprint_skills(skills: list[Any]) -> dict[str, Any]:
    """
    Prueft, dass Blueprints auf dieselben Skill-IDs und Versionen referenzieren
    (GUX-031: kein Duplikat-Store, einheitliches Skillmodell).
    """
    # Sammle alle bekannten Skills
    known_skills = {s["id"]: s for s in CANONICAL_CORE_SKILLS}
    for s_root in SKILLS_SEARCH_PATHS:
        if not s_root.exists():
            continue
        try:
            for skill_md in s_root.rglob("SKILL.md"):
                s_id = skill_md.parent.name
                if _ID_PATTERN.fullmatch(s_id) and s_id not in known_skills:
                    known_skills[s_id] = {
                        "id": s_id,
                        "name": s_id.replace("-", " ").title(),
                        "category": skill_md.parent.parent.name if skill_md.parent.parent != s_root else "general",
                        "version": "v1.0.0"
                    }
        except OSError:
            pass

    matched = []
    unmatched = []

    for item in skills:
        s_id = item if isinstance(item, str) else (item.get("id") or item.get("name") if isinstance(item, dict) else "")
        s_id = str(s_id).strip()
        if not s_id:
            continue
        if s_id in known_skills:
            info = known_skills[s_id]
            matched.append({
                "id": s_id,
                "name": info.get("name", s_id),
                "category": info.get("category", "general"),
                "version": info.get("version", "v1.0.0"),
                "matched": True
            })
        else:
            unmatched.append({
                "id": s_id,
                "matched": False,
                "reason": "skill_not_in_canonical_registry"
            })

    return {
        "valid": len(unmatched) == 0,
        "total_referenced": len(skills),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched": matched,
        "unmatched": unmatched,
        "missing": [u["id"] for u in unmatched],
        "canonical_registry_size": len(known_skills)
    }


# ═══════════════════════════════════════════════════════════════
# 7. EXTERNE ARTEFAKTE: PROFIPROMPT, PROMPTBOARD, EXPLORER PRO (GUX-066)
# ═══════════════════════════════════════════════════════════════

def detect_external_artifacts() -> dict[str, Any]:
    """
    Sucht nach real vorhandenen Artefakten fuer ProfiPrompt, PromptBoard und Explorer Pro
    (GUX-066: unter System/Einstellungen importierbar, falls tatsächlich vorhanden).
    """
    results: dict[str, dict[str, Any]] = {}

    # 1. ProfiPrompt
    pp_paths = ARTIFACT_SEARCH_PATHS["profiprompt"]
    pp_found_path = next((p for p in pp_paths if p.exists()), None)
    pp_files = []
    pp_preview = []
    if pp_found_path:
        pp_files = [f.name for f in pp_found_path.iterdir() if f.is_file()][:10]
        # Suche nach echter Exportdatei
        export_files = list(pp_found_path.rglob("profiprompt-library-v1.json"))
        if export_files:
            try:
                data = json.loads(export_files[0].read_text(encoding="utf-8"))
                for pr in data.get("prompts", [])[:3]:
                    pp_preview.append({
                        "title": pr.get("title", "Prompt"),
                        "purpose": pr.get("purpose", ""),
                        "category": "ProfiPrompt"
                    })
            except (OSError, json.JSONDecodeError):
                pass

    results["profiprompt"] = {
        "id": "profiprompt",
        "title": "ProfiPrompt Suite",
        "description": "Desktop- & Windows-Store Prompt-Manager mit Multi-Versionierung und profiprompt-library-v1.json",
        "present": pp_found_path is not None,
        "path": str(pp_found_path) if pp_found_path else None,
        "available_files": pp_files,
        "preview_items": pp_preview,
        "can_import": pp_found_path is not None
    }

    # 2. PromptBoard
    pb_paths = ARTIFACT_SEARCH_PATHS["promptboard"]
    pb_found_path = next((p for p in pb_paths if p.exists()), None)
    pb_files = []
    pb_preview = []
    if pb_found_path:
        pb_files = [f.name for f in pb_found_path.iterdir() if f.is_file()][:10]
        export_files = list(pb_found_path.rglob("library.json"))
        if export_files:
            try:
                data = json.loads(export_files[0].read_text(encoding="utf-8"))
                for it in data.get("items", [])[:3]:
                    pb_preview.append({
                        "name": it.get("name", "Item"),
                        "category": it.get("category") or "PromptBoard",
                        "content_preview": (it.get("content") or "")[:60]
                    })
            except (OSError, json.JSONDecodeError):
                pass

    results["promptboard"] = {
        "id": "promptboard",
        "title": "PromptBoard",
        "description": "Desktop Prompt-Bibliothek für Entwickler und Multi-Agenten mit library.json Exportformat",
        "present": pb_found_path is not None,
        "path": str(pb_found_path) if pb_found_path else None,
        "available_files": pb_files,
        "preview_items": pb_preview,
        "can_import": pb_found_path is not None
    }

    # 3. Explorer Pro
    ep_paths = ARTIFACT_SEARCH_PATHS["explorerpro"]
    ep_found_path = next((p for p in ep_paths if p.exists()), None)
    ep_files = []
    ep_preview = []
    if ep_found_path:
        ep_files = [f.name for f in ep_found_path.iterdir() if f.is_file()][:10]
        template_file = ep_found_path / "SUITE_EXPLORERPRO_TEMPLATE.md"
        if template_file.exists():
            ep_preview.append({
                "title": "ExplorerPro Suite Template",
                "purpose": "Vollständige Suite-Dokumentation und Fusionsarchitektur (6 Tools)",
                "category": "ExplorerPro"
            })

    results["explorerpro"] = {
        "id": "explorerpro",
        "title": "Explorer Pro Suite",
        "description": "Intelligenter Datei-Explorer mit FTS5-Indizierung, Editor und Datenschutz-Ampel",
        "present": ep_found_path is not None,
        "path": str(ep_found_path) if ep_found_path else None,
        "available_files": ep_files,
        "preview_items": ep_preview,
        "can_import": ep_found_path is not None
    }

    return results


def import_external_artifact(artifact_name: str, conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Importiert ein belegtes Artefakt (profiprompt, promptboard, explorerpro) in die
    Prompt-DB (GUX-066). Fail-closed wenn Artefakt nicht vorhanden ist.
    """
    clean_art = artifact_name.strip().lower()
    artifacts = detect_external_artifacts()
    if clean_art not in artifacts or not artifacts[clean_art]["present"]:
        raise ValueError(f"Artefakt '{clean_art}' nicht auf dem System gefunden oder nicht importierbar")

    art_meta = artifacts[clean_art]
    path_root = Path(art_meta["path"])
    now_iso = datetime.now(timezone.utc).isoformat()
    imported_count = 0
    skipped_count = 0

    # Ensure prompt_templates table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            purpose TEXT,
            text TEXT NOT NULL,
            tags TEXT,
            category TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            tags TEXT,
            created_at TEXT
        )
    """)

    if clean_art == "profiprompt":
        export_files = list(path_root.rglob("profiprompt-library-v1.json"))
        if not export_files:
            raise ValueError("Keine profiprompt-library-v1.json im Artefaktordner gefunden")
        data = json.loads(export_files[0].read_text(encoding="utf-8"))
        prompts = data.get("prompts", [])
        for pr in prompts:
            p_name = pr.get("title") or pr.get("id")
            p_text = pr.get("text") or ""
            p_purpose = pr.get("purpose") or "ProfiPrompt Import"
            p_tags = ",".join(pr.get("tags", [])) if isinstance(pr.get("tags"), list) else str(pr.get("tags") or "")
            if not p_name or not p_text:
                continue
            cur = conn.execute("""
                INSERT OR IGNORE INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"ProfiPrompt: {p_name}", p_purpose, p_text, p_tags, "ProfiPrompt", now_iso, now_iso))
            if cur.rowcount:
                imported_count += 1
            else:
                skipped_count += 1
        conn.commit()

    elif clean_art == "promptboard":
        export_files = list(path_root.rglob("library.json"))
        if not export_files:
            raise ValueError("Keine library.json im PromptBoard-Ordner gefunden")
        data = json.loads(export_files[0].read_text(encoding="utf-8"))
        items = data.get("items", [])
        for it in items:
            i_name = it.get("name")
            i_content = it.get("content")
            if not i_name or not i_content:
                continue
            tags = ",".join(it.get("tags", [])) if isinstance(it.get("tags"), list) else str(it.get("tags") or "")
            cur = conn.execute("""
                INSERT OR IGNORE INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"PromptBoard: {i_name}", it.get("description", "PromptBoard Import"), i_content, tags, it.get("category") or "PromptBoard", now_iso, now_iso))
            if cur.rowcount:
                imported_count += 1
            else:
                skipped_count += 1
        conn.commit()

    elif clean_art == "explorerpro":
        tmpl_file = path_root / "SUITE_EXPLORERPRO_TEMPLATE.md"
        if not tmpl_file.exists():
            raise ValueError("SUITE_EXPLORERPRO_TEMPLATE.md nicht gefunden")
        content = tmpl_file.read_text(encoding="utf-8")
        cur = conn.execute("""
            INSERT OR IGNORE INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("ExplorerPro: Suite Template", "ExplorerPro Architektur- und Tool-Vorlage", content, "explorer,suite,docs", "ExplorerPro", now_iso, now_iso))
        if cur.rowcount:
            imported_count += 1
        else:
            skipped_count += 1
        conn.commit()

    return {
        "success": True,
        "artifact": clean_art,
        "imported": imported_count,
        "skipped": skipped_count,
        "source_path": str(path_root)
    }
