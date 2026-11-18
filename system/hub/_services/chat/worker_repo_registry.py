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
import hashlib
import tempfile
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

REGISTRY_SCHEMA = "bach.worker-repo-registry.v1"
ENROLLED_SCHEMA = "bach.worker-repo-registry.v2"
_REPOSITORY_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_TASK_ID = re.compile(r"[1-9][0-9]{0,18}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
_MAX_REGISTRY_BYTES = 1_048_576


class RepositoryBindingError(RuntimeError):
    """A trusted task repository or its source clone could not be confirmed."""

    def __init__(self, message, *, reason_code="repository_unverified"):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class RepositoryBinding:
    task_id: int
    repository: str
    origin: str
    default_branch: str
    source_sha: str
    task_version: str | None = None


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
            or value.get("schema") not in {REGISTRY_SCHEMA, ENROLLED_SCHEMA}
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
        legacy = {"repository", "source_sha"}
        enrolled = legacy | {"task_version", "operator", "registered_at", "source_proof_sha256"}
        if (not isinstance(task_record, dict)
                or set(task_record) not in (legacy, enrolled)
                or value["schema"] == REGISTRY_SCHEMA and set(task_record) != legacy):
            raise RepositoryBindingError("Trusted Repo-Registry enthält eine ungültige Task-Bindung")
        repository_id = task_record.get("repository")
        canonical_repository_id(repository_id)
        if repository_id not in repositories:
            raise RepositoryBindingError("Task-Repo-Bindung verweist auf keinen registrierten Repo-Eintrag")
        if type(task_record.get("source_sha")) is not str or not _SHA.fullmatch(task_record["source_sha"]):
            raise RepositoryBindingError("Task-Repo-Bindung enthält keinen gültigen öffentlichen Source-Pin")
        if set(task_record) == enrolled:
            if (any(type(task_record[k]) is not str or re.fullmatch(r"[0-9a-f]{64}", task_record[k]) is None
                    for k in ("task_version", "source_proof_sha256"))
                    or type(task_record["operator"]) is not str
                    or re.fullmatch(r"operator:[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}", task_record["operator"]) is None):
                raise RepositoryBindingError("Versionierte Operatorbindung ist ungültig")
            try:
                timestamp = datetime.fromisoformat(task_record["registered_at"])
                if timestamp.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError):
                raise RepositoryBindingError("Operatorzeitpunkt ist ungültig") from None
    return value


def resolve_task_repository(task_id, *, path: Path | None = None) -> RepositoryBinding:
    tid = canonical_task_id(task_id)
    registry = load_registry(path)
    task_record = registry["tasks"].get(str(tid))
    if task_record is None:
        raise RepositoryBindingError("Für diese Task fehlt eine vertrauenswürdige Repo-Bindung")
    repository_id = task_record["repository"]
    record = registry["repositories"][repository_id]
    version = task_record.get("task_version")
    return RepositoryBinding(tid, repository_id, record["origin"], record["default_branch"],
                             task_record["source_sha"], version)


