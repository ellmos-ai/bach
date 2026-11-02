# SPDX-License-Identifier: MIT
"""Local maintenance owner for one revoked result-operator credential.

No HTTP/worker route exposes this provisioning operation. The maintenance
caller supplies its separately authorized target and existing operator token.
Only devices.token_hash stores credential authority. The append-only table
below stores nonsecret audit/recovery metadata, never a credential or its hash.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from gui.device_auth import _hash_token
from hub._services.task_result_service import (
    ResultConflict, ResultPermissionDenied, _correction_operator_device_id, _dict_row,
)

_AUDIT = "task_result_operator_token_rotation_audit"
_SCHEMA = "bach.task-result-operator-token-rotation.v1"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_POSIX_DIR_FD = hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and hasattr(os, "getuid")
# Reviewed local maintenance scope, not caller-provided reviewer authority.
MAINTENANCE_POLICY = {
    "actor_device_id": 45, "target_device_id": 47,
    "target_device_name": "ticket-master-review-luna-session01a176e7",
}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _version(value):
    # Input is exclusively the nonsecret metadata projection below.
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _uuid(value):
    if type(value) is not str:
        raise ValueError("Ungültige Request-ID")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError("Ungültige Request-ID") from None
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Ungültige Request-ID")
    return value


def _operator(conn, token, target_id, expected_actor_device_id):
    if (type(expected_actor_device_id) is not int
            or expected_actor_device_id != MAINTENANCE_POLICY["actor_device_id"]
            or type(target_id) is not int or target_id != MAINTENANCE_POLICY["target_device_id"]):
        raise ResultPermissionDenied("Wartungsauftrag liegt außerhalb der geprüften Actor-/Zielpolicy")
    actor = _correction_operator_device_id(conn, token)
    if actor != expected_actor_device_id:
        raise ResultPermissionDenied("Exakt der geprüfte aktive Wartungsoperator ist erforderlich")
    return actor


def _audit_exists(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_AUDIT,)).fetchone() is not None


def _metadata(conn, device_id):
    if type(device_id) is not int or device_id <= 0:
        raise ValueError("Ungültige Device-ID")
    row = _dict_row(conn.execute(
        "SELECT id,name,status,created_at,revoked_at,last_seen_at FROM devices WHERE id=?", (device_id,)))
    if row is None:
        raise ResultConflict("Operator-Device nicht vorhanden")
    columns = {item[1] for item in conn.execute("PRAGMA table_info(task_result_operators)")}
    if columns != {"device_id", "created_at", "can_request_correction"}:
        raise ResultConflict("Operator-Capability-Schema nicht bestätigt")
    capability = _dict_row(conn.execute("SELECT * FROM task_result_operators WHERE device_id=?", (device_id,)))
    if (capability is None or capability.get("device_id") != device_id
            or type(capability.get("can_request_correction")) is not int
            or capability["can_request_correction"] not in (0, 1)):
        raise ResultConflict("Vorhandene Operator-Mitgliedschaft nicht bestätigt")
    revision = (conn.execute(f"SELECT COALESCE(MAX(id),0) FROM {_AUDIT} WHERE device_id=?", (device_id,)).fetchone()[0]
                if _audit_exists(conn) else 0)
    value = {"device": row, "capability": capability, "rotation_audit_revision": revision}
    return {**value, "configuration_version": _version(value)}


def _rotation_state(conn, device_id, actor):
    value = _metadata(conn, device_id)
    if value["device"]["name"] != MAINTENANCE_POLICY["target_device_name"]:
        raise ResultConflict("Wartungsziel stimmt nicht mit der geprüften Policy überein")
    value["expected_actor_device_id"] = actor
    value["actor_preimage"] = _metadata(conn, actor)
    value["configuration_version"] = _version({k: v for k, v in value.items() if k != "configuration_version"})
    return value


def rotation_snapshot(conn, device_id, *, operator_token, expected_actor_device_id):
    if conn.in_transaction:
        raise ResultConflict("Rotation benötigt eine eigene Beobachtungstransaktion")
    actor = _operator(conn, operator_token, device_id, expected_actor_device_id)
    conn.execute("BEGIN")
    try:
        if _operator(conn, operator_token, device_id, expected_actor_device_id) != actor:
            raise ResultPermissionDenied("Wartungsoperator wurde geändert")
        return _rotation_state(conn, device_id, actor)
    finally:
        if conn.in_transaction:
            conn.rollback()


def _ensure_audit(conn):
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {_AUDIT} (
        id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
        device_id INTEGER NOT NULL, actor_device_id INTEGER NOT NULL,
        request_metadata_sha256 TEXT NOT NULL, before_metadata TEXT NOT NULL,
        after_metadata TEXT NOT NULL, occurred_at TEXT NOT NULL)""")


