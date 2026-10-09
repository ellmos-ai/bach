# SPDX-License-Identifier: MIT
"""Versioned domain navigation preferences; preserve legacy pins and metadata."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

from hub._services.user_config_store import _exclusive_lock

SCHEMA = "bach.domain-pins.v1"
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
VERSION = re.compile(r"^[a-f0-9]{64}$")
MAX_BYTES = 65_536
MAX_PINS = 256
ABSENT_VERSION = hashlib.sha256(b"bach.domain-pins.absent.v1").hexdigest()


class PinUnavailable(RuntimeError):
    pass


class PinConflict(RuntimeError):
    pass


class PinVersionRequired(ValueError):
    pass


def _safe_path(path: Path) -> None:
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise PermissionError("Pin-Speicher muss ein absoluter Pfad ohne Symlink sein")
    if path.with_name(path.name + ".lock").is_symlink():
        raise PermissionError("Pin-Sperrdatei darf kein Symlink sein")


def validate_ids(ids) -> list[str]:
    if not isinstance(ids, list) or len(ids) > MAX_PINS:
        raise ValueError("Pins benötigen eine Liste mit höchstens 256 IDs")
    if any(not isinstance(i, str) or not ID.fullmatch(i) for i in ids):
        raise ValueError("Ungültige Domain-ID")
    if len(set(ids)) != len(ids):
        raise ValueError("Domain-IDs dürfen nicht doppelt vorkommen")
    return list(ids)


def read(path: Path, defaults: list[str]) -> dict:
    _safe_path(path)
    if not path.exists():
        return {"ids": validate_ids(defaults), "version": ABSENT_VERSION, "persisted": False, "document": {}}
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise PinUnavailable("Pin-Speicher nicht lesbar oder zu groß")
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise PinUnavailable("Pin-Speicher ist zu groß")
        document = json.loads(raw.decode("utf-8"))
        ids = document if isinstance(document, list) else document.get("pins") if isinstance(document, dict) else None
        return {"ids": validate_ids(ids), "version": hashlib.sha256(raw).hexdigest(),
                "persisted": True, "document": document}
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PinUnavailable("Vorhandene Pins sind nicht bestätigt; Speicher bleibt unverändert") from exc


def mutate(path: Path, defaults: list[str], expected_version: str, *,
           ids=None, domain_id=None, pinned=None, guard: Callable[[Path], None] | None = None) -> dict:
    if not isinstance(expected_version, str) or not VERSION.fullmatch(expected_version):
        raise PinVersionRequired("Aktuelle Pin-Version erforderlich. Bitte aktualisieren.")
    if ids is not None:
        if domain_id is not None or pinned is not None:
            raise ValueError("Entweder Pinliste oder einzelne Domain ändern")
        cleaned = validate_ids(ids)
    else:
        if not isinstance(domain_id, str) or not ID.fullmatch(domain_id) or type(pinned) is not bool:
            raise ValueError("Domain-ID und ausdrücklicher boolescher Pinstatus erforderlich")
        cleaned = None
    if guard is None:
        from hub._services.skill_source_service import check_write_locks
        guard = check_write_locks
    _safe_path(path)
    guard(path)
    with _exclusive_lock(path):
        current = read(path, defaults)
        if current["version"] != expected_version:
            raise PinConflict("Pins wurden inzwischen geändert. Bitte aktualisieren.")
        result = list(cleaned) if cleaned is not None else list(current["ids"])
        if cleaned is None:
            if pinned and domain_id not in result:
                if len(result) >= MAX_PINS:
                    raise ValueError("Höchstens 256 Pins möglich")
                result.append(domain_id)
            elif not pinned:
                result = [i for i in result if i != domain_id]
        if current["persisted"] and result == current["ids"]:
            return current
        document = dict(current["document"]) if isinstance(current["document"], dict) else {}
        document["pins"] = result
        encoded = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise ValueError("Pin-Dokument einschließlich bestehender Metadaten ist zu groß")
        _safe_path(path)
        guard(path)
        fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        tmp = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            _safe_path(path)
            # Recheck raw content as well: a legacy writer may not share the advisory lock.
            if read(path, defaults)["version"] != expected_version:
                raise PinConflict("Pins wurden während des Speicherns geändert")
            guard(path)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                guard(tmp)
                tmp.unlink()
        actual = read(path, defaults)
        if actual["version"] != hashlib.sha256(encoded).hexdigest() or actual["ids"] != result:
            raise PinConflict("Gespeicherter Pinstand nicht bestätigt; bitte aktualisieren")
        return actual
