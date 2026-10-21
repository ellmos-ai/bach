"""Operator-owned repository catalogue and private task-bound source resolution.

Task tags identify an immutable catalogue entry and its exact source commit.
They never provide filesystem paths, clone URLs, or additional tool grants.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

REGISTRY_SCHEMA = "bach.worker-project-sources.v1"
BINDING_SCHEMA = "bach.task-project-source.v1"
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
_REPOSITORY = re.compile(r"[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PREFIXES = ("worker-source:", "worker-project:", "worker-commit:", "worker-entry:")
_ENTRY_KEYS = frozenset({"repository", "origin", "repo_root", "worktrees_root",
                         "lock_scope", "source_ref", "source_sha", "source_class", "retired"})


class ProjectSourceError(RuntimeError):
    """A source was not resolved; callers must not fall back to another repo."""


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_tags(value):
    """Return only reserved source tags, rejecting malformed/ambiguous input."""
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            if not any(prefix in value for prefix in _PREFIXES):
                return ()
            raise ProjectSourceError("Projektquellen-Tags sind kein natives JSON-Array") from None
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
        raise ProjectSourceError("Projektquellen-Tags sind ungültig")
    selected = tuple(sorted(v for v in value if v.startswith(_PREFIXES)))
    if len(selected) != len(set(selected)):
        raise ProjectSourceError("Projektquellen-Tags sind mehrdeutig")
    return selected


def task_source_selector(snapshot):
    tags = source_tags(snapshot.get("tags"))
    if not tags:
        # Explicit compatibility classification, resolved once into a private
        # binding. An existing foreign project is never inferred to be BACH.
        project = snapshot.get("project")
        if project is not None and str(project).strip().casefold() not in ("", "bach", "ellmos-ai/bach"):
            raise ProjectSourceError("Die Aufgabe benötigt eine native Projektquellenbindung")
        return None
    projects = [t.removeprefix("worker-project:") for t in tags if t.startswith("worker-project:")]
    commits = [t.removeprefix("worker-commit:") for t in tags if t.startswith("worker-commit:")]
    entries = [t.removeprefix("worker-entry:") for t in tags if t.startswith("worker-entry:")]
    if (len(tags) != 4 or "worker-source:v1" not in tags or len(projects) != 1
            or len(commits) != 1 or len(entries) != 1 or not _ID.fullmatch(projects[0])
            or not _SHA.fullmatch(commits[0]) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", entries[0])):
        raise ProjectSourceError("Projektkennung oder Quellcommit der Aufgabe ist ungültig")
    digest = base64.urlsafe_b64decode(entries[0] + "=").hex()
    if base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip("=") != entries[0]:
        raise ProjectSourceError("Projektregisterrevision der Aufgabe ist ungültig")
    return projects[0], commits[0], digest


def canonical_origin(raw, repository):
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ProjectSourceError("Repositorykennung ist ungültig")
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise ProjectSourceError("Repository-Origin ist ungültig")
    if raw.startswith("git@github.com:"):
        path = raw[len("git@github.com:"):]
    else:
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError:
            raise ProjectSourceError("Repository-Origin ist ungültig") from None
        if (parsed.hostname != "github.com" or parsed.query or parsed.fragment
                or parsed.scheme not in ("https", "ssh") or parsed.password is not None
                or (parsed.scheme == "https" and (parsed.username is not None or port not in (None, 443)))
                or (parsed.scheme == "ssh" and (parsed.username not in (None, "git") or port not in (None, 22)))):
            raise ProjectSourceError("Repository-Origin entspricht nicht der genehmigten Quelle")
        path = parsed.path.removeprefix("/")
    path = path.removesuffix("/").removesuffix(".git")
    if path.casefold() != repository:
        raise ProjectSourceError("Repository-Origin entspricht nicht der genehmigten Quelle")
    return "https://github.com/" + repository


def _physical_path(raw, *, missing=False):
    if not isinstance(raw, (str, os.PathLike)) or not str(raw) or "\x00" in str(raw):
        raise ProjectSourceError("Registrierter Projektpfad ist ungültig")
    path = Path(raw)
    if not path.is_absolute() or any(p in (".", "..") for p in path.parts):
        raise ProjectSourceError("Registrierter Projektpfad muss absolut und eindeutig sein")
    for cursor in reversed((path, *path.parents)):
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise ProjectSourceError("Registrierter Projektpfad ist nicht vorhanden") from None
        except OSError:
            raise ProjectSourceError("Registrierter Projektpfad ist nicht lesbar") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ProjectSourceError("Projektpfade dürfen keine Links oder Reparsepunkte enthalten")
    try:
        resolved = path.resolve(strict=not missing)
    except (OSError, RuntimeError):
        raise ProjectSourceError("Registrierter Projektpfad ist nicht prüfbar") from None
    if resolved != path:
        raise ProjectSourceError("Registrierter Projektpfad wird umgeleitet")
    return path


def registry_path():
    return Path.home() / ".bach" / "worker-project-sources.json"


def load_registry(path=None):
    path = _physical_path(path or registry_path())
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > 1048576 or info.st_nlink != 1
                    or (os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o022))):
                raise ProjectSourceError("Projektregister ist nicht als lokale Konfiguration geschützt")
            raw = stream.read(1048577)
        value = json.loads(raw)
    except (OSError, ValueError):
        raise ProjectSourceError("Projektregister ist nicht verfügbar oder ungültig") from None
    if (not isinstance(value, dict) or not {"schema", "entries"}.issubset(value)
            or set(value) - {"schema", "entries", "legacy_bach_tasks"}
            or value["schema"] != REGISTRY_SCHEMA or not isinstance(value["entries"], dict)):
        raise ProjectSourceError("Projektregister hat ein unbekanntes Format")
    legacy = value.get("legacy_bach_tasks", {})
    if (not isinstance(legacy, dict) or any(not isinstance(key, str) or not re.fullmatch(r"[1-9][0-9]*", key)
            or not isinstance(version, str) or not _HEX.fullmatch(version) for key, version in legacy.items())):
        raise ProjectSourceError("Legacy-Klassifikation im Projektregister ist ungültig")
    return value


def _assert_legacy_classification(snapshot, *, classification_version=None):
    # Before rollout the old BACH-only runtime remains compatible. Installing
    # the registry enables project sources and ends that implicit default.
    path = registry_path()
    if not path.exists() and not path.is_symlink():
        return
    approved = load_registry().get("legacy_bach_tasks", {})
    version = classification_version or snapshot.get("task_version")
    if (type(snapshot.get("id")) is not int or snapshot["id"] <= 0
            or not isinstance(version, str) or not _HEX.fullmatch(version)
            or approved.get(str(snapshot["id"])) != version):
        raise ProjectSourceError("Untagged Aufgabe benötigt eine explizite Legacy-BACH-Klassifikation oder Projektbindung")


def _git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    try:
        result = subprocess.run(["git", *args], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        raise ProjectSourceError("Registrierte Gitquelle konnte nicht geprüft werden") from None
    if result.returncode:
        raise ProjectSourceError("Registrierte Gitquelle konnte nicht geprüft werden")
    return result.stdout.strip()


@dataclass(frozen=True)
class TaskProjectSource:
    project_id: str
    entry_sha256: str
    repository: str
    origin: str
    source_ref: str
    source_sha: str
    source_class: str
    repo_root: Path
    worktrees_root: Path
    lock_scope: Path
    selector: tuple | None = None
    legacy_task_version: str | None = None

    def public_binding(self):
        return {"schema": BINDING_SCHEMA, "project_id": self.project_id,
                "entry_sha256": self.entry_sha256, "repository": self.repository,
                "origin": self.origin, "source_ref": self.source_ref,
                "source_sha": self.source_sha, "source_class": self.source_class}


def resolve_project(project_id, source_sha, *, path=None, expected_entry=None):
    if (not isinstance(project_id, str) or not _ID.fullmatch(project_id)
            or not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha)):
        raise ProjectSourceError("Projektquelle fehlt oder ist ungültig")
    record = load_registry(path)["entries"].get(project_id)
    if (not isinstance(record, dict) or set(record) != _ENTRY_KEYS
            or record.get("source_sha") != source_sha or record.get("source_class") != "public"
            or record.get("retired") is not False
            or not isinstance(record.get("source_ref"), str)
            or not re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*", record["source_ref"])
            or ".." in record["source_ref"] or record["source_ref"].endswith(("/", ".", ".lock"))):
        raise ProjectSourceError("Projektquelle ist unbekannt, geändert oder nicht für diesen Vertrag freigegeben")
    digest = _digest(record)
    if expected_entry is not None and digest != expected_entry:
        raise ProjectSourceError("Die gebundene Projektregisterrevision wurde verändert")
    repository = record["repository"]
    origin = canonical_origin(record["origin"], repository)
    repo = _physical_path(record["repo_root"])
    root = _physical_path(record["worktrees_root"], missing=True)
    lock_scope = _physical_path(record["lock_scope"])
    if root == repo or repo in root.parents or root in repo.parents:
        raise ProjectSourceError("Projektcheckout und Taskarbeitsbäume müssen getrennt liegen")
    if not repo.is_dir() or not lock_scope.is_dir():
        raise ProjectSourceError("Projektcheckout oder Sperrbereich ist kein Verzeichnis")
    if (_physical_path(_git(repo, "rev-parse", "--show-toplevel")) != repo
            or canonical_origin(_git(repo, "remote", "get-url", "origin"), repository) != origin
            or _git(repo, "rev-parse", "--verify", source_sha + "^{commit}") != source_sha):
        raise ProjectSourceError("Lokaler Checkout entspricht nicht der genehmigten Projektquelle")
    common_raw = Path(_git(repo, "rev-parse", "--git-common-dir"))
    _physical_path(common_raw if common_raw.is_absolute() else repo / common_raw)
    return TaskProjectSource(project_id, digest, repository, origin, record["source_ref"],
                             source_sha, record["source_class"], repo, root, lock_scope,
                             (project_id, source_sha, digest))


def project_evidence_valid(evidence):
    """Pure shape validation for the native ledger reader; no Git or file IO."""
    if (not isinstance(evidence, dict) or set(evidence) != {"schema", "project_id", "entry_sha256",
            "repository", "origin", "source_ref", "source_sha", "source_class"}
            or evidence.get("schema") != BINDING_SCHEMA
            or not isinstance(evidence.get("entry_sha256"), str) or not _HEX.fullmatch(evidence["entry_sha256"])
            or not isinstance(evidence.get("project_id"), str) or not _ID.fullmatch(evidence["project_id"])
            or not isinstance(evidence.get("source_sha"), str) or not _SHA.fullmatch(evidence["source_sha"])
            or evidence.get("source_class") != "public"
            or not isinstance(evidence.get("source_ref"), str)
            or not re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*", evidence["source_ref"])
            or ".." in evidence["source_ref"] or evidence["source_ref"].endswith(("/", ".", ".lock"))):
        return False
    try:
        return canonical_origin(evidence["origin"], evidence["repository"]) == evidence["origin"]
    except (ProjectSourceError, TypeError):
        return False


def source_from_evidence(evidence, *, path=None):
    if not project_evidence_valid(evidence):
        raise ProjectSourceError("Projektquellenbeleg ist ungültig")
    source = resolve_project(evidence["project_id"], evidence["source_sha"], path=path,
                             expected_entry=evidence["entry_sha256"])
    if source.public_binding() != evidence:
        raise ProjectSourceError("Projektquellenbeleg stimmt nicht mit dem Register überein")
    return source


def project_for_binding(binding, *, repo_root=None, worktrees_dir=None):
    """Resolve once, then revalidate that same entry before every use."""
    from hub import worker_git
    snapshot = binding.task_snapshot()
    selector = task_source_selector(snapshot)
    cached = getattr(binding, "_task_project_source", None)
    if selector is None:
        _assert_legacy_classification(snapshot,
            classification_version=cached.legacy_task_version if cached else None)
    if cached is not None:
        if cached.selector != selector:
            raise ProjectSourceError("Die Projektquelle wurde während des Workerlaufs geändert")
        source = (source_from_evidence(cached.public_binding()) if selector is not None else cached)
    elif selector is not None:
        source = resolve_project(selector[0], selector[1], expected_entry=selector[2])
    else:
        repo = Path(repo_root or worker_git.get_live_repo_root()).resolve(strict=True)
        root = Path(worktrees_dir or worker_git.get_worktrees_dir())
        source = TaskProjectSource("legacy-bach", "", "ellmos-ai/bach", "https://github.com/ellmos-ai/bach",
                                   "refs/heads/main", "", "legacy-bach", repo, root, repo,
                                   legacy_task_version=snapshot.get("task_version"))
    if (repo_root is not None and Path(repo_root).resolve(strict=True) != source.repo_root
            or worktrees_dir is not None and Path(worktrees_dir).resolve(strict=False) != source.worktrees_root):
        raise ProjectSourceError("Ein Werkzeugpfad darf die private Projektquelle nicht ersetzen")
    if cached is None:
        binding._task_project_source = source
    return source


def verify_public_source(source):
    """Verify public metadata and a pin contained in the exact named branch.

    GitHub's single-ref endpoint rejects missing refs. Compare immutable SHAs
    so a subsequent branch movement cannot change the observed comparison.
    """
    from hub.worker_git import _github_json
    base = "https://api.github.com/repos/" + source.repository
    metadata = _github_json(base)
    commit = _github_json(base + "/commits/" + source.source_sha)
    if (str(metadata.get("full_name", "")).casefold() != source.repository
            or metadata.get("private") is not False or metadata.get("visibility") != "public"
            or commit.get("sha") != source.source_sha):
        raise ProjectSourceError("Öffentliche Projektquelle oder Quellcommit ist nicht bestätigt")
    ref = _github_json(base + "/git/ref/" + quote(source.source_ref.removeprefix("refs/"), safe="/"))
    obj = ref.get("object")
    tip = obj.get("sha") if isinstance(obj, dict) else None
    if (ref.get("ref") != source.source_ref or not isinstance(obj, dict)
            or obj.get("type") != "commit" or not isinstance(tip, str) or not _SHA.fullmatch(tip)):
        raise ProjectSourceError("Registrierter öffentlicher Branch ist nicht bestätigt")
    comparison = _github_json(base + "/compare/" + source.source_sha + "..." + tip)
    ancestor = comparison.get("merge_base_commit")
    compared_base = comparison.get("base_commit")
    if (comparison.get("status") not in ("identical", "ahead")
            or not isinstance(ancestor, dict) or ancestor.get("sha") != source.source_sha
            or not isinstance(compared_base, dict) or compared_base.get("sha") != source.source_sha):
        raise ProjectSourceError("Quellcommit ist kein bestätigter Vorläufer des registrierten Branches")
    return {"schema": "bach.task-public-source.v1", "task_id": "", "repository": source.repository,
            "origin": source.origin, "source_ref": source.source_ref, "source_sha": source.source_sha,
            "visibility": "public", "private": False, "metadata_verified": True, "ref_verified": True,
            "observed_ref_sha": tip, "pin_ancestor_verified": True,
            "verified_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "project_source": source.public_binding()}


def assert_source_current(binding):
    """Cheap call-boundary check; actual Git/path checks precede tool effects."""
    cached = getattr(binding, "_task_project_source", None)
    if cached is None:
        return
    if cached.selector is None:
        _assert_legacy_classification(binding.task_snapshot(), classification_version=cached.legacy_task_version)
        return
    if task_source_selector(binding.task_snapshot()) != cached.selector:
        raise ProjectSourceError("Die Projektquelle wurde während des Workerlaufs geändert")
    record = load_registry()["entries"].get(cached.project_id)
    if not isinstance(record, dict) or record.get("retired") is not False or _digest(record) != cached.entry_sha256:
        raise ProjectSourceError("Die gebundene Projektregisterrevision ist nicht mehr aktuell")


def operator_bind_task_project(conn, task_id, task_version, project_id, *, path=None):
    """Native local-operator content service; not exposed through worker tools.

    A caller-owned connection targets the existing TaskDB. The canonical task
    audit writes content/history in this one free-lease, version-bound transaction.
    """
    from hub._services.task_lease import task_content_version
    from hub.task_audit import (
        apply_task_field_changes,
        normalize_task_tags,
        row_has_live_lease,
    )
    if (type(task_id) is not int or task_id <= 0 or not isinstance(task_version, str)
            or not _HEX.fullmatch(task_version) or conn.in_transaction):
        raise ProjectSourceError("Aktuelle Taskversion und freie Transaktion sind erforderlich")
    registry = load_registry(path)
    record = registry["entries"].get(project_id)
    if not isinstance(record, dict):
        raise ProjectSourceError("Projektquelle ist nicht registriert")
    source = resolve_project(project_id, record.get("source_sha"), path=path)
    # The metadata check precedes the write transaction and never loads a model.
    verify_public_source(source)
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        raw = cursor.fetchone()
        if raw is None:
            raise ProjectSourceError("Aufgabe ist nicht vorhanden")
        task = dict(zip((column[0] for column in cursor.description), raw))
        if row_has_live_lease(task) or task_content_version(task) != task_version:
            raise ProjectSourceError("Taskversion geändert oder Aufgabe bereits übernommen")
        if task.get("status") not in ("pending", "open", "blocked", "in_progress"):
            raise ProjectSourceError("Projektquelle nur vor der nächsten Bearbeitung ändern")
        # Recheck the entry after BEGIN; unrelated catalogue additions do not
        # change this entry's authority or disturb another running worker.
        current = resolve_project(project_id, source.source_sha, path=path,
                                  expected_entry=source.entry_sha256)
        tags = json.loads(normalize_task_tags(task.get("tags")) or "[]")
        tags = [tag for tag in tags if not tag.startswith(_PREFIXES)]
        encoded_entry = base64.urlsafe_b64encode(bytes.fromhex(current.entry_sha256)).decode().rstrip("=")
        tags.extend(("worker-source:v1", "worker-project:" + project_id,
                     "worker-commit:" + current.source_sha, "worker-entry:" + encoded_entry))
        apply_task_field_changes(conn, task_id, task, {"tags": tags},
                                 changed_by="project-source-operator", project_source_authorized=True)
        cursor = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        updated = dict(zip((column[0] for column in cursor.description), cursor.fetchone()))
        version = task_content_version(updated)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"task_id": task_id, "previous_task_version": task_version,
            "task_version": version, "project_source": current.public_binding()}


def operator_register_project(project_id, record, *, expected_registry_sha256=None, path=None):
    """Atomically append one immutable source entry; never replace an ID."""
    import tempfile
    path = Path(path or registry_path())
    _physical_path(path.parent)
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise ProjectSourceError("Projektkennung ist ungültig")
    lock = path.with_name(path.name + ".operator-lock")
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    temporary = None
    try:
        if path.exists():
            catalogue = load_registry(path)
            before = path.read_bytes()
            if hashlib.sha256(before).hexdigest() != expected_registry_sha256:
                raise ProjectSourceError("Projektregister wurde seit der Auswahl geändert")
        else:
            if expected_registry_sha256 is not None:
                raise ProjectSourceError("Erwartetes Projektregister ist nicht vorhanden")
            catalogue = {"schema": REGISTRY_SCHEMA, "entries": {}}
        if project_id in catalogue["entries"]:
            raise ProjectSourceError("Projektkennungen bleiben unveränderlich und werden nicht wiederverwendet")
        if not isinstance(record, dict) or set(record) != _ENTRY_KEYS or record.get("retired") is not False:
            raise ProjectSourceError("Projektregistereintrag ist ungültig")
        candidate = {**catalogue, "entries": {**catalogue["entries"], project_id: record}}
        fd, raw_name = tempfile.mkstemp(prefix=".worker-project-source-", dir=path.parent)
        temporary = Path(raw_name)
        payload = (json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        source = resolve_project(project_id, record["source_sha"], path=temporary)
        verify_public_source(source)
        for other in catalogue["entries"].values():
            if not isinstance(other, dict):
                raise ProjectSourceError("Bestehender Projektregistereintrag ist ungültig")
            if other.get("repository") != source.repository and other.get("worktrees_root") == str(source.worktrees_root):
                raise ProjectSourceError("Verschiedene Repositories benötigen getrennte Arbeitsbaumverzeichnisse")
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        if path.read_bytes() != payload:
            raise ProjectSourceError("Projektregister konnte nicht unabhängig zurückgelesen werden")
        return source.public_binding()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


def _operator_revise_registry(change, *, expected_registry_sha256, path=None):
    """CAS an operator-only configuration revision, retaining existing IDs."""
    import tempfile
    path = Path(path or registry_path())
    _physical_path(path.parent)
    lock = path.with_name(path.name + ".operator-lock")
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    temporary = None
    try:
        catalogue = load_registry(path)
        before = path.read_bytes()
        if hashlib.sha256(before).hexdigest() != expected_registry_sha256:
            raise ProjectSourceError("Projektregister wurde seit der Auswahl geändert")
        change(catalogue)
        payload = (json.dumps(catalogue, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        fd, name = tempfile.mkstemp(prefix=".worker-project-source-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        load_registry(temporary)
        if path.read_bytes() != before:
            raise ProjectSourceError("Projektregister wurde vor der Veröffentlichung geändert")
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        if path.read_bytes() != payload:
            raise ProjectSourceError("Projektregister konnte nicht unabhängig zurückgelesen werden")
        return {"registry_sha256": hashlib.sha256(payload).hexdigest()}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


def operator_retire_project(project_id, *, expected_registry_sha256, path=None):
    """Revoke an entry in place; its ID remains a permanent CLI tombstone."""
    def change(catalogue):
        record = catalogue["entries"].get(project_id)
        if not isinstance(record, dict):
            raise ProjectSourceError("Projektquelle ist nicht registriert")
        record["retired"] = True
    return _operator_revise_registry(change, expected_registry_sha256=expected_registry_sha256, path=path)


def operator_classify_legacy_task(conn, task_id, task_version, *, expected_registry_sha256, path=None):
    """Explicitly grandfather one free, version-bound BACH task, never new tasks."""
    from hub._services.task_lease import task_content_version
    from hub.task_audit import row_has_live_lease
    if type(task_id) is not int or task_id <= 0 or conn.in_transaction:
        raise ProjectSourceError("Gültige Aufgabe und freie Transaktion sind erforderlich")
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = cursor.fetchone()
        if row is None:
            raise ProjectSourceError("Aufgabe ist nicht vorhanden")
        task = dict(zip((column[0] for column in cursor.description), row))
        if (row_has_live_lease(task) or task_content_version(task) != task_version
                or task_source_selector(task) is not None):
            raise ProjectSourceError("Legacy-Klassifikation benötigt die aktuelle ungebundene Aufgabe ohne Lease")
        def change(catalogue):
            catalogue.setdefault("legacy_bach_tasks", {})[str(task_id)] = task_version
        receipt = _operator_revise_registry(change, expected_registry_sha256=expected_registry_sha256, path=path)
        return {**receipt, "task_id": task_id, "task_version": task_version, "classification": "legacy-bach"}
    finally:
        conn.rollback()


def main(argv=None):
    """Operator CLI; worker tool dispatch does not expose this command."""
    import argparse
    parser = argparse.ArgumentParser(description="Genehmigte Worker-Projektquellen verwalten")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    register = sub.add_parser("register")
    register.add_argument("project_id")
    register.add_argument("entry_json", type=Path)
    register.add_argument("--expected-registry-sha256")
    bind = sub.add_parser("bind")
    bind.add_argument("task_id", type=int)
    bind.add_argument("project_id")
    bind.add_argument("--task-version", required=True)
    retire = sub.add_parser("retire")
    retire.add_argument("project_id")
    retire.add_argument("--expected-registry-sha256", required=True)
    legacy = sub.add_parser("classify-legacy")
    legacy.add_argument("task_id", type=int)
    legacy.add_argument("--task-version", required=True)
    legacy.add_argument("--expected-registry-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "list":
        value = load_registry()
        print(json.dumps({"entries": value["entries"], "registry_sha256": hashlib.sha256(registry_path().read_bytes()).hexdigest()}, ensure_ascii=False))
    elif args.command == "register":
        record = json.loads(args.entry_json.read_text(encoding="utf-8"))
        print(json.dumps(operator_register_project(args.project_id, record,
                         expected_registry_sha256=args.expected_registry_sha256), ensure_ascii=False))
    elif args.command == "retire":
        print(json.dumps(operator_retire_project(args.project_id,
                         expected_registry_sha256=args.expected_registry_sha256)))
    else:
        from hub.bach_paths import BACH_DB
        with sqlite3.connect(BACH_DB, timeout=20) as conn:
            receipt = (operator_classify_legacy_task(conn, args.task_id, args.task_version,
                       expected_registry_sha256=args.expected_registry_sha256)
                       if args.command == "classify-legacy" else
                       operator_bind_task_project(conn, args.task_id, args.task_version, args.project_id))
            print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