def _request_metadata(device_id, expected, request_id, actor):
    if (type(expected) is not dict or set(expected) != {
            "device", "capability", "rotation_audit_revision", "configuration_version",
            "expected_actor_device_id", "actor_preimage"}
            or type(expected.get("device")) is not dict
            or expected["device"].get("id") != device_id
            or type(expected.get("expected_actor_device_id")) is not int
            or expected["expected_actor_device_id"] != MAINTENANCE_POLICY["actor_device_id"]
            or actor != MAINTENANCE_POLICY["actor_device_id"]
            or type(expected.get("actor_preimage")) is not dict
            or expected["actor_preimage"].get("device", {}).get("id") != actor):
        raise ValueError("Vollständiger erwarteter Operatorzustand fehlt")
    return {"device_id": device_id, "expected": expected,
            "request_id": _uuid(request_id), "actor_device_id": actor}


def _receipt(conn, request, replacement):
    if not _audit_exists(conn):
        return None
    row = _dict_row(conn.execute(f"SELECT * FROM {_AUDIT} WHERE request_id=?", (request["request_id"],)))
    if row is None:
        return None
    if (row["device_id"] != request["device_id"] or row["actor_device_id"] != request["actor_device_id"]
            or row["request_metadata_sha256"] != _version(request)):
        raise ResultConflict("Request-ID wurde bereits anders verwendet")
    current = _rotation_state(conn, request["device_id"], request["actor_device_id"])
    recorded = json.loads(row["after_metadata"])
    stored = conn.execute("SELECT token_hash FROM devices WHERE id=?", (request["device_id"],)).fetchone()[0]
    token_matches = hmac.compare_digest(_hash_token(replacement), stored)
    if not token_matches:
        raise ResultConflict("Request gehört nicht zu diesem privaten Ersatzcredential")
    confirmed = (current["expected_actor_device_id"] == MAINTENANCE_POLICY["actor_device_id"]
                 and current["actor_preimage"] == recorded["actor_preimage"]
                 and current["device"]["status"] == "active"
                 and current["device"]["name"] == recorded["device"]["name"]
                 and current["capability"] == recorded["capability"]
                 and current["rotation_audit_revision"] == row["id"])
    return {"schema": _SCHEMA, "request_id": request["request_id"], "event_id": row["id"],
            "device_id": row["device_id"], "actor_device_id": row["actor_device_id"],
            "rotation_recorded": True, "current_credential_confirmed": confirmed,
            "metadata": current, "replayed": True}


def rotation_receipt(conn, device_id, *, expected, request_id, replacement_token, operator_token,
                     expected_actor_device_id):
    """Read-only recovery, using the same private staged value; never rotates."""
    if conn.in_transaction:
        raise ResultConflict("Recovery benötigt eine eigene Lesetransaktion")
    actor = _operator(conn, operator_token, device_id, expected_actor_device_id)
    request = _request_metadata(device_id, expected, request_id, actor)
    _replacement(replacement_token)
    conn.execute("BEGIN")
    try:
        if _operator(conn, operator_token, device_id, expected_actor_device_id) != actor:
            raise ResultPermissionDenied("Wartungsoperator wurde geändert")
        return _receipt(conn, request, replacement_token)
    finally:
        if conn.in_transaction:
            conn.rollback()


