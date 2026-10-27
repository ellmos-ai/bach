"""Trusted task-to-repository bindings for isolated worker source trees.

The registry is deliberately outside every task worktree. Worker hooks only
read it; source provisioning is an explicit operator action implemented in
``worker_git`` and never runs as part of a provider or pre-tool hook.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

REGISTRY_SCHEMA = "bach.worker-repo-registry.v1"
_REPOSITORY_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_TASK_ID = re.compile(r"[1-9][0-9]{0,18}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
_MAX_REGISTRY_BYTES = 1_048_576


class RepositoryBindingError(RuntimeError):
    """A trusted task repository or its source clone could not be confirmed."""


@dataclass(frozen=True)
class RepositoryBinding:
    task_id: int
    repository: str
    origin: str
    default_branch: str
    source_sha: str


def registry_path() -> Path:
    """Return the fixed per-user registry path; environment overrides are forbidden."""
    return Path.home() / ".bach" / "worker_repo_registry.v1.json"


def source_root() -> Path:
    """Return the fixed source-clone root, separate from task worktrees."""
    return Path.home() / ".bach" / "task-repo-sources"


def canonical_task_id(value) -> int:
    if isinstance(value, bool) or not (type(value) is int or type(value) is str):
        raise RepositoryBindingError("Task-Repo-Bindung fehlt oder ist ungültig")
    raw = str(value)
    if not _TASK_ID.fullmatch(raw) or int(raw) > 2**63 - 1:
        raise RepositoryBindingError("Task-Repo-Bindung fehlt oder ist ungültig")
    return int(raw)


def canonical_repository_id(value) -> str:
    if type(value) is not str or not _REPOSITORY_ID.fullmatch(value):
        raise RepositoryBindingError("Kanonische Repository-ID fehlt oder ist ungültig")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise RepositoryBindingError("Kanonische Repository-ID fehlt oder ist ungültig")
    return value


def canonical_default_branch(value) -> str:
    if (type(value) is not str or not _BRANCH.fullmatch(value)
            or value.startswith("/") or value.endswith("/") or "//" in value
            or ".." in value or "@{" in value
            or any(part.endswith(".lock") for part in value.split("/"))):
        raise RepositoryBindingError("Repo-Registry enthält einen ungültigen Default-Branch")
    return value


def _json_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryBindingError("Trusted Repo-Registry enthält doppelte Felder")
        result[key] = value
    return result


def _read_registry_bytes(path: Path) -> bytes:
    try:
        expected_parent = Path.home() / ".bach"
        if (expected_parent.is_symlink() or path.parent != expected_parent
                or expected_parent.resolve(strict=True) != expected_parent):
            raise RepositoryBindingError("Trusted Repo-Registry liegt nicht im geschützten lokalen BACH-Verzeichnis")
        parent_info = expected_parent.stat()
        if not stat.S_ISDIR(parent_info.st_mode):
            raise RepositoryBindingError("Trusted Repo-Registry-Elternpfad ist kein Verzeichnis")
        if os.name != "nt" and parent_info.st_mode & 0o077:
            raise RepositoryBindingError("BACH-Konfigurationsverzeichnis ist nicht auf den Eigentümer beschränkt")
        if os.name != "nt" and hasattr(os, "getuid") and parent_info.st_uid != os.getuid():
            raise RepositoryBindingError("BACH-Konfigurationsverzeichnis gehört nicht dem aktuellen Eigentümer")
        if path.is_symlink():
            raise RepositoryBindingError("Trusted Repo-Registry ist ein Symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_REGISTRY_BYTES:
                raise RepositoryBindingError("Trusted Repo-Registry ist keine zulässige reguläre Datei")
            if os.name != "nt" and info.st_mode & 0o077:
                raise RepositoryBindingError("Trusted Repo-Registry ist nicht auf den Eigentümer beschränkt")
            if os.name != "nt" and hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise RepositoryBindingError("Trusted Repo-Registry gehört nicht dem aktuellen Eigentümer")
            chunks = []
            remaining = _MAX_REGISTRY_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > _MAX_REGISTRY_BYTES:
                raise RepositoryBindingError("Trusted Repo-Registry überschreitet das Größenlimit")
            return raw
        finally:
            os.close(descriptor)
    except RepositoryBindingError:
        raise
    except OSError:
        raise RepositoryBindingError("Trusted Repo-Registry fehlt oder ist nicht lesbar") from None


def load_registry(path: Path | None = None) -> dict:
    """Read and strictly validate the trusted, task-keyed repository registry."""
    selected = path or registry_path()
    try:
        value = json.loads(_read_registry_bytes(selected).decode("utf-8"),
                           object_pairs_hook=_json_no_duplicates)
    except RepositoryBindingError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise RepositoryBindingError("Trusted Repo-Registry ist ungültig") from None
    if (not isinstance(value, dict) or set(value) != {"schema", "repositories", "tasks"}
            or value.get("schema") != REGISTRY_SCHEMA
            or not isinstance(value.get("repositories"), dict)
            or not isinstance(value.get("tasks"), dict)):
        raise RepositoryBindingError("Trusted Repo-Registry hat ein nicht unterstütztes Schema")

    repositories = value["repositories"]
    for repository_id, record in repositories.items():
        canonical_repository_id(repository_id)
        expected_origin = f"https://github.com/{repository_id}"
        if (not isinstance(record, dict)
                or set(record) != {"origin", "default_branch", "visibility"}
                or record.get("origin") != expected_origin
                or record.get("visibility") != "public"):
            raise RepositoryBindingError("Trusted Repo-Registry enthält einen ungültigen Repo-Eintrag")
        canonical_default_branch(record.get("default_branch"))

    for task_key, task_record in value["tasks"].items():
        if type(task_key) is not str or not _TASK_ID.fullmatch(task_key):
            raise RepositoryBindingError("Trusted Repo-Registry enthält eine ungültige Task-ID")
        canonical_task_id(task_key)
        if (not isinstance(task_record, dict)
                or set(task_record) != {"repository", "source_sha"}):
            raise RepositoryBindingError("Trusted Repo-Registry enthält eine ungültige Task-Bindung")
        repository_id = task_record.get("repository")
        canonical_repository_id(repository_id)
        if repository_id not in repositories:
            raise RepositoryBindingError("Task-Repo-Bindung verweist auf keinen registrierten Repo-Eintrag")
        if type(task_record.get("source_sha")) is not str or not _SHA.fullmatch(task_record["source_sha"]):
            raise RepositoryBindingError("Task-Repo-Bindung enthält keinen gültigen öffentlichen Source-Pin")
    return value


def resolve_task_repository(task_id, *, path: Path | None = None) -> RepositoryBinding:
    tid = canonical_task_id(task_id)
    registry = load_registry(path)
    task_record = registry["tasks"].get(str(tid))
    if task_record is None:
        raise RepositoryBindingError("Für diese Task fehlt eine vertrauenswürdige Repo-Bindung")
    repository_id = task_record["repository"]
    record = registry["repositories"][repository_id]
    return RepositoryBinding(tid, repository_id, record["origin"], record["default_branch"],
                             task_record["source_sha"])


def source_clone_path(repository_id: str, source_sha: str, *, root: Path | None = None) -> Path:
    repository_id = canonical_repository_id(repository_id)
    if type(source_sha) is not str or not _SHA.fullmatch(source_sha):
        raise RepositoryBindingError("Öffentlicher Source-Pin ist ungültig")
    owner, name = repository_id.split("/", 1)
    source_root_path = root or source_root()
    path = source_root_path / owner / name / source_sha
    # The layout is entirely derived from validated owner/repo/SHA fields.
    if any(part in {".", ".."} for part in path.parts):
        raise RepositoryBindingError("Public-Source-Pfad ist ungültig")
    return path
