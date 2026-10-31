"""Fail-closed authorization for task-bound worker mutations and checks."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from core.sandbox import SandboxResult

_NATIVE_PATH = type(Path())

_RUN = subprocess.run
_WRITE_TOOLS = frozenset({
    "write_file", "edit_file", "move_file", "copy_file", "create_directory",
    "recycle", "start_task_worktree", "finish_task", "cleanup_task_worktree",
    "execute_command", "safe_shell",
})
_CHECK_BASES = frozenset({"pytest", "python", "python3", "ruff", "mypy", "pyright", "npm"})
_GIT_READ_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "rev-parse", "worktree"})
_PYTHON_MODULES = frozenset({"pytest", "unittest", "compileall", "ruff"})


class WorkerWriteGuardError(RuntimeError):
    """A worker write or check lacks current task/worktree/lock authority."""


def is_write_tool(name: str) -> bool:
    return name in _WRITE_TOOLS


def require_write_grant(name: str, allowed_tools) -> None:
    if allowed_tools is None or name not in allowed_tools:
        raise WorkerWriteGuardError("Werkzeug ist nicht ausdrücklich für diesen Worker freigegeben")


def _task_id(value) -> int:
    if isinstance(value, bool) or not str(value).isdecimal() or int(value) <= 0:
        raise WorkerWriteGuardError("Task-ID ist ungültig")
    return int(value)


def _field(view, name):
    return view.get(name) if isinstance(view, dict) else getattr(view, name, None)


def _fresh_lease(binding, task_id: int) -> None:
    if binding is None:
        raise WorkerWriteGuardError("Private Taskbindung fehlt")
    binding.assert_active()
    if _task_id(binding.task_id) != task_id:
        raise WorkerWriteGuardError("Taskbindung gehört zu einer anderen Aufgabe")
    ref = binding._ref()
    client = getattr(binding, "_client", None)
    if client is None or not callable(getattr(client, "read", None)):
        raise WorkerWriteGuardError("Kanonische Lease-Leseautorität fehlt")
    view = client.read(task_id, lease_id=ref.get("lease_id"), now=ref.get("now"))
    if not (
        _field(view, "own") is True
        and _field(view, "leased") is True
        and _field(view, "status") == "in_progress"
        and type(_field(view, "fence")) is int
        and _field(view, "fence") == ref.get("fence")
        and isinstance(_field(view, "task_version"), str)
        and _field(view, "task_version") == ref.get("task_version")
    ):
        raise WorkerWriteGuardError("Aktuelle eigene Task-Lease/Fence ist nicht bestätigt")


def authorize_safe_read(binding) -> int:
    """Validate the live task lease for a restricted, read-only shell call.

    Safe analysis may run without a task worktree. Mutations and full checks
    still go through authorize_mutation/run_bound_check and require one.
    """
    if binding is None:
        raise WorkerWriteGuardError("Private Taskbindung fehlt")
    task_id = _task_id(binding.task_id)
    _fresh_lease(binding, task_id)
    return task_id


def _paths(repo_root=None, worktrees_dir=None):
    from hub import worker_git
    repo = _NATIVE_PATH(repo_root or worker_git.get_live_repo_root()).expanduser().resolve(strict=True)
    root = _NATIVE_PATH(worktrees_dir or worker_git.get_worktrees_dir()).expanduser()
    root = _NATIVE_PATH(os.path.abspath(root))
    if root.is_symlink():
        raise WorkerWriteGuardError("Worktree-Verzeichnis ist ein Link")
    return repo, root


def _scope_git_env():
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    return env


def _run_readonly(argv, cwd, timeout=8):
    try:
        result = _RUN(
            argv, cwd=str(cwd), shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            timeout=timeout, env=_scope_git_env(),
        )
    except Exception as exc:
        raise WorkerWriteGuardError("Prüfung von Git- oder Sperrstatus fehlgeschlagen") from exc
    if result.returncode != 0:
        raise WorkerWriteGuardError("Prüfung von Git- oder Sperrstatus fehlgeschlagen")
    return result.stdout or ""


def _registered_tree(repo: Path, worktrees_root: Path, task_id: int) -> Path:
    target = worktrees_root / f"task-{task_id}"
    if target.is_symlink() or not target.is_dir():
        raise WorkerWriteGuardError("Der gebundene Task-Arbeitsbaum fehlt oder ist ein Link")
    target_real = target.resolve(strict=True)
    if target_real != target:
        raise WorkerWriteGuardError("Task-Arbeitsbaum weicht vom registrierten Pfad ab")
    records = _run_readonly(["git", "worktree", "list", "--porcelain"], repo).split("\n\n")
    expected_branch = f"refs/heads/bach-task/{task_id}"
    found = False
    for record in records:
        fields = {}
        for line in record.splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        raw_path = fields.get("worktree")
        if not raw_path:
            continue
        if _NATIVE_PATH(raw_path).resolve(strict=False) == target_real:
            if fields.get("branch") != expected_branch or "detached" in fields:
                raise WorkerWriteGuardError("Task-Arbeitsbaum ist nicht auf seinem erwarteten Branch")
            found = True
            break
    if not found:
        raise WorkerWriteGuardError("Task-Arbeitsbaum ist in Git nicht exakt registriert")
    top = _NATIVE_PATH(_run_readonly(["git", "rev-parse", "--show-toplevel"], target_real).strip()).resolve(strict=True)
    if top != target_real:
        raise WorkerWriteGuardError("Git-Root weicht vom Task-Arbeitsbaum ab")
    common = _NATIVE_PATH(_run_readonly(["git", "rev-parse", "--git-common-dir"], target_real).strip())
    if not common.is_absolute():
        common = (target_real / common).resolve(strict=True)
    else:
        common = common.resolve(strict=True)
    repo_common = _NATIVE_PATH(_run_readonly(["git", "rev-parse", "--git-common-dir"], repo).strip())
    if not repo_common.is_absolute():
        repo_common = (repo / repo_common).resolve(strict=True)
    else:
        repo_common = repo_common.resolve(strict=True)
    if common != repo_common:
        raise WorkerWriteGuardError("Task-Arbeitsbaum gehört zu einem anderen Git-Projekt")
    return target_real


def _scanner_path() -> Path:
    configured = os.environ.get("BACH_HARVEST_LOCK_SCAN") or os.environ.get("BACH_LOCK_SCAN")
    if configured:
        scanner = _NATIVE_PATH(configured).expanduser()
    elif sys.platform == "darwin":
        scanner = Path.home() / "services" / "lock-master" / "lock_scan.py"
    else:
        raise WorkerWriteGuardError("Kanonischer Sperrscanner ist nicht konfiguriert")
    if not scanner.is_file():
        raise WorkerWriteGuardError("Kanonischer Sperrscanner ist nicht verfügbar")
    return scanner.resolve(strict=True)


def _scan_locks(path: Path, *, main_repo=False) -> dict:
    scanner = _scanner_path()
    try:
        result = _RUN(
            [sys.executable, str(scanner), "--check-dir", str(path), "--json"],
            cwd=str(path if path.is_dir() else path.parent), shell=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=15,
        )
        payload = json.loads(result.stdout)
    except Exception as exc:
        raise WorkerWriteGuardError("Sperrscan fehlt oder ist nicht lesbar") from exc
    if result.returncode not in (0, 1) or not isinstance(payload, dict):
        raise WorkerWriteGuardError("Sperrscan ist fehlgeschlagen")
    if _NATIVE_PATH(str(payload.get("checked", ""))).resolve(strict=False) != path.resolve(strict=False):
        raise WorkerWriteGuardError("Sperrscan bestätigt nicht den angeforderten Pfad")
    if payload.get("twin_status") not in {"ok", "not-applicable"}:
        raise WorkerWriteGuardError("Twin-Sperrstatus ist unbekannt")
    if main_repo and payload.get("twin_status") != "ok":
        raise WorkerWriteGuardError("Kanonischer BACH-Twin wurde nicht bestätigt")
    locks = payload.get("locks")
    if not isinstance(locks, list) or locks:
        raise WorkerWriteGuardError("Fremde oder unbekannte Projektsperre blockiert")
    return payload


def _nearest_existing_directory(path: Path) -> Path:
    candidate = _NATIVE_PATH(os.path.abspath(path))
    while True:
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            parent = candidate.parent
            if parent == candidate:
                raise WorkerWriteGuardError("Vorhandener Sperrprüfungspfad fehlt")
            candidate = parent
            continue
        if stat.S_ISLNK(mode):
            raise WorkerWriteGuardError("Sperrprüfungspfad enthält einen Link")
        if stat.S_ISDIR(mode):
            return candidate.resolve(strict=True)
        parent = candidate.parent
        if parent == candidate:
            raise WorkerWriteGuardError("Vorhandener Sperrprüfungspfad fehlt")
        candidate = parent


def _fresh_locks(repo: Path, worktrees_root: Path, target: Path | None,
                 paths: Iterable[Path] = ()) -> None:
    _scan_locks(repo, main_repo=True)
    scan_dirs = [_nearest_existing_directory(worktrees_root)]
    if target is not None:
        scan_dirs.append(_nearest_existing_directory(target))
    scan_dirs.extend(_nearest_existing_directory(path) for path in paths)
    seen = set()
    for directory in scan_dirs:
        if directory == repo or directory in seen:
            continue
        seen.add(directory)
        _scan_locks(directory)


_SCOPE_SCHEMA = "bach.task-scope-snapshot.v1"
_SCOPE_CLEAN = "porcelain-v1-z-all-untracked-no-ignored"
_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _scope_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _scope_hash(value) -> str:
    return hashlib.sha256(_scope_json(value)).hexdigest()


def _scope_git(argv, cwd: Path, *, allowed=(0,), timeout=8):
    """Run one bounded local Git read without optional locks or fsmonitor hooks."""
    try:
        result = _RUN(["git", "-c", "core.fsmonitor=false",
                       "-c", "diff.external=", *argv],
                      cwd=str(cwd), shell=False, capture_output=True,
                      stdin=subprocess.DEVNULL, env=_scope_git_env(), timeout=timeout)
    except Exception as exc:
        raise WorkerWriteGuardError("Lokale Git-Sicht ist nicht lesbar") from exc
    if result.returncode not in allowed:
        raise WorkerWriteGuardError("Lokale Git-Sicht ist nicht lesbar")
    return result.returncode, result.stdout


def _scope_text(argv, cwd: Path) -> str:
    raw = _scope_git(argv, cwd)[1]
    try:
        return raw.decode("utf-8", "strict").strip()
    except UnicodeError as exc:
        raise WorkerWriteGuardError("Git-Metadaten sind ungültig") from exc


def _scope_unavailable(reason: str) -> dict:
    return {"schema": _SCOPE_SCHEMA, "availability": "unavailable", "reason": reason}


def _scope_stage(target: Path) -> bytes:
    """Inspect gitlinks before status could recurse into a submodule helper."""
    raw = _scope_git(["ls-files", "--stage", "-z"], target)[1]
    entries = raw.split(b"\0")
    if entries[-1] != b"" or any(not re.match(rb"^[0-7]{6} (?:[0-9a-f]{40}|[0-9a-f]{64}) [0-3]\t", entry)
                                      for entry in entries[:-1]):
        raise WorkerWriteGuardError("Git-Index ist nicht eindeutig lesbar")
    return raw


def snapshot_task_scope(task_id, *, repo_root=None, worktrees_dir=None) -> dict:
    """Read one registered, clean BACH task tree; never trust a worker path.

    This is a local Git/lock observation, not an accepted result or permission
    to mutate the worktree. Callers must re-read it at the point of use.
    """
    try:
        tid = _task_id(task_id)
    except (WorkerWriteGuardError, TypeError, ValueError):
        return _scope_unavailable("invalid_task_id")
    try:
        repo, root = _paths(repo_root, worktrees_dir)
    except (WorkerWriteGuardError, OSError, ValueError):
        return _scope_unavailable("paths_unavailable")
    try:
        target = _registered_tree(repo, root, tid)
    except (WorkerWriteGuardError, OSError, ValueError):
        return _scope_unavailable("registration_unavailable")
    try:
        _fresh_locks(repo, root, target)
    except (WorkerWriteGuardError, OSError, ValueError):
        return _scope_unavailable("lock_unavailable")
    from hub import worker_git
    try:
        origin = worker_git._canonical_bach_origin(
            _scope_text(["remote", "get-url", "origin"], repo))
        if worker_git._canonical_bach_origin(
                _scope_text(["remote", "get-url", "origin"], target)) != origin:
            raise WorkerWriteGuardError("Git-Origin weicht ab")
    except (WorkerWriteGuardError, RuntimeError, OSError, ValueError):
        return _scope_unavailable("origin_unavailable")
    try:
        key = worker_git._public_source_config_key(tid)
        code, raw_pin = _scope_git(["config", "--local", "--get-all", key], target,
                                   allowed=(0, 1))
        if code == 1:
            source_pin = None
        else:
            values = raw_pin.decode("utf-8", "strict").splitlines()
            if len(values) != 1:
                raise WorkerWriteGuardError("Mehrdeutige öffentliche Quellbindung")
            proof = json.loads(values[0])
            if (not isinstance(proof, dict)
                    or proof.get("schema") != "bach.task-public-source.v1"
                    or proof.get("task_id") != str(tid)
                    or proof.get("repository") != "ellmos-ai/bach"
                    or proof.get("origin") != origin
                    or proof.get("source_ref") != "refs/heads/main"
                    or not isinstance(proof.get("source_sha"), str)
                    or not re.fullmatch(r"[0-9a-f]{40}", proof["source_sha"])
                    or proof.get("visibility") != "public"
                    or proof.get("private") is not False
                    or proof.get("metadata_verified") is not True
                    or proof.get("ref_verified") is not True
                    or not isinstance(proof.get("verified_at"), str)
                    or not proof["verified_at"]):
                raise WorkerWriteGuardError("Öffentliche Quellbindung ist ungültig")
            if _scope_git(["merge-base", "--is-ancestor", proof["source_sha"], "HEAD"],
                          target, allowed=(0, 1))[0] != 0:
                raise WorkerWriteGuardError("Task-HEAD stammt nicht vom öffentlichen Pin ab")
            source_pin = {key: proof[key] for key in
                          ("schema", "source_ref", "source_sha", "verified_at")}
    except (WorkerWriteGuardError, RuntimeError, UnicodeError, KeyError, ValueError):
        return _scope_unavailable("source_pin_invalid")
    try:
        # A clean-status check must not launch repository-configured filters.
        filter_code, _ = _scope_git(
            ["config", "--get-regexp", r"^filter\..*\.(process|clean|smudge)$"],
            target, allowed=(0, 1))
        if filter_code == 0:
            return _scope_unavailable("git_unavailable")
        branch = _scope_text(["symbolic-ref", "--quiet", "HEAD"], target)
        if branch != f"refs/heads/bach-task/{tid}":
            return _scope_unavailable("registration_unavailable")
        head = _scope_text(["rev-parse", "--verify", "HEAD^{commit}"], target)
        tree = _scope_text(["rev-parse", "--verify", "HEAD^{tree}"], target)
        if not (_GIT_OID.fullmatch(head) and _GIT_OID.fullmatch(tree)
                and len(head) == len(tree)):
            return _scope_unavailable("git_unavailable")
        stage = _scope_stage(target)
        if any(entry.startswith(b"160000 ") for entry in stage.split(b"\0")[:-1]):
            return _scope_unavailable("submodule_scope_unsupported")
        status = _scope_git(["status", "--porcelain=v1", "-z",
                             "--untracked-files=all", "--ignore-submodules=none"], target)[1]
        if status:
            return _scope_unavailable("git_dirty")
        index = _scope_git(["ls-files", "--cached", "-v", "-z"], target)[1]
        entries = index.split(b"\0")
        if entries[-1] != b"" or any(not entry.startswith(b"H ") for entry in entries[:-1]):
            return _scope_unavailable("index_flags")
        common_raw = _scope_text(["rev-parse", "--git-common-dir"], target)
        common = _NATIVE_PATH(common_raw)
        common = (target / common).resolve(strict=True) if not common.is_absolute() else common.resolve(strict=True)
        repo_common_raw = _scope_text(["rev-parse", "--git-common-dir"], repo)
        repo_common = _NATIVE_PATH(repo_common_raw)
        repo_common = ((repo / repo_common).resolve(strict=True) if not repo_common.is_absolute()
                       else repo_common.resolve(strict=True))
        if common != repo_common:
            return _scope_unavailable("registration_unavailable")
    except (WorkerWriteGuardError, OSError, ValueError, IndexError):
        return _scope_unavailable("git_unavailable")
    # Bracket the multi-command observation. A branch or index change while
    # scanning must not be mistaken for one clean, coherent Git view.
    try:
        if _registered_tree(repo, root, tid) != target:
            return _scope_unavailable("git_changed")
    except (WorkerWriteGuardError, OSError, ValueError):
        return _scope_unavailable("registration_unavailable")
    try:
        _fresh_locks(repo, root, target)
    except (WorkerWriteGuardError, OSError, ValueError):
        return _scope_unavailable("lock_unavailable")
    try:
        final_filter_code, _ = _scope_git(
            ["config", "--get-regexp", r"^filter\..*\.(process|clean|smudge)$"],
            target, allowed=(0, 1))
        if final_filter_code != 1:
            return _scope_unavailable("git_changed")
        final_stage = _scope_stage(target)
        if any(entry.startswith(b"160000 ") for entry in final_stage.split(b"\0")[:-1]):
            return _scope_unavailable("submodule_scope_unsupported")
        final = (
            _scope_git(["status", "--porcelain=v1", "-z",
                        "--untracked-files=all", "--ignore-submodules=none"], target)[1],
            _scope_git(["ls-files", "--cached", "-v", "-z"], target)[1],
            _scope_text(["symbolic-ref", "--quiet", "HEAD"], target),
            _scope_text(["rev-parse", "--verify", "HEAD^{commit}"], target),
            _scope_text(["rev-parse", "--verify", "HEAD^{tree}"], target),
            _scope_git(["config", "--local", "--get-all", key], target,
                       allowed=(0, 1)),
            _scope_text(["remote", "get-url", "origin"], repo),
            _scope_text(["remote", "get-url", "origin"], target),
        )
        if (final_stage != stage or final[:5] != (status, index, branch, head, tree)
                or final[5] != (code, raw_pin)
                or worker_git._canonical_bach_origin(final[6]) != origin
                or worker_git._canonical_bach_origin(final[7]) != origin):
            return _scope_unavailable("git_changed")
    except (WorkerWriteGuardError, RuntimeError, OSError, ValueError):
        return _scope_unavailable("git_unavailable")
    snapshot = {
        "schema": _SCOPE_SCHEMA, "availability": "available", "task_id": tid,
        "repository": "ellmos-ai/bach", "origin": origin, "branch": branch,
        "head_oid": head, "tree_oid": tree,
        "repo_path_sha256": hashlib.sha256(str(repo).encode("utf-8")).hexdigest(),
        "worktree_path_sha256": hashlib.sha256(str(target).encode("utf-8")).hexdigest(),
        "common_dir_sha256": hashlib.sha256(str(common).encode("utf-8")).hexdigest(),
        "source_pin": source_pin, "clean_scope": _SCOPE_CLEAN,
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "index_sha256": hashlib.sha256(index).hexdigest(),
    }
    snapshot["project_state_ref"] = _scope_hash({
        "repository": snapshot["repository"], "origin": origin,
        "source_pin": source_pin, "head_oid": head})
    snapshot["workspace_fingerprint"] = _scope_hash({
        "worktree_path_sha256": snapshot["worktree_path_sha256"],
        "common_dir_sha256": snapshot["common_dir_sha256"], "branch": branch,
        "tree_oid": tree, "clean_scope": _SCOPE_CLEAN,
        "status_sha256": snapshot["status_sha256"],
        "index_sha256": snapshot["index_sha256"]})
    return snapshot


_TASK_START_SCOPE_SCHEMA = "bach.task-start-scope.v1"


def _task_start_scope_unavailable(reason: str) -> dict:
    return {"schema": _TASK_START_SCOPE_SCHEMA, "availability": "unavailable",
            "reason": reason}


def snapshot_task_start_scope(binding, *, task_root=None, source_pin_required=False,
                              repo_root=None, worktrees_dir=None) -> dict:
    """Authorize the registered task tree for a new worker run, including WIP.

    This deliberately does not require a clean worktree and is never evidence
    for a completed result. Final result capture continues to use
    snapshot_task_scope(), which rejects dirty trees.
    """
    from hub._services.task_lease_client import LeaseError

    if type(source_pin_required) is not bool:
        return _task_start_scope_unavailable("invalid_source_capability")
    try:
        tid = _task_id(getattr(binding, "task_id", None))
        repo, root = _paths(repo_root, worktrees_dir)
        target = authorize_start(binding, tid, repo_root=repo, worktrees_dir=root)
        if task_root is not None and _NATIVE_PATH(task_root).resolve(strict=True) != target:
            return _task_start_scope_unavailable("registration_unavailable")

        from hub import worker_git
        origin = worker_git._canonical_bach_origin(
            _scope_text(["remote", "get-url", "origin"], repo))
        target_origin = worker_git._canonical_bach_origin(
            _scope_text(["remote", "get-url", "origin"], target))
        if origin != "https://github.com/ellmos-ai/bach" or target_origin != origin:
            return _task_start_scope_unavailable("origin_unavailable")

        branch = _scope_text(["symbolic-ref", "--quiet", "HEAD"], target)
        head = _scope_text(["rev-parse", "--verify", "HEAD^{commit}"], target)
        if (branch != f"refs/heads/bach-task/{tid}"
                or not _GIT_OID.fullmatch(head)):
            return _task_start_scope_unavailable("registration_unavailable")

        filter_code, _ = _scope_git(
            ["config", "--get-regexp", r"^filter\..*\.(process|clean|smudge)$"],
            target, allowed=(0, 1))
        if filter_code == 0:
            return _task_start_scope_unavailable("git_unavailable")
        stage = _scope_stage(target)
        if any(entry.startswith(b"160000 ") for entry in stage.split(b"\0")[:-1]):
            return _task_start_scope_unavailable("submodule_scope_unsupported")

        key = worker_git._public_source_config_key(tid)
        pin_state = _scope_git(
            ["config", "--local", "--get-all", key], target, allowed=(0, 1))
        if pin_state[0] == 0:
            # A valid prior code-source pin remains valid for a later read-only
            # run. Its presence grants no write capability to that run.
            values = pin_state[1].decode("utf-8", "strict").splitlines()
            if len(values) != 1:
                return _task_start_scope_unavailable("source_pin_invalid")
            proof = json.loads(values[0])
            validated = worker_git.read_task_public_source_registration(repo, target, tid)
            if proof != validated:
                return _task_start_scope_unavailable("git_changed")
            source_pin = {name: validated[name] for name in
                          ("schema", "source_ref", "source_sha", "verified_at")}
        else:
            if source_pin_required:
                return _task_start_scope_unavailable("source_pin_invalid")
            source_pin = None

        common_raw = _scope_text(["rev-parse", "--git-common-dir"], target)
        common = _NATIVE_PATH(common_raw)
        common = (target / common).resolve(strict=True) if not common.is_absolute() else common.resolve(strict=True)
        repo_common_raw = _scope_text(["rev-parse", "--git-common-dir"], repo)
        repo_common = _NATIVE_PATH(repo_common_raw)
        repo_common = ((repo / repo_common).resolve(strict=True) if not repo_common.is_absolute()
                       else repo_common.resolve(strict=True))
        if common != repo_common:
            return _task_start_scope_unavailable("registration_unavailable")

        final_filter_code, _ = _scope_git(
            ["config", "--get-regexp", r"^filter\..*\.(process|clean|smudge)$"],
            target, allowed=(0, 1))
        final_pin_state = _scope_git(
            ["config", "--local", "--get-all", key], target, allowed=(0, 1))
        final_stage = _scope_stage(target)
        final_branch = _scope_text(["symbolic-ref", "--quiet", "HEAD"], target)
        final_head = _scope_text(["rev-parse", "--verify", "HEAD^{commit}"], target)
        final_origin = worker_git._canonical_bach_origin(
            _scope_text(["remote", "get-url", "origin"], target))
        if (final_filter_code != 1 or final_pin_state != pin_state
                or final_stage != stage or final_branch != branch
                or final_head != head or final_origin != origin
                or _registered_tree(repo, root, tid) != target
                or authorize_start(binding, tid, repo_root=repo, worktrees_dir=root) != target):
            return _task_start_scope_unavailable("git_changed")
    except LeaseError:
        return _task_start_scope_unavailable("lease_unavailable")
    except (WorkerWriteGuardError, RuntimeError, OSError, UnicodeError, KeyError, ValueError):
        return _task_start_scope_unavailable("registration_unavailable")

    return {
        "schema": _TASK_START_SCOPE_SCHEMA,
        "availability": "available",
        "task_id": tid,
        "branch": branch,
        "head_oid": head,
        "source_pin": source_pin,
    }




@dataclass(frozen=True)
class TaskReadScope:
    """One lease-bound view of public-base files and task-created artifacts."""
    root: Path
    requested: Path
    files: tuple[Path, ...]
    directories: frozenset[Path]
    provenance: dict[str, str]
    sizes: dict[Path, int]
    requested_is_file: bool


def _run_git_bytes(argv, cwd, *, input_bytes=None, allowed=(0,), timeout=15) -> bytes:
    kwargs = {
        "cwd": str(cwd), "shell": False, "capture_output": True,
        "stdin": subprocess.DEVNULL, "timeout": timeout, "check": False,
    }
    if input_bytes is not None:
        kwargs.pop("stdin")
        kwargs["input"] = input_bytes
    try:
        result = _RUN(argv, **kwargs)
    except Exception:  # noqa: BLE001 - Git-/Prozessfehler sperren den gesamten Lesescope.
        raise WorkerWriteGuardError("Task-Leseumfang konnte nicht vollständig geprüft werden") from None
    if result.returncode not in allowed:
        raise WorkerWriteGuardError("Task-Leseumfang konnte nicht vollständig geprüft werden")
    output = result.stdout or b""
    return output.encode("utf-8", errors="surrogateescape") if isinstance(output, str) else bytes(output)


def _task_relative_path(root: Path, candidate) -> Path:
    if not isinstance(candidate, (str, os.PathLike)) or not str(candidate) or "\x00" in str(candidate):
        raise WorkerWriteGuardError("Task-Lesepfad fehlt oder ist ungültig")
    raw = _NATIVE_PATH(candidate).expanduser()
    lexical = _NATIVE_PATH(os.path.abspath(raw if raw.is_absolute() else root / raw))
    try:
        relative = lexical.relative_to(root)
    except ValueError:
        raise WorkerWriteGuardError("Task-Lesepfad liegt außerhalb des gebundenen Arbeitsbaums") from None
    cursor = root
    try:
        if stat.S_ISLNK(cursor.lstat().st_mode) or cursor.resolve(strict=True) != root:
            raise WorkerWriteGuardError("Task-Arbeitsbaum ist nicht physisch gebunden")
        for part in relative.parts:
            cursor = cursor / part
            mode = cursor.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise WorkerWriteGuardError("Symlinks sind im Task-Lesebereich gesperrt")
    except FileNotFoundError:
        raise WorkerWriteGuardError("Task-Lesepfad ist nicht vorhanden") from None
    except OSError:
        raise WorkerWriteGuardError("Task-Lesepfad konnte nicht sicher geprüft werden") from None
    resolved = cursor.resolve(strict=True)
    if resolved != cursor:
        raise WorkerWriteGuardError("Task-Lesepfad wird umgeleitet")
    return cursor


def review_source_root(binding, *, repo_root=None, worktrees_dir=None) -> Path:
    """Resolve only a private review grant's current registered parent tree.

    The child keeps its own lease. Reading the parent grants no parent lease,
    write authority, alternate worktree or exemption from the public source pin.
    """
    from hub._services.worker_result_review import _grant_valid

    tid = _task_id(getattr(binding, "task_id", None))
    _fresh_lease(binding, tid)
    grant = getattr(binding, "_review_grant", None)
    if not _grant_valid(grant) or grant.task_id != tid:
        raise WorkerWriteGuardError("Private aktuelle Reviewberechtigung fehlt")
    client = getattr(binding, "_client", None)
    check = getattr(client, "_guard_review_dispatch", None)
    if not callable(check) or check(
        binding, route=grant.route, requested_model=grant.requested_model,
    ) is not True:
        raise WorkerWriteGuardError("Review-Ziel, Ergebnisrevision oder Berechtigung ist nicht aktuell")
    observed = client.task_result_snapshot(grant.target_task_id)
    result = observed.get("result") if isinstance(observed, dict) else None
    if (not isinstance(result, dict) or observed.get("status") != "review"
            or result.get("result_id") != grant.target_result_id
            or result.get("result_revision") != grant.target_revision
            or result.get("scope", {}).get("availability") != "available"):
        raise WorkerWriteGuardError("Review-Leseziel passt nicht zur gebundenen Ergebnisrevision")
    repo, root = _paths(repo_root, worktrees_dir)
    return _registered_tree(repo, root, _task_id(grant.target_task_id))


def authorize_task_read(binding, candidate, *, secret_check, repo_root=None, worktrees_dir=None) -> TaskReadScope:
    """Authorize a tool-level read under the exact public-pinned Task worktree."""
    if not callable(secret_check):
        raise WorkerWriteGuardError("Vorhandene Secrets-Prüfung fehlt")
    tid = _task_id(getattr(binding, "task_id", None))
    _fresh_lease(binding, tid)
    repo, root = _paths(repo_root, worktrees_dir)
    grant = getattr(binding, "_review_grant", None)
    if grant is not None:
        target = review_source_root(binding, repo_root=repo, worktrees_dir=root)
        source_tid = _task_id(grant.target_task_id)
    else:
        target = _registered_tree(repo, root, tid)
        source_tid = tid
    from hub import worker_git
    registration = worker_git.read_task_public_source_registration(repo, target, source_tid)
    requested = _task_relative_path(target, candidate)
    if secret_check(requested):
        raise WorkerWriteGuardError("Task-Lesepfad ist als geheim eingestuft")

    names_raw = _run_git_bytes(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], target,
    )
    if len(names_raw) > 8_388_608:
        raise WorkerWriteGuardError("Task-Lesebestand überschreitet die sichere Grenze")
    names = [item for item in names_raw.split(b"\x00") if item]
    if len(names) > 25000:
        raise WorkerWriteGuardError("Task-Lesebestand überschreitet die sichere Grenze")
    if names:
        ignored_raw = _run_git_bytes(
            ["git", "check-ignore", "--no-index", "-z", "--stdin"], target,
            input_bytes=b"\x00".join(names) + b"\x00", allowed=(0, 1),
        )
        ignored = {item for item in ignored_raw.split(b"\x00") if item}
    else:
        ignored = set()

    base = registration["source_sha"]
    base_raw = _run_git_bytes(["git", "ls-tree", "-r", "-z", "--name-only", base], target)
    if len(base_raw) > 8_388_608:
        raise WorkerWriteGuardError("Gepinnte Quellbasis überschreitet die sichere Grenze")
    base_names = {item for item in base_raw.split(b"\x00") if item}
    changed_raw = _run_git_bytes(["git", "diff", "--name-only", "-z", base, "--"], target)
    changed = {item for item in changed_raw.split(b"\x00") if item}

    files: list[Path] = []
    directories: set[Path] = {target}
    provenance: dict[str, str] = {}
    sizes: dict[Path, int] = {}
    for raw_name in names:
        if raw_name in ignored:
            continue
        rel_text = os.fsdecode(raw_name)
        rel = _NATIVE_PATH(rel_text)
        if rel.is_absolute() or not rel.parts or any(part in {".", ".."} for part in rel.parts):
            raise WorkerWriteGuardError("Git meldet einen ungültigen Task-Pfad")
        path = target / rel
        cursor = target
        safe = True
        try:
            for part in rel.parts:
                cursor = cursor / part
                mode = cursor.lstat().st_mode
                if stat.S_ISLNK(mode):
                    safe = False
                    break
            if not safe:
                continue
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) or secret_check(path) or path.lstat().st_nlink != 1:
                continue
            if path.resolve(strict=True) != path:
                continue
        except FileNotFoundError:
            # A deleted tracked path is not readable and is not an incomplete scan.
            continue
        except OSError:
            raise WorkerWriteGuardError("Task-Dateibestand konnte nicht vollständig geprüft werden") from None
        files.append(path)
        sizes[path] = path.lstat().st_size
        for parent in path.parents:
            if parent == target or target in parent.parents:
                directories.add(parent)
            if parent == target:
                break
        provenance[rel.as_posix()] = (
            "public_base" if raw_name in base_names and raw_name not in changed else "task_artifact"
        )

    if requested.is_file():
        if requested not in files:
            raise WorkerWriteGuardError("Datei gehört nicht zum freigegebenen Task-Lesebestand")
        requested_is_file = True
    elif requested.is_dir():
        if requested not in directories:
            raise WorkerWriteGuardError("Verzeichnis gehört nicht zum freigegebenen Task-Lesebestand")
        requested_is_file = False
    else:
        raise WorkerWriteGuardError("Task-Lesepfad ist weder Datei noch freigegebenes Verzeichnis")
    _fresh_lease(binding, tid)
    if grant is not None and review_source_root(
        binding, repo_root=repo, worktrees_dir=root,
    ) != target:
        raise WorkerWriteGuardError("Review-Lesebereich hat sich während der Prüfung geändert")
    return TaskReadScope(
        root=target, requested=requested, files=tuple(sorted(files)),
        directories=frozenset(directories), provenance=provenance,
        sizes=sizes, requested_is_file=requested_is_file,
    )


@contextmanager
def open_authorized_task_file(scope: TaskReadScope, path: Path):
    """Open without following any path component; unsupported hosts fail closed."""
    if path not in scope.files:
        raise WorkerWriteGuardError("Datei gehört nicht zum freigegebenen Task-Lesebestand")
    if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY")) or os.open not in os.supports_dir_fd:
        raise WorkerWriteGuardError("Sicheres symlinkfreies Öffnen ist auf diesem Host nicht verfügbar")
    relative = path.relative_to(scope.root)
    flags_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags_file = os.O_RDONLY | os.O_NOFOLLOW
    descriptor = None
    current = None
    stream = None
    try:
        try:
            current = os.open(scope.root, flags_dir)
            for part in relative.parts[:-1]:
                next_fd = os.open(part, flags_dir, dir_fd=current)
                os.close(current)
                current = next_fd
            descriptor = os.open(relative.parts[-1], flags_file, dir_fd=current)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise WorkerWriteGuardError("Task-Datei ist kein sicherer regulärer Inhalt")
            stream = os.fdopen(descriptor, "rb")
            descriptor = None
        except WorkerWriteGuardError:
            raise
        except Exception:  # noqa: BLE001 - unsicherer Dateizugriff bleibt gesperrt.
            raise WorkerWriteGuardError("Task-Datei konnte nicht symlinkfrei geöffnet werden") from None
        yield stream
    finally:
        try:
            if stream is not None:
                stream.close()
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if current is not None:
                os.close(current)

def authorize_start(binding, task_id, *, repo_root=None, worktrees_dir=None) -> Path:
    tid = _task_id(task_id)
    _fresh_lease(binding, tid)
    repo, root = _paths(repo_root, worktrees_dir)
    target = root / f"task-{tid}"
    _fresh_locks(repo, root, target)
    if target.exists():
        _registered_tree(repo, root, tid)
    _fresh_lease(binding, tid)
    return target


def _safe_task_path(root: Path, candidate, *, allow_missing=True) -> Path:
    if not isinstance(candidate, (str, os.PathLike)) or not str(candidate):
        raise WorkerWriteGuardError("Dateipfad fehlt")
    raw = _NATIVE_PATH(candidate).expanduser()
    if not raw.is_absolute():
        raw = root / raw
    lexical = _NATIVE_PATH(os.path.abspath(raw))
    try:
        lexical.relative_to(root)
    except ValueError as exc:
        raise WorkerWriteGuardError("Schreibpfad liegt außerhalb des Task-Arbeitsbaums") from exc
    cursor = root
    for part in lexical.relative_to(root).parts:
        cursor = cursor / part
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            if not allow_missing:
                raise WorkerWriteGuardError("Dateipfad existiert nicht")
            continue
        if stat.S_ISLNK(mode):
            raise WorkerWriteGuardError("Symlinks sind in Worker-Schreibpfaden gesperrt")
    resolved = lexical.resolve(strict=False)
    if resolved != lexical:
        raise WorkerWriteGuardError("Schreibpfad wird durch einen Link umgeleitet")
    return lexical


def authorize_mutation(binding, task_id=None, *, paths: Iterable = (),
                       repo_root=None, worktrees_dir=None) -> tuple[Path, tuple[Path, ...]]:
    tid = _task_id(task_id if task_id is not None else binding.task_id)
    _fresh_lease(binding, tid)
    repo, root = _paths(repo_root, worktrees_dir)
    target = _registered_tree(repo, root, tid)
    checked = tuple(_safe_task_path(target, value) for value in paths)
    # Scan each source/target's nearest existing directory before parent mkdir.
    _fresh_locks(repo, root, target, checked)
    _fresh_lease(binding, tid)
    return target, checked




def _bound_check_path(task_root: Path, cwd: Path, raw, checked, *, allow_dash=False) -> str:
    value = str(raw)
    if not value or "\x00" in value:
        raise WorkerWriteGuardError("Prüfpfad fehlt oder ist ungültig")
    if allow_dash and value == "-":
        return value
    if any(part == ".." for part in value.replace("\\", "/").split("/")):
        raise WorkerWriteGuardError("Prüfpfad darf den Task-Arbeitsbaum nicht verlassen")
    windows_path = PureWindowsPath(value)
    if windows_path.drive and os.name != "nt":
        raise WorkerWriteGuardError("Windows-Pfad kann auf diesem Prüfsystem nicht sicher gebunden werden")
    candidate = _NATIVE_PATH(value)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    resolved = _safe_task_path(task_root, candidate)
    checked.append(resolved)
    return str(resolved)


def _bound_check_pattern(task_root: Path, cwd: Path, raw, checked) -> str:
    value = str(raw)
    if not value or "\x00" in value:
        raise WorkerWriteGuardError("Prüfmuster fehlt oder ist ungültig")
    if _NATIVE_PATH(value).is_absolute() or PureWindowsPath(value).drive:
        raise WorkerWriteGuardError("Prüfmuster darf keinen externen absoluten Pfad enthalten")
    if any(part == ".." for part in value.replace("\\", "/").split("/")):
        raise WorkerWriteGuardError("Prüfmuster darf den Task-Arbeitsbaum nicht verlassen")
    _bound_check_path(task_root, cwd, value, checked)
    return value


def _take_check_value(args, index, option):
    token = args[index]
    if token == option:
        if index + 1 >= len(args) or not args[index + 1]:
            raise WorkerWriteGuardError(f"Wert für {option} fehlt")
        return args[index + 1], index + 2, False
    if option.startswith("--") and token.startswith(option + "="):
        value = token[len(option) + 1:]
        if not value:
            raise WorkerWriteGuardError(f"Wert für {option} fehlt")
        return value, index + 1, True
    raise WorkerWriteGuardError(f"Ungültige Option {option}")


def _put_check_value(output, option, value, joined):
    output.append(f"{option}={value}" if joined else option)
    if not joined:
        output.append(value)


_PYTEST_FLAGS = frozenset({
    "-q", "--quiet", "-v", "--verbose", "-s", "-x", "--exitfirst", "-l", "--showlocals",
    "--full-trace", "--no-header", "--no-summary", "--disable-warnings", "--strict-markers",
    "--strict-config", "--continue-on-collection-errors", "--keep-duplicates", "--doctest-modules",
    "--collect-only", "--noconftest", "--trace-config", "--lf", "--last-failed", "--failed-first",
    "--new-first", "--stepwise", "--sw", "--sw-skip", "--cache-show", "--cache-clear",
    "--cov-branch", "--cov-append", "--no-cov", "--self-contained-html", "--json-report",
    "--help", "-h", "--version", "--fixtures", "--fixtures-per-test", "--funcargs",
})
_PYTEST_VALUES = frozenset({
    "-k", "-m", "-r", "-W", "-p", "-c", "--confcutdir", "--rootdir", "--basetemp",
    "--ignore", "--ignore-glob", "--deselect", "--import-mode", "--junitxml", "--junit-xml",
    "--log-file", "--log-file-level", "--log-file-format", "--log-file-date-format", "--html",
    "--alluredir", "--json-report-file", "--json-report-indent", "--json-report-verbosity",
    "--cov", "--cov-config", "--cov-report", "--cov-context", "--doctest-glob", "--maxfail",
    "--durations", "--tb", "--color", "--code-highlight", "--capture", "--show-capture",
    "--verbosity", "--assert", "--override-ini", "-o", "--last-failed-no-failures",
})
_PYTEST_OVERRIDE_KEYS = frozenset({
    "addopts", "cache_dir", "log_file", "log_file_level", "log_file_format", "log_file_date_format",
    "log_auto_indent", "junit_family", "junit_logging", "junit_log_passing_tests", "console_output_style",
    "python_files", "python_classes", "python_functions", "testpaths", "norecursedirs", "minversion",
    "markers", "filterwarnings", "usefixtures", "asyncio_mode", "asyncio_default_fixture_loop_scope",
    "asyncio_default_test_loop_scope", "timeout", "timeout_method", "timeout_func_only",
    "strict_markers", "strict_config", "consider_namespace_packages", "confcutdir",
})


def _pytest_override(task_root, cwd, value, checked):
    key, separator, setting = value.partition("=")
    if not separator or key not in _PYTEST_OVERRIDE_KEYS:
        raise WorkerWriteGuardError("Unbekannte oder unvollständige pytest-Konfigurationsüberschreibung")
    if key in {"addopts", "pytest_plugins"} and setting:
        raise WorkerWriteGuardError("pytest addopts/plugins können zusätzliche ungebundene Ziele starten")
    if key in {"cache_dir", "log_file", "confcutdir"}:
        setting = _bound_check_path(task_root, cwd, setting, checked)
    elif key == "testpaths":
        values = setting.split()
        if not values:
            raise WorkerWriteGuardError("pytest testpaths ist leer")
        setting = " ".join(_bound_check_path(task_root, cwd, item, checked) for item in values)
    elif key == "addopts":
        setting = ""
    return key + "=" + setting


def _prepare_pytest(task_root, cwd, args, checked, state_dir):
    output = []
    i = 0
    after_separator = False
    separator_index = None
    has_basetemp = False
    while i < len(args):
        token = args[i]
        if token == "--" and not after_separator:
            separator_index = len(output)
            output.append(token)
            after_separator = True
            i += 1
            continue
        if not after_separator and token in _PYTEST_VALUES:
            value, i, joined = _take_check_value(args, i, token)
            if token in {"-c", "--confcutdir", "--rootdir", "--basetemp", "--ignore", "--ignore-glob",
                         "--junitxml", "--junit-xml", "--log-file", "--html", "--alluredir",
                         "--json-report-file", "--cov-config"}:
                value = _bound_check_path(task_root, cwd, value, checked)
                has_basetemp = has_basetemp or token == "--basetemp"
            elif token == "--deselect":
                head, sep, tail = value.partition("::")
                head = _bound_check_path(task_root, cwd, head, checked)
                value = head + (sep + tail if sep else "")
            elif token == "--cov-report":
                kind, sep, destination = value.partition(":")
                if not kind:
                    raise WorkerWriteGuardError("pytest cov-report-Format fehlt")
                if sep:
                    destination = _bound_check_path(task_root, cwd, destination, checked, allow_dash=True)
                    value = kind + ":" + destination
            elif token == "--doctest-glob":
                value = _bound_check_pattern(task_root, cwd, value, checked)
            elif token == "-p" and not value.startswith("no:"):
                raise WorkerWriteGuardError("pytest darf keine zusätzlichen Plugins laden")
            elif token in {"-o", "--override-ini"}:
                value = _pytest_override(task_root, cwd, value, checked)
            elif token in {"-k", "-m", "-r", "-W", "--import-mode", "--maxfail", "--durations",
                           "--tb", "--color", "--code-highlight", "--capture", "--show-capture",
                           "--verbosity", "--assert", "--last-failed-no-failures", "--log-file-level",
                           "--log-file-format", "--log-file-date-format", "--cov", "--cov-context",
                           "--json-report-indent", "--json-report-verbosity"}:
                if token == "--import-mode" and value not in {"prepend", "append", "importlib"}:
                    raise WorkerWriteGuardError("pytest import-mode ist ungültig")
            _put_check_value(output, token, value, joined)
            continue
        if not after_separator and any(token.startswith(option + "=") for option in _PYTEST_VALUES if option.startswith("--")):
            option = next(option for option in _PYTEST_VALUES if option.startswith("--") and token.startswith(option + "="))
            value, i, joined = _take_check_value(args, i, option)
            if option in {"--confcutdir", "--rootdir", "--basetemp", "--ignore", "--ignore-glob", "--junitxml",
                          "--junit-xml", "--log-file", "--html", "--alluredir", "--json-report-file", "--cov-config"}:
                value = _bound_check_path(task_root, cwd, value, checked)
                has_basetemp = has_basetemp or option == "--basetemp"
            elif option == "--deselect":
                head, sep, tail = value.partition("::")
                value = _bound_check_path(task_root, cwd, head, checked) + (sep + tail if sep else "")
            elif option == "--cov-report":
                kind, sep, destination = value.partition(":")
                if sep:
                    destination = _bound_check_path(task_root, cwd, destination, checked, allow_dash=True)
                    value = kind + ":" + destination
            elif option == "--doctest-glob":
                value = _bound_check_pattern(task_root, cwd, value, checked)
            elif option == "--override-ini":
                value = _pytest_override(task_root, cwd, value, checked)
            elif option == "--import-mode" and value not in {"prepend", "append", "importlib"}:
                raise WorkerWriteGuardError("pytest import-mode ist ungültig")
            _put_check_value(output, option, value, joined)
            continue
        if not after_separator and token in _PYTEST_FLAGS:
            output.append(token)
            i += 1
            continue
        if not after_separator and token.startswith("-"):
            raise WorkerWriteGuardError("Unbekannte pytest-Option ist nicht sicher gebunden")
        if token.startswith("--pyargs"):
            raise WorkerWriteGuardError("pytest --pyargs kann Module außerhalb des Task-Baums laden")
        head, sep, tail = token.partition("::")
        head = _bound_check_path(task_root, cwd, head, checked)
        output.append(head + (sep + tail if sep else ""))
        i += 1
    if not has_basetemp:
        basetemp = str(state_dir / "pytest-temp")
        if separator_index is None:
            output.extend(["--basetemp", basetemp])
        else:
            output[separator_index:separator_index] = ["--basetemp", basetemp]
            separator_index += 2
        checked.append(state_dir / "pytest-temp")
    forced = ["-o", "cache_dir=" + str(state_dir / "pytest-cache"), "-o", "addopts=", "-o", "log_file=",
              "-o", "testpaths=" + str(task_root), "-o", "confcutdir=" + str(task_root)]
    if separator_index is None:
        output.extend(forced)
    else:
        output[separator_index:separator_index] = forced
    checked.extend([state_dir / "pytest-cache"])
    checked.append(task_root)
    return output


def _prepare_compileall(task_root, cwd, args, checked):
    output = []
    i = 0
    valued = {"-d", "-s", "-p", "-j", "-o", "--invalidation-mode"}
    flags = {"-q", "-f", "-b", "-l", "--help", "-h"}
    while i < len(args):
        token = args[i]
        if token in valued:
            value, i, joined = _take_check_value(args, i, token)
            if token in {"-s", "-p"}:
                value = _bound_check_path(task_root, cwd, value, checked)
            if token == "-j" and value != "0" and not value.isdecimal():
                raise WorkerWriteGuardError("compileall -j verlangt eine Workerzahl")
            if token == "-o" and value not in {"0", "1", "2"}:
                raise WorkerWriteGuardError("compileall -o verlangt 0, 1 oder 2")
            if token == "--invalidation-mode" and value not in {"timestamp", "checked-hash", "unchecked-hash"}:
                raise WorkerWriteGuardError("compileall Invalidation-Mode ist ungültig")
            _put_check_value(output, token, value, joined)
            continue
        if not token.startswith("-"):
            output.append(_bound_check_path(task_root, cwd, token, checked))
            i += 1
            continue
        if token in flags:
            output.append(token)
            i += 1
            continue
        raise WorkerWriteGuardError("Unbekannte compileall-Option könnte fremde Ziele beeinflussen")
    return output


def _prepare_unittest(task_root, cwd, args, checked):
    output = []
    i = 0
    value_options = {"-s", "--start-directory", "-t", "--top-level-directory", "-p", "--pattern", "-k", "--keyword"}
    flags = {"-v", "--verbose", "-q", "--quiet", "--locals", "--buffer", "--failfast", "--catch", "--help", "-h"}
    while i < len(args):
        token = args[i]
        if token == "discover":
            output.append(token)
            i += 1
            continue
        if token in value_options:
            value, i, joined = _take_check_value(args, i, token)
            if token in {"-s", "--start-directory", "-t", "--top-level-directory"}:
                value = _bound_check_path(task_root, cwd, value, checked)
            elif token in {"-p", "--pattern"} and ("/" in value or "\\" in value or ".." in value):
                raise WorkerWriteGuardError("unittest-Dateimuster muss ein Name ohne Pfadanteile sein")
            _put_check_value(output, token, value, joined)
            continue
        if token in flags:
            output.append(token)
            i += 1
            continue
        if token.startswith("-"):
            raise WorkerWriteGuardError("Unbekannte unittest-Option ist nicht sicher gebunden")
        module_path = token.replace(".", "/") + ".py"
        bound = _bound_check_path(task_root, cwd, module_path, checked)
        if not _NATIVE_PATH(bound).is_file():
            raise WorkerWriteGuardError("unittest-Modul ist im Task-Arbeitsbaum nicht vorhanden")
        output.append(token)
        i += 1
    return output


def _prepare_ruff(task_root, cwd, args, checked, state_dir):
    if not args or args[0] not in {"check", "format"}:
        raise WorkerWriteGuardError("Ruff ist nur mit check oder format zugelassen")
    output = [args[0]]
    i = 1
    path_options = {"--output-file", "--stdin-filename", "--cache-dir"}
    value_options = {
        "--config", "--select", "--extend-select", "--ignore", "--extend-ignore", "--fixable",
        "--unfixable", "--extend-fixable", "--extend-unfixable", "--line-length", "--target-version",
        "--output-format", "--exclude", "--extend-exclude", "--per-file-ignores",
        "--extend-per-file-ignores", "--extension", "--range",
    }
    flags = {
        "--fix", "--fix-only", "--unsafe-fixes", "--diff", "--show-fixes", "--show-source",
        "--no-show-source", "--exit-zero", "--quiet", "--verbose", "--silent", "--preview",
        "--no-preview", "--respect-gitignore", "--no-respect-gitignore", "--force-exclude",
        "--no-force-exclude", "--check", "--no-cache", "--show-files", "--show-settings", "--add-noqa",
    }
    while i < len(args):
        token = args[i]
        option = next((item for item in (path_options | value_options) if token == item or (item.startswith("--") and token.startswith(item + "="))), None)
        if option:
            value, i, joined = _take_check_value(args, i, option)
            if option in path_options:
                value = _bound_check_path(task_root, cwd, value, checked, allow_dash=option == "--output-file")
            elif option == "--config":
                if "=" in value and not _NATIVE_PATH(value).is_file():
                    key, _, setting = value.partition("=")
                    if key == "cache-dir":
                        setting = _bound_check_path(task_root, cwd, setting, checked)
                        value = key + "=" + setting
                    elif _NATIVE_PATH(setting).is_absolute() or PureWindowsPath(setting).drive or ".." in setting.replace("\\", "/").split("/"):
                        raise WorkerWriteGuardError("Ruff-Konfiguration enthält ein externes Pfadziel")
                else:
                    value = _bound_check_path(task_root, cwd, value, checked)
            elif option in {"--exclude", "--extend-exclude"}:
                value = _bound_check_pattern(task_root, cwd, value, checked)
            elif option in {"--per-file-ignores", "--extend-per-file-ignores"}:
                prefix, sep, suffix = value.partition(":")
                if not sep:
                    raise WorkerWriteGuardError("Ruff per-file-ignores benötigt ein Dateimuster")
                value = _bound_check_pattern(task_root, cwd, prefix, checked) + sep + suffix
            _put_check_value(output, option, value, joined)
            continue
        if token in flags:
            output.append(token)
            i += 1
            continue
        if token.startswith("-"):
            raise WorkerWriteGuardError("Unbekannte Ruff-Option könnte ungebundene Ausgabeziele setzen")
        output.append(_bound_check_path(task_root, cwd, token, checked))
        i += 1
    output.extend(["--cache-dir", str(state_dir / "ruff-cache")])
    checked.append(state_dir / "ruff-cache")
    return output


def _prepare_typechecker(task_root, cwd, base, args, checked):
    output = []
    i = 0
    path_values = {
        "--config-file", "--cache-dir", "--python-executable", "--html-report", "--txt-report",
        "--xml-report", "--xslt-html-report", "--linecount-report", "--any-exprs-report",
        "--cobertura-xml-report", "--junit-xml", "--project", "--pythonpath", "--venvpath", "--typeshedpath",
    }
    value_options = {
        "--python-version", "--platform", "--follow-imports", "--exclude", "--enable-error-code",
        "--disable-error-code", "--level", "--pythonplatform", "--pythonversion",
        "--executionenvironment",
    }
    flags = {
        "--strict", "--ignore-missing-imports", "--no-incremental", "--no-site-packages", "--namespace-packages",
        "--explicit-package-bases", "--show-error-codes", "--hide-error-codes", "--no-error-summary", "--pretty",
        "--no-pretty", "--show-traceback", "--warn-unused-ignores", "--no-warn-unused-ignores", "--check-untyped-defs",
        "--disallow-any-generics", "--disallow-untyped-defs", "--disallow-incomplete-defs", "--warn-return-any",
        "--warn-redundant-casts", "--warn-unused-configs", "--stats", "--verbose", "--outputjson", "--skipunannotated",
        "--ignoreexternal", "--help", "-h", "--version",
    }
    while i < len(args):
        token = args[i]
        if token == "--verifytypes" and base == "pyright":
            value, i, joined = _take_check_value(args, i, token)
            package_path = _bound_check_path(task_root, cwd, value.replace(".", "/"), checked)
            if not _NATIVE_PATH(package_path).exists():
                raise WorkerWriteGuardError("pyright verifytypes-Paket ist im Task-Arbeitsbaum nicht vorhanden")
            _put_check_value(output, token, value, joined)
            continue
        option = next((item for item in path_values | value_options if token == item or (item.startswith("--") and token.startswith(item + "="))), None)
        if option:
            value, i, joined = _take_check_value(args, i, option)
            if option in path_values:
                value = _bound_check_path(task_root, cwd, value, checked)
            _put_check_value(output, option, value, joined)
            continue
        if token in flags:
            output.append(token)
            i += 1
            continue
        if token in {"-m", "-p"} and base == "mypy":
            value, i, joined = _take_check_value(args, i, token)
            module_path = _bound_check_path(task_root, cwd, value.replace(".", "/") + "/__init__.py", checked)
            if not _NATIVE_PATH(module_path).is_file():
                raise WorkerWriteGuardError("Mypy-Modul ist im Task-Arbeitsbaum nicht vorhanden")
            _put_check_value(output, token, value, joined)
            continue
        if token.startswith("-"):
            raise WorkerWriteGuardError("Unbekannte Typechecker-Option ist nicht sicher gebunden")
        output.append(_bound_check_path(task_root, cwd, token, checked))
        i += 1
    return output


def _worker_check_environment(task_root):
    state = task_root / ".cache" / ".worker-check"
    paths = {
        "HOME": state / "home",
        "TMPDIR": state / "tmp",
        "TMP": state / "tmp",
        "TEMP": state / "tmp",
        "XDG_CACHE_HOME": state / "xdg-cache",
        "XDG_CONFIG_HOME": state / "xdg-config",
        "XDG_STATE_HOME": state / "xdg-state",
        "PYTHONPYCACHEPREFIX": state / "python-pycache",
        "RUFF_CACHE_DIR": state / "ruff-cache",
        "MYPY_CACHE_DIR": state / "mypy-cache",
        "PYRIGHT_PYTHON_CACHE_DIR": state / "pyright-cache",
        "npm_config_cache": state / "npm-cache",
        "PIP_CACHE_DIR": state / "pip-cache",
        "UV_CACHE_DIR": state / "uv-cache",
        "PRE_COMMIT_HOME": state / "pre-commit-cache",
        "COVERAGE_FILE": state / ".coverage",
        "PYTEST_DEBUG_TEMPROOT": state / "pytest-debug-temp",
        "BACH_DB": state / "worker-check.sqlite3",
        "NPM_CONFIG_USERCONFIG": state / "npmrc",
        "NPM_CONFIG_GLOBALCONFIG": state / "npm-globalrc",
        "LOCALAPPDATA": state / "local-app-data",
        "APPDATA": state / "app-data",
    }
    env = os.environ.copy()
    checked = []
    for key, path in paths.items():
        env[key] = str(path)
        checked.append(path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_ADDOPTS"] = ""
    env["PYTEST_PLUGINS"] = ""
    env["BACH_ALLOW_ONEDRIVE_DB_FALLBACK"] = "0"
    if os.name == "nt":
        env["USERPROFILE"] = str(paths["HOME"])
    return env, checked, state


_WORKER_CHECK_DIRECTORY_KEYS = (
    "HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
    "XDG_STATE_HOME", "PYTHONPYCACHEPREFIX", "RUFF_CACHE_DIR", "MYPY_CACHE_DIR",
    "PYRIGHT_PYTHON_CACHE_DIR", "npm_config_cache", "PIP_CACHE_DIR",
    "UV_CACHE_DIR", "PRE_COMMIT_HOME", "PYTEST_DEBUG_TEMPROOT",
    "LOCALAPPDATA", "APPDATA", "USERPROFILE",
)



def _create_task_directory_windows(task_root: Path, candidate: Path) -> None:
    """Walk and create through held directory handles, rejecting reparse points.

    NtCreateFile's RootDirectory resolves a single child relative to its
    actual parent handle. FILE_OPEN_REPARSE_POINT prevents following a child
    junction, and omitting FILE_SHARE_DELETE holds every ancestor in place.
    Existing ancestors are opened, never created outside the authorized root.
    """
    import ctypes
    from ctypes import wintypes

    root = _NATIVE_PATH(os.path.abspath(task_root))
    target = _NATIVE_PATH(os.path.abspath(candidate))
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise WorkerWriteGuardError("Prüfverzeichnis liegt außerhalb des Task-Arbeitsbaums") from None
    anchor = _NATIVE_PATH(root.anchor)
    if not root.is_absolute() or not root.anchor:
        raise WorkerWriteGuardError("Windows-Prüfverzeichnis hat keine sichere Wurzel")

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", wintypes.LPWSTR)]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(UnicodeString)), ("Attributes", wintypes.ULONG),
                    ("SecurityDescriptor", wintypes.LPVOID), ("SecurityQualityOfService", wintypes.LPVOID)]

    class StatusValue(ctypes.Union):
        _fields_ = [("Status", wintypes.LONG), ("Pointer", wintypes.LPVOID)]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", StatusValue), ("Information", ctypes.c_size_t)]

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    handles = []
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        native = ctypes.WinDLL("ntdll")
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                       wintypes.LPVOID, wintypes.DWORD]
        kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
        native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                       ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatusBlock),
                                       wintypes.LPVOID, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
                                       wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG]
        native.NtCreateFile.restype = wintypes.LONG

        def checked_handle(handle):
            handles.append(handle)
            state = AttributeTagInfo()
            if (not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(state), ctypes.sizeof(state))
                    or not state.FileAttributes & 0x10 or state.FileAttributes & 0x400):
                raise WorkerWriteGuardError("Windows-Prüfverzeichnis ist kein reparsefreier Ordner")
            return handle

        # OPEN_EXISTING; BACKUP_SEMANTICS | OPEN_REPARSE_POINT. Read/write
        # sharing is permitted, delete/rename sharing deliberately is not.
        handle = kernel.CreateFileW(str(anchor), 0x00100081, 0x3, None, 3, 0x02200000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise WorkerWriteGuardError("Windows-Verzeichniswurzel konnte nicht sicher geöffnet werden")
        handle = checked_handle(handle)
        existing = root.relative_to(anchor).parts
        parts = (*existing, *relative.parts)
        for index, part in enumerate(parts):
            if (part in {"", ".", ".."} or any(char in part for char in "\\/:\x00")
                    or part.rstrip(" .") != part):
                raise WorkerWriteGuardError("Windows-Prüfverzeichniskomponente ist ungültig")
            encoded_length = len(part.encode("utf-16-le"))
            if encoded_length > 65532:
                raise WorkerWriteGuardError("Windows-Prüfverzeichniskomponente ist zu lang")
            buffer = ctypes.create_unicode_buffer(part, encoded_length // 2 + 1)
            value = UnicodeString(encoded_length, encoded_length + 2,
                                  ctypes.cast(buffer, wintypes.LPWSTR))
            attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), handle,
                                          ctypes.pointer(value), 0x40, None, None)
            child = wintypes.HANDLE()
            status = IoStatusBlock()
            # FILE_OPEN for the already-authorized root chain. FILE_OPEN_IF
            # only for descendants of that root; DIRECTORY | SYNCHRONOUS_IO
            # | OPEN_REPARSE_POINT ensures a directory handle without traversal.
            disposition = 1 if index < len(existing) else 3
            result = native.NtCreateFile(ctypes.byref(child), 0x00100081,
                                         ctypes.byref(attributes), ctypes.byref(status), None,
                                         0x10, 0x3, disposition, 0x00200021, None, 0)
            if result != 0 or not child.value:
                if child.value:
                    kernel.CloseHandle(child)
                raise WorkerWriteGuardError("Windows-Prüfverzeichnis konnte nicht relativ geöffnet werden")
            handle = checked_handle(child)
    except WorkerWriteGuardError:
        raise
    except Exception:
        raise WorkerWriteGuardError("Sicheres Windows-Verzeichnisverfahren ist nicht verfügbar") from None
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def _create_task_directory(task_root: Path, candidate: Path) -> None:
    """Create one authorized task directory without following symlinks."""
    root = _NATIVE_PATH(os.path.abspath(task_root))
    target = _safe_task_path(root, candidate)
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise WorkerWriteGuardError("Prüfverzeichnis liegt außerhalb des Task-Arbeitsbaums") from None
    if not relative.parts:
        return
    if os.name == "nt":
        _create_task_directory_windows(root, target)
        return

    if (os.name == "posix" and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and os.open in getattr(os, "supports_dir_fd", set())
            and os.mkdir in getattr(os, "supports_dir_fd", set())):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = None
        try:
            descriptor = os.open(root, flags)
            for part in relative.parts:
                if part in {"", ".", ".."}:
                    raise WorkerWriteGuardError("Prüfverzeichnis ist ungültig")
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
        except WorkerWriteGuardError:
            raise
        except Exception:
            raise WorkerWriteGuardError("Prüfverzeichnis konnte nicht symlinkfrei angelegt werden") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return

    raise WorkerWriteGuardError("Symlinkfreies Anlegen von Prüfverzeichnissen ist nicht verfügbar")


def _create_worker_check_directories(task_root: Path, state_dir: Path, env: dict,
                                     checked: Iterable[Path]) -> None:
    """Materialize task-local environment directories after lease authorization."""
    checked_paths = {_NATIVE_PATH(path) for path in checked}
    directories = [state_dir]
    for key in _WORKER_CHECK_DIRECTORY_KEYS:
        value = env.get(key)
        if isinstance(value, str) and value:
            candidate = _NATIVE_PATH(value)
            if candidate in checked_paths:
                directories.append(candidate)
    for name in ("pytest-temp", "pytest-cache"):
        candidate = state_dir / name
        if candidate in checked_paths:
            directories.append(candidate)
    seen = set()
    for candidate in directories:
        if candidate in seen:
            continue
        seen.add(candidate)
        _create_task_directory(task_root, candidate)


def _prepare_bound_check_args(task_root, cwd, base, args, checked, state_dir):
    if base in {"python", "python3"}:
        if len(args) < 2 or args[0] != "-m" or args[1] not in _PYTHON_MODULES:
            raise WorkerWriteGuardError("Python ist nur für freigegebene Prüfmodule erlaubt")
        module = args[1]
        rest = args[2:]
        if module == "pytest":
            return ["-m", module, *_prepare_pytest(task_root, cwd, rest, checked, state_dir)]
        if module == "compileall":
            return ["-m", module, *_prepare_compileall(task_root, cwd, rest, checked)]
        if module == "unittest":
            return ["-m", module, *_prepare_unittest(task_root, cwd, rest, checked)]
        if module == "ruff":
            return ["-m", module, *_prepare_ruff(task_root, cwd, rest, checked, state_dir)]
        raise WorkerWriteGuardError("Python-Prüfmodul ist nicht sicher gebunden")
    if base == "ruff":
        return _prepare_ruff(task_root, cwd, args, checked, state_dir)
    if base in {"mypy", "pyright"}:
        return _prepare_typechecker(task_root, cwd, base, args, checked)
    if base == "npm" and args not in (["test"], ["run", "test"]):
        raise WorkerWriteGuardError("npm ist nur für den Testskript-Aufruf freigegeben")
    return list(args)


def run_bound_check(binding, command: str, cwd, timeout=60, *, safe=False, return_result=False) -> str | SandboxResult:
    if not isinstance(command, str) or not command.strip():
        raise WorkerWriteGuardError("Befehl fehlt")
    target, checked = authorize_mutation(binding, paths=(cwd,))
    checked = list(checked)
    run_cwd = checked[0]
    if not run_cwd.is_dir():
        raise WorkerWriteGuardError("Arbeitsverzeichnis liegt nicht im Task-Arbeitsbaum")
    from hub import safe_exec
    try:
        tokens = [safe_exec.dequote(token) for token in safe_exec.tokenize(command)]
        if not tokens:
            raise WorkerWriteGuardError("Befehl fehlt")
        base = _NATIVE_PATH(tokens[0]).name.lower().removesuffix(".exe")
        allowed = (frozenset({"ls", "cat", "head", "tail", "find", "wc", "file", "stat",
                              "echo", "date", "which", "whoami", "hostname", "uname", "df",
                              "du", "uptime", "ps", "top", "sw_vers", "sysctl", "git"})
                   if safe else _CHECK_BASES)
        argv = safe_exec.resolve_executable(command, allowed)
    except Exception as exc:
        raise WorkerWriteGuardError("Befehl ist nicht für den Task-Worker zugelassen") from exc
    args = tokens[1:]
    env = None
    state_dir = target / ".cache" / ".worker-check"
    if base == "git":
        if not args or args[0] not in _GIT_READ_SUBCOMMANDS:
            raise WorkerWriteGuardError("Git-Schreibbefehle sind nur über den Task-Workflow erlaubt")
        if args[0] == "worktree" and (len(args) < 2 or args[1] != "list"):
            raise WorkerWriteGuardError("Git-Worktree-Schreibbefehle sind gesperrt")
        if any(a == "--output" or a.startswith("--output=") or
               a in {"--ext-diff", "--textconv", "--exec", "--config-env"} or
               a == "-c" or a.startswith("--config=") for a in args[1:]):
            raise WorkerWriteGuardError("Git-Ausgabe-/Hook-Optionen sind gesperrt")
    elif safe:
        if base == "ollama":
            raise WorkerWriteGuardError("Ollama-Aufrufe sind für gebundene Worker nicht verfügbar")
    else:
        if base in {"python", "python3", "ruff", "mypy", "pyright", "npm"}:
            env, env_paths, state_dir = _worker_check_environment(target)
            prepared = _prepare_bound_check_args(target, run_cwd, base, args, checked, state_dir)
            argv = [argv[0], *prepared]
            checked.extend(env_paths)
            checked.append(state_dir)
        else:
            raise WorkerWriteGuardError("Prüfbefehl ist nicht sicher gebunden")
    timeout = min(max(int(timeout), 1), 120)
    authorize_mutation(binding, paths=(run_cwd, *checked))
    from core import sandbox
    if os.name == "nt" and not sandbox.HAS_PSUTIL:
        raise WorkerWriteGuardError("Prozessbaum kann auf Windows ohne psutil nicht sicher beendet werden")
    if env is not None:
        _create_worker_check_directories(target, state_dir, env, checked)
        # Recheck the lease, symlink-free paths, and all enclosing locks after
        # materialization and immediately before launching the child process.
        authorize_mutation(binding, paths=(run_cwd, *checked))
    try:
        result = sandbox.run_isolated(
            argv, limits=sandbox.SandboxLimits(timeout_sec=timeout, memory_mb=None),
            cwd=str(run_cwd), shell=False, env=env,
        )
    except Exception as exc:
        raise WorkerWriteGuardError("Prüfbefehl konnte nicht sicher gestartet werden") from exc
    if return_result:
        if not isinstance(result, sandbox.SandboxResult):
            raise WorkerWriteGuardError("Prüfergebnis ist unbekannt oder nicht typisiert")
        return result
    output = result.stdout or ""
    if result.stderr:
        output += "\n[stderr] " + result.stderr
    if result.timed_out:
        status = f"Prüfung fehlgeschlagen; Timeout nach {timeout}s; Exitcode {result.returncode}"
    elif result.memory_exceeded:
        status = f"Prüfung fehlgeschlagen; Speichergrenze; Exitcode {result.returncode}"
    elif result.returncode == 0:
        status = f"Prüfung erfolgreich; Exitcode {result.returncode}"
    else:
        status = f"Prüfung fehlgeschlagen; Exitcode {result.returncode}"
    return (status + "\n" + (output or "(keine Ausgabe)"))[:4000]



def block_bound_recycle(binding) -> None:
    if binding is not None:
        raise WorkerWriteGuardError("Papierkorb-Zugriff liegt außerhalb des Task-Arbeitsbaums")
