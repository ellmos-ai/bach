#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
Worker-Plan -- Persistente Plaene und Todos fuer Bridge-Worker (Task #1596)
===========================================================================

Bridge-Worker sind stateless Subprozesse (--no-session-persistence): Ein
Worker-Lauf weiss nach Beenden nichts mehr von seinem Stand. Dieses Modul
gibt Workern einen persistenen Plan-/Todo-Speicher in BACH_DB:

- Worker schreibt zu Beginn einen Plan mit Todos nieder (create_plan).
- Er erledigt Todos und markiert sie (mark_done).
- Bei Blocker: status='blocked' (set_todo_status / set_plan_status).
- Fortsetzung nach Unterbrechung: Ein neuer Worker-Lauf laedt offene Todos
  (resume_plan / list_open) und arbeitet weiter.
- Tageslogik: 34h Arbeitszeit = 1 Arbeitstag -> bump_day erhoeht day_index.

Tabellen:
  worker_plans (plan_id, task_description, plan_text, status,
                day_index, created_at, updated_at)
  worker_todos (todo_id, plan_id, todo_text, status, position,
                day_index, created_at, done_at)

Das Modul ist absichtlich frei von bridge_daemon.py (kein Import), damit es
vom Daemon, von Workern und von Standalone-Skripten importiert werden kann.

CLI (fuer Worker-Subprozesse):
  python hub/_services/worker_plan.py create --task "..." --plan "..." \
      --todo "Erstens" --todo "Zweitens"
  python hub/_services/worker_plan.py list [--plan-id N]
  python hub/_services/worker_plan.py resume --plan-id N
  python hub/_services/worker_plan.py done --todo-id N
  python hub/_services/worker_plan.py blocked --todo-id N
  python hub/_services/worker_plan.py plan-done --plan-id N
  python hub/_services/worker_plan.py bump-day --plan-id N
Ausgabe jeweils als JSON auf stdout.
"""

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Universal-Import fuer bach_paths (Muster: fackeltraeger.py) ----------
_current = Path(__file__).resolve()
for _parent in [_current] + list(_current.parents):
    _hub = _parent / "hub"
    if _hub.exists() and (_hub / "bach_paths.py").exists():
        if str(_hub) not in sys.path:
            sys.path.insert(0, str(_hub))
        break
from bach_paths import BACH_DB

# --- Konstanten -----------------------------------------------------------
TABLE_PLANS = "worker_plans"
TABLE_TODOS = "worker_todos"

VALID_PLAN_STATUS = ("open", "in_progress", "done", "blocked")
VALID_TODO_STATUS = ("open", "done", "blocked")


# --- Dataclasses ----------------------------------------------------------

@dataclass
class WorkerPlan:
    """Leseansicht eines Worker-Plans."""
    plan_id: int
    task_description: str
    plan_text: str = ""
    status: str = "open"          # open | in_progress | done | blocked
    day_index: int = 0            # Arbeitstage (34h Arbeitszeit = 1 Tag)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerTodo:
    """Leseansicht eines Worker-Todos."""
    todo_id: int
    plan_id: int
    todo_text: str
    status: str = "open"          # open | done | blocked
    position: int = 0
    day_index: int = 0
    created_at: str = ""
    done_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- DB-Schema ------------------------------------------------------------

def _ensure_table() -> None:
    """Erstellt die Tabellen `worker_plans`/`worker_todos` falls sie fehlen."""
    db_path = Path(BACH_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_PLANS} (
            plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_description TEXT NOT NULL,
            plan_text TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            day_index INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_TODOS} (
            todo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            todo_text TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            position INTEGER DEFAULT 0,
            day_index INTEGER DEFAULT 0,
            created_at TEXT,
            done_at TEXT,
            FOREIGN KEY (plan_id) REFERENCES {TABLE_PLANS}(plan_id)
        )
    """)
    # Migration: day_index-Spalten nachtragen, falls aus frueherem Schema
    for table in (TABLE_PLANS, TABLE_TODOS):
        try:
            cur.execute(f"SELECT day_index FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN day_index INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def _db_execute(
    query: str,
    params: Tuple = (),
    fetch: bool = False,
    fetchone: bool = False,
    return_id: bool = False,
    retries: int = 3,
) -> Any:
    """Kleiner SQLite-Wrapper mit Retry bei 'database is locked'.

    return_id=True liefert cur.lastrowid (fuer INSERTs).
    fetch=True liefert Rows (sqlite3.Row), fetchone=True nur die erste.
    """
    _ensure_table()
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(str(BACH_DB), timeout=10)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()
            result = None
            if fetch:
                result = cur.fetchone() if fetchone else cur.fetchall()
            elif return_id:
                result = cur.lastrowid
            conn.close()
            return result
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
    if last_err is not None:
        raise last_err
    return None


# --- Row-Konverter ----------------------------------------------------------

