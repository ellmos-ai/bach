# SPDX-License-Identifier: MIT
"""Immutable observed blueprint revisions. No runtime or TaskDB writes."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

SCHEMA = "bach.blueprint-revisions.v1"
FIELDS = ("id", "name", "title", "description", "persona_role", "persona_prompt",
          "skills_json", "animus_type", "contractus_json", "modus", "is_template",
          "governance_json", "kind", "start_prompt", "version", "provider",
          "provider_template_id", "provider_version", "template_sha256",
          "derived_from_json")
SHA = re.compile(r"^[0-9a-f]{64}$")


def ensure_revision_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_blueprint_revisions (
        blueprint_id INTEGER NOT NULL, version INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
        recorded_at TEXT NOT NULL, restored_from_version INTEGER,
        PRIMARY KEY (blueprint_id, version))""")
    # REPLACE can bypass DELETE triggers when recursive_triggers is off.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS blueprint_revisions_no_replace
        BEFORE INSERT ON agent_blueprint_revisions
        WHEN EXISTS (SELECT 1 FROM agent_blueprint_revisions
                     WHERE blueprint_id=NEW.blueprint_id AND version=NEW.version)
        BEGIN SELECT RAISE(ABORT, 'blueprint_revision_immutable'); END""")
    for action in ("UPDATE", "DELETE"):
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS blueprint_revisions_no_{action.lower()}
            BEFORE {action} ON agent_blueprint_revisions
            BEGIN SELECT RAISE(ABORT, 'blueprint_revision_immutable'); END""")


def read_blueprint(conn, blueprint_id):
    cur = conn.execute("SELECT * FROM agent_blueprints WHERE id=?", (blueprint_id,))
    row = cur.fetchone()
    if row is None:
        raise KeyError("blueprint_not_found")
    return dict(zip([col[0] for col in cur.description], row))


def positive(value):
    if type(value) is not int or value <= 0:
        raise ValueError("positive_integer_required")
    return value


def _encode(snapshot):
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(encoded):
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def record_revision(conn, row, *, restored_from_version=None):
    """Only called in the definition writer's BEGIN IMMEDIATE transaction."""
    if not conn.in_transaction:
        raise RuntimeError("blueprint_revision_transaction_required")
    snapshot = {key: row.get(key) for key in FIELDS}
    snapshot["derived_from_json"] = row.get("derived_from_json") or "null"
    positive(snapshot["id"])
    positive(snapshot["version"])
    encoded = _encode(snapshot)
    if len(encoded.encode("utf-8")) > 768 * 1024:
        raise ValueError("blueprint_revision_size_limit")
    sha = _sha(encoded)
    existing = conn.execute("""SELECT snapshot_sha256,snapshot_json
        FROM agent_blueprint_revisions WHERE blueprint_id=? AND version=?""",
        (snapshot["id"], snapshot["version"])).fetchone()
    if existing is not None:
        if tuple(existing) != (sha, encoded):
            raise RuntimeError("blueprint_revision_conflict")
        return sha
    conn.execute("""INSERT INTO agent_blueprint_revisions
        (blueprint_id,version,snapshot_json,snapshot_sha256,recorded_at,restored_from_version)
        VALUES (?,?,?,?,?,?)""", (snapshot["id"],snapshot["version"],encoded,sha,
        datetime.now(timezone.utc).isoformat(),restored_from_version))
    return sha


def resolve_lineage(conn, value):
    """Resolve source pin within the same transaction as the copy."""
    if (type(value) is not dict or set(value) != {"blueprint_id","version","sha256"}
            or not isinstance(value.get("sha256"),str) or not SHA.fullmatch(value["sha256"])):
        raise ValueError("blueprint_source_pin_invalid")
    positive(value["blueprint_id"])
    positive(value["version"])
    source = read_blueprint(conn,value["blueprint_id"])
    from .governance_binding import blueprint_sha256
    if source["version"] != value["version"] or blueprint_sha256(source) != value["sha256"]:
        raise RuntimeError("blueprint_source_pin_conflict")
    record_revision(conn,source)
    return dict(value)


def _storage_ready(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        ("agent_blueprint_revisions",)).fetchone() is not None


