"""Versioned native-chain definitions and fenced checkpoints in the lead TaskDB."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class SequenceConflict(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def definition(payload):
    fields = {"name", "title", "description", "mode", "agent_slot", "steps"}
    if not isinstance(payload, dict) or set(payload) - fields:
        raise ValueError("Unbekannte Kettenfelder")
    name = payload.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", name):
        raise ValueError("Name muss eine kurze Kennung sein")
    title, description = payload.get("title", name), payload.get("description", "")
    if (not isinstance(title, str) or not title.strip() or len(title) > 120
            or not isinstance(description, str) or len(description) > 20000):
        raise ValueError("Ungültiger Kettentitel oder Beschreibung")
    mode = payload.get("mode")
    if mode not in {"agents", "skills"}:
        raise ValueError("Modus muss agents oder skills sein")
    agent = payload.get("agent_slot", "")
    if not isinstance(agent, str) or (mode == "skills" and not agent):
        raise ValueError("Skillfolge braucht einen Agenten")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        raise ValueError("Kette braucht 1 bis 32 Schritte")
    clean = []
    for item in steps:
        if not isinstance(item, dict) or set(item) - {"label", "agent_slot", "skill_ids", "instructions"}:
            raise ValueError("Unbekannte Schrittfelder")
        label, instructions = item.get("label"), item.get("instructions", "")
        if (not isinstance(label, str) or not label.strip() or len(label) > 120
                or not isinstance(instructions, str) or len(instructions) > 12000):
            raise ValueError("Ungültiger Schritttext")
        slot = item.get("agent_slot", "") if mode == "agents" else agent
        if not isinstance(slot, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", slot):
            raise ValueError("Gültiger Living-Steckplatz erforderlich")
        skills = item.get("skill_ids", [])
        if (not isinstance(skills, list) or len(skills) > 4
                or any(not isinstance(s, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", s) for s in skills)
                or len(set(skills)) != len(skills) or (mode == "skills" and len(skills) != 1)):
            raise ValueError("Skillfolge braucht genau einen Skill je Schritt")
        clean.append({"label": label.strip(), "agent_slot": slot, "skill_ids": skills, "instructions": instructions})
    return {"name": name, "title": title.strip(), "description": description,
            "mode": mode, "agent_slot": agent if mode == "skills" else "", "steps": clean}


class SequenceStore:
    def __init__(self, db_path, *, write_guard=None):
        self.path = Path(db_path).expanduser().resolve()
        self.write_guard = write_guard or (lambda: None)

    @contextmanager
    def connection(self, *, write=False):
        if not self.path.is_file():
            raise RuntimeError("Kanonische TaskDB fehlt")
        if write:
            self.write_guard()
        db = sqlite3.connect(str(self.path) if write else self.path.as_uri() + "?mode=ro", uri=not write, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _exists(db, table):
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    def initialize(self):
        """Explicit mutation only; catalog GET never creates or migrates tables."""
        with self.connection(write=True) as db:
            if not self._exists(db, "tasks"):
                raise RuntimeError("Keine kanonische Tasktabelle")
            db.execute("""CREATE TABLE IF NOT EXISTS marblerun_chains (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
                title TEXT, description TEXT DEFAULT '', steps_json TEXT DEFAULT '[]',
                is_active INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(marblerun_chains)")}
            for name, sql in {"mode": "TEXT DEFAULT ''", "agent_slot": "TEXT DEFAULT ''",
                              "version": "INTEGER DEFAULT 0", "title": "TEXT", "description": "TEXT DEFAULT ''",
                              "updated_at": "TEXT", "created_at": "TEXT"}.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE marblerun_chains ADD COLUMN {name} {sql}")
            db.execute("""CREATE TABLE IF NOT EXISTS native_sequence_runs (
                run_id TEXT PRIMARY KEY, chain_id INTEGER NOT NULL, chain_version INTEGER NOT NULL,
                request_digest TEXT NOT NULL, owner_service TEXT NOT NULL, module_commit TEXT NOT NULL,
                plan_json TEXT NOT NULL, state_json TEXT, revision INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL DEFAULT 'ready', stop_requested INTEGER NOT NULL DEFAULT 0,
                error TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS native_sequence_steps (
                run_id TEXT NOT NULL, cursor INTEGER NOT NULL, task_id INTEGER NOT NULL,
                worker_id TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL UNIQUE,
                generation TEXT, authority_id TEXT, PRIMARY KEY(run_id,cursor))""")

    @staticmethod
    def _chain(row):
        item = dict(row)
        item["steps"] = json.loads(item.pop("steps_json"))
        for key, value in (("version", 0), ("mode", ""), ("agent_slot", "")):
            item.setdefault(key, value)
        item["legacy"] = item["mode"] not in {"agents", "skills"}
        return item

    def chains(self):
        with self.connection() as db:
            if not self._exists(db, "marblerun_chains"):
                return []
            return [self._chain(row) for row in db.execute("SELECT * FROM marblerun_chains ORDER BY id")]

    def chain(self, chain_id):
        if type(chain_id) is not int or chain_id <= 0:
            raise ValueError("Gültige Ketten-ID erforderlich")
        return next((item for item in self.chains() if item["id"] == chain_id), None)

    @staticmethod
    def _idle_chain(db, chain_id):
        if db.execute("SELECT 1 FROM native_sequence_runs WHERE chain_id=? AND phase NOT IN ('complete','failed','stopped')", (chain_id,)).fetchone():
            raise SequenceConflict("Kette hat einen laufenden oder ungeklärten Lauf")

    def save_chain(self, payload, *, chain_id=None, expected_version=None):
        clean = definition(payload)
        self.initialize()
        stamp = now()
        with self.connection(write=True) as db:
            values = (clean["name"], clean["title"], clean["description"], encoded(clean["steps"]),
                      clean["mode"], clean["agent_slot"], stamp)
            if chain_id is None:
                if db.execute("SELECT 1 FROM marblerun_chains WHERE name=?", (clean["name"],)).fetchone():
                    raise SequenceConflict("Kettenname bereits vorhanden")
                cur = db.execute("""INSERT INTO marblerun_chains
                    (name,title,description,steps_json,mode,agent_slot,updated_at,created_at,version)
                    VALUES (?,?,?,?,?,?,?,?,1)""", (*values, stamp))
                chain_id = cur.lastrowid
            else:
                if type(expected_version) is not int or expected_version < 0:
                    raise ValueError("Aktuelle Kettenversion erforderlich")
                self._idle_chain(db, chain_id)
                cur = db.execute("""UPDATE marblerun_chains SET name=?,title=?,description=?,steps_json=?,
                    mode=?,agent_slot=?,updated_at=?,version=version+1 WHERE id=? AND version=?""",
                    (*values, chain_id, expected_version))
                if cur.rowcount != 1:
                    raise SequenceConflict("Kette inzwischen geändert oder gelöscht")
            return self._chain(db.execute("SELECT * FROM marblerun_chains WHERE id=?", (chain_id,)).fetchone())

    def delete_chain(self, chain_id, expected_version):
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("Aktuelle Kettenversion erforderlich")
        self.initialize()
        with self.connection(write=True) as db:
            self._idle_chain(db, chain_id)
            if db.execute("DELETE FROM marblerun_chains WHERE id=? AND version=?", (chain_id, expected_version)).rowcount != 1:
                raise SequenceConflict("Kette inzwischen geändert oder gelöscht")

    def create_run(self, run_id, chain_id, version, request_digest, service, module_commit, plan):
        self.initialize()
        stamp = now()
        with self.connection(write=True) as db:
            existing = db.execute("SELECT * FROM native_sequence_runs WHERE run_id=?", (run_id,)).fetchone()
            if existing is not None:
                if existing["request_digest"] != request_digest or existing["owner_service"] != service:
                    raise SequenceConflict("Startkennung gehört zu einem anderen Auftrag oder Controller")
                return False
            row = db.execute("SELECT version FROM marblerun_chains WHERE id=?", (chain_id,)).fetchone()
            if row is None or row["version"] != version:
                raise SequenceConflict("Kettenversion inzwischen geändert")
            self._idle_chain(db, chain_id)
            db.execute("""INSERT INTO native_sequence_runs
                (run_id,chain_id,chain_version,request_digest,owner_service,module_commit,plan_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""", (run_id,chain_id,version,request_digest,service,module_commit,encoded(plan),stamp,stamp))
            return True

    def run(self, run_id):
        with self.connection() as db:
            if not self._exists(db, "native_sequence_runs"):
                raise KeyError("Lauf nicht gefunden")
            row = db.execute("SELECT * FROM native_sequence_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError("Lauf nicht gefunden")
            item = dict(row)
            item["plan"] = json.loads(item.pop("plan_json"))
            state = item.pop("state_json")
            item["state"] = json.loads(state) if state else None
            item["steps"] = [dict(step) for step in db.execute("SELECT * FROM native_sequence_steps WHERE run_id=? ORDER BY cursor", (run_id,))]
            return item

    def runs(self):
        with self.connection() as db:
            if not self._exists(db, "native_sequence_runs"):
                return []
            ids = [row[0] for row in db.execute("SELECT run_id FROM native_sequence_runs ORDER BY created_at DESC LIMIT 100")]
        return [self.run(run_id) for run_id in ids]

    def checkpoint(self, state, service):
        with self.connection(write=True) as db:
            cur = db.execute("""UPDATE native_sequence_runs SET state_json=?,revision=?,phase=?,updated_at=?,error=''
                WHERE run_id=? AND owner_service=? AND revision=?""",
                (encoded(state.as_record()),state.revision,state.phase,now(),state.run_id,service,state.revision-1))
            if cur.rowcount != 1:
                raise SequenceConflict("Checkpoint nicht bestätigt; Controller oder Revision geändert")

    def stop(self, run_id, service):
        with self.connection(write=True) as db:
            cur = db.execute("UPDATE native_sequence_runs SET stop_requested=1,updated_at=? WHERE run_id=? AND owner_service=?", (now(),run_id,service))
            if cur.rowcount != 1:
                raise SequenceConflict("Lauf gehört nicht zu diesem Controller")

    def error(self, run_id, service, reason):
        with self.connection(write=True) as db:
            db.execute("UPDATE native_sequence_runs SET error=? WHERE run_id=? AND owner_service=?", (reason,run_id,service))

    def prepare_step(self, run_id, cursor, request_id, worker_id, title, description, model, *, backend="ollama"):
        """Task creation and its run binding commit together; no duplicate on retry."""
        from hub._services.task_schema import ensure_task_slot_columns, ensure_task_creation_origin
        with self.connection(write=True) as db:
            existing = db.execute("SELECT * FROM native_sequence_steps WHERE run_id=? AND cursor=?", (run_id,cursor)).fetchone()
            if existing is not None:
                if existing["request_id"] != request_id or existing["worker_id"] != worker_id:
                    raise SequenceConflict("Schrittbindung geändert")
                return dict(existing)
            ensure_task_slot_columns(db)
            ensure_task_creation_origin(db)
            source = f"marblerun:{run_id}:{cursor}"
            if db.execute("SELECT 1 FROM tasks WHERE source=?", (source,)).fetchone():
                raise SequenceConflict("Ungebundene Task mit dieser Startkennung vorhanden")
            cur = db.execute("""INSERT INTO tasks
                (title,description,priority,category,status,created_at,created_by,assigned_to,source,required_model,assigned_slot,creation_origin)
                VALUES (?,?,'P3','marblerun','pending',?,'user',?,?,?,?,'user')""",
                (title,description,now(),backend.upper(),source,model,worker_id))
            db.execute("INSERT INTO native_sequence_steps (run_id,cursor,task_id,worker_id,request_id) VALUES (?,?,?,?,?)", (run_id,cursor,cur.lastrowid,worker_id,request_id))
            return dict(db.execute("SELECT * FROM native_sequence_steps WHERE run_id=? AND cursor=?", (run_id,cursor)).fetchone())

    def bind_execution(self, run_id, cursor, handle):
        with self.connection(write=True) as db:
            saved = db.execute("SELECT * FROM native_sequence_steps WHERE run_id=? AND cursor=?", (run_id,cursor)).fetchone()
            if saved is not None and (saved["request_id"],saved["generation"],saved["authority_id"]) == (handle.request_id,handle.job_id,handle.authority_id):
                return
            cur = db.execute("""UPDATE native_sequence_steps SET generation=?,authority_id=?
                WHERE run_id=? AND cursor=? AND request_id=? AND generation IS NULL AND authority_id IS NULL""",
                (handle.job_id,handle.authority_id,run_id,cursor,handle.request_id))
            if cur.rowcount != 1:
                raise SequenceConflict("Schritt-Ausführungsbeleg nicht gespeichert")
