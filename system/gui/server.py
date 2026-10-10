#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

# -*- coding: utf-8 -*-

"""

BACH GUI Server v1.0

====================
FastAPI-basiertes Backend fuer das BACH Dashboard



Basiert auf: DaemonManager/backend.py

"""



import sys
import os

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import json
import re
import threading
import httpx

import sqlite3

from pathlib import Path

from datetime import datetime, date

from typing import Optional, List

from contextlib import asynccontextmanager

# BACH imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from hub.lang import t, get_lang
from hub.theme import ThemeHandler
from hub.task_audit import apply_task_field_changes, claim_task_atomic, GateReopenBlocked, LeaseRequired
from hub._services.chat.control_auth import get_control_api_auth_header
from gui.config import settings
from gui.console import mount_console

# Nutzerentscheid D-20260906-002 (2026-09-11) = B: Neue Tasks gehen per Default an den
# Idle-Worker; persoenliche Aufgaben weist der Nutzer bewusst "user" zu (Auswahlfeld in
# tasks.html / tasks_board.html, Liste aus /api/assignees). Der Tray-Idle-Worker pickt
# OLLAMA|BUDDHA|BACH und ueberspringt "user" ausdruecklich (chat_tray._process_idle_task).
# gui/api/headless.py fuehrt denselben Wert; test_default_task_assignee.py haelt beide gleich.
DEFAULT_TASK_ASSIGNEE = "OLLAMA"


def _refuse_if_foreign_domain(domain: str, operation: str) -> None:
    """Uebersetzt das Domaenen-Gate in einen HTTP-Status (T-20260822-624075478, Punkt 3).

    423 Locked statt 409 Conflict: Es geht nicht um einen Versionskonflikt, sondern um
    eine Domaene, die einem anderen Kanon gehoert und hier read-only konsumiert wird.
    Der Grundtext des Gates nennt Kanon, Projektionsvertrag und den Migrationsweg, also
    geht er unveraendert an den Aufrufer.
    """
    from hub.domain_writer_gate import blocked_reason

    reason = blocked_reason(domain, operation)
    if reason:
        raise HTTPException(status_code=423, detail=reason)

# Claude Router Import
sys.path.insert(0, str(Path(__file__).parent / "api"))
try:
    from claude_router import route_request
    CLAUDE_ROUTER_AVAILABLE = True
except ImportError:
    CLAUDE_ROUTER_AVAILABLE = False

# FastAPI imports

try:

    from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Query, WebSocket, WebSocketDisconnect, Body

    from fastapi.staticfiles import StaticFiles

    from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse, Response

    from fastapi.middleware.cors import CORSMiddleware

    from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

except ImportError:

    print("[ERROR] FastAPI nicht installiert!")

    print("        pip install fastapi uvicorn")

    sys.exit(1)



# Pfade

GUI_DIR = Path(__file__).parent

BACH_DIR = GUI_DIR.parent



# Recurring Tasks Import

sys.path.insert(0, str(BACH_DIR / "hub" / "_services" / "recurring"))

try:

    from recurring_tasks import list_recurring_tasks, check_recurring_tasks, trigger_recurring_task

    RECURRING_AVAILABLE = True

except ImportError:

    RECURRING_AVAILABLE = False

DATA_DIR = BACH_DIR / "data"

try:
    from hub.bach_paths import BACH_DB as _PATHS_DB
    BACH_DB = _PATHS_DB
except ImportError:
    BACH_DB = BACH_DB

USER_DB = BACH_DB

def _messages():
    """Store auf der kanonischen User-DB; fehlt sie, fail-closed wie get_user_db()."""
    from assistant_core import MessageStore  # Welle 1 (D-20260830-002)
    if not USER_DB.exists():
        raise FileNotFoundError(f"User-DB nicht gefunden: {USER_DB}")
    return MessageStore(USER_DB)


def _account_store():
    """AccountStore auf der kanonischen DB; fail-closed analog _messages() (Fix #1280, Regression c59b0da)."""
    from accounts_core import AccountStore  # Welle 2 (D-20260903-003 = A)
    if not BACH_DB.exists():
        raise FileNotFoundError(f"BACH-DB nicht gefunden: {BACH_DB}")
    return AccountStore(BACH_DB)

TEMPLATES_DIR = GUI_DIR / "templates"

try:
    from hub._services.cognitive_service import (
        ensure_denkarium_schema,
        archive_denkarium_entry,
        unarchive_denkarium_entry
    )
except ImportError:
    pass

STATIC_DIR = GUI_DIR / "static"

from hub._services.gui_contract_service import resolve_gui_distribution

ASTRO_DIST_DIR = resolve_gui_distribution(GUI_DIR, os.environ.get("ELLMOS_SYSTEM_GUI_DIST"))

HELP_DIR = BACH_DIR / "docs" / "help"
WIKI_DIR = BACH_DIR / "wiki"

SKILLS_DIR = BACH_DIR / "skills"
AGENTS_DIR = BACH_DIR / "agents"
EXPERTS_DIR = AGENTS_DIR / "_experts"

HIERARCHY_TYPE_TO_KEY = {
    "agent": "agents",
    "expert": "experts",
    "skill": "skills",
    "service": "services",
    "workflow": "workflows",
}

DIRECTORY_FILE_CANDIDATES = ("SKILL.md", "README.md", "CONCEPT.md", "ATI.md")
TEXT_FILE_SUFFIXES = (".md", ".txt", ".py")
PUBLIC_ERROR_MESSAGE = "Interner Fehler. Details stehen im Server-Log."
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}$")
SAFE_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
SAFE_CLI_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@ -]{0,127}$")
SAFE_PARTNER_NAMES = {"claude", "codex", "gemini", "kimi", "ollama"}
LOCAL_CHAT_HOSTS = {"", "127.0.0.1", "localhost", "::1"}
CHAT_CONTROL_PATHS = {
    "status", "backends", "models", "chat", "backend", "model", "mode",
    "think", "max_tool_rounds", "readiness",
    "clear", "fork", "history", "sessions", "session",
    "transcribe",
}


def _startspine_runtime_dir() -> Path:
    override = os.environ.get("BACH_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "BACH" / "runtime"
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "bach" / "runtime"


def _chat_control_base_url() -> str | None:
    discovery_path = _startspine_runtime_dir() / "discovery.json"
    try:
        discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        discovery = None
    if isinstance(discovery, dict):
        registered_root = discovery.get("root")
        try:
            same_root = (
                registered_root
                and Path(registered_root).resolve() == BACH_DIR.parent.resolve()
            )
        except (OSError, ValueError, TypeError):
            same_root = False
        services = discovery.get("services")
        if not same_root or not isinstance(services, dict):
            return None
        if "chat" in services:
            chat = services["chat"]
            if not isinstance(chat, dict):
                return None
            host = str(chat.get("host") or "")
            try:
                port = int(chat.get("actual_port"))
            except (TypeError, ValueError):
                port = 0
            if host in LOCAL_CHAT_HOSTS and 1 <= port <= 65535:
                return f"http://127.0.0.1:{port}/api"
            return None
        # Older Startspine discovery can register only the bridge. The proxy
        # checks the fallback listener's typed chat-control identity each time.

    try:
        port = int(os.environ.get("BACH_CONTROL_PORT", "8081"))
    except ValueError:
        return None
    if 1 <= port <= 65535:
        return f"http://127.0.0.1:{port}/api"
    return None


def _chat_control_payload_ready(payload) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("service") == "bach-chat-control"
        and isinstance(payload.get("telegram_verified"), bool)
    )


def _chat_proxy_timeout() -> float:
    try:
        timeout = float(os.environ.get("BACH_CHAT_PROXY_TIMEOUT_SECONDS", "960"))
    except ValueError:
        return 960.0
    return min(max(timeout, 10.0), 7200.0)


def public_error_message() -> str:
    return PUBLIC_ERROR_MESSAGE


def safe_path_segment(value: str, *, field_name: str = "Pfadsegment") -> str:
    segment = str(value or "")
    if (
        not segment
        or segment in {".", ".."}
        or "/" in segment
        or "\\" in segment
        or not SAFE_SEGMENT_RE.fullmatch(segment)
    ):
        raise HTTPException(status_code=400, detail=f"Ungueltiges {field_name}")
    return segment


def safe_tool_name(value: str) -> str:
    name = str(value or "")
    if not SAFE_TOOL_NAME_RE.fullmatch(name) or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Ungueltiger Tool-Name")
    return name


def safe_partner_name(value: str) -> str:
    partner = str(value or "claude").lower()
    if partner not in SAFE_PARTNER_NAMES:
        raise HTTPException(status_code=400, detail="Ungueltiger KI-Partner")
    return partner


def safe_cli_args(values) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="Argumente muessen eine Liste sein")
    args = []
    for value in values:
        arg = str(value)
        if "\x00" in arg or len(arg) > 500:
            raise HTTPException(status_code=400, detail="Ungueltiges Argument")
        args.append(arg)
    return args


def safe_cli_value(value, *, field_name: str) -> str:
    text = str(value or "")
    if not SAFE_CLI_VALUE_RE.fullmatch(text):
        raise HTTPException(status_code=400, detail=f"Ungueltiger Wert fuer {field_name}")
    return text


def resolve_under_base(base: Path, value: str, *, allowed_suffixes=None, must_exist: bool = False) -> Path:
    base_resolved = base.resolve()
    raw = Path(str(value or ""))
    if raw.is_absolute():
        candidate = raw.resolve(strict=False)
    else:
        candidate = (base_resolved / raw).resolve(strict=False)
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Zugriff verweigert") from exc
    if allowed_suffixes and candidate.suffix.lower() not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Dateityp nicht erlaubt")
    if must_exist and not candidate.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return candidate


def resolve_child_file(base: Path, filename: str, *, allowed_suffixes=None, must_exist: bool = False) -> Path:
    safe_name = safe_path_segment(filename, field_name="Dateiname")
    return resolve_under_base(base, safe_name, allowed_suffixes=allowed_suffixes, must_exist=must_exist)


def resolve_configured_dir(config: dict, key: str, default_dir: Path) -> Path:
    configured = config.get("settings", {}).get(key)
    if configured:
        return resolve_under_base(BACH_DIR, str(configured))
    return default_dir.resolve(strict=False)


def write_private_text_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


def resolve_tool_file(name: str) -> Optional[Path]:
    safe_name = safe_tool_name(name)
    direct = resolve_child_file(TOOLS_DIR, f"{safe_name}.py", allowed_suffixes={".py"})
    if direct.exists() and direct.is_file():
        return direct

    tools_root = TOOLS_DIR.resolve()
    for candidate in sorted(TOOLS_DIR.rglob("*.py")):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(tools_root)
        except ValueError:
            continue
        if resolved.stem == safe_name:
            return resolved
    return None


def resolve_workflow_file(workflow_name: str) -> Optional[Path]:
    workflows_dir = SKILLS_DIR / "_workflows"
    safe_name = safe_path_segment(workflow_name, field_name="Workflow-Name")
    candidates = [safe_name]
    if not safe_name.endswith(".md"):
        candidates.insert(0, f"{safe_name}.md")
    for candidate_name in candidates:
        candidate = resolve_under_base(workflows_dir, candidate_name, allowed_suffixes={".md"})
        if candidate.exists() and candidate.is_file():
            return candidate
    return None



# ═══════════════════════════════════════════════════════════════

# PYDANTIC MODELS

# ═══════════════════════════════════════════════════════════════



class TaskCreate(BaseModel):

    title: str

    description: Optional[str] = None

    priority: str = "P3"

    project: Optional[str] = None

    assignee: Optional[str] = None

    assigned_to: Optional[str] = DEFAULT_TASK_ASSIGNEE

    created_by: Optional[str] = "user"
    required_model: Optional[str] = None
    assigned_slot: Optional[str] = None


class ThemeUpdate(BaseModel):
    theme: str
    custom: Optional[dict[str, str]] = None



class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    project: Optional[str] = None
    category: Optional[str] = None
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    depends_on: Optional[str] = None
    due_date: Optional[str] = None
    required_model: Optional[str] = None
    assigned_slot: Optional[str] = None
    assignment_configuration_version: Optional[str] = None
    changed_by: Optional[str] = None
    # T-20260916-1330: bewusster Operator-Reopen eines terminal-geparkten Tasks
    allow_reopen: Optional[bool] = False





class MessageCreate(BaseModel):

    recipient: str

    subject: Optional[str] = None

    body: str

    priority: int = 0



class DaemonJobCreate(BaseModel):

    name: str

    description: Optional[str] = None

    job_type: str = "interval"

    schedule: str

    command: str

    script_path: Optional[str] = None

    arguments: Optional[str] = None



class ChainCreate(BaseModel):

    name: str

    description: Optional[str] = None

    trigger_type: str = "manual"

    trigger_value: Optional[str] = None

    steps_json: str = "[]"

    is_active: int = 1



class ChainUpdate(BaseModel):

    name: Optional[str] = None

    description: Optional[str] = None

    trigger_type: Optional[str] = None

    trigger_value: Optional[str] = None

    steps_json: Optional[str] = None

    is_active: Optional[int] = None



class ScanConfigUpdate(BaseModel):

    key: str

    value: str



class BerichtExport(BaseModel):

    folder: str

    password: str



class BerichtGenerate(BaseModel):

    json_path: str

    output_path: str

    template_path: Optional[str] = None



class FileUpdateRequest(BaseModel):

    path: str

    content: str



class InsuranceModel(BaseModel):

    anbieter: str

    tarif_name: Optional[str] = None

    police_nr: Optional[str] = None

    sparte: str

    status: Optional[str] = "aktiv"

    beginn_datum: Optional[str] = None

    ablauf_datum: Optional[str] = None

    kuendigungsfrist_monate: Optional[int] = 3

    verlaengerung_monate: Optional[int] = 12

    beitrag: Optional[float] = 0.0

    zahlweise: Optional[str] = "monatlich"

    steuer_relevant_typ: Optional[str] = None

    ordner_pfad: Optional[str] = None

    notizen: Optional[str] = None



class ContractModel(BaseModel):

    name: str

    kategorie: Optional[str] = "sonstiges"

    anbieter: Optional[str] = None

    kundennummer: Optional[str] = None

    vertragsnummer: Optional[str] = None

    betrag: Optional[float] = 0.0

    waehrung: str = "EUR"

    intervall: Optional[str] = "monatlich"

    naechste_zahlung: Optional[str] = None

    beginn_datum: Optional[str] = None

    mindestlaufzeit_monate: Optional[int] = 0

    kuendigungsfrist_tage: Optional[int] = 30

    verlaengerung_monate: Optional[int] = 12

    ablauf_datum: Optional[str] = None

    kuendigungs_status: str = "aktiv"

    dokument_pfad: Optional[str] = None

    web_login_url: Optional[str] = None



class MountAdd(BaseModel):

    path: str

    alias: str





# ═══════════════════════════════════════════════════════════════

# WEBSOCKET CONNECTION MANAGER (GUI_003a/b)

# ═══════════════════════════════════════════════════════════════



class ConnectionManager:

    """Verwaltet aktive WebSocket-Verbindungen fuer Real-time Updates."""

    

    def __init__(self):

        self.active_connections: list[WebSocket] = []

    

    async def connect(self, websocket: WebSocket):

        """Neue Verbindung akzeptieren."""

        offered = websocket.scope.get("subprotocols") or []

        await websocket.accept(subprotocol=WS_PROTOCOL if WS_PROTOCOL in offered else None)

        self.active_connections.append(websocket)

        print(f"[WEBSOCKET] Client verbunden. Aktive: {len(self.active_connections)}")

    

    def disconnect(self, websocket: WebSocket):

        """Verbindung entfernen."""

        if websocket in self.active_connections:

            self.active_connections.remove(websocket)

        print(f"[WEBSOCKET] Client getrennt. Aktive: {len(self.active_connections)}")

    

    async def broadcast(self, message: dict):

        """Nachricht an alle verbundenen Clients senden."""

        disconnected = []

        for connection in self.active_connections:

            try:

                await connection.send_json(message)

            except Exception:

                disconnected.append(connection)

        # Tote Verbindungen entfernen

        for conn in disconnected:

            self.disconnect(conn)



# Globale Instanz

ws_manager = ConnectionManager()



# ═══════════════════════════════════════════════════════════════

# DATABASE HELPERS

# ═══════════════════════════════════════════════════════════════



def get_user_db():

    """User-DB Verbindung mit Row-Factory."""

    if not USER_DB.exists():

        raise FileNotFoundError(f"User-DB nicht gefunden: {USER_DB}")

    conn = sqlite3.connect(USER_DB)

    conn.row_factory = sqlite3.Row

    return conn



def get_bach_db():

    """System-DB Verbindung."""

    if not BACH_DB.exists():

        raise FileNotFoundError(f"BACH-DB nicht gefunden: {BACH_DB}")

    conn = sqlite3.connect(BACH_DB)

    conn.row_factory = sqlite3.Row

    return conn



def row_to_dict(row):

    """Konvertiert sqlite3.Row zu dict."""

    if row is None:

        return None

    return dict(row)



def rows_to_list(rows):

    """Konvertiert Liste von Rows zu Liste von dicts."""

    return [dict(row) for row in rows]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:

    """Prueft ob eine SQLite-Tabelle existiert."""

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def empty_skills_hierarchy() -> dict:

    """Leere Default-Struktur fuer das Skills Board."""

    return {
        "items": {key: [] for key in HIERARCHY_TYPE_TO_KEY.values()},
        "assignments": {},
        "_meta": {
            "source": "empty",
            "generated_at": datetime.now().isoformat(),
        },
    }


def hierarchy_has_items(data: dict) -> bool:

    """Prueft ob ein Hierarchie-Payload befuellte Items enthaelt."""

    if not isinstance(data, dict):
        return False

    items = data.get("items")
    if not isinstance(items, dict):
        return False

    return any(bool(items.get(key)) for key in HIERARCHY_TYPE_TO_KEY.values())


def pretty_label(value: str) -> str:

    """Erzeugt eine lesbare Fallback-Beschriftung."""

    if not value:
        return ""
    return value.replace("_", " ").replace("-", " ").strip().title()


def infer_agent_dashboard(name: str) -> Optional[str]:

    """Leitet eine Dashboard-URL fuer bekannte Agenten ab."""

    if not name:
        return None

    if name in {"ati", "developer-assistent"}:
        return "/agents/ati"
    if "steuer" in name:
        return "/agents/steuer"
    if "gesundheit" in name:
        return "/agents/gesundheit"
    if "persoenlich" in name:
        return "/agents/persoenlich"
    if "foerder" in name:
        return "/agents/foerderplaner"
    if "buero" in name:
        return "/agents"
    return None


def infer_expert_dashboard(name: str) -> Optional[str]:

    """Leitet eine Dashboard-URL fuer bekannte Experten ab."""

    if not name:
        return None

    if name == "steuer-agent":
        return "/agents/steuer"
    if name in {"foerderplaner", "report_generator"}:
        return "/agents/foerderplaner"
    if "gesundheit" in name:
        return "/agents/gesundheit"
    return None


def pick_directory_file(directory: Path, stem_hint: str = "") -> Optional[Path]:

    """Waehlt eine sinnvolle Hauptdatei aus einem Verzeichnis."""

    if not directory.exists() or not directory.is_dir():
        return None

    candidates = []
    if stem_hint:
        raw_stem = str(stem_hint).replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if SAFE_SEGMENT_RE.fullmatch(raw_stem):
            candidates.extend((f"{raw_stem}.md", f"{raw_stem}.txt", f"{raw_stem}.py"))
    candidates.extend(DIRECTORY_FILE_CANDIDATES)

    seen = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        candidate = directory / name
        if candidate.exists() and candidate.is_file():
            return candidate

    for child in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        if child.is_file() and child.suffix.lower() in TEXT_FILE_SUFFIXES:
            return child

    return None


def resolve_path_hint(path_hint: str) -> Optional[Path]:

    """Versucht eine veraltete oder relative Pfadangabe robust auf eine Datei abzubilden."""

    if not path_hint:
        return None

    normalized = path_hint.replace("\\", "/").strip()
    try:
        candidate_paths = [resolve_under_base(BACH_DIR, normalized)]
    except HTTPException:
        return None

    for candidate in candidate_paths:
        if candidate.exists():
            if candidate.is_file():
                return candidate
            picked = pick_directory_file(candidate, candidate.name)
            if picked:
                return picked

        if candidate.suffix:
            stem_dir = candidate.with_suffix("")
            if stem_dir.exists() and stem_dir.is_dir():
                picked = pick_directory_file(stem_dir, candidate.stem)
                if picked:
                    return picked

            sibling_dir = candidate.parent / candidate.stem
            if sibling_dir.exists() and sibling_dir.is_dir():
                picked = pick_directory_file(sibling_dir, candidate.stem)
                if picked:
                    return picked

    return None


def load_skills_board_from_db() -> dict:

    """Baut einen Hierarchie-Payload direkt aus bach.db auf."""

    data = empty_skills_hierarchy()

    try:
        conn = get_bach_db()
    except Exception:
        return data

    try:
        # Boss agents / main agents are the authoritative top-level nodes.
        if table_exists(conn, "bach_agents"):
            rows = conn.execute(
                """
                SELECT name, display_name, description, skill_path, is_active, priority, id
                FROM bach_agents
                WHERE is_active = 1
                ORDER BY priority DESC, id ASC
                """
            ).fetchall()

            seen = set()
            for row in rows:
                item_id = row["name"]
                if item_id in seen:
                    continue
                seen.add(item_id)
                data["items"]["agents"].append(
                    {
                        "id": item_id,
                        "name": row["display_name"] or pretty_label(item_id),
                        "description": row["description"] or pretty_label(item_id),
                        "dashboard": infer_agent_dashboard(item_id),
                        "status": "active",
                        "path_hint": row["skill_path"],
                    }
                )

        if table_exists(conn, "bach_experts"):
            rows = conn.execute(
                """
                SELECT id, name, display_name, description, skill_path, agent_id
                FROM bach_experts
                WHERE is_active = 1
                ORDER BY id ASC
                """
            ).fetchall()

            seen = set()
            agent_name_by_id = {}
            if table_exists(conn, "bach_agents"):
                for row in conn.execute(
                    "SELECT id, name FROM bach_agents WHERE is_active = 1 ORDER BY id ASC"
                ).fetchall():
                    agent_name_by_id.setdefault(row["id"], row["name"])

            for row in rows:
                item_id = row["name"]
                if item_id not in seen:
                    seen.add(item_id)
                    data["items"]["experts"].append(
                        {
                            "id": item_id,
                            "name": row["display_name"] or pretty_label(item_id),
                            "description": row["description"] or pretty_label(item_id),
                            "dashboard": infer_expert_dashboard(item_id),
                            "status": "active",
                            "path_hint": row["skill_path"],
                        }
                    )

                parent_id = agent_name_by_id.get(row["agent_id"])
                if parent_id:
                    assignment = data["assignments"].setdefault(
                        parent_id,
                        {"experts": [], "skills": [], "services": [], "workflows": []},
                    )
                    if item_id not in assignment["experts"]:
                        assignment["experts"].append(item_id)

        if table_exists(conn, "hierarchy_items"):
            rows = conn.execute(
                """
                SELECT id, type, name, description, dashboard_url, status
                FROM hierarchy_items
                WHERE status = 'active' AND type IN ('skill', 'service', 'workflow')
                ORDER BY type, name, id
                """
            ).fetchall()

            seen_by_key = {
                "skills": set(),
                "services": set(),
                "workflows": set(),
            }
            for row in rows:
                key = HIERARCHY_TYPE_TO_KEY.get(row["type"])
                if key not in seen_by_key:
                    continue
                if row["id"] in seen_by_key[key]:
                    continue
                seen_by_key[key].add(row["id"])
                data["items"][key].append(
                    {
                        "id": row["id"],
                        "name": row["name"] or pretty_label(row["id"]),
                        "description": row["description"],
                        "dashboard": row["dashboard_url"],
                        "status": row["status"],
                    }
                )
        elif table_exists(conn, "skills"):
            rows = conn.execute(
                """
                SELECT id, name, type, description, path
                FROM skills
                WHERE is_active = 1 AND type IN ('skill', 'service', 'protocol')
                ORDER BY type, name, id
                """
            ).fetchall()

            legacy_type_map = {
                "skill": "skills",
                "service": "services",
                "protocol": "workflows",
            }
            seen_by_key = {key: set() for key in legacy_type_map.values()}
            for row in rows:
                key = legacy_type_map.get(row["type"])
                if not key or row["id"] in seen_by_key[key]:
                    continue
                seen_by_key[key].add(row["id"])
                data["items"][key].append(
                    {
                        "id": str(row["id"]),
                        "name": row["name"] or pretty_label(str(row["id"])),
                        "description": row["description"],
                        "status": "active",
                        "path_hint": row["path"],
                    }
                )

        if table_exists(conn, "hierarchy_assignments"):
            valid_targets = {
                key: {item["id"] for item in data["items"][key]}
                for key in HIERARCHY_TYPE_TO_KEY.values()
            }
            rows = conn.execute(
                """
                SELECT parent_id, child_id, child_type
                FROM hierarchy_assignments
                ORDER BY parent_id, child_type, assignment_order, child_id
                """
            ).fetchall()

            for row in rows:
                parent_id = row["parent_id"]
                child_key = HIERARCHY_TYPE_TO_KEY.get(row["child_type"])
                child_id = row["child_id"]

                if parent_id not in valid_targets["agents"] or child_key is None:
                    continue
                if child_id not in valid_targets[child_key]:
                    continue

                assignment = data["assignments"].setdefault(
                    parent_id,
                    {"experts": [], "skills": [], "services": [], "workflows": []},
                )
                if child_id not in assignment[child_key]:
                    assignment[child_key].append(child_id)

        for key in data["items"]:
            data["items"][key].sort(key=lambda item: (item.get("name") or item["id"]).lower())

        for assignment in data["assignments"].values():
            for key, values in assignment.items():
                assignment[key] = sorted(values, key=str.lower)

        data["_meta"] = {
            "source": "bach.db",
            "generated_at": datetime.now().isoformat(),
        }
        return data
    finally:
        conn.close()



# ═══════════════════════════════════════════════════════════════

# APP SETUP

# ═══════════════════════════════════════════════════════════════



@asynccontextmanager

async def lifespan(app: FastAPI):

    """Startup/Shutdown Handler."""

    print(f"[BACH GUI] Server startet...")

    print(f"           BACH_DIR: {BACH_DIR}")

    print(f"           USER_DB:  {USER_DB}")

    try:

        init_financial_tables()

    except Exception as exc:  # noqa: BLE001 - startup must not fail on optional tables

        print(f"[BACH GUI] Financial-Tabellen nicht initialisiert: {type(exc).__name__}")

    

    # File Watcher für Live-Updates (Phase 4.3)

    file_watcher = None

    try:

        from gui.file_watcher import init_watcher, WATCHDOG_AVAILABLE

        from gui.sync_service import on_file_change

        import asyncio



        if WATCHDOG_AVAILABLE:

            # Event-Loop für threadsafe broadcast

            loop = asyncio.get_running_loop()

            

            def combined_callback(event_type: str, path: str, file_type: str):

                """Callback für Dateiänderungen - sendet WebSocket-Broadcast UND führt Sync aus."""

                print(f"[FILE-WATCHER] {event_type}: {path} ({file_type})")

                

                # 1. DB Sync (Task #439)

                on_file_change(event_type, path, file_type)

                

                # 2. WebSocket-Broadcast (GUI_003b)

                message = {

                    "type": "file_change",

                    "payload": {

                        "event": event_type,

                        "path": path,

                        "file_type": file_type

                    }

                }

                try:

                    asyncio.run_coroutine_threadsafe(

                        ws_manager.broadcast(message), 

                        loop

                    )

                except Exception as e:

                    print(f"[FILE-WATCHER] Broadcast-Fehler: {e}")

            

            file_watcher = init_watcher(combined_callback)

            if file_watcher.start():

                print(f"[BACH GUI] File-Watcher gestartet (mit SyncService)")

    except Exception as e:

        print(f"[BACH GUI] File-Watcher Fehler: {e}")

    

    yield

    

    # Cleanup

    if file_watcher:

        file_watcher.stop()

        print(f"[BACH GUI] File-Watcher gestoppt")

    print(f"[BACH GUI] Server beendet.")



app = FastAPI(

    title="BACH Dashboard API",

    version="1.1.8",

    description="REST-API fuer das BACH v1.1 Dashboard",

    lifespan=lifespan

)



# CORS erlauben (fuer lokale Entwicklung)

app.add_middleware(

    CORSMiddleware,

    allow_origins=[],

    allow_credentials=False,

    allow_methods=["*"],

    allow_headers=["*"],

)


@app.exception_handler(FileNotFoundError)
async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Datenbank nicht verfügbar: {exc}"}
    )


# Cache-Control Middleware - verhindert Browser-Caching (v1.1.82)

from starlette.middleware.base import BaseHTTPMiddleware



class NoCacheMiddleware(BaseHTTPMiddleware):

    """Setzt No-Cache Header fuer alle API und HTML Responses."""

    async def dispatch(self, request, call_next):

        response = await call_next(request)

        # Nur fuer API und HTML, nicht fuer statische Assets wie Bilder

        path = request.url.path

        if path.startswith("/api/") or path.endswith(".html") or path == "/":

            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

            response.headers["Pragma"] = "no-cache"

            response.headers["Expires"] = "0"

        return response



app.add_middleware(NoCacheMiddleware)

# ── Device-Token Authentication Middleware (Task #1499) ─────────
try:
    from gui.device_auth import (
        create_device,
        has_active_devices,
        list_devices,
        revoke_device,
        validate_token,
    )
except ImportError:
    try:
        from device_auth import (  # type: ignore
            create_device,
            has_active_devices,
            list_devices,
            revoke_device,
            validate_token,
        )
    except ImportError:
        import importlib.util
        _devauth_path = Path(__file__).parent / "device_auth.py"
        _spec = importlib.util.spec_from_file_location("device_auth", _devauth_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        create_device = _mod.create_device
        has_active_devices = _mod.has_active_devices
        list_devices = _mod.list_devices
        revoke_device = _mod.revoke_device
        validate_token = _mod.validate_token


# ── Perimeter helpers shared by HTTP middleware and the WebSocket handshake ──

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


_DNS_LABEL_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")


def _split_host_port(value: str):
    """Strictly parse "host", "host:port", "[v6]" or "[v6]:port"; None if malformed.

    Anything else (userinfo, paths, suffixes after "]", bare IPv6, non-numeric or
    out-of-range ports, odd characters) is rejected instead of being guessed at.
    """
    import ipaddress
    value = (value or "").strip().lower()
    port = None
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        rest = value[end + 1:]
        if rest:
            if not rest.startswith(":"):
                return None
            port_text = rest[1:]
        else:
            port_text = ""
        try:
            host = ipaddress.IPv6Address(value[1:end]).compressed
        except ValueError:
            return None
    else:
        if value.count(":") > 1:
            return None
        host, _, port_text = value.partition(":")
        host = host.rstrip(".")
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            if not _DNS_LABEL_HOST.match(host):
                return None
    if port_text:
        if not (port_text.isascii() and port_text.isdigit()) or not 0 < int(port_text) < 65536:
            return None
        port = int(port_text)
    elif value.endswith(":"):
        return None
    return (host, port) if host else None


def _hostname(host_header: str) -> str:
    """Normalised hostname of a Host header value without port; "" if malformed."""
    parsed = _split_host_port(host_header)
    return parsed[0] if parsed else ""


def allowed_hosts() -> frozenset:
    """Hosts this GUI answers to: loopback plus BACH_GUI_ALLOWED_HOSTS (comma separated)."""
    configured = os.environ.get("BACH_GUI_ALLOWED_HOSTS", "")
    extra = {_hostname(item) for item in configured.split(",") if item.strip()}
    return LOOPBACK_HOSTS | {item for item in extra if item}


def host_is_allowed(host_header: str) -> bool:
    """Host allowlist against DNS rebinding: an Origin derived from Host proves nothing."""
    name = _hostname(host_header)
    return bool(name) and name in allowed_hosts()


def origin_matches_host(origin: str, host_header: str, request_scheme: str = "ws") -> bool:
    """True if an Origin is exactly the origin of this request: scheme, host and port.

    ws -> http, wss -> https (behind a TLS-terminating proxy run uvicorn with
    --proxy-headers so the scope scheme is right). Default ports are implied by the
    scheme. "null", userinfo, paths and queries never match.
    """
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(origin)
        origin_port = parts.port
        origin_host = parts.hostname
    except ValueError:
        return False
    expected_scheme = {"ws": "http", "wss": "https", "http": "http", "https": "https"}.get(request_scheme)
    if (parts.scheme != expected_scheme or not origin_host or parts.username is not None
            or parts.password is not None or parts.path not in ("", "/")
            or parts.query or parts.fragment):
        return False
    host = _split_host_port(host_header)
    if host is None:
        return False
    default = 443 if expected_scheme == "https" else 80
    if _hostname(origin_host if ":" not in origin_host else f"[{origin_host}]") != host[0]:
        return False
    return (origin_port or default) == (host[1] or default)


# ── Never log WebSocket token subprotocols (Sec-WebSocket-Protocol) ──
_WS_TOKEN_RE = re.compile(r"bach\.token\.[A-Za-z0-9_.~+/=-]+")
_REDACT_LOGGERS = ("websockets", "uvicorn", "starlette", "fastapi", "asyncio")


def _redact_ws_tokens(text: str) -> str:
    return _WS_TOKEN_RE.sub("bach.token.[redacted]", text)


def _install_log_redaction():
    """Wrap the LogRecord factory so server/WebSocket-library records never carry tokens."""
    import logging
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_bach_redacts", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            if record.name.startswith(_REDACT_LOGGERS):
                message = record.getMessage()
                if "bach.token." in message:
                    record.msg, record.args = _redact_ws_tokens(message), ()
        except Exception:  # logging must never break the request
            pass
        return record

    factory._bach_redacts = True
    logging.setLogRecordFactory(factory)


_install_log_redaction()

WS_PROTOCOL = "bach.v1"
WS_TOKEN_PROTOCOL_PREFIX = "bach.token."


def websocket_device_token(websocket) -> str:
    """Device token of a WebSocket handshake: Authorization header, cookie or subprotocol.

    Never from the URL (query strings end up in logs and history). Browsers cannot set
    headers on WebSocket, so they pass ["bach.v1", "bach.token.<token>"] as subprotocols.
    """
    auth = websocket.headers.get("authorization", "").strip()
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    cookie = websocket.cookies.get("bach_device_token", "").strip()
    if cookie:
        return cookie
    offered = websocket.scope.get("subprotocols") or []
    if WS_PROTOCOL in offered:
        for proto in offered:
            if proto.startswith(WS_TOKEN_PROTOCOL_PREFIX):
                return proto[len(WS_TOKEN_PROTOCOL_PREFIX):].strip()
    return ""


async def authorize_websocket(websocket) -> bool:
    """Handshake check; on failure the socket is closed BEFORE it is accepted."""
    try:
        host = websocket.headers.get("host", "")
        origin = websocket.headers.get("origin")
        # Browsers always send Origin on WebSocket handshakes: when present it must be
        # this server's own origin (a "null" origin is rejected). Native clients send
        # none; they stay allowed, but only with a valid device token below.
        ok = host_is_allowed(host) and (
            origin is None
            or origin_matches_host(origin, host, websocket.scope.get("scheme", "ws")))
        if ok:
            token = websocket_device_token(websocket)
            ok = bool(token) and bool(validate_token(token))
    except Exception:
        ok = False  # fail closed, never report why
    if not ok:
        await websocket.close(code=1008)
    return ok


class DeviceAuthMiddleware(BaseHTTPMiddleware):
    """Require device credentials for private APIs, including loopback clients."""

    # DEFAULT-DENY: every path not listed here needs a registered device token.
    # New routes are therefore protected automatically; making one public is a
    # deliberate edit of these lists (and of tests/test_gui_perimeter.py).
    #
    # Page shells are static HTML (or redirects) that fetch their data from /api/
    # with the token from localStorage; browsers cannot attach that token to a
    # navigation, so the shells themselves must be public. They carry no user data.
    PUBLIC_PAGE_PATHS = frozenset({
        "/unified",
        "/ocean",
        "/",
        "/agenten/fabrika",
        "/agenten/blueprints",
        "/agenten/running",
        "/agenten/marblerun",
        "/governance",
        "/governance/funk",
        "/governance/usecases",
        "/governance/logs",
        "/life",
        "/domains",
        "/artefakte",
        "/agenten/sessions",
        "/inbox",
        "/daemon",
        "/tasks",
        "/user-inbox",
        "/messages",
        "/reports",
        "/help",
        "/maintenance",
        "/logs",
        "/chat",
        "/settings",
        "/system",
        "/wiki",
        "/agents",
        "/agents/ati",
        "/ati",
        "/partners",
        "/agents/steuer",
        "/agents/gesundheit",
        "/agents/persoenlich",
        "/agents/foerderplaner",
        "/skills-board",
        "/agents-board",
        "/skills",
        "/skills/plugins",
        "/skills/mcp",
        "/skills/software",
        "/skills/ocean",
        "/finanzen",
        "/steuer",
        "/gesundheit",
        "/persoenlich",
        "/routines",
        "/denkarium",
        "/tokens",
        "/token-dashboard",
        "/tasks-board",
        "/financial",
        "/memory",
        "/tools",
        "/prompt-generator",
        "/prompt-library",
        "/usecases",
        "/kontakte",
        "/routinen",
        "/anonymization",
        "/anonymizer",
        "/foerderplaner",
        "/steuer-assistent",
        "/workflow-tuev",
        "/favicon.ico",
        "/device-fetch.js",
    })
    # Static assets (JS/CSS/images/fonts) without data.
    PUBLIC_STATIC_PREFIXES = ("/static/", "/_astro/")

    EXEMPT_API_PATHS = {
        "/api/health",
        "/api/devices/verify",
        "/api/gui/backend-origin",
        "/api/gui/brand",
        "/api/gui/kit-manifest",
        "/api/gui/architecture/concepts",
        "/api/capabilities/mcp/cookbooks",
        "/api/learning/hermes/stats",
        "/api/learning/hermes/candidates",
        "/api/learning/nemofold/stats",
        "/api/learning/nemofold/candidates",
        "/api/chat/compare-race/lanes",
        "/api/chat/buddha/compare-race/lanes",
        "/api/chat/compare-race/history",
        "/api/chat/buddha/compare-race/history",
        "/api/chat/buddha/compare-race",
        "/api/chat/compare-race/buddha",
        "/api/domains/installed",
        "/api/domains/pins",
    }

    async def _require_device(self, request: Request, call_next):
        """Token gate for everything that is not explicitly public."""
        auth_header = request.headers.get("Authorization", "").strip()
        token = (auth_header[7:].strip() if auth_header.startswith("Bearer ")
                 else request.cookies.get("bach_device_token", "").strip())
        if not token:
            return JSONResponse(status_code=401, content={"error": "Geräteanmeldung erforderlich"})
        device = validate_token(token)
        if not device:
            return JSONResponse(status_code=403, content={"error": "Geräteschlüssel ungültig oder widerrufen"})
        request.state.device = device
        return await call_next(request)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 1. Default-deny outside /api/: only the explicit page/asset allowlist passes.
        #    (/docs, /openapi.json, /redoc and the /control mount need a token too.)
        if not path.startswith("/api/"):
            if ((request.method in ("GET", "HEAD")
                    and (path in self.PUBLIC_PAGE_PATHS
                         or path.startswith(self.PUBLIC_STATIC_PREFIXES)))):
                return await call_next(request)
            return await self._require_device(request, call_next)

        # A browser talking to localhost is still a loopback client. Reject
        # cross-origin requests before credentials or any API handler runs.
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        if ((origin is not None and origin != same_origin)
                or request.headers.get("sec-fetch-site") == "cross-site"):
            return JSONResponse(status_code=403, content={"detail": "Cross-origin API request denied"})

        # 2. Status & probe endpoints pass through
        if path in self.EXEMPT_API_PATHS or (path in {"/api/nav/config", "/api/domains/installed", "/api/domains/pins", "/api/gui/capabilities"} and request.method == "GET"):
            return await call_next(request)

        # The browser authenticates as a registered device. The proxy supplies
        # its separate Control credential only on the trusted loopback hop.
        if (path.startswith("/api/chat-control/") and request.method in {"GET", "POST"}
                and path.removeprefix("/api/chat-control/") in CHAT_CONTROL_PATHS):
            auth_header = request.headers.get("Authorization", "").strip()
            device_token = (auth_header[7:].strip() if auth_header.startswith("Bearer ")
                            else request.cookies.get("bach_device_token"))
            if not device_token:
                return JSONResponse(status_code=401, content={"error": "Geräteanmeldung erforderlich"})
            device = validate_token(device_token)
            if not device:
                return JSONResponse(status_code=403, content={"error": "Geräteschlüssel ungültig oder widerrufen"})
            request.state.device = device
            return await call_next(request)

        # 3. Credentials belong in headers or cookies, never URLs.
        auth_header = request.headers.get("Authorization", "").strip()
        bearer_token = None
        if auth_header.startswith("Bearer "):
            bearer_token = auth_header[7:].strip()
        elif request.cookies.get("bach_device_token"):
            bearer_token = request.cookies.get("bach_device_token")

        # Inbox paths expose private file names, previews and sorting actions.
        # Require a registered device even on loopback and with no devices set up.
        if (path == "/api/inbox" or path.startswith("/api/inbox/")
                or path == "/api/mounts" or path.startswith("/api/mounts/")
                or path == "/api/artifacts" or path.startswith("/api/artifacts/")
                or path == "/api/artefakte"
                or path in {"/api/system/cluster-cockpit", "/api/system/fackel"}
                or path == "/api/system/core-agents" or path.startswith("/api/system/core-agents/")
                or path == "/api/system/core-prompts" or path.startswith("/api/system/core-prompts/")
                or path == "/api/governance/audit"
                or path == "/api/daemon" or path.startswith("/api/daemon/")
                or (path == "/api/settings/theme" and request.method == "PUT")):
            private_token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else request.cookies.get("bach_device_token")
            if not private_token:
                return JSONResponse(status_code=401, content={"error": "Geräteanmeldung erforderlich"})
            device = validate_token(private_token)
            if not device:
                return JSONResponse(status_code=403, content={"error": "Geräteschlüssel ungültig oder widerrufen"})
            request.state.device = device
            return await call_next(request)

        # Memory and Agent Studio responses contain private notes and persona
        # prompts. Transitional and loopback fallbacks must not expose them.
        if (path == "/api/calendar" or path.startswith("/api/calendar/")
                or path == "/api/routines" or path.startswith("/api/routines/")
                or path == "/api/memory" or path.startswith("/api/memory/")
                or path == "/api/gardener" or path.startswith("/api/gardener/")
                or path == "/api/agent-studio" or path.startswith("/api/agent-studio/")):
            private_token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else request.cookies.get("bach_device_token")
            if not private_token:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Missing device authorization token", "detail": "Unauthorized"},
                )
            device = validate_token(private_token)
            if not device:
                return JSONResponse(
                    status_code=403,
                    content={"error": "Invalid or revoked device token", "detail": "Forbidden"},
                )
            request.state.device = device
            return await call_next(request)

        # If a token was supplied, validate it
        if bearer_token:
            device = validate_token(bearer_token)
            if not device:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid or revoked device token", "detail": "Unauthorized"},
                )
            request.state.device = device
            return await call_next(request)

        # Unconfigured and loopback systems fail closed too. Initial device
        # provisioning is an explicit local administration action.
        return JSONResponse(
            status_code=401,
            content={"error": "Missing device authorization token", "detail": "Unauthorized"},
        )


class SharedGUIReleaseMiddleware(BaseHTTPMiddleware):
    """An explicit shared release cannot silently render a legacy page."""

    async def dispatch(self, request: Request, call_next):
        if os.environ.get("ELLMOS_SYSTEM_GUI_DIST") and request.method in {"GET", "HEAD"}:
            from gui.api.gui_capabilities import PAGE_READS
            page = request.url.path.rstrip("/") or "/"
            if page in PAGE_READS:
                filename = "index.html" if page == "/" else page.lstrip("/") + ".html"
                target = ASTRO_DIST_DIR / filename
                if not target.is_file() or target.is_symlink():
                    return JSONResponse({"detail": "Configured shared GUI page is unavailable",
                                         "reason_code": "shared_gui_page_missing"}, status_code=503)
        return await call_next(request)


app.add_middleware(SharedGUIReleaseMiddleware)
app.add_middleware(DeviceAuthMiddleware)


class HostAllowlistMiddleware:
    """Pure ASGI gate (HTTP and WebSocket): reject unknown Host headers (DNS rebinding).

    An attacker's page rebinding its domain to 127.0.0.1 is same-origin to the browser, so
    the Origin check alone cannot stop it; the Host header still names the attacker domain.
    Runs outermost, before any credential or handler logic.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
            if not host_is_allowed(host):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    body = b"Host not allowed"
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"text/plain"),
                                            (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                return
        await self.inner(scope, receive, send)


app.add_middleware(HostAllowlistMiddleware)

try:
    from gui.api.unified_api import router as unified_router
    app.include_router(unified_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("Unified API Router konnte nicht geladen werden: %s", e)

try:
    from gui.api.core_system_agents import router as core_system_agents_router, prompt_router
    app.include_router(core_system_agents_router)
    from gui.api.model_sockets import router as model_sockets_router
    app.include_router(model_sockets_router)
    from gui.api.agent_history import router as agent_history_router
    app.include_router(agent_history_router)
    from gui.api.docs_maintenance import router as docs_maintenance_router
    app.include_router(docs_maintenance_router)
    app.include_router(prompt_router)
    from gui.api.task_assignment import router as task_assignment_router
    app.include_router(task_assignment_router)
    from gui.api.governance_registry import router as governance_registry_router
    app.include_router(governance_registry_router)
    from gui.api.catalog_projection import router as catalog_projection_router
    app.include_router(catalog_projection_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("System-Agenten-API konnte nicht geladen werden: %s", e)




# ═══════════════════════════════════════════════════════════════

# API ROUTES - STATUS

# ═══════════════════════════════════════════════════════════════



@app.get("/api/gui/backend-origin")
async def get_gui_backend_origin():
    """Non-secret declaration plus live read-only probe of this API's BACH DB."""
    from gui.backend_origin import observe_backend_origin
    from gui.api import unified_api

    return observe_backend_origin(BACH_DB, unified_api.BACH_DB)


@app.get("/device-fetch.js", include_in_schema=False)
async def get_device_fetch_script():
    """Serve the shared kit's fixed public auth bootstrap without a path parameter."""
    script = ASTRO_DIST_DIR / "device-fetch.js"
    if not script.is_file() or script.is_symlink():
        raise HTTPException(404, "GUI-Geräteanmeldungsskript nicht installiert")
    return FileResponse(script, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/gui/brand")
async def get_gui_brand():
    """Return validated non-secret branding for this GUI consumer."""
    from gui.branding import read_gui_brand

    return read_gui_brand()


@app.get("/api/gui/capabilities")
async def get_gui_capabilities():
    """Describe registered GUI adapters without inventing runtime availability."""
    from datetime import datetime, timezone
    from gui.branding import read_gui_brand
    from hub._services.gui_contract_service import get_pinned_kit_manifest, verify_installed_dist

    observed = datetime.now(timezone.utc).isoformat()
    registered_paths = {getattr(route, "path", None) for route in app.routes}
    endpoints = {
        "ellmos-system-gui": "/",
        "tasks": "/api/tasks",
        "agent-studio": "/api/agent-studio/blueprints",
        "memory": "/api/memory/search",
        "domains": "/api/domains/installed",
        "core-system-agents": "/api/system/core-agents",
        "core-prompts": "/api/system/core-prompts",
        "hardware-cockpit": "/api/system/cluster-cockpit",
    }
    modules = {}
    for module_id, endpoint in endpoints.items():
        present = endpoint in registered_paths
        modules[module_id] = {
            "adapter_registered": present,
            "runtime_verified": None,
            "available": None if present else False,
            "reason_code": "route_registered_runtime_not_probed" if present else "adapter_not_registered",
            "observed_at": observed if present else None,
        }

    kit_manifest = get_pinned_kit_manifest()
    dist_info = verify_installed_dist(ASTRO_DIST_DIR, expected_commit=kit_manifest.get("pinned_source_commit"))
    expected_pages = kit_manifest.get("expected_page_count")
    is_kit_verified = bool(
        kit_manifest.get("verified")
        and dist_info.get("verified")
        and type(expected_pages) is int
        and dist_info.get("page_count") == expected_pages
    )

    kit_status = {
        "revision": kit_manifest.get("pinned_source_commit"),
        "version": kit_manifest.get("version"),
        "archive_sha256": kit_manifest.get("release_archive_sha256"),
        "verified": is_kit_verified,
        "installed": dist_info.get("installed", False),
        "installed_files_verified": dist_info.get("verified", False),
        "served": dist_info.get("installed", False),
        "reason_code": "verified_pinned_release" if is_kit_verified else dist_info.get("reason_code", "release_identity_not_probed"),
        "dist_page_count": dist_info.get("page_count", 0),
    }

    from gui.api.gui_capabilities import declaration
    from hub._services.policy_registry_adapter import provider_status
    policy = provider_status()
    modules["policy-registry"] = {"adapter_registered": "/api/governance/policy-registry" in registered_paths,
        "runtime_verified": False, "available": None if policy["verified"] else False,
        "reason_code": policy["reason"], "observed_at": observed}
    return declaration(app.routes, kit_status, read_gui_brand(), modules,
                       public_paths=DeviceAuthMiddleware.EXEMPT_API_PATHS, module_sources=[policy])


@app.get("/api/gui/kit-manifest")
async def get_gui_kit_manifest():
    """Return pinned kit manifest and verification status for ellmos-system-gui (GUX-001)."""
    from hub._services.gui_contract_service import get_pinned_kit_manifest, verify_installed_dist

    manifest = get_pinned_kit_manifest()
    dist_info = verify_installed_dist(ASTRO_DIST_DIR, expected_commit=manifest.get("pinned_source_commit"))
    return {
        **manifest,
        "installed_dist": dist_info,
    }


@app.get("/api/gui/architecture/concepts")
async def get_gui_architecture_concepts():
    """Return canonical definitions for SALT, Trithon, and Muschelgrund (GUX-004)."""
    from hub._services.gui_contract_service import get_architectural_concepts

    return get_architectural_concepts()


@app.get("/api/status")

async def get_status():

    """Liefert System-Status."""

    conn_user = get_user_db()

    conn_bach = get_bach_db()



    # Tasks aus bach.db (mit Fallback)

    try:

        tasks_open = conn_bach.execute(

            "SELECT COUNT(*) FROM tasks WHERE status IN ('pending', 'open', 'in_progress')"

        ).fetchone()[0]

    except (sqlite3.OperationalError, sqlite3.DatabaseError):

        tasks_open = 0



    # Scanned tasks aus bach.db (mit Fallback)
    try:
        scanned_tasks = conn_bach.execute(
            "SELECT COUNT(*) FROM ati_tasks WHERE status = 'offen'"
        ).fetchone()[0]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        scanned_tasks = 0



    # Messages (mit Fallback)
    try:
        messages_unread = _messages().unread_count()
    except (sqlite3.OperationalError, sqlite3.DatabaseError, FileNotFoundError, ImportError):
        messages_unread = 0



    # Daemon Jobs (mit Fallback)

    try:

        daemon_active = conn_user.execute(

            "SELECT COUNT(*) FROM scheduler_jobs WHERE is_active = 1"

        ).fetchone()[0]

    except (sqlite3.OperationalError, sqlite3.DatabaseError):

        daemon_active = 0



    # Last Scan (mit Fallback)

    try:

        last_scan = conn_user.execute(

            "SELECT started_at FROM scan_runs ORDER BY id DESC LIMIT 1"

        ).fetchone()

    except (sqlite3.OperationalError, sqlite3.DatabaseError):

        last_scan = None



    conn_user.close()

    conn_bach.close()

    # System-Ressourcen (NEU v1.1.85)
    system_info = {}
    try:
        import psutil
        mem = psutil.virtual_memory()
        system_info = {
            "ram_used_gb": round(mem.used / (1024**3), 1),
            "ram_total_gb": round(mem.total / (1024**3), 1),
            "ram_percent": mem.percent,
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "disk_percent": psutil.disk_usage(os.path.abspath(os.sep)).percent if hasattr(psutil, 'disk_usage') else None
        }
    except ImportError:
        system_info = {"error": "psutil not installed"}
    except Exception as e:
        system_info = {"error": public_error_message()}

    db_connected = None
    try:
        from contextlib import closing
        with closing(sqlite3.connect(BACH_DB.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=2)) as probe:
            probe.execute("PRAGMA query_only = ON")
            if probe.execute("SELECT 1").fetchone() == (1,):
                db_connected = True
    except (OSError, sqlite3.Error):
        pass

    return {

        "status": "online",

        "version": "1.1.85",

        "timestamp": datetime.now().isoformat(),
        "db_connected": db_connected,

        "stats": {

            "tasks_open": tasks_open,

            "scanned_tasks": scanned_tasks,

            "messages_unread": messages_unread,

            "scheduler_jobs_active": daemon_active,

            "last_scan": last_scan[0] if last_scan else None

        },
        "system": system_info

    }



# ═══════════════════════════════════════════════════════════════

# API ROUTES - TASKS (aus bach.db)

# ═══════════════════════════════════════════════════════════════




# --- Old duplicate GET/POST/PUT /api/tasks entfernt (Bug #902) ---
# Korrekte Versionen siehe weiter unten (ab Zeile ~1164)



@app.delete("/api/tasks/{task_id}")

async def api_del_task(task_id: int):

    """Löscht einen Task in bach.db."""

    try:

        conn = get_bach_db()

        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

        conn.commit()

        conn.close()

        return {"success": True}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/tasks/export")

async def api_tasks_export():

    """Exportiert offene Tasks in eine JSON-Datei."""

    try:

        conn = get_bach_db()

        rows = conn.execute("SELECT * FROM tasks WHERE status = 'pending'").fetchall()

        tasks = [_public_task_snapshot(row_to_dict(row)) for row in rows]

        conn.close()

        

        export_dir = BACH_DIR / "user" / "exports"

        export_dir.mkdir(parents=True, exist_ok=True)

        

        filename = f"tasks_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        export_path = export_dir / filename

        

        with open(export_path, "w", encoding="utf-8") as f:

            json.dump(tasks, f, indent=2, ensure_ascii=False)

            

        return {"success": True, "path": str(export_path), "count": len(tasks)}

    except Exception as e:

        return {"success": False, "error": public_error_message()}




# --- Old duplicate GET single + PUT mit TaskUpdate entfernt (Bug #902) ---

@app.get("/api/tasks/meta")
async def api_tasks_meta():
    """Liefert Metadaten für Task-Filter (Kategorien, Prioritäten, Zuweisungen)."""
    try:
        conn = get_bach_db()
        cat_rows = conn.execute("SELECT DISTINCT category FROM tasks WHERE category IS NOT NULL AND TRIM(category) != '' ORDER BY category ASC").fetchall()
        prio_rows = conn.execute("SELECT DISTINCT priority FROM tasks WHERE priority IS NOT NULL AND TRIM(priority) != '' ORDER BY priority ASC").fetchall()
        assignee_rows = conn.execute("SELECT DISTINCT assigned_to FROM tasks WHERE assigned_to IS NOT NULL AND TRIM(assigned_to) != '' ORDER BY assigned_to ASC").fetchall()
        conn.close()
        categories = sorted(list(set(r[0].strip() for r in cat_rows if r[0] and r[0].strip())))
        priorities = sorted(list(set(r[0].strip() for r in prio_rows if r[0] and r[0].strip())))
        assignees = sorted(list(set(r[0].strip() for r in assignee_rows if r[0] and r[0].strip())))
        return {
            "success": True,
            "categories": categories,
            "priorities": priorities,
            "assignees": assignees,
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}

@app.get("/api/tasks")
async def api_get_tasks(
    status: str = "all",
    project: str = None,
    category: str = None,
    assigned_to: str = None,
    assignment_group: str = "all",
    priority: str = None,
    limit: int = 100,
    offset: int = 0
):
    """Liefert Tasks mit kombiniertem Filter vor Zählung und Pagination."""
    if assignment_group not in {"all", "user", "auto", "unassigned"}:
        raise HTTPException(400, "Ungültige Task-Zuordnung")
    try:
        conn = get_bach_db()

        # Status-Filter: unterstützt kommaseparierte Werte und Aliase
        # (z.B. "in_progress,progress" oder "done,completed,closed")
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        if status and status.lower() == "nonterminal":
            query += " AND LOWER(TRIM(COALESCE(status, ''))) NOT IN ('done', 'completed', 'closed', 'cancelled', 'canceled', 'duplicate')"
        elif status and status.lower() != "all":
            requested = [s.strip().lower() for s in status.split(",") if s.strip()]
            normalized = set()
            if requested == ["open"]:
                normalized.update(["open", "pending", "todo", "in_progress", "progress"])
            else:
                STATUS_ALIASES = {
                    "in_progress": ["in_progress", "progress"],
                    "pending": ["pending", "open", "todo"],
                    "done": ["done", "completed", "closed"],
                    "blocked": ["blocked"],
                    "cancelled": ["cancelled", "canceled"],
                    "duplicate": ["duplicate"],
                }
                for s in requested:
                    if s in STATUS_ALIASES:
                        normalized.update(STATUS_ALIASES[s])
                    else:
                        matched = False
                        for canonical, aliases in STATUS_ALIASES.items():
                            if s in aliases:
                                normalized.update(aliases)
                                matched = True
                                break
                        if not matched:
                            normalized.add(s)
            if normalized:
                placeholders = ",".join(["?"] * len(normalized))
                query += f" AND (LOWER(status) IN ({placeholders}))"
                params.extend(sorted(normalized))

        target_cat = category or project
        if target_cat:
            query += " AND UPPER(category) = UPPER(?)"
            params.append(target_cat)
        if assignment_group == "user":
            query += " AND LOWER(TRIM(COALESCE(assigned_to, ''))) = 'user'"
        elif assignment_group == "auto":
            query += " AND TRIM(COALESCE(assigned_to, '')) <> '' AND LOWER(TRIM(assigned_to)) <> 'user'"
        elif assignment_group == "unassigned":
            query += " AND TRIM(COALESCE(assigned_to, '')) = ''"
        if assigned_to:
            query += " AND UPPER(assigned_to) = UPPER(?)"
            params.append(assigned_to)
        if priority:
            prio_clean = priority.strip().upper()
            if prio_clean in ("P1", "1", "HIGH", "HOCH", "KRITISCH"):
                query += " AND (UPPER(priority) IN ('P1', '1', 'HIGH', 'HOCH', 'KRITISCH') OR priority IS NULL)"
            elif prio_clean in ("P2", "2", "MEDIUM", "MITTEL", "WICHTIG"):
                query += " AND (UPPER(priority) IN ('P2', '2', 'MEDIUM', 'MITTEL', 'WICHTIG'))"
            elif prio_clean in ("P3", "3", "LOW", "NIEDRIG", "NORMAL"):
                query += " AND (UPPER(priority) IN ('P3', '3', 'LOW', 'NIEDRIG', 'NORMAL'))"
            elif prio_clean in ("P4", "4", "MINIMAL"):
                query += " AND (UPPER(priority) IN ('P4', '4', 'MINIMAL'))"
            else:
                query += " AND UPPER(priority) = UPPER(?)"
                params.append(priority)

        # Keep count as the returned page size; total describes the same filters
        # before pagination (the dashboard only requests five recent tasks).
        total = conn.execute(
            query.replace("SELECT *", "SELECT COUNT(*)", 1), params
        ).fetchone()[0]
        query += """ ORDER BY CASE
            WHEN UPPER(TRIM(priority)) IN ('P1','1','HIGH','HOCH','KRITISCH') THEN 1
            WHEN UPPER(TRIM(priority)) IN ('P2','2','MEDIUM','MITTEL','WICHTIG') THEN 2
            WHEN UPPER(TRIM(priority)) IN ('P3','3','LOW','NIEDRIG','NORMAL') THEN 3
            WHEN UPPER(TRIM(priority)) IN ('P4','4','MINIMAL') THEN 4
            ELSE 5 END ASC, created_at DESC, id DESC LIMIT ? OFFSET ?"""
        params.extend((limit + 1 if limit > 0 else limit, max(0, offset)))
        
        rows = conn.execute(query, params).fetchall()
        has_more = limit > 0 and len(rows) > limit
        if has_more:
            rows = rows[:limit]
        tasks = [_public_task_snapshot(row_to_dict(row)) for row in rows]

        # image_data nicht in Liste senden (Performance), nur Flag
        for task in tasks:
            if task.get("image_data"):
                task["has_image"] = True
            task.pop("image_data", None)

        # Abhaengigkeitsstatus fail-closed fuer jeden Task setzen: ungueltige,
        # fehlende oder unerledigte Vorgaenger blockieren (der Idle-Worker im
        # Tray verlaesst sich auf das Feld).
        for task in tasks:
            task["is_blocked_by_dep"] = _task_blocked_by_dependency(conn, task)

        conn.close()
        return {"success": True, "tasks": tasks, "count": len(tasks), "total": total, "has_more": has_more,
                "offset": max(0, offset),
                "applied_filters": {"assignment_group": assignment_group, "status": status}}
    except Exception as e:
        return {"success": False, "error": public_error_message()}

@app.post("/api/tasks")
async def api_post_task(payload: dict = Body(...)):
    """Erstellt neuen Task in bach.db via JSON Payload (idempotent via source/draft_hash)."""
    try:
        from gui.api.task_assignment import assignment_write_guard
        with assignment_write_guard(payload):
            conn = get_bach_db()
            from hub._services.task_schema import (
                ensure_task_creation_origin,
                ensure_task_slot_columns,
            )
            ensure_task_slot_columns(conn)
            ensure_task_creation_origin(conn)
            draft_source = payload.get("source") or payload.get("draft_hash")
            if draft_source:
                existing = conn.execute("SELECT id FROM tasks WHERE source = ?", (draft_source,)).fetchone()
                if existing:
                    conn.close()
                    return {"success": True, "id": existing[0], "status": "already_present"}

            due_date = payload.get("due_date")
            if due_date is not None:
                if isinstance(due_date, str) and not due_date.strip():
                    due_date = None
                else:
                    clean_due = str(due_date).strip()
                    try:
                        from datetime import datetime as _dt
                        if "T" in clean_due or " " in clean_due:
                            _dt.fromisoformat(clean_due.replace(" ", "T"))
                        else:
                            _dt.strptime(clean_due, "%Y-%m-%d")
                        due_date = clean_due
                    except ValueError:
                        conn.close()
                        raise HTTPException(status_code=400, detail="Ungültiges Fälligkeitsdatum. Erwartet: YYYY-MM-DD")

            now = datetime.now().isoformat()
            cursor = conn.execute("""
                INSERT INTO tasks (title, description, priority, category, status, created_at, created_by, assigned_to, depends_on, image_data, due_date, source, required_model, assigned_slot, creation_origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payload.get("title"),
                payload.get("description", ""),
                payload.get("priority", "P3"),
                payload.get("category") or payload.get("project") or "general",
                payload.get("status", "pending"),
                now,
                payload.get("created_by", "user"),
                payload.get("assigned_to") or payload.get("assignee") or DEFAULT_TASK_ASSIGNEE,
                payload.get("depends_on"),
                payload.get("image"),
                due_date,
                draft_source,
                payload.get("required_model") or None,
                payload.get("assigned_slot") or None,
                payload.get("creation_origin") or None,
            ))

            task_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return {"success": True, "id": task_id, "status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": public_error_message()}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: int):
    """Holt einzelnen Task aus bach.db."""
    conn = get_bach_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        task = _public_task_snapshot(row_to_dict(row))
        task["is_blocked_by_dep"] = _task_blocked_by_dependency(conn, task)
        return task
    finally:
        conn.close()


def _task_blocked_by_dependency(conn, task: dict) -> bool:
    """Fail-closed: ungueltige, fehlende oder unerledigte Vorgaenger blockieren."""
    if not str(task.get("depends_on") or "").strip():
        return False
    from hub._services.task_schema import inspect_task_dependencies
    try:
        return bool(inspect_task_dependencies(conn, task.get("depends_on"))["blocked"])
    except sqlite3.Error:
        return True


# --- BACH #1721: Lead-seitiger Task-Lease-Dienst (TASKDB-SALT-LEASE-VERTRAG-v1 §5) ---
# Auth: /api/ liegt hinter DeviceAuthMiddleware (fail-closed, Device-Token).

def _public_task_snapshot(row):
    from hub._services.task_lease import task_content_version
    result = dict(row)
    version = task_content_version(result)
    for secret in ("claim_id", "claim_request_id", "claim_task_version"):
        result.pop(secret, None)
    result["task_version"] = version
    return result


class LeaseAcquireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str
    host: str
    request_id: str
    ttl_profile: Optional[str] = None
    intent: Optional[str] = None
    task_version: Optional[StrictStr] = None
    result_generation: Optional[StrictStr] = None


class LeaseRefRequest(BaseModel):
    lease_id: str
    fence: StrictInt
    task_version: Optional[StrictStr] = None


class LeaseReleaseRequest(LeaseRefRequest):
    model_config = ConfigDict(extra="forbid")
    outcome: str
    result_ref: Optional[str] = None
    note: Optional[str] = None
    worker_result: Optional[dict] = None


class LeaseUpdateRequest(LeaseRefRequest):
    model_config = ConfigDict(extra="forbid")
    task_version: StrictStr
    changes: dict[StrictStr, StrictStr]


class LeaseDecomposeRequest(LeaseRefRequest):
    model_config = ConfigDict(extra="forbid")
    task_version: StrictStr
    subtasks: list[dict]
    close_parent: StrictBool = True
    sequential: StrictBool = False


def _lease_device_label(request: Request) -> Optional[str]:
    device = getattr(request.state, "device", None)
    if isinstance(device, dict):
        label = device.get("name") or device.get("device_name") or device.get("id")
        return str(label) if label is not None else None
    return str(device) if device else None


class TaskResultAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: StrictInt
    result_sha256: StrictStr
    task_version: StrictStr
    status_revision: StrictInt


@app.get("/api/tasks/{task_id}/result")
async def read_task_result(task_id: int):
    """Ergebnis und heutige Abnahme aus einem kanonischen Lesesnapshot."""
    from hub._services.task_result_service import read_result
    conn = get_bach_db()
    try:
        if not conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        return read_result(conn, task_id)
    finally:
        conn.close()


@app.post("/api/tasks/{task_id}/result/accept")
async def accept_task_result(task_id: int, body: TaskResultAcceptanceRequest, request: Request):
    """Getrennte Operator-Abnahme; Geräteidentität kommt ausschließlich aus Auth."""
    from hub._services.task_result_service import accept_result, ResultConflict, ResultPermissionDenied
    operator_token = request.headers.get("X-BACH-Result-Operator", "")
    conn = get_bach_db()
    try:
        if not conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        return accept_result(conn, task_id, body.result_id, digest=body.result_sha256,
                             task_version=body.task_version, status_revision=body.status_revision,
                             operator_token=operator_token)
    except ResultPermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ResultConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        conn.close()


def _run_lease_op(op, *args, **kwargs):
    from hub._services.task_lease import LeaseValidationError, TaskNotFound
    conn = get_bach_db()
    try:
        result = op(conn, *args, **kwargs)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    except LeaseValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(status_code=result.http_status, content=result.payload)


@app.post("/api/tasks/{task_id}/lease")
async def acquire_task_lease(task_id: int, body: LeaseAcquireRequest, request: Request):
    """Lease anfordern (Vertrag §5.1). 200 = ACK mit lease_id/fence, 409 = Ablehnung mit reason."""
    from hub._services.task_lease import acquire_lease
    return _run_lease_op(acquire_lease, task_id, worker_id=body.worker_id, host=body.host,
                         request_id=body.request_id, ttl_profile=body.ttl_profile,
                         task_version=body.task_version,
                         result_generation=body.result_generation,
                         intent=body.intent or "", device=_lease_device_label(request))


@app.get("/api/tasks/{task_id}/lease")
async def read_task_lease(task_id: int, request: Request):
    """Wer hält die Task? (Vertrag §5.2). Ohne lease_id; ``own`` nur mit passendem X-Lease-Id."""
    from hub._services.task_lease import read_lease
    return _run_lease_op(read_lease, task_id, lease_id=request.headers.get("X-Lease-Id") or None)


@app.post("/api/tasks/{task_id}/lease/renew")
async def renew_task_lease(task_id: int, body: LeaseRefRequest):
    """Heartbeat/Verlängerung (Vertrag §5.3)."""
    from hub._services.task_lease import renew_lease
    return _run_lease_op(renew_lease, task_id, lease_id=body.lease_id, fence=body.fence,
                         task_version=body.task_version)


@app.post("/api/tasks/{task_id}/lease/release")
async def release_task_lease(task_id: int, body: LeaseReleaseRequest):
    """Rückgabe/Abschluss (Vertrag §5.4): outcome return|done|blocked|review."""
    from hub._services.task_lease import release_lease
    return _run_lease_op(release_lease, task_id, lease_id=body.lease_id, fence=body.fence,
                         task_version=body.task_version,
                         outcome=body.outcome, result_ref=body.result_ref or "",
                         note=body.note or "", worker_result=body.worker_result)


@app.post("/api/tasks/{task_id}/lease/update")
async def update_task_lease(task_id: int, body: LeaseUpdateRequest):
    """Atomare Inhaltsänderung samt neuer Lease-Bindung."""
    from hub._services.task_lease import update_lease
    return _run_lease_op(update_lease, task_id, lease_id=body.lease_id, fence=body.fence,
                         task_version=body.task_version, changes=body.changes)


@app.post("/api/tasks/{task_id}/lease/decompose")
async def decompose_task_lease(task_id: int, body: LeaseDecomposeRequest):
    """Atomare Zerlegung mit Geräteauth, Lease, Fence und Taskversion."""
    from hub._services.task_lease import decompose_lease
    return _run_lease_op(decompose_lease, task_id, lease_id=body.lease_id, fence=body.fence,
                         task_version=body.task_version, subtasks=body.subtasks,
                         close_parent=body.close_parent, sequential=body.sequential)


@app.put("/api/tasks/{task_id}")
async def update_task(task_id: int, update: TaskUpdate):
    """Aktualisiert Task in bach.db und protokolliert jede Feldaenderung in task_history.

    T-20260906-985973908: Vorher wurde `task_history` nie beschrieben (0 Zeilen system-
    weit) und `started_at` beim Wechsel auf 'in_progress' nie gesetzt -- die Queue hatte
    keinen Audit-Trail. Beide Luecken werden hier im selben Handler geschlossen, weil GUI
    und Tray-Idle-Worker gleichermassen ueber PUT /api/tasks/{id} gehen.

    T-20260906-240256515: Die eigentliche Schreiblogik (UPDATE + task_history) liegt seit
    diesem Ticket zentral in hub.task_audit.apply_task_field_changes, weil die separate
    Headless-API (system/gui/api/headless.py, Port 8001) dieselbe Luecke hatte -- hier nur
    noch die GUI-eigene Feldabbildung (`project` -> Spalte `category`).
    """
    conn = get_bach_db()
    try:
        from hub._services.task_schema import ensure_task_slot_columns
        existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        existing_row = row_to_dict(existing)
        from gui.api.task_assignment import assignment_write_guard
        with assignment_write_guard(update.model_dump(exclude_unset=True), existing_row):
            if "required_model" in update.model_fields_set or "assigned_slot" in update.model_fields_set:
                ensure_task_slot_columns(conn)

            # changed_by: vom Aufrufer mitgegeben (z.B. Idle-Worker meldet sich als
            # "idle-worker"), sonst generischer API-Default -- Schema-Default waere 'user',
            # das waere hier irrefuehrend, da die meisten PUTs programmatisch erfolgen.
            changed_by = update.changed_by or "api"

            # T-20260913-709822598: Atomarer Claim bei Neu-Uebergang auf 'in_progress'
            # bzw. Claim-Versuch gegen fremd beanspruchten Task
            is_new_claim = (
                update.status == "in_progress"
                and not (
                    existing_row.get("status") == "in_progress"
                    and existing_row.get("claimed_by") == changed_by
                )
            )

            did_update = False
            if is_new_claim:
                if not claim_task_atomic(conn, task_id, changed_by):
                    return {"status": "claim_failed", "success": False}
                did_update = True

            # field_values: {DB-Spalte: neuer_wert} -- `project` ist ein GUI-Alias fuer
            # die tatsaechliche Spalte `category`, muss also VOR dem Aufruf aufgeloest werden.
            field_values = {}
            if update.title is not None:
                field_values["title"] = update.title
            if update.description is not None:
                field_values["description"] = update.description
            if update.priority is not None:
                field_values["priority"] = update.priority
            if update.status is not None and not is_new_claim:
                field_values["status"] = update.status
            if update.project is not None:
                field_values["category"] = update.project
            if update.category is not None:
                field_values["category"] = update.category
            if update.assigned_to is not None:
                field_values["assigned_to"] = update.assigned_to
            if update.created_by is not None:
                field_values["created_by"] = update.created_by
            if update.depends_on is not None:
                field_values["depends_on"] = update.depends_on
            if "due_date" in update.model_fields_set:
                raw_due = update.due_date
                if raw_due is None or (isinstance(raw_due, str) and not raw_due.strip()):
                    field_values["due_date"] = None
                else:
                    clean_due = str(raw_due).strip()
                    try:
                        from datetime import datetime as _dt
                        if "T" in clean_due or " " in clean_due:
                            _dt.fromisoformat(clean_due.replace(" ", "T"))
                        else:
                            _dt.strptime(clean_due, "%Y-%m-%d")
                        field_values["due_date"] = clean_due
                    except ValueError:
                        raise HTTPException(status_code=400, detail="Ungültiges Fälligkeitsdatum. Erwartet: YYYY-MM-DD")
            if "required_model" in update.model_fields_set:
                field_values["required_model"] = update.required_model or None
            if "assigned_slot" in update.model_fields_set:
                field_values["assigned_slot"] = update.assigned_slot or None

            try:
                # T-20260916-1330: Fail-Closed-Guard gegen Resurrektion von
                # gate-geparkten Tasks -- Reopen ohne allow_reopen wird blockiert.
                if apply_task_field_changes(conn, task_id, existing_row, field_values,
                                            changed_by=changed_by,
                                            allow_reopen=bool(update.allow_reopen)):
                    did_update = True
            except LeaseRequired as exc:
                # BACH #1721: lebender Lease -> nur /lease/release darf den Status aendern.
                raise HTTPException(status_code=409, detail={"reason": exc.reason, "message": str(exc)})
            except (GateReopenBlocked, ValueError) as exc:
                # Business-rule conflicts (for example the missing-PR completion guard)
                # are client-resolvable conflicts, not internal server errors.
                raise HTTPException(status_code=409, detail=str(exc))

            if did_update:
                conn.commit()
    finally:
        conn.close()

    return {"status": "updated"}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    """Löscht einen Task aus bach.db."""
    conn = get_bach_db()
    try:
        existing = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "deleted", "id": task_id}

# ═══════════════════════════════════════════════════════════════
# API ROUTES - ASSIGNEES (Agenten, Experten, Partner)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/assignees")
async def list_assignees():
    """Listet alle moeglichen Zuweisungsempfaenger: user, agents, experts, connections."""
    conn = get_bach_db()
    assignees = []

    # Presence Map laden
    presence_map = {}
    try:
        # Get latest status for each partner (assuming id increases with time)
        rows = conn.execute("""
            SELECT partner_name, status 
            FROM partner_presence 
            WHERE id IN (SELECT MAX(id) FROM partner_presence GROUP BY partner_name)
        """).fetchall()
        for r in rows:
            presence_map[r[0]] = r[1]
    except Exception as e:
        print(f"Presence check failed: {e}")

    # BACH System als Default (zuerst in der Liste)
    assignees.append({
        "id": "bach",
        "name": "bach",
        "display_name": "BACH System",
        "type": "system",
        "category": None,
        "status": "online"
    })

    # User (manuell)
    assignees.append({
        "id": "user",
        "name": "user",
        "display_name": "Benutzer (manuell)",
        "type": "user",
        "category": None,
        "status": "online"
    })

    # Idle Worker Assignees (automatische Ausfuehrung im Leerlauf)
    assignees.append({
        "id": "OLLAMA",
        "name": "OLLAMA",
        "display_name": "Ollama (Idle Worker)",
        "type": "idle-worker",
        "category": None,
        "status": "online"
    })
    assignees.append({
        "id": "BUDDHA",
        "name": "BUDDHA",
        "display_name": "Buddha (Idle Worker)",
        "type": "idle-worker",
        "category": None,
        "status": "online"
    })

    # Agenten aus bach_agents
    try:
        agents = conn.execute(
            "SELECT id, name, display_name, type FROM bach_agents WHERE is_active = 1"
        ).fetchall()
        for a in agents:
            status = presence_map.get(a[1], "offline")
            if status == "crashed": status = "offline"
            assignees.append({
                "id": f"agent:{a[1]}",
                "name": a[1],
                "display_name": a[2],
                "type": "agent",
                "category": a[3],
                "status": status
            })
    except Exception:
        pass

    # Experten aus bach_experts
    try:
        experts = conn.execute(
            "SELECT id, name, display_name, domain FROM bach_experts WHERE is_active = 1"
        ).fetchall()
        for e in experts:
            assignees.append({
                "id": f"expert:{e[1]}",
                "name": e[1],
                "display_name": e[2],
                "type": "expert",
                "category": e[3],
                "status": "offline"
            })
    except Exception:
        pass

    # Externe Connections (AI, MCP)
    try:
        conns = conn.execute(
            "SELECT id, name, type, category FROM connections WHERE is_active = 1"
        ).fetchall()
        for c in conns:
            assignees.append({
                "id": f"connection:{c[1]}",
                "name": c[1],
                "display_name": c[1].replace('_', ' ').title(),
                "type": "connection",
                "status": "available"
            })
    except Exception:
        pass

    # Avatar-Agenten (Subscription / CLI Dummies & Proxies)
    avatar_defs = [
        {"name": "claude", "display_name": "Claude Code (Subscription / CLI)", "animus": "subscription"},
        {"name": "gemini", "display_name": "Gemini Antigravity (Subscription / CLI)", "animus": "subscription"},
        {"name": "codex", "display_name": "Codex / GPT (Subscription / CLI)", "animus": "subscription"},
        {"name": "kimi", "display_name": "Kimi Code (CLI)", "animus": "cli"},
    ]
    for av in avatar_defs:
        status = presence_map.get(av["name"], "offline")
        if status == "crashed":
            status = "offline"
        assignees.append({
            "id": f"avatar:{av['name']}",
            "name": av["name"],
            "display_name": av["display_name"],
            "type": "avatar",
            "category": "cli",
            "animus": av["animus"],
            "status": status
        })

    conn.close()
    return {"assignees": assignees, "count": len(assignees)}


@app.post("/api/presence")
async def update_presence(payload: dict = Body(...)):
    """Aktualisiert die Praesenz eines Partners / Avatar-Agenten (z.B. via Hook bei SessionStart/SessionEnd)."""
    name = (payload.get("partner_name") or payload.get("name") or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Name fehlt")
    status = payload.get("status", "online")
    session_id = payload.get("session_id")
    task_id = payload.get("current_task")
    now = datetime.now().isoformat()
    conn = get_bach_db()
    try:
        conn.execute("""
            INSERT INTO partner_presence (partner_name, status, clocked_in, last_heartbeat, current_task, session_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, status, now if status == "online" else None, now, task_id, session_id, now, now))
        conn.commit()
        return {"success": True, "partner": name, "status": status}
    finally:
        conn.close()



@app.get("/api/agents")

async def api_list_agents():

    """Detaillierte Liste aller Agenten inkl. Experten."""

    try:

        conn = get_bach_db()

        

        # Agenten laden

        agents_rows = conn.execute("SELECT * FROM bach_agents ORDER BY priority DESC, display_name ASC").fetchall()

        agents = rows_to_list(agents_rows)

        

        # Experten laden

        experts_rows = conn.execute("SELECT * FROM bach_experts WHERE is_active = 1").fetchall()

        experts = rows_to_list(experts_rows)

        # Dashboard-Links fuer Experten ergaenzen
        expert_dashboards = {
            "foerderplaner": "/agents/foerderplaner",
            "steuer-agent": "/steuer",
            "report_generator": "/agents/foerderplaner",
        }
        for expert in experts:
            if expert["name"] in expert_dashboards:
                expert["dashboard"] = expert_dashboards[expert["name"]]

        # Experten den Agenten zuordnen

        for agent in agents:

            agent["experts"] = [e for e in experts if e["agent_id"] == agent["id"]]
            agent["profile_chat_ready"] = False
            try:
                from hub._services.chat.agent_profile_context import resolve_profile
                binding, _profile_text = resolve_profile(int(agent["id"]))
                agent["profile_chat_ready"] = binding["agent_id"] == int(agent["id"])
            except (ValueError, TypeError, OSError):
                pass

            # Dashboard URL Fallback/Konstruktion

            if not agent.get("dashboard"):

                # Pruefen ob ein Standard-Asset existiert

                if (TEMPLATES_DIR / f"{agent['name']}.html").exists():

                    agent["dashboard"] = f"/{agent['name']}"

                elif agent['name'] in ['ati', 'developer-assistent']:
                    agent["dashboard"] = "/agents/ati"

        

        conn.close()

        return {"success": True, "agents": agents, "count": len(agents)}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.get("/api/agents/runtime")
async def api_agent_runtime(request: Request):
    """Read only: report launcher-owned processes for verified local profiles."""
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not token or not validate_token(token):
        raise HTTPException(status_code=401, detail="Geräteanmeldung erforderlich")

    from hub.agent_launcher import AgentLauncherHandler
    from hub.agent_process_provider import inspect_process_identity
    from hub._services.chat.agent_profile_context import resolve_profile

    handler = AgentLauncherHandler(BACH_DIR)
    registered = {item["name"] for item in handler._scan_agents()}
    conn = get_bach_db()
    try:
        rows = conn.execute("SELECT id FROM bach_agents").fetchall()
    finally:
        conn.close()

    states = []
    for row in rows:
        agent_id = int(row["id"])
        try:
            binding, _text = resolve_profile(agent_id)
        except (ValueError, TypeError, OSError):
            continue
        slug = binding["exact_slug"]
        if slug not in registered:
            states.append({"agent_id": agent_id, "process_state": "unavailable", "running": False})
            continue
        pid_file = handler.pid_dir / f"{slug}.pid"
        if not pid_file.exists():
            state = "not_started"
            reason = None
        else:
            reason = None
            pid_data = handler._load_pid_data(slug)
            identity, _process = inspect_process_identity(pid_data)
            if identity == "owned":
                # inspect_process_identity verifies PID and birth time. Do not
                # construct the optional external registry on a read-only route.
                external_enabled = os.environ.get("BACH_USE_EXTERNAL_AGENT_REGISTRY", "").strip().lower() in {
                    "1", "true", "yes", "on"
                }
                state = "unavailable" if external_enabled else "running"
                if external_enabled:
                    reason = "external_registry_not_probed"
            elif identity == "gone":
                state = "ended"
            else:
                state = identity
        states.append({"agent_id": agent_id, "process_state": state, "running": state == "running",
                       **({"reason": reason} if reason else {})})
    return {"success": True, "agents": states}


@app.put("/api/agents/{agent_id}/toggle")

async def api_toggle_agent(agent_id: int):

    """Aktiviert/Deaktiviert einen Agenten."""

    try:

        conn = get_bach_db()

        current = conn.execute("SELECT is_active FROM bach_agents WHERE id = ?", (agent_id,)).fetchone()

        if not current:

            conn.close()

            raise HTTPException(status_code=404, detail="Agent nicht gefunden")

        

        new_state = 0 if current["is_active"] else 1

        conn.execute("UPDATE bach_agents SET is_active = ? WHERE id = ?", (new_state, agent_id))

        conn.commit()

        conn.close()

        return {"success": True, "is_active": bool(new_state)}

    except Exception as e:

        return {"success": False, "error": public_error_message()}







# ═══════════════════════════════════════════════════════════════

# API ROUTES - SCANNED TASKS

# ═══════════════════════════════════════════════════════════════



@app.get("/api/scanned-tasks")
@app.get("/api/ati/tasks")
async def list_scanned_tasks(tool: Optional[str] = None, status: Optional[str] = None, limit: int = 50):

    """Listet gescannte Tasks."""

    conn = get_user_db()
    try:
        query = "SELECT * FROM ati_tasks WHERE 1=1"
        params = []

        if tool:
            query += " AND tool_name LIKE ?"
            params.append(f"%{tool}%")

        if status:
            query += " AND status = ?"
            params.append(status)
        else:
            query += " AND status IN ('offen', 'in_arbeit')"

        query += " ORDER BY priority_score DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    return {"tasks": rows_to_list(rows), "count": len(rows)}



# ═══════════════════════════════════════════════════════════════

# API ROUTES - BERICHT (Foerderplanung)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/bericht/status")

async def api_bericht_status():

    """Ruft Status der Bericht-Pipeline ab."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.bericht import BerichtHandler

        handler = BerichtHandler(BACH_DIR)

        success, output = handler._status()

        return {"success": success, "output": output}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.get("/api/bericht/clients")

async def api_bericht_clients():

    """Listet Klienten-Ordner auf."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.bericht import BerichtHandler

        handler = BerichtHandler(BACH_DIR)

        success, output = handler._list([])

        return {"success": success, "output": output}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/bericht/export")

async def api_bericht_export(payload: BerichtExport):

    """Exportiert (de-anonymisiert) einen Bericht."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.bericht import BerichtHandler

        handler = BerichtHandler(BACH_DIR)

        args = [payload.folder, "-p", payload.password]

        success, output = handler._export(args)

        if not success:
            raise HTTPException(status_code=500, detail=public_error_message())
        return {"success": True, "message": "Export abgeschlossen"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/bericht/generate")

async def api_bericht_generate(payload: BerichtGenerate):

    """Generiert einen Bericht."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.bericht import BerichtHandler

        handler = BerichtHandler(BACH_DIR)

        args = [payload.json_path, "-o", payload.output_path]

        if payload.template_path:

            args.extend(["-t", payload.template_path])

        success, output = handler._generate(args)

        if not success:
            raise HTTPException(status_code=500, detail=public_error_message())
        return {"success": True, "message": "Bericht generiert"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



# ═══════════════════════════════════════════════════════════════

# API ROUTES - MOUNTS (SYS_001)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/mounts")

async def api_list_mounts():

    """Listet alle Mounts auf."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.mount import MountHandler

        handler = MountHandler(BACH_DIR)

        success, output = handler._list_mounts()

        

        mounts = []

        if success and "Aktive Mounts:" in output:

            lines = output.split('\n')[2:]

            for line in lines:

                if " -> " in line:

                    # Parse: "[OK] alias -> path [EXISTIERT]"

                    # Vorsicht bei Leerzeichen in Pfaden

                    parts = line.split(' ')

                    status = parts[0]

                    alias = parts[1]

                    # rest is "-> path [EXISTIERT]"

                    rest = line.split(' -> ')[1]

                    path = rest.split(' [')[0]

                    exists = "[EXISTIERT]" in rest

                    active = status == "[OK]"

                    mounts.append({

                        "alias": alias,

                        "path": path,

                        "active": active,

                        "exists": exists

                    })

        if not success:
            raise HTTPException(status_code=500, detail=public_error_message())
        return {"success": True, "mounts": mounts}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/mounts")

async def api_add_mount(payload: MountAdd):

    """Fügt einen neuen Mount hinzu."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.mount import MountHandler

        handler = MountHandler(BACH_DIR)

        success, output = handler._add_mount([payload.path, payload.alias], dry_run=False)

        if not success:
            raise HTTPException(status_code=500, detail=public_error_message())
        return {"success": True, "message": "Mount angelegt"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.delete("/api/mounts/{alias}")

async def api_remove_mount(alias: str):

    """Entfernt einen Mount."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.mount import MountHandler

        handler = MountHandler(BACH_DIR)

        success, output = handler._remove_mount([alias], dry_run=False)

        if not success:
            raise HTTPException(status_code=500, detail=public_error_message())
        return {"success": True, "message": "Mount entfernt"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/mounts/restore")

async def api_restore_mounts():

    """Stellt alle Mounts wieder her."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub.mount import MountHandler

        handler = MountHandler(BACH_DIR)

        success, output = handler._restore_mounts(dry_run=False)

        if not success:
            raise HTTPException(status_code=500, detail=public_error_message())
        return {"success": True, "message": "Mounts wiederhergestellt"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}







# ═══════════════════════════════════════════════════════════════

# API ROUTES - MESSAGES

# ═══════════════════════════════════════════════════════════════



from gui.api.user_inbox import build_router as build_user_inbox_router
app.include_router(build_user_inbox_router(_messages))


@app.get("/api/messages")
async def list_messages(direction: Optional[str] = None, status: Optional[str] = None,
                        partner: Optional[str] = None,
                        include_archived: bool = True, limit: int = 50):
    """Listet Nachrichten.

    Args:
        direction: 'inbox' oder 'outbox'
        status: 'unread', 'read', 'archived'
        include_archived: Auch archivierte anzeigen (default: True)
        limit: Max Anzahl
    """
    rows = _messages().list(direction=direction, status=status, partner=partner,
                            include_archived=include_archived, limit=limit)
    return {"messages": rows, "count": len(rows)}


@app.post("/api/messages")
async def create_message(msg: MessageCreate):
    """Erstellt neue Nachricht."""
    msg_id = _messages().create_order(msg.recipient, msg.body, subject=msg.subject, priority=msg.priority)
    return {"id": msg_id, "status": "created"}


@app.put("/api/messages/{msg_id}/read")
async def mark_message_read(msg_id: int):
    """Markiert Nachricht als gelesen."""
    _messages().mark_read(msg_id)
    return {"status": "read"}


@app.post("/api/messages/mark-all-read")
async def mark_all_messages_read():
    """Markiert alle ungelesenen Nachrichten als gelesen."""
    count = _messages().mark_all_read()
    return {"status": "ok", "marked": count}


@app.put("/api/messages/{msg_id}/archive")
async def archive_message(msg_id: int):
    """Archiviert eine Nachricht."""
    _messages().archive(msg_id)
    return {"status": "archived"}


@app.put("/api/messages/{msg_id}/delete")
async def delete_message(msg_id: int):
    """Markiert Nachricht als geloescht (soft delete)."""
    _messages().delete(msg_id)
    return {"status": "deleted"}


@app.get("/api/partners")
async def get_partners():
    """Partner-Liste aus Agenten und Nachrichtenhistorie."""
    partners = []
    try:
        with get_bach_db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT name FROM bach_agents WHERE is_active = 1 ORDER BY name"
            ).fetchall()
            seen = set()
            for r in rows:
                name = r[0] if isinstance(r, (tuple, list)) else r["name"]
                if name and name not in seen:
                    partners.append({"name": name})
                    seen.add(name)
        for name in _messages().partners():
            if name and name not in seen:
                partners.append({"name": name})
                seen.add(name)
    except Exception:
        pass
    return {"partners": partners}
# ═══════════════════════════════════════════════════════════════

# API ROUTES - DAEMON

# ═══════════════════════════════════════════════════════════════



@app.get("/api/daemon/jobs")

async def list_scheduler_jobs():

    """Listet alle Daemon-Jobs."""

    conn = get_user_db()

    try:

        rows = conn.execute("SELECT * FROM scheduler_jobs ORDER BY name").fetchall()

    finally:

        conn.close()

    return {"jobs": rows_to_list(rows), "count": len(rows)}



@app.post("/api/daemon/jobs")

async def create_daemon_job(job: DaemonJobCreate):

    """Erstellt neuen Daemon-Job."""

    conn = get_user_db()

    try:

        cursor = conn.execute("""

            INSERT INTO scheduler_jobs (name, description, job_type, schedule, command, script_path, arguments)

            VALUES (?, ?, ?, ?, ?, ?, ?)

        """, (job.name, job.description, job.job_type, job.schedule, job.command, job.script_path, job.arguments))

        job_id = cursor.lastrowid

        conn.commit()

    finally:

        conn.close()

    return {"id": job_id, "status": "created"}



@app.put("/api/daemon/jobs/{job_id}/toggle")

async def toggle_daemon_job(job_id: int):

    """Aktiviert/Deaktiviert Daemon-Job."""

    conn = get_user_db()

    try:

        current = conn.execute("SELECT is_active FROM scheduler_jobs WHERE id = ?", (job_id,)).fetchone()

        if not current:

            raise HTTPException(status_code=404, detail="Job nicht gefunden")

        new_state = 0 if current[0] else 1

        conn.execute("UPDATE scheduler_jobs SET is_active = ? WHERE id = ?", (new_state, job_id))

        conn.commit()

    finally:

        conn.close()

    return {"is_active": bool(new_state)}



@app.get("/api/daemon/runs")

async def list_scheduler_runs(job_id: Optional[int] = None, limit: int = 20):

    """Listet Daemon-Laeufe."""

    conn = get_user_db()

    try:

        if job_id:

            rows = conn.execute(

                "SELECT * FROM scheduler_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT ?",

                (job_id, limit)

            ).fetchall()

        else:

            rows = conn.execute(

                "SELECT * FROM scheduler_runs ORDER BY started_at DESC LIMIT ?",

                (limit,)

            ).fetchall()

    finally:

        conn.close()

    return {"runs": rows_to_list(rows), "count": len(rows)}





_DAEMON_CONTROL_LOCK = threading.Lock()
_GUI_DAEMON = None
_GUI_DAEMON_STARTING = False


@app.get("/api/daemon/status")

async def get_daemon_status():

    """Liefert aktuellen Daemon-Status mit Job-Statistiken und Runtime-Metriken."""

    from gui.daemon_service import DAEMON_PID_FILE
    from gui.daemon_identity import observe_identity

    identity = observe_identity(DAEMON_PID_FILE, BACH_DIR, local_service=_GUI_DAEMON)
    running = identity["running"]
    pid = identity["pid"]
    started_at = None

    config = {"interval": 15, "max_sessions": 3, "quiet_time": None}
    is_quiet = False
    config_file = BACH_DIR / "data" / "daemon_config.json"
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                config["interval"] = cfg.get("interval_minutes", 15)
                config["max_sessions"] = cfg.get("max_sessions", 3)
                quiet_start = cfg.get("quiet_start")
                quiet_end = cfg.get("quiet_end")
                if quiet_start and quiet_end:
                    config["quiet_time"] = f"{quiet_start}-{quiet_end}"
                    is_quiet = is_quiet_time(quiet_start, quiet_end)
        except Exception:
            pass

    # A configured interval does not prove a session ran or when the loop began.
    runtime_str = None
    sessions_generated = None
    next_session_in = None

    stats = {"total_jobs": None, "active_jobs": None, "runs_today": None, "failed_today": None}
    last_runs = []
    stats_availability = "unavailable"
    try:
        from contextlib import closing
        with closing(sqlite3.connect(BACH_DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            observed = {
                "total_jobs": conn.execute("SELECT COUNT(*) FROM scheduler_jobs").fetchone()[0],
                "active_jobs": conn.execute("SELECT COUNT(*) FROM scheduler_jobs WHERE is_active = 1").fetchone()[0],
                "runs_today": conn.execute(
                    "SELECT COUNT(*) FROM scheduler_runs WHERE date(started_at) = date('now')"
                ).fetchone()[0],
                "failed_today": conn.execute(
                    "SELECT COUNT(*) FROM scheduler_runs WHERE date(started_at) = date('now') AND result = 'failed'"
                ).fetchone()[0],
            }
            observed_runs = conn.execute("""
                SELECT r.id, j.name, r.result, r.started_at, r.duration_seconds
                FROM scheduler_runs r
                JOIN scheduler_jobs j ON r.job_id = j.id
                ORDER BY r.started_at DESC LIMIT 5
            """).fetchall()
            stats, last_runs, stats_availability = observed, observed_runs, "available"
    except (OSError, sqlite3.Error):
        pass

    return {
        "running": running,
        "pid": pid,
        "identity": identity["identity"],
        "identity_reason": identity["reason"],
        "control_available": identity["control_available"],
        "started_at": started_at,
        "config": config,
        "runtime_str": runtime_str,
        "sessions_generated": sessions_generated,
        "next_session_in": next_session_in,
        "is_quiet_time": is_quiet,
        "stats": stats,
        "stats_availability": stats_availability,
        "last_runs": rows_to_list(last_runs),
    }


@app.post("/api/daemon/start")
async def start_daemon(background_tasks: BackgroundTasks):
    """Queue a GUI-owned scheduler only when no legacy or foreign PID is present."""
    global _GUI_DAEMON_STARTING, _GUI_DAEMON
    from gui.daemon_service import DaemonService, DAEMON_PID_FILE
    from gui.daemon_identity import observe_identity

    with _DAEMON_CONTROL_LOCK:
        if _GUI_DAEMON_STARTING:
            raise HTTPException(status_code=409, detail="Daemon-Start läuft bereits")
        identity = observe_identity(DAEMON_PID_FILE, BACH_DIR, local_service=_GUI_DAEMON)
        if identity["running"]:
            return {"status": "already_running", "message": "Daemon-Prozessidentität bestätigt"}
        if identity["identity"] != "stopped":
            raise HTTPException(status_code=409, detail="Daemon-Identität nicht bestätigt; Start gesperrt")
        _GUI_DAEMON_STARTING = True

    def run_daemon():
        global _GUI_DAEMON_STARTING, _GUI_DAEMON
        daemon = None
        try:
            daemon = DaemonService()
            with _DAEMON_CONTROL_LOCK:
                _GUI_DAEMON = daemon
            daemon.run(owner_kind="gui")
        finally:
            with _DAEMON_CONTROL_LOCK:
                if _GUI_DAEMON is daemon:
                    _GUI_DAEMON = None
                _GUI_DAEMON_STARTING = False

    background_tasks.add_task(run_daemon)
    return {"status": "starting", "message": "Daemon-Start eingereiht; Laufstatus erneut prüfen"}


@app.post("/api/daemon/stop")
async def stop_daemon():
    """Request graceful stop only from the verified GUI-owned service object."""
    from gui.daemon_service import DAEMON_PID_FILE
    from gui.daemon_identity import observe_identity

    with _DAEMON_CONTROL_LOCK:
        identity = observe_identity(DAEMON_PID_FILE, BACH_DIR, local_service=_GUI_DAEMON)
        if not identity["running"] or not identity["control_available"] or _GUI_DAEMON is None:
            raise HTTPException(status_code=409, detail="Steuerung ohne bestätigte lokale Prozessidentität gesperrt")
        _GUI_DAEMON.stop()
    return {"status": "stopping", "message": "Stop-Signal an bestätigten lokalen Daemon gesendet"}


@app.post("/api/daemon/kill-all")
async def kill_all_daemons():
    """Broad process-name termination has no safe ownership contract."""
    raise HTTPException(status_code=409, detail="Massenbeenden ohne Prozessidentität gesperrt")


@app.post("/api/daemon/jobs/{job_id}/run")

async def run_daemon_job(job_id: int, background_tasks: BackgroundTasks):

    """Fuehrt einen Job sofort aus."""

    from gui.daemon_service import DaemonService



    def do_run():

        daemon = DaemonService()

        daemon.load_jobs()

        return daemon.run_job(job_id, triggered_by='manual')



    background_tasks.add_task(do_run)

    return {"status": "started", "job_id": job_id}



# ═══════════════════════════════════════════════════════════════

# API ROUTES - CHAINS (B28)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/daemon/chains")

async def list_chains():

    """Listet alle Toolchains aus der DB."""

    conn = get_user_db()

    try:

        rows = conn.execute("SELECT * FROM toolchains ORDER BY id").fetchall()

    finally:

        conn.close()

    return {"chains": rows_to_list(rows), "count": len(rows)}



@app.post("/api/daemon/chains")

async def create_chain(chain: ChainCreate):

    """Erstellt eine neue Toolchain."""

    import json as _json

    # steps_json validieren

    try:

        _json.loads(chain.steps_json)

    except _json.JSONDecodeError:

        raise HTTPException(status_code=400, detail="Ungueltiges JSON in steps_json")

    conn = get_user_db()

    try:

        cursor = conn.execute("""

            INSERT INTO toolchains (name, description, trigger_type, trigger_value, steps_json, is_active)

            VALUES (?, ?, ?, ?, ?, ?)

        """, (chain.name, chain.description, chain.trigger_type, chain.trigger_value, chain.steps_json, chain.is_active))

        chain_id = cursor.lastrowid

        conn.commit()

    finally:

        conn.close()

    return {"id": chain_id, "status": "created"}



@app.put("/api/daemon/chains/{chain_id}")

async def update_chain(chain_id: int, chain: ChainUpdate):

    """Aktualisiert eine Toolchain."""

    import json as _json

    conn = get_user_db()

    try:

        existing = conn.execute("SELECT * FROM toolchains WHERE id = ?", (chain_id,)).fetchone()

        if not existing:

            raise HTTPException(status_code=404, detail="Chain nicht gefunden")

        updates = {}

        if chain.name is not None:

            updates["name"] = chain.name

        if chain.description is not None:

            updates["description"] = chain.description

        if chain.trigger_type is not None:

            updates["trigger_type"] = chain.trigger_type

        if chain.trigger_value is not None:

            updates["trigger_value"] = chain.trigger_value

        if chain.steps_json is not None:

            try:

                _json.loads(chain.steps_json)

            except _json.JSONDecodeError:

                raise HTTPException(status_code=400, detail="Ungueltiges JSON in steps_json")

            updates["steps_json"] = chain.steps_json

        if chain.is_active is not None:

            updates["is_active"] = chain.is_active

        if not updates:

            return {"status": "no_changes"}

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())

        values = list(updates.values()) + [chain_id]

        conn.execute(f"UPDATE toolchains SET {set_clause} WHERE id = ?", values)

        conn.commit()

    finally:

        conn.close()

    return {"status": "updated", "id": chain_id}



@app.put("/api/daemon/chains/{chain_id}/toggle")

async def toggle_chain(chain_id: int):

    """Aktiviert/Deaktiviert eine Toolchain."""

    conn = get_user_db()

    try:

        current = conn.execute("SELECT is_active FROM toolchains WHERE id = ?", (chain_id,)).fetchone()

        if not current:

            raise HTTPException(status_code=404, detail="Chain nicht gefunden")

        new_state = 0 if current[0] else 1

        conn.execute("UPDATE toolchains SET is_active = ? WHERE id = ?", (new_state, chain_id))

        conn.commit()

    finally:

        conn.close()

    return {"is_active": bool(new_state)}



@app.delete("/api/daemon/chains/{chain_id}")

async def delete_chain(chain_id: int):

    """Loescht eine Toolchain."""

    conn = get_user_db()

    try:

        existing = conn.execute("SELECT id FROM toolchains WHERE id = ?", (chain_id,)).fetchone()

        if not existing:

            raise HTTPException(status_code=404, detail="Chain nicht gefunden")

        conn.execute("DELETE FROM toolchain_runs WHERE chain_id = ?", (chain_id,))

        conn.execute("DELETE FROM toolchains WHERE id = ?", (chain_id,))

        conn.commit()

    finally:

        conn.close()

    return {"status": "deleted", "id": chain_id}



@app.post("/api/daemon/chains/{chain_id}/run")

async def run_chain(chain_id: int, background_tasks: BackgroundTasks):

    """Fuehrt eine Toolchain sofort aus (im Hintergrund)."""

    conn = get_user_db()

    try:

        chain = conn.execute("SELECT * FROM toolchains WHERE id = ?", (chain_id,)).fetchone()

    finally:

        conn.close()

    if not chain:

        raise HTTPException(status_code=404, detail="Chain nicht gefunden")

    def do_run():

        from hub.chain import ChainHandler

        handler = ChainHandler(BACH_DIR)

        handler._run(str(chain_id), dry_run=False)

    background_tasks.add_task(do_run)

    return {"status": "started", "chain_id": chain_id}



@app.get("/api/daemon/chains/{chain_id}/runs")

async def list_chain_runs(chain_id: int, limit: int = 10):

    """Listet Ausfuehrungen einer bestimmten Toolchain."""

    conn = get_user_db()

    try:

        rows = conn.execute(

            "SELECT * FROM toolchain_runs WHERE chain_id = ? ORDER BY id DESC LIMIT ?",

            (chain_id, limit)

        ).fetchall()

    finally:

        conn.close()

    return {"runs": rows_to_list(rows), "count": len(rows)}



# ═══════════════════════════════════════════════════════════════

# API ROUTES - WARTUNG (WARTUNG_001-003)

# ═══════════════════════════════════════════════════════════════



@app.post("/api/wartung/trigger")

async def trigger_wartung_job(request: Request, background_tasks: BackgroundTasks):

    """

    WARTUNG_001: Universeller Wartungs-Trigger.

    Fuehrt einen Wartungsjob nach Name/Typ aus.

    """

    try:

        data = await request.json()

        job_type = data.get("type", "all")  # scanner, daemon, memory, backup, all



        results = []



        # Scanner

        if job_type in ["scanner", "all"]:

            try:

                sys.path.insert(0, str(BACH_DIR))

                from agents.ati.scanner.task_scanner import TaskScanner

                scanner = TaskScanner(USER_DB)



                def do_scan():

                    scanner.scan_all()



                background_tasks.add_task(do_scan)

                results.append({"job": "scanner", "status": "started"})

            except Exception as e:

                results.append({"job": "scanner", "status": "error", "message": public_error_message()})



        # Daemon-Jobs pruefen

        if job_type in ["daemon", "all"]:

            try:

                from gui.daemon_service import DaemonService

                daemon = DaemonService()

                daemon.load_jobs()

                pending = daemon.get_pending_jobs()

                results.append({"job": "daemon", "status": "checked", "pending": len(pending)})

            except Exception as e:

                results.append({"job": "daemon", "status": "error", "message": public_error_message()})



        # Memory-Cleanup

        if job_type in ["memory", "all"]:

            try:

                # Working Memory aufraumen (aelter als 7 Tage)

                conn = get_user_db()

                cursor = conn.cursor()

                cursor.execute("""
                    DELETE FROM memory_working
                    WHERE created_at < datetime('now', '-7 days')
                """)

                deleted = cursor.rowcount

                conn.commit()

                conn.close()

                results.append({"job": "memory_cleanup", "status": "done", "deleted": deleted})

            except Exception as e:

                results.append({"job": "memory_cleanup", "status": "error", "message": public_error_message()})



        # Backup

        if job_type in ["backup", "all"]:

            try:

                import shutil

                backup_dir = BACH_DIR / "_backups"

                backup_dir.mkdir(exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")



                # User-DB Backup

                if USER_DB.exists():

                    shutil.copy2(USER_DB, backup_dir / f"user_{timestamp}.db")

                    results.append({"job": "backup", "status": "done", "file": f"user_{timestamp}.db"})

            except Exception as e:

                results.append({"job": "backup", "status": "error", "message": public_error_message()})



        return {"success": True, "results": results}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.get("/api/wartung/status")

async def get_wartung_status():

    """WARTUNG_003: Konsolidierte Wartungs-Uebersicht."""

    try:

        status = {

            "scanner": {"last_run": None, "tasks_found": 0},

            "daemon": {"running": False, "jobs_count": 0, "pending": 0},

            "memory": {"working_count": 0, "lessons_count": 0},

            "backup": {"last_backup": None, "backup_count": 0}

        }



        conn = get_user_db()



        # Scanner Status

        try:

            last_scan = conn.execute("""

                SELECT started_at, tasks_created FROM scan_runs

                ORDER BY id DESC LIMIT 1

            """).fetchone()

            if last_scan:

                status["scanner"]["last_run"] = last_scan["started_at"]

                status["scanner"]["tasks_found"] = last_scan["tasks_created"] or 0

        except (sqlite3.OperationalError, sqlite3.DatabaseError):

            pass



        # Daemon Status

        try:

            from gui.daemon_service import DaemonService

            daemon = DaemonService()

            daemon.load_jobs()

            status["daemon"]["jobs_count"] = len(daemon.jobs)

            status["daemon"]["pending"] = len(daemon.get_pending_jobs())

            status["daemon"]["running"] = Path(BACH_DIR / "data" / "daemon.pid").exists()

        except Exception:

            pass



        # Memory Status
        try:
            working = conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0]
            lessons = conn.execute("SELECT COUNT(*) FROM memory_lessons").fetchone()[0]
            status["memory"]["working_count"] = working
            status["memory"]["lessons_count"] = lessons
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass



        # Backup Status

        try:

            backup_dir = BACH_DIR / "_backups"

            if backup_dir.exists():

                backups = list(backup_dir.glob("*.db"))

                status["backup"]["backup_count"] = len(backups)

                if backups:

                    latest = max(backups, key=lambda p: p.stat().st_mtime)

                    status["backup"]["last_backup"] = datetime.fromtimestamp(

                        latest.stat().st_mtime

                    ).isoformat()

        except (OSError, ValueError):

            pass



        conn.close()

        return status

    except Exception as e:

        return {"error": public_error_message()}



# ═══════════════════════════════════════════════════════════════

# API ROUTES - TOKENS (GUI_020)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/tokens/usage")

async def get_token_usage():

    """Liefert Token-Verbrauch und Kosten."""

    try:

        conn = get_bach_db()

        

        # Gesamtverbrauch last 30 days

        usage = conn.execute("""

            SELECT 

                SUM(tokens_total) as total_tokens,

                SUM(cost_eur) as total_cost_eur,

                AVG(tokens_total) as avg_tokens_per_task

            FROM monitor_tokens

            WHERE timestamp >= date('now', '-30 days')

        """).fetchone()

        

        # Top Modell

        top_model_row = conn.execute("""

            SELECT model, SUM(tokens_total) as val 

            FROM monitor_tokens 

            WHERE model IS NOT NULL

            GROUP BY model 

            ORDER BY val DESC LIMIT 1

        """).fetchone()

        

        # Wechselkurs & Datum

        rate_row = conn.execute("SELECT exchange_rate, timestamp FROM monitor_tokens ORDER BY id DESC LIMIT 1").fetchone()

        exchange_rate = rate_row['exchange_rate'] if rate_row and rate_row['exchange_rate'] else 0.85

        rate_date = rate_row['timestamp'].split('T')[0] if rate_row and rate_row['timestamp'] else datetime.now().strftime("%Y-%m-%d")

        

        conn.close()

        

        return {

            "success": True,

            "total_tokens": usage['total_tokens'] or 0,

            "total_cost_eur": format(usage['total_cost_eur'] or 0.0, ".2f"),

            "avg_tokens_per_task": int(usage['avg_tokens_per_task'] or 0),

            "top_model": top_model_row['model'] if top_model_row else "Claude Opus 4.6",

            "exchange_rate": exchange_rate,

            "rate_date": rate_date

        }

    except Exception as e:

        return {"success": False, "error": public_error_message()}







@app.post("/api/scanner/trigger")

async def trigger_scanner(background_tasks: BackgroundTasks):

    """WARTUNG_002: Direkter Scanner-Trigger."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from agents.ati.scanner.task_scanner import TaskScanner

        scanner = TaskScanner(USER_DB)



        def do_scan():

            scanner.scan_all()



        background_tasks.add_task(do_scan)

        return {"success": True, "status": "scan_started"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





# ═══════════════════════════════════════════════════════════════

# API ROUTES - SCANNER

# ═══════════════════════════════════════════════════════════════



@app.post("/api/scanner/run")

async def run_scanner(background_tasks: BackgroundTasks):

    """Startet ATI-Scanner im Hintergrund."""

    def do_scan():

        try:

            sys.path.insert(0, str(BACH_DIR))

            # ATI-Scanner verwenden (scanner/task_scanner.py ist deprecated)

            from agents.ati.scanner.task_scanner import TaskScanner

            scanner = TaskScanner(USER_DB)

            scanner.scan_all()

        except Exception as e:

            print(f"[ERROR] Scan fehlgeschlagen: {e}")

    

    background_tasks.add_task(do_scan)

    return {"status": "scan_started"}



@app.get("/api/scanner/status")

async def get_scanner_status():

    """Liefert Scanner-Status."""

    conn = get_user_db()
    try:
        # Last run (mit Fallback)
        try:
            last_run = conn.execute("""
                SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1
            """).fetchone()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            last_run = None

        # Total tasks (mit Fallback)
        try:
            total_tasks = conn.execute("SELECT COUNT(*) FROM ati_tasks").fetchone()[0]
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            total_tasks = 0

        # Total tools (mit Fallback)
        try:
            total_tools = conn.execute("SELECT COUNT(*) FROM tool_registry").fetchone()[0]
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            total_tools = 0
    finally:
        conn.close()

    return {
        "last_run": row_to_dict(last_run) if last_run else None,
        "total_tasks": total_tasks,
        "total_tools": total_tools
    }



@app.get("/api/scanner/tools")

async def list_tools():

    """Listet registrierte Tools."""

    conn = get_user_db()
    try:
        rows = conn.execute(
            "SELECT * FROM tool_registry ORDER BY task_count DESC"
        ).fetchall()
    finally:
        conn.close()
    return {"tools": rows_to_list(rows), "count": len(rows)}



@app.get("/api/scanner/config")

async def get_scan_config():

    """Liefert Scanner-Konfiguration."""

    conn = get_user_db()
    try:
        rows = conn.execute("SELECT key, value FROM scan_config").fetchall()
        config = {}
        for row in rows:
            try:
                config[row[0]] = json.loads(row[1])
            except (json.JSONDecodeError, ValueError):
                config[row[0]] = row[1]
        return config
    except Exception:
        return {}
    finally:
        conn.close()



# ═══════════════════════════════════════════════════════════════

# API ROUTES - ATI AGENT

# ═══════════════════════════════════════════════════════════════



# /api/ati/tasks wurde zu /api/scanned-tasks konsolidiert (Alias vorhanden)



@app.get("/api/ati/stats")
async def get_ati_stats():
    """Liefert ATI-Statistiken inkl. Tages-Zähler."""
    try:
        conn = get_user_db()
        stats = {
            "total_tasks": 0,
            "open_tasks": 0,
            "tools_scanned": 0,
            "sessions_today": 0,
            "completed_today": 0
        }
        
        # Grundstatistiken
        stats["total_tasks"] = conn.execute("SELECT COUNT(*) FROM ati_tasks").fetchone()[0]
        stats["open_tasks"] = conn.execute("SELECT COUNT(*) FROM ati_tasks WHERE status = 'offen'").fetchone()[0]
        stats["tools_scanned"] = conn.execute("SELECT COUNT(DISTINCT tool_name) FROM ati_tasks").fetchone()[0]
        
        # Tages-Zähler (Sessions)
        today = datetime.now().strftime("%Y-%m-%d")
        stats["sessions_today"] = conn.execute(
            "SELECT COUNT(*) FROM memory_sessions WHERE started_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]
        
        # Tages-Zähler (Erledigt) - nutze last_modified statt updated_at
        stats["completed_today"] = conn.execute(
            "SELECT COUNT(*) FROM ati_tasks WHERE status = 'erledigt' AND last_modified LIKE ?", (f"{today}%",)
        ).fetchone()[0]
        
        conn.close()
        return stats
    except Exception as e:
        if 'conn' in locals(): conn.close()
        return {"error": public_error_message(), "total_tasks": 0, "open_tasks": 0, "tools_scanned": 0, "sessions_today": 0, "completed_today": 0}





@app.get("/api/ati/tasks/{task_id}")

async def get_ati_task(task_id: int):

    """Holt einzelnen ATI-Task."""

    conn = get_user_db()

    row = conn.execute("SELECT * FROM ati_tasks WHERE id = ?", (task_id,)).fetchone()

    conn.close()



    if not row:

        raise HTTPException(status_code=404, detail="ATI Task nicht gefunden")



    return {"task": row_to_dict(row)}

@app.get("/api/ati/sessions")
async def get_ati_sessions(limit: int = 10):
    """Liefert die letzten KI-Sessions."""
    try:
        conn = get_user_db()
        rows = conn.execute(
            "SELECT * FROM memory_sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return {"sessions": rows_to_list(rows), "count": len(rows)}
    except Exception as e:
        if 'conn' in locals(): conn.close()
        return {"sessions": [], "error": public_error_message()}


@app.post("/api/ati/session/start")
async def start_ati_session(work_time: int = 15):
    """Startet eine ATI-Session mit dem gleichen Prompt wie im Prompt-Manager.

    Generiert den ATI-Prompt, kopiert ihn in die Zwischenablage und
    triggert Claude Desktop via Hotkey.
    """
    try:
        from datetime import datetime, timedelta
        import subprocess

        # ATI-Profil laden
        profile_path = BACH_DIR / "hub" / "_services" / "daemon" / "profiles" / "ati.json"
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
        else:
            profile = {
                "name": "ati",
                "agent_prompt": "Du bist ATI (Advanced Tool Integration) - ein Software-Entwickler Agent.",
                "timeout_minutes": 15,
                "start_command": "Pruefe offene Tasks mit `bach ati task list`"
            }

        # Arbeitszeit aus Parameter oder Profil
        timeout = work_time or profile.get("timeout_minutes", 15)
        session_start = datetime.now().strftime("%H:%M")
        session_end = (datetime.now() + timedelta(minutes=timeout)).strftime("%H:%M")

        # Prompt generieren
        parts = []

        # 1. Agent-Prompt
        agent_prompt = profile.get("agent_prompt", "")
        if agent_prompt:
            parts.append(agent_prompt)

        # 2. Erste Aktion
        parts.append(f"""
## 1. ERSTE AKTION (Automatischer Modus)

```bash
cd "{BACH_DIR}"
python bach.py --startup --partner=claude --mode=silent
bach countdown {timeout} --name="Session-Ende" --notify
```""")

        # 3. SKILL.md Referenz
        skill_file = BACH_DIR / "SKILL.md"
        parts.append(f"""
## 2. SKILL.md (ab Abschnitt 2)

Lies {skill_file} und springe direkt zu Abschnitt **(2) SYSTEM**.""")

        # 4. Start-Command
        start_command = profile.get("start_command", "")
        if start_command:
            parts.append(f"\n{start_command}")

        # 5. Workflow
        parts.append("""
### AUFGABEN-WORKFLOW:
```
(A) bach beat           # Startzeit merken
(B) Aufgabe erledigen
(C) bach beat           # Endzeit = Dauer berechnen
```""")

        # 6. Session-Ende
        parts.append(f"""
## 4. SESSION-ENDE (um {session_end})

### Kontinuitaetstests (max. 2 Min):
- Lessons learned? -> `bach memory add "..."`
- Tasks erledigt? -> Im Taskmanager dokumentieren
- Neue Folgeaufgaben? -> Als neue Tasks anlegen

### Abschliessen:
```bash
bach --memory session
```""")

        prompt = "\n".join(parts)

        # In Zwischenablage kopieren
        try:
            import pyperclip
            pyperclip.copy(prompt)
        except ImportError:
            if sys.platform == "win32":
                subprocess.run(
                    ["powershell", "-Command", f"Set-Clipboard -Value '{prompt.replace(chr(39), chr(39)+chr(39))}'"],
                    capture_output=True, creationflags=0x08000000,
                    encoding='utf-8', errors='replace'
                )
            elif sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=prompt.encode("utf-8"), capture_output=True)
            else:
                import shutil
                data = prompt.encode("utf-8")
                if shutil.which("wl-copy"):
                    subprocess.run(["wl-copy"], input=data, capture_output=True)
                elif shutil.which("xsel"):
                    subprocess.run(["xsel", "-b", "-i"], input=data, capture_output=True)
                elif shutil.which("xclip"):
                    subprocess.run(["xclip", "-selection", "clipboard"], input=data, capture_output=True)

        # Claude triggern (optional - nur wenn pyautogui verfuegbar)
        triggered = False
        try:
            import pyautogui
            import time
            time.sleep(0.3)
            pyautogui.hotkey('ctrl', 'space')
            time.sleep(0.5)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.3)
            pyautogui.press('enter')
            triggered = True
        except ImportError:
            pass

        return {
            "success": True,
            "message": "ATI-Session gestartet" if triggered else "Prompt in Zwischenablage kopiert",
            "triggered": triggered,
            "work_time": timeout,
            "session_end": session_end
        }

    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/ati/session/start-cli")
async def start_ati_session_cli(work_time: int = 15, task_prompt: str = ""):
    """Startet eine ATI-Session direkt ueber Claude Code CLI.

    Oeffnet ein neues Terminal-Fenster mit 'claude' und uebergibt den
    generierten ATI-Prompt als Datei-Argument.
    """
    try:
        from datetime import datetime, timedelta
        import subprocess, tempfile

        # ATI-Profil laden
        profile_path = BACH_DIR / "hub" / "_services" / "daemon" / "profiles" / "ati.json"
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
        else:
            profile = {
                "name": "ati",
                "agent_prompt": "Du bist ATI (Advanced Tool Integration) - ein Software-Entwickler Agent.",
                "timeout_minutes": 15,
                "start_command": "Pruefe offene Tasks mit `bach ati task list`"
            }

        timeout = work_time or profile.get("timeout_minutes", 15)
        session_end = (datetime.now() + timedelta(minutes=timeout)).strftime("%H:%M")

        # Prompt zusammenbauen
        parts = []
        if profile.get("agent_prompt"):
            parts.append(profile["agent_prompt"])

        parts.append(f"Arbeitszeit: {timeout} Minuten (Ende: {session_end})")
        parts.append(f"Arbeitsverzeichnis: {BACH_DIR}")

        if task_prompt:
            parts.append(f"\n## Direktauftrag\n{task_prompt}")
        else:
            parts.append("\nLies SKILL.md und starte die Startprozedur ab Abschnitt (2) SYSTEM.")

        start_command = profile.get("start_command", "")
        if start_command:
            parts.append(f"\n{start_command}")

        prompt_text = "\n\n".join(parts)

        # Prompt als Temp-Datei speichern (claude -p liest von stdin)
        prompt_file = Path(tempfile.gettempdir()) / "bach_ati_prompt.txt"
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt_text)

        # Claude Code im neuen Terminal starten
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "", "cmd", "/k",
                 f"cd /d \"{BACH_DIR}\" && claude"],
                creationflags=0x08000000
            )
        elif sys.platform == "darwin":
            import shlex
            script = f'tell application "Terminal" to do script "cd {shlex.quote(str(BACH_DIR))} && claude"'
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            import shutil
            term = shutil.which("gnome-terminal") or shutil.which("xterm")
            if term:
                shell_cmd = f'cd "{BACH_DIR}" && claude'
                if "gnome-terminal" in term:
                    subprocess.Popen([term, "--", "bash", "-c", shell_cmd],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                else:
                    subprocess.Popen([term, "-e", "bash", "-c", shell_cmd],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)

        return {
            "success": True,
            "message": f"Claude Code Terminal geoeffnet (Arbeitsverzeichnis: {BACH_DIR})",
            "work_time": timeout,
            "session_end": session_end,
            "prompt_file": str(prompt_file),
            "hint": "Prompt wurde gespeichert. Im Claude Code Terminal: Einfach den Auftrag eingeben oder SKILL.md referenzieren."
        }

    except Exception as e:
        return {"success": False, "error": public_error_message()}


class ATITaskCreate(BaseModel):

    task_text: str

    tool_name: Optional[str] = "Manuell"

    aufwand: Optional[str] = "mittel"

    priority_score: Optional[int] = 50

    status: Optional[str] = "offen"





class ATITaskUpdate(BaseModel):

    task_text: Optional[str] = None

    tool_name: Optional[str] = None

    aufwand: Optional[str] = None

    priority_score: Optional[int] = None

    status: Optional[str] = None





@app.post("/api/ati/tasks")

async def create_ati_task(task: ATITaskCreate):

    """Erstellt neuen ATI-Task."""

    conn = get_user_db()



    # Tabelle existiert moeglicherweise noch nicht

    conn.execute("""

        CREATE TABLE IF NOT EXISTS ati_tasks (

            id INTEGER PRIMARY KEY,

            tool_name TEXT,

            task_text TEXT,

            aufwand TEXT DEFAULT 'mittel',

            priority_score REAL DEFAULT 50,

            status TEXT DEFAULT 'offen',

            created_at TEXT,

            updated_at TEXT

        )

    """)



    cursor = conn.execute("""

        INSERT INTO ati_tasks (tool_name, task_text, aufwand, priority_score, status, created_at)

        VALUES (?, ?, ?, ?, ?, ?)

    """, (

        task.tool_name,

        task.task_text,

        task.aufwand,

        task.priority_score,

        task.status,

        datetime.now().isoformat()

    ))



    task_id = cursor.lastrowid

    conn.commit()

    conn.close()



    return {"id": task_id, "status": "created"}





@app.put("/api/ati/tasks/{task_id}")

async def update_ati_task(task_id: int, update: ATITaskUpdate):

    """Aktualisiert ATI-Task."""

    conn = get_user_db()
    try:

        existing = conn.execute("SELECT id FROM ati_tasks WHERE id = ?", (task_id,)).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="ATI Task nicht gefunden")

        updates = []
        values = []

        if update.task_text is not None:
            updates.append("task_text = ?")
            values.append(update.task_text)
        if update.tool_name is not None:
            updates.append("tool_name = ?")
            values.append(update.tool_name)
        if update.aufwand is not None:
            updates.append("aufwand = ?")
            values.append(update.aufwand)
        if update.priority_score is not None:
            updates.append("priority_score = ?")
            values.append(update.priority_score)
        if update.status is not None:
            updates.append("status = ?")
            values.append(update.status)

        if updates:
            values.append(task_id)
            conn.execute(f"UPDATE ati_tasks SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()

    finally:
        conn.close()

    return {"status": "updated"}





@app.delete("/api/ati/tasks/{task_id}")

async def delete_ati_task(task_id: int):

    """Loescht ATI-Task."""

    conn = get_user_db()
    try:
        conn.execute("DELETE FROM ati_tasks WHERE id = ?", (task_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "deleted"}





# ═══════════════════════════════════════════════════════════════

# API ROUTES - SKILLS (Task #93)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/skills")

async def list_skills(category: Optional[str] = None, is_active: Optional[bool] = None, limit: int = 100):

    """Listet Skills aus bach.db mit optionalen Filtern."""

    conn = get_bach_db()
    try:
        query = "SELECT id, name, type, category, path, version, description, is_active, priority, trigger_phrases FROM skills WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if is_active is not None:
            query += " AND is_active = ?"
            params.append(1 if is_active else 0)

        query += " ORDER BY category, priority DESC, name LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    return {"skills": rows_to_list(rows), "count": len(rows)}



@app.get("/api/skills/categories")

async def list_skill_categories():

    """Listet alle Skill-Kategorien mit Zaehler."""

    conn = get_bach_db()
    try:
        rows = conn.execute("""
            SELECT category, COUNT(*) as count
            FROM skills
            GROUP BY category
            ORDER BY count DESC
        """).fetchall()
    finally:
        conn.close()

    return {"categories": [{"name": r[0], "count": r[1]} for r in rows]}



@app.get("/api/skills/{skill_id}")

async def get_skill(skill_id: int):

    """Holt einzelnen Skill mit Details."""

    conn = get_bach_db()
    try:
        row = conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Skill nicht gefunden")

    return row_to_dict(row)





@app.get("/api/system/logs")
async def list_system_logs():
    """Listet Log-Dateien aus /data/logs (konsolidiert 2026-02-06)."""
    log_dirs = {
        "data": DATA_DIR / "logs",
        "service": Path.home() / "Library" / "Logs" / "bach",
    }
    logs = []
    for source, log_dir in log_dirs.items():
        if not log_dir.exists():
            continue
        for ext in ["*.log", "*.txt", "*.md"]:
            for f in log_dir.glob(ext):
                if f.is_file():
                    stat = f.stat()
                    logs.append({
                        "name": f.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "source": source
                    })
    return {"logs": sorted(logs, key=lambda x: x['modified'], reverse=True)}



@app.get("/api/system/logs/{filename}")
async def get_log_content(filename: str, lines: int = 500, source: str = "data"):
    """Gibt die letzten N Zeilen einer Log-Datei zurueck."""
    # Sicherheit
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

    source_dirs = {
        "data": DATA_DIR / "logs",
        "service": Path.home() / "Library" / "Logs" / "bach",
    }
    base = source_dirs.get(source, DATA_DIR / "logs")
    log_file = base / filename
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log nicht gefunden")

    try:
        content_lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()
        last_lines = content_lines[-lines:] if len(content_lines) > lines else content_lines
        return {"filename": filename, "source": source, "lines": len(last_lines), "content": "\n".join(last_lines)}
    except Exception as e:
        return {"error": public_error_message()}





# ═══════════════════════════════════════════════════════════════

# GUI SETTINGS

# ═══════════════════════════════════════════════════════════════


@app.get("/api/settings/theme")
async def get_gui_theme():
    """Return the user-neutral dashboard theme preference."""
    try:
        return {"success": True, **ThemeHandler(BACH_DIR).get_theme()}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=public_error_message()) from exc


@app.put("/api/settings/theme")
async def update_gui_theme(payload: ThemeUpdate):
    """Validate and persist the dashboard theme in user_config.json."""
    try:
        handler = ThemeHandler(BACH_DIR)
        result = handler.set_theme(payload.theme, payload.custom)
        persisted = handler.get_theme()
        if persisted["theme"] != result["theme"] or persisted["custom"] != result["custom"]:
            raise HTTPException(status_code=503, detail="Theme-Speicherung nicht bestätigt")
        return {"success": True, **persisted}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Theme-Speicherung nicht verfügbar") from exc


# ═══════════════════════════════════════════════════════════════

# STATIC FILES & TEMPLATES

# ═══════════════════════════════════════════════════════════════



# Statische Dateien mounten (falls vorhanden)

if STATIC_DIR.exists():

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if (ASTRO_DIST_DIR / "_astro").exists():
    app.mount("/_astro", StaticFiles(directory=ASTRO_DIST_DIR / "_astro"), name="astro_assets")


# Operator-Konsole bleibt standardmaessig aus. Bei expliziter Aktivierung
# verwendet sie ihre bestehende Adapter-Konfiguration; BACH fuehrt weder eine
# zweite Authentifizierung noch eine zweite Unified-GUI-Konfigurationsquelle ein.
if settings.console_enabled:
    mount_console(app, prefix=settings.console_prefix)



@app.get("/ocean", response_class=HTMLResponse)
@app.get("/unified", response_class=HTMLResponse)
async def unified_ocean_dashboard():
    """Unified BACH & Ocean Workstation Dashboard."""
    dashboard_file = GUI_DIR / "unified_dashboard.html"
    if dashboard_file.exists():
        return FileResponse(dashboard_file)
    raise HTTPException(status_code=404, detail="unified_dashboard.html nicht gefunden")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Startseite (Astro v5 Modular GUI mit Legacy-Fallback)."""
    astro_index = ASTRO_DIST_DIR / "index.html"
    if astro_index.exists():
        return FileResponse(astro_index)

    index_file = TEMPLATES_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = STATIC_DIR / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404, detail="favicon.ico nicht gefunden")


@app.get("/agenten/fabrika", response_class=HTMLResponse)
async def agenten_fabrika_page():
    p = ASTRO_DIST_DIR / "agenten" / "fabrika.html"
    if p.exists():
        return FileResponse(p)
    template_file = TEMPLATES_DIR / "agents.html"
    if template_file.exists():
        return FileResponse(template_file)
    raise HTTPException(status_code=404, detail="Fabrika-Seite nicht gefunden")


@app.get("/agenten/blueprints", response_class=HTMLResponse)
async def agenten_blueprints_page():
    p = ASTRO_DIST_DIR / "agenten" / "blueprints.html"
    if p.exists():
        return FileResponse(p)
    template_file = TEMPLATES_DIR / "blueprints.html"
    if template_file.exists():
        return FileResponse(template_file)
    raise HTTPException(status_code=404, detail="Blueprints-Seite nicht gefunden")


@app.get("/agenten/running", response_class=HTMLResponse)
async def agenten_running_page():
    p = ASTRO_DIST_DIR / "agenten" / "running.html"
    if p.exists():
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Living & Running Seite nicht gefunden")


@app.get("/agenten/marblerun", response_class=HTMLResponse)
async def agenten_marblerun_page():
    p = ASTRO_DIST_DIR / "agenten" / "marblerun.html"
    if p.exists():
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="MarbleRun Seite nicht gefunden")


@app.get("/governance", response_class=HTMLResponse)
async def governance_page():
    for candidate in [ASTRO_DIST_DIR / "governance.html", ASTRO_DIST_DIR / "governance" / "index.html"]:
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="Governance Seite nicht gefunden")


@app.get("/governance/funk", response_class=HTMLResponse)
async def governance_funk_page():
    p = ASTRO_DIST_DIR / "governance" / "funk.html"
    if p.exists():
        return FileResponse(p)
    return await governance_page()


@app.get("/governance/usecases", response_class=HTMLResponse)
async def governance_usecases_page():
    p = ASTRO_DIST_DIR / "governance" / "usecases.html"
    if p.exists():
        return FileResponse(p)
    usecases_file = TEMPLATES_DIR / "usecases.html"
    if usecases_file.exists():
        return FileResponse(usecases_file)
    raise HTTPException(status_code=404, detail="Governance Use Cases nicht gefunden")


@app.get("/governance/logs", response_class=HTMLResponse)
async def governance_logs_page():
    p = ASTRO_DIST_DIR / "governance" / "logs.html"
    if p.exists():
        return FileResponse(p)
    logs_file = TEMPLATES_DIR / "logs.html"
    if logs_file.exists():
        return FileResponse(logs_file)
    raise HTTPException(status_code=404, detail="Governance Logs nicht gefunden")



@app.get("/life", response_class=HTMLResponse)
async def life_page():
    p = ASTRO_DIST_DIR / "life.html"
    if p.exists():
        return FileResponse(p)
    life_template = TEMPLATES_DIR / "life.html"
    if life_template.exists():
        return FileResponse(life_template)
    pers_file = TEMPLATES_DIR / "persoenlich.html"
    if pers_file.exists():
        return FileResponse(pers_file)
    raise HTTPException(status_code=404, detail="Life-Seite nicht gefunden")


@app.get("/api/life/providers")
async def get_life_providers():
    """Prüft die Verfügbarkeit von externen Life-Providern (Routinika, UpToDay, Health, Balance)."""
    # Fail-closed: nur wenn ein tatsächlicher Startvertrag oder verifizierter Prozess existiert
    routinika_installed = False
    uptoday_installed = False
    return {
        "routinika": {
            "available": routinika_installed,
            "url": None,
            "status": "available" if routinika_installed else "in_progress",
            "message": "Routinika Desktop/Web verfügbar" if routinika_installed else "Routinika ist als Desktop-App belegt; ein verifizierter Web-Startvertrag und eine Installation auf diesem Gerät fehlen."
        },
        "uptoday": {
            "available": uptoday_installed,
            "url": None,
            "status": "available" if uptoday_installed else "in_progress",
            "message": "UpToday Web verfügbar" if uptoday_installed else "Für UpToday ist keine installierte Web-Oberfläche mit verifiziertem Startvertrag belegt."
        },
        "health": {
            "available": False,
            "status": "in_progress",
            "message": "Die bisherige Gesundheitsansicht enthält nur geplante Funktionen. Für Vitalwerte, Arzttermine und Medikamente fehlen ein geprüfter Fachadapter, ein Datenvertrag und ein Gerätezugriffsvertrag. Hier werden keine Gesundheitsdaten gelesen oder angezeigt."
        },
        "balance": {
            "available": False,
            "status": "in_progress",
            "message": "In Arbeit. Für persönliche Balancewerte fehlen eine freiwillige Eingabe, ein nachvollziehbares Bewertungsverfahren und eine geschützte Speicherung. Es werden keine Prozentwerte geschätzt."
        }
    }


@app.get("/domains", response_class=HTMLResponse)
async def domains_page():
    p = ASTRO_DIST_DIR / "domains.html"
    if p.exists():
        return FileResponse(p)
    dom_file = TEMPLATES_DIR / "domains.html"
    if dom_file.exists():
        return FileResponse(dom_file)
    ati_file = TEMPLATES_DIR / "ati.html"
    if ati_file.exists():
        return FileResponse(ati_file)
    raise HTTPException(status_code=404, detail="Domains-Seite nicht gefunden")


@app.get("/foerderplaner", response_class=HTMLResponse)
async def foerderplaner_fachseite_page():
    """Förderplaner Fachseite (GUX-070: Domänen sind Fachbereiche, keine Agenten)."""
    p = ASTRO_DIST_DIR / "foerderplaner.html"
    if p.exists():
        return FileResponse(p)
    template_file = TEMPLATES_DIR / "anonymization.html"
    if template_file.exists():
        return FileResponse(template_file)
    return RedirectResponse("/agents/foerderplaner")


@app.get("/steuer-assistent")
async def steuer_assistent_redirect():
    """Steuer-Assistent Fachseite (GUX-070)."""
    return RedirectResponse("/steuer")


@app.get("/anonymizer", response_class=HTMLResponse)
async def anonymizer_fachseite_page():
    """Anonymizer Fachseite (GUX-070)."""
    p = ASTRO_DIST_DIR / "anonymizer.html"
    if p.exists():
        return FileResponse(p)
    template_file = TEMPLATES_DIR / "anonymization.html"
    if template_file.exists():
        return FileResponse(template_file)
    return RedirectResponse("/domains")


@app.get("/artefakte", response_class=HTMLResponse)
async def artefakte_page():
    p = ASTRO_DIST_DIR / "artefakte.html"
    if p.exists():
        return FileResponse(p)
    inbox_file = TEMPLATES_DIR / "inbox.html"
    if inbox_file.exists():
        return FileResponse(inbox_file)
    raise HTTPException(status_code=404, detail="Artefakte-Seite nicht gefunden")


@app.get("/agenten/sessions", response_class=HTMLResponse)
async def agenten_sessions_page():
    p = ASTRO_DIST_DIR / "agenten" / "sessions.html"
    if p.exists():
        return FileResponse(p)
    tpl = TEMPLATES_DIR / "sessions.html"
    if tpl.exists():
        return FileResponse(tpl)
    raise HTTPException(status_code=503, detail="Sessions-Seite noch nicht gebaut")


    

    # Fallback: Einfache Status-Seite

    return """

    <!DOCTYPE html>

    <html>

    <head><title>BACH Dashboard</title></head>

    <body>

        <h1>BACH v1.1 Dashboard</h1>

        <p>API verfuegbar unter <a href="/docs">/docs</a></p>

    </body>

    </html>

    """



@app.get("/inbox", response_class=HTMLResponse)

async def inbox_page():

    """Inbox Seite."""

    inbox_file = TEMPLATES_DIR / "inbox.html"

    if inbox_file.exists():

        return FileResponse(inbox_file)

    raise HTTPException(status_code=404, detail="Template inbox.html nicht gefunden")



@app.get("/daemon", response_class=HTMLResponse)

async def daemon_page():

    """Daemon Manager Seite."""

    daemon_file = TEMPLATES_DIR / "daemon.html"

    if daemon_file.exists():

        return FileResponse(daemon_file)

    raise HTTPException(status_code=404, detail="Template daemon.html nicht gefunden")



@app.get("/tasks", response_class=HTMLResponse)

async def tasks_page():

    """Tasks Seite."""

    astro_tasks = ASTRO_DIST_DIR / "tasks.html"
    if astro_tasks.exists():
        return FileResponse(astro_tasks)

    tasks_file = TEMPLATES_DIR / "tasks.html"
    if tasks_file.exists():
        return FileResponse(tasks_file)

    raise HTTPException(status_code=404, detail="Template tasks.html nicht gefunden")






@app.get("/user-inbox", response_class=HTMLResponse)
async def user_inbox_page():
    """Nachrichten an den Nutzer; Chats und Läufe haben eigene Ansichten."""
    page = ASTRO_DIST_DIR / "user-inbox.html"
    if page.is_file():
        return FileResponse(page)
    raise HTTPException(status_code=503, detail="Inbox-Oberfläche noch nicht installiert")


@app.get("/messages", response_class=HTMLResponse)
async def messages_page():
    """Compatibility redirect for old bookmarks."""
    return RedirectResponse(url="/user-inbox", status_code=307)


@app.get("/reports", response_class=HTMLResponse)
async def reports_page():
    """Berichte & Abschlussberichte Seite (Alias fuer messages.html)."""
    messages_file = TEMPLATES_DIR / "messages.html"
    if messages_file.exists():
        return FileResponse(messages_file)
    raise HTTPException(status_code=404, detail="Template messages.html nicht gefunden")



@app.get("/help", response_class=HTMLResponse)

async def help_page():

    """Help/Dokumentation Seite."""

    help_file = TEMPLATES_DIR / "help.html"

    if help_file.exists():

        return FileResponse(help_file)

    raise HTTPException(status_code=404, detail="Template help.html nicht gefunden")





@app.get("/maintenance", response_class=HTMLResponse)

async def maintenance_page():

    """Wartungs-Board Seite."""

    maintenance_file = TEMPLATES_DIR / "maintenance.html"

    if maintenance_file.exists():

        return FileResponse(maintenance_file)

    # Fallback zu daemon.html falls maintenance noch nicht existiert

    daemon_file = TEMPLATES_DIR / "daemon.html"

    if daemon_file.exists():

        return FileResponse(daemon_file)

    raise HTTPException(status_code=404, detail="Template daemon.html nicht gefunden")





@app.get("/logs", response_class=HTMLResponse)
async def logs_page():
    """Logs Anzeige Seite."""
    astro_log = ASTRO_DIST_DIR / "governance" / "logs.html"
    if astro_log.exists():
        return FileResponse(astro_log)
    logs_file = TEMPLATES_DIR / "logs.html"
    if logs_file.exists():
        return FileResponse(logs_file)
    raise HTTPException(status_code=404, detail="Template logs.html nicht gefunden")



@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    """Buddha Chat Seite."""
    chat_file = TEMPLATES_DIR / "chat.html"
    if chat_file.exists():
        return FileResponse(chat_file)
    raise HTTPException(status_code=404, detail="Template chat.html nicht gefunden")


@app.api_route("/api/chat-control/{control_path:path}", methods=["GET", "POST"])
async def chat_control_proxy(control_path: str, request: Request):
    """Bind the GUI chat to Startspine's resolved local Control port."""
    if control_path not in CHAT_CONTROL_PATHS:
        raise HTTPException(status_code=404, detail="Unbekannter Chat-Control-Pfad")
    base_url = _chat_control_base_url()
    if not base_url:
        raise HTTPException(status_code=503, detail="Chatdienst nicht registriert")
    control_authorization = get_control_api_auth_header()
    if not control_authorization:
        raise HTTPException(status_code=503, detail="Interne Chat-Autorisierung nicht verfügbar")
    # Task #1338: STT kann das Whisper-Modell nachladen (einmalig ~Minuten) —
    # daher ein deutlich hoeherer Timeout als fuer Status-/Steuerpfade.
    if control_path == "chat":
        timeout = _chat_proxy_timeout()
    elif control_path == "transcribe":
        timeout = 600.0
    else:
        timeout = 8.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream_headers = {"authorization": control_authorization}
            status_url = f"{base_url}/status"
            if upstream_headers:
                status_response = await client.get(status_url, headers=upstream_headers)
            else:
                status_response = await client.get(status_url)
            try:
                status_payload = status_response.json()
            except ValueError:
                status_payload = None
            if status_response.status_code != 200 or not _chat_control_payload_ready(status_payload):
                raise HTTPException(status_code=503, detail="Chatdienst-Identität nicht bestätigt")
            if request.method == "GET" and control_path in {"history", "sessions", "session"}:
                auth_response = await client.get(f"{base_url}/auth/check", headers=upstream_headers)
                try:
                    auth_payload = auth_response.json()
                except ValueError:
                    auth_payload = None
                if (auth_response.status_code != 200 or not isinstance(auth_payload, dict)
                        or auth_payload.get("authenticated") is not True):
                    raise HTTPException(status_code=503, detail="Interne Chat-Autorisierung fehlgeschlagen")
            if control_path == "status" and request.method == "GET":
                upstream = status_response
            else:
                headers = dict(upstream_headers)
                for name in ("content-type", "x-delegation-depth"):
                    if request.headers.get(name):
                        headers[name] = request.headers[name]
                upstream = await client.request(
                    request.method,
                    f"{base_url}/{control_path}",
                    params=request.query_params,
                    content=await request.body(),
                    headers=headers,
                )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Chatdienst nicht erreichbar") from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"content-type": upstream.headers.get("content-type", "application/json")},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """Zentrale GUI-Einstellungen."""
    astro_settings = ASTRO_DIST_DIR / "settings.html"
    if astro_settings.exists():
        return FileResponse(astro_settings)
    settings_file = TEMPLATES_DIR / "settings.html"
    if settings_file.exists():
        return FileResponse(settings_file)
    raise HTTPException(status_code=404, detail="Template settings.html nicht gefunden")


@app.get("/system", response_class=HTMLResponse)
async def system_page():
    """System-Route leitet auf Einstellungen/Setup weiter."""
    return await settings_page()





@app.get("/wiki", response_class=HTMLResponse)

async def wiki_page():

    """Wiki Seite."""

    wiki_file = TEMPLATES_DIR / "wiki.html"

    if wiki_file.exists():

        return FileResponse(wiki_file)

    raise HTTPException(status_code=404, detail="Template wiki.html nicht gefunden")



@app.get("/agents", response_class=HTMLResponse)
async def agents_page():
    """Agenten-Uebersicht Seite."""
    agents_file = TEMPLATES_DIR / "agents.html"
    if agents_file.exists():
        return FileResponse(agents_file)
    raise HTTPException(status_code=404, detail="Template agents.html nicht gefunden")

@app.get("/ati", response_class=HTMLResponse)
@app.get("/agents/ati", response_class=HTMLResponse)
async def ati_agent_page():
    """ATI Agent Dashboard Seite."""
    ati_file = TEMPLATES_DIR / "ati.html"
    if ati_file.exists():
        return FileResponse(ati_file)
    raise HTTPException(status_code=404, detail="Template ati.html nicht gefunden")





@app.get("/partners")
async def partners_page():
    """Partner Dashboard -> Konsolidiert im Agents Board."""
    return RedirectResponse("/agents-board")





@app.get("/agents/steuer", response_class=HTMLResponse)

async def steuer_dashboard_page():

    """Steuer Agent Dashboard - Redirect zu Scanner vorerst."""

    # TODO: Eigenes Steuer-Dashboard

    steuer_file = TEMPLATES_DIR / "steuer.html"

    if steuer_file.exists():

        return FileResponse(steuer_file)

    return HTMLResponse("<h1>Steuer Dashboard</h1><p>Template noch nicht implementiert</p>")



@app.get("/agents/gesundheit", response_class=HTMLResponse)

async def gesundheit_dashboard_page():

    """Gesundheitsassistent Dashboard."""

    template_file = TEMPLATES_DIR / "gesundheit.html"

    if template_file.exists():

        return FileResponse(template_file)

    raise HTTPException(status_code=404, detail="Template gesundheit.html nicht gefunden")



@app.get("/agents/persoenlich", response_class=HTMLResponse)

async def persoenlich_dashboard_page():

    """Persoenlicher Assistent Dashboard."""

    template_file = TEMPLATES_DIR / "persoenlich.html"

    if template_file.exists():

        return FileResponse(template_file)

    raise HTTPException(status_code=404, detail="Template persoenlich.html nicht gefunden")



@app.get("/agents/foerderplaner", response_class=HTMLResponse)
async def foerderplaner_dashboard_page():
    """Foerderplaner Dashboard."""
    template_file = TEMPLATES_DIR / "anonymization.html"
    if template_file.exists():
        return FileResponse(template_file)
    raise HTTPException(status_code=404, detail="Template anonymization.html nicht gefunden")



@app.get("/agents-board", response_class=HTMLResponse)
@app.get("/skills-board", response_class=HTMLResponse)
async def skills_board_page(request: Request):
    """Deprecated aliases; editing and chains live in the shared GUI."""
    target = "/skills" if request.url.path == "/skills-board" else "/agenten/blueprints"
    return RedirectResponse(target, status_code=307)


@app.get("/skills")
async def skills_page():
    """Current Skill-Zentrale with the actual SKILL.md editor."""
    p = ASTRO_DIST_DIR / "skills.html"
    if p.exists():
        return FileResponse(p)
    tpl = TEMPLATES_DIR / "skills.html"
    if tpl.exists():
        return FileResponse(tpl)
    return RedirectResponse("/agents-board")


@app.get("/skills/plugins")
@app.get("/skills/mcp")
@app.get("/skills/software")
@app.get("/skills/ocean")
async def capability_board_page(request: Request):
    """Separate static boards; all host inventories require device authentication."""
    name = request.url.path.rsplit("/", 1)[-1]
    if name not in {"plugins", "mcp", "software", "ocean"}:
        raise HTTPException(404, "Board nicht gefunden")
    page = ASTRO_DIST_DIR / "skills" / (name + ".html")
    if not page.is_file():
        raise HTTPException(503, "Board noch nicht gebaut")
    return FileResponse(page)

@app.get("/finanzen")
async def finanzen_redirect():
    return RedirectResponse("/financial")

@app.get("/steuer")
async def steuer_redirect():
    return RedirectResponse("/agents/steuer")

@app.get("/gesundheit")
async def gesundheit_redirect():
    return RedirectResponse("/agents/gesundheit")

@app.get("/persoenlich")
async def persoenlich_redirect():
    return RedirectResponse("/agents/persoenlich")

@app.get("/routines")
async def routines_redirect():
    return RedirectResponse("/routinen")



@app.get("/denkarium", response_class=HTMLResponse)

async def denkarium_page():

    """Denkarium — Logbuch und Gedanken-Sammler."""

    f = TEMPLATES_DIR / "denkarium.html"

    if f.exists():

        return FileResponse(f)

    raise HTTPException(status_code=404, detail="Template denkarium.html nicht gefunden")



@app.get("/api/denkarium")
async def denkarium_list(entry_type: str = None, category: str = None, limit: int = 50, search: str = None, exclude_archived: bool = True):
    """Denkarium-Einträge abrufen (GUX-043)."""
    conn = sqlite3.connect(str(USER_DB))
    try:
        ensure_denkarium_schema(conn)
        query = "SELECT id, entry_type, title, content, category, source, mood, promoted_to, promoted_id, is_archived, archived_reason, archived_at, created_at, updated_at FROM denkarium_entries"
        conditions = []
        params = []
        if exclude_archived:
            conditions.append("(is_archived = 0 OR is_archived IS NULL)")
        if entry_type:
            conditions.append("entry_type = ?")
            params.append(entry_type)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if search:
            conditions.append("(content LIKE ? OR title LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = conn.execute(query, params)
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        entries = [dict(zip(cols, row)) for row in rows]
        stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_archived = 1 THEN 1 ELSE 0 END) as archived_count,
                SUM(CASE WHEN (is_archived = 0 OR is_archived IS NULL) AND entry_type = 'logbuch' THEN 1 ELSE 0 END) as logbuch,
                SUM(CASE WHEN (is_archived = 0 OR is_archived IS NULL) AND (entry_type = 'denkarium' OR entry_type IS NULL) THEN 1 ELSE 0 END) as denkarium
            FROM denkarium_entries
        """).fetchone()
        categories = conn.execute("SELECT category, COUNT(*) as cnt FROM denkarium_entries WHERE (is_archived = 0 OR is_archived IS NULL) GROUP BY category ORDER BY cnt DESC").fetchall()
        return {
            "entries": entries,
            "count": len(entries),
            "stats": {
                "total": (stats[0] or 0) if stats else 0,
                "archived": (stats[1] or 0) if stats else 0,
                "logbuch": (stats[2] or 0) if stats else 0,
                "denkarium": (stats[3] or 0) if stats else 0
            },
            "categories": [{"name": c[0], "count": c[1]} for c in categories]
        }
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return {"entries": [], "count": 0, "stats": {"total": 0, "archived": 0, "logbuch": 0, "denkarium": 0}, "categories": []}
    finally:
        conn.close()



@app.post("/api/denkarium")

async def denkarium_create(request: Request):

    """Neuen Denkarium-Eintrag erstellen."""

    data = await request.json()

    content = data.get("content", "").strip()

    if not content:

        raise HTTPException(status_code=400, detail="Inhalt darf nicht leer sein")

    entry_type = data.get("entry_type", "denkarium")

    category = data.get("category", "notiz")

    title = data.get("title")

    mood = data.get("mood")

    source = data.get("source", "web")

    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if entry_type == "logbuch" and not title:

        title = f"Sternzeit {now}"

    conn = sqlite3.connect(str(USER_DB))

    try:

        conn.execute("INSERT INTO denkarium_entries (entry_type, title, content, category, source, mood, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",

            (entry_type, title, content, category, source, mood, now))

        row = conn.execute("SELECT last_insert_rowid()").fetchone()

        entry_id = row[0] if row else 0

        conn.commit()

    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:

        return JSONResponse(status_code=500, content={"ok": False, "error": public_error_message()})

    finally:

        conn.close()

    return {"ok": True, "id": entry_id, "message": f"Eintrag #{entry_id} gespeichert"}



@app.delete("/api/denkarium/{entry_id}")

async def denkarium_delete(entry_id: int):

    """Denkarium-Eintrag löschen."""

    conn = sqlite3.connect(str(USER_DB))

    try:

        conn.execute("DELETE FROM denkarium_entries WHERE id = ?", (entry_id,))

        conn.commit()

    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:

        return JSONResponse(status_code=500, content={"ok": False, "error": public_error_message()})

    finally:

        conn.close()

    return {"ok": True}


@app.post("/api/denkarium/{entry_id}/archive")
async def denkarium_archive_direct(entry_id: int, request: Request):
    """Denkarium-Eintrag reversibel archivieren (GUX-043)."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    reason = data.get("reason", "wrong_agent_dump") if isinstance(data, dict) else "wrong_agent_dump"
    conn = sqlite3.connect(str(USER_DB))
    try:
        return archive_denkarium_entry(entry_id, reason=reason, conn=conn)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    finally:
        conn.close()


@app.post("/api/denkarium/{entry_id}/unarchive")
async def denkarium_unarchive_direct(entry_id: int):
    """Archivierten Denkarium-Eintrag wiederherstellen (GUX-043)."""
    conn = sqlite3.connect(str(USER_DB))
    try:
        return unarchive_denkarium_entry(entry_id, conn=conn)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    finally:
        conn.close()


@app.post("/api/denkarium/{entry_id}/promote")

async def denkarium_promote(entry_id: int, request: Request):

    """Denkarium-Eintrag zu Task befördern."""

    data = await request.json()

    target = data.get("target", "task")

    conn = sqlite3.connect(str(USER_DB))

    try:

        entry = conn.execute("SELECT id, title, content FROM denkarium_entries WHERE id = ?", (entry_id,)).fetchone()

        if not entry:

            raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")

        title = entry[1] or (entry[2][:50] if entry[2] else "Denkarium-Eintrag")

        if target == "task":

            conn.execute("INSERT INTO tasks (title, description, status, priority, assigned_to, dist_type) VALUES (?, ?, 'pending', 3, 'user', 0)", (title, entry[2]))

            row = conn.execute("SELECT last_insert_rowid()").fetchone()

            promoted_id = row[0] if row else 0

        else:

            raise HTTPException(status_code=400, detail=f"Unbekanntes Ziel: {target}. Erlaubt: task")

        from datetime import datetime

        conn.execute("UPDATE denkarium_entries SET promoted_to = ?, promoted_id = ?, updated_at = ? WHERE id = ?",

            (target, promoted_id, datetime.now().isoformat(), entry_id))

        conn.commit()

    except HTTPException:

        raise

    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:

        return JSONResponse(status_code=500, content={"ok": False, "error": public_error_message()})

    finally:

        conn.close()

    return {"ok": True, "promoted_id": promoted_id}



@app.get("/tokens", response_class=HTMLResponse)

async def tokens_page():

    """Token Dashboard Seite."""

    tokens_file = TEMPLATES_DIR / "tokens.html"

    if tokens_file.exists():

        return FileResponse(tokens_file)

    raise HTTPException(status_code=404, detail="Template tokens.html nicht gefunden")


@app.get("/token-dashboard", response_class=HTMLResponse)
async def token_dashboard_page():
    """Device Token Dashboard Seite (Task #1501)."""
    tokens_file = TEMPLATES_DIR / "token-dashboard.html"
    if tokens_file.exists():
        return FileResponse(tokens_file)
    raise HTTPException(status_code=404, detail="Template token-dashboard.html nicht gefunden")


# ── API ROUTES - DEVICES AUTH (Task #1499) ──────────────────────

@app.get("/api/devices")
async def api_list_devices():
    """List all registered devices (names, statuses, timestamps)."""
    return {"devices": list_devices()}


@app.post("/api/devices")
async def api_create_device(payload: dict = Body(...)):
    """Register a new device and return its one-time plaintext token."""
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name ist erforderlich.")
    try:
        token = create_device(name)
        return {"ok": True, "name": name, "token": token, "status": "active"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.delete("/api/devices/{name}")
@app.post("/api/devices/{name}/revoke")
async def api_revoke_device(name: str):
    """Revoke a device token by name."""
    success = revoke_device(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Gerät '{name}' nicht gefunden oder bereits gesperrt.")
    return {"ok": True, "name": name, "status": "revoked"}


@app.post("/api/devices/verify")
async def api_verify_device(request: Request, payload: dict = Body(None)):
    """Verify whether a token is valid and active."""
    token = None
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif payload and isinstance(payload, dict):
        token = payload.get("token")

    if not token:
        return {"valid": False, "reason": "No token provided"}

    device = validate_token(token)
    if device:
        return {"valid": True, "device": device}
    return {"valid": False, "reason": "Invalid or revoked token"}







@app.get("/tasks-board", response_class=HTMLResponse)
async def tasks_board_api():
    """Tasks Board Seite."""

    astro_tasks = ASTRO_DIST_DIR / "tasks.html"
    if astro_tasks.exists():
        return FileResponse(astro_tasks)

    try:
        from gui.board_renderers import render_tasks_board
        return HTMLResponse(render_tasks_board())
    except Exception as render_error:
        board_file = TEMPLATES_DIR / "tasks_board.html"
        if board_file.is_file():
            try:
                from gui.board_renderers import (
                    DEFAULT_TASKS_BOARD_BRANDING,
                    _apply_common_replacements,
                )
                rendered = _apply_common_replacements(
                    board_file.read_text(encoding="utf-8"),
                    dict(DEFAULT_TASKS_BOARD_BRANDING),
                )
                return HTMLResponse(rendered)
            except Exception as fallback_error:
                raise HTTPException(status_code=500, detail="Tasks Board konnte nicht gerendert werden") from fallback_error
        if not board_file.exists():
            raise HTTPException(status_code=404, detail="Template tasks_board.html nicht gefunden")
        raise HTTPException(status_code=500, detail="Tasks Board konnte nicht gerendert werden") from render_error





@app.get("/api/inbox/config")

async def api_get_inbox_config():

    """Lädt die aktuelle Inbox-Konfiguration."""

    config_file = DATA_DIR / "inbox_config.json"

    if config_file.exists():

        try:

            return json.loads(config_file.read_text(encoding='utf-8'))

        except Exception as e:

            return {"success": False, "error": public_error_message()}

    return {"success": False, "error": "Konfigurationsdatei nicht gefunden"}





@app.post("/api/ai/headless/run")

async def api_ai_headless_run(payload: dict = Body(...)):

    """Triggert eine Headless AI Session."""

    from threading import Thread
    from tools.headless_agent import run_headless_query

    

    prompt = str(payload.get("prompt") or "")

    partner = safe_partner_name(payload.get("partner", "claude"))

    

    if not prompt:

        return {"success": False, "error": "Prompt fehlt"}

    if "\x00" in prompt or len(prompt) > 100000:

        raise HTTPException(status_code=400, detail="Ungueltiger Prompt")


    try:

        # Async-Start: Der Headless-Worker pollt bis zu zwei Minuten auf die Antwort.
        Thread(
            target=run_headless_query,
            args=(BACH_DB, prompt, partner),
            daemon=True,
        ).start()

        return {"success": True, "message": "Headless Session gestartet. Antwort erscheint in der Inbox."}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.post("/api/inbox/config")

async def api_save_inbox_config(payload: dict = Body(...)):

    """Speichert die Inbox-Konfiguration."""

    config_file = DATA_DIR / "inbox_config.json"

    try:

        config_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')

        return {"success": True, "message": "Konfiguration gespeichert"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}

    """Listet alle Tools (Python + DB) im vom Dashboard erwarteten Format."""

    import re

    python_tools = []

    

    categories_map = {

        "c_": "Coding",

        "agent_": "Agent",

        "backup_": "Backup",

        "ollama_": "Ollama",

        "steuer_": "Steuer",

        "policy_": "Policy",

        "migrate_": "Migration"

    }

    

    found_categories = set()

    

    if TOOLS_DIR.exists():

        for tool_file in sorted(TOOLS_DIR.glob("*.py")):

            if tool_file.name.startswith('__'):

                continue

                

            name = tool_file.stem

            category = "Andere"

            prefix = ""

            for pref, cat_name in categories_map.items():

                if name.startswith(pref):

                    category = cat_name

                    prefix = pref.rstrip('_')

                    break

            

            found_categories.add(category)

            

            # Docstring extrahieren

            description = ""

            try:

                content = tool_file.read_text(encoding='utf-8', errors='ignore')

                docstring_match = re.search(r'"""(.*?)"""', content, re.DOTALL)

                if docstring_match:

                    description = docstring_match.group(1).strip().split('\n')[0]

            except (OSError, UnicodeDecodeError):

                pass

                

            python_tools.append({

                "name": name,

                "path": str(tool_file.relative_to(BACH_DIR)),

                "prefix": prefix,

                "category": category,

                "description": description,

                "type": "python"

            })

            

    # Mock DB tools if none exist (or load from real DB if available)

    db_tools = []

    try:

        conn = get_bach_db()

        rows = conn.execute("SELECT name, type, category, description FROM tools").fetchall()

        for row in rows:

            db_tools.append({

                "name": row[0],

                "type": row[1],

                "category": row[2],

                "description": row[3]

            })

            if row[2]: found_categories.add(row[2])

        conn.close()

    except (sqlite3.OperationalError, sqlite3.DatabaseError):

        pass



@app.get("/api/steuer/dokumente/unlinked")

async def api_steuer_unlinked_docs(username: str = "user", jahr: int = 2025):

    """Liefert Dokumente, die noch nicht mit einem Posten verknüpft sind."""

    try:

        conn = get_bach_db() # Nutzt bach.db (Unified DB seit v1.1.84)

        # In data/bach.db suchen

        rows = conn.execute("""

            SELECT id, dateiname, status, posten_anzahl, hochgeladen_am 

            FROM steuer_dokumente 

            WHERE username = ? AND steuerjahr = ? AND posten_anzahl = 0

            ORDER BY hochgeladen_am DESC

        """, (username, jahr)).fetchall()

        conn.close()

        return {"success": True, "docs": [dict(row) for row in rows]}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.post("/api/steuer/posten/{posten_id}/link")

async def api_steuer_link_posten(posten_id: int, payload: dict = Body(...)):

    """Verknüpft einen Posten mit einem Dokument."""

    doc_id = payload.get("dokument_id")

    if not doc_id:

        return {"success": False, "error": "Keine dokument_id angegeben"}

        

    try:

        conn = get_bach_db()

        # 1. Posten aktualisieren

        conn.execute("UPDATE steuer_posten SET dokument_id = ? WHERE id = ?", (doc_id, posten_id))

        

        # 2. Dokumentenzähler aktualisieren

        conn.execute("UPDATE steuer_dokumente SET posten_anzahl = posten_anzahl + 1, status = 'ERFASST' WHERE id = ?", (doc_id,))

        

        conn.commit()

        conn.close()

        return {"success": True, "message": "Posten erfolgreich verknüpft"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.post("/api/steuer/match-bank")

async def api_steuer_match_bank(payload: dict = Body(...)):

    """Triggert den Bank-Abgleich."""

    camt_file = str(payload.get("camt_file") or "")

    username = safe_cli_value(payload.get("username", "user"), field_name="Benutzername")

    try:
        jahr = int(payload.get("jahr", 2025))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Ungueltiges Jahr")
    if jahr < 2000 or jahr > 2100:
        raise HTTPException(status_code=400, detail="Ungueltiges Jahr")

    

    if not camt_file:

        return {"success": False, "error": "CAMT Datei fehlt"}

        

    normalized_camt = camt_file.replace("\\", "/")
    if "/" in normalized_camt:
        camt_path = resolve_under_base(BACH_DIR, normalized_camt, allowed_suffixes={".xml"}, must_exist=True)
    else:
        camt_name = safe_path_segment(normalized_camt, field_name="CAMT-Dateiname")
        camt_path = None
        for base_dir in (
            BACH_DIR,
            DATA_DIR,
            BACH_DIR / "user" / "inbox",
            BACH_DIR / "user" / "inbox" / "unsortiert",
        ):
            candidate = resolve_child_file(base_dir, camt_name, allowed_suffixes={".xml"})
            if candidate.exists() and candidate.is_file():
                camt_path = candidate
                break
        if camt_path is None:
            raise HTTPException(status_code=404, detail="CAMT Datei nicht gefunden")

    _ = (camt_path, username, jahr)
    raise HTTPException(status_code=503, detail="Bank-Matcher ist nicht installiert")





@app.get("/api/tools/{name}")

async def api_get_tool_detail(name: str):

    """Details zu einem Tool abrufen."""

    import re

    name = safe_tool_name(name)

    # 1. In Python-Tools suchen

    tool_file = resolve_tool_file(name)

            

    if tool_file and tool_file.exists():

        content = tool_file.read_text(encoding='utf-8', errors='ignore')

        docstring = ""

        docstring_match = re.search(r'"""(.*?)"""', content, re.DOTALL)

        if docstring_match:

            docstring = docstring_match.group(1).strip()

            

        return {

            "name": name,

            "type": "python",

            "path": str(tool_file.relative_to(BACH_DIR)),

            "docstring": docstring,

            "lines": len(content.splitlines())

        }

        

    # 2. In DB suchen

    try:

        conn = get_bach_db()

        row = conn.execute("SELECT * FROM tools WHERE name = ?", (name,)).fetchone()

        conn.close()

        if row:

            return dict(row)

    except (sqlite3.OperationalError, sqlite3.DatabaseError):

        pass



    raise HTTPException(status_code=404, detail="Tool nicht gefunden")





@app.post("/api/tools/{name}/run")

async def api_run_tool(name: str, payload: dict = Body(...)):

    """Tool ausführen."""

    import subprocess

    import sys

    

    name = safe_tool_name(name)
    tool_file = resolve_tool_file(name)

            

    if not tool_file or not tool_file.exists():

        raise HTTPException(status_code=404, detail="Tool nicht gefunden oder nicht ausführbar")

        

    args = payload.get("args", [])
    if args:
        raise HTTPException(status_code=400, detail="Tool-Argumente sind ohne Schema nicht erlaubt")

    try:

        process = subprocess.run(

            [sys.executable, str(tool_file)],

            capture_output=True,

            text=True,

            encoding='utf-8', errors='replace',

            timeout=30,

            cwd=str(BACH_DIR)

        )

        return {

            "success": True,

            "stdout": process.stdout,

            "stderr": process.stderr,

            "exit_code": process.returncode

        }

    except Exception as e:

        return {"success": False, "error": public_error_message()}





# ═══════════════════════════════════════════════════════════════

# API ROUTES - AGENTS & EXPERTS (aus DB)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/bach-agents")

async def get_bach_agents():

    """Laedt Agenten und Experten aus der Datenbank."""

    conn = get_bach_db()



    agents = []

    experts = []



    # Agenten laden

    try:

        rows = conn.execute("""

            SELECT id, name, display_name, type, description, skill_path, is_active, version

            FROM bach_agents ORDER BY priority DESC

        """).fetchall()

        for row in rows:

            dashboard = None

            # Dashboard-URL basierend auf name

            name = row[1]

            if 'persoenlich' in name:

                dashboard = '/agents/persoenlich'

            elif 'gesundheit' in name:

                dashboard = '/agents/gesundheit'

            elif 'buero' in name:

                dashboard = '/agents/buero'



            agents.append({

                "id": row[0],

                "name": row[1],

                "display_name": row[2],

                "type": row[3],

                "description": row[4] or f"{row[2]} Agent",

                "skill_path": row[5],

                "is_active": bool(row[6]),

                "version": row[7] or "1.0.0",

                "dashboard": dashboard

            })

    except Exception as e:

        print(f"Error loading agents: {e}")



    # Experten laden

    try:

        rows = conn.execute("""

            SELECT id, name, display_name, agent_id, description, skill_path, domain, is_active

            FROM bach_experts ORDER BY agent_id, name

        """).fetchall()

        for row in rows:

            dashboard = None

            name = row[1]

            if 'steuer' in name:

                dashboard = '/agents/steuer'

            elif 'foerder' in name:

                dashboard = '/agents/foerderplaner'

            elif 'gesundheit' in name:

                dashboard = '/agents/gesundheit'

            elif 'psycho' in name:

                dashboard = '/agents/psycho'

            elif 'haushalt' in name:

                dashboard = '/agents/haushalt'



            experts.append({

                "id": row[0],

                "name": row[1],

                "display_name": row[2],

                "agent_id": row[3],

                "description": row[4] or f"{row[2]} Experte",

                "skill_path": row[5],

                "domain": row[6],

                "is_active": bool(row[7]),

                "dashboard": dashboard

            })

    except Exception as e:

        print(f"Error loading experts: {e}")



    conn.close()

    return {

        "agents": agents,

        "experts": experts,

        "count_agents": len(agents),

        "count_experts": len(experts)

    }





# ═══════════════════════════════════════════════════════════════

def resolve_skill_file(
    item_type: str,
    item_id: str,
    description: str = "",
    path_hint: str = "",
) -> Optional[Path]:

    """Sucht die zugehoerige .md/.txt/.py Datei fuer ein Skills-Board Item."""

    direct = resolve_path_hint(path_hint)
    if direct:
        return direct

    # 1. Hint-basierte Aufloesung (aus der Beschreibung)
    if description:
        if "Dateibasierter Workflow:" in description:
            filename = description.split("Dateibasierter Workflow:")[1].strip()
            for base in (SKILLS_DIR / "workflows", SKILLS_DIR / "_workflows"):
                target = base / filename
                if target.exists():
                    return target

        if "DB-basiert:" in description:
            hint = description.split("DB-basiert:")[1].strip().replace("\\", "/")
            hinted = resolve_path_hint(hint)
            if hinted:
                return hinted

            parts = [part for part in hint.split("/") if part]
            if parts:
                root_map = {
                    "agent": AGENTS_DIR,
                    "expert": EXPERTS_DIR,
                    "service": BACH_DIR / "hub" / "_services",
                    "workflow": SKILLS_DIR / "workflows",
                    "skill": SKILLS_DIR,
                    "template": SKILLS_DIR / "_templates",
                }
                base = root_map.get(parts[0])
                if base:
                    candidate = base
                    for part in parts[1:]:
                        candidate /= part
                    hinted = resolve_path_hint(str(candidate))
                    if hinted:
                        return hinted

    # 2. Logik-basierter Fallback basierend auf Type/ID
    clean_id = item_id
    prefixes = ("workflow-", "service-", "expert-", "agent-", "skill-", "template-")
    for prefix in prefixes:
        if clean_id.startswith(prefix):
            clean_id = clean_id[len(prefix):]
            break

    base_dirs = {
        "agent": [AGENTS_DIR],
        "expert": [EXPERTS_DIR],
        "service": [BACH_DIR / "hub" / "_services"],
        "workflow": [SKILLS_DIR / "workflows", SKILLS_DIR / "_workflows"],
        "skill": [SKILLS_DIR],
    }

    for base in base_dirs.get(item_type, []):
        if not base.exists():
            continue

        for ext in TEXT_FILE_SUFFIXES:
            candidate = base / f"{clean_id}{ext}"
            if candidate.exists():
                return candidate

        picked = pick_directory_file(base / clean_id, clean_id)
        if picked:
            return picked

        for root, dirs, files in os.walk(str(base)):
            root_path = Path(root)
            if root_path.name.lower() == clean_id.lower():
                picked = pick_directory_file(root_path, clean_id)
                if picked:
                    return picked

            for filename in files:
                file_path = root_path / filename
                if file_path.suffix.lower() not in TEXT_FILE_SUFFIXES:
                    continue
                if file_path.stem.lower() == clean_id.lower():
                    return file_path

    return None



# API ROUTES - SKILLS BOARD

# ═══════════════════════════════════════════════════════════════



SKILLS_HIERARCHY_FILE = DATA_DIR / "skills_hierarchy.json"



@app.get("/api/skills-board/item-file")

async def get_skills_item_file(
    type: str,
    id: str,
    description: Optional[str] = "",
    path_hint: Optional[str] = "",
):

    """Sucht und liefert den Inhalt der Quelldatei eines Items."""

    path = resolve_skill_file(type, id, description, path_hint or "")

    if not path:

        return {"success": False, "error": "Keine Quelldatei (.md/.txt) fuer dieses Element gefunden."}

    

    try:

        content = path.read_text(encoding='utf-8')

        return {

            "success": True,

            "path": str(path.relative_to(BACH_DIR)).replace("\\", "/"),

            "absolute_path": str(path),

            "content": content,

            "filename": path.name

        }

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.put("/api/skills-board/item-file")

async def update_skills_item_file(request: FileUpdateRequest):

    """Speichert den Inhalt der Quelldatei."""

    path = resolve_under_base(BACH_DIR, request.path, allowed_suffixes={".md", ".txt", ".py"})

        

    # Nur .md, .txt, .py erlauben

    if path.suffix.lower() not in ['.md', '.txt', '.py']:

        raise HTTPException(status_code=400, detail="Dateityp nicht erlaubt.")

        

    try:

        path.write_text(request.content, encoding='utf-8')

        return {"success": True}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.get("/api/skills-board/hierarchy")

async def get_skills_hierarchy():

    """Laedt die Skills-Hierarchie."""

    import json

    if SKILLS_HIERARCHY_FILE.exists():
        try:
            with open(SKILLS_HIERARCHY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if hierarchy_has_items(data):
                return data
        except Exception as e:
            print(f"[BACH GUI] skills_hierarchy.json konnte nicht geladen werden: {e}")

    data = load_skills_board_from_db()
    if hierarchy_has_items(data):
        try:
            SKILLS_HIERARCHY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SKILLS_HIERARCHY_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[BACH GUI] skills_hierarchy.json konnte nicht geschrieben werden: {e}")

    return data



@app.put("/api/skills-board/hierarchy")

async def save_skills_hierarchy(request: Request):

    """Speichert die Skills-Hierarchie."""

    import json

    from datetime import datetime



    data = await request.json()



    # Update timestamp

    if '_meta' not in data:

        data['_meta'] = {}

    data['_meta']['last_updated'] = datetime.now().isoformat()



    with open(SKILLS_HIERARCHY_FILE, 'w', encoding='utf-8') as f:

        json.dump(data, f, indent=4, ensure_ascii=False)



    return {"status": "saved"}



# ═══════════════════════════════════════════════════════════════

# API ROUTES - HELP

# ═══════════════════════════════════════════════════════════════



@app.get("/api/help")

async def list_help_files():

    """Listet alle Help-Dateien inkl. Wiki-Unterordner (rekursiv)."""

    if not HELP_DIR.exists():

        return {"files": [], "count": 0, "total_size": 0, "wiki_folders": []}



    files = []

    total_size = 0

    wiki_folders = []



    # Help-Dateien rekursiv (inkl. tools/ Unterordner)

    for help_file in sorted(HELP_DIR.rglob("*.txt")):

        if help_file.name.startswith('_'):
            continue

        size = help_file.stat().st_size

        total_size += size

        rel = help_file.relative_to(HELP_DIR)
        name_key = str(rel).replace('\\', '/').replace('.txt', '')

        files.append({

            "name": name_key,

            "filename": help_file.name,

            "size": size,

            "type": "help",

            "folder": rel.parts[0] if len(rel.parts) > 1 else None

        })



    # Wiki-Ordner (separates Verzeichnis)

    wiki_dir = WIKI_DIR

    if wiki_dir.exists():

        # Alle .txt Dateien rekursiv finden

        for wiki_file in sorted(wiki_dir.rglob("*.txt")):

            if wiki_file.name.startswith('_'):

                continue  # _index.txt etc. ueberspringen



            size = wiki_file.stat().st_size

            total_size += size



            # Relativen Pfad zum wiki-Ordner berechnen

            rel_path = wiki_file.relative_to(wiki_dir)

            rel_path_str = str(rel_path).replace('\\', '/')

            name_without_ext = rel_path_str[:-4] if rel_path_str.endswith('.txt') else rel_path_str



            # Ordner-Ebene bestimmen

            parts = rel_path.parts

            if len(parts) == 1:

                # Direkt in wiki/

                file_type = "wiki"

                folder = None

            else:

                # In Unterordner

                file_type = "wiki_sub"

                folder = parts[0]  # Erster Ordner



            files.append({

                "name": f"wiki/{name_without_ext}",

                "filename": wiki_file.name,

                "size": size,

                "type": file_type,

                "folder": folder,

                "depth": len(parts) - 1  # Verschachtelungstiefe

            })



        # Ordner-Info sammeln (nur erste Ebene)

        for subfolder in sorted(wiki_dir.iterdir()):

            if subfolder.is_dir() and not subfolder.name.startswith('_'):

                # Rekursiv alle Dateien in diesem Ordner zaehlen

                folder_files = list(subfolder.rglob("*.txt"))

                folder_size = sum(f.stat().st_size for f in folder_files)



                wiki_folders.append({

                    "name": subfolder.name,

                    "path": f"wiki/{subfolder.name}",

                    "file_count": len(folder_files),

                    "total_size": folder_size

                })



    return {

        "files": files,

        "count": len(files),

        "total_size": total_size,

        "wiki_folders": wiki_folders

    }



@app.get("/api/help/{name:path}")
@app.get("/api/docs/help/{name:path}")

async def get_help_file(name: str):

    """Liefert Inhalt einer Help-Datei (unterstuetzt auch wiki/ordner/datei)."""

    requested = name.replace("\\", "/").strip()
    if not requested.endswith(".txt"):
        requested = f"{requested}.txt"

    candidates = [(HELP_DIR, requested)]
    if requested.startswith("wiki/"):
        candidates.insert(0, (WIKI_DIR, requested[5:]))

    help_file = None
    base_dir = HELP_DIR
    for candidate_base, candidate_name in candidates:
        candidate = resolve_under_base(candidate_base, candidate_name, allowed_suffixes={".txt"})
        if candidate.exists() and candidate.is_file():
            help_file = candidate
            base_dir = candidate_base
            break

    if help_file is None:

        raise HTTPException(status_code=404, detail="Help-Datei nicht gefunden")



    try:

        content = help_file.read_text(encoding='utf-8', errors='ignore')

        if base_dir == WIKI_DIR:
            rel_path = "wiki/" + str(help_file.relative_to(WIKI_DIR))
            file_type = 'wiki_sub' if '/' in str(help_file.relative_to(WIKI_DIR)) else 'wiki'
        else:
            rel_path = str(help_file.relative_to(HELP_DIR))
            file_type = 'help'



        return {

            "name": help_file.stem,

            "filename": help_file.name,

            "path": rel_path,

            "size": help_file.stat().st_size,

            "content": content,

            "type": file_type

        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())





class HelpUpdate(BaseModel):

    content: str





@app.put("/api/help/{name:path}")
@app.put("/api/docs/help/{name:path}")

async def update_help_file(name: str, data: HelpUpdate):

    """Aktualisiert eine Help-Datei (nur im Entwicklermodus)."""

    requested = name.replace("\\", "/").strip()
    if not requested.endswith(".txt"):
        requested = f"{requested}.txt"

    help_file = resolve_under_base(HELP_DIR, requested, allowed_suffixes={".txt"})



    # Elternverzeichnis erstellen falls noetig

    help_file.parent.mkdir(parents=True, exist_ok=True)



    try:

        # Backup erstellen

        if help_file.exists():

            backup_file = resolve_under_base(HELP_DIR, f"{help_file.relative_to(HELP_DIR)}.bak")

            backup_file.write_text(help_file.read_text(encoding='utf-8'), encoding='utf-8')



        # Speichern

        help_file.write_text(data.content, encoding='utf-8')



        return {

            "success": True,

            "name": name.replace('.txt', ''),

            "size": help_file.stat().st_size

        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())





@app.post("/api/help")

async def create_help_file(name: str = Query(...), data: HelpUpdate = None):

    """Erstellt eine neue Help-Datei."""

    if not name:

        raise HTTPException(status_code=400, detail="Name erforderlich")



    # Sanitize name

    name = safe_path_segment(name.strip().replace(' ', '_').lower(), field_name="Dateiname")

    if not name.endswith('.txt'):

        name = name + '.txt'



    help_file = resolve_under_base(HELP_DIR, name, allowed_suffixes={".txt"})



    if help_file.exists():

        raise HTTPException(status_code=409, detail="Datei existiert bereits")



    try:

        content = data.content if data else f"# {name.replace('.txt', '').upper()}\n\nNeue Dokumentation.\n"

        help_file.write_text(content, encoding='utf-8')



        return {

            "success": True,

            "name": name.replace('.txt', ''),

            "size": help_file.stat().st_size

        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())





@app.delete("/api/help/{name:path}")
@app.delete("/api/docs/help/{name:path}")

async def delete_help_file(name: str):

    """Loescht eine Help-Datei (verschiebt sie nach .deleted)."""

    requested = name.replace("\\", "/").strip()
    if not requested.endswith(".txt"):
        requested = f"{requested}.txt"

    help_file = resolve_under_base(HELP_DIR, requested, allowed_suffixes={".txt"}, must_exist=True)



    if not help_file.exists():

        raise HTTPException(status_code=404, detail="Datei nicht gefunden")



    try:

        # Nicht wirklich loeschen, nur umbenennen

        deleted_file = resolve_under_base(HELP_DIR, f"{help_file.relative_to(HELP_DIR)}.deleted")

        help_file.rename(deleted_file)



        return {"success": True, "name": name.replace('.txt', '')}

    except Exception as e:
        raise HTTPException(status_code=500, detail=public_error_message())





@app.get("/api/docs/help/search/{term}")

async def search_help(term: str):

    """Durchsucht Help-Dateien nach Begriff."""

    if not HELP_DIR.exists():

        return {"results": [], "count": 0}

    

    results = []

    term_lower = term.lower()

    

    for help_file in HELP_DIR.glob("*.txt"):

        try:

            content = help_file.read_text(encoding='utf-8', errors='ignore')

            if term_lower in content.lower():

                # Kontext extrahieren

                lines = content.split('\n')

                matches = []

                for i, line in enumerate(lines):

                    if term_lower in line.lower():

                        matches.append({

                            "line": i + 1,

                            "text": line.strip()[:100]

                        })

                        if len(matches) >= 3:

                            break

                

                results.append({

                    "name": help_file.stem,

                    "matches": matches,

                    "match_count": content.lower().count(term_lower)

                })

        except (OSError, UnicodeDecodeError):

            pass

    

    # Nach Anzahl Treffer sortieren

    results.sort(key=lambda x: x['match_count'], reverse=True)

    

    return {

        "term": term,

        "results": results,

        "count": len(results)

    }



# ═══════════════════════════════════════════════════════════════

# FINANCIAL MAIL API

# ═══════════════════════════════════════════════════════════════



FINANCIAL_DATA_FILE = DATA_DIR / "financial_data.json"

FINANCIAL_SCHEMA_FILE = BACH_DIR / "hub" / "_services" / "mail" / "schema_financial.sql"



def init_financial_tables():

    """Initialisiert Financial-Tabellen falls nicht vorhanden."""

    conn = get_user_db()

    cursor = conn.cursor()



    # Pruefe ob Tabellen existieren

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mail_accounts'")

    if not cursor.fetchone():

        # Schema laden und ausfuehren

        if FINANCIAL_SCHEMA_FILE.exists():

            schema = FINANCIAL_SCHEMA_FILE.read_text(encoding='utf-8')

            # SQLite executescript verarbeitet mehrere Statements

            conn.executescript(schema)

            conn.commit()

            print("[BACH] Financial-Tabellen initialisiert")



    conn.close()



def save_financial_data_json():

    """Speichert Financial-Daten als JSON unter data/financial_data.json"""

    conn = get_user_db()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()



    try:

        # Backup erstellen falls Datei existiert

        if FINANCIAL_DATA_FILE.exists():

            backup_dir = DATA_DIR / "backups"

            backup_dir.mkdir(exist_ok=True)

            backup_name = f"financial_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            backup_path = backup_dir / backup_name



            # Alte Backups aufraeumen (nur letzte 10 behalten)

            backups = sorted(backup_dir.glob("financial_data_*.json"))

            if len(backups) > 10:

                for old_backup in backups[:-10]:

                    old_backup.unlink()



            # Aktuelles Backup erstellen

            import shutil

            shutil.copy(FINANCIAL_DATA_FILE, backup_path)



        # Daten sammeln

        cursor.execute("SELECT * FROM financial_emails ORDER BY email_date DESC")

        emails = [dict(row) for row in cursor.fetchall()]



        cursor.execute("SELECT * FROM financial_subscriptions")

        subscriptions = [dict(row) for row in cursor.fetchall()]



        cursor.execute("SELECT * FROM mail_accounts")

        accounts = [dict(row) for row in cursor.fetchall()]

        # Passwort-Felder entfernen

        for acc in accounts:

            acc.pop('password', None)



        # Summary berechnen

        cursor.execute("""

            SELECT

                COUNT(*) as total_emails,

                SUM(CASE WHEN steuer_relevant = 1 THEN 1 ELSE 0 END) as steuer_count,

                SUM(COALESCE(betrag, 0)) as total_betrag

            FROM financial_emails WHERE status != 'ignoriert'

        """)

        summary_row = cursor.fetchone()

        summary = dict(summary_row) if summary_row else {}



        conn.close()



        # JSON-Daten

        data = {

            "_meta": {

                "version": "1.0",

                "description": "BACH Financial Mail Data Export",

                "exported_at": datetime.now().isoformat(),

                "source": "BACH v1.1.7"

            },

            "summary": summary,

            "accounts": accounts,

            "emails": emails,

            "subscriptions": subscriptions

        }



        # Speichern

        FINANCIAL_DATA_FILE.write_text(

            json.dumps(data, ensure_ascii=False, indent=2, default=str),

            encoding='utf-8'

        )



        return True



    except Exception as e:

        conn.close()

        print(f"[BACH] Fehler beim Speichern von financial_data.json: {e}")

        return False



@app.get("/financial", response_class=HTMLResponse)

async def financial_page():

    """Financial Mail Dashboard."""

    # Tabellen werden beim Serverstart angelegt (lifespan), nie durch anonyme GETs.

    template = TEMPLATES_DIR / "financial.html"

    if template.exists():

        return template.read_text(encoding='utf-8')

    raise HTTPException(status_code=404, detail="Template financial.html nicht gefunden")



@app.get("/api/financial/status")

async def financial_status():

    """Status der Financial Mail Service."""

    conn = get_user_db()

    cursor = conn.cursor()



    try:

        # Konten

        cursor.execute("SELECT COUNT(*) FROM mail_accounts WHERE is_active = 1")

        accounts = cursor.fetchone()[0]



        # E-Mails

        cursor.execute("SELECT COUNT(*) FROM financial_emails")

        total_emails = cursor.fetchone()[0]



        cursor.execute("SELECT COUNT(*) FROM financial_emails WHERE status = 'neu'")

        new_emails = cursor.fetchone()[0]



        cursor.execute("SELECT COUNT(*) FROM financial_emails WHERE steuer_relevant = 1")

        steuer_emails = cursor.fetchone()[0]



        # Abos

        cursor.execute("""
            SELECT COUNT(*) FROM financial_subscriptions
            WHERE aktiv = 1
              AND id IN (
                  SELECT MIN(id) FROM financial_subscriptions GROUP BY provider_id
              )
        """)

        active_subs = cursor.fetchone()[0]



        # Letzter Sync

        cursor.execute("""

            SELECT finished_at, status, emails_matched

            FROM mail_sync_runs

            ORDER BY finished_at DESC LIMIT 1

        """)

        last_sync = row_to_dict(cursor.fetchone())



        # Monatliche Kosten

        cursor.execute("""

            SELECT SUM(COALESCE(betrag_monatlich, betrag_jaehrlich / 12.0, 0))
            FROM financial_subscriptions
            WHERE aktiv = 1
              AND id IN (
                  SELECT MIN(id) FROM financial_subscriptions GROUP BY provider_id
              )

        """)

        monthly_cost = cursor.fetchone()[0] or 0



        conn.close()



        return {

            "accounts": accounts,

            "total_emails": total_emails,

            "new_emails": new_emails,

            "steuer_relevant": steuer_emails,

            "active_subscriptions": active_subs,

            "monthly_subscription_cost": monthly_cost,

            "last_sync": last_sync

        }

    except Exception as e:

        conn.close()

        return {"error": public_error_message(), "accounts": 0, "total_emails": 0}



@app.get("/api/financial/emails")

async def financial_emails(

    status: Optional[str] = None,

    category: Optional[str] = None,

    steuer_only: bool = False,

    limit: int = 50

):

    """Liste der Financial E-Mails."""

    conn = get_user_db()

    cursor = conn.cursor()



    try:

        query = "SELECT * FROM financial_emails WHERE 1=1"

        params = []



        if status:

            query += " AND status = ?"

            params.append(status)



        if category:

            query += " AND category = ?"

            params.append(category)



        if steuer_only:

            query += " AND steuer_relevant = 1"



        query += " ORDER BY email_date DESC LIMIT ?"

        params.append(limit)



        cursor.execute(query, params)

        emails = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()



        return {"emails": emails, "count": len(emails)}

    except Exception as e:

        conn.close()

        return {"emails": [], "count": 0, "error": public_error_message()}



@app.get("/api/financial/emails/{email_id}")

async def get_financial_email(email_id: int):

    """Holt eine einzelne Financial E-Mail mit Body."""

    conn = get_user_db()

    cursor = conn.cursor()

    try:

        row = conn.execute("SELECT * FROM financial_emails WHERE id = ?", (email_id,)).fetchone()

        conn.close()

        if not row:

            raise HTTPException(status_code=404, detail="E-Mail nicht gefunden")

        return {"email": row_to_dict(row)}

    except Exception as e:

        conn.close()

        raise HTTPException(status_code=500, detail=public_error_message())



@app.get("/api/financial/subscriptions")

async def financial_subscriptions(active_only: bool = True):

    """Liste der erkannten Abonnements."""

    conn = get_user_db()

    cursor = conn.cursor()



    try:

        query = """
            SELECT * FROM financial_subscriptions
            WHERE id IN (
                SELECT MIN(id) FROM financial_subscriptions GROUP BY provider_id
            )
        """

        if active_only:
            query += " AND aktiv = 1"

        query += " ORDER BY betrag_monatlich DESC"



        cursor.execute(query)

        subs = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()



        return {"subscriptions": subs, "count": len(subs)}

    except Exception as e:

        conn.close()

        return {"subscriptions": [], "count": 0, "error": public_error_message()}


@app.get("/api/financial/subscriptions-unified")
async def financial_subscriptions_unified():
    """v1.1.84: Unified subscriptions aus v_subscriptions View mit Duplikat-Info."""
    try:
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Nutzt die v_subscriptions View (definiert in schema_user_data.sql)
        cursor.execute("""
            SELECT
                name, provider, category, monthly_cost, status, source_table,
                COUNT(*) as duplicates,
                GROUP_CONCAT(id) as duplicate_ids
            FROM v_subscriptions
            WHERE status = 'active'
            GROUP BY LOWER(name), LOWER(COALESCE(provider, ''))
            ORDER BY monthly_cost DESC
        """)

        rows = cursor.fetchall()
        subscriptions = []
        total_monthly = 0
        duplicate_count = 0

        for row in rows:
            sub = dict(row)
            total_monthly += sub['monthly_cost'] or 0
            if sub['duplicates'] > 1:
                duplicate_count += 1
            subscriptions.append(sub)

        conn.close()

        return {
            "success": True,
            "subscriptions": subscriptions,
            "count": len(subscriptions),
            "total_monthly": total_monthly,
            "duplicate_count": duplicate_count
        }
    except Exception as e:
        return {"success": False, "subscriptions": [], "error": public_error_message()}


@app.delete("/api/financial/subscriptions/{sub_id}")

async def delete_financial_subscription(sub_id: int):

    """Loescht ein Abonnement."""

    conn = get_user_db()

    try:

        conn.execute("DELETE FROM financial_subscriptions WHERE id = ?", (sub_id,))

        conn.commit()

        conn.close()

        return {"success": True, "id": sub_id}

    except Exception as e:

        conn.close()

        raise HTTPException(status_code=500, detail=public_error_message())



@app.get("/api/financial/categories")

async def financial_categories():

    """Uebersicht nach Kategorien."""

    conn = get_user_db()

    cursor = conn.cursor()



    try:

        cursor.execute("""

            SELECT

                category,

                COUNT(*) as count,

                SUM(COALESCE(betrag, 0)) as total,

                SUM(CASE WHEN steuer_relevant = 1 THEN COALESCE(betrag, 0) ELSE 0 END) as steuer_total

            FROM financial_emails

            GROUP BY category

            ORDER BY total DESC

        """)



        categories = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()



        return {"categories": categories}

    except Exception as e:

        conn.close()

        return {"categories": [], "error": public_error_message()}



@app.post("/api/financial/sync")

async def financial_sync(background_tasks: BackgroundTasks):

    """Startet E-Mail-Synchronisierung."""

    import subprocess



    # Tabellen initialisieren

    init_financial_tables()



    mail_service = BACH_DIR / "hub" / "_services" / "mail" / "mail_service.py"

    if not mail_service.exists():

        raise HTTPException(status_code=404, detail="Mail-Service nicht gefunden")



    def run_sync():

        # Sync durchfuehren

        result = subprocess.run(

            [sys.executable, str(mail_service), "sync"],

            cwd=str(BACH_DIR),

            capture_output=True,

            text=True,

            encoding='utf-8', errors='replace'

        )

        print(f"[BACH Sync] {result.stdout}")

        if result.stderr:

            print(f"[BACH Sync Error] {result.stderr}")



        # Nach Sync: JSON speichern

        save_financial_data_json()



    background_tasks.add_task(run_sync)

    return {"status": "started", "message": "Synchronisierung gestartet"}



@app.post("/api/financial/save-json")

async def save_financial_json():

    """Speichert aktuelle Financial-Daten als JSON."""

    success = save_financial_data_json()

    if success:

        return {"status": "success", "path": str(FINANCIAL_DATA_FILE)}

    raise HTTPException(status_code=500, detail="Fehler beim Speichern")



# ─── Config-Endpunkte ───

MAIL_CONFIG_FILE = BACH_DIR / "hub" / "_services" / "mail" / "config.json"



def get_mail_config():

    """Liest die Mail-Service Konfiguration."""

    if MAIL_CONFIG_FILE.exists():

        return json.loads(MAIL_CONFIG_FILE.read_text(encoding='utf-8'))

    return {}



def save_mail_config(config: dict):

    """Speichert die Mail-Service Konfiguration."""

    MAIL_CONFIG_FILE.write_text(

        json.dumps(config, ensure_ascii=False, indent=4),

        encoding='utf-8'

    )



@app.get("/api/financial/config")

async def financial_config():

    """Liefert die Mail-Service Konfiguration."""

    config = get_mail_config()

    return {

        "date_range_days": config.get("date_range_days", 90),

        "max_emails_per_run": config.get("max_emails_per_run", 50),

        "auto_extract": config.get("auto_extract", True),

        "quiet_start": config.get("quiet_start", "23:00"),

        "quiet_end": config.get("quiet_end", "07:00")

    }



@app.put("/api/financial/config")

async def update_financial_config(

    date_range_days: Optional[int] = None,

    max_emails_per_run: Optional[int] = None,

    auto_extract: Optional[bool] = None

):

    """Aktualisiert die Mail-Service Konfiguration."""

    config = get_mail_config()



    if date_range_days is not None:

        # Validierung: 7 bis 365 Tage erlaubt

        if date_range_days < 7:

            raise HTTPException(status_code=400, detail="Mindestens 7 Tage erforderlich")

        if date_range_days > 365:

            raise HTTPException(status_code=400, detail="Maximal 365 Tage erlaubt")

        config["date_range_days"] = date_range_days



    if max_emails_per_run is not None:

        if max_emails_per_run < 10 or max_emails_per_run > 500:

            raise HTTPException(status_code=400, detail="max_emails_per_run muss zwischen 10 und 500 liegen")

        config["max_emails_per_run"] = max_emails_per_run



    if auto_extract is not None:

        config["auto_extract"] = auto_extract



    save_mail_config(config)

    return {"success": True, "config": config}



@app.put("/api/financial/emails/{email_id}/status")

async def update_email_status(email_id: int, status: str):

    """Aktualisiert E-Mail-Status."""

    valid_status = ['neu', 'verarbeitet', 'exportiert', 'ignoriert']

    if status not in valid_status:

        raise HTTPException(status_code=400, detail=f"Status muss einer von {valid_status} sein")



    conn = get_user_db()

    cursor = conn.cursor()

    cursor.execute("UPDATE financial_emails SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",

                   (status, email_id))

    conn.commit()

    conn.close()



    return {"success": True, "id": email_id, "status": status}



@app.get("/api/financial/export")

async def financial_export():

    """Exportiert Finanzdaten als JSON."""

    conn = get_user_db()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()



    try:

        # E-Mails

        cursor.execute("SELECT * FROM financial_emails WHERE status != 'ignoriert' ORDER BY email_date DESC")

        emails = [dict(row) for row in cursor.fetchall()]



        # Abos

        cursor.execute("SELECT * FROM financial_subscriptions WHERE aktiv = 1")

        subs = [dict(row) for row in cursor.fetchall()]



        # Summary

        cursor.execute("""

            SELECT

                COUNT(*) as total,

                SUM(CASE WHEN steuer_relevant = 1 THEN 1 ELSE 0 END) as steuer_count,

                SUM(COALESCE(betrag, 0)) as total_betrag

            FROM financial_emails WHERE status != 'ignoriert'

        """)

        summary = dict(cursor.fetchone())



        conn.close()



        return {

            "_info": "BACH Financial Mail Export",

            "_exported": datetime.now().isoformat(),

            "summary": summary,

            "emails": emails,

            "subscriptions": subs

        }

    except Exception as e:

        conn.close()

        return {

            "_info": "BACH Financial Mail Export",

            "_exported": datetime.now().isoformat(),

            "error": public_error_message(),

            "summary": {"total": 0, "steuer_count": 0, "total_betrag": 0},

            "emails": [],

            "subscriptions": []

        }



@app.get("/api/financial/accounts")

async def financial_accounts():

    """Liste der E-Mail-Konten."""

    conn = get_user_db()

    cursor = conn.cursor()



    try:

        cursor.execute("SELECT id, name, email, provider, imap_host, imap_port, use_oauth, is_active, last_sync FROM mail_accounts")

        accounts = [row_to_dict(row) for row in cursor.fetchall()]

    except (sqlite3.OperationalError, sqlite3.DatabaseError):

        accounts = []



    conn.close()

    return {"accounts": accounts}



class MailAccountCreate(BaseModel):

    name: str

    email: str

    password: Optional[str] = None

    provider: str = "imap"

    imap_host: Optional[str] = None

    imap_port: int = 993

    use_oauth: bool = False



@app.post("/api/financial/accounts")

async def create_mail_account(account: MailAccountCreate):

    """Erstellt neues E-Mail-Konto."""

    conn = get_user_db()

    cursor = conn.cursor()



    # IMAP-Presets

    imap_presets = {

        "gmail.com": ("imap.gmail.com", 993),

        "googlemail.com": ("imap.gmail.com", 993),

        "outlook.com": ("outlook.office365.com", 993),

        "hotmail.com": ("outlook.office365.com", 993),

        "gmx.de": ("imap.gmx.net", 993),

        "gmx.net": ("imap.gmx.net", 993),

        "web.de": ("imap.web.de", 993),

        "t-online.de": ("secureimap.t-online.de", 993),

        "yahoo.com": ("imap.mail.yahoo.com", 993),

        "icloud.com": ("imap.mail.me.com", 993),

    }



    # Host automatisch ermitteln

    domain = account.email.split('@')[-1].lower()

    if not account.imap_host and domain in imap_presets:

        account.imap_host, account.imap_port = imap_presets[domain]



    try:

        cursor.execute("""

            INSERT INTO mail_accounts (name, email, provider, imap_host, imap_port, use_oauth, is_active)

            VALUES (?, ?, ?, ?, ?, ?, 1)

        """, (

            account.name,

            account.email,

            account.provider,

            account.imap_host,

            account.imap_port,

            1 if account.use_oauth else 0

        ))

        account_id = cursor.lastrowid

        conn.commit()



        # Passwort speichern wenn vorhanden

        if account.password:

            try:

                import keyring

                keyring.set_password("bach_financial_mail", account.email, account.password)

            except Exception:

                pass



        conn.close()

        return {"success": True, "id": account_id, "email": account.email}



    except sqlite3.IntegrityError:

        conn.close()

        raise HTTPException(status_code=400, detail="E-Mail-Adresse bereits registriert")

    except Exception as e:

        conn.close()

        raise HTTPException(status_code=500, detail=public_error_message())



@app.delete("/api/financial/accounts/{account_id}")

async def delete_mail_account(account_id: int):

    """Loescht E-Mail-Konto."""

    conn = get_user_db()

    cursor = conn.cursor()



    # E-Mail fuer Keyring holen

    cursor.execute("SELECT email FROM mail_accounts WHERE id = ?", (account_id,))

    row = cursor.fetchone()



    if not row:

        conn.close()

        raise HTTPException(status_code=404, detail="Konto nicht gefunden")



    email = row[0]



    # Konto loeschen

    cursor.execute("DELETE FROM mail_accounts WHERE id = ?", (account_id,))

    conn.commit()

    conn.close()



    # Passwort aus Keyring loeschen

    try:

        import keyring

        keyring.delete_password("bach_financial_mail", email)

    except Exception:

        pass



    return {"success": True, "id": account_id}



@app.put("/api/financial/accounts/{account_id}/toggle")

async def toggle_mail_account(account_id: int):

    """Aktiviert/Deaktiviert E-Mail-Konto."""

    conn = get_user_db()

    try:

        cursor = conn.cursor()

        cursor.execute("""

            UPDATE mail_accounts

            SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END,

                updated_at = CURRENT_TIMESTAMP

            WHERE id = ?

        """, (account_id,))

        if cursor.rowcount == 0:

            raise HTTPException(status_code=404, detail="Konto nicht gefunden")

        cursor.execute("SELECT is_active FROM mail_accounts WHERE id = ?", (account_id,))

        row = cursor.fetchone()

        is_active = row[0] if row else 0

        conn.commit()

    except HTTPException:

        raise

    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:

        return JSONResponse(status_code=500, content={"success": False, "error": public_error_message()})

    finally:

        conn.close()

    return {"success": True, "id": account_id, "is_active": bool(is_active)}



@app.post("/api/financial/accounts/{account_id}/test")

async def test_mail_account(account_id: int):

    """Testet Verbindung zum E-Mail-Konto."""

    conn = get_user_db()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()



    cursor.execute("SELECT * FROM mail_accounts WHERE id = ?", (account_id,))

    row = cursor.fetchone()

    conn.close()



    if not row:

        raise HTTPException(status_code=404, detail="Konto nicht gefunden")



    account = dict(row)



    # Gmail API Test

    if account['provider'] == 'gmail_api':

        try:

            # Account Manager importieren

            import sys

            mail_service_path = BACH_DIR / "hub" / "_services" / "mail"

            sys.path.insert(0, str(mail_service_path))

            from account_manager import AccountManager



            mgr = AccountManager()

            service = mgr.get_gmail_service()



            if service:

                profile = service.users().getProfile(userId='me').execute()

                return {"success": True, "message": f"Gmail API verbunden: {profile.get('emailAddress')}"}

            else:

                return {"success": False, "message": "Gmail API nicht eingerichtet"}

        except Exception as e:

            return {"success": False, "message": public_error_message()}



    # IMAP Test

    try:

        import keyring

        password = keyring.get_password("bach_financial_mail", account['email'])

    except Exception:

        password = None



    if not password:

        return {"success": False, "message": "Kein Passwort gespeichert"}



    try:

        import imaplib

        mail = imaplib.IMAP4_SSL(account['imap_host'], account['imap_port'])

        mail.login(account['email'], password)

        mail.logout()

        return {"success": True, "message": "IMAP-Verbindung erfolgreich"}

    except Exception as e:

        return {"success": False, "message": public_error_message()}



@app.get("/api/financial/imap-presets")

async def get_imap_presets():

    """Gibt IMAP-Presets fuer bekannte Provider zurueck."""

    return {

        "presets": {

            "gmail.com": {"name": "Gmail", "host": "imap.gmail.com", "port": 993, "note": "App-Passwort erforderlich"},

            "outlook.com": {"name": "Outlook", "host": "outlook.office365.com", "port": 993},

            "hotmail.com": {"name": "Hotmail", "host": "outlook.office365.com", "port": 993},

            "gmx.de": {"name": "GMX", "host": "imap.gmx.net", "port": 993, "note": "IMAP aktivieren"},

            "web.de": {"name": "Web.de", "host": "imap.web.de", "port": 993},

            "t-online.de": {"name": "T-Online", "host": "secureimap.t-online.de", "port": 993},

            "yahoo.com": {"name": "Yahoo", "host": "imap.mail.yahoo.com", "port": 993},

            "icloud.com": {"name": "iCloud", "host": "imap.mail.me.com", "port": 993}

        }

    }



@app.get("/api/financial/gmail/find-credentials")

async def find_gmail_credentials():

    """Sucht nach vorhandenen Gmail credentials.json Dateien."""

    try:

        mail_service_path = BACH_DIR / "hub" / "_services" / "mail"

        sys.path.insert(0, str(mail_service_path))

        from account_manager import AccountManager



        mgr = AccountManager()

        found = mgr.find_gmail_credentials()



        return {

            "found": len(found),

            "credentials": [str(p) for p in found[:10]],  # Max 10 zurueckgeben

            "has_token": mgr.has_gmail_api_setup()

        }

    except Exception as e:

        return {"found": 0, "credentials": [], "error": public_error_message()}



@app.post("/api/financial/gmail/setup")

async def setup_gmail_api():

    """

    Richtet Gmail API automatisch ein.

    Startet OAuth-Flow in einem separaten Prozess, damit der Browser sich oeffnet.

    """

    import subprocess

    import time



    try:

        mail_service_path = BACH_DIR / "hub" / "_services" / "mail"

        sys.path.insert(0, str(mail_service_path))

        from account_manager import AccountManager



        mgr = AccountManager()



        # Pruefe ob bereits eingerichtet

        if mgr.has_gmail_api_setup():

            service = mgr.get_gmail_service()

            if service:

                try:

                    profile = service.users().getProfile(userId='me').execute()

                    email = profile.get('emailAddress', '')

                    return {

                        "success": True,

                        "already_setup": True,

                        "email": email,

                        "message": f"Gmail API bereits eingerichtet: {email}"

                    }

                except Exception:

                    pass



        # Credentials suchen

        found = mgr.find_gmail_credentials()

        if not found:

            return {

                "success": False,

                "message": "Keine Gmail credentials.json gefunden. Bitte laden Sie die Datei von der Google Cloud Console herunter.",

                "help_url": "https:/console.cloud.google.com/apis/credentials"

            }



        # OAuth-Flow in separatem Prozess starten (damit Browser sich oeffnet)

        account_manager_script = mail_service_path / "account_manager.py"



        # Starte OAuth-Flow (Befehl: setup-gmail)

        result = subprocess.run(

            [sys.executable, str(account_manager_script), "setup-gmail"],

            capture_output=True,

            text=True,

            encoding='utf-8', errors='replace',

            timeout=180,  # 3 Minuten Timeout

            cwd=str(mail_service_path)

        )



        if result.returncode == 0:

            # Pruefe ob jetzt Token vorhanden

            time.sleep(1)

            mgr2 = AccountManager()  # Neu laden

            if mgr2.has_gmail_api_setup():

                service = mgr2.get_gmail_service()

                if service:

                    try:

                        profile = service.users().getProfile(userId='me').execute()

                        email = profile.get('emailAddress', '')



                        # Konto in DB speichern falls noch nicht vorhanden

                        existing = mgr2.get_account_by_email(email)

                        if not existing:

                            from account_manager import MailAccount

                            account = MailAccount(

                                name="Gmail",

                                email=email,

                                provider="gmail_api",

                                use_oauth=True

                            )

                            account_id = mgr2.add_account(account)

                        else:

                            account_id = existing.id



                        return {

                            "success": True,

                            "email": email,

                            "account_id": account_id,

                            "message": f"Gmail API erfolgreich eingerichtet: {email}"

                        }

                    except Exception as e:

                        return {"success": False, "message": public_error_message()}



            return {"success": False, "message": "OAuth-Prozess abgeschlossen aber Token nicht gefunden"}

        else:

            error_msg = result.stderr or result.stdout or "Unbekannter Fehler"

            return {"success": False, "message": f"OAuth-Fehler: {error_msg[:500]}"}



    except subprocess.TimeoutExpired:

        return {"success": False, "message": "OAuth-Timeout - Autorisierung nicht abgeschlossen (3 Minuten)"}

    except Exception as e:

        return {"success": False, "message": public_error_message()}



@app.get("/api/financial/gmail/status")

async def gmail_api_status():

    """Prueft den aktuellen Gmail API Status."""

    try:

        mail_service_path = BACH_DIR / "hub" / "_services" / "mail"

        sys.path.insert(0, str(mail_service_path))

        from account_manager import AccountManager



        mgr = AccountManager()



        result = {

            "has_credentials": False,

            "has_token": mgr.has_gmail_api_setup(),

            "is_valid": False,

            "email": None,

            "found_credentials": []

        }



        # Credentials suchen

        found = mgr.find_gmail_credentials()

        result["found_credentials"] = [str(p) for p in found[:5]]

        result["has_credentials"] = len(found) > 0



        # Token testen

        if result["has_token"]:

            service = mgr.get_gmail_service()

            if service:

                try:

                    profile = service.users().getProfile(userId='me').execute()

                    result["is_valid"] = True

                    result["email"] = profile.get('emailAddress', '')

                except Exception as e:

                    result["token_error"] = public_error_message()



        return result



    except Exception as e:

        return {"error": public_error_message()}



# ═══════════════════════════════════════════════════════════════

# API ROUTES - DAEMON (DAEMON_001)

# ═══════════════════════════════════════════════════════════════



import math

import time as time_module



# Daemon-Konfigurationspfad

DAEMON_CONFIG_FILE = BACH_DIR / "data" / "daemon_config.json"

DAEMON_PID_FILE = BACH_DIR / "data" / "daemon.pid"



def get_extrapolated_session_count(start_time_str: str, interval_min: int) -> int:

    """

    Berechnet wie oft der Intervall-Timer seit Start theoretisch ausgeloest hat.

    Formel aus CONCEPT_daemon_dashboard.md

    """

    try:

        start_time = datetime.fromisoformat(start_time_str)

        now = datetime.now()

        elapsed_sec = (now - start_time).total_seconds()

        elapsed_min = elapsed_sec / 60

        safety_buffer_min = 0.75  # 45 Sek Initial-Verzögerung

        

        if elapsed_min < safety_buffer_min:

            return 0

            

        return math.floor((elapsed_min - safety_buffer_min) / interval_min)

    except (ValueError, TypeError, OverflowError):

        return 0



def get_next_session_seconds(start_time_str: str, interval_min: int) -> int:

    """

    Berechnet Sekunden bis zur naechsten Session.

    Formel aus CONCEPT_daemon_dashboard.md

    """

    try:

        start_time = datetime.fromisoformat(start_time_str)

        now = datetime.now()

        interval_sec = interval_min * 60

        elapsed_sec = (now - start_time).total_seconds()

        

        # Modulo ergibt vergangene Zeit im aktuellen Intervall

        progress_in_interval = elapsed_sec % interval_sec

        return int(interval_sec - progress_in_interval)

    except (ValueError, TypeError, OverflowError):

        return interval_min * 60



def get_runtime_string(start_time_str: str) -> str:

    """Berechnet Laufzeit als HH:MM:SS String."""

    try:

        start_time = datetime.fromisoformat(start_time_str)

        now = datetime.now()

        elapsed = now - start_time

        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)

        minutes, seconds = divmod(remainder, 60)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    except (ValueError, TypeError, OverflowError):

        return "00:00:00"



def is_quiet_time(quiet_start: str, quiet_end: str) -> bool:

    """Prueft ob aktuell Ruhezeit ist."""

    try:

        now = datetime.now().time()

        start = datetime.strptime(quiet_start, "%H:%M").time()

        end = datetime.strptime(quiet_end, "%H:%M").time()

        

        if start <= end:

            return start <= now <= end

        else:  # Über Mitternacht (z.B. 22:00-08:00)

            return now >= start or now <= end

    except (ValueError, TypeError):

        return False



@app.put("/api/daemon/config")

async def update_daemon_config(request: Request):

    """

    Aktualisiert Daemon-Konfiguration (max_sessions, interval, etc.)

    Implementiert DAEMON_005 aus ROADMAP_ADVANCED.md

    """

    try:

        data = await request.json()

        

        # Bestehende Config laden oder neu erstellen

        config = {}

        if DAEMON_CONFIG_FILE.exists():

            with open(DAEMON_CONFIG_FILE, 'r', encoding='utf-8') as f:

                config = json.load(f)

        

        # Aktualierungen anwenden

        if "max_sessions" in data:

            val = data["max_sessions"]

            # 0 oder None = unbegrenzt

            config["max_sessions"] = int(val) if val and int(val) > 0 else 0

        

        if "interval_minutes" in data:

            config["interval_minutes"] = int(data["interval_minutes"])

        

        # Speichern

        DAEMON_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(DAEMON_CONFIG_FILE, 'w', encoding='utf-8') as f:

            json.dump(config, f, indent=2)

        

        return {"status": "ok", "config": config}

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())






# ═══════════════════════════════════════════════════════════════

# RECURRING TASKS API (RECURRING_003 aus ROADMAP_ADVANCED.md)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/recurring")

async def get_recurring_tasks():

    """Listet alle konfigurierten recurring Tasks mit Status."""

    if not RECURRING_AVAILABLE:

        raise HTTPException(status_code=503, detail="Recurring Tasks Modul nicht verfuegbar")

    

    try:

        tasks = list_recurring_tasks()

        return {

            "success": True,

            "count": len(tasks),

            "tasks": tasks

        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())



@app.post("/api/recurring/check")

async def check_recurring():

    """Prueft faellige recurring Tasks und erstellt sie."""

    if not RECURRING_AVAILABLE:

        raise HTTPException(status_code=503, detail="Recurring Tasks Modul nicht verfuegbar")

    

    try:

        created = check_recurring_tasks()

        return {

            "success": True,

            "created_count": len(created),

            "created_tasks": created

        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())



@app.post("/api/recurring/trigger/{task_id}")

async def trigger_recurring(task_id: str):

    """Loest einen recurring Task manuell aus."""

    if not RECURRING_AVAILABLE:

        raise HTTPException(status_code=503, detail="Recurring Tasks Modul nicht verfuegbar")

    

    try:

        result = trigger_recurring_task(task_id)

        if result:

            return {"success": True, "message": f"Task '{task_id}' erfolgreich ausgeloest"}

        else:

            raise HTTPException(status_code=404, detail=f"Recurring Task '{task_id}' nicht gefunden")

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())



# ═══════════════════════════════════════════════════════════════

# MEMORY API (Task 144)

# ═══════════════════════════════════════════════════════════════



@app.get("/memory", response_class=HTMLResponse)

async def memory_page():

    """Memory Dashboard (Task 144)."""

    astro_mem = ASTRO_DIST_DIR / "memory.html"
    if astro_mem.exists():
        return FileResponse(astro_mem)

    template = TEMPLATES_DIR / "memory.html"
    if template.exists():
        return template.read_text(encoding='utf-8')

    raise HTTPException(status_code=404, detail="Template memory.html nicht gefunden")





@app.get("/api/memory/overview")

async def get_memory_overview():

    """Memory-Uebersicht mit allen Kategorien."""

    result = {

        "working": [],

        "facts": [],

        "lessons": [],

        "sessions": [],

        "stats": {}

    }
    try:
        with get_bach_db() as conn:
            # Working Memory
            rows = conn.execute("""
                SELECT id, content, created_at FROM memory_working
                WHERE is_active = 1
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()
            result["working"] = rows_to_list(rows)

            # Facts
            rows = conn.execute("""
                SELECT id, category, key, value, value_type, confidence, source, created_at
                FROM memory_facts
                ORDER BY created_at DESC LIMIT 30
            """).fetchall()
            result["facts"] = rows_to_list(rows)

            # Lessons - map solution to content for GUI
            rows = conn.execute("""
                SELECT id, category, title, solution as content, created_at
                FROM memory_lessons
                WHERE is_active = 1
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()
            result["lessons"] = rows_to_list(rows)

            # Sessions
            rows = conn.execute("""
                SELECT id, session_id, started_at, ended_at, summary
                FROM memory_sessions
                ORDER BY id DESC LIMIT 10
            """).fetchall()
            result["sessions"] = rows_to_list(rows)

            # Consolidation
            rows = conn.execute("""
                SELECT id, source_table, source_id, weight, status, created_at
                FROM memory_consolidation
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()
            result["consolidation"] = rows_to_list(rows)

            # Injektoren (Triggers)
            rows = conn.execute("""
                SELECT id, trigger_phrase as trigger_key, source as trigger_type, hint_text, is_active, last_used as last_fired
                FROM context_triggers
                WHERE is_active = 1
                ORDER BY last_used DESC LIMIT 50
            """).fetchall()
            result["triggers"] = rows_to_list(rows)

            # Automation Injectors
            rows = conn.execute("""
                SELECT id, name, trigger_words as pattern, response_template as action, updated_at as created_at
                FROM automation_injectors
                WHERE is_active = 1
            """).fetchall()
            result["injectors"] = rows_to_list(rows)

            # Best Practices
            rows = conn.execute("""
                SELECT id, category, title, solution as content, created_at
                FROM memory_lessons
                WHERE category IN ('practice', 'best_practice', 'best-practice', 'architecture', 'gotcha', 'integration')
                ORDER BY created_at DESC LIMIT 30
            """).fetchall()
            result["best_practices"] = rows_to_list(rows)

            # Workflows (Procedural Memory: Lessons, Skills & Experts)
            workflows = []
            try:
                lesson_wf = conn.execute("""
                    SELECT title, category, solution as content FROM memory_lessons
                    WHERE category IN ('workflow', 'routine') OR title LIKE '%workflow%'
                    ORDER BY created_at DESC LIMIT 20
                """).fetchall()
                for row in lesson_wf:
                    workflows.append({
                        "name": row["title"] if hasattr(row, "keys") else row[0],
                        "filename": f"Lesson ({row['category'] if hasattr(row, 'keys') else row[1]})",
                        "content": (row["content"] if hasattr(row, "keys") else row[2]) or ""
                    })
            except Exception:
                pass

            try:
                skill_wf = conn.execute("""
                    SELECT name, category, description FROM skills
                    WHERE category IN ('dev', 'infrastructure', 'workflow', 'utilities') OR name LIKE '%workflow%' OR name LIKE '%pipeline%'
                    ORDER BY name ASC LIMIT 25
                """).fetchall()
                for row in skill_wf:
                    workflows.append({
                        "name": row["name"] if hasattr(row, "keys") else row[0],
                        "filename": f"Skill: {row['category'] if hasattr(row, 'keys') else row[1]}",
                        "content": (row["description"] if hasattr(row, "keys") else row[2]) or ""
                    })
            except Exception:
                pass

            try:
                expert_rows = conn.execute("""
                    SELECT display_name, domain, description FROM bach_experts
                    WHERE is_active = 1
                    ORDER BY display_name ASC LIMIT 15
                """).fetchall()
                for row in expert_rows:
                    workflows.append({
                        "name": f"Expert: {row['display_name'] if hasattr(row, 'keys') else row[0]}",
                        "filename": f"Domain: {row['domain'] if hasattr(row, 'keys') else row[1]}",
                        "content": (row["description"] if hasattr(row, "keys") else row[2]) or ""
                    })
            except Exception:
                pass

            try:
                workflow_dir = BACH_DIR / "skills" / "_workflows"
                if workflow_dir.exists():
                    for f in workflow_dir.glob("*.md"):
                        workflows.append({
                            "name": f.stem.replace("_", " ").title(),
                            "path": str(f.relative_to(BACH_DIR)),
                            "filename": f.name
                        })
            except OSError:
                pass
            result["workflows"] = workflows

            # Stats (extended)
            result["stats"]["working_count"] = conn.execute(
                "SELECT COUNT(*) FROM memory_working WHERE is_active = 1"
            ).fetchone()[0]
            result["stats"]["facts_count"] = conn.execute(
                "SELECT COUNT(*) FROM memory_facts"
            ).fetchone()[0]
            result["stats"]["lessons_count"] = conn.execute(
                "SELECT COUNT(*) FROM memory_lessons WHERE is_active = 1"
            ).fetchone()[0]
            result["stats"]["sessions_count"] = conn.execute(
                "SELECT COUNT(*) FROM memory_sessions"
            ).fetchone()[0]
            result["stats"]["consolidation_count"] = conn.execute(
                "SELECT COUNT(*) FROM memory_consolidation"
            ).fetchone()[0]
            result["stats"]["triggers_count"] = conn.execute(
                "SELECT COUNT(*) FROM context_triggers WHERE is_active = 1"
            ).fetchone()[0]
            result["stats"]["workflows_count"] = len(workflows)

            # Letzte Session
            last_session = conn.execute("""
                SELECT * FROM memory_sessions ORDER BY id DESC LIMIT 1
            """).fetchone()
            if last_session:
                result["last_session"] = dict(last_session)

    except Exception as e:
        result["error"] = public_error_message()



    return result





@app.get("/api/memory/working")

async def get_working_memory(limit: int = 50):

    """Working Memory Eintraege."""

    try:

        with get_bach_db() as conn:

            rows = conn.execute("""

                SELECT id, content, created_at FROM memory_working

                WHERE is_active = 1

                ORDER BY created_at DESC LIMIT ?

            """, (limit,)).fetchall()

            return {"entries": rows_to_list(rows), "count": len(rows)}

    except Exception as e:

        return {"entries": [], "count": 0, "error": public_error_message()}





@app.get("/api/memory/lessons")

async def get_lessons(limit: int = 50, category: Optional[str] = None):

    """Lessons Learned."""

    try:

        with get_bach_db() as conn:

            if category:

                rows = conn.execute("""

                    SELECT id, category, title, solution as content, created_at

                    FROM memory_lessons

                    WHERE category = ? AND is_active = 1

                    ORDER BY created_at DESC LIMIT ?

                """, (category, limit)).fetchall()

            else:

                rows = conn.execute("""

                    SELECT id, category, title, solution as content, created_at

                    FROM memory_lessons

                    WHERE is_active = 1

                    ORDER BY created_at DESC LIMIT ?

                """, (limit,)).fetchall()

            return {"entries": rows_to_list(rows), "count": len(rows)}

    except Exception as e:

        return {"entries": [], "count": 0, "error": public_error_message()}





@app.get("/api/memory/sessions")

async def get_sessions(limit: int = 20):

    """Session-History."""

    try:

        with get_bach_db() as conn:

            rows = conn.execute("""

                SELECT id, session_id, started_at, ended_at, summary

                FROM memory_sessions

                ORDER BY id DESC LIMIT ?

            """, (limit,)).fetchall()

            return {"sessions": rows_to_list(rows), "count": len(rows)}

    except Exception as e:

        return {"sessions": [], "count": 0, "error": public_error_message()}





class MemoryCreate(BaseModel):

    content: str

    category: Optional[str] = None

    source: Optional[str] = "gui"





@app.post("/api/memory/working")

async def add_working_memory(entry: MemoryCreate):

    """Neuen Working Memory Eintrag erstellen."""

    try:

        with get_bach_db() as conn:

            conn.execute("""

                INSERT INTO memory_working (type, content, created_at, is_active)

                VALUES ('note', ?, ?, 1)

            """, (entry.content, datetime.now().isoformat()))

            conn.commit()

            return {"status": "created", "message": "Memory-Eintrag erstellt"}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.post("/api/memory/lessons")

async def add_lesson(entry: MemoryCreate):

    """Neue Lesson erstellen."""

    try:

        with get_bach_db() as conn:

            conn.execute("""

                INSERT INTO memory_lessons (category, title, solution, created_at, is_active)

                VALUES (?, 'Lesson', ?, ?, 1)

            """, (entry.category or 'general', entry.content, datetime.now().isoformat()))

            conn.commit()

            return {"status": "created", "message": "Lesson erstellt"}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.get("/api/memory/facts")

async def get_facts(limit: int = 50):

    """Memory Facts abrufen."""

    try:

        with get_bach_db() as conn:

            rows = conn.execute("""

                SELECT id, category, key, value, value_type, confidence, source, created_at

                FROM memory_facts

                ORDER BY created_at DESC LIMIT ?

            """, (limit,)).fetchall()

            return {"facts": rows_to_list(rows)}

    except Exception as e:

        return {"error": public_error_message()}





@app.post("/api/memory/facts")

async def add_fact(entry: dict):

    """Memory Fact erstellen."""

    key = entry.get("key", "").strip()

    value = entry.get("value", "").strip()

    category = entry.get("category", "")

    if not key or not value:

        return {"status": "error", "message": "Key und Value sind erforderlich"}

    try:

        with get_bach_db() as conn:

            conn.execute("""

                INSERT INTO memory_facts (category, key, value, value_type, confidence, source, created_at)

                VALUES (?, ?, ?, 'text', 1.0, 'gui', ?)

            """, (category, key, value, datetime.now().isoformat()))

            conn.commit()

            return {"status": "created", "message": "Fact erstellt"}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.delete("/api/memory/facts/{fact_id}")

async def delete_fact(fact_id: int):

    """Memory Fact loeschen."""

    try:

        with get_bach_db() as conn:

            conn.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))

            conn.commit()

            return {"status": "deleted"}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.delete("/api/memory/working/{entry_id}")

async def delete_working_memory(entry_id: int):

    """Working Memory Eintrag deaktivieren."""

    try:

        with get_bach_db() as conn:

            conn.execute("UPDATE memory_working SET is_active = 0 WHERE id = ?", (entry_id,))

            conn.commit()

            return {"status": "deleted"}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}



@app.delete("/api/memory/lessons/{lesson_id}")

async def delete_lesson(lesson_id: int):

    """Lesson deaktivieren."""

    try:

        with get_bach_db() as conn:

            conn.execute("UPDATE memory_lessons SET is_active = 0 WHERE id = ?", (lesson_id,))

            conn.commit()

            return {"status": "deleted"}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.get("/api/memory/stats/db")

async def get_memory_db_stats():

    """Detaillierte DB-Statistiken fuer Memory-Tabellen."""

    try:

        with get_bach_db() as conn:

            conn.row_factory = sqlite3.Row

            cursor = conn.cursor()

            

            # Alle Tabellen laden

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")

            tables = [row['name'] for row in cursor.fetchall()]

            

            stats = []

            for table in tables:

                cursor.execute(f"SELECT COUNT(*) FROM {table}")

                count = cursor.fetchone()[0]

                

                # Letztes Update (falls Spalte existiert)

                cursor.execute(f"PRAGMA table_info({table})")

                columns = [c['name'] for c in cursor.fetchall()]

                last_update = None

                if 'updated_at' in columns:

                    cursor.execute(f"SELECT MAX(updated_at) FROM {table}")

                    last_update = cursor.fetchone()[0]

                elif 'created_at' in columns:

                    cursor.execute(f"SELECT MAX(created_at) FROM {table}")

                    last_update = cursor.fetchone()[0]

                

                stats.append({

                    "table": table,

                    "rows": count,

                    "last_update": last_update

                })

            

            return {"success": True, "tables": stats, "count": len(stats)}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.post("/api/memory/maintenance/cleanup")

async def memory_maintenance_cleanup():

    """System-Cleanup fuer Memory (Orphans, alte Eintraege)."""

    try:

        with get_bach_db() as conn:

            results = {}

            

            # 1. Orphans in memory_consolidation (Source existiert nicht mehr)

            # Wir checken beispielhaft fuer working und lessons

            cursor = conn.cursor()

            

            # Zu loeschende Consolidation-Eintraege finden

            cursor.execute("""

                DELETE FROM memory_consolidation 

                WHERE source_table = 'memory_working' 

                AND source_id NOT IN (SELECT id FROM memory_working)

            """)

            results["orphans_working_removed"] = cursor.rowcount

            

            cursor.execute("""

                DELETE FROM memory_consolidation 

                WHERE source_table = 'memory_lessons' 

                AND source_id NOT IN (SELECT id FROM memory_lessons)

            """)

            results["orphans_lessons_removed"] = cursor.rowcount

            

            # 2. Inaktive Eintraege endgueltig loeschen (optional, je nach Policy)

            # Hier nur Zaehlen was "weg koennte"

            cursor.execute("SELECT COUNT(*) FROM memory_working WHERE is_active = 0")

            results["inactive_working_count"] = cursor.fetchone()[0]

            

            conn.commit()

            return {"success": True, "details": results}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.get("/api/memory/sessions/{session_id}")

async def get_session_detail(session_id: str):

    """Session-Details abrufen (entweder via ID oder session_id String)."""

    try:

        with get_bach_db() as conn:

            conn.row_factory = sqlite3.Row

            

            if session_id.isdigit():

                row = conn.execute("SELECT * FROM memory_sessions WHERE id = ?", (session_id,)).fetchone()

            else:

                row = conn.execute("SELECT * FROM memory_sessions WHERE session_id = ?", (session_id,)).fetchone()

            

            if not row:

                raise HTTPException(status_code=404, detail="Session nicht gefunden")

            

            session_data = dict(row)

            

            # Optional: Zugehoerige Tasks laden

            # row['tasks_completed'] usw. sind schon drin

            

            return {"success": True, "session": session_data}

    except HTTPException:

        raise

    except Exception as e:

        return {"success": False, "error": public_error_message()}





# ═══════════════════════════════════════════════════════════════

# TOOLS API (Task 99/100)

# ═══════════════════════════════════════════════════════════════



TOOLS_DIR = BACH_DIR / "tools"





@app.get("/tools", response_class=HTMLResponse)

async def tools_page():

    """Tools Dashboard (Task 100)."""

    template = TEMPLATES_DIR / "tools.html"

    if template.exists():

        return template.read_text(encoding='utf-8')

    raise HTTPException(status_code=404, detail="Template tools.html nicht gefunden")





@app.get("/api/tools")

async def get_tools(

    type: Optional[str] = None,

    category: Optional[str] = None,

    search: Optional[str] = None

):

    """Listet alle verfuegbaren Tools (Task 99).



    Args:

        type: Filterung nach Typ (python, cli, external)

        category: Filterung nach Kategorie

        search: Suchbegriff

    """

    result = {

        "python_tools": [],

        "db_tools": [],

        "categories": [],

        "stats": {}

    }



    # 1. Python-Tools aus Dateisystem

    if TOOLS_DIR.exists():

        for f in TOOLS_DIR.glob("*.py"):

            if f.name.startswith("_"):

                continue



            # Prefix erkennen

            name = f.stem

            prefix = name.split("_")[0] if "_" in name else ""



            tool_info = {

                "name": name,

                "path": str(f.relative_to(BACH_DIR)),

                "prefix": prefix,

                "type": "python"

            }



            # Docstring extrahieren

            try:

                content = f.read_text(encoding='utf-8', errors='ignore')

                if '"""' in content:

                    doc_start = content.find('"""') + 3

                    doc_end = content.find('"""', doc_start)

                    if doc_end > doc_start:

                        docstring = content[doc_start:doc_end].strip()

                        first_line = docstring.split('\n')[0]

                        tool_info["description"] = first_line[:100]

            except (OSError, UnicodeDecodeError):

                pass



            # Filter anwenden

            if search and search.lower() not in name.lower():

                continue

            if type and type != "python":

                continue



            result["python_tools"].append(tool_info)



        # Subdirectories

        for subdir in ["steuer", "testing", "generators", "mapping"]:

            subpath = TOOLS_DIR / subdir

            if subpath.exists():

                for f in subpath.glob("*.py"):

                    if f.name.startswith("_"):

                        continue



                    name = f.stem

                    tool_info = {

                        "name": name,

                        "path": str(f.relative_to(BACH_DIR)),

                        "prefix": subdir,

                        "type": "python",

                        "category": subdir

                    }



                    if search and search.lower() not in name.lower():

                        continue



                    result["python_tools"].append(tool_info)



    # 2. CLI/External Tools aus Datenbank

    try:

        with get_bach_db() as conn:

            query = "SELECT * FROM tools WHERE 1=1"

            params = []



            if type and type in ["cli", "external"]:

                query += " AND type = ?"

                params.append(type)



            if category:

                query += " AND category = ?"

                params.append(category)



            if search:

                query += " AND (name LIKE ? OR description LIKE ?)"

                params.extend([f"%{search}%", f"%{search}%"])



            rows = conn.execute(query, params).fetchall()



            for row in rows:

                tool_info = {

                    "id": row["id"],

                    "name": row["name"],

                    "type": row["type"],

                    "category": row["category"],

                    "description": row["description"],

                    "command": row.get("command"),

                    "endpoint": row.get("endpoint"),

                    "is_available": bool(row.get("is_available", True))

                }

                result["db_tools"].append(tool_info)



            # Kategorien sammeln

            cats = conn.execute(

                "SELECT DISTINCT category FROM tools WHERE category IS NOT NULL"

            ).fetchall()

            result["categories"] = [c[0] for c in cats]



    except Exception as e:

        result["db_error"] = public_error_message()



    # 3. Statistiken

    result["stats"] = {

        "python_count": len(result["python_tools"]),

        "db_count": len(result["db_tools"]),

        "total": len(result["python_tools"]) + len(result["db_tools"])

    }



    return result










# ═══════════════════════════════════════════════════════════════

# PROMPT-GENERATOR API (DEPRECATED — PromptBoard ist jetzt im Unified System Tray)

# ═══════════════════════════════════════════════════════════════



# Import Prompt-Generator Service

sys.path.insert(0, str(BACH_DIR / "hub" / "_services" / "prompt_generator"))

try:

    from prompt_generator import PromptGenerator

    PROMPT_GEN_AVAILABLE = True

except ImportError:

    PROMPT_GEN_AVAILABLE = False





@app.get("/prompt-generator")

async def prompt_generator_page():

    """DEPRECATED: Prompt-Generator wurde durch PromptBoard im Unified System Tray ersetzt."""

    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/prompt-library", status_code=302)


# ═══════════════════════════════════════════════════════════════

# PROMPT-BIBLIOTHEK (BACH-eigene DB: prompt_templates/-versions/-boards)
# Uebergangsloesung bis zur Unified GUI: GUI-Anbindung an hub/prompt.py-
# Datenmodell + Import aus PromptBoard (library.json).

# ═══════════════════════════════════════════════════════════════


class PromptCreateRequest(BaseModel):
    name: str
    text: str
    category: Optional[str] = None
    tags: Optional[str] = None
    purpose: Optional[str] = None


class PromptUpdateRequest(BaseModel):
    text: str
    tags: Optional[str] = None


def _promptboard_library_paths():
    """Kandidaten fuer PromptBoard library.json (gleiche Logik wie chat_tray.py)."""
    candidates = []
    env_path = os.environ.get("BACH_PROMPTBOARD_LIBRARY")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path.home() / ".promptboard" / "library.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "PromptBoard" / "library.json")
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        project_dir = (Path(user_profile) / "OneDrive" / ".TOPICS" / ".SOFTWARE"
                       / "LLM" / "REL-PUB_PromptBoard")
        candidates.extend([project_dir / "library.json", project_dir / "data" / "library.json"])
    return candidates


@app.get("/prompt-library", response_class=HTMLResponse)
async def prompt_library_page():
    """Prompt-Bibliothek (BACH-DB) als GUI-Seite."""
    template = TEMPLATES_DIR / "prompt-library.html"
    if template.exists():
        return HTMLResponse(content=template.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Template prompt-library.html fehlt</h1>", status_code=404)


@app.get("/api/prompt-library")
async def list_prompt_library(q: Optional[str] = None, category: Optional[str] = None):
    """Listet Prompt-Templates aus der BACH-DB (optional Suche/Kategorie)."""
    conn = get_bach_db()
    try:
        sql = ("SELECT id, name, category, purpose, tags, created_at, updated_at "
               "FROM prompt_templates")
        clauses, params = [], []
        if q:
            clauses.append("(name LIKE ? OR text LIKE ? OR tags LIKE ? OR purpose LIKE ?)")
            params.extend([f"%{q}%"] * 4)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name"
        rows = conn.execute(sql, params).fetchall()
        cats = conn.execute(
            "SELECT DISTINCT category FROM prompt_templates WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()
        return {
            "prompts": [row_to_dict(r) for r in rows],
            "categories": [c["category"] for c in cats],
        }
    finally:
        conn.close()


@app.get("/api/prompt-library/{prompt_id}")
async def get_prompt_library_entry(prompt_id: int):
    """Einzelnes Template inkl. Versionshistorie."""
    conn = get_bach_db()
    try:
        row = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (prompt_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prompt nicht gefunden")
        versions = conn.execute(
            "SELECT id, version_number, text, tags, created_at FROM prompt_versions "
            "WHERE prompt_id = ? ORDER BY version_number DESC",
            (prompt_id,),
        ).fetchall()
        return {"prompt": row_to_dict(row), "versions": [row_to_dict(v) for v in versions]}
    finally:
        conn.close()


@app.post("/api/prompt-library")
async def create_prompt_library_entry(req: PromptCreateRequest):
    """Neues Template anlegen."""
    name = req.name.strip()
    if not name or not req.text.strip():
        raise HTTPException(status_code=400, detail="name und text sind Pflicht")
    now = datetime.now().isoformat()
    conn = get_bach_db()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, req.purpose, req.text, req.tags, req.category, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"Name existiert bereits: {name}")
        return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/prompt-library/{prompt_id}")
async def update_prompt_library_entry(prompt_id: int, req: PromptUpdateRequest):
    """Text aktualisieren — alter Stand wird als Version archiviert (wie hub/prompt.py)."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text ist Pflicht")
    now = datetime.now().isoformat()
    conn = get_bach_db()
    try:
        row = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (prompt_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prompt nicht gefunden")
        max_v = conn.execute(
            "SELECT MAX(version_number) FROM prompt_versions WHERE prompt_id = ?", (prompt_id,)
        ).fetchone()[0] or 0
        conn.execute(
            "INSERT INTO prompt_versions (prompt_id, version_number, text, tags, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (prompt_id, max_v + 1, row["text"], row["tags"], now),
        )
        conn.execute(
            "UPDATE prompt_templates SET text = ?, tags = COALESCE(?, tags), updated_at = ? WHERE id = ?",
            (req.text, req.tags, now, prompt_id),
        )
        conn.commit()
        return {"ok": True, "archived_version": max_v + 1}
    finally:
        conn.close()


@app.delete("/api/prompt-library/{prompt_id}")
async def delete_prompt_library_entry(prompt_id: int):
    """Template inkl. Versionen und Board-Verknuepfungen loeschen."""
    conn = get_bach_db()
    try:
        row = conn.execute("SELECT id FROM prompt_templates WHERE id = ?", (prompt_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prompt nicht gefunden")
        conn.execute("DELETE FROM prompt_board_items WHERE prompt_id = ?", (prompt_id,))
        conn.execute("DELETE FROM prompt_versions WHERE prompt_id = ?", (prompt_id,))
        conn.execute("DELETE FROM prompt_templates WHERE id = ?", (prompt_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/prompt-library/import-promptboard")
async def import_promptboard_library():
    """Importiert PromptBoard library.json in die BACH-Prompt-DB (idempotent per Name)."""
    library_path = next((p for p in _promptboard_library_paths() if p.exists()), None)
    if library_path is None:
        raise HTTPException(
            status_code=404,
            detail="Keine PromptBoard library.json gefunden (BACH_PROMPTBOARD_LIBRARY, "
                   "~/.promptboard, %APPDATA%/PromptBoard, REL-PUB_PromptBoard)",
        )
    try:
        payload = json.loads(library_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=422, detail=f"library.json nicht lesbar: {e}")

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="Unerwartetes Format: 'items'-Liste fehlt")

    now = datetime.now().isoformat()
    imported, skipped = 0, 0
    conn = get_bach_db()
    try:
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            content = str(item.get("content") or "").strip()
            if not name or not content:
                continue
            category = str(item.get("category") or item.get("item_type") or "PromptBoard").strip()
            tags = item.get("tags")
            if isinstance(tags, list):
                tags = ",".join(str(t) for t in tags)
            cur = conn.execute(
                "INSERT OR IGNORE INTO prompt_templates "
                "(name, purpose, text, tags, category, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, item.get("description"), content, tags, category, now, now),
            )
            if cur.rowcount:
                imported += 1
            else:
                skipped += 1
        conn.commit()
        return {"ok": True, "source": str(library_path), "imported": imported, "skipped": skipped}
    finally:
        conn.close()





@app.get("/api/prompt-generator/templates")

async def get_prompt_templates():

    """Listet alle verfuegbaren Templates (PROMPT_GEN_002)."""

    if not PROMPT_GEN_AVAILABLE:

        return {"system": [], "agents": [], "custom": []}



    try:

        pg = PromptGenerator()

        templates = pg.list_templates()

        return templates

    except Exception as e:

        return {"system": [], "agents": [], "custom": [], "error": public_error_message()}





@app.get("/api/prompt-generator/template/{template_path:path}")

async def get_prompt_template(template_path: str):

    """Laedt ein einzelnes Template (PROMPT_GEN_003)."""

    if not PROMPT_GEN_AVAILABLE:

        raise HTTPException(status_code=503, detail="Prompt-Generator nicht verfuegbar")



    try:

        pg = PromptGenerator()

        content = pg.get_template(template_path)

        if content:

            return {"path": template_path, "content": content}

        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {template_path}")

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(status_code=500, detail=public_error_message())





class PromptSendRequest(BaseModel):

    prompt: str

    priority: Optional[str] = "P2"

    timeout_minutes: Optional[int] = 12

    variables: Optional[dict] = None

    include_header: Optional[bool] = True  # Toggle fuer Auto-Session Header





@app.post("/api/prompt-generator/send/task")

async def send_prompt_as_task(req: PromptSendRequest):

    """Erstellt Task aus Prompt (PROMPT_GEN_004)."""

    if not PROMPT_GEN_AVAILABLE:

        raise HTTPException(status_code=503, detail="Prompt-Generator nicht verfuegbar")



    try:

        pg = PromptGenerator()

        result = pg.send_as_task(req.prompt, req.priority)

        return result

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.post("/api/prompt-generator/send/session")

async def send_prompt_direct_session(req: PromptSendRequest):

    """Startet direkte Claude-Session (PROMPT_GEN_004).



    Kombiniert minimalen Header mit Textfenster-Prompt.

    Header enthält:

    1. BACH Startup mit CLI-Timer-Flags

    2. Verweis auf SKILL.md ab Abschnitt (5)

    3. User-Prompt aus Textfenster

    """

    if not PROMPT_GEN_AVAILABLE:

        raise HTTPException(status_code=503, detail="Prompt-Generator nicht verfuegbar")



    try:

        timeout = req.timeout_minutes or 12

        skill_file = BACH_DIR / "SKILL.md"



        # Header mit CLI-Timer-Befehlen und Workflow

        header = f"""# BACH AUTO-SESSION

## 1. ERSTE AKTION (Automatischer Modus)

```bash
cd "{BACH_DIR}"
python bach.py --startup --partner=claude --mode=silent
bach countdown {timeout} --name="Session-Ende" --notify
bach between use autosession
```

## 2. SKILL.md (ab Abschnitt 2)

Lies {skill_file} und springe direkt zu Abschnitt **(2) SYSTEM**.
Nur Punkt (1) EINLEITUNG wurde bereits durchgefuehrt.

## 3. ARBEITSPHASE

"""

        # Workflow-Footer
        workflow_footer = """

### AUFGABEN-WORKFLOW:
```
(A) bach beat           # Startzeit merken
(B) Aufgabe erledigen
(C) bach beat           # Endzeit = Dauer berechnen
```

### BETWEEN-TASK CHECK (nach jeder Aufgabe):
1. ZEIT-CHECK: `bach countdown status` - Restzeit pruefen
2. ENTSCHEIDUNG:
   - Restzeit > Aufgabendauer + 3min Sicherheit? -> Naechste Aufgabe
   - Sonst -> Weiter zu SESSION-ENDE

**DENKANSTOSS:**
- Planen und Zerlegen kann deine Aufgabe sein!
- Du musst nicht fertig werden, nur dokumentieren wo du warst!

## 4. SESSION-ENDE

### Kontinuitaetstests (max. 2 Min):
- Lessons learned? -> `bach memory add "..."`
- Tasks erledigt? -> Im Taskmanager dokumentieren
- Neue Folgeaufgaben? -> Als neue Tasks anlegen
- Grosse Aenderung? -> CHANGELOG.md + help aktualisieren

### Meta-Plan (max. 2 Min):
- ROADMAP-Aufgabe erledigt? -> ROADMAP.md aktualisieren
- Bug entdeckt? -> BUGLOG.md

### Abschliessen:
```bash
bach --memory session
bach --shutdown "Zusammenfassung der erledigten Arbeit"
```
"""

        # Je nach Toggle: Mit oder ohne Header
        if req.include_header:
            # Kombiniere Header + User-Prompt + Workflow-Footer
            full_prompt = header + req.prompt + workflow_footer
        else:
            # Nur User-Prompt (ohne Header/Footer)
            full_prompt = req.prompt



        pg = PromptGenerator()

        result = pg.send_direct_session(full_prompt)

        return result

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.post("/api/prompt-generator/send/copy")

async def copy_prompt_to_clipboard(req: PromptSendRequest):

    """Kopiert Prompt in Zwischenablage (PROMPT_GEN_004)."""

    if not PROMPT_GEN_AVAILABLE:

        raise HTTPException(status_code=503, detail="Prompt-Generator nicht verfuegbar")



    try:

        pg = PromptGenerator()

        result = pg.copy_to_clipboard(req.prompt)

        return result

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.get("/api/prompt-generator/daemon/status")

async def get_prompt_daemon_status():

    """Daemon-Status fuer Prompt-Generator (PROMPT_GEN_005)."""

    # Pfade zum System-Daemon-Service

    pid_file = BACH_DIR / "hub" / "_services" / "daemon" / "daemon.pid"

    config_file = BACH_DIR / "hub" / "_services" / "daemon" / "config.json"



    # Prüfe ob Daemon-Prozess läuft

    daemon_running = False

    daemon_pid = 0

    if pid_file.exists():

        try:

            daemon_pid = int(pid_file.read_text().strip())

            os.kill(daemon_pid, 0)  # Prüft ob Prozess existiert

            daemon_running = True

        except (OSError, ValueError):

            # OSError deckt auch WinError 87 ab: os.kill(pid, 0) wirft auf
            # Windows bei nicht existierender PID generischen OSError
            pass



    # Config laden

    config = {}

    if config_file.exists():

        try:

            config = json.loads(config_file.read_text(encoding="utf-8"))

        except (json.JSONDecodeError, OSError):

            pass



    return {

        "enabled": config.get("enabled", False),

        "running": daemon_running,

        "pid": daemon_pid if daemon_running else None,

        "interval_minutes": config.get("interval_minutes", 30),

        "max_sessions": config.get("daemon", {}).get("max_sessions", 0) if "daemon" in config else 0,

        "quiet_start": config.get("quiet_start", "22:00"),

        "quiet_end": config.get("quiet_end", "08:00")

    }





class DaemonConfigRequest(BaseModel):

    interval_minutes: Optional[int] = None

    max_sessions: Optional[int] = None

    quiet_time: Optional[str] = None

    enabled: Optional[bool] = None





@app.put("/api/prompt-generator/daemon/config")

async def update_prompt_daemon_config(req: DaemonConfigRequest):

    """Aktualisiert Daemon-Konfiguration (PROMPT_GEN_005)."""

    if not PROMPT_GEN_AVAILABLE:

        raise HTTPException(status_code=503, detail="Prompt-Generator nicht verfuegbar")



    try:

        pg = PromptGenerator()



        # Quiet time parsen

        quiet_start = None

        quiet_end = None

        if req.quiet_time and '-' in req.quiet_time:

            parts = req.quiet_time.split('-')

            quiet_start = parts[0]

            quiet_end = parts[1]



        result = pg.update_daemon_config(

            interval_minutes=req.interval_minutes,

            max_sessions=req.max_sessions,

            quiet_start=quiet_start,

            quiet_end=quiet_end,

            enabled=req.enabled

        )

        return result

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.post("/api/prompt-generator/daemon/toggle")

async def toggle_prompt_daemon():

    """Startet/Stoppt Prompt-Generator Daemon (PROMPT_GEN_005)."""

    if not PROMPT_GEN_AVAILABLE:

        raise HTTPException(status_code=503, detail="Prompt-Generator nicht verfuegbar")



    import subprocess

    import signal



    # Pfade zum System-Daemon-Service

    daemon_script = BACH_DIR / "hub" / "_services" / "daemon" / "session_daemon.py"

    pid_file = BACH_DIR / "hub" / "_services" / "daemon" / "daemon.pid"



    try:

        # Prüfe ob Daemon läuft (PID-Check)

        daemon_running = False

        daemon_pid = 0

        if pid_file.exists():

            try:

                daemon_pid = int(pid_file.read_text().strip())

                os.kill(daemon_pid, 0)  # Prüft ob Prozess existiert

                daemon_running = True

            except (ProcessLookupError, ValueError, PermissionError):

                # PID-File existiert aber Prozess nicht mehr

                try:

                    pid_file.unlink()

                except OSError:

                    pass



        if daemon_running:

            # STOP: Daemon beenden

            try:

                os.kill(daemon_pid, signal.SIGTERM)

                return {

                    "status": "ok",

                    "enabled": False,

                    "running": False,

                    "message": f"Daemon (PID {daemon_pid}) gestoppt"

                }

            except Exception as e:

                return {"status": "error", "message": public_error_message()}

        else:

            # START: Daemon starten

            if not daemon_script.exists():

                return {"status": "error", "message": f"Daemon-Script nicht gefunden: {daemon_script}"}


            # Reset last_run in config fuer sofortigen Start nach Sicherheitsintervall
            config_file = BACH_DIR / "hub" / "_services" / "daemon" / "config.json"
            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text(encoding="utf-8"))
                    for job in config.get("jobs", []):
                        job["last_run"] = None  # Reset fuer sofortigen Start
                    config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
                except (json.JSONDecodeError, OSError):
                    pass

            # Starte Daemon im Hintergrund

            creation_flags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS

            subprocess.Popen(

                [sys.executable, str(daemon_script)],

                cwd=str(daemon_script.parent),

                creationflags=creation_flags,

                stdout=subprocess.DEVNULL,

                stderr=subprocess.DEVNULL,

                start_new_session=True

            )



            # Kurz warten und prüfen ob gestartet

            import time

            time.sleep(1)



            new_pid = 0

            if pid_file.exists():

                try:

                    new_pid = int(pid_file.read_text().strip())

                except (OSError, ValueError):

                    pass



            return {

                "status": "ok",

                "enabled": True,

                "running": True,

                "pid": new_pid,

                "message": f"Daemon gestartet (PID {new_pid})"

            }



    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.post("/api/auto-sessions/launch")
async def launch_auto_session(request: Request):
    """Startet eine vordefinierte Claude Code Auto-Session."""
    import subprocess
    import re
    try:
        data = await request.json()
        session_id = data.get("session_id", "")
        if not re.match(r'^[a-zA-Z0-9_-]+$', session_id):
            return {"status": "error", "message": "Ungueltige Session-ID"}
        start_dir = Path(__file__).parent.parent.parent / "start"
        session_script = safe_path_segment(session_id, field_name="Session-ID")

        env = {**os.environ, "BACH_AUTO": "1"}
        if sys.platform == "win32":
            script_file = resolve_child_file(start_dir, f"{session_script}.bat", allowed_suffixes={".bat"})
            if not script_file.exists():
                return {"status": "error", "message": f"Batch-Datei nicht gefunden: {script_file.name}"}
            subprocess.Popen(
                ["cmd", "/c", "start", str(script_file)],
                cwd=str(start_dir),
                creationflags=0x00000010,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )
        else:
            script_file = resolve_child_file(start_dir, f"{session_script}.sh", allowed_suffixes={".sh"})
            if not script_file.exists():
                return {"status": "error", "message": f"Script nicht gefunden: {script_file.name}"}
            subprocess.Popen(
                ["bash", str(script_file)],
                cwd=str(start_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env
            )

        return {"status": "launched", "session_id": session_id, "message": f"Session {session_id} gestartet"}
    except Exception as e:
        return {"status": "error", "message": public_error_message()}


class TemplateSaveRequest(BaseModel):

    name: str

    content: str

    category: Optional[str] = "custom"





@app.post("/api/prompt-generator/templates/save")

async def save_prompt_template(req: TemplateSaveRequest):

    """Speichert eigene Vorlage (PROMPT_GEN_007)."""

    if not PROMPT_GEN_AVAILABLE:

        raise HTTPException(status_code=503, detail="Prompt-Generator nicht verfuegbar")



    try:

        # Speichere als Datei im custom-Ordner

        custom_dir = BACH_DIR / "hub" / "_services" / "prompt_generator" / "templates" / "custom"

        custom_dir.mkdir(parents=True, exist_ok=True)



        # Dateiname normalisieren

        safe_name = safe_path_segment("".join(c if c.isalnum() or c in "-_" else "_" for c in req.name), field_name="Vorlagenname")

        file_path = resolve_child_file(custom_dir, f"{safe_name}.txt", allowed_suffixes={".txt"})



        # Mit Header speichern

        content_with_header = f"# {req.name}\n# Eigene Vorlage\n\n{req.content}"

        file_path.write_text(content_with_header, encoding='utf-8')



        return {"status": "saved", "path": f"custom/{safe_name}", "name": req.name}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





# ═══════════════════════════════════════════════════════════════

# API ROUTES - SESSION (ASM_001)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/session/activities")

async def get_session_activities():

    """ASM_001: Laedt Aktivitaeten der aktuellen Session."""

    try:

        # Autolog-Analyzer importieren

        tools_dir = BACH_DIR / "tools"

        sys.path.insert(0, str(tools_dir))

        from autolog_analyzer import AutologAnalyzer



        analyzer = AutologAnalyzer()

        analyzer.parse_log(last_n_lines=200)



        # Aktivitaeten extrahieren

        activities = []

        for entry in analyzer.entries:

            activity = {

                "time": entry.timestamp.strftime("%H:%M") if entry.timestamp else "",

                "type": "other",

                "summary": ""

            }



            content = entry.content



            # Task-bezogen

            if "task" in content.lower():

                activity["type"] = "task"

                if "erledigt" in content.lower() or "done" in content.lower():

                    activity["summary"] = "Task erledigt: " + content[:60]

                elif "erstellt" in content.lower() or "create" in content.lower():

                    activity["summary"] = "Task erstellt: " + content[:60]

                else:

                    activity["summary"] = content[:80]



            # Datei-bezogen

            elif any(x in content.lower() for x in ["edit", "write", "file", ".py", ".html", ".js", ".md"]):

                activity["type"] = "file"

                activity["summary"] = content[:80]



            # Memory-Eintrag

            elif content.startswith("memory"):

                activity["type"] = "memory"

                activity["summary"] = content[7:80] if len(content) > 7 else content



            # Sonstiges

            else:

                activity["summary"] = content[:60]



            if activity["summary"]:

                activities.append(activity)



        # Nur die letzten 30 Eintraege zurueckgeben

        return {"activities": activities[-30:]}

    except Exception as e:

        return {"activities": [], "error": public_error_message()}





@app.post("/api/session/generate-summary")

async def generate_session_summary():

    """ASM_002: Generiert automatische Session-Zusammenfassung."""

    try:

        tools_dir = BACH_DIR / "tools"

        sys.path.insert(0, str(tools_dir))

        from autolog_analyzer import AutologAnalyzer



        analyzer = AutologAnalyzer()

        analyzer.parse_log(last_n_lines=200)

        session = analyzer.extract_session()



        # Zusammenfassung generieren

        parts = []



        if session.tasks_completed:

            parts.append("ERLEDIGT:\n" + "\n".join(f"- {t}" for t in session.tasks_completed[:5]))



        if session.files_changed:

            parts.append("DATEIEN:\n" + "\n".join(f"- {f}" for f in session.files_changed[:5]))



        if session.commands:

            # Nur wichtige Commands (nicht startup/shutdown)

            important_cmds = [c for c in session.commands if c not in ['startup', 'shutdown']]

            if important_cmds:

                parts.append("COMMANDS:\n" + "\n".join(f"- {c}" for c in important_cmds[:5]))



        if session.session_summary:

            parts.append("BISHERIGER BERICHT:\n" + session.session_summary)



        summary = "\n\n".join(parts) if parts else "Keine Aktivitaeten in dieser Session gefunden."



        return {"summary": summary}

    except Exception as e:

        return {"summary": f"Fehler bei der Generierung: {public_error_message()}"}





@app.post("/api/session/end")

async def end_session():

    """ASM_001: Beendet die aktuelle Session."""

    try:

        import subprocess



        # BACH Shutdown aufrufen

        bach_cli = BACH_DIR / "bach.py"

        result = subprocess.run(

            [sys.executable, str(bach_cli), "--shutdown"],

            capture_output=True,

            text=True,

            encoding='utf-8', errors='replace',

            timeout=30

        )



        return {

            "success": result.returncode == 0,

            "message": result.stdout or "Session beendet"

        }

    except subprocess.TimeoutExpired:

        return {"success": False, "message": "Timeout beim Shutdown"}

    except Exception as e:

        return {"success": False, "message": public_error_message()}





@app.post("/api/memory/sessions")

async def add_session_memory(request: Request):

    """Speichert Session-Memory Eintrag."""

    try:

        data = await request.json()

        content = data.get("content", "")

        session_id = data.get("session_id", datetime.now().strftime("%Y-%m-%d"))



        if not content:

            raise HTTPException(status_code=400, detail="Content erforderlich")



        conn = get_user_db()

        cursor = conn.cursor()



        # Session-Memory Tabelle pruefen/erstellen

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS session_memories (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                session_id TEXT NOT NULL,

                content TEXT NOT NULL,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )

        """)



        cursor.execute(

            "INSERT INTO session_memories (session_id, content) VALUES (?, ?)",

            (session_id, content)

        )



        conn.commit()

        conn.close()



        return {"success": True, "session_id": session_id}

    except HTTPException:

        raise

    except Exception as e:

        return {"success": False, "error": public_error_message()}





# ═══════════════════════════════════════════════════════════════

# API ROUTES - MAIL PROFILES (MAIL_001-005)

# ═══════════════════════════════════════════════════════════════



MAIL_PROFILES_FILE = BACH_DIR / "data" / "mail_profiles.json"

MAIL_FALSE_POSITIVES_FILE = BACH_DIR / "data" / "mail_false_positives.json"



class MailProfileCreate(BaseModel):

    id: str

    name: str

    enabled: bool = True

    sender_patterns: List[str] = []

    subject_patterns: List[str] = []

    blacklist: List[str] = []

    body_must_contain: List[str] = []

    body_must_not_contain: List[str] = []

    category: str = "sonstiges"

    type: str = "rechnung"

    steuer_relevant: bool = False

    recurring: bool = False



class FalsePositiveCreate(BaseModel):

    message_id: str

    sender: str

    subject: str

    reason: Optional[str] = None

    add_to_blacklist: bool = False

    blacklist_terms: List[str] = []



class ProfileTestRequest(BaseModel):

    sender: str

    subject: str

    body: Optional[str] = ""



def load_mail_profiles() -> dict:

    """Laedt Mail-Profile aus JSON."""

    if MAIL_PROFILES_FILE.exists():

        return json.loads(MAIL_PROFILES_FILE.read_text(encoding='utf-8'))

    return {"profiles": [], "version": "1.0"}



def save_mail_profiles(data: dict):

    """Speichert Mail-Profile in JSON."""

    MAIL_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)

    MAIL_PROFILES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')



def load_false_positives() -> dict:

    """Laedt False-Positive Daten aus JSON."""

    if MAIL_FALSE_POSITIVES_FILE.exists():

        return json.loads(MAIL_FALSE_POSITIVES_FILE.read_text(encoding='utf-8'))

    return {"message_ids": [], "patterns": {}, "version": "1.0"}



def save_false_positives(data: dict):

    """Speichert False-Positive Daten in JSON."""

    MAIL_FALSE_POSITIVES_FILE.parent.mkdir(parents=True, exist_ok=True)

    MAIL_FALSE_POSITIVES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')





@app.get("/api/financial/profiles")

async def get_mail_profiles():

    """MAIL_001: Alle Mail-Profile laden."""

    try:

        # Kombiniere Provider-Profiles mit benutzerdefinierten

        profiles_data = load_mail_profiles()



        # Provider.json laden fuer System-Profile

        providers_file = BACH_DIR / "hub" / "_services" / "mail" / "providers.json"

        system_profiles = []

        if providers_file.exists():

            pdata = json.loads(providers_file.read_text(encoding='utf-8'))

            for p in pdata.get('providers', []):

                system_profiles.append({

                    "id": p.get('id', ''),

                    "name": p.get('name', ''),

                    "source": "system",

                    "enabled": True,

                    "sender_patterns": p.get('sender_patterns', []),

                    "subject_patterns": p.get('subject_patterns', []),

                    "blacklist": p.get('blacklist', []),

                    "body_must_contain": p.get('body_must_contain', []),

                    "body_must_not_contain": p.get('body_must_not_contain', []),

                    "category": p.get('category', 'sonstiges'),

                    "type": p.get('type', 'rechnung'),

                    "steuer_relevant": p.get('steuer_relevant', False),

                    "recurring": p.get('recurring', False)

                })



        # Benutzerdefinierte Profile

        user_profiles = profiles_data.get('profiles', [])

        for up in user_profiles:

            up["source"] = "user"



        return {

            "system_profiles": system_profiles,

            "user_profiles": user_profiles,

            "total": len(system_profiles) + len(user_profiles)

        }

    except Exception as e:

        return {"error": public_error_message(), "system_profiles": [], "user_profiles": []}





@app.post("/api/financial/profiles")

async def create_mail_profile(profile: MailProfileCreate):

    """MAIL_001: Neues benutzerdefiniertes Profil erstellen."""

    try:

        data = load_mail_profiles()



        # Pruefen ob ID bereits existiert

        existing = [p for p in data['profiles'] if p['id'] == profile.id]

        if existing:

            raise HTTPException(status_code=400, detail=f"Profil-ID '{profile.id}' existiert bereits")



        new_profile = {

            "id": profile.id,

            "name": profile.name,

            "enabled": profile.enabled,

            "sender_patterns": profile.sender_patterns,

            "subject_patterns": profile.subject_patterns,

            "blacklist": profile.blacklist,

            "body_must_contain": profile.body_must_contain,

            "body_must_not_contain": profile.body_must_not_contain,

            "category": profile.category,

            "type": profile.type,

            "steuer_relevant": profile.steuer_relevant,

            "recurring": profile.recurring,

            "created_at": datetime.now().isoformat()

        }



        data['profiles'].append(new_profile)

        save_mail_profiles(data)



        return {"success": True, "profile": new_profile}

    except HTTPException:

        raise

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.put("/api/financial/profiles/{profile_id}")

async def update_mail_profile(profile_id: str, profile: MailProfileCreate):

    """MAIL_001: Benutzerdefiniertes Profil aktualisieren."""

    try:

        data = load_mail_profiles()



        for i, p in enumerate(data['profiles']):

            if p['id'] == profile_id:

                data['profiles'][i] = {

                    "id": profile.id,

                    "name": profile.name,

                    "enabled": profile.enabled,

                    "sender_patterns": profile.sender_patterns,

                    "subject_patterns": profile.subject_patterns,

                    "blacklist": profile.blacklist,

                    "body_must_contain": profile.body_must_contain,

                    "body_must_not_contain": profile.body_must_not_contain,

                    "category": profile.category,

                    "type": profile.type,

                    "steuer_relevant": profile.steuer_relevant,

                    "recurring": profile.recurring,

                    "updated_at": datetime.now().isoformat()

                }

                save_mail_profiles(data)

                return {"success": True, "profile": data['profiles'][i]}



        raise HTTPException(status_code=404, detail=f"Profil '{profile_id}' nicht gefunden")

    except HTTPException:

        raise

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.delete("/api/financial/profiles/{profile_id}")

async def delete_mail_profile(profile_id: str):

    """MAIL_001: Benutzerdefiniertes Profil loeschen."""

    try:

        data = load_mail_profiles()



        original_count = len(data['profiles'])

        data['profiles'] = [p for p in data['profiles'] if p['id'] != profile_id]



        if len(data['profiles']) == original_count:

            raise HTTPException(status_code=404, detail=f"Profil '{profile_id}' nicht gefunden")



        save_mail_profiles(data)

        return {"success": True, "deleted": profile_id}

    except HTTPException:

        raise

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.get("/api/financial/false-positives")

async def get_false_positives():

    """MAIL_002: Alle False-Positives laden."""

    try:

        data = load_false_positives()

        return data

    except Exception as e:

        return {"error": public_error_message(), "message_ids": [], "patterns": {}}





@app.post("/api/financial/false-positives")

async def add_false_positive(fp: FalsePositiveCreate):

    """MAIL_002/003: E-Mail als False-Positive markieren."""

    try:

        data = load_false_positives()



        # Message-ID speichern (wird nie wieder gematched)

        if fp.message_id and fp.message_id not in data['message_ids']:

            data['message_ids'].append(fp.message_id)



        # MAIL_003: Optional zur Blacklist hinzufuegen

        if fp.add_to_blacklist and fp.blacklist_terms:

            # Extrahiere Domain aus Sender

            sender_domain = ""

            if "@" in fp.sender:

                sender_domain = fp.sender.split("@")[-1].split(">")[0].lower()



            if sender_domain not in data['patterns']:

                data['patterns'][sender_domain] = {

                    "blocked_subjects": [],

                    "blocked_senders": []

                }



            for term in fp.blacklist_terms:

                if term not in data['patterns'][sender_domain]['blocked_subjects']:

                    data['patterns'][sender_domain]['blocked_subjects'].append(term)



        # Log-Eintrag

        if 'history' not in data:

            data['history'] = []

        data['history'].append({

            "message_id": fp.message_id,

            "sender": fp.sender,

            "subject": fp.subject,

            "reason": fp.reason,

            "added_at": datetime.now().isoformat()

        })



        save_false_positives(data)



        return {"success": True, "total_blocked": len(data['message_ids'])}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.delete("/api/financial/false-positives/{message_id}")

async def remove_false_positive(message_id: str):

    """MAIL_002: False-Positive entfernen."""

    try:

        data = load_false_positives()



        if message_id in data['message_ids']:

            data['message_ids'].remove(message_id)

            save_false_positives(data)

            return {"success": True, "removed": message_id}



        raise HTTPException(status_code=404, detail=f"Message-ID '{message_id}' nicht gefunden")

    except HTTPException:

        raise

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.post("/api/financial/profiles/test")

async def test_mail_profile(req: ProfileTestRequest):

    """MAIL_005: Testet eine E-Mail gegen alle Profile."""

    try:

        # Lade alle Profile (System + User)

        profiles_resp = await get_mail_profiles()

        all_profiles = profiles_resp.get('system_profiles', []) + profiles_resp.get('user_profiles', [])



        sender_lower = req.sender.lower()

        subject_lower = req.subject.lower()

        body_lower = req.body.lower() if req.body else ""



        matches = []



        for profile in all_profiles:

            if not profile.get('enabled', True):

                continue



            score = 0

            match_details = []



            # Sender-Match

            for pattern in profile.get('sender_patterns', []):

                if pattern != '*' and pattern.lower() in sender_lower:

                    score += 10

                    match_details.append(f"Sender: '{pattern}' (+10)")



            # Subject-Match

            for pattern in profile.get('subject_patterns', []):

                if pattern.lower() in subject_lower:

                    score += 5

                    match_details.append(f"Subject: '{pattern}' (+5)")



            # Body-Match (schwach)

            if body_lower:

                for pattern in profile.get('sender_patterns', []):

                    if pattern != '*' and pattern.lower() in body_lower:

                        score += 2

                        match_details.append(f"Body-Sender: '{pattern}' (+2)")



            # Blacklist pruefen

            blocked = False

            for term in profile.get('blacklist', []):

                if term.lower() in subject_lower or term.lower() in body_lower:

                    blocked = True

                    match_details.append(f"BLOCKED: Blacklist '{term}'")

                    break



            # body_must_contain pruefen

            if profile.get('body_must_contain') and body_lower:

                found_any = any(t.lower() in body_lower for t in profile['body_must_contain'])

                if not found_any:

                    blocked = True

                    match_details.append("BLOCKED: body_must_contain nicht erfuellt")



            # body_must_not_contain pruefen

            for term in profile.get('body_must_not_contain', []):

                if body_lower and term.lower() in body_lower:

                    blocked = True

                    match_details.append(f"BLOCKED: body_must_not_contain '{term}'")

                    break



            if score >= 5:

                matches.append({

                    "profile_id": profile['id'],

                    "profile_name": profile['name'],

                    "source": profile.get('source', 'system'),

                    "score": score,

                    "blocked": blocked,

                    "would_match": score >= 5 and not blocked,

                    "details": match_details,

                    "category": profile.get('category'),

                    "steuer_relevant": profile.get('steuer_relevant', False)

                })



        # Sortiere nach Score

        matches.sort(key=lambda x: x['score'], reverse=True)



        # Bester Match

        best_match = None

        for m in matches:

            if m['would_match']:

                best_match = m

                break



        return {

            "success": True,

            "best_match": best_match,

            "all_matches": matches,

            "total_tested": len(all_profiles)

        }

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.post("/api/financial/profiles/import")

async def import_profiles_from_universal_mail():

    """MAIL_004: Importiert Profile aus UniversalInvoiceMail Config."""

    try:

        # Suche UniversalInvoiceMail Config

        search_paths = [

            Path.home() / "OneDrive" / ".SOFTWARE" / "TOOLS" / "Mail" / "UniversalInvoiceMail",

            BACH_DIR / "tools" / "mail",

            Path.home() / "UniversalInvoiceMail"

        ]



        config_file = None

        for path in search_paths:

            candidates = [

                path / "config.json",

                path / "provider_profiles.json",

                path / "profiles.json"

            ]

            for c in candidates:

                if c.exists():

                    config_file = c

                    break

            if config_file:

                break



        if not config_file:

            return {"success": False, "error": "UniversalInvoiceMail Config nicht gefunden", "searched": [str(p) for p in search_paths]}



        # Config laden

        external_config = json.loads(config_file.read_text(encoding='utf-8'))



        # Profile extrahieren (Format kann variieren)

        imported_profiles = []



        if 'providers' in external_config:

            providers = external_config['providers']

        elif 'profiles' in external_config:

            providers = external_config['profiles']

        else:

            providers = [external_config] if 'id' in external_config else []



        data = load_mail_profiles()

        existing_ids = {p['id'] for p in data['profiles']}



        for p in providers:

            profile_id = p.get('id', p.get('name', '').lower().replace(' ', '_'))



            if profile_id in existing_ids:

                continue  # Ueberspringe bereits existierende



            new_profile = {

                "id": profile_id,

                "name": p.get('name', profile_id),

                "enabled": p.get('enabled', True),

                "sender_patterns": p.get('sender_patterns', p.get('selectors', {}).get('sender_patterns', [])),

                "subject_patterns": p.get('subject_patterns', p.get('selectors', {}).get('subject_patterns', [])),

                "blacklist": p.get('blacklist', p.get('anti_selectors', {}).get('blacklist', [])),

                "body_must_contain": p.get('body_must_contain', p.get('selectors', {}).get('body_must_contain', [])),

                "body_must_not_contain": p.get('body_must_not_contain', p.get('anti_selectors', {}).get('body_must_not_contain', [])),

                "category": p.get('category', p.get('classification', {}).get('category', 'sonstiges')),

                "type": p.get('type', p.get('classification', {}).get('type', 'rechnung')),

                "steuer_relevant": p.get('steuer_relevant', p.get('classification', {}).get('steuer_relevant', False)),

                "recurring": p.get('recurring', p.get('classification', {}).get('is_recurring', False)),

                "imported_from": str(config_file),

                "imported_at": datetime.now().isoformat()

            }



            data['profiles'].append(new_profile)

            imported_profiles.append(new_profile)



        if imported_profiles:

            save_mail_profiles(data)



        return {

            "success": True,

            "imported": len(imported_profiles),

            "profiles": imported_profiles,

            "source": str(config_file)

        }

    except Exception as e:

        return {"success": False, "error": public_error_message()}





# ═══════════════════════════════════════════════════════════════

# API ROUTES - FINANCIAL CONTRACTS & INSURANCES (Task #538)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/financial/contracts")

async def get_contracts():

    """FIN_002: Alle Vertraege/Abos laden."""

    try:

        conn = get_user_db()

        conn.row_factory = sqlite3.Row

        cursor = conn.cursor()

        cursor.execute("SELECT * FROM fin_contracts ORDER BY naechste_zahlung")

        rows = cursor.fetchall()

        contracts = [dict(row) for row in rows]

        conn.close()

        return {"success": True, "contracts": contracts, "count": len(contracts)}

    except Exception as e:

        return {"success": False, "error": public_error_message(), "contracts": []}



@app.post("/api/financial/contracts")

async def add_contract(contract: ContractModel):

    """FIN_002: Neuen Vertrag/Abo anlegen."""

    conn = None
    try:

        conn = get_user_db()

        cursor = conn.cursor()

        data = contract.dict()

        columns = ", ".join(data.keys())

        placeholders = ", ".join([":" + k for k in data.keys()])

        cursor.execute(f"INSERT INTO fin_contracts ({columns}) VALUES ({placeholders})", data)

        conn.commit()

        new_id = cursor.lastrowid

        return {"success": True, "id": new_id}

    except Exception as e:

        return {"success": False, "error": public_error_message()}

    finally:
        if conn:
            conn.close()



@app.put("/api/financial/contracts/{contract_id}")

async def update_contract(contract_id: int, contract: ContractModel):

    """FIN_002: Vertrag/Abo aktualisieren."""

    conn = None
    try:

        conn = get_user_db()

        cursor = conn.cursor()

        data = contract.dict()

        set_clause = ", ".join([f"{k} = :{k}" for k in data.keys()])

        data['id_param'] = contract_id

        cursor.execute(f"UPDATE fin_contracts SET {set_clause} WHERE id = :id_param", data)

        conn.commit()

        return {"success": True}

    except Exception as e:

        return {"success": False, "error": public_error_message()}

    finally:
        if conn:
            conn.close()



@app.delete("/api/financial/contracts/{contract_id}")

async def delete_contract(contract_id: int):

    """FIN_002: Vertrag/Abo loeschen."""

    try:

        conn = get_user_db()

        cursor = conn.cursor()

        cursor.execute("DELETE FROM fin_contracts WHERE id = ?", (contract_id,))

        conn.commit()

        conn.close()

        return {"success": True}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.get("/api/financial/insurances")

async def get_insurances():

    """FIN_002: Alle Versicherungen laden."""

    try:

        conn = get_user_db()

        conn.row_factory = sqlite3.Row

        cursor = conn.cursor()

        cursor.execute("SELECT * FROM fin_insurances ORDER BY anbieter")

        rows = cursor.fetchall()

        insurances = [dict(row) for row in rows]

        conn.close()

        

        # Stats berechnen

        total = len(insurances)

        yearly = sum(float(i.get('beitrag', 0) or 0) * 12 for i in insurances if i.get('zahlweise') == 'monatlich')

        yearly += sum(float(i.get('beitrag', 0) or 0) for i in insurances if i.get('zahlweise') == 'jaehrlich')

        

        return {"success": True, "insurances": insurances, "count": total, "yearly_cost": yearly}

    except Exception as e:

        return {"success": False, "error": public_error_message(), "insurances": []}



@app.get("/api/financial/deadlines")

async def get_financial_deadlines():

    """FIN_002c: Gemeinsame Fristenliste für Versicherungen und Vertraege."""

    try:

        from datetime import date, timedelta

        conn = get_user_db()

        conn.row_factory = sqlite3.Row

        cursor = conn.cursor()

        

        deadlines = []

        today = date.today()

        warning_limit = today + timedelta(days=60) # 60 Tage Vorlauf



        # 1. Versicherungen

        cursor.execute("SELECT id, anbieter, tarif_name, sparte, ablauf_datum, kuendigungsfrist_monate FROM fin_insurances WHERE status = 'aktiv'")

        for row in cursor.fetchall():

            if row['ablauf_datum']:

                ablauf = date.fromisoformat(row['ablauf_datum'])

                frist_tage = row['kuendigungsfrist_monate'] * 30

                frist_datum = ablauf - timedelta(days=frist_tage)

                

                if frist_datum <= warning_limit:

                    deadlines.append({

                        "type": "versicherung",

                        "id": row['id'],

                        "name": f"{row['anbieter']} - {row['sparte']}",

                        "deadline": frist_datum.isoformat(),

                        "ablauf": ablauf.isoformat(),

                        "days_left": (frist_datum - today).days,

                        "severity": "high" if (frist_datum - today).days < 14 else "medium"

                    })



        # 2. Vertraege

        cursor.execute("SELECT id, name, anbieter, ablauf_datum, kuendigungsfrist_tage FROM fin_contracts WHERE kuendigungs_status = 'aktiv'")

        for row in cursor.fetchall():

            if row['ablauf_datum']:

                ablauf = date.fromisoformat(row['ablauf_datum'])

                frist_tage = row['kuendigungsfrist_tage'] or 30

                frist_datum = ablauf - timedelta(days=frist_tage)

                

                if frist_datum <= warning_limit:

                    deadlines.append({

                        "type": "vertrag",

                        "id": row['id'],

                        "name": row['name'],

                        "deadline": frist_datum.isoformat(),

                        "ablauf": ablauf.isoformat(),

                        "days_left": (frist_datum - today).days,

                        "severity": "high" if (frist_datum - today).days < 14 else "medium"

                    })



        conn.close()

        deadlines.sort(key=lambda x: x['days_left'])

        

        return {"success": True, "deadlines": deadlines, "count": len(deadlines)}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/financial/insurances")

async def add_insurance(ins: InsuranceModel):

    """FIN_001: Neue Versicherung anlegen."""

    try:

        conn = get_user_db()

        cursor = conn.cursor()

        data = ins.dict()

        columns = ", ".join(data.keys())

        placeholders = ", ".join([":" + k for k in data.keys()])

        cursor.execute(f"INSERT INTO fin_insurances ({columns}) VALUES ({placeholders})", data)

        conn.commit()

        new_id = cursor.lastrowid

        conn.close()

        return {"success": True, "id": new_id}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.put("/api/financial/insurances/{ins_id}")

async def update_insurance(ins_id: int, ins: InsuranceModel):

    """FIN_001: Versicherung aktualisieren."""

    try:

        conn = get_user_db()

        cursor = conn.cursor()

        data = ins.dict()

        set_clause = ", ".join([f"{k} = :{k}" for k in data.keys()])

        data['id_param'] = ins_id

        cursor.execute(f"UPDATE fin_insurances SET {set_clause} WHERE id = :id_param", data)

        conn.commit()

        conn.close()

        return {"success": True}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.delete("/api/financial/insurances/{ins_id}")

async def delete_insurance(ins_id: int):

    """FIN_001: Versicherung loeschen."""

    try:

        conn = get_user_db()

        cursor = conn.cursor()

        cursor.execute("DELETE FROM fin_insurances WHERE id = ?", (ins_id,))

        conn.commit()

        conn.close()

        return {"success": True}

    except Exception as e:

        return {"success": False, "error": public_error_message()}


# ═══════════════════════════════════════════════════════════════
# API ROUTES - USECASES (v1.1.84 - Task 790)
# ═══════════════════════════════════════════════════════════════

@app.get("/usecases", response_class=HTMLResponse)
async def usecases_page():
    """Usecase Verwaltung."""
    astro_uc = ASTRO_DIST_DIR / "governance" / "usecases.html"
    if astro_uc.exists():
        return FileResponse(astro_uc)
    usecases_file = TEMPLATES_DIR / "usecases.html"
    if usecases_file.exists():
        return FileResponse(usecases_file)
    raise HTTPException(status_code=404, detail="Template usecases.html nicht gefunden")



@app.get("/api/usecases")
async def get_usecases():
    """Alle Usecases laden mit Stats."""
    try:
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usecases ORDER BY title")
        rows = cursor.fetchall()
        usecases = [dict(row) for row in rows]

        # Stats berechnen
        total = len(usecases)
        pass_count = len([u for u in usecases if u.get('test_result') == 'pass'])
        fail_count = len([u for u in usecases if u.get('test_result') == 'fail'])
        pending = total - pass_count - fail_count

        conn.close()

        return {
            "success": True,
            "usecases": usecases,
            "stats": {
                "total": total,
                "pass": pass_count,
                "fail": fail_count,
                "pending": pending
            }
        }
    except Exception as e:
        return {"success": False, "error": public_error_message(), "usecases": []}


@app.get("/api/usecases/{usecase_id}")
async def get_usecase(usecase_id: int):
    """Einzelnen Usecase laden."""
    try:
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"success": True, "usecase": dict(row)}
        return {"success": False, "error": "Nicht gefunden"}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/usecases")
async def add_usecase(request: Request):
    """Neuen Usecase anlegen."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usecases (title, description, workflow_name, test_input, expected_output, created_by)
            VALUES (?, ?, ?, ?, ?, 'gui')
        """, (
            data.get('title'),
            data.get('description'),
            data.get('workflow_name'),
            data.get('test_input'),
            data.get('expected_output')
        ))
        conn.commit()
        conn.close()
        return {"success": True, "id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.put("/api/usecases/{usecase_id}")
async def update_usecase(usecase_id: int, request: Request):
    """Usecase aktualisieren."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE usecases SET
                title = ?, description = ?, workflow_name = ?,
                test_input = ?, expected_output = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data.get('title'),
            data.get('description'),
            data.get('workflow_name'),
            data.get('test_input'),
            data.get('expected_output'),
            usecase_id
        ))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.delete("/api/usecases/{usecase_id}")
async def delete_usecase(usecase_id: int):
    """Usecase loeschen."""
    try:
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM usecases WHERE id = ?", (usecase_id,))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/usecases/{usecase_id}/test")
async def test_usecase(usecase_id: int):
    """Usecase testen (simuliert)."""
    try:
        from datetime import datetime
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,))
        uc = cursor.fetchone()
        if not uc:
            conn.close()
            return {"success": False, "error": "Nicht gefunden"}

        # Test-Logik: Pruefe Workflow-Datei + expected_output
        workflow_name = uc['workflow_name'] or ''
        expected = uc['expected_output'] if 'expected_output' in uc.keys() else ''
        test_input = uc['test_input'] if 'test_input' in uc.keys() else ''

        checks = []
        score_parts = 0
        score_max = 0

        # Check 1: Workflow zugewiesen?
        score_max += 1
        if workflow_name:
            checks.append("[OK] Workflow zugewiesen: " + workflow_name)
            score_parts += 1
        else:
            checks.append("[FEHLT] Kein Workflow zugewiesen")

        # Check 2: Workflow-Datei existiert?
        if workflow_name:
            score_max += 1
            try:
                wf_path = resolve_workflow_file(workflow_name)
            except HTTPException:
                wf_path = None
            if wf_path and wf_path.exists():
                checks.append(f"[OK] Workflow-Datei gefunden: {wf_path.name}")
                score_parts += 1
            else:
                checks.append(f"[FEHLT] Workflow-Datei nicht gefunden: {workflow_name}")

        # Check 3: Test-Input definiert?
        score_max += 1
        if test_input and str(test_input).strip():
            checks.append("[OK] Test-Input definiert")
            score_parts += 1
        else:
            checks.append("[FEHLT] Kein Test-Input definiert")

        # Check 4: Expected-Output definiert?
        score_max += 1
        if expected and str(expected).strip():
            checks.append("[OK] Expected-Output definiert")
            score_parts += 1
        else:
            checks.append("[FEHLT] Kein Expected-Output definiert")

        test_score = int((score_parts / score_max) * 100) if score_max > 0 else 0
        test_result = 'pass' if test_score >= 75 else ('fail' if test_score > 0 else 'pending')

        # Ergebnis speichern
        cursor.execute("""
            UPDATE usecases SET
                last_tested = ?, test_result = ?, test_score = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), test_result, test_score, usecase_id))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "title": uc['title'],
            "result": test_result,
            "score": test_score,
            "output": "\n".join(checks) + f"\n\nScore: {test_score}% ({score_parts}/{score_max})"
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/usecases/test-all")
async def test_all_usecases():
    """Alle Usecases testen."""
    try:
        from datetime import datetime
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM usecases")
        usecases = cursor.fetchall()

        results = []
        passed = 0
        failed = 0

        for uc in usecases:
            workflow_name = uc['workflow_name'] or ''
            expected = uc['expected_output'] if 'expected_output' in uc.keys() else ''
            test_input = uc['test_input'] if 'test_input' in uc.keys() else ''

            score_parts = 0
            score_max = 4

            if workflow_name:
                score_parts += 1
                try:
                    wf_path = resolve_workflow_file(workflow_name)
                except HTTPException:
                    wf_path = None
                if wf_path and wf_path.exists():
                    score_parts += 1
            if test_input and str(test_input).strip():
                score_parts += 1
            if expected and str(expected).strip():
                score_parts += 1

            test_score = int((score_parts / score_max) * 100) if score_max > 0 else 0
            test_result = 'pass' if test_score >= 75 else ('fail' if test_score > 0 else 'pending')

            cursor.execute("""
                UPDATE usecases SET last_tested = ?, test_result = ?, test_score = ? WHERE id = ?
            """, (datetime.now().isoformat(), test_result, test_score, uc['id']))

            results.append({"id": uc['id'], "title": uc['title'], "result": test_result})
            if test_result == 'pass':
                passed += 1
            else:
                failed += 1

        conn.commit()
        conn.close()

        return {
            "success": True,
            "total": len(usecases),
            "passed": passed,
            "failed": failed,
            "results": results
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/usecases/{usecase_id}/execute")
async def execute_usecase(usecase_id: int, request: Request):
    """Usecase ausfuehren (simuliert)."""
    try:
        data = await request.json()
        user_input = data.get('input', '')

        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,))
        uc = cursor.fetchone()
        conn.close()

        if not uc:
            return {"success": False, "error": "Nicht gefunden"}

        # Simulierte Ausfuehrung
        output = f"=== Usecase: {uc['title']} ===\n\n"
        output += f"Eingabe: {user_input}\n\n"
        output += f"Workflow: {uc['workflow_name'] or '(kein Workflow definiert)'}\n\n"
        output += "Hinweis: Die tatsaechliche Ausfuehrung erfolgt ueber 'bach run' im Terminal.\n"
        output += f"Befehl: bach run {uc['workflow_name']} \"{user_input}\""

        return {"success": True, "output": output}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


# ═══════════════════════════════════════════════════════════════
# API ROUTES - CONTACTS (v1.1.84 - Task 789)
# ═══════════════════════════════════════════════════════════════

@app.get("/kontakte", response_class=HTMLResponse)
async def kontakte_page():
    """Kontakte Verwaltung."""
    kontakte_file = TEMPLATES_DIR / "kontakte.html"
    if kontakte_file.exists():
        return FileResponse(kontakte_file)
    raise HTTPException(status_code=404, detail="Template kontakte.html nicht gefunden")


@app.get("/api/contacts")
async def get_contacts(category: str = None):
    """Alle Kontakte laden mit Stats."""
    try:
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM contacts WHERE is_active = 1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY COALESCE(last_name, name) ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        contacts = [dict(row) for row in rows]

        # Stats berechnen
        cursor.execute("SELECT COUNT(*) FROM contacts WHERE is_active = 1")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(category,'sonstige') as cat, COUNT(*) as cnt FROM contacts WHERE is_active = 1 GROUP BY cat ORDER BY cnt DESC")
        by_category = {r[0]: r[1] for r in cursor.fetchall()}

        conn.close()

        return {
            "success": True,
            "contacts": contacts,
            "stats": {
                "total": total,
                "by_category": by_category,
                "health": by_category.get("arzt", 0),
                "business": by_category.get("beruflich", 0),
                "personal": by_category.get("privat", 0),
            }
        }
    except Exception as e:
        return {"success": False, "error": public_error_message(), "contacts": []}


@app.get("/api/contacts/{contact_id}")
async def get_contact(contact_id: int):
    """Einzelnen Kontakt laden."""
    try:
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"success": True, "contact": dict(row)}
        return {"success": False, "error": "Nicht gefunden"}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/contacts")
async def add_contact(request: Request):
    """Neuen Kontakt anlegen."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO contacts (name, first_name, last_name, category, subcategory,
                                  organization, position, phone, phone_mobile, email,
                                  street, city, zip_code, website, birthday, tags, notes, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            data.get('name'),
            data.get('first_name'),
            data.get('last_name'),
            data.get('category', 'Sonstiges'),
            data.get('subcategory'),
            data.get('organization'),
            data.get('position'),
            data.get('phone'),
            data.get('phone_mobile'),
            data.get('email'),
            data.get('street'),
            data.get('city'),
            data.get('zip_code'),
            data.get('website'),
            data.get('birthday'),
            data.get('tags'),
            data.get('notes')
        ))
        conn.commit()
        conn.close()
        return {"success": True, "id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.put("/api/contacts/{contact_id}")
async def update_contact(contact_id: int, request: Request):
    """Kontakt aktualisieren."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE contacts SET
                name = ?, first_name = ?, last_name = ?, category = ?, subcategory = ?,
                organization = ?, position = ?, phone = ?, phone_mobile = ?, email = ?,
                street = ?, city = ?, zip_code = ?, website = ?, birthday = ?,
                tags = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data.get('name'),
            data.get('first_name'),
            data.get('last_name'),
            data.get('category'),
            data.get('subcategory'),
            data.get('organization'),
            data.get('position'),
            data.get('phone'),
            data.get('phone_mobile'),
            data.get('email'),
            data.get('street'),
            data.get('city'),
            data.get('zip_code'),
            data.get('website'),
            data.get('birthday'),
            data.get('tags'),
            data.get('notes'),
            contact_id
        ))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.delete("/api/contacts/{contact_id}")
async def delete_contact(contact_id: int):
    """Kontakt loeschen (soft delete)."""
    try:
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE contacts SET is_active = 0 WHERE id = ?", (contact_id,))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.get("/api/contacts/export")
async def export_contacts():
    """Kontakte als TXT exportieren."""
    try:
        from datetime import date
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contacts WHERE is_active = 1 ORDER BY category, COALESCE(last_name, name)")
        rows = cursor.fetchall()
        conn.close()

        output_dir = BACH_DIR / "user" / "finanzen"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "kontakte_uebersicht.txt"

        lines = []
        lines.append("=" * 70)
        lines.append("KONTAKTE-UEBERSICHT")
        lines.append(f"Erstellt: {date.today().strftime('%d.%m.%Y')}")
        lines.append("=" * 70)

        current_cat = None
        for row in rows:
            if row['category'] != current_cat:
                current_cat = row['category']
                lines.append(f"\n--- {current_cat or 'Ohne Kategorie'} ---\n")

            name = row['name'] or f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
            lines.append(f"  {name}")
            if row['organization']:
                lines.append(f"        {row['position'] + ' - ' if row['position'] else ''}{row['organization']}")
            if row['phone']:
                lines.append(f"        Tel: {row['phone']}")
            if row['email']:
                lines.append(f"        E-Mail: {row['email']}")
            if row['city']:
                lines.append(f"        Adresse: {row['street'] + ', ' if row['street'] else ''}{row['zip_code'] or ''} {row['city']}")
            lines.append("")

        lines.append("=" * 70)
        lines.append(f"Gesamt: {len(rows)} Kontakte")

        write_private_text_file(output_file, '\n'.join(lines))

        return {"success": True, "file": str(output_file), "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


# ═══════════════════════════════════════════════════════════════
# API ROUTES - ROUTINES (v1.1.84 - Task 788)
# ═══════════════════════════════════════════════════════════════

@app.get("/routinen", response_class=HTMLResponse)
async def routinen_page():
    """Routinen Dashboard."""
    routinen_file = TEMPLATES_DIR / "routinen.html"
    if routinen_file.exists():
        return FileResponse(routinen_file)
    raise HTTPException(status_code=404, detail="Template routinen.html nicht gefunden")


@app.get("/api/routines")
async def get_routines(category: str = None, interval: str = None):
    """Alle Routinen laden mit Stats."""
    try:
        from datetime import date, timedelta
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        today = date.today().isoformat()

        # Query aufbauen
        query = "SELECT * FROM routines WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if interval:
            query += " AND interval_type = ?"
            params.append(interval)
        query += " ORDER BY priority ASC, name ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        routines = []
        due_today = []
        overdue_count = 0
        active_count = 0

        for row in rows:
            r = dict(row)
            r['is_due_today'] = False
            r['is_overdue'] = False

            if r['is_active']:
                active_count += 1
                if r['next_due_at']:
                    if r['next_due_at'] <= today:
                        if r['next_due_at'] < today:
                            r['is_overdue'] = True
                            overdue_count += 1
                        else:
                            r['is_due_today'] = True
                        due_today.append(r)

            routines.append(r)

        conn.close()

        return {
            "success": True,
            "routines": routines,
            "due_today": due_today,
            "stats": {
                "total": len(routines),
                "active": active_count,
                "due_today": len([r for r in due_today if r['is_due_today']]),
                "overdue": overdue_count
            }
        }
    except Exception as e:
        return {"success": False, "error": public_error_message(), "routines": []}


@app.get("/api/routines/{routine_id}")
async def get_routine(routine_id: int):
    """Einzelne Routine laden."""
    try:
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM routines WHERE id = ?", (routine_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"success": True, "routine": dict(row)}
        return {"success": False, "error": "Nicht gefunden"}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


def _ensure_routine_assigned_agent_column(conn: sqlite3.Connection):
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(routines)").fetchall()}
        if cols and "assigned_agent" not in cols:
            conn.execute("ALTER TABLE routines ADD COLUMN assigned_agent TEXT")
            conn.commit()
    except (sqlite3.Error, OSError):
        pass


@app.post("/api/routines")
async def add_routine(request: Request):
    """Neue Routine anlegen."""
    _refuse_if_foreign_domain("routine", "GUI POST /api/routines")
    try:
        from datetime import date, timedelta
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        _ensure_routine_assigned_agent_column(conn)

        # next_due_at berechnen
        today = date.today()
        next_due = today.isoformat()

        cursor.execute("""
            INSERT INTO routines (name, description, category, priority, interval_type,
                                  interval_value, specific_day, duration_minutes, next_due_at, is_active, assigned_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            data.get('name'),
            data.get('description'),
            data.get('category', 'Haushalt'),
            data.get('priority', 2),
            data.get('interval_type', 'woechentlich'),
            data.get('interval_value', 1),
            data.get('specific_day'),
            data.get('duration_minutes'),
            next_due,
            data.get('assigned_agent')
        ))
        conn.commit()
        conn.close()
        return {"success": True, "id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.put("/api/routines/{routine_id}")
async def update_routine(routine_id: int, request: Request):
    """Routine aktualisieren."""
    _refuse_if_foreign_domain("routine", "GUI PUT /api/routines/{id}")
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        _ensure_routine_assigned_agent_column(conn)
        cursor.execute("""
            UPDATE routines SET
                name = ?, description = ?, category = ?, priority = ?,
                interval_type = ?, interval_value = ?, specific_day = ?,
                duration_minutes = ?, assigned_agent = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data.get('name'),
            data.get('description'),
            data.get('category'),
            data.get('priority', 2),
            data.get('interval_type'),
            data.get('interval_value', 1),
            data.get('specific_day'),
            data.get('duration_minutes'),
            data.get('assigned_agent'),
            routine_id
        ))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/routines/{routine_id}/complete")
async def complete_routine(routine_id: int):
    """Routine als erledigt markieren und naechstes Datum berechnen."""
    _refuse_if_foreign_domain("routine", "GUI POST /api/routines/{id}/complete")
    try:
        from datetime import date, timedelta
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Routine laden
        cursor.execute("SELECT interval_type, interval_value FROM routines WHERE id = ?", (routine_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": "Nicht gefunden"}

        # Naechstes Datum berechnen
        today = date.today()
        interval_type = row['interval_type']
        interval_value = row['interval_value'] or 1

        if interval_type == 'taeglich':
            next_due = today + timedelta(days=interval_value)
        elif interval_type == 'woechentlich':
            next_due = today + timedelta(weeks=interval_value)
        elif interval_type == 'monatlich':
            next_month = today.month + interval_value
            next_year = today.year + (next_month - 1) // 12
            next_month = ((next_month - 1) % 12) + 1
            try:
                next_due = date(int(next_year), int(next_month), today.day)
            except ValueError:
                next_due = date(int(next_year), int(next_month) % 12 + 1, 1) - timedelta(days=1)
        elif interval_type == 'jaehrlich':
            try:
                next_due = date(today.year + interval_value, today.month, today.day)
            except ValueError:
                next_due = date(today.year + interval_value, today.month, 28)
        else:
            next_due = today + timedelta(days=7)

        cursor.execute("""
            UPDATE routines SET
                last_completed_at = ?,
                next_due_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (today.isoformat(), next_due.isoformat(), routine_id))

        conn.commit()
        conn.close()
        return {"success": True, "next_due": next_due.isoformat()}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.delete("/api/routines/{routine_id}")
async def delete_routine(routine_id: int):
    """Routine loeschen."""
    _refuse_if_foreign_domain("routine", "GUI DELETE /api/routines/{id}")
    try:
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.get("/api/routines/export")
async def export_routines():
    """Routinen als TXT exportieren."""
    try:
        import os
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM routines WHERE is_active = 1 ORDER BY category, name")
        rows = cursor.fetchall()
        conn.close()

        output_dir = BACH_DIR / "user" / "finanzen"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "routinen_uebersicht.txt"

        lines = []
        lines.append("=" * 70)
        lines.append("ROUTINEN-UEBERSICHT")
        lines.append(f"Erstellt: {date.today().strftime('%d.%m.%Y')}")
        lines.append("=" * 70)
        lines.append("")

        current_cat = None
        for row in rows:
            if row['category'] != current_cat:
                current_cat = row['category']
                lines.append(f"\n--- {current_cat or 'Ohne Kategorie'} ---\n")

            interval_str = f"{row['interval_value'] or 1}x {row['interval_type']}"
            lines.append(f"  [{row['interval_type'][:3].upper()}] {row['name']}")
            if row['description']:
                lines.append(f"        Beschreibung: {row['description']}")
            lines.append(f"        Intervall: {interval_str}")
            if row['next_due_at']:
                lines.append(f"        Naechste: {row['next_due_at']}")
            lines.append("")

        lines.append("=" * 70)
        lines.append(f"Gesamt: {len(rows)} aktive Routinen")

        write_private_text_file(output_file, '\n'.join(lines))

        return {"success": True, "file": str(output_file), "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


# ═══════════════════════════════════════════════════════════════
# API ROUTES - BANK ACCOUNTS (v1.1.84 - Task 783)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/financial/bank-accounts")
async def get_bank_accounts():
    """Alle Bankkonten laden."""
    try:
        accounts = _account_store().list_accounts()
        return {"success": True, "accounts": accounts}
    except Exception as e:
        return {"success": False, "error": public_error_message(), "accounts": []}


@app.post("/api/financial/bank-accounts")
async def add_bank_account(request: Request):
    """Neues Bankkonto anlegen."""
    try:
        data = await request.json()
        account_id = _account_store().create_account(
            data.get('name'),
            bank_name=data.get('bank_name'),
            iban=data.get('iban'),
            bic=data.get('bic'),
            account_type=data.get('account_type', 'girokonto'),
            notes=data.get('notes'),
        )
        return {"success": True, "id": account_id}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.put("/api/financial/bank-accounts/{account_id}")
async def update_bank_account(account_id: int, request: Request):
    """Bankkonto aktualisieren."""
    try:
        data = await request.json()
        _account_store().update_account(
            account_id,
            data.get('name'),
            bank_name=data.get('bank_name'),
            iban=data.get('iban'),
            bic=data.get('bic'),
            account_type=data.get('account_type', 'girokonto'),
            notes=data.get('notes'),
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.delete("/api/financial/bank-accounts/{account_id}")
async def delete_bank_account(account_id: int):
    """Bankkonto loeschen."""
    try:
        _account_store().delete_account(account_id)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


# ═══════════════════════════════════════════════════════════════
# API ROUTES - CREDITS (v1.1.85 - Credits Management)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/financial/credits")
async def get_credits():
    """Alle Kredite laden."""
    try:
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM credits ORDER BY status ASC, name")
        rows = cursor.fetchall()
        credits = [dict(row) for row in rows]
        conn.close()
        return {"success": True, "credits": credits}
    except Exception as e:
        return {"success": False, "error": public_error_message(), "credits": []}


@app.post("/api/financial/credits")
async def add_credit(request: Request):
    """Neuen Kredit anlegen."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO credits (name, purpose, bank_name, original_amount, remaining_amount,
                                interest_rate, payment_amount, start_date, end_date, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('name'),
            data.get('purpose'),
            data.get('bank_name'),
            data.get('original_amount'),
            data.get('remaining_amount'),
            data.get('interest_rate'),
            data.get('payment_amount'),
            data.get('start_date'),
            data.get('end_date'),
            data.get('status', 'active'),
            data.get('notes')
        ))
        conn.commit()
        conn.close()
        return {"success": True, "id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.put("/api/financial/credits/{credit_id}")
async def update_credit(credit_id: int, request: Request):
    """Kredit aktualisieren."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE credits SET
                name = ?, purpose = ?, bank_name = ?, original_amount = ?,
                remaining_amount = ?, interest_rate = ?, payment_amount = ?,
                start_date = ?, end_date = ?, status = ?, notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data.get('name'),
            data.get('purpose'),
            data.get('bank_name'),
            data.get('original_amount'),
            data.get('remaining_amount'),
            data.get('interest_rate'),
            data.get('payment_amount'),
            data.get('start_date'),
            data.get('end_date'),
            data.get('status', 'active'),
            data.get('notes'),
            credit_id
        ))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.delete("/api/financial/credits/{credit_id}")
async def delete_credit(credit_id: int):
    """Kredit loeschen."""
    try:
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM credits WHERE id = ?", (credit_id,))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


# ═══════════════════════════════════════════════════════════════

# API ROUTES - INBOX SCANNER (Phase 10)

# ═══════════════════════════════════════════════════════════════



INBOX_FOLDERS_FILE = DATA_DIR / "inbox_folders.txt"

INBOX_CONFIG_FILE = DATA_DIR / "inbox_config.json"





@app.get("/api/inbox/status")

async def get_inbox_status():

    """INBOX_001: Scanner-Status abrufen."""

    try:

        # Config laden

        config = {}

        if INBOX_CONFIG_FILE.exists():

            config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))



        # Folders laden (Format: PFAD | MODUS | FILTER | ZIEL)

        folders = []

        if INBOX_FOLDERS_FILE.exists():

            for line in INBOX_FOLDERS_FILE.read_text(encoding='utf-8').splitlines():

                line = line.strip()

                if line and not line.startswith('#'):

                    parts = [p.strip() for p in line.split('|')]

                    try:
                        folder_path = resolve_under_base(BACH_DIR, parts[0])
                    except HTTPException:
                        folder_path = None

                    folders.append({

                        "path": parts[0],

                        "mode": parts[1] if len(parts) > 1 else "",

                        "filter": parts[2] if len(parts) > 2 else "",

                        "target": parts[3] if len(parts) > 3 else "",

                        "exists": bool(folder_path and folder_path.exists()),

                        "file_count": len(list(folder_path.iterdir())) if folder_path and folder_path.exists() else 0

                    })



        # Unsortierte Dateien zaehlen

        unsorted_dir = resolve_configured_dir(config, 'unsorted_dir', BACH_DIR / 'user' / 'inbox' / 'unsortiert')

        unsorted_count = len(list(unsorted_dir.glob('*'))) if unsorted_dir.exists() else 0



        return {

            "enabled": config.get('settings', {}).get('enabled', False),

            "folders": folders,

            "rules_count": len(config.get('rules', [])),

            "unsorted_count": unsorted_count,

            "scan_interval": config.get('settings', {}).get('scan_interval_seconds', 60)

        }

    except Exception as e:

        return {"error": public_error_message()}







@app.get("/api/inbox/folders")

async def get_inbox_folders():

    """INBOX_001: Ueberwachte Ordner abrufen."""

    folders = []

    if INBOX_FOLDERS_FILE.exists():

        for line in INBOX_FOLDERS_FILE.read_text(encoding='utf-8').splitlines():

            line = line.strip()

            if line and not line.startswith('#'):

                folders.append(line)

    return {"folders": folders}





@app.post("/api/inbox/folders")

async def add_inbox_folder(folder: dict):

    """INBOX_008: Ordner hinzufuegen."""

    path = folder.get('path', '').strip()

    if not path:

        raise HTTPException(status_code=400, detail="Pfad fehlt")



    # Existierende Ordner laden

    existing = []

    if INBOX_FOLDERS_FILE.exists():

        existing = INBOX_FOLDERS_FILE.read_text(encoding='utf-8').splitlines()



    # Pruefen ob bereits vorhanden

    if path in [l.strip() for l in existing if l.strip() and not l.startswith('#')]:

        return {"success": False, "error": "Ordner bereits vorhanden"}



    # Hinzufuegen

    existing.append(path)

    INBOX_FOLDERS_FILE.write_text('\n'.join(existing), encoding='utf-8')



    return {"success": True, "path": path}





@app.put("/api/inbox/folders")

async def update_inbox_folder(folder: dict):

    """INBOX_008: Ordner bearbeiten (Pfad, Modus, Filter)."""

    index = folder.get('index', -1)

    path = folder.get('path', '').strip()

    mode = folder.get('mode', '').strip()

    filt = folder.get('filter', '').strip()



    if not path:

        return {"success": False, "error": "Pfad fehlt"}



    if not INBOX_FOLDERS_FILE.exists():

        return {"success": False, "error": "Keine Ordner konfiguriert"}



    lines = INBOX_FOLDERS_FILE.read_text(encoding='utf-8').splitlines()



    # Finde die n-te nicht-kommentierte Zeile

    data_lines = [(i, l) for i, l in enumerate(lines) if l.strip() and not l.strip().startswith('#')]

    if index < 0 or index >= len(data_lines):

        return {"success": False, "error": f"Index {index} nicht gefunden"}



    # Format: PFAD | MODUS | FILTER | ZIEL

    parts = [path]

    if mode:

        parts.append(mode)

    if filt:

        if len(parts) == 1:

            parts.append('manual')

        parts.append(filt)



    new_line = ' | '.join(parts) if len(parts) > 1 else path

    line_index = data_lines[index][0]

    lines[line_index] = new_line



    INBOX_FOLDERS_FILE.write_text('\n'.join(lines), encoding='utf-8')

    return {"success": True, "updated": new_line}





@app.delete("/api/inbox/folders")

async def remove_inbox_folder(path: str):

    """INBOX_008: Ordner entfernen."""

    if not INBOX_FOLDERS_FILE.exists():

        raise HTTPException(status_code=404, detail="Keine Ordner konfiguriert")



    lines = INBOX_FOLDERS_FILE.read_text(encoding='utf-8').splitlines()

    new_lines = [l for l in lines if l.strip().split('|')[0].strip() != path]



    if len(new_lines) == len(lines):

        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")



    INBOX_FOLDERS_FILE.write_text('\n'.join(new_lines), encoding='utf-8')

    return {"success": True, "removed": path}





@app.get("/api/inbox/rules")

async def get_inbox_rules():

    """INBOX_005: Sortier-Regeln abrufen."""

    if not INBOX_CONFIG_FILE.exists():

        return {"rules": [], "fallback": {}}



    config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))

    return {

        "rules": config.get('rules', []),

        "fallback": config.get('fallback', {}),

        "settings": config.get('settings', {})

    }





@app.post("/api/inbox/rules")

async def add_inbox_rule(rule: dict):

    """INBOX_005: Regel hinzufuegen."""

    if not INBOX_CONFIG_FILE.exists():

        config = {"settings": {}, "rules": [], "fallback": {}}

    else:

        config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))



    # Validierung

    if not rule.get('name'):

        raise HTTPException(status_code=400, detail="Regelname fehlt")

    if not rule.get('target'):

        raise HTTPException(status_code=400, detail="Zielpfad fehlt")



    # ID generieren

    rule['id'] = f"rule_{datetime.now().strftime('%Y%m%d%H%M%S')}"



    config['rules'].append(rule)



    INBOX_CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')

    return {"success": True, "rule": rule}





@app.put("/api/inbox/rules/{rule_id}")

async def update_inbox_rule(rule_id: str, rule: dict):

    """INBOX_005: Regel aktualisieren."""

    if not INBOX_CONFIG_FILE.exists():

        raise HTTPException(status_code=404, detail="Config nicht gefunden")



    config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))



    for i, r in enumerate(config.get('rules', [])):

        if r.get('id') == rule_id or r.get('name') == rule_id:

            config['rules'][i] = {**r, **rule}

            INBOX_CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')

            return {"success": True, "rule": config['rules'][i]}



    raise HTTPException(status_code=404, detail="Regel nicht gefunden")





@app.delete("/api/inbox/rules/{rule_id}")

async def delete_inbox_rule(rule_id: str):

    """INBOX_005: Regel loeschen."""

    if not INBOX_CONFIG_FILE.exists():

        raise HTTPException(status_code=404, detail="Config nicht gefunden")



    config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))

    original_count = len(config.get('rules', []))

    config['rules'] = [r for r in config.get('rules', []) if r.get('id') != rule_id and r.get('name') != rule_id]



    if len(config['rules']) == original_count:

        raise HTTPException(status_code=404, detail="Regel nicht gefunden")



    INBOX_CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')

    return {"success": True, "deleted": rule_id}





@app.get("/anonymization", response_class=HTMLResponse)
async def serve_anonymization():
    # Alias fuer Abwaertskompatibilitaet, leitet nun auf das Agenten-Dashboard um
    return FileResponse(TEMPLATES_DIR / "anonymization.html")





@app.post("/api/inbox/scan")

async def run_inbox_scan():

    """INBOX_003: Einmaligen Scan ausfuehren."""

    try:

        from hub._services.document.scanner_service import InboxScanner

        scanner = InboxScanner()

        result = scanner.scan_once()

        return {

            "success": True,

            "processed": result.processed,

            "sorted": result.sorted,

            "unsorted": result.unsorted,

            "error_count": len(result.errors or [])

        }

    except ImportError:

        return {"success": False, "error": "Scanner-Service nicht verfuegbar"}

    except Exception as e:

        return {"success": False, "error": public_error_message()}





@app.get("/api/inbox/unsorted")

async def get_unsorted_files():

    """INBOX_007: Unsortierte Dateien auflisten (Review-Queue)."""

    config = {}

    if INBOX_CONFIG_FILE.exists():

        config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))



    unsorted_dir = resolve_configured_dir(config, 'unsorted_dir', BACH_DIR / 'user' / 'inbox' / 'unsortiert')



    files = []

    if unsorted_dir.exists():

        for f in unsorted_dir.iterdir():

            if f.is_file():

                stat = f.stat()

                files.append({

                    "name": f.name,

                    "path": str(f),

                    "size_bytes": stat.st_size,

                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()

                })



    return {"files": files, "count": len(files), "directory": str(unsorted_dir)}





@app.post("/api/inbox/sort")

async def sort_inbox_file(data: dict):

    """INBOX_007: Datei manuell sortieren/verschieben."""

    filename = data.get('filename')

    target_folder = data.get('target_folder')

    new_name = data.get('new_name')



    if not filename or not target_folder:

        raise HTTPException(status_code=400, detail="Filename oder Zielordner fehlt")



    config = {}

    if INBOX_CONFIG_FILE.exists():

        config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))



    unsorted_dir = resolve_configured_dir(config, 'unsorted_dir', BACH_DIR / 'user' / 'inbox' / 'unsortiert')

    source_path = resolve_child_file(unsorted_dir, filename, must_exist=True)



    target_dir = resolve_under_base(BACH_DIR, target_folder)



    try:

        target_dir.mkdir(parents=True, exist_ok=True)

        

        final_name = safe_path_segment(new_name, field_name="Zieldateiname") if new_name else source_path.name

        target_path = resolve_child_file(target_dir, final_name)

        

        # Falls Zieldatei existiert, Zeitstempel anhaengen

        if target_path.exists():

            stem = target_path.stem

            suffix = target_path.suffix

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            target_path = resolve_child_file(target_dir, f"{stem}_{timestamp}{suffix}")



        import shutil

        shutil.move(str(source_path), str(target_path))

        

        return {"success": True, "moved_to": str(target_path)}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.get("/api/inbox/preview/{filename}")

async def get_inbox_preview(filename: str):

    """INBOX_007: Vorschau fuer unsortierte Dateien."""

    config = {}

    if INBOX_CONFIG_FILE.exists():

        config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))

    

    unsorted_dir = resolve_configured_dir(config, 'unsorted_dir', BACH_DIR / 'user' / 'inbox' / 'unsortiert')

    file_path = resolve_child_file(unsorted_dir, filename, must_exist=True)

    

    # MIME Type bestimmen

    import mimetypes

    mime, _ = mimetypes.guess_type(str(file_path))

    

    return FileResponse(file_path, media_type=mime)



@app.get("/api/inbox/analyze/{filename}")

async def analyze_inbox_file(filename: str):

    """INBOX_007: Datei analysieren und Vorschlag generieren."""

    config = {}

    if INBOX_CONFIG_FILE.exists():

        config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))

    

    unsorted_dir = resolve_configured_dir(config, 'unsorted_dir', BACH_DIR / 'user' / 'inbox' / 'unsortiert')

    file_path = resolve_child_file(unsorted_dir, filename)

    

    if not file_path.exists():

        return {"success": False, "error": "Datei nicht gefunden"}



    # Vorschlaege basierend auf Regeln

    suggestions = []

    rules = config.get('rules', [])

    for r in rules:

        if r.get('target') not in suggestions:

            suggestions.append(r.get('target'))



    # Einfaches Keyword Matching fuer Vorschlag

    content = ""

    target_suggestion = None

    

    if file_path.suffix.lower() == '.txt':

        content = file_path.read_text(encoding='utf-8', errors='ignore')

    

    # TODO: PDF OCR integration hier falls noetig

    

    for r in rules:

        patterns = r.get('conditions', {}).get('filename', [])

        if any(p.lower() in filename.lower() for p in patterns):

            target_suggestion = r.get('target')

            break

            

    return {

        "success": True, 

        "filename": filename,

        "content_snippet": content[:500],

        "suggestion": target_suggestion,

        "all_targets": suggestions

    }





@app.put("/api/inbox/settings")

async def update_inbox_settings(settings: dict):

    """INBOX_008: Scanner-Einstellungen aktualisieren."""

    if not INBOX_CONFIG_FILE.exists():

        config = {"settings": {}, "rules": [], "fallback": {}}

    else:

        config = json.loads(INBOX_CONFIG_FILE.read_text(encoding='utf-8'))



    config['settings'] = {**config.get('settings', {}), **settings}

    INBOX_CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')



    return {"success": True, "settings": config['settings']}





# ═══════════════════════════════════════════════════════════════

# WEBSOCKET ENDPOINT (GUI_003a)

# ═══════════════════════════════════════════════════════════════



@app.websocket("/ws")

async def websocket_endpoint(websocket: WebSocket):

    """

    WebSocket-Endpoint fuer Real-time GUI-Updates.

    

    Clients verbinden sich hier und erhalten:

    - task_update: Task wurde geaendert

    - memory_update: Memory wurde aktualisiert

    - file_change: Datei wurde geaendert

    - daemon_event: Daemon-Job Status

    

    Usage (JavaScript):

        // Handshake requires a device token (browsers: subprotocols).

        const ws = new WebSocket('ws://localhost:8000/ws', ['bach.v1', 'bach.token.' + token]);

        ws.onmessage = (event) => {

            const data = JSON.parse(event.data);

            console.log('Update:', data.type, data.payload);

        };

    """

    if not await authorize_websocket(websocket):

        return

    await ws_manager.connect(websocket)

    try:

        while True:

            # Auf Nachrichten vom Client warten (Keep-alive)

            data = await websocket.receive_text()

            # Optional: Client-Befehle verarbeiten

            if data == "ping":

                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})

    except WebSocketDisconnect:

        pass

    finally:

        ws_manager.disconnect(websocket)





@app.get("/api/ws/status")

async def websocket_status():

    """Status der WebSocket-Verbindungen."""

    return {

        "active_connections": len(ws_manager.active_connections),

        "available": True

    }





# ═══════════════════════════════════════════════════════════════

# ANONYMIZATION API (Task #500/#501)

# ═══════════════════════════════════════════════════════════════



@app.get("/api/anonymization/clients")

async def list_anon_clients():

    """Listet Klienten/Ordner in Quarantine."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub._services.document.file_access_hook import list_all_clients

        clients = list_all_clients()

        return {"success": True, "clients": clients}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/anonymization/profile")

async def create_anon_profile(data: dict = Body(...)):

    """Erstellt ein Anonymisierungsprofil."""

    try:

        sys.path.insert(0, str(BACH_DIR))

        from hub._services.document.anonymizer_service import DocumentAnonymizer

        anonymizer = DocumentAnonymizer()



        folder_name = data.get("folder_name") or data.get("client_id")

        real_name = data.get("real_name", folder_name)

        terms = [t.strip() for t in data.get("redaction_terms", "").split(",") if t.strip()]



        profile = anonymizer.create_profile(
            real_name=real_name,
            geburtsdatum=data.get("geburtsdatum", "01.01.2010"),
            additional_terms=terms
        )

        return {"success": True, "tarnname": profile.tarnname, "client_id": profile.client_id}

    except Exception as e:

        return {"success": False, "error": public_error_message()}



@app.post("/api/anonymization/upload")

async def upload_anon_file(file: Request):

    """

    Upload file for quarantine.

    Expects multipart/form-data via Request body parsing manually 

    or simpler: just raw bytes if single file. 

    For now, placeholder logic.

    """

    # TODO: Proper file upload handling with FastAPI UploadFile

    raise HTTPException(status_code=501, detail="Not implemented yet")


# ═══════════════════════════════════════════════════════════════
# REPORT WORKFLOW API (Refactored v1.1)
# ═══════════════════════════════════════════════════════════════

# Global service instance
_report_workflow_service = None

def get_report_workflow_service():
    """Lazy-load Report Workflow Service."""
    global _report_workflow_service
    if _report_workflow_service is None:
        sys.path.insert(0, str(BACH_DIR))
        from hub._services.document.report_workflow_service import ReportWorkflowService
        _report_workflow_service = ReportWorkflowService()
    return _report_workflow_service


@app.post("/api/report/session/start")
async def start_report_session():
    """Startet eine neue Report-Workflow-Session."""
    try:
        service = get_report_workflow_service()
        session = service.start_session()
        return {
            "success": True,
            "session_id": session.session_id,
            "status": session.status
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/report/session/{session_id}/import")
async def import_files_to_session(session_id: str, data: dict = Body(...)):
    """
    Importiert Dateien in eine Session.

    Body: {"folder": "/path/to/folder"} oder {"files": ["/path/file1", "/path/file2"]}
    """
    try:
        service = get_report_workflow_service()
        session = service.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session nicht gefunden"}

        folder = data.get("folder")
        files = data.get("files", [])

        if folder:
            source_folder = resolve_under_base(BACH_DIR, folder, must_exist=True)
            if not source_folder.is_dir():
                raise HTTPException(status_code=400, detail="Ordner erwartet")
            count = service.import_from_folder(session, source_folder)
        elif files:
            source_files = []
            for file_name in files:
                source_file = resolve_under_base(BACH_DIR, file_name, must_exist=True)
                if not source_file.is_file():
                    raise HTTPException(status_code=400, detail="Datei erwartet")
                source_files.append(source_file)
            count = service.import_files(session, source_files)
        else:
            return {"success": False, "error": "folder oder files angeben"}

        return {
            "success": True,
            "imported_count": count,
            "status": session.status
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/report/session/{session_id}/profile")
async def create_session_profile(session_id: str, data: dict = Body(...)):
    """
    Erstellt ein temporaeres Anonymisierungsprofil.

    Body: {
        "client_name": "Max Mustermann",
        "geburtsdatum": "15.03.2016",
        "additional_terms": ["Term1", "Term2"]  / optional
    }
    """
    try:
        service = get_report_workflow_service()
        session = service.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session nicht gefunden"}

        client_name = data.get("client_name")
        if not client_name:
            return {"success": False, "error": "client_name erforderlich"}

        geburtsdatum = data.get("geburtsdatum", "01.01.2010")
        additional_terms = data.get("additional_terms", [])

        profile = service.create_temp_profile(
            session, client_name, geburtsdatum, additional_terms
        )

        return {
            "success": True,
            "tarnname": profile.tarnname,
            "fake_geburtsdatum": profile.fake_geburtsdatum,
            "mappings_count": len(profile.get_all_mappings()),
            "status": session.status
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/report/session/{session_id}/anonymize")
async def anonymize_session_documents(session_id: str, data: dict = Body(default={})):
    """
    Anonymisiert die importierten Dokumente.

    Body: {"include_extended": false}  / optional
    """
    try:
        service = get_report_workflow_service()
        session = service.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session nicht gefunden"}

        include_extended = data.get("include_extended", False)
        result = service.anonymize_to_bundles(session, include_extended)

        return {
            "success": True,
            "core_count": result.core_count,
            "stufe2_count": result.stufe2_count,
            "extended_count": result.extended_count,
            "status": session.status
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/report/session/{session_id}/prompt")
async def generate_session_prompt(session_id: str, data: dict = Body(default={})):
    """
    Generiert den LLM-Prompt.

    Body: {
        "berichtszeitraum": "01.01.2025 - 31.12.2025",
        "include_wissensdatenbank": true,
        "custom_instructions": ""
    }
    """
    try:
        service = get_report_workflow_service()
        session = service.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session nicht gefunden"}

        berichtszeitraum = data.get("berichtszeitraum", "")
        include_kb = data.get("include_wissensdatenbank", True)
        custom = data.get("custom_instructions", "")

        prompt = service.generate_prompt(
            session,
            include_wissensdatenbank=include_kb,
            berichtszeitraum=berichtszeitraum,
            custom_instructions=custom
        )

        return {
            "success": True,
            "prompt": prompt,
            "prompt_length": len(prompt),
            "status": session.status
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/report/session/{session_id}/generate")
async def generate_session_report(session_id: str, data: dict = Body(...)):
    """
    Generiert das Word-Dokument.

    Body: {
        "llm_response": "Der generierte Berichtstext...",
        "auto_deanonymize": true
    }
    """
    try:
        service = get_report_workflow_service()
        session = service.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session nicht gefunden"}

        llm_response = data.get("llm_response")
        if not llm_response:
            return {"success": False, "error": "llm_response erforderlich"}

        auto_deanonymize = data.get("auto_deanonymize", True)

        output_path = service.generate_report(session, llm_response, auto_deanonymize)

        return {
            "success": True,
            "output_path": str(output_path),
            "status": session.status
        }
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/report/session/{session_id}/cleanup")
async def cleanup_session(session_id: str, data: dict = Body(default={})):
    """
    Räumt alle temporären Session-Daten auf.

    Body: {"keep_output": true}  / optional
    """
    try:
        service = get_report_workflow_service()
        session = service.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session nicht gefunden"}

        keep_output = data.get("keep_output", True)
        service.cleanup(session, keep_output)

        return {"success": True, "message": "Session aufgeräumt"}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.get("/api/report/session/{session_id}")
async def get_session_status(session_id: str):
    """Gibt den aktuellen Session-Status zurück."""
    try:
        service = get_report_workflow_service()
        session = service.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session nicht gefunden"}

        return {"success": True, "session": session.to_dict()}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.get("/api/report/pending")
async def list_pending_reports():
    """Listet wartende Ordner für Berichte."""
    try:
        sys.path.insert(0, str(BACH_DIR))
        from hub._services.document.report_workflow_service import list_pending_reports
        pending = list_pending_reports()
        return {"success": True, "pending": pending}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


# ═══════════════════════════════════════════════════════════════
# WORKFLOW TÜV SYSTEM
# ═══════════════════════════════════════════════════════════════

def _ensure_workflow_tuev_table():
    """Erstellt die workflow_tuev Tabelle und synchronisiert mit Dateisystem."""
    conn = sqlite3.connect(BACH_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_tuev (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_path TEXT UNIQUE,
            workflow_name TEXT,
            last_tuev_date TEXT,
            tuev_valid_until TEXT,
            tuev_status TEXT DEFAULT 'pending',
            test_count INTEGER DEFAULT 0,
            pass_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            avg_score REAL DEFAULT 0.0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM workflow_tuev").fetchone()[0]
    if count == 0:
        workflows_dir = Path(__file__).parent.parent / "skills" / "_workflows"
        if workflows_dir.exists():
            for wf_file in workflows_dir.glob("*.md"):
                rel_path = f"skills/workflows/{wf_file.name}"
                wf_name = wf_file.stem
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO workflow_tuev (workflow_path, workflow_name, tuev_status)
                        VALUES (?, ?, 'pending')
                    """, (rel_path, wf_name))
                except Exception:
                    pass
            conn.commit()
    conn.close()

@app.get("/workflow-tuev", response_class=HTMLResponse)
async def workflow_tuev_page():
    """Workflow TÜV Dashboard."""
    workflow_tuev_file = TEMPLATES_DIR / "workflow_tuev.html"
    if workflow_tuev_file.exists():
        return FileResponse(workflow_tuev_file)
    raise HTTPException(status_code=404, detail="Template workflow_tuev.html nicht gefunden")


@app.get("/api/workflow-tuev")
async def get_workflow_tuev():
    """Alle Workflows mit TÜV-Status laden."""
    try:
        _ensure_workflow_tuev_table()
        conn = sqlite3.connect(BACH_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, workflow_path, workflow_name, last_tuev_date, tuev_valid_until,
                   tuev_status, test_count, pass_count, fail_count, avg_score, notes
            FROM workflow_tuev
            ORDER BY workflow_name
        """)
        rows = cursor.fetchall()

        from datetime import datetime, timedelta
        today = datetime.now().date()

        workflows = []
        stats = {"total": 0, "valid": 0, "expired": 0, "pending": 0}

        for row in rows:
            wf = dict(row)
            stats["total"] += 1

            if wf["tuev_valid_until"]:
                valid_until = datetime.fromisoformat(wf["tuev_valid_until"]).date()
                if valid_until < today:
                    wf["tuev_status"] = "expired"
                    stats["expired"] += 1
                elif valid_until <= today + timedelta(days=14):
                    wf["tuev_status"] = "warning"
                    stats["valid"] += 1
                else:
                    wf["tuev_status"] = "valid"
                    stats["valid"] += 1
            else:
                wf["tuev_status"] = "pending"
                stats["pending"] += 1

            workflows.append(wf)

        conn.close()
        return {"workflows": workflows, "stats": stats}

    except Exception as e:
        return {"error": public_error_message(), "workflows": [], "stats": {}}


@app.post("/api/workflow-tuev/{workflow_id}/check")
async def check_workflow_tuev(workflow_id: int, request: Request):
    """TÜV für einen Workflow durchführen."""
    try:
        _ensure_workflow_tuev_table()
        data = await request.json()
        result = data.get("result", "pass")
        validity_days = data.get("validity_days", 90)
        notes = data.get("notes", "")

        from datetime import datetime, timedelta
        now = datetime.now()
        valid_until = now + timedelta(days=validity_days)

        conn = sqlite3.connect(BACH_DB)
        cursor = conn.cursor()

        if result == "pass":
            cursor.execute("""
                UPDATE workflow_tuev SET
                    last_tuev_date = ?,
                    tuev_valid_until = ?,
                    tuev_status = 'valid',
                    test_count = test_count + 1,
                    pass_count = pass_count + 1,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
            """, (now.isoformat(), valid_until.isoformat(), notes, now.isoformat(), workflow_id))
        elif result == "fail":
            cursor.execute("""
                UPDATE workflow_tuev SET
                    last_tuev_date = ?,
                    tuev_status = 'expired',
                    test_count = test_count + 1,
                    fail_count = fail_count + 1,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
            """, (now.isoformat(), notes, now.isoformat(), workflow_id))
        else:
            cursor.execute("""
                UPDATE workflow_tuev SET
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
            """, (notes, now.isoformat(), workflow_id))

        conn.commit()
        conn.close()
        return {"success": True}

    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/workflow-tuev/check-all")
async def check_all_workflows():
    """Alle Workflows als geprüft markieren (90 Tage Gültigkeit)."""
    try:
        _ensure_workflow_tuev_table()
        from datetime import datetime, timedelta
        now = datetime.now()
        valid_until = now + timedelta(days=90)

        conn = sqlite3.connect(BACH_DB)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE workflow_tuev SET
                last_tuev_date = ?,
                tuev_valid_until = ?,
                tuev_status = 'valid',
                test_count = test_count + 1,
                pass_count = pass_count + 1,
                updated_at = ?
        """, (now.isoformat(), valid_until.isoformat(), now.isoformat()))

        checked = cursor.rowcount
        conn.commit()
        conn.close()
        return {"success": True, "checked": checked}

    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.post("/api/workflow-tuev/sync")
async def sync_workflow_tuev():
    """Workflow-TÜV Tabelle mit Dateisystem synchronisieren."""
    _ensure_workflow_tuev_table()
    try:
        workflows_dir = Path(__file__).parent.parent / "skills" / "_workflows"

        conn = sqlite3.connect(BACH_DB)
        cursor = conn.cursor()

        cursor.execute("SELECT workflow_path FROM workflow_tuev")
        existing = set(row[0] for row in cursor.fetchall())

        added = 0

        if workflows_dir.exists():
            for wf_file in workflows_dir.glob("*.md"):
                rel_path = f"skills/workflows/{wf_file.name}"
                wf_name = wf_file.stem

                if rel_path not in existing:
                    cursor.execute("""
                        INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_status)
                        VALUES (?, ?, 'pending')
                    """, (rel_path, wf_name))
                    added += 1

        conn.commit()
        conn.close()
        return {"success": True, "added": added, "updated": 0}

    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.get("/api/workflow-tuev/content")
async def get_workflow_content(path: str):
    """Workflow-Inhalt anzeigen."""
    try:
        normalized = path.replace("\\", "/").replace("%5C", "/")
        workflow_path = resolve_under_base(BACH_DIR, normalized, allowed_suffixes={".md", ".txt"})

        if workflow_path.exists():
            content = workflow_path.read_text(encoding='utf-8')
            escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return HTMLResponse(content=f"<pre style='white-space: pre-wrap; font-family: monospace; padding: 20px; background: #1e1e1e; color: #d4d4d4;'>{escaped}</pre>")
        else:
            return HTMLResponse(content="<h1>Workflow nicht gefunden</h1>", status_code=404)

    except HTTPException:
        raise
    except Exception as e:
        return HTMLResponse(content=f"<h1>Fehler: {public_error_message()}</h1>", status_code=500)


# ═══════════════════════════════════════════════════════════════

# UNIFIED GUI (optionales externes Modul ellmos-unified-gui)
# Operator-Konsole als Sub-App unter /control — Panels erscheinen
# capability-driven je nach erreichbaren Backends. Fehlt das Paket,
# laeuft BACH unveraendert (bewusst weiches Optional).

# ═══════════════════════════════════════════════════════════════

try:
    from unified_gui import mount as _unified_gui_mount

    _unified_gui_mount(app, prefix="/control")
    print("[GUI] Unified GUI unter /control eingebunden (ellmos-unified-gui)")
except ImportError:
    pass
except Exception as _ug_exc:  # noqa: BLE001 — Mount-Fehler duerfen BACH nie stoppen
    print(f"[GUI] Unified GUI nicht eingebunden: {_ug_exc}")


# ═══════════════════════════════════════════════════════════════

# MAIN

# ═══════════════════════════════════════════════════════════════



def run_server(host: str = "127.0.0.1", port: int = 8000):

    """Startet den Server."""

    try:

        import uvicorn

        if host not in ("0.0.0.0", "::", ""):

            # An explicitly chosen bind address is a deliberate Host for this GUI.

            os.environ["BACH_GUI_ALLOWED_HOSTS"] = ",".join(
                filter(None, [os.environ.get("BACH_GUI_ALLOWED_HOSTS", ""), host]))

        print(f"[BACH GUI] Starte Server auf http://{host}:{port}")

        print(f"[BACH GUI] API-Docs: http://{host}:{port}/docs")

        uvicorn.run(app, host=host, port=port)

    except ImportError:

        print("[ERROR] uvicorn nicht installiert!")

        print("        pip install uvicorn")




if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description="BACH GUI Server")

    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")

    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")

    args = parser.parse_args()

    

    run_server(args.host, args.port)