def enroll_task_repository(client, task_id, *, repository, task_version, source_sha,
                           expected_registry_sha256, operator, rebind_existing=False):
    """Explicit trusted operator repair, never a provider/selector fallback.

    The operator establishes the semantic task-to-project mapping independently.
    This entry point verifies native task identity/version, existing public repo
    authority and real pinned-source evidence; supplied hashes grant nothing.
    Existing bindings change only with explicit same-repository rebind, a fresh
    task version, no live lease, and no existing task worktree. Repository authority
    belongs to the stable task ID; later ordinary content updates cannot grant
    another repository. Every execution still needs its separate current lease.
    """
    from hub._services.task_lease_client import TaskLeaseClient
    if type(client) is not TaskLeaseClient or client.mode != "local" or client._conn is not None:
        raise RepositoryBindingError("Lokaler kanonischer Tasklead ohne geborgene Connection erforderlich")
    # Registration is a lead-side operator operation, never authority supplied
    # by an injected DB/transport or a caller-replaced snapshot method.
    database = Path.home() / ".bach" / "bach.db"
    if (database.is_symlink() or not database.is_file()
            or database.resolve(strict=True) != database
            or client._db_path is not None and Path(client._db_path) != database
            or getattr(client._task_policy_snapshot, "__func__", None) is not TaskLeaseClient._task_policy_snapshot
            or getattr(client._get_local_connection, "__func__", None) is not TaskLeaseClient._get_local_connection):
        raise RepositoryBindingError("Taskclient ist nicht an die kanonische Lead-Datei gebunden")
    identity = database.stat()
    if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1 or os.name != "nt" and identity.st_uid != os.getuid():
        raise RepositoryBindingError("Kanonische Taskdatei ist nicht physisch eigentümergebunden")
    def current_task_version(tid):
        current = database.lstat()
        if (not stat.S_ISREG(current.st_mode) or current.st_dev != identity.st_dev
                or current.st_ino != identity.st_ino):
            raise RepositoryBindingError("Kanonische Taskdatei wurde ausgetauscht")
        # This same-authority reader has no ensure_schema/migration path.
        observed = client._task_policy_snapshot(tid)
        if (not isinstance(observed, dict) or observed.get("schema") != "bach.task-worker-policy-override.v1"
                or observed.get("availability") != "available" or observed.get("task_id") != tid):
            raise RepositoryBindingError("Kanonischer Taskreadback fehlt")
        return observed.get("task_version")
    tid = canonical_task_id(task_id)
    canonical_repository_id(repository)
    if (type(rebind_existing) is not bool
            or type(operator) is not str or re.fullmatch(r"operator:[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}", operator) is None
            or any(type(v) is not str or re.fullmatch(r"[0-9a-f]{64}", v) is None
                   for v in (task_version, expected_registry_sha256))
            or type(source_sha) is not str or _SHA.fullmatch(source_sha) is None):
        raise RepositoryBindingError("Operator-CAS-Pins sind ungültig")
    path = registry_path()
    marker = path.with_name(path.name + ".operator-lock")
    # Same canonical operator marker as source maintenance, not another registry.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    temporary = None
    try:
        initial = _read_registry_bytes(path)
        if hashlib.sha256(initial).hexdigest() != expected_registry_sha256:
            raise RepositoryBindingError("Registry änderte sich; frisch lesen")
        registry = load_registry()
        existing = registry["tasks"].get(str(tid))
        if existing is not None:
            if (not rebind_existing or existing.get("repository") != repository
                    or existing.get("task_version") not in (None, task_version)):
                raise RepositoryBindingError("Vorhandene Taskbindung erfordert expliziten gleichen Repo-Rebind")
            from hub import worker_git
            target = worker_git.get_worktrees_dir() / f"task-{tid}"
            if target.exists() or target.is_symlink():
                raise RepositoryBindingError("Bestehender Task-Arbeitsbaum muss vor dem Source-Rebind erhalten und separat geprüft werden")
            lease = client.read(tid)
            if lease.leased or lease.status != "pending":
                raise RepositoryBindingError("Task hat keinen unbelegten Pending-Status für den Source-Rebind")
        elif rebind_existing:
            raise RepositoryBindingError("Source-Rebind braucht eine vorhandene Taskbindung")
        record = registry["repositories"].get(repository)
        if record is None:
            raise RepositoryBindingError("Projekt-Repository ist nicht kanonisch registriert")
        binding = RepositoryBinding(tid, repository, record["origin"], record["default_branch"], source_sha, task_version)
        if current_task_version(tid) != task_version:
            raise RepositoryBindingError("Taskversion änderte sich; frisch zuordnen")
        from hub import worker_git
        validate_source = getattr(worker_git, "_validate_pinned_source_clone", None)
        physical_source = getattr(worker_git, "_safe_source_clone_path", None)
        if not callable(validate_source) or not callable(physical_source):
            raise RepositoryBindingError("Installierter Sourceowner unterstützt keine gepinnte Enrollmentprüfung")
        source = physical_source(binding)
        if source != source_clone_path(repository, source_sha):
            raise RepositoryBindingError("Sourceowner bestätigt nicht den kanonischen Clonepfad")
        from .worker_write_guard import _scan_locks
        def source_fences():
            # The canonical scanner accepts directories. Scanning the registry
            # parent also observes locks protecting this existing file.
            for target in (path.parent, source):
                observed = _scan_locks(target)
                if observed.get("hook_guards") != []:
                    raise RepositoryBindingError("Sourcefence-Scan ist unvollständig")
        source_fences()
        if marker.exists():
            raise RepositoryBindingError("Kanonische Source-Operatorfence ist belegt")
        proof = validate_source(source, binding, require_current=True)
        if (not isinstance(proof, dict) or proof.get("schema") != "bach.task-public-source.v2"
                or proof.get("source_ref") != f"refs/heads/{record['default_branch']}"
                or proof.get("repository") != repository
                or proof.get("source_sha") != source_sha or proof.get("origin") != record["origin"]
                or proof.get("visibility") != "public" or proof.get("private") is not False
                or proof.get("metadata_verified") is not True or proof.get("ref_verified") is not True):
            raise RepositoryBindingError("Public-Source-Owner bestätigt die Zuordnung nicht")
        descriptor = os.open(marker, flags, 0o600)
        marker_identity = os.fstat(descriptor)
        if (not stat.S_ISREG(marker_identity.st_mode) or marker_identity.st_nlink != 1
                or os.name != "nt" and (marker_identity.st_uid != os.getuid() or marker_identity.st_mode & 0o077)):
            raise RepositoryBindingError("Operatorfence ist keine reguläre Datei")
        source_fences()
        # Recheck the same physical immutable source while holding the existing
        # cooperative source-maintenance marker; caller assertions are unused.
        rechecked = validate_source(source, binding, require_current=True)
        if any(rechecked.get(k) != proof.get(k) for k in
               ("repository", "origin", "source_sha", "source_ref", "visibility", "private", "metadata_verified", "ref_verified")):
            raise RepositoryBindingError("Sourceowner änderte seine Bestätigung")
        if _read_registry_bytes(path) != initial or current_task_version(tid) != task_version:
            raise RepositoryBindingError("Task oder Registry änderte sich vor Enrollment")
        registered_at = datetime.now(timezone.utc).isoformat()
        registry["schema"] = ENROLLED_SCHEMA
        registry["tasks"][str(tid)] = {"repository": repository, "source_sha": source_sha,
            "task_version": task_version, "operator": operator, "registered_at": registered_at,
            "source_proof_sha256": hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        raw = (json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".repo-enrollment-", delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, 0o600)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        latest_version = current_task_version(tid)
        latest_lease = client.read(tid) if rebind_existing else None
        if (_read_registry_bytes(path) != initial or latest_version != task_version
                or marker.lstat().st_ino != marker_identity.st_ino
                or latest_lease is not None and (latest_lease.leased or latest_lease.status != "pending")
                or rebind_existing and (target.exists() or target.is_symlink())):
            raise RepositoryBindingError("Enrollmentfence, Task-Status oder Preimage änderte sich")
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        observed = resolve_task_repository(tid)
        if observed != binding:
            raise RepositoryBindingError("Enrollmentreadback stimmt nicht")
        return {"task_id": tid, "repository": repository, "source_sha": source_sha,
                "task_version": task_version, "operator": operator,
                "registry_sha256": hashlib.sha256(_read_registry_bytes(path)).hexdigest(),
                "registered_at": registered_at, "task_mutated": False}
    except FileExistsError:
        raise RepositoryBindingError("Kanonische Source-Operatorfence ist belegt") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if descriptor is not None:
            current = marker.lstat()
            os.close(descriptor)
            if current.st_ino == marker_identity.st_ino and current.st_dev == marker_identity.st_dev:
                marker.unlink()


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


class _RegistryWriter:
    """Existing operator fence shared by enrollment and native child inheritance."""

    def __init__(self, expected_sha256=None):
        self.path = registry_path()
        self.marker = self.path.with_name(self.path.name + ".operator-lock")
        self.expected = expected_sha256
        self.descriptor = None
        self.identity = None
        self.before = None

    def __enter__(self):
        if self.expected is not None and (
                type(self.expected) is not str or re.fullmatch(r"[0-9a-f]{64}", self.expected) is None):
            raise RepositoryBindingError("Registry-CAS-Pin ist ungültig", reason_code="registry_changed")
        self.before = _read_registry_bytes(self.path)
        if self.expected is not None and hashlib.sha256(self.before).hexdigest() != self.expected:
            raise RepositoryBindingError("Registry wurde geändert; frisch lesen", reason_code="registry_changed")
        self.check_fences()  # No marker creation beneath an already active native lock.
        try:
            self.descriptor = os.open(self.marker,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            raise RepositoryBindingError("Registry-Schreibfence ist belegt", reason_code="registry_busy") from None
        try:
            self.identity = os.fstat(self.descriptor)
            if (not stat.S_ISREG(self.identity.st_mode) or self.identity.st_nlink != 1
                    or os.name != "nt" and (self.identity.st_uid != os.getuid()
                                            or self.identity.st_mode & 0o077)):
                raise RepositoryBindingError("Registry-Schreibfence ist ungültig", reason_code="registry_busy")
            self.check_fences()
            self.assert_current()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def check_fences(self):
        from .worker_write_guard import _scan_locks
        try:
            if _scan_locks(self.path.parent).get("hook_guards") != []:
                raise ValueError
        except Exception:
            raise RepositoryBindingError("Native Registry-Sperrprüfung nicht bestätigt",
                                         reason_code="registry_fence_unavailable") from None

    def assert_current(self):
        try:
            current = self.marker.lstat()
            unchanged = ((current.st_dev, current.st_ino) == (self.identity.st_dev, self.identity.st_ino)
                         and stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                         and (os.name == "nt" or current.st_uid == os.getuid() and not current.st_mode & 0o077))
        except OSError:
            unchanged = False
        if not unchanged:
            raise RepositoryBindingError("Registry-Schreibfence wurde geändert", reason_code="registry_changed")
        if _read_registry_bytes(self.path) != self.before:
            raise RepositoryBindingError("Registry-Preimage wurde geändert", reason_code="registry_changed")

    def publish(self, value):
        self.assert_current()
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(raw) > _MAX_REGISTRY_BYTES:
            raise RepositoryBindingError("Registry überschreitet das Größenlimit", reason_code="registry_changed")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".repo-inherit-", delete=False) as output:
                temporary = Path(output.name)
                os.chmod(temporary, 0o600)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            self.assert_current()
            os.replace(temporary, self.path)
            temporary = None
            self.before = raw
            if os.name != "nt":
                directory = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            self.assert_current()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def __exit__(self, *_):
        if self.descriptor is None:
            return
        try:
            try:
                current = self.marker.lstat()
            except OSError:
                current = None
            if (current is not None and self.identity is not None
                    and (current.st_dev, current.st_ino) == (self.identity.st_dev, self.identity.st_ino)):
                self.marker.unlink()
        finally:
            os.close(self.descriptor)
            self.descriptor = None


def _canonical_review_client(client):
    from hub._services.task_lease_client import TaskLeaseClient
    database = Path.home() / ".bach" / "bach.db"
    if (type(client) is not TaskLeaseClient or client.mode != "local" or client._conn is not None
            or client._db_path is not None and Path(client._db_path) != database
            or getattr(client._get_local_connection, "__func__", None) is not TaskLeaseClient._get_local_connection):
        raise RepositoryBindingError("Kanonischer lokaler Leadclient erforderlich", reason_code="canonical_lead_required")
    try:
        identity = database.lstat()
        if (database.is_symlink() or database.resolve(strict=True) != database
                or not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1
                or os.name != "nt" and identity.st_uid != os.getuid()):
            raise OSError
    except OSError:
        raise RepositoryBindingError("Kanonische Lead-Datei nicht bestätigt", reason_code="canonical_lead_required") from None
    return database, identity


def _assert_database_identity(database, identity):
    try:
        current = database.lstat()
        valid = (stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                 and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino))
    except OSError:
        valid = False
    if not valid:
        raise RepositoryBindingError("Kanonische Lead-Datei wurde geändert", reason_code="canonical_lead_required")