def _replacement(value):
    if type(value) is not str or not _TOKEN.fullmatch(value):
        raise ValueError("Ungültiges privates Ersatzcredential")


def _rotate_operator_credential(conn, device_id, *, expected, request_id,
                                replacement_token, operator_token, expected_actor_device_id):
    """Local owner write; callers must durably stage the value before calling."""
    if conn.in_transaction:
        raise ResultConflict("Rotation benötigt eine eigene Transaktion")
    actor = _operator(conn, operator_token, device_id, expected_actor_device_id)
    request = _request_metadata(device_id, expected, request_id, actor)
    _replacement(replacement_token)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _operator(conn, operator_token, device_id, expected_actor_device_id) != actor:
            raise ResultPermissionDenied("Wartungsoperator wurde geändert")
        prior = _receipt(conn, request, replacement_token)
        if prior is not None:
            conn.rollback()
            return prior
        before = _rotation_state(conn, device_id, actor)
        if (_json(before) != _json(expected) or before["device"]["status"] != "revoked"
                or not before["device"]["revoked_at"]):
            raise ResultConflict("Widerrufener Device-/Capability-Zustand geändert")
        old_hash = conn.execute("SELECT token_hash FROM devices WHERE id=?", (device_id,)).fetchone()[0]
        new_hash = _hash_token(replacement_token)
        if hmac.compare_digest(old_hash, new_hash):
            raise ResultConflict("Widerrufenes Credential darf nicht wiederverwendet werden")
        _ensure_audit(conn)
        cursor = conn.execute("UPDATE devices SET token_hash=?,status='active',revoked_at=NULL "
                              "WHERE id=? AND name=? AND status='revoked' AND token_hash=?",
                              (new_hash, device_id, before["device"]["name"], old_hash))
        if cursor.rowcount != 1:
            raise ResultConflict("Device-CAS nicht bestätigt")
        after = _rotation_state(conn, device_id, actor)
        if (after["actor_preimage"] != before["actor_preimage"]
                or after["capability"] != before["capability"] or after["device"]["id"] != device_id
                or any(after["device"][key] != before["device"][key]
                       for key in ("name", "created_at", "last_seen_at"))):
            raise ResultConflict("Gleiche Identity/Capabilities nicht bestätigt")
        event_id = conn.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {_AUDIT}").fetchone()[0]
        after["rotation_audit_revision"] = event_id
        after["configuration_version"] = _version({k: v for k, v in after.items() if k != "configuration_version"})
        conn.execute(f"INSERT INTO {_AUDIT} VALUES (?,?,?,?,?,?,?,?)",
                     (event_id, request_id, device_id, actor, _version(request),
                      _json(before), _json(after), datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return {"schema": _SCHEMA, "request_id": request_id, "event_id": event_id,
                "device_id": device_id, "actor_device_id": actor,
                "rotation_recorded": True, "current_credential_confirmed": True,
                "metadata": after, "replayed": False}
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def _file_identity(st):
    return {"dev": st.st_dev, "ino": st.st_ino, "uid": st.st_uid, "mode": stat.S_IMODE(st.st_mode),
            "size": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns}


def _directory_identity(st):
    return {key: value for key, value in _file_identity(st).items() if key in {"dev", "ino", "uid", "mode"}}


def _root_fd(root, expected=None):
    root = Path(root)
    if root.is_symlink() or root.resolve(strict=True) != root:
        raise ResultConflict("Privater Credentialpfad ist nicht bestätigt")
    if not _POSIX_DIR_FD:
        current = _directory_identity(root.lstat())
        if not root.is_dir() or (expected is not None and current != expected):
            raise ResultConflict("Privater Credentialparent wurde geändert")
        return root
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    current = _directory_identity(os.fstat(fd))
    if (current["uid"] != os.getuid() or current["mode"] != 0o700
            or current != _directory_identity(root.lstat())
            or expected is not None and current != expected):
        os.close(fd)
        raise ResultConflict("Privater Credentialparent wurde geändert")
    return fd


def _close_root_fd(parent_fd):
    if isinstance(parent_fd, int):
        os.close(parent_fd)


def _private_read(path, root, expected_root=None):
    path, root = Path(path), Path(root)
    if path.parent != root:
        raise ResultConflict("Privater Credentialpfad ist nicht bestätigt")
    parent_fd = _root_fd(root, expected_root)
    if not _POSIX_DIR_FD:
        if path.is_symlink() or not path.is_file():
            raise ResultConflict("Privates Credential ist nicht bestätigt")
        st = path.lstat()
        data = path.read_bytes()
        if len(data) > 4096:
            raise ResultConflict("Privates Credentialformat ist nicht bestätigt")
        if _file_identity(path.lstat()) != _file_identity(st):
            raise ResultConflict("Privates Credential änderte sich")
        return data, _file_identity(st)
    fd = None
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
            raise ResultConflict("Privates Credential ist nicht bestätigt")
        data = os.read(fd, 4097)
        if len(data) > 4096:
            raise ResultConflict("Privates Credentialformat ist nicht bestätigt")
        if _file_identity(os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)) != _file_identity(st):
            raise ResultConflict("Privates Credential änderte sich")
        return data, _file_identity(st)
    finally:
        if fd is not None:
            os.close(fd)
        _close_root_fd(parent_fd)


def _private_create(path, data, root_identity):
    path = Path(path)
    parent_fd = _root_fd(path.parent, root_identity)
    if not _POSIX_DIR_FD:
        if path.exists() or path.is_symlink():
            raise ResultConflict("Vorhandener Rotationsstand benötigt Owner-Recovery")
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        return
    fd = None
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        if fd is not None:
            os.close(fd)
        _close_root_fd(parent_fd)


def prepare_private_stage(credential_path, *, root, expected, request_id, expected_actor_device_id):
    """No DB effect. Existing stage/intent requires recovery, never a new value."""
    _uuid(request_id)
    _request_metadata(MAINTENANCE_POLICY["target_device_id"], expected, request_id, expected_actor_device_id)
    path, root = Path(credential_path), Path(root)
    parent_fd = _root_fd(root)
    try:
        root_identity = _directory_identity(os.fstat(parent_fd) if isinstance(parent_fd, int) else root.lstat())
    finally:
        _close_root_fd(parent_fd)
    old, identity = _private_read(path, root)
    prefix = "." + path.name + ".rotation-" + request_id
    stage, intent, backup = (root / (prefix + suffix) for suffix in (".pending", ".intent.json", ".revoked.backup"))
    if any(p.exists() or p.is_symlink() for p in (stage, intent, backup)):
        raise ResultConflict("Vorhandener Rotationsstand benötigt Owner-Recovery")
    replacement = secrets.token_urlsafe(32)
    _private_create(backup, old, root_identity)
    _private_create(stage, (replacement + "\n").encode("utf-8"), root_identity)
    record = {"schema": _SCHEMA, "request_id": request_id, "credential_name": path.name,
              "expected_actor_device_id": expected_actor_device_id,
              "original_identity": identity, "expected": expected,
              "root_identity": root_identity,
              "stage_name": stage.name, "backup_name": backup.name}
    _private_create(intent, _json(record).encode("utf-8"), root_identity)
    directory = _root_fd(root, root_identity)
    try:
        if isinstance(directory, int):
            os.fsync(directory)
    finally:
        _close_root_fd(directory)
    return {"intent_path": str(intent), "stage_path": str(stage), "backup_path": str(backup),
            "credential_path": str(path), "request_id": request_id}


def rotate_staged_operator_credential(conn, intent_path, *, root, operator_token):
    """The local write entry point: a durable private stage precedes the DB effect."""
    root, intent_path = Path(root), Path(intent_path)
    raw, _ = _private_read(intent_path, root)
    record = json.loads(raw)
    if record.get("schema") != _SCHEMA:
        raise ResultConflict("Privater Rotationsintent ist nicht bestätigt")
    _uuid(record["request_id"])
    names = [record[key] for key in ("credential_name", "stage_name", "backup_name")]
    if any(type(name) is not str or Path(name).name != name or name in (".", "..") for name in names):
        raise ResultConflict("Privater Rotationspfad ist nicht bestätigt")
    target, stage, backup = (root / name for name in names)
    old, identity = _private_read(target, root, record["root_identity"])
    saved, _ = _private_read(backup, root, record["root_identity"])
    data, _ = _private_read(stage, root, record["root_identity"])
    if identity != record["original_identity"] or old != saved:
        raise ResultConflict("Ursprüngliches Credential wurde verändert")
    device_id = record["expected"]["device"]["id"]
    _operator(conn, operator_token, device_id, record["expected_actor_device_id"])
    current = conn.execute("SELECT token_hash FROM devices WHERE id=?", (device_id,)).fetchone()
    if current is None or not hmac.compare_digest(_hash_token(old.decode("utf-8").strip()), current[0]):
        raise ResultConflict("Credentialdatei gehört nicht zum widerrufenen Device")
    return _rotate_operator_credential(conn, device_id, expected=record["expected"],
        request_id=record["request_id"], replacement_token=data.decode("utf-8").strip(),
        operator_token=operator_token, expected_actor_device_id=record["expected_actor_device_id"])


def install_confirmed_stage(conn, intent_path, *, root, operator_token):
    """Forward-only file install after authoritative DB confirmation; no write/retry to DB."""
    root, intent_path = Path(root), Path(intent_path)
    raw, _ = _private_read(intent_path, root)
    record = json.loads(raw)
    if record.get("schema") != _SCHEMA:
        raise ResultConflict("Privater Rotationsintent ist nicht bestätigt")
    _uuid(record["request_id"])
    names = [record[key] for key in ("credential_name", "stage_name", "backup_name")]
    if any(type(name) is not str or Path(name).name != name or name in (".", "..") for name in names):
        raise ResultConflict("Privater Rotationspfad ist nicht bestätigt")
    target, stage, backup = (root / name for name in names)
    _private_read(backup, root, record["root_identity"])
    stage_exists = stage.exists() or stage.is_symlink()
    data, stage_identity = _private_read(stage if stage_exists else target, root, record["root_identity"])
    replacement = data.decode("utf-8").strip()
    receipt = rotation_receipt(conn, record["expected"]["device"]["id"], expected=record["expected"],
                               request_id=record["request_id"], replacement_token=replacement,
                               operator_token=operator_token, expected_actor_device_id=record["expected_actor_device_id"])
    if receipt is None or receipt["current_credential_confirmed"] is not True:
        return {"state": "unconfirmed", "database_write_attempted": False, "file_installed": False}
    if stage_exists:
        old, identity = _private_read(target, root, record["root_identity"])
        if identity != record["original_identity"]:
            raise ResultConflict("Credentialdatei seit Vorbereitung verändert; kein Überschreiben")
        directory = _root_fd(root, record["root_identity"])
        try:
            if isinstance(directory, int):
                if (_file_identity(os.stat(stage.name, dir_fd=directory, follow_symlinks=False)) != stage_identity
                        or _file_identity(os.stat(target.name, dir_fd=directory, follow_symlinks=False)) != identity):
                    raise ResultConflict("Privater Stage oder Credential wurde geändert")
                os.replace(stage.name, target.name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            else:
                if (_file_identity(stage.lstat()) != stage_identity
                        or _file_identity(target.lstat()) != identity):
                    raise ResultConflict("Privater Stage oder Credential wurde geändert")
                os.replace(stage, target)
        finally:
            _close_root_fd(directory)
    installed, _ = _private_read(target, root, record["root_identity"])
    if installed != data:
        raise ResultConflict("Credentialinstallation ist nicht bestätigt")
    return {"state": "confirmed", "receipt": receipt, "file_installed": True,
            "same_device_and_capabilities": True, "database_write_attempted": False}