def _row_to_plan(row: sqlite3.Row) -> WorkerPlan:
    return WorkerPlan(
        plan_id=row["plan_id"],
        task_description=row["task_description"],
        plan_text=row["plan_text"] or "",
        status=row["status"] or "open",
        day_index=row["day_index"] or 0,
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _row_to_todo(row: sqlite3.Row) -> WorkerTodo:
    return WorkerTodo(
        todo_id=row["todo_id"],
        plan_id=row["plan_id"],
        todo_text=row["todo_text"],
        status=row["status"] or "open",
        position=row["position"] or 0,
        day_index=row["day_index"] or 0,
        created_at=row["created_at"] or "",
        done_at=row["done_at"],
    )


# --- API -------------------------------------------------------------------

def create_plan(
    task_description: str,
    plan_text: str = "",
    todos: Optional[List[str]] = None,
    day_index: int = 0,
) -> int:
    """Legt einen Plan an, optional mit Todo-Liste. Liefert plan_id."""
    now = datetime.now().isoformat()
    plan_id = _db_execute(
        f"""
        INSERT INTO {TABLE_PLANS}
            (task_description, plan_text, status, day_index, created_at, updated_at)
        VALUES (?, ?, 'open', ?, ?, ?)
        """,
        (task_description, plan_text, day_index, now, now),
        return_id=True,
    )
    for pos, todo_text in enumerate(todos or []):
        add_todo(plan_id, todo_text, position=pos, day_index=day_index)
    return plan_id


def add_todo(
    plan_id: int,
    todo_text: str,
    position: Optional[int] = None,
    day_index: Optional[int] = None,
) -> int:
    """Fuegt ein Todo zu einem Plan hinzu. Liefert todo_id."""
    if position is None:
        row = _db_execute(
            f"SELECT MAX(position) AS max_pos FROM {TABLE_TODOS} WHERE plan_id = ?",
            (plan_id,),
            fetch=True, fetchone=True,
        )
        position = ((row["max_pos"] if row else None) or -1) + 1
    if day_index is None:
        plan = get_plan(plan_id)
        day_index = plan.day_index if plan else 0
    now = datetime.now().isoformat()
    return _db_execute(
        f"""
        INSERT INTO {TABLE_TODOS}
            (plan_id, todo_text, status, position, day_index, created_at)
        VALUES (?, ?, 'open', ?, ?, ?)
        """,
        (plan_id, todo_text, position, day_index, now),
        return_id=True,
    )


def get_plan(plan_id: int) -> Optional[WorkerPlan]:
    """Liefert einen Plan oder None."""
    row = _db_execute(
        f"SELECT * FROM {TABLE_PLANS} WHERE plan_id = ?",
        (plan_id,),
        fetch=True, fetchone=True,
    )
    return _row_to_plan(row) if row else None


def list_open(plan_id: Optional[int] = None) -> Dict[str, Any]:
    """Listet offene Plaene und deren offene Todos.

    Ohne plan_id: alle Plaene mit status != 'done'.
    Mit plan_id: nur dieser Plan (auch wenn erledigt, dann leere Todo-Liste).
    Rueckgabe: {"plans": [...], "todos": {plan_id: [...]}}
    """
    if plan_id is not None:
        plan_rows = _db_execute(
            f"SELECT * FROM {TABLE_PLANS} WHERE plan_id = ? ORDER BY plan_id",
            (plan_id,),
            fetch=True,
        )
    else:
        plan_rows = _db_execute(
            f"SELECT * FROM {TABLE_PLANS} WHERE status != 'done' ORDER BY plan_id",
            fetch=True,
        )
    plans = [_row_to_plan(r) for r in (plan_rows or [])]
    todos: Dict[int, List[Dict[str, Any]]] = {}
    for plan in plans:
        todo_rows = _db_execute(
            f"""
            SELECT * FROM {TABLE_TODOS}
            WHERE plan_id = ? AND status != 'done'
            ORDER BY position, todo_id
            """,
            (plan.plan_id,),
            fetch=True,
        )
        todos[plan.plan_id] = [_row_to_todo(r).to_dict() for r in (todo_rows or [])]
    return {
        "plans": [p.to_dict() for p in plans],
        "todos": todos,
    }


def set_todo_status(todo_id: int, status: str) -> bool:
    """Setzt den Status eines Todos. done_at wird bei 'done' gesetzt."""
    if status not in VALID_TODO_STATUS:
        raise ValueError(f"Ungueltiger Todo-Status: {status} (erlaubt: {VALID_TODO_STATUS})")
    done_at = datetime.now().isoformat() if status == "done" else None
    if status == "done":
        _db_execute(
            f"UPDATE {TABLE_TODOS} SET status = ?, done_at = ? WHERE todo_id = ?",
            (status, done_at, todo_id),
        )
    else:
        _db_execute(
            f"UPDATE {TABLE_TODOS} SET status = ?, done_at = NULL WHERE todo_id = ?",
            (status, todo_id),
        )
    row = _db_execute(
        f"SELECT todo_id FROM {TABLE_TODOS} WHERE todo_id = ?",
        (todo_id,),
        fetch=True, fetchone=True,
    )
    return row is not None


def mark_done(todo_id: int) -> bool:
    """Markiert ein Todo als erledigt."""
    return set_todo_status(todo_id, "done")


def mark_blocked(todo_id: int) -> bool:
    """Markiert ein Todo als blockiert."""
    return set_todo_status(todo_id, "blocked")


def set_plan_status(plan_id: int, status: str) -> bool:
    """Setzt den Status eines Plans."""
    if status not in VALID_PLAN_STATUS:
        raise ValueError(f"Ungueltiger Plan-Status: {status} (erlaubt: {VALID_PLAN_STATUS})")
    now = datetime.now().isoformat()
    _db_execute(
        f"UPDATE {TABLE_PLANS} SET status = ?, updated_at = ? WHERE plan_id = ?",
        (status, now, plan_id),
    )
    return get_plan(plan_id) is not None


def mark_plan_done(plan_id: int) -> bool:
    """Markiert einen Plan als erledigt."""
    return set_plan_status(plan_id, "done")


def resume_plan(plan_id: int) -> Tuple[Optional[WorkerPlan], List[WorkerTodo]]:
    """Laedt einen Plan zur Fortsetzung nach Unterbrechung.

    Setzt status auf 'in_progress' (aus open/blocked) und liefert
    (plan, offene Todos sortiert nach position).
    """
    plan = get_plan(plan_id)
    if plan is None:
        return None, []
    if plan.status in ("open", "blocked"):
        set_plan_status(plan_id, "in_progress")
        plan.status = "in_progress"
    todo_rows = _db_execute(
        f"""
        SELECT * FROM {TABLE_TODOS}
        WHERE plan_id = ? AND status != 'done'
        ORDER BY position, todo_id
        """,
        (plan_id,),
        fetch=True,
    )
    return plan, [_row_to_todo(r) for r in (todo_rows or [])]


def bump_day(plan_id: int) -> int:
    """Erhoeht day_index um 1 (34h Arbeitszeit = 1 Arbeitstag).

    Liefert den neuen day_index. Wirft ValueError bei unbekanntem Plan.
    """
    plan = get_plan(plan_id)
    if plan is None:
        raise ValueError(f"Unbekannter Plan: {plan_id}")
    new_index = plan.day_index + 1
    now = datetime.now().isoformat()
    _db_execute(
        f"UPDATE {TABLE_PLANS} SET day_index = ?, updated_at = ? WHERE plan_id = ?",
        (new_index, now, plan_id),
    )
    return new_index


# --- CLI (fuer Worker-Subprozesse) -----------------------------------------

def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="worker_plan",
        description="Persistente Plaene/Todos fuer BACH-Bridge-Worker (#1596)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create", help="Plan anlegen")
    p.add_argument("--task", required=True, help="Aufgabenbeschreibung")
    p.add_argument("--plan", default="", help="Plantext")
    p.add_argument("--todo", action="append", default=[], help="Todo (mehrfach)")

    p = sub.add_parser("add", help="Todo hinzufuegen")
    p.add_argument("--plan-id", type=int, required=True)
    p.add_argument("--text", required=True)

    p = sub.add_parser("list", help="Offene Plaene/Todos listen")
    p.add_argument("--plan-id", type=int, default=None)

    p = sub.add_parser("done", help="Todo erledigen")
    p.add_argument("--todo-id", type=int, required=True)

    p = sub.add_parser("blocked", help="Todo blockieren")
    p.add_argument("--todo-id", type=int, required=True)

    p = sub.add_parser("plan-done", help="Plan abschliessen")
    p.add_argument("--plan-id", type=int, required=True)

    p = sub.add_parser("resume", help="Plan fortsetzen (offene Todos laden)")
    p.add_argument("--plan-id", type=int, required=True)

    p = sub.add_parser("bump-day", help="Arbeitstag weiterzaehlen (34h=1 Tag)")
    p.add_argument("--plan-id", type=int, required=True)

    args = parser.parse_args(argv)

    if args.cmd == "create":
        plan_id = create_plan(args.task, args.plan, args.todo)
        _print_json({"plan_id": plan_id})
    elif args.cmd == "add":
        _print_json({"todo_id": add_todo(args.plan_id, args.text)})
    elif args.cmd == "list":
        _print_json(list_open(args.plan_id))
    elif args.cmd == "done":
        _print_json({"ok": mark_done(args.todo_id)})
    elif args.cmd == "blocked":
        _print_json({"ok": mark_blocked(args.todo_id)})
    elif args.cmd == "plan-done":
        _print_json({"ok": mark_plan_done(args.plan_id)})
    elif args.cmd == "resume":
        plan, todos = resume_plan(args.plan_id)
        _print_json({
            "plan": plan.to_dict() if plan else None,
            "open_todos": [t.to_dict() for t in todos],
        })
    elif args.cmd == "bump-day":
        _print_json({"day_index": bump_day(args.plan_id)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
