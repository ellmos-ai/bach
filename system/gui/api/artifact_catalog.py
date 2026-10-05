"""Private, read-only catalog for files in the BACH export directory.

Directory membership proves a file exists; it does not prove its producer or
that another service is installed. Never scan the repository or user home.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import mimetypes
import os
from pathlib import Path
import re

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "exports"
ALLOWED_SUFFIXES = frozenset({".md", ".txt", ".pdf", ".docx", ".csv", ".json", ".png", ".jpg", ".jpeg"})
TEXT_SUFFIXES = frozenset({".md", ".txt", ".csv", ".json"})
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 1000
_PRIVATE_NAME = re.compile(r"(?:^|[._-])(tokens?|secrets?|credentials?|passwords?|id_rsa|id_ed25519|private|patient|health|medizin|klient)(?:[._-]|$)", re.I)


class ArtifactUnavailable(Exception):
    pass


def _safe_root() -> Path | None:
    try:
        root = ARTIFACT_ROOT.resolve(strict=True)
        return root if root.is_dir() and not ARTIFACT_ROOT.is_symlink() else None
    except (OSError, RuntimeError):
        return None


def _candidate(path: Path, root: Path):
    try:
        if path.is_symlink() or path.name.startswith(".") or _PRIVATE_NAME.search(path.name):
            return None
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            return None
        resolved = path.resolve(strict=True)
        if resolved.parent != root or not resolved.is_file():
            return None
        stat = resolved.stat()
        if stat.st_size < 0 or stat.st_size > MAX_FILE_BYTES:
            return None
        opaque = hashlib.sha256(
            f"{resolved.name}\0{stat.st_dev}\0{stat.st_ino}\0{stat.st_mtime_ns}\0{stat.st_size}".encode("utf-8")
        ).hexdigest()[:32]
        return {
            "id": opaque,
            "name": resolved.name,
            "type": resolved.suffix.lstrip(".").lower(),
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "producer": "unknown",
            "source": "bach_exports",
            "_file": resolved,
        }
    except (OSError, RuntimeError, ValueError):
        return None


def catalog(limit: int = 50) -> dict:
    root = _safe_root()
    if root is None:
        return {"availability": "unavailable", "reason": "export_directory_missing",
                "source": "bach_exports", "artifacts": [], "count": 0}
    items = []
    try:
        for index, path in enumerate(root.iterdir()):
            if index >= MAX_CANDIDATES:
                break
            item = _candidate(path, root)
            if item is not None:
                items.append(item)
    except (OSError, RuntimeError):
        raise ArtifactUnavailable("export_directory_unreadable")
    items.sort(key=lambda item: item["modified"], reverse=True)
    public = [{k: v for k, v in item.items() if k != "_file"} for item in items[:limit]]
    return {"availability": "available", "source": "bach_exports",
            "producer_evidence": "unknown", "artifacts": public, "count": len(public),
            "observed_at": datetime.now(timezone.utc).isoformat()}


def resolve_artifact(artifact_id: str) -> tuple[Path, dict]:
    if not isinstance(artifact_id, str) or not re.fullmatch(r"[0-9a-f]{32}", artifact_id):
        raise FileNotFoundError("artifact_not_found")
    root = _safe_root()
    if root is None:
        raise ArtifactUnavailable("export_directory_missing")
    try:
        for index, path in enumerate(root.iterdir()):
            if index >= MAX_CANDIDATES:
                break
            item = _candidate(path, root)
            if item is not None and item["id"] == artifact_id:
                return item["_file"], item
    except (OSError, RuntimeError):
        raise ArtifactUnavailable("export_directory_unreadable")
    raise FileNotFoundError("artifact_not_found")


def read_artifact(artifact_id: str) -> tuple[bytes, dict]:
    path, item = resolve_artifact(artifact_id)
    root = _safe_root()
    if root is None or path.parent != root or path.is_symlink():
        raise FileNotFoundError("artifact_not_found")
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            current = path.stat()
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns
            ) or path.resolve(strict=True).parent != root:
                raise FileNotFoundError("artifact_changed")
            content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise FileNotFoundError("artifact_too_large")
        return content, item
    except (OSError, RuntimeError):
        raise FileNotFoundError("artifact_not_found")


def content_type(item: dict) -> str:
    return mimetypes.guess_type(item["name"])[0] or "application/octet-stream"
