# BACH Adapter: seam_microtasks
"""BACH-to-ELLMOS Migration: Seam Micro-Tasks Catalog & Execution Pipeline (Ticket T-20260909-566626503).

Defines the isolated 5 Seam Micro-Tasks (M1-M5), idempotent seeding, safety preflight,
and the escalation cascade to Claude.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# ── Catalog of the 5 Seam Micro-Tasks (WP1) ──
MICRO_TASK_CATALOG: List[Dict[str, Any]] = [
    {
        "code": "M1",
        "title": "[Migration M1] session_store.py Seam-Adapter auf ellmos_chat.store",
        "category": "migration-seam",
        "priority": "high",
        "target_module": "system/hub/_services/chat/session_store.py",
        "external_target": "ellmos_chat.store",
        "acceptance_command": "pytest system/tests/test_chat_session_store.py",
        "depends_on": None,
        "description": (
            "Seam-Adapter für session_store.py mit Fallback auf lokale SQLiteChatSessionStore "
            "Implementierung. Ermöglicht modulare Verlagerung an ellmos_chat.store ohne Regressionen."
        ),
    },
    {
        "code": "M2",
        "title": "[Migration M2] Chat-Snapshots Archivierungs-Seam auf session-checkpoint",
        "category": "migration-seam",
        "priority": "normal",
        "target_module": "system/hub/_services/chat/snapshot.py",
        "external_target": "session-checkpoint",
        "acceptance_command": "pytest system/tests/test_session_checkpoint_adapter.py",
        "depends_on": "M1",
        "description": (
            "Auslagerung der Snapshot-Archivierung an das kanonische session-checkpoint Modul "
            "mit lokaler atomarer Rückfallebene in bach.db."
        ),
    },
    {
        "code": "M3",
        "title": "[Migration M3] Task-Reader Seam in routes_tasks.py auf ticket-master",
        "category": "migration-seam",
        "priority": "normal",
        "target_module": "system/gui/routes_tasks.py",
        "external_target": "ticket-master",
        "acceptance_command": "pytest system/tests/test_routes_tasks.py",
        "depends_on": "M2",
        "description": (
            "Task-Abfragen und Queue-Reader an autoritative ticket-master Schnittstelle anbinden. "
            "Legacy-Tabellenabfragen bleiben als Rückfallebene erhalten."
        ),
    },
    {
        "code": "M4",
        "title": "[Migration M4] Prompt-Provider Seam in chat_tray.py auf PromptBoard",
        "category": "migration-seam",
        "priority": "normal",
        "target_module": "system/hub/_services/chat/chat_tray.py",
        "external_target": "PromptBoard",
        "acceptance_command": "pytest system/tests/test_chat_tray_monitoring.py",
        "depends_on": "M3",
        "description": (
            "Favoriten- und Quick-Prompts über PromptBoard Provider laden und synchronisieren. "
            "Offline-Fallback auf lokale Prompts sichergestellt."
        ),
    },
    {
        "code": "M5",
        "title": "[Migration M5] Deprecation von Legacy-Tools in system/tools/",
        "category": "migration-seam",
        "priority": "normal",
        "target_module": "system/tools/",
        "external_target": "ellmos-core",
        "acceptance_command": "pytest system/tests/test_imported_capabilities.py",
        "depends_on": "M4",
        "description": (
            "Legacy-Tools als deprecated wrapper markieren und kanonische Importe aus ellmos-core "
            "etablieren."
        ),
    },
]


def get_default_db_path() -> Path:
    """Resolve default database path."""
    try:
        from hub.bach_paths import BACH_DB
        if BACH_DB.exists():
            return BACH_DB
    except Exception:
        pass
    return REPO_ROOT / "system" / "hub" / "bach.db"


def ensure_seam_microtasks(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Idempotently seed the 5 migration micro-tasks M1-M5 into bach.db (tasks table).

    Returns a summary dict with created, existing, and task_ids.
    """
    path = db_path or get_default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'normal',
            category TEXT,
            assigned_to TEXT,
            source TEXT,
            result TEXT,
            depends_on TEXT,
            claimed_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    results = {}
    created_count = 0
    existing_count = 0

    for m in MICRO_TASK_CATALOG:
        code = m["code"]
        source_key = f"migration:{code}"

        cursor.execute("SELECT id, status, assigned_to FROM tasks WHERE source = ? ORDER BY id DESC LIMIT 1", (source_key,))
        row = cursor.fetchone()

        if row:
            results[code] = {"id": row["id"], "status": row["status"], "created": False}
            existing_count += 1
        else:
            full_desc = (
                f"{m['description']}\n\n"
                f"Micro-Task-Code: {code}\n"
                f"Target-Modul: {m['target_module']}\n"
                f"Externes Modul: {m['external_target']}\n"
                f"Akzeptanzkriterium: {m['acceptance_command']}\n"
                f"Abhaengigkeit: {m['depends_on'] or 'keine'}"
            )
            cursor.execute("""
                INSERT INTO tasks (title, description, status, priority, category, assigned_to, source, depends_on, created_at, updated_at)
                VALUES (?, ?, 'pending', ?, ?, 'BUDDHA', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (m["title"], full_desc, m["priority"], m["category"], source_key, m["depends_on"]))
            new_id = cursor.lastrowid
            results[code] = {"id": new_id, "status": "pending", "created": True}
            created_count += 1

    conn.commit()
    conn.close()

    return {
        "success": True,
        "created_count": created_count,
        "existing_count": existing_count,
        "tasks": results,
    }


def run_microtask_preflight(
    task_code_or_id: Any,
    repo_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
    allow_untracked: bool = True,
) -> Dict[str, Any]:
    """Safety Preflight Check (WP2): Git clean check, Lock check, and Dependency check.

    Must pass before Buddha claims or executes a micro-task.
    """
    root = repo_path or REPO_ROOT
    path = db_path or get_default_db_path()

    # 1. Dependency check in DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if isinstance(task_code_or_id, int) or (isinstance(task_code_or_id, str) and task_code_or_id.isdigit()):
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (int(task_code_or_id),))
    else:
        source_key = f"migration:{task_code_or_id}"
        cursor.execute("SELECT * FROM tasks WHERE source = ? ORDER BY id DESC LIMIT 1", (source_key,))

    task_row = cursor.fetchone()
    if not task_row:
        conn.close()
        return {"ok": False, "reason": "task_not_found", "message": f"Task {task_code_or_id} nicht gefunden"}

    task_dict = dict(task_row)
    depends_on = task_dict.get("depends_on")

    if depends_on:
        dep_source = f"migration:{depends_on}"
        cursor.execute("SELECT status FROM tasks WHERE source = ? ORDER BY id DESC LIMIT 1", (dep_source,))
        dep_row = cursor.fetchone()
        if not dep_row or dep_row["status"] not in ("completed", "done", "passed"):
            conn.close()
            return {
                "ok": False,
                "reason": "dependency_unmet",
                "message": f"Abhängigkeit {depends_on} ist noch nicht abgeschlossen (Status: {dep_row['status'] if dep_row else 'nicht gefunden'})",
            }

    conn.close()

    # 2. Lock check: Scan repository directory for active lock files
    lock_patterns = ["LOCK.user*", "LOCK.txt", "LOCK.until*", "LOCK.condition*"]
    found_locks = []
    for pattern in lock_patterns:
        found_locks.extend([str(p) for p in root.glob(pattern)])
        # Also check .TOPICS twin if relevant
    if found_locks:
        return {
            "ok": False,
            "reason": "lock_active",
            "message": f"Repository gesperrt durch Lock-Dateien: {found_locks}",
            "locks": found_locks,
        }

    # 3. Git clean check
    try:
        git_res = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if git_res.returncode == 0:
            lines = git_res.stdout.strip().splitlines()
            dirty_lines = [l for l in lines if not allow_untracked or not l.startswith("??")]
            if dirty_lines:
                return {
                    "ok": False,
                    "reason": "git_dirty",
                    "message": "Arbeitsverzeichnis enthält ungesicherte Änderungen",
                    "changes": dirty_lines,
                }
    except Exception as e:
        logger.warning(f"Git clean check warning: {e}")

    return {
        "ok": True,
        "task_id": task_dict["id"],
        "source": task_dict["source"],
        "status": task_dict["status"],
    }


def claim_microtask(
    task_id: int,
    worker_id: str = "buddha@macstudio",
    db_path: Optional[Path] = None,
) -> bool:
    """Atomically claim a microtask for Buddha."""
    path = db_path or get_default_db_path()
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tasks
        SET claimed_by = ?, status = 'in_progress', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'pending'
    """, (worker_id, task_id))
    claimed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return claimed