def canonical_review_connection(conn):
    """No side effects: a borrowed or test database must never write live registry state."""
    database = Path.home() / ".bach" / "bach.db"
    try:
        files = [row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"]
        return (not conn.in_transaction and files == [str(database)]
                and database.is_file() and not database.is_symlink()
                and database.resolve(strict=True) == database)
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        return False


def _review_repository_evidence(conn, task_id, task_version):
    from hub._services import worker_result_review as review
    from hub._services.worker_result_provenance import source_kind
    found = review._intent(conn, task_id)
    if found is None:
        raise RepositoryBindingError("Privater Review-Intent fehlt oder ist ungültig",
                                     reason_code="review_provenance_unavailable")
    task = found["task"]
    if task.get("status") not in {"pending", "open"} or task.get("claim_id"):
        raise RepositoryBindingError("Review ist nicht frei und ausstehend", reason_code="review_not_pending")
    if review.task_content_version(task) != task_version:
        raise RepositoryBindingError("Review-Auftragsversion wurde geändert", reason_code="review_provenance_changed")
    pair = review._intent_target(conn, found)
    if pair is None or source_kind(pair[0]) != "native":
        raise RepositoryBindingError("Frische native Parent-/Result-Provenienz fehlt",
                                     reason_code="review_provenance_unavailable")
    target, authority = pair
    pin = (found["row"]["intent_sha256"], target["task_id"], target["result_id"],
           target["result_revision"], target["task_version"], task_version,
           authority["policy_version"], authority["identity_version"])
    return found, target, authority, pin


def enroll_review_task_repository(client, review_task_id, *, task_version,
                                  expected_registry_sha256, operator):
    """Derive a native review's repository solely from its verified parent result.

    It inherits the parent's immutable source pin; it never provisions a clone,
    substitutes a current main revision, issues review grants or accepts results.
    Canonical source checks happen outside SQLite transactions. Final intent,
    task and result CAS run under the SQLite writer while the existing registry
    operator fence is held. No alternate registry or caller-selected repo exists.
    """
    from hub import worker_git
    from hub._services import worker_result_review as review
    from .worker_write_guard import _scan_locks
    tid = canonical_task_id(review_task_id)
    if (type(task_version) is not str or re.fullmatch(r"[0-9a-f]{64}", task_version) is None
            or type(operator) is not str
            or re.fullmatch(r"operator:[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}", operator) is None):
        raise RepositoryBindingError("Review-Enrollment-Pins sind ungültig", reason_code="review_provenance_changed")
    if (type(expected_registry_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_registry_sha256) is None):
        raise RepositoryBindingError("Expliziter Registry-CAS-Pin fehlt oder ist ungültig",
                                     reason_code="registry_changed")
    database, identity = _canonical_review_client(client)
    conn = client._get_local_connection()
    try:
        with _RegistryWriter(expected_registry_sha256) as writer:
            _assert_database_identity(database, identity)
            found, target, authority, initial_pin = _review_repository_evidence(conn, tid, task_version)
            data = load_registry()
            parent = data["tasks"].get(str(target["task_id"]))
            if parent is None:
                raise RepositoryBindingError("Verifizierte Repository-Bindung des Elternresultats fehlt",
                                             reason_code="parent_binding_missing")
            repository = parent["repository"]
            record = data["repositories"][repository]
            parent_binding = RepositoryBinding(target["task_id"], repository, record["origin"],
                record["default_branch"], parent["source_sha"], parent.get("task_version"))
            existing = data["tasks"].get(str(tid))
            if existing is not None and any(existing.get(key) != parent[key] for key in ("repository", "source_sha")):
                raise RepositoryBindingError("Vorhandene Review-Bindung widerspricht dem Elternresultat",
                                             reason_code="review_binding_conflict")

            def verify_source():
                try:
                    source = worker_git._safe_source_clone_path(parent_binding)
                    if source != source_clone_path(repository, parent_binding.source_sha):
                        raise ValueError
                    for path in (writer.path.parent, source):
                        if _scan_locks(path).get("hook_guards") != []:
                            raise ValueError
                    proof = worker_git._validate_pinned_source_clone(source, parent_binding, require_current=False)
                    expected = {"schema": "bach.task-public-source.v2", "repository": repository,
                        "origin": parent_binding.origin, "source_sha": parent_binding.source_sha,
                        "source_ref": "refs/heads/" + parent_binding.default_branch,
                        "visibility": "public", "private": False, "metadata_verified": True, "ref_verified": True}
                    if (not isinstance(proof, dict)
                            or any(proof.get(k) != value for k, value in expected.items())
                            or proof.get("private") is not False
                            or proof.get("metadata_verified") is not True
                            or proof.get("ref_verified") is not True):
                        raise ValueError
                    return proof
                except (RuntimeError, OSError, ValueError, TypeError, KeyError):
                    raise RepositoryBindingError("Gepinnte Parent-Source ist nicht frisch bestätigt",
                                                 reason_code="review_source_unverified") from None

            verify_source()
            proof = verify_source()
            fresh_found, fresh_target, fresh_authority, fresh_pin = _review_repository_evidence(conn, tid, task_version)
            if fresh_pin != initial_pin:
                raise RepositoryBindingError("Review-Provenienz wurde vor Enrollment geändert",
                                             reason_code="review_provenance_changed")
            _assert_database_identity(database, identity)
            conn.execute("BEGIN IMMEDIATE")
            try:
                # No Git, network or nested DB client reads while holding this writer.
                current = review._intent(conn, tid)
                if (current is None or current["row"]["intent_sha256"] != fresh_found["row"]["intent_sha256"]
                        or review.task_content_version(current["task"]) != task_version
                        or current["task"].get("status") not in {"pending", "open"}
                        or current["task"].get("claim_id")
                        or not review._same_target_db(conn, fresh_target, fresh_authority)):
                    raise RepositoryBindingError("Review-/Parent-CAS ist nicht mehr aktuell",
                                                 reason_code="review_provenance_changed")
                _assert_database_identity(database, identity)
                writer.assert_current()
                if existing is None:
                    registered_at = datetime.now(timezone.utc).isoformat()
                    data["schema"] = ENROLLED_SCHEMA
                    data["tasks"][str(tid)] = {
                        "repository": repository, "source_sha": parent_binding.source_sha,
                        "task_version": task_version, "operator": operator, "registered_at": registered_at,
                        "source_proof_sha256": hashlib.sha256(json.dumps(
                            proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    }
                    writer.publish(data)
            finally:
                conn.rollback()  # Only held the writer for a cross-store CAS; no task changes.
            observed = resolve_task_repository(tid)
            if (observed.repository != repository or observed.source_sha != parent_binding.source_sha):
                raise RepositoryBindingError("Review-Enrollment-Readback stimmt nicht", reason_code="registry_changed")
            return {"state": "already_bound" if existing is not None else "enrolled",
                    "task_id": tid, "parent_task_id": target["task_id"],
                    "target_result_id": target["result_id"], "repository": repository,
                    "source_sha": parent_binding.source_sha, "task_version": task_version,
                    "registry_sha256": hashlib.sha256(_read_registry_bytes(writer.path)).hexdigest(),
                    "task_mutated": False}
    finally:
        conn.close()


def _native_decomposition_receipt(conn, task_id, task_version=None):
    """Read the existing native audit relation, never IDs asserted by task text."""
    from hub._services import task_lease as native
    row = conn.execute(
        "SELECT id,new_value FROM task_history WHERE task_id=? AND action='lease_decompose' "
        "AND field_changed='lease' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    try:
        if row is None or type(row[1]) is not str or len(row[1]) > 65536:
            raise ValueError
        record = json.loads(row[1], object_pairs_hook=_json_no_duplicates)
        children = record["created_ids"]
        if (not isinstance(record, dict) or record.get("parent_closed") is not False
                or type(record.get("fence")) is not int or record["fence"] <= 0
                or task_version is not None and record.get("task_version") != task_version
                or not isinstance(children, list) or not 1 <= len(children) <= 100
                or len(set(children)) != len(children)
                or any(type(tid) is not int or canonical_task_id(tid) != tid for tid in children)
                or not isinstance(record.get("reused_ids"), list)
                or any(tid not in children for tid in record["reused_ids"])
                or any(type(record.get(key)) is not str
                       or re.fullmatch(r"[0-9a-f]{64}", record[key]) is None
                       for key in ("previous_task_version", "task_version"))):
            raise ValueError
        request_digest = record.get("request_sha256")
        if request_digest is not None and (type(request_digest) is not str
                or re.fullmatch(r"[0-9a-f]{64}", request_digest) is None):
            raise ValueError
        versions = record.get("child_task_versions")
        if versions is not None and (not isinstance(versions, dict)
                or set(versions) != {str(tid) for tid in children}
                or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                       for value in versions.values())):
            raise ValueError
        return {**record, "event_id": row[0],
                "event_sha256": hashlib.sha256(row[1].encode()).hexdigest()}
    except (TypeError, ValueError, KeyError, RepositoryBindingError):
        raise RepositoryBindingError("Nativer Zerlegungsbeleg fehlt oder ist nicht aktuell",
                                     reason_code="decomposition_receipt_unavailable") from None


def inherit_decomposed_task_repositories(binding, *, expected_child_ids=None,
                                        request_sha256=None, inspect_only=False):
    """Complete an existing native decomposition under fresh holder and child CAS.

    Completion readback uses the native event and existing trusted bindings.
    Missing bindings need a matching native operation and exact parent/child
    content pins under a fresh canonical parent lease. Callers cannot choose
    other IDs, repositories, source pins or a different database.
    """
    from .worker_lease_binding import WorkerLeaseBinding
    from hub._services import task_lease as native
    if type(binding) is not WorkerLeaseBinding:
        raise RepositoryBindingError("Native Parentbindung fehlt", reason_code="parent_lease_unconfirmed")
    binding.assert_active(soft=True)
    client = binding._client
    database, identity = _canonical_review_client(client)
    version = binding._snapshot["task_version"]
    conn = client._get_local_connection()
    try:
        receipt = _native_decomposition_receipt(conn, binding.task_id)
        children = tuple(receipt["created_ids"])
        if expected_child_ids is not None and tuple(expected_child_ids) != children:
            raise RepositoryBindingError("Kind-IDs widersprechen dem nativen Beleg",
                                         reason_code="decomposition_receipt_unavailable")
        def holder_check():
            binding._assert_authority_active(soft=True)
            _assert_database_identity(database, identity)
            _parent, problem = native._load_for_holder(conn, binding.task_id,
                binding._ack.lease_id, binding._ack.fence, binding._clock(),
                native.LeaseConfig.from_env(), version)
            if problem:
                raise RepositoryBindingError("Aktuelle Parent-Lease nicht bestätigt",
                                             reason_code="parent_lease_unconfirmed")

        holder_check()
        with _RegistryWriter() as writer:
            data = load_registry()
            parent = data["tasks"].get(str(binding.task_id))
            if parent is None:
                raise RepositoryBindingError("Parent-Repository-Bindung fehlt",
                                             reason_code="parent_binding_missing")
            writer.check_fences()
            conn.execute("BEGIN IMMEDIATE")
            try:
                holder_check()
                fresh = _native_decomposition_receipt(conn, binding.task_id)
                if fresh != receipt:
                    raise RepositoryBindingError("Zerlegungsbeleg wurde geändert",
                                                 reason_code="decomposition_receipt_changed")
                matching_request = (request_sha256 is not None
                                    and request_sha256 == receipt.get("request_sha256"))
                all_bound = all(
                    isinstance(data["tasks"].get(str(child_id)), dict)
                    and all(data["tasks"][str(child_id)].get(key) == parent[key]
                            for key in ("repository", "source_sha"))
                    for child_id in children)
                if all_bound or inspect_only:
                    # Existing authority is stable by task ID. Historical content
                    # versions constrain new publication, not later ordinary edits.
                    writer.assert_current()
                    return {"state": "bound" if all_bound else "pending",
                            "task_id": binding.task_id, "created_ids": children,
                            "task_version": version, "event_id": receipt["event_id"],
                            "request_matches": matching_request, "changed": False}
                if receipt["task_version"] != version:
                    raise RepositoryBindingError("Parentversion wurde seit der Zerlegung geändert",
                                                 reason_code="decomposition_receipt_unavailable")
                if expected_child_ids is None and not matching_request:
                    raise RepositoryBindingError("Aufruf passt nicht zum nativen Zerlegungsbeleg",
                                                 reason_code="decomposition_request_changed")
                changed = False
                for child_id in children:
                    row = native._row(conn, child_id)
                    versions = receipt.get("child_task_versions")
                    if row is None or (versions is not None
                            and native.task_content_version(row) != versions[str(child_id)]):
                        raise RepositoryBindingError("Kindversion wurde geändert",
                                                     reason_code="child_version_changed")
                    existing = data["tasks"].get(str(child_id))
                    if existing is not None:
                        if any(existing.get(key) != parent[key] for key in ("repository", "source_sha")):
                            raise RepositoryBindingError("Vorhandene Kindbindung widerspricht dem Parent",
                                                         reason_code="child_binding_conflict")
                        continue
                    if versions is None:
                        raise RepositoryBindingError("Historischer Zerlegungsbeleg braucht explizite Operatorreparatur",
                                                     reason_code="decomposition_receipt_legacy")
                    if row.get("status") not in {"pending", "open"} or row.get("claim_id"):
                        raise RepositoryBindingError("Kind ist nicht frei und ausstehend",
                                                     reason_code="child_not_pending")
                    entry = {"repository": parent["repository"], "source_sha": parent["source_sha"]}
                    if "source_proof_sha256" in parent:
                        data["schema"] = ENROLLED_SCHEMA
                        entry.update(task_version=receipt["child_task_versions"][str(child_id)],
                            operator=parent["operator"], registered_at=datetime.now(timezone.utc).isoformat(),
                            source_proof_sha256=parent["source_proof_sha256"])
                    data["tasks"][str(child_id)] = entry
                    changed = True
                holder_check()
                writer.assert_current()
                if changed:
                    writer.publish(data)
            finally:
                conn.rollback()
            return {"state": "bound", "task_id": binding.task_id, "created_ids": children,
                    "task_version": version, "event_id": receipt["event_id"],
                    "request_matches": matching_request, "changed": changed}
    finally:
        conn.close()
