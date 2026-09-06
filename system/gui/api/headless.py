#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
BACH Headless REST-API Server
==============================

Pure JSON API fuer programmatischen Zugriff auf BACH.
Getrennt vom GUI-Server (Port 8000), laeuft auf Port 8001.

Endpoints:
  GET  /api/v1/tasks             Tasks auflisten
  POST /api/v1/tasks             Task erstellen
  PUT  /api/v1/tasks/{id}        Task aktualisieren
  GET  /api/v1/tasks/{id}        Task-Details
  GET  /api/v1/memory/facts      Fakten abrufen
  GET  /api/v1/memory/lessons    Lessons abrufen
  GET  /api/v1/memory/search     Memory durchsuchen
  POST /api/v1/messages/send     Nachricht in Queue einreihen
  GET  /api/v1/messages/queue    Queue-Status
  GET  /api/v1/messages/inbox    Inbox lesen (Paginierung)
  POST /api/v1/messages/route    Routing manuell ausloesen
  GET  /api/v1/status            System-Status
  POST /api/v1/backup            Backup erstellen
  GET  /api/v1/skills            Skills auflisten
  GET  /api/v1/health            Health-Check

Auth:
  - Localhost: Kein Auth noetig (Trust-Modus)
  - Remote: X-BACH-Key Header oder ?api_key= Parameter

Start:
  python gui/api/headless.py [--port 8001] [--key YOUR_API_KEY]

Swagger Docs:
  http://localhost:8001/api/docs
