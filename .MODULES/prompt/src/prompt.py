# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: prompt
===========================
Self-contained prompt template management and PromptBoard synchronization.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def serialize_prompt_tags(tags: Any) -> Optional[str]:
    """Store new tags as JSON; accept CSV and existing serialized lists."""
    if tags is None:
        return None
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
        except ValueError:
            parsed = None
        tags = (parsed if isinstance(parsed, list) and all(isinstance(tag, str) for tag in parsed)
                else tags.split(","))
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("tags: Text oder Liste von Texten erwartet")
    return json.dumps([tag.strip() for tag in tags if tag.strip()], ensure_ascii=False)


def prompt_tags_text(tags: Any) -> Optional[str]:
    """Display/search both legacy CSV and JSON, including escaped Unicode."""
    if tags is None:
        return None
    try:
        parsed = json.loads(tags)
    except ValueError:
        parsed = None
    if isinstance(parsed, list) and all(isinstance(tag, str) for tag in parsed):
        return ", ".join(tag.strip() for tag in parsed if tag.strip())
    return str(tags)


def prompt_tags_edit_text(tags: Any) -> Optional[str]:
    """Use CSV for simple tags and JSON when CSV would lose tag boundaries."""
    display = prompt_tags_text(tags)
    if tags is None:
        return None
    try:
        parsed = json.loads(tags)
    except ValueError:
        parsed = None
    if isinstance(parsed, list) and all(isinstance(tag, str) for tag in parsed):
        if serialize_prompt_tags(display) != serialize_prompt_tags(parsed):
            return json.dumps(parsed, ensure_ascii=False)
    return display


def promptboard_library_paths() -> List[Path]:
    """Discover existing PromptBoard library without creating directories."""
    candidates = []
    if os.environ.get("BACH_PROMPTBOARD_LIBRARY"):
        candidates.append(Path(os.environ["BACH_PROMPTBOARD_LIBRARY"]).expanduser())
    candidates.append(Path.home() / ".promptboard" / "library.json")
    if os.environ.get("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "PromptBoard" / "library.json")

    local_dev = Path(os.environ.get("LOCAL_DEV_REPOS", r"C:\_Local_DEV\repos"))
    for repo_name in ("REL-PUB_PromptBoard-tasksolver-1136-1137", "REL-PUB_PromptBoard"):
        repo_dir = local_dev / repo_name
        candidates.extend([repo_dir / "library.json", repo_dir / "data" / "library.json"])

    if os.environ.get("USERPROFILE"):
        for sub in ("DATA", "LLM"):
            project = (Path(os.environ["USERPROFILE"]) / "OneDrive" / ".TOPICS" /
                       ".SOFTWARE" / sub / "REL-PUB_PromptBoard")
            candidates.extend([
                project / "library.json",
                project / "data" / "library.json",
                project / "_tmp_accessibility_check" / "library.json",
            ])
    return candidates


def promptboard_library_not_found(candidates: List[Path]) -> str:
    searched = ", ".join(str(path) for path in candidates) or "(keine Kandidaten)"
    return ("Keine PromptBoard library.json gefunden (BACH_PROMPTBOARD_LIBRARY, "
            "~/.promptboard, %APPDATA%/PromptBoard, REL-PUB_PromptBoard; "
            f"geprüft: {searched})")


def init_prompt_schema(conn: sqlite3.Connection) -> None:
    """Ensure required prompt tables exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
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
            created_at TEXT,
            FOREIGN KEY (prompt_id) REFERENCES prompt_templates(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_board_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL,
            prompt_id INTEGER NOT NULL,
            added_at TEXT,
            UNIQUE(board_id, prompt_id),
            FOREIGN KEY (board_id) REFERENCES prompt_boards(id),
            FOREIGN KEY (prompt_id) REFERENCES prompt_templates(id)
        )
    """)
    conn.commit()