def history(conn, blueprint_id, *, limit=50, before_version=None):
    """Read recorded versions without inventing missing legacy history."""
    positive(blueprint_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("revision_page_limit_invalid")
    if before_version is not None:
        positive(before_version)
    try:
        current = read_blueprint(conn,blueprint_id)
    except KeyError:
        current = None
    ready = _storage_ready(conn)
    rows = []
    if ready:
        rows = conn.execute("""SELECT version,snapshot_sha256,recorded_at,restored_from_version
            FROM agent_blueprint_revisions WHERE blueprint_id=? AND (? IS NULL OR version<?)
            ORDER BY version DESC LIMIT ?""",(blueprint_id,before_version,before_version,limit+1)).fetchall()
    latest = conn.execute("SELECT version FROM agent_blueprint_revisions WHERE blueprint_id=? ORDER BY version DESC LIMIT 1",
                          (blueprint_id,)).fetchone() if ready else None
    if current is None and latest is None:
        raise KeyError("blueprint_not_found")
    items = [dict(zip(("version","snapshot_sha256","recorded_at","restored_from_version"),row))
             for row in rows[:limit]]
    return {"schema":SCHEMA,"blueprint_id":blueprint_id,"current_version":current["version"] if current else None,
            "definition_deleted":current is None,"latest_recorded_version":latest[0] if latest else None,
            "storage_ready":ready,"legacy_history_complete":False,"revisions":items,
            "next_before_version":items[-1]["version"] if len(rows)>limit else None,
            "derived_from":json.loads(current.get("derived_from_json") or "null") if current else None}


def revision(conn, blueprint_id, version):
    positive(blueprint_id)
    positive(version)
    row = None
    if _storage_ready(conn):
        row = conn.execute("""SELECT snapshot_json,snapshot_sha256,recorded_at,restored_from_version
            FROM agent_blueprint_revisions WHERE blueprint_id=? AND version=?""",
            (blueprint_id,version)).fetchone()
    if row is None:
        raise KeyError("blueprint_revision_not_recorded")
    encoded,sha,stamp,restored_from = row
    if _sha(encoded) != sha:
        raise RuntimeError("blueprint_revision_hash_mismatch")
    snapshot = json.loads(encoded)
    if snapshot.get("id") != blueprint_id or snapshot.get("version") != version:
        raise RuntimeError("blueprint_revision_identity_mismatch")
    return {"schema":SCHEMA,"blueprint_id":blueprint_id,"version":version,"snapshot":snapshot,
            "snapshot_sha256":sha,"recorded_at":stamp,"restored_from_version":restored_from}


def diff_revisions(conn, blueprint_id, from_version, to_version):
    left = revision(conn,blueprint_id,from_version)
    right = revision(conn,blueprint_id,to_version)
    a,b = left["snapshot"],right["snapshot"]
    changed = [key for key in FIELDS if a.get(key) != b.get(key)]
    text = "\n".join(difflib.unified_diff(
        json.dumps({k:a.get(k) for k in changed},ensure_ascii=False,sort_keys=True,indent=2).splitlines(),
        json.dumps({k:b.get(k) for k in changed},ensure_ascii=False,sort_keys=True,indent=2).splitlines(),
        fromfile=str(from_version),tofile=str(to_version),lineterm=""))
    return {"schema":SCHEMA,"blueprint_id":blueprint_id,"from_version":from_version,
            "to_version":to_version,"from_sha256":left["snapshot_sha256"],
            "to_sha256":right["snapshot_sha256"],"changed_fields":changed,
            "diff":text[:128*1024],"truncated":len(text)>128*1024}


def restore_revision(conn, blueprint_id, version, *, expected_version):
    positive(expected_version)
    old = revision(conn,blueprint_id,version)["snapshot"]
    current = read_blueprint(conn,blueprint_id)
    if current["version"] != expected_version:
        raise RuntimeError("blueprint_version_conflict")
    payload = {key:old[key] for key in ("title","description","persona_role","persona_prompt",
                                      "animus_type","modus","kind","start_prompt")}
    payload.update({"name":current["name"],"expected_version":expected_version,"is_template":0})
    for field in ("skills","contractus","governance"):
        payload[field] = json.loads(old[field+"_json"])
    # Ordinary writer revalidates current governance pins. No instance refresh.
    from .blueprint_service import save_blueprint
    return save_blueprint(conn,payload,_restored_from_version=version,_expected_id=blueprint_id)


def clone_blueprint(conn, blueprint_id, *, name, expected_version, source_sha256):
    positive(blueprint_id)
    positive(expected_version)
    source = read_blueprint(conn,blueprint_id)
    from .governance_binding import blueprint_sha256
    if source["version"] != expected_version or blueprint_sha256(source) != source_sha256:
        raise RuntimeError("blueprint_source_pin_conflict")
    payload = {key:source.get(key) for key in ("title","description","persona_role",
               "persona_prompt","animus_type","modus","kind","start_prompt")}
    payload.update({"name":name,"expected_version":0,"is_template":0,
                    "derived_from":{"blueprint_id":blueprint_id,"version":expected_version,
                                    "sha256":source_sha256}})
    for field in ("skills","contractus","governance"):
        payload[field] = json.loads(source[field+"_json"])
    from .blueprint_service import save_blueprint
    return save_blueprint(conn,payload)
