"""Versioned native-chain definitions and fenced checkpoints in the lead TaskDB."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


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
            db.execute("""CREATE TABLE IF NOT EXISTS native_sequence_creator_delegations (
                run_id TEXT NOT NULL, cursor INTEGER NOT NULL, task_id INTEGER NOT NULL UNIQUE,
                task_version TEXT NOT NULL, slot_id TEXT NOT NULL, start_request_id TEXT NOT NULL UNIQUE,
                service_instance TEXT NOT NULL, generation TEXT, worker_id TEXT, host TEXT,
                acquire_request_id TEXT UNIQUE, created_at TEXT NOT NULL,
                consumed_at TEXT, consumed_fence INTEGER, revoked_at TEXT,
                PRIMARY KEY(run_id,cursor))""")

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


    @staticmethod
    def _ensure_learning_promotion_schema(db):
        db.execute("""CREATE TABLE IF NOT EXISTS native_sequence_learning_promotions (
            request_id TEXT PRIMARY KEY,
            action TEXT NOT NULL CHECK(action IN ('promote','revoke')),
            request_digest TEXT NOT NULL,
            source_request_id TEXT NOT NULL DEFAULT '',
            candidate_id INTEGER NOT NULL,
            candidate_revision INTEGER NOT NULL,
            candidate_digest TEXT NOT NULL,
            actor TEXT NOT NULL,
            target_chain_id INTEGER NOT NULL,
            target_chain_name TEXT NOT NULL,
            expected_target_version INTEGER NOT NULL,
            target_version INTEGER,
            previous_chain_json TEXT,
            published_chain_json TEXT,
            proposal_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS native_sequence_learning_source_idx
            ON native_sequence_learning_promotions(candidate_id,candidate_revision,candidate_digest,action,state)""")

    @staticmethod
    def _learning_proposal(proposal):
        if not isinstance(proposal, Mapping) or set(proposal) != {"schema", "source", "definition", "resolved"}:
            raise ValueError("Native Lernkette braucht genau schema, source, definition und resolved")
        if proposal.get("schema") != "bach.learning.native-sequence.v1":
            raise ValueError("Unbekannte native Lernkettenversion")
        source = proposal.get("source")
        if (not isinstance(source, Mapping)
                or set(source) != {"provider", "candidate_id", "candidate_revision", "candidate_digest"}
                or source.get("provider") != "nemofold"
                or type(source.get("candidate_id")) is not int or source["candidate_id"] <= 0
                or type(source.get("candidate_revision")) is not int or source["candidate_revision"] < 1
                or not isinstance(source.get("candidate_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", source["candidate_digest"])):
            raise ValueError("Native Lernkette braucht eine genaue NemoFold-Quellbindung")
        clean = definition(proposal.get("definition"))
        if clean != proposal.get("definition"):
            raise ValueError("Native Lernkettendefinition ist nicht kanonisch")
        resolved = proposal.get("resolved")
        if (not isinstance(resolved, Mapping)
                or set(resolved) != {"config_version", "agent_slots", "skills"}
                or not isinstance(resolved.get("config_version"), str)
                or not resolved["config_version"].strip()
                or len(resolved["config_version"]) > 200
                or "\x00" in resolved["config_version"]
                or not isinstance(resolved.get("agent_slots"), list)
                or not isinstance(resolved.get("skills"), list)):
            raise ValueError("Native Lernkette braucht gebundene Agenten- und Skillauflösung")
        agent_ids = {step["agent_slot"] for step in clean["steps"]}
        skill_ids = {skill for step in clean["steps"] for skill in step["skill_ids"]}
        agents, skills = resolved["agent_slots"], resolved["skills"]
        if (any(not isinstance(item, Mapping) or set(item) != {"id", "config_version"}
                or not isinstance(item.get("id"), str) or not item["id"]
                or not isinstance(item.get("config_version"), str) or not item["config_version"]
                or len(item["config_version"]) > 200 or "\x00" in item["config_version"] for item in agents)
                or len({item["id"] for item in agents}) != len(agents)
                or {item["id"] for item in agents} != agent_ids
                or any(not isinstance(item, Mapping) or set(item) != {"id", "source_version"}
                       or not isinstance(item.get("id"), str) or not item["id"]
                       or not isinstance(item.get("source_version"), str) or not item["source_version"]
                       or len(item["source_version"]) > 200 or "\x00" in item["source_version"] for item in skills)
                or len({item["id"] for item in skills}) != len(skills)
                or {item["id"] for item in skills} != skill_ids):
            raise ValueError("Agenten-/Skillversionen passen nicht eindeutig zu den Schritten")
        return {
            "schema": proposal["schema"],
            "source": dict(source),
            "definition": clean,
            "resolved": {
                "config_version": resolved["config_version"],
                "agent_slots": [dict(item) for item in agents],
                "skills": [dict(item) for item in skills],
            },
        }

    @staticmethod
    def _promotion_receipt(row):
        try:
            receipt = json.loads(row["receipt_json"])
        except (TypeError, ValueError):
            raise RuntimeError("Native Sequenz-Promotionsreceipt ist ungültig") from None
        return {**receipt, "replayed": True}

    @staticmethod
    def _validate_learning_request(request_id, actor):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
            raise ValueError("Explizite native Promotions-Request-ID erforderlich")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 180 or "\x00" in actor:
            raise ValueError("Authentifizierter Promotionsakteur erforderlich")

    def publish_learning_candidate(self, proposal, *, request_id, expected_version,
                                   actor, source_validator: Callable[[sqlite3.Connection], Mapping]):
        """Atomically publish one reviewed, bound native definition and its receipt.

        The validator runs under the same TaskDB write transaction as target CAS
        and receipt persistence. It must re-read and re-bind the reviewed source.
        """
        self._validate_learning_request(request_id, actor)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("Aktuelle SequenceStore-Zielversion erforderlich")
        if not callable(source_validator):
            raise ValueError("Native Quellvalidierung in der Zieltransaktion erforderlich")
        clean = self._learning_proposal(proposal)
        source = clean["source"]
        stamp = now()
        request_digest = digest({
            "action": "promote",
            "proposal": clean,
            "expected_target_version": expected_version,
            "actor": actor,
        })
        self.initialize()
        with self.connection(write=True) as db:
            self._ensure_learning_promotion_schema(db)
            prior = db.execute(
                "SELECT * FROM native_sequence_learning_promotions WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if prior is not None:
                if prior["request_digest"] != request_digest or prior["action"] != "promote":
                    raise SequenceConflict("Native Promotions-Request-ID wurde anders verwendet")
                return self._promotion_receipt(prior)
            current = self._learning_proposal(source_validator(db))
            if current != clean:
                raise SequenceConflict("Geprüfte NemoFold-Quelle oder native Auflösung änderte sich vor dem Ziel-CAS")
            active = db.execute("""SELECT request_id FROM native_sequence_learning_promotions
                WHERE action='promote' AND candidate_id=? AND candidate_revision=?
                  AND candidate_digest=? AND state='published'""",
                (source["candidate_id"], source["candidate_revision"], source["candidate_digest"])).fetchone()
            if active is not None:
                raise SequenceConflict("Diese Kandidatenrevision besitzt bereits eine aktive Sequenzpromotion")
            chain = db.execute("SELECT * FROM marblerun_chains WHERE name=?",
                               (clean["definition"]["name"],)).fetchone()
            previous_json = None
            if chain is None:
                if expected_version != 0:
                    raise SequenceConflict("Kette fehlt; erwartete Zielversion war nicht 0")
                payload = clean["definition"]
                cur = db.execute("""INSERT INTO marblerun_chains
                    (name,title,description,steps_json,is_active,created_at,updated_at,mode,agent_slot,version)
                    VALUES (?,?,?,?,1,?,?,?,?,1)""",
                    (payload["name"], payload["title"], payload["description"], encoded(payload["steps"]),
                     stamp, stamp, payload["mode"], payload["agent_slot"]))
                chain_id = cur.lastrowid
            else:
                if type(chain["version"]) is not int or chain["version"] != expected_version:
                    raise SequenceConflict("SequenceStore-Zielversion inzwischen geändert")
                chain_id = chain["id"]
                self._idle_chain(db, chain_id)
                previous_json = encoded(dict(chain))
                payload = clean["definition"]
                cur = db.execute("""UPDATE marblerun_chains SET name=?,title=?,description=?,steps_json=?,
                    mode=?,agent_slot=?,updated_at=?,version=version+1 WHERE id=? AND version=?""",
                    (payload["name"], payload["title"], payload["description"], encoded(payload["steps"]),
                     payload["mode"], payload["agent_slot"], stamp, chain_id, expected_version))
                if cur.rowcount != 1:
                    raise SequenceConflict("SequenceStore-Ziel änderte sich während der Promotion")
            published = db.execute("SELECT * FROM marblerun_chains WHERE id=?", (chain_id,)).fetchone()
            if published is None:
                raise RuntimeError("Native Kette fehlt nach dem SequenceStore-Write")
            published_json = encoded(dict(published))
            receipt = {
                "status": "published",
                "request_id": request_id,
                "target_kind": "sequence",
                "candidate_id": source["candidate_id"],
                "candidate_revision": source["candidate_revision"],
                "candidate_digest": source["candidate_digest"],
                "target_id": chain_id,
                "target_name": clean["definition"]["name"],
                "expected_target_version": expected_version,
                "previous_target_version": expected_version if previous_json is not None else None,
                "target_version": published["version"],
                "target_active": bool(published["is_active"]),
                "targets_published": True,
                "empirically_validated": False,
                "tools_granted": False,
                "agent_started": False,
                "replayed": False,
                "created_at": stamp,
            }
            db.execute("""INSERT INTO native_sequence_learning_promotions (
                request_id,action,request_digest,source_request_id,candidate_id,candidate_revision,
                candidate_digest,actor,target_chain_id,target_chain_name,expected_target_version,
                target_version,previous_chain_json,published_chain_json,proposal_json,state,
                receipt_json,created_at,updated_at
            ) VALUES (?,'promote',?,'',?,?,?,?,?,?,?,?,?,?,?,'published',?,?,?)""",
                (request_id, request_digest, source["candidate_id"], source["candidate_revision"],
                 source["candidate_digest"], actor, chain_id, clean["definition"]["name"],
                 expected_version, published["version"], previous_json, published_json,
                 encoded(clean), encoded(receipt), stamp, stamp))
            return receipt

    def revoke_learning_candidate(self, source_request_id, *, request_id, actor,
                                  candidate_id, candidate_revision, candidate_digest):
        """Revoke only the exact chain version recorded by a prior promotion."""
        self._validate_learning_request(request_id, actor)
        if not isinstance(source_request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", source_request_id):
            raise ValueError("Native Promotions-Request-ID zur Rücknahme erforderlich")
        if (type(candidate_id) is not int or candidate_id <= 0
                or type(candidate_revision) is not int or candidate_revision < 1
                or not isinstance(candidate_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", candidate_digest)):
            raise ValueError("Exakte NemoFold-Quellbindung zur Rücknahme erforderlich")
        request_digest = digest({
            "action": "revoke",
            "source_request_id": source_request_id,
            "candidate_id": candidate_id,
            "candidate_revision": candidate_revision,
            "candidate_digest": candidate_digest,
            "actor": actor,
        })
        stamp = now()
        self.initialize()
        with self.connection(write=True) as db:
            self._ensure_learning_promotion_schema(db)
            prior = db.execute(
                "SELECT * FROM native_sequence_learning_promotions WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if prior is not None:
                if prior["request_digest"] != request_digest or prior["action"] != "revoke":
                    raise SequenceConflict("Native Rücknahme-Request-ID wurde anders verwendet")
                return self._promotion_receipt(prior)
            source_row = db.execute("""SELECT * FROM native_sequence_learning_promotions
                WHERE request_id=? AND action='promote'""", (source_request_id,)).fetchone()
            if (source_row is None
                    or source_row["candidate_id"] != candidate_id
                    or source_row["candidate_revision"] != candidate_revision
                    or source_row["candidate_digest"] != candidate_digest):
                raise SequenceConflict("Keine passende native Sequenzpromotion für diese Quellrevision")
            if source_row["state"] != "published":
                raise SequenceConflict("Native Sequenzpromotion ist bereits zurückgenommen")
            chain = db.execute("SELECT * FROM marblerun_chains WHERE id=?",
                               (source_row["target_chain_id"],)).fetchone()
            if chain is None or encoded(dict(chain)) != source_row["published_chain_json"]:
                raise SequenceConflict("Native Kette wurde nach der Promotion verändert; Rücknahme-CAS abgelehnt")
            self._idle_chain(db, chain["id"])
            previous = json.loads(source_row["previous_chain_json"]) if source_row["previous_chain_json"] else None
            if previous is None:
                cur = db.execute("DELETE FROM marblerun_chains WHERE id=? AND version=?",
                                 (chain["id"], source_row["target_version"]))
                if cur.rowcount != 1:
                    raise SequenceConflict("Neue native Kette änderte sich; Rücknahme-CAS abgelehnt")
                resulting = None
                target_state = "deleted"
            else:
                conflict = db.execute("SELECT 1 FROM marblerun_chains WHERE name=? AND id<>?",
                                      (previous["name"], chain["id"])).fetchone()
                if conflict is not None:
                    raise SequenceConflict("Vorheriger Kettenname ist inzwischen belegt; Rücknahme bleibt gesperrt")
                cur = db.execute("""UPDATE marblerun_chains SET name=?,title=?,description=?,steps_json=?,
                    is_active=?,created_at=?,updated_at=?,mode=?,agent_slot=?,version=version+1
                    WHERE id=? AND version=?""",
                    (previous["name"], previous["title"], previous["description"], previous["steps_json"],
                     previous["is_active"], previous["created_at"], stamp, previous["mode"],
                     previous["agent_slot"], chain["id"], source_row["target_version"]))
                if cur.rowcount != 1:
                    raise SequenceConflict("Vorherige native Kette konnte nicht atomar wiederhergestellt werden")
                restored = db.execute("SELECT * FROM marblerun_chains WHERE id=?", (chain["id"],)).fetchone()
                resulting = restored["version"]
                target_state = "restored"
            receipt = {
                "status": "reverted",
                "request_id": request_id,
                "source_request_id": source_request_id,
                "target_kind": "sequence",
                "candidate_id": candidate_id,
                "candidate_revision": candidate_revision,
                "candidate_digest": candidate_digest,
                "target_id": source_row["target_chain_id"],
                "target_name": source_row["target_chain_name"],
                "target_state": target_state,
                "target_version": resulting,
                "targets_published": False,
                "targets_revoked": True,
                "empirically_validated": False,
                "replayed": False,
                "created_at": stamp,
            }
            db.execute("""INSERT INTO native_sequence_learning_promotions (
                request_id,action,request_digest,source_request_id,candidate_id,candidate_revision,
                candidate_digest,actor,target_chain_id,target_chain_name,expected_target_version,
                target_version,previous_chain_json,published_chain_json,proposal_json,state,
                receipt_json,created_at,updated_at
            ) VALUES (?,'revoke',?,?,?,?,?,?,?,?,?,?,?,?,?,'reverted',?,?,?)""",
                (request_id, request_digest, source_request_id, candidate_id, candidate_revision,
                 candidate_digest, actor, source_row["target_chain_id"], source_row["target_chain_name"],
                 source_row["target_version"], resulting, source_row["published_chain_json"],
                 encoded(json.loads(source_row["previous_chain_json"])) if source_row["previous_chain_json"] else "",
                 source_row["proposal_json"], encoded(receipt), stamp, stamp))
            source_receipt = json.loads(source_row["receipt_json"])
            source_receipt.update(
                status="reverted",
                targets_published=False,
                historical_publication=True,
                revoked_by=request_id,
            )
            db.execute("""UPDATE native_sequence_learning_promotions
                SET state='reverted',receipt_json=?,updated_at=?
                WHERE request_id=? AND action='promote' AND state='published'""",
                (encoded(source_receipt), stamp, source_request_id))
            return receipt
    def create_run(self, run_id, chain_id, version, request_digest, service, module_commit, plan):
        self.initialize()
        stamp = now()
        with self.connection(write=True) as db:
            existing = db.execute("SELECT * FROM native_sequence_runs WHERE run_id=?", (run_id,)).fetchone()
            if existing is not None:
                if existing["request_digest"] != request_digest or existing["owner_service"] != service:
                    raise SequenceConflict("Startkennung gehört zu einem anderen Auftrag oder Controller")
                return False
            row = db.execute("SELECT version,is_active FROM marblerun_chains WHERE id=?", (chain_id,)).fetchone()
            if row is None or row["version"] != version:
                raise SequenceConflict("Kettenversion inzwischen geändert")
            if row["is_active"] != 1:
                raise SequenceConflict("Kette ist nicht aktiviert")
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
            if self._exists(db, "native_sequence_creator_delegations"):
                db.execute("""UPDATE native_sequence_creator_delegations SET revoked_at=?
                    WHERE run_id=? AND service_instance=? AND consumed_at IS NULL AND revoked_at IS NULL""",
                    (now(), run_id, service))

    def error(self, run_id, service, reason):
        with self.connection(write=True) as db:
            db.execute("UPDATE native_sequence_runs SET error=? WHERE run_id=? AND owner_service=?", (reason,run_id,service))

    @staticmethod
    def _live_run(db, run_id, service, cursor):
        if (not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id)
                or not isinstance(service, str) or not re.fullmatch(r"[0-9a-f]{32}", service)
                or type(cursor) is not int or cursor < 0):
            raise SequenceConflict("Ungültige private Schrittzulassung")
        run = db.execute("SELECT * FROM native_sequence_runs WHERE run_id=?", (run_id,)).fetchone()
        if (run is None or run["owner_service"] != service or run["stop_requested"]
                or run["phase"] in {"complete", "failed", "stopped"}):
            raise SequenceConflict("Schritt gehört nicht zu einem aktiven Lauf dieses Controllers")
        state = json.loads(run["state_json"]) if run["state_json"] else {}
        if state.get("cursor", 0) != cursor:
            raise SequenceConflict("Laufcursor inzwischen geändert")
        plan = json.loads(run["plan_json"])
        if cursor >= len(plan.get("steps", [])):
            raise SequenceConflict("Schritt außerhalb des bestätigten Laufplans")
        return run

    def prepare_step(self, run_id, cursor, request_id, worker_id, title, description, model,
                     *, backend="ollama", service):
        """Task, step and one creator grant commit together; preparation grants no lease."""
        from hub._services.task_schema import ensure_task_slot_columns, ensure_task_creation_origin
        from hub._services.task_lease import task_content_version
        if (not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id)
                or worker_id != f"system-sequence-{run_id}-{cursor}"):
            raise SequenceConflict("Ungültige Schritt-Startkennung oder dedizierter Sequenzsteckplatz")
        with self.connection(write=True) as db:
            self._live_run(db, run_id, service, cursor)
            existing = db.execute("SELECT * FROM native_sequence_steps WHERE run_id=? AND cursor=?", (run_id,cursor)).fetchone()
            if existing is not None:
                grant = db.execute("""SELECT * FROM native_sequence_creator_delegations
                    WHERE run_id=? AND cursor=?""", (run_id, cursor)).fetchone()
                if (existing["request_id"] != request_id or existing["worker_id"] != worker_id
                        or grant is None or grant["task_id"] != existing["task_id"]
                        or grant["start_request_id"] != request_id or grant["slot_id"] != worker_id
                        or grant["service_instance"] != service or grant["revoked_at"] is not None):
                    raise SequenceConflict("Schrittbindung oder Creator-Delegation geändert")
                return dict(existing)
            ensure_task_slot_columns(db)
            ensure_task_creation_origin(db)
            source = f"marblerun:{run_id}:{cursor}"
            if db.execute("SELECT 1 FROM tasks WHERE source=?", (source,)).fetchone():
                raise SequenceConflict("Ungebundene Task mit dieser Startkennung vorhanden")
            stamp = now()
            cur = db.execute("""INSERT INTO tasks
                (title,description,priority,category,status,created_at,created_by,assigned_to,source,required_model,assigned_slot,creation_origin)
                VALUES (?,?,'P3','marblerun','pending',?,'user',?,?,?,?,'user')""",
                (title,description,stamp,backend.upper(),source,model,worker_id))
            task_id = cur.lastrowid
            db.execute("INSERT INTO native_sequence_steps (run_id,cursor,task_id,worker_id,request_id) VALUES (?,?,?,?,?)",
                (run_id,cursor,task_id,worker_id,request_id))
            version = task_content_version(dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()))
            db.execute("""INSERT INTO native_sequence_creator_delegations
                (run_id,cursor,task_id,task_version,slot_id,start_request_id,service_instance,created_at)
                VALUES (?,?,?,?,?,?,?,?)""", (run_id,cursor,task_id,version,worker_id,request_id,service,stamp))
            return dict(db.execute("SELECT * FROM native_sequence_steps WHERE run_id=? AND cursor=?", (run_id,cursor)).fetchone())

    def bind_creator_delegation(self, run_id, cursor, service, *, task_id, slot_id,
                                start_request_id, generation, worker_id, host):
        """Bind an existing grant to the actual private controller before its first acquire."""
        from hub._services.task_lease import _NativeCreatorBinding, _validate_worker, task_content_version
        _validate_worker(worker_id, host)
        if (type(task_id) is not int or task_id <= 0 or slot_id != f"system-sequence-{run_id}-{cursor}"
                or not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation)
                or not isinstance(start_request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", start_request_id)):
            raise SequenceConflict("Ungültige Controller-Generation")
        with self.connection(write=True) as db:
            self._live_run(db, run_id, service, cursor)
            saved = db.execute("""SELECT * FROM native_sequence_creator_delegations
                WHERE run_id=? AND cursor=?""", (run_id, cursor)).fetchone()
            step = db.execute("SELECT * FROM native_sequence_steps WHERE run_id=? AND cursor=?", (run_id, cursor)).fetchone()
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if (saved is None or step is None or task is None
                    or (saved["task_id"], saved["slot_id"], saved["start_request_id"], saved["service_instance"])
                        != (task_id, slot_id, start_request_id, service)
                    or (step["task_id"], step["worker_id"], step["request_id"]) != (task_id, slot_id, start_request_id)
                    or step["generation"] not in (None, generation)
                    or step["authority_id"] not in (None, service)
                    or saved["revoked_at"] is not None
                    or task["assigned_slot"] != slot_id
                    or task_content_version(dict(task)) != saved["task_version"]):
                raise SequenceConflict("Creator-Delegation passt nicht zum zugelassenen Workerlauf")
            physical = (generation, worker_id, host)
            if saved["generation"] is None:
                request_id = digest({"run_id": run_id, "cursor": cursor, "slot_id": slot_id,
                    "start_request_id": start_request_id, "service_instance": service,
                    "generation": generation, "worker_id": worker_id, "host": host})
                changed = db.execute("""UPDATE native_sequence_creator_delegations
                    SET generation=?,worker_id=?,host=?,acquire_request_id=?
                    WHERE run_id=? AND cursor=? AND generation IS NULL
                          AND consumed_at IS NULL AND revoked_at IS NULL""",
                    (*physical, request_id, run_id, cursor))
                if changed.rowcount != 1:
                    raise SequenceConflict("Creator-Delegation nicht bestätigt")
            else:
                if (saved["generation"], saved["worker_id"], saved["host"]) != physical:
                    raise SequenceConflict("Creator-Delegation ist bereits an einen anderen Workerlauf gebunden")
                request_id = saved["acquire_request_id"]
            return _NativeCreatorBinding(run_id, cursor, task_id, saved["task_version"], slot_id,
                start_request_id, service, generation, worker_id, host, request_id)

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
