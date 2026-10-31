"""Private, durable archive for terminal worker model-request receipts.

The archive stores only records accepted by :mod:`slots_config`; it never
copies a worker profile or conversation data.  Each receipt is an immutable
JSON file whose name is derived from the worker id and request id.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterable

from . import slots_config


_ARCHIVE_SCHEMA = "bach.worker-model-request-archive.v1"
_ARCHIVE_FIELDS = {
    "schema", "worker_id", "start_request_id", "archived_at",
    "record_sha256", "record",
}
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_DURABLE_ERROR = "POSIX-Verzeichnissync für Modellanfrage-Archiv nicht verfügbar"


class WorkerRunArchiveError(RuntimeError):
    """Raised when a receipt cannot be safely validated or archived."""


def _canonical_json(value: Any, *, newline: bool = True) -> bytes:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        if not newline:
            raw = raw[:-1]
        return raw
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise WorkerRunArchiveError("Modellanfragebeleg ist nicht kanonisch serialisierbar") from exc


def _record_bytes(record: dict[str, Any]) -> bytes:
    return _canonical_json(record, newline=False)


def _archive_filename(worker_id: str, start_request_id: str) -> str:
    worker_hash = hashlib.sha256(worker_id.encode("utf-8", errors="strict")).hexdigest()
    return f"{worker_hash}-{start_request_id}.json"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_document(raw: bytes) -> dict[str, Any]:
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkerRunArchiveError("Modellanfrage-Archivdatei ist ungültig") from exc
    if type(document) is not dict:
        raise WorkerRunArchiveError("Modellanfrage-Archivdatei ist ungültig")
    return document


def _valid_archived_at(value: Any) -> bool:
    if type(value) is not str or _TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
        and parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") == value
    )


def _validate_archive_document(
    document: dict[str, Any], worker_id: str, start_request_id: str,
) -> bytes:
    if (
        set(document) != _ARCHIVE_FIELDS
        or document.get("schema") != _ARCHIVE_SCHEMA
        or document.get("worker_id") != worker_id
        or document.get("start_request_id") != start_request_id
        or not _valid_archived_at(document.get("archived_at"))
        or type(document.get("record_sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", document["record_sha256"]) is None
    ):
        raise WorkerRunArchiveError("Modellanfrage-Archivbindung ist ungültig")
    try:
        record = slots_config._validated_model_request_record(document.get("record"))
    except (RuntimeError, TypeError, ValueError) as exc:
        raise WorkerRunArchiveError("Archivierter Modellanfragebeleg ist ungültig") from exc
    if (
        record["phase"] != "terminal"
        or record["worker_id"] != worker_id
        or record["start_request_id"] != start_request_id
    ):
        raise WorkerRunArchiveError("Archivierter Modellanfragebeleg ist nicht terminal gebunden")
    record_raw = _record_bytes(record)
    if hashlib.sha256(record_raw).hexdigest() != document["record_sha256"]:
        raise WorkerRunArchiveError("Archivierter Modellanfragebeleg-Hash stimmt nicht")
    return record_raw


def _require_posix_durability() -> None:
    if os.name != "posix":
        raise OSError(_DURABLE_ERROR)
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if any(not hasattr(os, flag) for flag in required_flags):
        raise OSError(_DURABLE_ERROR)
    if not all(
        function in getattr(os, "supports_dir_fd", set())
        for function in (os.open, os.mkdir, os.link, os.unlink)
    ) or os.link not in getattr(os, "supports_follow_symlinks", set()):
        raise OSError(_DURABLE_ERROR)


def _open_private_directory(directory: str | os.PathLike[str]) -> int:
    raw_path = os.fspath(directory)
    if type(raw_path) is not str or not os.path.isabs(raw_path):
        raise WorkerRunArchiveError("Archivverzeichnis muss ein absoluter POSIX-Pfad sein")
    normalized = os.path.normpath(raw_path)
    components = [part for part in normalized.split(os.sep) if part]
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    current_fd = os.open(os.sep, flags)
    try:
        if not components:
            raise WorkerRunArchiveError("Wurzelverzeichnis ist kein privates Archivverzeichnis")
        for index, component in enumerate(components):
            child_fd: int | None = None
            try:
                child_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
                os.fsync(current_fd)
                child_fd = os.open(component, flags, dir_fd=current_fd)
            try:
                child_stat = os.fstat(child_fd)
                if not stat.S_ISDIR(child_stat.st_mode):
                    raise WorkerRunArchiveError("Archivpfad enthält kein Verzeichnis")
                if index == len(components) - 1:
                    if child_stat.st_uid != os.geteuid() or child_stat.st_mode & 0o077:
                        raise WorkerRunArchiveError("Archivverzeichnis ist nicht privat")
                previous_fd = current_fd
                current_fd = child_fd
                child_fd = None
                os.close(previous_fd)
            finally:
                if child_fd is not None:
                    os.close(child_fd)
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_existing(
    directory_fd: int, filename: str, worker_id: str, start_request_id: str,
) -> bytes | None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(filename, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o077
        ):
            raise WorkerRunArchiveError("Archivdatei ist nicht privat oder keine reguläre Datei")
        raw = _read_all(fd)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        ) or len(raw) != after.st_size:
            raise WorkerRunArchiveError("Archivdatei wurde während der Prüfung verändert")
        document = _parse_document(raw)
        record_raw = _validate_archive_document(document, worker_id, start_request_id)
        if _canonical_json(document) != raw:
            raise WorkerRunArchiveError("Archivdatei ist nicht kanonisch gespeichert")
        os.fsync(fd)
        return record_raw
    finally:
        os.close(fd)


def _write_all(fd: int, raw: bytes) -> None:
    view = memoryview(raw)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("Archivdatei konnte nicht vollständig geschrieben werden")
        view = view[written:]


def _new_document(worker_id: str, record: dict[str, Any], record_raw: bytes) -> dict[str, Any]:
    return {
        "schema": _ARCHIVE_SCHEMA,
        "worker_id": worker_id,
        "start_request_id": record["start_request_id"],
        "archived_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "record_sha256": hashlib.sha256(record_raw).hexdigest(),
        "record": record,
    }


def _publish_new(
    directory_fd: int,
    filename: str,
    worker_id: str,
    record: dict[str, Any],
    record_raw: bytes,
) -> None:
    document = _new_document(worker_id, record, record_raw)
    raw = _canonical_json(document)
    temporary = f".tmp-{secrets.token_hex(16)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd: int | None = None
    temporary_created = False
    try:
        fd = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
        temporary_created = True
        _write_all(fd, raw)
        os.fsync(fd)
        fd_to_close = fd
        fd = None
        os.close(fd_to_close)
        try:
            os.link(
                temporary,
                filename,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            # Another caller may have published the same immutable receipt.
            pass
    finally:
        if fd is not None:
            os.close(fd)
        if temporary_created:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def archive_terminal_records(
    worker_id: str,
    records: Iterable[dict[str, Any]],
    directory: str | os.PathLike[str],
) -> int:
    """Durably archive validated terminal receipts for one worker.

    Returns the number of distinct receipts verified present, including exact
    matches already archived by an earlier call.  An empty batch returns zero
    before platform or path checks and performs no filesystem operation.
    """
    try:
        batch = list(records)
    except TypeError as exc:
        raise WorkerRunArchiveError("Modellanfragebelege müssen iterierbar sein") from exc
    if not batch:
        return 0
    if type(worker_id) is not str or not worker_id:
        raise WorkerRunArchiveError("Worker-ID für Modellanfrage-Archiv ist ungültig")

    unique: dict[str, tuple[dict[str, Any], bytes]] = {}
    for candidate in batch:
        try:
            validated = slots_config._validated_model_request_record(candidate)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise WorkerRunArchiveError("Modellanfragebeleg ist ungültig") from exc
        record = dict(validated)
        if record["phase"] != "terminal" or record["worker_id"] != worker_id:
            raise WorkerRunArchiveError("Modellanfragebeleg ist nicht terminal an diesen Worker gebunden")
        record_raw = _record_bytes(record)
        request_id = record["start_request_id"]
        previous = unique.get(request_id)
        if previous is not None and previous[1] != record_raw:
            raise WorkerRunArchiveError("Konfligierende Belege teilen dieselbe Request-ID")
        unique[request_id] = (record, record_raw)
    if len(unique) > slots_config._MODEL_REQUEST_TERMINAL_LIMIT + 1:
        raise WorkerRunArchiveError("Zu viele Modellanfragebelege für einen Worker")

    # Match the durable slot-config contract: unsupported platforms reject
    # before creating directories or temporary files.
    _require_posix_durability()
    directory_fd = _open_private_directory(directory)
    try:
        archived = 0
        for request_id, (record, record_raw) in unique.items():
            filename = _archive_filename(worker_id, request_id)
            existing = _read_existing(directory_fd, filename, worker_id, request_id)
            if existing is not None:
                if existing != record_raw:
                    raise WorkerRunArchiveError("Archiv enthält bereits einen abweichenden Beleg")
                os.fsync(directory_fd)
                archived += 1
                continue

            _publish_new(directory_fd, filename, worker_id, record, record_raw)
            readback = _read_existing(directory_fd, filename, worker_id, request_id)
            if readback != record_raw:
                raise WorkerRunArchiveError("Modellanfragebeleg konnte nicht unverändert zurückgelesen werden")
            os.fsync(directory_fd)
            archived += 1
        return archived
    finally:
        os.close(directory_fd)
