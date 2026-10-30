import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from hub.bach_paths import BACH_DB
except ImportError:  # pragma: no cover - fallback wenn BACH_ROOT nicht im sys.path
    BACH_DB = Path(__file__).parent.parent / "data" / "bach.db"


def row_to_dict(row: sqlite3.Row) -> dict:
    """Wandelt eine sqlite3-Row in ein Dictionary um."""
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def rows_to_list(rows: list) -> list:
    """Wandelt eine Liste von sqlite3-Rows in eine Liste von Dictionaries um."""
    return [row_to_dict(row) for row in rows]


# ═══════════════════════════════════════════════════════════════
# bach_agents (Avatar-Agenten & Animus Matrix)
# ═══════════════════════════════════════════════════════════════

_BACH_AGENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bach_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT,
    type TEXT,
    category TEXT,
    description TEXT,
    skill_path TEXT,
    user_data_folder TEXT,
    parent_agent_id INTEGER,
    is_active INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    requires_setup INTEGER DEFAULT 0,
    setup_completed INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    last_used TEXT,
    version TEXT DEFAULT '1.0.0',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    dashboard TEXT,
    language TEXT,
    persona TEXT,
    dist_type TEXT,
    animus TEXT,
    session_hook TEXT,
    taskboard_id TEXT,
    taskboard_default INTEGER DEFAULT 0
);
"""

# Minimaler Kanon der Avatar-Agenten (ehemals hartcodiert in gui/server.py).
DEFAULT_AVATAR_AGENTS = [
    {
        "name": "claude",
        "display_name": "Claude Code (Subscription / CLI)",
        "type": "avatar",
        "category": "subscription",
        "animus": "subscription",
        "session_hook": "claude://session",
        "taskboard_id": "claude-board",
        "taskboard_default": 1,
        "is_active": 1,
        "priority": 10,
    },
    {
        "name": "gemini",
        "display_name": "Gemini (Subscription / API)",
        "type": "avatar",
        "category": "subscription",
        "animus": "subscription",
        "session_hook": "gemini://session",
        "taskboard_id": "gemini-board",
        "taskboard_default": 1,
        "is_active": 1,
        "priority": 10,
    },
    {
        "name": "codex",
        "display_name": "OpenAI Codex CLI",
        "type": "avatar",
        "category": "cli",
        "animus": "cli",
        "session_hook": "codex://session",
        "taskboard_id": "codex-board",
        "taskboard_default": 1,
        "is_active": 1,
        "priority": 10,
    },
    {
        "name": "kimi",
        "display_name": "Kimi (Moonshot)",
        "type": "avatar",
        "category": "subscription",
        "animus": "subscription",
        "session_hook": "kimi://session",
        "taskboard_id": "kimi-board",
        "taskboard_default": 1,
        "is_active": 1,
        "priority": 10,
    },
]

# Idle-Worker, die als Fallback-Assignees dienen (z.B. Ollama/Buddha im Hintergrund).
DEFAULT_IDLE_WORKERS = ["OLLAMA", "BUDDHA"]

# Fallback-Assignee fuer neue Tasks (identisch zu gui/server.py & headless).
DEFAULT_TASK_ASSIGNEE = DEFAULT_IDLE_WORKERS[0]

# Animus-Typen-Kanon (GUI-OCEAN-03): Art der Anbindung eines Avatar-Agenten.
#   api          - programmatischer API-Kanal
#   mcp          - Model Context Protocol
#   cli          - CLI-Prozess (z.B. Claude Code CLI, Codex CLI)
#   subscription - Abo-/Session-Anbindung
ANIMUS_TYPES = ("api", "mcp", "cli", "subscription")


def _migrate_bach_agents(conn: sqlite3.Connection) -> None:
    """Ergänzt fehlende Spalten in bach_agents robust nach dem aktuellen Zielschema.

    Die Tabelle kann in verschiedenen DBs unterschiedlich aussehen (z.B. fehlt
    `dist_type` in aelteren Versionen). Wir ergänzen daher nur Spalten, die nach
    PRAGMA table_info wirklich fehlen.
    """
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(bach_agents)").fetchall()
    }
    target_cols = [
        ("dist_type", "TEXT"),
        ("animus", "TEXT"),
        ("session_hook", "TEXT"),
        ("taskboard_id", "TEXT"),
        ("taskboard_default", "INTEGER DEFAULT 0"),
    ]
    for col_name, col_def in target_cols:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE bach_agents ADD COLUMN {col_name} {col_def}")
            conn.commit()


def _init_bach_agents(conn: sqlite3.Connection) -> None:
    """Erstellt bach_agents falls noetig und migriert fehlende Spalten."""
    conn.executescript(_BACH_AGENTS_SCHEMA)
    conn.commit()
    _migrate_bach_agents(conn)


def get_bach_db() -> sqlite3.Connection:
    """Verbindung zur zentralen bach.db."""
    conn = sqlite3.connect(str(BACH_DB))
    conn.row_factory = sqlite3.Row
    return conn


def upsert_bach_agent(conn: sqlite3.Connection, agent: dict) -> dict:
    """Erstellt oder aktualisiert einen Agenten anhand seines eindeutigen Namens.

    Gibt {"success": True, "agent": {...}} oder
    {"success": False, "error": str, "status_code": int} zurueck.
    """
    _init_bach_agents(conn)
    name = agent.get("name")
    if not name:
        return {"success": False, "error": "Agent-Name fehlt", "status_code": 400}

    now = datetime.now().isoformat()
    defaults = {
        "display_name": name,
        "type": "agent",
        "category": None,
        "description": None,
        "skill_path": None,
        "user_data_folder": None,
        "parent_agent_id": None,
        "is_active": 1,
        "priority": 0,
        "requires_setup": 0,
        "setup_completed": 0,
        "usage_count": 0,
        "last_used": None,
        "version": "1.0.0",
        "dashboard": None,
        "language": None,
        "persona": None,
        "dist_type": None,
        "animus": None,
        "session_hook": None,
        "taskboard_id": None,
        "taskboard_default": 0,
    }
    merged = {**defaults, **agent, "updated_at": now}
    # Animus-Kanon validieren (GUI-OCEAN-03): ungueltige oder leere Werte
    # werden auf None gesetzt, damit Bestands-/Fremddaten den Serverstart nie brechen.
    animus_val = merged.get("animus")
    if isinstance(animus_val, str):
        animus_val = animus_val.strip().lower() or None
        if animus_val is not None and animus_val not in ANIMUS_TYPES:
            animus_val = None
    else:
        animus_val = None
    merged["animus"] = animus_val
    # created_at nur beim Insert setzen
    existing = conn.execute(
        "SELECT id FROM bach_agents WHERE name = ?", (name,)
    ).fetchone()
    if existing:
        allowed = {k: v for k, v in merged.items() if k in defaults or k == "updated_at"}
        if not allowed:
            return {"success": False, "error": "Keine gueltigen Felder", "status_code": 400}
        set_clause = ", ".join(f"{k} = ?" for k in allowed)
        values = list(allowed.values()) + [name]
        conn.execute(f"UPDATE bach_agents SET {set_clause} WHERE name = ?", values)
        conn.commit()
        agent_id = existing["id"]
    else:
        merged["created_at"] = now
        cols = [k for k in defaults if k not in {"updated_at"}] + ["created_at", "updated_at"]
        placeholders = ", ".join(["?"] * len(cols))
        values = [merged.get(c) for c in cols]
        cur = conn.execute(
            f"INSERT INTO bach_agents ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        agent_id = cur.lastrowid

    row = conn.execute("SELECT * FROM bach_agents WHERE id = ?", (agent_id,)).fetchone()
    return {"success": True, "agent": row_to_dict(row)}


# ═══════════════════════════════════════════════════════════════
# CLUSTER: Multi-Node-Verwaltung (Knoten, Token, Delegated Tasks)
# ═══════════════════════════════════════════════════════════════

def _init_cluster_tables(conn):
    """Legt die Cluster-Tabellen an, falls sie noch nicht existieren."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            url TEXT,
            token TEXT,
            role TEXT DEFAULT 'worker',
            status TEXT DEFAULT 'offline',
            capabilities TEXT,
            last_seen TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_node_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL REFERENCES cluster_nodes(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            label TEXT DEFAULT '',
            uses_left INTEGER,
            revoked INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_used_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_delegated_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            from_node_id INTEGER,
            to_node_id INTEGER,
            payload TEXT,
            direction TEXT DEFAULT 'outgoing',
            status TEXT DEFAULT 'pending',
            result TEXT,
            error TEXT,
            accepted_at TEXT,
            completed_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
    """)
    conn.commit()


def list_cluster_nodes(conn):
    """Listet alle Cluster-Nodes."""
    _init_cluster_tables(conn)
    rows = conn.execute("SELECT * FROM cluster_nodes ORDER BY id").fetchall()
    return {"success": True, "nodes": rows_to_list(rows)}


def create_cluster_node(conn, name, url=None, token=None, role="worker",
                        status="offline", capabilities=None):
    """Erstellt eine neue Cluster-Node."""
    _init_cluster_tables(conn)
    try:
        cur = conn.execute(
            "INSERT INTO cluster_nodes (name, url, token, role, status, capabilities) VALUES (?, ?, ?, ?, ?, ?)",
            (name, url, token, role, status, capabilities),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return {"success": False, "error": "Knoten existiert bereits", "status_code": 409}
    row = conn.execute("SELECT * FROM cluster_nodes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"success": True, "node": row_to_dict(row)}


def get_cluster_node(conn, node_id):
    """Liest eine Cluster-Node anhand ihrer ID."""
    _init_cluster_tables(conn)
    row = conn.execute("SELECT * FROM cluster_nodes WHERE id = ?", (node_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Cluster-Node nicht gefunden", "status_code": 404}
    return {"success": True, "node": row_to_dict(row)}


def update_cluster_node(conn, node_id, update_dict):
    """Aktualisiert zulaessige Felder einer Cluster-Node."""
    _init_cluster_tables(conn)
    allowed = {"name", "url", "token", "role", "status", "capabilities", "last_seen"}
    fields = {k: v for k, v in update_dict.items() if k in allowed}
    if not fields:
        return {"success": False, "error": "Keine gueltigen Felder", "status_code": 400}
    row = conn.execute("SELECT id FROM cluster_nodes WHERE id = ?", (node_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Cluster-Node nicht gefunden", "status_code": 404}
    set_parts = [f"{k} = ?" for k in fields]
    set_parts.append("updated_at = datetime('now')")
    params = list(fields.values()) + [node_id]
    conn.execute(
        "UPDATE cluster_nodes SET " + ", ".join(set_parts) + " WHERE id = ?",
        params,
    )
    conn.commit()
    new_row = conn.execute("SELECT * FROM cluster_nodes WHERE id = ?", (node_id,)).fetchone()
    return {"success": True, "node": row_to_dict(new_row)}


def delete_cluster_node(conn, node_id):
    """Loescht eine Cluster-Node (Tokens bleiben unberuehrt)."""
    _init_cluster_tables(conn)
    row = conn.execute("SELECT id FROM cluster_nodes WHERE id = ?", (node_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Cluster-Node nicht gefunden", "status_code": 404}
    conn.execute("DELETE FROM cluster_nodes WHERE id = ?", (node_id,))
    conn.commit()
    return {"success": True}


def create_cluster_node_token(conn, node_id, raw_token, label="", uses_left=None):
    """Erstellt einen Token-Hash-Eintrag fuer eine Cluster-Node."""
    _init_cluster_tables(conn)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    try:
        cur = conn.execute(
            "INSERT INTO cluster_node_tokens (node_id, token_hash, label, uses_left) VALUES (?, ?, ?, ?)",
            (node_id, token_hash, label, uses_left),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return {"success": False, "error": "Token existiert bereits", "status_code": 409}
    row = conn.execute("SELECT * FROM cluster_node_tokens WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"success": True, "token": row_to_dict(row)}


def validate_cluster_node_token(conn, node_id, raw_token):
    """Prueft einen Node-Token und aktualisiert last_seen und uses_left."""
    _init_cluster_tables(conn)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    row = conn.execute(
        "SELECT id FROM cluster_node_tokens WHERE node_id = ? AND token_hash = ? AND revoked = 0 AND (uses_left IS NULL OR uses_left > 0)",
        (node_id, token_hash),
    ).fetchone()
    if not row:
        return {"success": False, "error": "Ungueltiges Token", "status_code": 401}
    token_id = row[0]
    conn.execute(
        "UPDATE cluster_nodes SET last_seen = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (node_id,),
    )
    conn.execute(
        "UPDATE cluster_node_tokens SET last_used_at = datetime('now'), uses_left = CASE WHEN uses_left IS NULL THEN uses_left ELSE uses_left - 1 END WHERE id = ?",
        (token_id,),
    )
    conn.commit()
    node_row = conn.execute("SELECT last_seen FROM cluster_nodes WHERE id = ?", (node_id,)).fetchone()
    last_seen = node_row[0] if node_row else None
    return {"success": True, "last_seen": last_seen}


def list_cluster_node_tokens(conn, node_id):
    """Listet alle Tokens einer Cluster-Node."""
    _init_cluster_tables(conn)
    rows = conn.execute(
        "SELECT * FROM cluster_node_tokens WHERE node_id = ? ORDER BY id",
        (node_id,),
    ).fetchall()
    return {"success": True, "tokens": rows_to_list(rows)}


def revoke_cluster_node_token(conn, token_id):
    """Widerruft einen Token (revoked = 1)."""
    _init_cluster_tables(conn)
    row = conn.execute("SELECT id FROM cluster_node_tokens WHERE id = ?", (token_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Token nicht gefunden", "status_code": 404}
    conn.execute("UPDATE cluster_node_tokens SET revoked = 1 WHERE id = ?", (token_id,))
    conn.commit()
    return {"success": True}


def delete_cluster_node_token(conn, token_id):
    """Loescht einen Token vollstaendig."""
    _init_cluster_tables(conn)
    row = conn.execute("SELECT id FROM cluster_node_tokens WHERE id = ?", (token_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Token nicht gefunden", "status_code": 404}
    conn.execute("DELETE FROM cluster_node_tokens WHERE id = ?", (token_id,))
    conn.commit()
    return {"success": True}


def create_cluster_delegated_task(conn, task_id, from_node_id, to_node_id, payload="", direction="outgoing"):
    """Erstellt einen Delegated-Task zwischen Cluster-Nodes."""
    _init_cluster_tables(conn)
    cur = conn.execute(
        "INSERT INTO cluster_delegated_tasks (task_id, from_node_id, to_node_id, payload, direction) VALUES (?, ?, ?, ?, ?)",
        (task_id, from_node_id, to_node_id, payload, direction),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cluster_delegated_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"success": True, "delegation": row_to_dict(row)}


def list_cluster_delegated_tasks(conn, node_id=None, direction="both", status=None):
    """Listet Delegated Tasks, gefiltert nach Node, Richtung und Status."""
    _init_cluster_tables(conn)
    query = "SELECT * FROM cluster_delegated_tasks"
    where = []
    params = []
    if node_id is not None:
        if direction == "sent":
            where.append("from_node_id = ?")
            params.append(node_id)
        elif direction == "received":
            where.append("to_node_id = ?")
            params.append(node_id)
        else:
            where.append("(from_node_id = ? OR to_node_id = ?)")
            params.append(node_id)
            params.append(node_id)
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    return {"success": True, "delegations": rows_to_list(rows)}


def get_cluster_delegated_task(conn, delegation_id):
    """Liest einen Delegated-Task anhand seiner ID."""
    _init_cluster_tables(conn)
    row = conn.execute("SELECT * FROM cluster_delegated_tasks WHERE id = ?", (delegation_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Delegation nicht gefunden", "status_code": 404}
    return {"success": True, "delegation": row_to_dict(row)}


def update_cluster_delegated_task(conn, delegation_id, update_dict):
    """Aktualisiert Status, Ergebnis, Fehlertext, Payload oder task_id."""
    _init_cluster_tables(conn)
    allowed = {"status", "result", "error", "payload", "task_id"}
    fields = {k: v for k, v in update_dict.items() if k in allowed}
    if not fields:
        return {"success": False, "error": "Keine gueltigen Felder", "status_code": 400}
    row = conn.execute("SELECT id FROM cluster_delegated_tasks WHERE id = ?", (delegation_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Delegation nicht gefunden", "status_code": 404}
    set_parts = [f"{k} = ?" for k in fields]
    set_parts.append("updated_at = datetime('now')")
    if fields.get("status") == "accepted":
        set_parts.append("accepted_at = datetime('now')")
    if fields.get("status") == "completed":
        set_parts.append("completed_at = datetime('now')")
    params = list(fields.values()) + [delegation_id]
    conn.execute(
        "UPDATE cluster_delegated_tasks SET " + ", ".join(set_parts) + " WHERE id = ?",
        params,
    )
    conn.commit()
    new_row = conn.execute("SELECT * FROM cluster_delegated_tasks WHERE id = ?", (delegation_id,)).fetchone()
    return {"success": True, "delegation": row_to_dict(new_row)}


def delete_cluster_delegated_task(conn, delegation_id):
    """Loescht einen Delegated-Task."""
    _init_cluster_tables(conn)
    row = conn.execute("SELECT id FROM cluster_delegated_tasks WHERE id = ?", (delegation_id,)).fetchone()
    if not row:
        return {"success": False, "error": "Delegation nicht gefunden", "status_code": 404}
    conn.execute("DELETE FROM cluster_delegated_tasks WHERE id = ?", (delegation_id,))
    conn.commit()
    return {"success": True}