"""

import os
import sys
import json
import sqlite3
import secrets
import hashlib
import hmac
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

# BACH Root
BACH_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BACH_ROOT))

# Zentrale Registry ist Pflicht — ein ImportError-Fallback auf einen selbst
# gebauten Pfad zeigte still auf die veraltete Repo-/Cloud-Kopie
# (test_db_path_central, T-20260901-202368596). sys.path steht oben bereits.
from hub.bach_paths import BACH_DB as _PATHS_DB, BACKUPS_DIR
from hub.task_audit import apply_task_field_changes
BACH_DB = str(_PATHS_DB)

try:
    from fastapi import FastAPI, HTTPException, Depends, Request, Query
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("FastAPI nicht installiert. Bitte: pip install fastapi uvicorn")
    sys.exit(1)


# ------------------------------------------------------------------
# App & Auth
# ------------------------------------------------------------------

app = FastAPI(
    title="BACH Headless API",
    description="Programmatischer Zugriff auf BACH Personal Assistant",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key (generiert beim ersten Start oder per --key)
API_KEY: Optional[str] = None
KEY_FILE = BACH_ROOT / "data" / ".api_key.sha256"
LEGACY_KEY_FILE = BACH_ROOT / "data" / ".api_key"
API_KEY_HASH: Optional[str] = None


def _hash_key(key: str, salt: Optional[str] = None) -> str:
    rounds = 200000
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        key.encode("utf-8"),
        bytes.fromhex(salt),
        rounds,
    ).hex()
    return f"pbkdf2_sha256${rounds}${salt}${digest}"


def _check_key_hash(candidate: str, stored: str) -> bool:
    try:
        algorithm, rounds_text, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            candidate.encode("utf-8"),
            bytes.fromhex(salt),
            int(rounds_text),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def _write_key_hash(key_hash: str):
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key_hash)


def _load_or_generate_key() -> str:
    global API_KEY, API_KEY_HASH
    if API_KEY:
        API_KEY_HASH = API_KEY_HASH or _hash_key(API_KEY)
        return API_KEY
    if KEY_FILE.exists():
        API_KEY_HASH = KEY_FILE.read_text(encoding="utf-8").strip()
        return ""
    if LEGACY_KEY_FILE.exists():
        legacy_key = LEGACY_KEY_FILE.read_text(encoding="utf-8").strip()
        API_KEY_HASH = _hash_key(legacy_key)
        _write_key_hash(API_KEY_HASH)
        try:
            LEGACY_KEY_FILE.unlink()
        except OSError:
            pass
        return ""

    API_KEY = secrets.token_urlsafe(32)
    API_KEY_HASH = _hash_key(API_KEY)
    _write_key_hash(API_KEY_HASH)
    return API_KEY


def _verify_api_key(candidate: str) -> bool:
    global API_KEY_HASH
    _load_or_generate_key()
    if not candidate or not API_KEY_HASH:
        return False
    return _check_key_hash(candidate, API_KEY_HASH)


def _get_db():
    conn = sqlite3.connect(BACH_DB)
    conn.row_factory = sqlite3.Row
    return conn


async def verify_auth(request: Request, api_key: Optional[str] = Query(None)):
    """Auth-Check: Localhost = Trust, Remote = API-Key."""
    client = request.client.host if request.client else "unknown"
    if client in ("127.0.0.1", "::1", "localhost"):
        return True

    key = request.headers.get("X-BACH-Key") or api_key
    if not _verify_api_key(key or ""):
        raise HTTPException(status_code=401, detail="Unauthorized. Provide X-BACH-Key header or api_key parameter.")
    return True


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------

class TaskCreate(BaseModel):
    title: str
    priority: str = "P3"
    category: str = "general"
    assigned_to: str = ""
    description: str = ""

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    description: Optional[str] = None
    # T-20260906-240256515: optionaler Aufrufer-Bezeichner fuer task_history.changed_by,
    # analog zu TaskUpdate.changed_by im GUI-Server. Externe API-Clients identifizieren
    # sich damit; ohne Angabe greift der Default "headless-api" (siehe update_task).
    changed_by: Optional[str] = None

class MemoryWrite(BaseModel):
    content: str
    type: str = "note"
    tags: str = ""


# ------------------------------------------------------------------
# Task Endpoints
# ------------------------------------------------------------------

@app.get("/api/v1/tasks")
async def list_tasks(status: str = "pending", limit: int = 50,
                     priority: str = "", _=Depends(verify_auth)):
    conn = _get_db()
    try:
        query = "SELECT id, title, priority, status, category, assigned_to, created_at FROM tasks WHERE 1=1"
        params = []
        if status != "all":
            query += " AND status = ?"
            params.append(status)
        if priority:
            query += " AND priority = ?"
            params.append(priority)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return {"tasks": [dict(r) for r in rows], "count": len(rows)}
    finally:
        conn.close()


@app.post("/api/v1/tasks", status_code=201)
async def create_task(task: TaskCreate, _=Depends(verify_auth)):
    conn = _get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute("""
            INSERT INTO tasks (title, priority, category, status, assigned_to, description, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
        """, (task.title, task.priority, task.category,
              task.assigned_to or None, task.description, now, now))
        conn.commit()
        return {"id": cur.lastrowid, "title": task.title, "status": "pending"}
    finally:
        conn.close()


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: int, _=Depends(verify_auth)):
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Task nicht gefunden")
        return dict(row)
    finally:
        conn.close()


@app.put("/api/v1/tasks/{task_id}")
async def update_task(task_id: int, update: TaskUpdate, _=Depends(verify_auth)):
    """Aktualisiert Task in bach.db und protokolliert jede Feldaenderung in task_history.

    T-20260906-240256515: Hatte dieselbe Luecke wie der GUI-Server (T-20260906-985973908,
    system/gui/server.py) -- kein task_history-Schreibpfad, started_at nie gesetzt. Die
    Schreiblogik liegt jetzt zentral in hub.task_audit.apply_task_field_changes (von
    system/gui/server.py gleichermassen genutzt); hier nur noch die Headless-eigene
    Feldabbildung -- die TaskUpdate-Felder hier entsprechen 1:1 den `tasks`-Spalten,
    anders als GUI's `project` -> `category`-Alias.
    """
    conn = _get_db()
    try:
        existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Task nicht gefunden")
        existing_row = dict(existing)

        field_values = update.model_dump(exclude_none=True, exclude={"changed_by"})
        if not field_values:
            raise HTTPException(400, "Keine Felder zum Aktualisieren")

        # Zeitformat bewusst wie im Rest von headless.py belassen (kein isoformat() wie
        # im GUI-Server) -- apply_task_field_changes ist formatagnostisch, nur konsistent
        # innerhalb dieser API sollte es bleiben.
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        changed_by = update.changed_by or "headless-api"

        if apply_task_field_changes(conn, task_id, existing_row, field_values,
                                     changed_by=changed_by, now=now):
            conn.commit()

        return {"id": task_id, "updated": True}
    finally:
        conn.close()


# ------------------------------------------------------------------
# Memory Endpoints
# ------------------------------------------------------------------

@app.get("/api/v1/memory/facts")
async def get_facts(category: str = "", min_confidence: float = 0.0,
                    _=Depends(verify_auth)):
    conn = _get_db()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM memory_facts WHERE category = ? AND confidence >= ?",
                (category, min_confidence)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_facts WHERE confidence >= ?",
                (min_confidence,)).fetchall()
        return {"facts": [dict(r) for r in rows], "count": len(rows)}
    finally:
        conn.close()


@app.get("/api/v1/memory/lessons")
async def get_lessons(limit: int = 30, category: str = "",
                      _=Depends(verify_auth)):
    conn = _get_db()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM memory_lessons WHERE category = ? AND is_active = 1 ORDER BY created_at DESC LIMIT ?",
                (category, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_lessons WHERE is_active = 1 ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return {"lessons": [dict(r) for r in rows], "count": len(rows)}
    finally:
        conn.close()


@app.get("/api/v1/memory/search")
async def search_memory(q: str, _=Depends(verify_auth)):
    conn = _get_db()
    try:
        like = f"%{q}%"
        lessons = conn.execute("""
            SELECT id, title, solution, category FROM memory_lessons
            WHERE is_active = 1 AND (title LIKE ? OR solution LIKE ?)
            LIMIT 20
        """, (like, like)).fetchall()

        facts = conn.execute("""
            SELECT id, category, key, value FROM memory_facts
            WHERE key LIKE ? OR value LIKE ? LIMIT 20
        """, (like, like)).fetchall()

        return {
            "lessons": [dict(r) for r in lessons],
            "facts": [dict(r) for r in facts],
        }
    finally:
        conn.close()


@app.post("/api/v1/memory")
async def write_memory(entry: MemoryWrite, _=Depends(verify_auth)):
    conn = _get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute("""
            INSERT INTO memory_working (type, content, tags, created_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (entry.type, entry.content, entry.tags, now))
        conn.commit()
        return {"id": cur.lastrowid, "stored": True}
    finally:
        conn.close()


# ------------------------------------------------------------------
# System Endpoints
# ------------------------------------------------------------------

@app.get("/api/v1/status")
async def system_status(_=Depends(verify_auth)):
    conn = _get_db()
    try:
        tasks_total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        tasks_done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'done'").fetchone()[0]
        tasks_pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'").fetchone()[0]
        facts = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
        lessons = conn.execute("SELECT COUNT(*) FROM memory_lessons WHERE is_active = 1").fetchone()[0]
        sessions = conn.execute("SELECT COUNT(*) FROM memory_sessions").fetchone()[0]

        db_size = os.path.getsize(BACH_DB) / (1024 * 1024)

        return {
            "version": "3.3.0",
            "db_size_mb": round(db_size, 1),
            "tasks": {"total": tasks_total, "done": tasks_done, "pending": tasks_pending},
            "memory": {"facts": facts, "lessons": lessons, "sessions": sessions},
        }
    finally:
        conn.close()


@app.get("/api/v1/skills")
async def list_skills(type: str = "", limit: int = 100, _=Depends(verify_auth)):
    conn = _get_db()
    try:
        if type:
            rows = conn.execute(
                "SELECT name, type, category, version, is_active FROM skills WHERE type = ? AND is_active = 1 LIMIT ?",
                (type, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, type, category, version, is_active FROM skills WHERE is_active = 1 LIMIT ?",
                (limit,)).fetchall()
        return {"skills": [dict(r) for r in rows], "count": len(rows)}
    finally:
        conn.close()


@app.post("/api/v1/backup")
async def create_backup(_=Depends(verify_auth)):
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUPS_DIR / "api"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"bach_api_{now}.db"
    try:
        shutil.copy2(BACH_DB, str(backup_path))
        size_kb = backup_path.stat().st_size / 1024
        return {"backup": str(backup_path), "size_kb": round(size_kb)}
    except Exception as e:
        raise HTTPException(500, f"Backup fehlgeschlagen: {e}")


@app.get("/api/v1/health")
async def health_check():
    """Oeffentlicher Health-Check (kein Auth noetig)."""
    db_ok = os.path.exists(BACH_DB)
    return {"status": "ok" if db_ok else "error", "db": db_ok, "timestamp": datetime.now().isoformat()}


# ------------------------------------------------------------------
# Messages API (Queue, Inbox, Routing)
# ------------------------------------------------------------------

from gui.api.messages_api import router as messages_router
app.include_router(messages_router)


# ------------------------------------------------------------------
# Start
# ------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BACH Headless API")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--key", help="API Key (sonst auto-generiert)")
    args = parser.parse_args()

    if args.key:
        API_KEY = args.key
    else:
        _load_or_generate_key()

    print(f"BACH Headless API v1.0.0")
    print(f"  Port: {args.port}")
    print(f"  DB: {BACH_DB}")
    print(f"  Docs: http://localhost:{args.port}/api/docs")
    if API_KEY:
        print(f"  API-Key: neu generiert (Hash gespeichert in {KEY_FILE})")
    else:
        print(f"  API-Key-Hash: {KEY_FILE}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