class PromptCore:
    """Self-contained prompt template manager."""

    def __init__(self, db_path_or_conn_factory: Any = None):
        if callable(db_path_or_conn_factory):
            self._factory = db_path_or_conn_factory
            self._db_path = None
        elif isinstance(db_path_or_conn_factory, (str, Path)):
            self._db_path = Path(db_path_or_conn_factory)
            self._factory = None
        else:
            self._db_path = Path(":memory:")
            self._factory = None

    def get_connection(self) -> sqlite3.Connection:
        if self._factory:
            conn = self._factory()
        else:
            conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        init_prompt_schema(conn)
        return conn

    def add(self, name: str, text: str, *, category: str | None = None, tags: Any = None, purpose: str | None = None) -> int:
        name = name.strip()
        text = text.strip()
        if not name or not text:
            raise ValueError("Name und Text erforderlich")
        now = datetime.now().isoformat()
        tags_json = serialize_prompt_tags(tags)
        conn = self.get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, purpose, text, tags_json, category, now, now)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get(self, id_or_name: str | int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            if isinstance(id_or_name, int) or (isinstance(id_or_name, str) and id_or_name.isdigit()):
                row = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (int(id_or_name),)).fetchone()
            else:
                row = conn.execute("SELECT * FROM prompt_templates WHERE name = ?", (str(id_or_name).strip(),)).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def list_prompts(self, category: str | None = None) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            if category:
                rows = conn.execute("SELECT * FROM prompt_templates WHERE category = ? ORDER BY name", (category,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM prompt_templates ORDER BY name").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def sync_promptboard(self, library_path: str | Path | None = None, *, category: str | None = None, dry_run: bool = False) -> Dict[str, Any]:
        """Bidirectional reconciliation between PromptBoard library.json and prompt_templates."""
        target = Path(library_path).expanduser() if library_path else next((p for p in promptboard_library_paths() if p.exists()), Path.home() / ".promptboard" / "library.json")
        existing_items = []
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    existing_items = data["items"]
                elif isinstance(data, list):
                    existing_items = data
            except Exception as e:
                raise ValueError(f"Fehler beim Lesen der Ziel-Bibliothek '{target}': {e}")

        item_by_name = {}
        for idx, item in enumerate(existing_items):
            if isinstance(item, dict) and item.get("name"):
                name_key = str(item["name"]).strip().lower()
                item_by_name[name_key] = idx

        conn = self.get_connection()
        try:
            query = "SELECT id, name, text, tags, category, purpose, created_at, updated_at FROM prompt_templates"
            params = []
            if category:
                query += " WHERE category = ?"
                params.append(category)
            query += " ORDER BY id"
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        bach_by_name = { (r["name"] or "").strip().lower(): r for r in rows if (r["name"] or "").strip() }
        now_iso = datetime.now().isoformat()
        imported = 0
        exported = 0
        updated_in_bach = 0
        updated_in_pb = 0

        final_items = [dict(it) if isinstance(it, dict) else it for it in existing_items]
        bach_inserts = []
        bach_updates = []

        for idx, item in enumerate(final_items):
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            text = (item.get("content") or "").strip()
            if not name or not text:
                continue

            name_key = name.lower()
            try:
                pb_tags_json = serialize_prompt_tags(item.get("tags"))
            except ValueError:
                pb_tags_json = None

            pb_cat = (item.get("category") or item.get("item_type") or "PromptBoard").strip() or "PromptBoard"
            pb_desc = (item.get("description") or "").strip()
            pb_created = item.get("created_at") or now_iso
            pb_updated = item.get("updated_at") or now_iso

            if name_key not in bach_by_name:
                bach_inserts.append((name, pb_desc, text, pb_tags_json, pb_cat, pb_created, pb_updated))
                imported += 1
            else:
                bach_row = bach_by_name[name_key]
                bach_text = (bach_row["text"] or "").strip()
                bach_updated = bach_row["updated_at"] or ""
                if text != bach_text:
                    if pb_updated and bach_updated and pb_updated > bach_updated:
                        bach_updates.append((bach_row["id"], text, pb_tags_json, pb_cat, pb_desc, pb_updated, bach_row["text"], bach_row["tags"]))
                        updated_in_bach += 1
                    else:
                        item_copy = dict(item)
                        item_copy["content"] = bach_text
                        item_copy["updated_at"] = now_iso
                        final_items[idx] = item_copy
                        updated_in_pb += 1

        for name_key, row in bach_by_name.items():
            if name_key not in item_by_name:
                name = (row["name"] or "").strip()
                text = (row["text"] or "").strip()
                if not name or not text:
                    continue
                parsed_tags = []
                if row["tags"]:
                    try:
                        pt = json.loads(row["tags"])
                        parsed_tags = [str(t).strip() for t in pt if str(t).strip()] if isinstance(pt, list) else [t.strip() for t in str(pt).split(",") if t.strip()]
                    except Exception:
                        parsed_tags = [t.strip() for t in str(row["tags"]).split(",") if t.strip()]
                new_item = {
                    "id": uuid.uuid4().hex,
                    "item_type": "PROMPT",
                    "name": name,
                    "content": text,
                    "category": (row["category"] or "PromptBoard").strip() or "PromptBoard",
                    "tags": parsed_tags,
                    "source": "bach",
                    "description": (row["purpose"] or "").strip(),
                    "created_at": row["created_at"] or now_iso,
                    "updated_at": row["updated_at"] or now_iso,
                }
                final_items.append(new_item)
                item_by_name[name_key] = len(final_items) - 1
                exported += 1

        if not dry_run and (bach_inserts or bach_updates):
            conn = self.get_connection()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    for ins in bach_inserts:
                        conn.execute("INSERT INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ins)
                    for upd in bach_updates:
                        p_id, new_t, new_tags, new_cat, new_desc, upd_time, old_t, old_tags = upd
                        if old_t is not None:
                            max_ver = conn.execute("SELECT MAX(version_number) FROM prompt_versions WHERE prompt_id = ?", (p_id,)).fetchone()[0]
                            next_ver = (max_ver or 0) + 1
                            conn.execute("INSERT INTO prompt_versions (prompt_id, version_number, text, tags, created_at) VALUES (?, ?, ?, ?, ?)", (p_id, next_ver, old_t, old_tags, upd_time))
                        conn.execute("UPDATE prompt_templates SET text = ?, tags = ?, category = ?, purpose = ?, updated_at = ? WHERE id = ?", (new_t, new_tags, new_cat, new_desc, upd_time, p_id))
            finally:
                conn.close()

        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_file = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temp_file.write_text(json.dumps({"items": final_items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(temp_file, target)

        conn = self.get_connection()
        try:
            total_bach = conn.execute("SELECT COUNT(*) FROM prompt_templates").fetchone()[0]
        finally:
            conn.close()

        return {
            "ok": True,
            "source": str(target),
            "target": str(target),
            "imported": imported,
            "exported": exported,
            "updated_in_bach": updated_in_bach,
            "updated_in_promptboard": updated_in_pb,
            "total_bach": total_bach,
            "total_promptboard": len(final_items),
            "dry_run": bool(dry_run),
        }
