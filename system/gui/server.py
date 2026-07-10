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

import sqlite3

from pathlib import Path

from datetime import datetime, date

from typing import Optional, List

from contextlib import asynccontextmanager

# BACH imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from hub.lang import t, get_lang

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

    from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse

    from fastapi.middleware.cors import CORSMiddleware

    from pydantic import BaseModel

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
    BACH_DB = DATA_DIR / "bach.db"

USER_DB = BACH_DB

TEMPLATES_DIR = GUI_DIR / "templates"

STATIC_DIR = GUI_DIR / "static"

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

    assigned_to: Optional[str] = "user"

    created_by: Optional[str] = "user"



class TaskUpdate(BaseModel):

    title: Optional[str] = None

    description: Optional[str] = None

    priority: Optional[str] = None

    status: Optional[str] = None

    project: Optional[str] = None

    assigned_to: Optional[str] = None

    created_by: Optional[str] = None

    depends_on: Optional[str] = None





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

        await websocket.accept()

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

    allow_origins=["*"],

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



# ═══════════════════════════════════════════════════════════════

# API ROUTES - STATUS

# ═══════════════════════════════════════════════════════════════



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
        messages_unread = conn_bach.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'unread'"
        ).fetchone()[0]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
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

    return {

        "status": "online",

        "version": "1.1.85",

        "timestamp": datetime.now().isoformat(),
        "db_connected": True,

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

        tasks = rows_to_list(rows)

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

@app.get("/api/tasks")
async def api_get_tasks(status: str = "all", project: str = None, assigned_to: str = None, limit: int = 100):
    """Liefert Tasks mit erweitertem Filter und Blockierungs-Check."""
    try:
        conn = get_bach_db()

        # Support "all" to return all statuses (fix for task disappearing bug)
        if status and status.lower() != "all":
            query = "SELECT * FROM tasks WHERE status = ?"
            params = [status]
        else:
            query = "SELECT * FROM tasks WHERE 1=1"
            params = []
        
        if project:
            query += " AND category = ?"
            params.append(project)
        if assigned_to:
            query += " AND UPPER(assigned_to) = UPPER(?)"
            params.append(assigned_to)
            
        query += " ORDER BY priority ASC, created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        tasks = rows_to_list(rows)

        # image_data nicht in Liste senden (Performance), nur Flag
        for task in tasks:
            if task.get("image_data"):
                task["has_image"] = True
            task.pop("image_data", None)

        # Check dependencies for blocking status
        for task in tasks:
            if task.get("depends_on"):
                try:
                    dep_ids = [int(x.strip()) for x in task["depends_on"].split(",") if x.strip()]
                    if dep_ids:
                        # Prüfen ob alle erledigt sind
                        placeholders = ",".join(["?"] * len(dep_ids))
                        unfinished = conn.execute(f"SELECT COUNT(*) FROM tasks WHERE id IN ({placeholders}) AND status != 'done'", dep_ids).fetchone()[0]
                        if unfinished > 0:
                            task["is_blocked_by_dep"] = True
                except (sqlite3.OperationalError, sqlite3.DatabaseError, ValueError, AttributeError):
                    pass

        conn.close()
        return {"success": True, "tasks": tasks, "count": len(tasks)}
    except Exception as e:
        return {"success": False, "error": public_error_message()}

@app.post("/api/tasks")
async def api_post_task(payload: dict = Body(...)):
    """Erstellt neuen Task in bach.db via JSON Payload."""
    try:
        conn = get_bach_db()
        now = datetime.now().isoformat()
        
        cursor = conn.execute("""
            INSERT INTO tasks (title, description, priority, category, status, created_at, created_by, assigned_to, depends_on, image_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.get("title"),
            payload.get("description", ""),
            payload.get("priority", "P3"),
            payload.get("category", "general"),
            payload.get("status", "pending"),
            now,
            payload.get("created_by", "user"),
            payload.get("assigned_to", "user"),
            payload.get("depends_on"),
            payload.get("image")
        ))

        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"success": True, "id": task_id, "status": "created"}
    except Exception as e:
        return {"success": False, "error": public_error_message()}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: int):
    """Holt einzelnen Task aus bach.db."""
    conn = get_bach_db()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    return row_to_dict(row)

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: int, update: TaskUpdate):
    """Aktualisiert Task in bach.db."""
    conn = get_bach_db()
    try:
        existing = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task nicht gefunden")

        updates = []
        values = []

        if update.title is not None:
            updates.append("title = ?")
            values.append(update.title)
        if update.description is not None:
            updates.append("description = ?")
            values.append(update.description)
        if update.priority is not None:
            updates.append("priority = ?")
            values.append(update.priority)
        if update.status is not None:
            updates.append("status = ?")
            values.append(update.status)
            if update.status == "completed":
                updates.append("completed_at = ?")
                values.append(datetime.now().isoformat())
        if update.project is not None:
            updates.append("category = ?")
            values.append(update.project)
        if update.assigned_to is not None:
            updates.append("assigned_to = ?")
            values.append(update.assigned_to)
        if update.created_by is not None:
            updates.append("created_by = ?")
            values.append(update.created_by)
        if update.depends_on is not None:
            updates.append("depends_on = ?")
            values.append(update.depends_on)

        if updates:
            updates.append("updated_at = ?")
            values.append(datetime.now().isoformat())
            values.append(task_id)
            conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
    finally:
        conn.close()

    return {"status": "updated"}

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
                "category": c[2],
                "status": "available"
            })
    except Exception:
        pass

    conn.close()
    return {"assignees": assignees, "count": len(assignees)}


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

    conn = get_user_db()
    try:
        query = "SELECT * FROM messages WHERE status != 'deleted'"
        params = []

        if direction:
            query += " AND direction = ?"
            params.append(direction)

        if status:
            query += " AND status = ?"
            params.append(status)
        elif not include_archived:
            query += " AND status != 'archived'"

        if partner:
            query += " AND (sender = ? OR recipient = ?)"
            params.extend([partner, partner])

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    return {"messages": rows_to_list(rows), "count": len(rows)}



@app.post("/api/claude/chat")
async def claude_chat(
    request_type: str = Body(...),
    prompt: str = Body(...),
    user_id: str = Body(default="user")
):
    """
    Sendet Anfrage an Claude (Bridge oder GUI-Session).

    Body:
        request_type: "chat" | "assistant" | "quick_question" | "code_analysis" | "long_task"
        prompt: User-Eingabe
        user_id: User-ID (default: lukas)
    """
    if not CLAUDE_ROUTER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Claude Router nicht verfügbar")

    try:
        result = route_request(request_type, prompt, user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Router-Fehler: {type(e).__name__}")


@app.post("/api/messages")

async def create_message(msg: MessageCreate):

    """Erstellt neue Nachricht."""

    conn = get_user_db()

    try:

        cursor = conn.execute("""

            INSERT INTO messages (direction, sender, recipient, subject, body, priority)

            VALUES ('outbox', 'user', ?, ?, ?, ?)

        """, (msg.recipient, msg.subject, msg.body, msg.priority))

        msg_id = cursor.lastrowid

        conn.commit()

    finally:

        conn.close()

    return {"id": msg_id, "status": "created"}



@app.put("/api/messages/{msg_id}/read")

async def mark_message_read(msg_id: int):

    """Markiert Nachricht als gelesen."""

    conn = get_user_db()

    try:

        conn.execute(

            "UPDATE messages SET status = 'read', read_at = ? WHERE id = ?",

            (datetime.now().isoformat(), msg_id)

        )

        conn.commit()

    finally:

        conn.close()

    return {"status": "read"}


@app.post("/api/messages/mark-all-read")
async def mark_all_messages_read():
    """Markiert alle ungelesenen Nachrichten als gelesen."""
    conn = get_user_db()
    try:
        now = datetime.now().isoformat()
        cursor = conn.execute(
            "UPDATE messages SET status = 'read', read_at = ? WHERE status = 'unread'",
            (now,)
        )
        count = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "marked": count}



@app.put("/api/messages/{msg_id}/archive")

async def archive_message(msg_id: int):

    """Archiviert eine Nachricht."""

    conn = get_user_db()

    try:

        conn.execute(

            "UPDATE messages SET status = 'archived' WHERE id = ?",

            (msg_id,)

        )

        conn.commit()

    finally:

        conn.close()

    return {"status": "archived"}





@app.put("/api/messages/{msg_id}/delete")

async def delete_message(msg_id: int):

    """Markiert Nachricht als geloescht (soft delete)."""

    conn = get_user_db()

    try:

        conn.execute(

            "UPDATE messages SET status = 'deleted' WHERE id = ?",

            (msg_id,)

        )

        conn.commit()

    finally:

        conn.close()

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
        conn = get_user_db()
        rows = conn.execute(
            "SELECT DISTINCT sender FROM messages WHERE sender != 'user' AND sender IS NOT NULL ORDER BY sender"
        ).fetchall()
        conn.close()
        for r in rows:
            name = r[0]
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





@app.get("/api/daemon/status")

async def get_daemon_status():

    """Liefert aktuellen Daemon-Status mit Job-Statistiken und Runtime-Metriken."""

    from gui.daemon_service import DaemonService, DAEMON_PID_FILE

    running = False
    pid = None
    pid_content = None
    started_at = None

    if DAEMON_PID_FILE.exists():
        try:
            pid_content = DAEMON_PID_FILE.read_text().strip()
            pid = int(pid_content)
            import subprocess
            if os.name == 'nt':
                output = subprocess.check_output(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    stderr=subprocess.DEVNULL).decode('utf-8', errors='replace')
                running = str(pid) in output
            else:
                os.kill(pid, 0)
                running = True
        except Exception:
            pass

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
                started_at = cfg.get("started_at")
        except Exception:
            pass

    runtime_str = "00:00:00"
    sessions_generated = 0
    next_session_in = 0
    if running and started_at:
        interval = config["interval"]
        sessions_generated = get_extrapolated_session_count(started_at, interval)
        next_session_in = get_next_session_seconds(started_at, interval)
        runtime_str = get_runtime_string(started_at)

    conn = get_user_db()
    stats = {"total_jobs": 0, "active_jobs": 0, "runs_today": 0, "failed_today": 0}
    last_runs = []
    try:
        stats["total_jobs"] = conn.execute("SELECT COUNT(*) FROM scheduler_jobs").fetchone()[0]
        stats["active_jobs"] = conn.execute("SELECT COUNT(*) FROM scheduler_jobs WHERE is_active = 1").fetchone()[0]
        stats["runs_today"] = conn.execute(
            "SELECT COUNT(*) FROM scheduler_runs WHERE date(started_at) = date('now')"
        ).fetchone()[0]
        stats["failed_today"] = conn.execute(
            "SELECT COUNT(*) FROM scheduler_runs WHERE date(started_at) = date('now') AND result = 'failed'"
        ).fetchone()[0]
        last_runs = conn.execute("""
            SELECT r.id, j.name, r.result, r.started_at, r.duration_seconds
            FROM scheduler_runs r
            JOIN scheduler_jobs j ON r.job_id = j.id
            ORDER BY r.started_at DESC LIMIT 5
        """).fetchall()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass
    conn.close()

    return {
        "running": running,
        "pid": pid,
        "pid_file": str(DAEMON_PID_FILE),
        "pid_content": pid_content,
        "started_at": started_at,
        "config": config,
        "runtime_str": runtime_str,
        "sessions_generated": sessions_generated,
        "next_session_in": next_session_in,
        "is_quiet_time": is_quiet,
        "stats": stats,
        "last_runs": rows_to_list(last_runs),
    }





@app.post("/api/daemon/start")

async def start_daemon(background_tasks: BackgroundTasks):

    """Startet den Daemon-Service im Hintergrund."""

    from gui.daemon_service import DaemonService, DAEMON_PID_FILE



    # Pruefen ob bereits laeuft (mit PID-Validierung)

    if DAEMON_PID_FILE.exists():
        daemon_running = False
        try:
            pid = int(DAEMON_PID_FILE.read_text().strip())
            if os.name == 'nt':
                import subprocess as _sp
                output = _sp.check_output(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    stderr=_sp.DEVNULL).decode('utf-8', errors='replace')
                daemon_running = str(pid) in output
            else:
                os.kill(pid, 0)
                daemon_running = True
        except Exception:
            DAEMON_PID_FILE.unlink(missing_ok=True)
        if daemon_running:
            return {"status": "already_running", "message": "Daemon laeuft bereits"}



    def run_daemon():

        daemon = DaemonService()

        daemon.run()



    background_tasks.add_task(run_daemon)

    return {"status": "starting", "message": "Daemon wird gestartet..."}





@app.post("/api/daemon/stop")

async def stop_daemon():

    """Stoppt den Daemon-Service."""

    from gui.daemon_service import DaemonService, DAEMON_PID_FILE



    if not DAEMON_PID_FILE.exists():

        return {"status": "not_running", "message": "Daemon laeuft nicht"}



    # Signal senden (PID-File entfernen reicht meist)

    try:

        DAEMON_PID_FILE.unlink()

        return {"status": "stopped", "message": "Stop-Signal gesendet"}

    except Exception as e:

        return {"status": "error", "message": public_error_message()}





@app.post("/api/daemon/kill-all")

async def kill_all_daemons():

    """Beendet alle Daemon-Prozesse (Zombie-Praevention)."""

    from gui.daemon_service import DaemonService



    DaemonService.kill_all_daemons()

    return {

        "status": "ok",

        "message": "Daemon-Prozesse wurden beendet"

    }





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

# STATIC FILES & TEMPLATES

# ═══════════════════════════════════════════════════════════════



# Statische Dateien mounten (falls vorhanden)

if STATIC_DIR.exists():

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")



@app.get("/", response_class=HTMLResponse)

async def index():

    """Startseite."""

    index_file = TEMPLATES_DIR / "index.html"

    if index_file.exists():

        return FileResponse(index_file)

    

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

    tasks_file = TEMPLATES_DIR / "tasks.html"

    if tasks_file.exists():

        return FileResponse(tasks_file)

    raise HTTPException(status_code=404, detail="Template tasks.html nicht gefunden")






@app.get("/messages", response_class=HTMLResponse)

async def messages_page():

    """Messages Seite."""

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





@app.get("/partners", response_class=HTMLResponse)

async def partners_page():

    """Partner Dashboard Seite."""

    partners_file = TEMPLATES_DIR / "partners.html"

    if partners_file.exists():

        return FileResponse(partners_file)

    raise HTTPException(status_code=404, detail="Template partners.html nicht gefunden")





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



@app.get("/skills-board", response_class=HTMLResponse)

async def skills_board_page():

    """Skills Board - Hierarchie-Verwaltung."""

    board_file = TEMPLATES_DIR / "skills-board.html"

    if board_file.exists():

        return FileResponse(board_file)

    raise HTTPException(status_code=404, detail="Template skills-board.html nicht gefunden")


@app.get("/skills")
async def skills_redirect():
    return RedirectResponse("/skills-board")

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

async def denkarium_list(entry_type: str = None, category: str = None, limit: int = 50, search: str = None):

    """Denkarium-Einträge abrufen."""

    conn = sqlite3.connect(str(USER_DB))

    try:

        query = "SELECT id, entry_type, title, content, category, source, mood, promoted_to, promoted_id, created_at, updated_at FROM denkarium_entries"

        conditions = []

        params = []

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

        stats = conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN entry_type='logbuch' THEN 1 ELSE 0 END) as logbuch, SUM(CASE WHEN entry_type='denkarium' THEN 1 ELSE 0 END) as denkarium FROM denkarium_entries").fetchone()

        categories = conn.execute("SELECT category, COUNT(*) as cnt FROM denkarium_entries GROUP BY category ORDER BY cnt DESC").fetchall()

        return {

            "entries": entries,

            "count": len(entries),

            "stats": {"total": (stats[0] or 0) if stats else 0, "logbuch": (stats[1] or 0) if stats else 0, "denkarium": (stats[2] or 0) if stats else 0},

            "categories": [{"name": c[0], "count": c[1]} for c in categories]

        }

    except (sqlite3.OperationalError, sqlite3.DatabaseError):

        return {"entries": [], "count": 0, "stats": {"total": 0, "logbuch": 0, "denkarium": 0}, "categories": []}

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







@app.get("/tasks-board", response_class=HTMLResponse)

async def tasks_board_api():

    """Tasks Board Seite."""

    board_file = TEMPLATES_DIR / "tasks_board.html"

    if board_file.exists():

        return FileResponse(board_file)

    raise HTTPException(status_code=404, detail="Template tasks_board.html nicht gefunden")





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

    # Tabellen initialisieren falls noetig

    init_financial_tables()



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

        cursor.execute("SELECT COUNT(*) FROM financial_subscriptions WHERE aktiv = 1")

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

            SELECT SUM(betrag_monatlich) FROM financial_subscriptions WHERE aktiv = 1

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

        query = "SELECT * FROM financial_subscriptions"

        if active_only:

            query += " WHERE aktiv = 1"

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
                WHERE category IN ('practice', 'best_practice', 'best-practice')
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()
            result["best_practices"] = rows_to_list(rows)

            # Workflows (Procedural)
            workflows = []
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

    return RedirectResponse(url="/", status_code=302)





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


@app.post("/api/routines")
async def add_routine(request: Request):
    """Neue Routine anlegen."""
    try:
        from datetime import date, timedelta
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()

        # next_due_at berechnen
        today = date.today()
        next_due = today.isoformat()

        cursor.execute("""
            INSERT INTO routines (name, description, category, priority, interval_type,
                                  interval_value, specific_day, duration_minutes, next_due_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            data.get('name'),
            data.get('description'),
            data.get('category', 'Haushalt'),
            data.get('priority', 2),
            data.get('interval_type', 'woechentlich'),
            data.get('interval_value', 1),
            data.get('specific_day'),
            data.get('duration_minutes'),
            next_due
        ))
        conn.commit()
        conn.close()
        return {"success": True, "id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.put("/api/routines/{routine_id}")
async def update_routine(routine_id: int, request: Request):
    """Routine aktualisieren."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE routines SET
                name = ?, description = ?, category = ?, priority = ?,
                interval_type = ?, interval_value = ?, specific_day = ?,
                duration_minutes = ?, updated_at = CURRENT_TIMESTAMP
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
        conn = get_user_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_accounts ORDER BY name")
        rows = cursor.fetchall()
        accounts = [dict(row) for row in rows]
        conn.close()
        return {"success": True, "accounts": accounts}
    except Exception as e:
        return {"success": False, "error": public_error_message(), "accounts": []}


@app.post("/api/financial/bank-accounts")
async def add_bank_account(request: Request):
    """Neues Bankkonto anlegen."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bank_accounts (name, bank_name, iban, bic, account_type, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data.get('name'),
            data.get('bank_name'),
            data.get('iban'),
            data.get('bic'),
            data.get('account_type', 'girokonto'),
            data.get('notes')
        ))
        conn.commit()
        conn.close()
        return {"success": True, "id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.put("/api/financial/bank-accounts/{account_id}")
async def update_bank_account(account_id: int, request: Request):
    """Bankkonto aktualisieren."""
    try:
        data = await request.json()
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE bank_accounts SET
                name = ?, bank_name = ?, iban = ?, bic = ?,
                account_type = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data.get('name'),
            data.get('bank_name'),
            data.get('iban'),
            data.get('bic'),
            data.get('account_type', 'girokonto'),
            data.get('notes'),
            account_id
        ))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": public_error_message()}


@app.delete("/api/financial/bank-accounts/{account_id}")
async def delete_bank_account(account_id: int):
    """Bankkonto loeschen."""
    try:
        conn = get_user_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bank_accounts WHERE id = ?", (account_id,))
        conn.commit()
        conn.close()
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

        const ws = new WebSocket('ws://localhost:8000/ws');

        ws.onmessage = (event) => {

            const data = JSON.parse(event.data);

            console.log('Update:', data.type, data.payload);

        };

    """

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

# MAIN

# ═══════════════════════════════════════════════════════════════



def run_server(host: str = "127.0.0.1", port: int = 8000):

    """Startet den Server."""

    try:

        import uvicorn

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