def escalate_failed_microtask(
    task_id: int,
    error_log: str,
    attempt_count: int,
    max_attempts: int = 3,
    target_agent: str = "CLAUDE",
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Escalation handler (WP3): After max_attempts (default 3), hands task over to Claude."""
    path = db_path or get_default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return {"success": False, "error": f"Task #{task_id} nicht gefunden"}

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if attempt_count >= max_attempts:
        current_desc = task["description"] or ""
        escalation_notice = (
            f"\n\n--- ESKALATION AN {target_agent} [{timestamp}] ---\n"
            f"Grund: Micro-Task nach {attempt_count} Runden fehlgeschlagen.\n"
            f"Pytest-Fehlerprotokoll:\n{error_log}"
        )
        cursor.execute("""
            UPDATE tasks
            SET assigned_to = ?, status = 'delegated', description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (target_agent, current_desc + escalation_notice, task_id))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "escalated": True,
            "task_id": task_id,
            "attempt": attempt_count,
            "assigned_to": target_agent,
            "status": "delegated",
        }
    else:
        # Record retry attempt
        cursor.execute("""
            UPDATE tasks
            SET status = 'pending', result = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (f"Versuch {attempt_count} fehlgeschlagen: {error_log[:200]}", task_id))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "escalated": False,
            "task_id": task_id,
            "attempt": attempt_count,
            "status": "pending",
        }


def complete_microtask(
    task_id: int,
    result_summary: str,
    db_path: Optional[Path] = None,
) -> bool:
    """Mark a micro-task as completed upon green pytest run."""
    path = db_path or get_default_db_path()
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tasks
        SET status = 'completed', result = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (result_summary, task_id))
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok
