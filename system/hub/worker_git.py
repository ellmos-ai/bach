# -*- coding: utf-8 -*-
"""hub/worker_git.py — Git-Arbeitsweise für BACH-Worker.

Implementiert:
1. start_task_worktree(task_id): Fetcht origin und erzeugt isolierten Worktree
   unter ~/services/bach-worktrees/task-<id> auf Branch bach-task/<id>.
2. finish_task(task_id, message): Secrets-Scan, git diff --check, Testlauf,
   Commit mit [task <id>], Push und PR auf den vertrauenswürdigen Default-Branch.
   Trägt PR-URL in Task ein und setzt Status auf review.
   Bei Abbruch/WIP: Sichert Stand als [WIP]-Commit ohne PR.
3. cleanup_task_worktree(task_id): Entfernt Worktree sauber.
4. is_live_path_blocked(path): Schützt den Live-Ordner ~/services/bach vor
   Schreibzugriffen außerhalb von bach-worktrees/.
5. Schutz vor unberechtigtem Task-Abschluss ohne PR bei vorhandenen Codeänderungen.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import sqlite3
import stat
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

DEFAULT_WORKTREES_DIR = Path.home() / "services" / "bach-worktrees"
DEFAULT_BASE_BRANCH = "origin/main"

_PUBLIC_REPO = "ellmos-ai/bach"
_PUBLIC_SOURCE_SCHEMA = "bach.task-public-source.v2"
_LEGACY_PUBLIC_SOURCE_SCHEMA = "bach.task-public-source.v1"
_PUBLIC_SHA = re.compile(r"^[0-9a-f]{40}$")


def _canonical_public_origin(value: str, repository: str) -> str:
    """Return only the exact HTTPS/SSH URL for one trusted registry identity."""
    from hub._services.chat.worker_repo_registry import canonical_repository_id
    repository = canonical_repository_id(repository)
    canonical = f"https://github.com/{repository}"
    raw = str(value or "").strip()
    if raw.startswith("git@github.com:"):
        host, path = raw[len("git@"):].split(":", 1)
        if host.lower() != "github.com":
            raise RuntimeError("Repositoryquelle stimmt nicht mit der vertrauenswürdigen Repo-Bindung überein")
    else:
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError:
            raise RuntimeError("Repositoryquelle stimmt nicht mit der vertrauenswürdigen Repo-Bindung überein") from None
        if parsed.scheme not in {"https", "ssh"} or parsed.hostname is None:
            raise RuntimeError("Repositoryquelle stimmt nicht mit der vertrauenswürdigen Repo-Bindung überein")
        if parsed.hostname.lower() != "github.com" or parsed.query or parsed.fragment:
            raise RuntimeError("Repositoryquelle stimmt nicht mit der vertrauenswürdigen Repo-Bindung überein")
        if parsed.scheme == "https" and (parsed.username or parsed.password or port not in (None, 443)):
            raise RuntimeError("Repositoryquelle stimmt nicht mit der vertrauenswürdigen Repo-Bindung überein")
        if parsed.scheme == "ssh" and (parsed.username not in (None, "git") or parsed.password or port not in (None, 22)):
            raise RuntimeError("Repositoryquelle stimmt nicht mit der vertrauenswürdigen Repo-Bindung überein")
        path = parsed.path.lstrip("/")
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path.removesuffix(".git")
    if path.lower() != repository:
        raise RuntimeError("Repositoryquelle stimmt nicht mit der vertrauenswürdigen Repo-Bindung überein")
    return canonical


def _canonical_bach_origin(value: str) -> str:
    """Compatibility wrapper for BACH-only call sites and older tests."""
    return _canonical_public_origin(value, _PUBLIC_REPO)


def _git_text(
    repo: Path, operation: str, *, task_id: int | str | None = None,
    branch: str | None = None, timeout: int = 8,
) -> str:
    """Run only fixed public-source reads with validated task/repo arguments."""
    if operation == "origin":
        argv = ["git", "remote", "get-url", "origin"]
    elif operation == "main":
        argv = ["git", "rev-parse", "--verify", "refs/heads/main^{commit}"]
    elif operation == "branch":
        from hub._services.chat.worker_repo_registry import canonical_default_branch
        try:
            selected = canonical_default_branch(branch)
        except Exception:
            raise RuntimeError("Öffentliche Git-Branch-Prüfung ist nicht zulässig") from None
        argv = ["git", "rev-parse", "--verify", f"refs/heads/{selected}^{{commit}}"]
    elif operation == "head":
        argv = ["git", "rev-parse", "--verify", "HEAD^{commit}"]
    elif operation == "registration":
        key = _public_source_config_key(task_id)
        argv = ["git", "config", "--local", "--get", key]
    else:
        raise RuntimeError("Öffentliche Git-Leseoperation ist nicht zulässig")
    try:
        result = subprocess.run(
            argv, cwd=str(repo), shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            timeout=timeout, check=False,
        )
    except Exception:  # noqa: BLE001 - Gitfehler liefern keine Quellfreigabe.
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden") from None
    if result.returncode != 0:
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
    return (result.stdout or "").strip()


def _github_json(url: str) -> dict:
    """Read anonymous GitHub metadata; credentials and response bodies stay private."""
    from urllib.request import Request, urlopen
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "BACH-task-reader"})
    try:
        with urlopen(request, timeout=8) as response:
            from urllib.parse import urlsplit
            final_url = urlsplit(response.geturl())
            if (getattr(response, "status", 200) != 200
                    or final_url.scheme != "https" or final_url.hostname != "api.github.com"):
                raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
            payload = response.read(65537)
        if len(payload) > 65536:
            raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
        value = json.loads(payload.decode("utf-8"))
    except Exception:  # noqa: BLE001 - Netzwerk-/JSONfehler liefern keine Quellfreigabe.
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden") from None
    if not isinstance(value, dict):
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")  # noqa: TRY004 - RuntimeError ist der öffentliche Fail-closed-Vertrag.
    return value


def _public_default_branch_metadata(repository: str, default_branch: str) -> dict[str, str | bool]:
    """Read the configured public default branch and exact commit without Git writes."""
    from urllib.parse import quote
    from hub._services.chat.worker_repo_registry import canonical_default_branch, canonical_repository_id
    repository = canonical_repository_id(repository)
    default_branch = canonical_default_branch(default_branch)
    base_url = f"https://api.github.com/repos/{repository}"
    metadata = _github_json(base_url)
    full_name = metadata.get("full_name")
    if not (
        isinstance(full_name, str) and full_name.lower() == repository
        and metadata.get("private") is False
        and metadata.get("visibility") == "public"
        and metadata.get("default_branch") == default_branch
    ):
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
    branch = _github_json(f"{base_url}/branches/{quote(default_branch, safe='')}")
    commit = branch.get("commit") if branch.get("name") == default_branch else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not _PUBLIC_SHA.fullmatch(sha):
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
    return {
        "schema": _PUBLIC_SOURCE_SCHEMA,
        "task_id": "",  # set by the caller before persistence
        "repository": repository,
        "origin": f"https://github.com/{repository}",
        "source_ref": f"refs/heads/{default_branch}",
        "source_sha": sha,
        "visibility": "public",
        "private": False,
        "metadata_verified": True,
        "ref_verified": True,
        "verified_at": _utc_now(),
    }


def _public_main_metadata(repository: str = _PUBLIC_REPO) -> dict[str, str | bool]:
    """Compatibility wrapper for the historically BACH-main-only tests."""
    return _public_default_branch_metadata(repository, "main")


def _public_main_source(repo: Path, binding=None) -> dict[str, str | bool]:
    """Pin only the exact current, anonymously verified public default branch."""
    repository = getattr(binding, "repository", _PUBLIC_REPO)
    branch_name = getattr(binding, "default_branch", "main")
    origin = _canonical_public_origin(_git_text(repo, "origin"), repository)
    proof = _public_default_branch_metadata(repository, branch_name)
    if origin != proof["origin"]:
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
    local_sha = _git_text(repo, "branch", branch=branch_name)
    if local_sha != proof["source_sha"]:
        message = ("Lokale BACH-Basis entspricht nicht dem verifizierten öffentlichen main"
                   if repository == _PUBLIC_REPO and branch_name == "main"
                   else "Lokale öffentliche Basis entspricht nicht dem verifizierten Default-Branch")
        raise RuntimeError(message)
    _assert_source_clone_clean(repo)
    proof["origin"] = origin
    return proof


def _isolated_git_environment(global_config: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(global_config)
    return env


def _assert_source_clone_clean(repo: Path) -> None:
    """Reject dirty/untracked/filter-configured source trees without side effects."""
    config_dir = tempfile.TemporaryDirectory(prefix="bach-worker-git-config-")
    global_config = Path(config_dir.name) / "empty.gitconfig"
    global_config.write_text("", encoding="utf-8")
    env = _isolated_git_environment(global_config)
    commands = (
        (["git", "config", "--local", "--get-regexp", r"^filter\..*\.(process|clean|smudge)$"], (0, 1)),
        (["git", "status", "--porcelain=v1", "-z", "--untracked-files=all",
          "--ignore-submodules=none"], (0,)),
        (["git", "ls-files", "--cached", "-v", "-z"], (0,)),
    )
    outputs = []
    try:
        for argv, allowed in commands:
            result = subprocess.run(
                argv, cwd=str(repo), shell=False, capture_output=True,
                stdin=subprocess.DEVNULL, timeout=10, check=False, env=env,
            )
            if result.returncode not in allowed:
                raise RuntimeError("Public-Source-Clone konnte nicht sicher geprüft werden")
            outputs.append(result.stdout or b"")
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 - Git/config failures fail closed.
        raise RuntimeError("Public-Source-Clone konnte nicht sicher geprüft werden") from None
    finally:
        config_dir.cleanup()
    if outputs[0]:
        raise RuntimeError("Public-Source-Clone enthält einen konfigurierten Filter")
    if outputs[1]:
        raise RuntimeError("Public-Source-Clone ist nicht sauber")
    entries = outputs[2].split(b"\x00")
    if entries[-1] != b"" or any(not entry.startswith(b"H ") for entry in entries[:-1]):
        raise RuntimeError("Public-Source-Clone hat einen nicht sicheren Git-Index")


def _validate_pinned_source_clone(repo: Path, binding, *, require_current: bool) -> dict[str, str | bool]:
    """Recheck a task's exact immutable pin without invalidating older pins."""
    repository = binding.repository
    origin = _canonical_public_origin(_git_text(repo, "origin"), repository)
    local_sha = _git_text(repo, "branch", branch=binding.default_branch)
    if origin != binding.origin or local_sha != binding.source_sha:
        raise RuntimeError("Public-Source-Clone weicht von der unveränderlichen Task-Repo-Bindung ab")
    _assert_source_clone_clean(repo)
    if require_current and _public_default_branch_metadata(
            repository, binding.default_branch)["source_sha"] != binding.source_sha:
        raise RuntimeError("Task-Source-Pin ist nicht mehr der aktuelle öffentliche Default-Branch; explizite Neubindung erforderlich")
    return {
        "schema": _PUBLIC_SOURCE_SCHEMA,
        "task_id": "",
        "repository": repository,
        "origin": origin,
        "source_ref": f"refs/heads/{binding.default_branch}",
        "source_sha": binding.source_sha,
        "visibility": "public",
        "private": False,
        "metadata_verified": True,
        "ref_verified": True,
        "verified_at": _utc_now(),
    }


def _safe_source_clone_path(binding):
    import stat
    from hub._services.chat.worker_repo_registry import (
        RepositoryBindingError, source_clone_path,
    )
    try:
        root = source_clone_path(binding.repository, binding.source_sha)
        home = Path.home()
        bach_root = home / ".bach"
        fixed_root = bach_root / "task-repo-sources"
        if home.is_symlink() or home.resolve(strict=True) != home or bach_root.is_symlink():
            raise RepositoryBindingError("Public-Source-Root ist nicht physisch gebunden")
        bach_stat = bach_root.stat()
        if (not stat.S_ISDIR(bach_stat.st_mode)
                or (os.name != "nt" and bach_stat.st_mode & 0o077)
                or (os.name != "nt" and hasattr(os, "getuid") and bach_stat.st_uid != os.getuid())):
            raise RepositoryBindingError("BACH-Konfigurationsverzeichnis ist nicht geschützt")
        if root.resolve(strict=False) != root or not str(root).startswith(str(fixed_root) + os.sep):
            raise RepositoryBindingError("Public-Source-Pfad liegt außerhalb des geschützten Source-Verzeichnisses")
        cursor = fixed_root
        if cursor.is_symlink():
            raise RepositoryBindingError("Public-Source-Verzeichnis ist ein Link")
        if not cursor.is_dir():
            raise RepositoryBindingError("Public-Source-Verzeichnis fehlt")
        source_stat = cursor.stat()
        if (os.name != "nt" and source_stat.st_mode & 0o077) or (
                os.name != "nt" and hasattr(os, "getuid") and source_stat.st_uid != os.getuid()):
            raise RepositoryBindingError("Public-Source-Verzeichnis ist nicht geschützt")
        for part in root.relative_to(fixed_root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise RepositoryBindingError("Public-Source-Pfad enthält einen Link")
            if not cursor.is_dir():
                raise RepositoryBindingError("Public-Source-Clone fehlt")
        return root
    except (RepositoryBindingError, OSError, ValueError):
        raise RuntimeError("Trusted Public-Source-Bindung ist ungültig") from None


def _resolve_task_source(task_id, *, require_current=False):
    """Resolve only a task-keyed registry entry and its immutable source clone."""
    from hub._services.chat.worker_repo_registry import resolve_task_repository
    try:
        binding = resolve_task_repository(task_id)
    except Exception as exc:
        raise RuntimeError(str(exc) if type(exc).__name__ == "RepositoryBindingError"
                           else "Trusted Task-Repo-Bindung ist nicht verfügbar") from None
    source = _safe_source_clone_path(binding)
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError("Verifizierter Public-Source-Clone fehlt; Provisionierung durch Operator erforderlich")
    proof = _validate_pinned_source_clone(source, binding, require_current=require_current)
    return binding, source, proof


def provision_public_source_clone(repository_id: str) -> dict[str, Any]:
    """Explicit operator step: stage and validate an immutable public-default clone.

    This function is intentionally never called by task-start or pre-tool hooks.
    It creates a new SHA-addressed source tree and never updates an existing one.
    """
    import tempfile
    import shutil
    import stat
    from hub._services.chat.worker_repo_registry import (
        RepositoryBindingError, load_registry, source_clone_path,
    )
    try:
        registry = load_registry()
        record = registry["repositories"].get(repository_id)
        if not isinstance(record, dict):
            raise RepositoryBindingError("Repository fehlt in der Trusted Repo-Registry")
        canonical = _canonical_public_origin(record["origin"], repository_id)
        metadata = _public_default_branch_metadata(repository_id, record["default_branch"])
        final_path = source_clone_path(repository_id, str(metadata["source_sha"]))
        fixed_root = (Path.home() / ".bach" / "task-repo-sources").resolve(strict=False)
        if final_path.resolve(strict=False) != final_path or not str(final_path).startswith(str(fixed_root) + os.sep):
            raise RepositoryBindingError("Public-Source-Pfad liegt außerhalb des geschützten Source-Verzeichnisses")
        cursor = fixed_root
        if cursor.is_symlink():
            raise RepositoryBindingError("Public-Source-Verzeichnis ist ein Link")
        fixed_root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not fixed_root.exists():
            fixed_root.mkdir(mode=0o700)
        source_root_stat = fixed_root.stat()
        if (not stat.S_ISDIR(source_root_stat.st_mode)
                or (os.name != "nt" and source_root_stat.st_mode & 0o077)
                or (os.name != "nt" and hasattr(os, "getuid") and source_root_stat.st_uid != os.getuid())):
            raise RepositoryBindingError("Public-Source-Verzeichnis ist nicht geschützt")
        for part in final_path.parent.relative_to(fixed_root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise RepositoryBindingError("Public-Source-Pfad enthält einen Link")
            if not cursor.exists():
                cursor.mkdir(mode=0o700)
            entry_stat = cursor.stat()
            if (not stat.S_ISDIR(entry_stat.st_mode)
                    or (os.name != "nt" and entry_stat.st_mode & 0o077)
                    or (os.name != "nt" and hasattr(os, "getuid") and entry_stat.st_uid != os.getuid())):
                raise RepositoryBindingError("Public-Source-Pfad ist nicht geschützt")
        if final_path.is_symlink():
            raise RepositoryBindingError("Public-Source-Clone ist ein Link")
        if final_path.exists():
            proof = _public_main_source(final_path, type("Binding", (), {
                "repository": repository_id, "default_branch": record["default_branch"]})())
            if proof["origin"] != canonical or proof["source_sha"] != metadata["source_sha"]:
                raise RuntimeError("Vorhandener Public-Source-Clone stimmt nicht mit dem aktuellen verifizierten Default-Branch überein")
            return {"repository": repository_id, "source_sha": str(metadata["source_sha"]),
                    "path": str(final_path), "created": False}
        stage_parent = Path(tempfile.mkdtemp(prefix=".provision-", dir=str(final_path.parent)))
        stage = stage_parent / "clone"
        try:
            global_config = stage_parent / "empty.gitconfig"
            global_config.write_text("", encoding="utf-8")
            clone_env = _isolated_git_environment(global_config)
            result = subprocess.run(
                ["git", "clone", "--single-branch", "--branch", record["default_branch"], "--", canonical, str(stage)],
                cwd=str(stage_parent), shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                timeout=180, check=False, env=clone_env,
            )
            if result.returncode != 0:
                raise RuntimeError("Public-Source-Provisionierung fehlgeschlagen")
            proof = _public_main_source(stage, type("Binding", (), {
                "repository": repository_id, "default_branch": record["default_branch"]})())
            current = _public_default_branch_metadata(repository_id, record["default_branch"])
            if proof["source_sha"] != metadata["source_sha"] or current["source_sha"] != metadata["source_sha"]:
                raise RuntimeError("Öffentlicher Default-Branch änderte sich während der Source-Provisionierung")
            try:
                os.replace(stage, final_path)
            except OSError:
                if not final_path.exists() or final_path.is_symlink():
                    raise RuntimeError("Public-Source-Clone konnte nicht atomar bereitgestellt werden") from None
                proof = _public_main_source(final_path, type("Binding", (), {
                    "repository": repository_id, "default_branch": record["default_branch"]})())
                if proof["source_sha"] != metadata["source_sha"]:
                    raise RuntimeError("Parallele Public-Source-Provisionierung ergab einen anderen Pin")
            check = _public_main_source(final_path, type("Binding", (), {
                "repository": repository_id, "default_branch": record["default_branch"]})())
            if check["source_sha"] != metadata["source_sha"]:
                raise RuntimeError("Provisionierter Public-Source-Clone konnte nicht bestätigt werden")
        finally:
            shutil.rmtree(stage_parent, ignore_errors=True)
        return {"repository": repository_id, "source_sha": str(metadata["source_sha"]),
                "path": str(final_path), "created": True}
    except RepositoryBindingError as exc:
        raise RuntimeError(str(exc)) from None


def _public_source_config_key(task_id: int | str) -> str:
    if not (type(task_id) is int
            or (type(task_id) is str and re.fullmatch(r"[1-9][0-9]{0,18}", task_id))):
        raise RuntimeError("Öffentliche Taskkennung ist nicht gültig")
    numeric_id = int(task_id)
    if not 0 < numeric_id <= 2**63 - 1:
        raise RuntimeError("Öffentliche Taskkennung ist nicht gültig")
    return f"branch.bach-task/{numeric_id}.bach-public-source"


def _store_public_source_registration(repo: Path, target: Path, task_id: int | str, proof: dict) -> dict:
    from hub._services.chat.worker_repo_registry import resolve_task_repository
    binding = resolve_task_repository(task_id)
    record = dict(proof)
    source_sha = record.get("source_sha")
    if not (
        record.get("schema") == _PUBLIC_SOURCE_SCHEMA
        and record.get("repository") == binding.repository
        and record.get("origin") == binding.origin
        and record.get("source_ref") == f"refs/heads/{binding.default_branch}"
        and isinstance(source_sha, str) and _PUBLIC_SHA.fullmatch(source_sha)
        and source_sha == binding.source_sha
        and record.get("visibility") == "public" and record.get("private") is False
        and record.get("metadata_verified") is True and record.get("ref_verified") is True
        and isinstance(record.get("verified_at"), str)
    ):
        raise RuntimeError("Task-Quellregistrierung konnte nicht bestätigt werden")
    record["task_id"] = str(task_id)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    key = _public_source_config_key(task_id)
    try:
        write = subprocess.run(["git", "config", "--local", "--replace-all", key, encoded],
                               cwd=str(target), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", stdin=subprocess.DEVNULL, timeout=8, check=False)
        read = subprocess.run(["git", "config", "--local", "--get", key],
                              cwd=str(target), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=8, check=False)
    except Exception:  # noqa: BLE001 - Schreib-/Readbackfehler verhindern die Registrierung.
        raise RuntimeError("Task-Quellregistrierung konnte nicht bestätigt werden") from None
    if write.returncode != 0 or read.returncode != 0 or (read.stdout or "").strip() != encoded:
        raise RuntimeError("Task-Quellregistrierung konnte nicht bestätigt werden")
    return record


def read_task_public_source_registration(repo: Path, target: Path, task_id: int | str) -> dict:
    """Validate the stored task-worktree source pin without fetching or moving it."""
    from hub._services.chat.worker_repo_registry import resolve_task_repository
    binding = resolve_task_repository(task_id)
    try:
        raw = _git_text(target, "registration", task_id=task_id)
        record = json.loads(raw)
    except Exception:  # noqa: BLE001 - fehlerhafte Taskbindung bleibt unverfügbar.
        raise RuntimeError("Öffentliche Task-Quellregistrierung fehlt oder ist ungültig") from None
    if not isinstance(record, dict):
        raise RuntimeError("Öffentliche Task-Quellregistrierung fehlt oder ist ungültig")  # noqa: TRY004 - RuntimeError ist der öffentliche Fail-closed-Vertrag.
    try:
        origin = _canonical_public_origin(_git_text(repo, "origin"), binding.repository)
    except Exception:  # noqa: BLE001 - fehlerhafte Taskbindung bleibt unverfügbar.
        raise RuntimeError("Öffentliche Task-Quellregistrierung fehlt oder ist ungültig") from None
    if not (
        record.get("schema") in {_PUBLIC_SOURCE_SCHEMA, _LEGACY_PUBLIC_SOURCE_SCHEMA}
        and record.get("task_id") == str(task_id)
        and record.get("repository") == binding.repository
        and record.get("origin") == origin == binding.origin
        and record.get("source_ref") == f"refs/heads/{binding.default_branch}"
        and (record.get("schema") != _LEGACY_PUBLIC_SOURCE_SCHEMA or binding.repository == _PUBLIC_REPO)
        and isinstance(record.get("source_sha"), str)
        and _PUBLIC_SHA.fullmatch(record["source_sha"])
        and record.get("source_sha") == binding.source_sha
        and record.get("visibility") == "public"
        and record.get("private") is False
        and record.get("metadata_verified") is True
        and record.get("ref_verified") is True
        and isinstance(record.get("verified_at"), str)
    ):
        raise RuntimeError("Öffentliche Task-Quellregistrierung fehlt oder ist ungültig")
    head = _git_text(target, "head")
    base = record["source_sha"]
    try:
        check = subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=str(target),
                               capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               timeout=8, check=False)
    except Exception:  # noqa: BLE001 - Fehler beim Ancestorcheck sperren den Arbeitsbaum.
        raise RuntimeError("Task-Arbeitsbaum weicht von der gepinnten öffentlichen Basis ab") from None
    if check.returncode != 0:
        raise RuntimeError("Task-Arbeitsbaum weicht von der gepinnten öffentlichen Basis ab")
    return record


# Regex-Muster fuer Secrets-Scan (API Keys, Tokens, Private Keys)
SECRET_PATTERNS = [
    re.compile(r"""(?:api[_-]?key|secret|token|password|auth|bearer)\s*[:=]\s*['"][A-Za-z0-9_\-\.]{12,}['"]""", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{30,}", re.IGNORECASE),
    re.compile(r"github_pat_[A-Za-z0-9]{20,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----"),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_worktrees_dir() -> Path:
    env_dir = os.environ.get("BACH_WORKTREES_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return DEFAULT_WORKTREES_DIR.expanduser().resolve()


def get_live_repo_root() -> Path:
    env_root = os.environ.get("BACH_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parents[2].expanduser().resolve()


def _resolve(p: str | Path) -> Path:
    try:
        return Path(p).expanduser().resolve()
    except OSError:
        return Path(p).expanduser()


def _is_under(child: Path, parent: Path) -> bool:
    c = os.path.normcase(str(child)).rstrip(r"\/")
    par = os.path.normcase(str(parent)).rstrip(r"\/")
    return c == par or c.startswith(par + os.sep)


def is_live_path_blocked(path: str | Path) -> Optional[str]:
    """Prüft, ob der Pfad unter dem Live-Ordner ~/services/bach liegt, außerhalb

    von bach-worktrees/. Falls ja, blockieren mit 'Nutze start_task_worktree()'.
    """
    if os.environ.get("BACH_ALLOW_LIVE_WRITE") == "1":
        return None

    resolved = _resolve(path)
    worktrees_root = get_worktrees_dir()
    if _is_under(resolved, worktrees_root):
        return None

    live_root = get_live_repo_root()
    if _is_under(resolved, live_root):
        return "Nutze start_task_worktree()"

    return None


def start_task_worktree(
    task_id: int | str,
    *,
    base_branch: str = DEFAULT_BASE_BRANCH,
    repo_root: Path | None = None,
    worker_task_binding=None,
    require_task_binding: bool = False,
    task_code_capability: bool = False,
) -> Path:
    """Create a bound task worktree from its trusted public-source pin."""
    if require_task_binding and worker_task_binding is None:
        raise RuntimeError("Private Taskbindung fehlt")
    if type(task_code_capability) is not bool or (task_code_capability and worker_task_binding is None):
        raise RuntimeError("Task-Codefähigkeit ist nicht privat gebunden")
    if task_code_capability:
        # Reject aliases before authorization, mkdir, or any Git side effect.
        _public_source_config_key(task_id)
    task_id_str = str(task_id).strip()
    worktrees_dir = get_worktrees_dir()
    target_dir = worktrees_dir / f"task-{task_id_str}"
    branch_name = f"bach-task/{task_id_str}"

    if worker_task_binding is not None:
        if repo_root is None:
            binding, repo, public_record = _resolve_task_source(
                task_id, require_current=not target_dir.exists())
        else:
            from hub._services.chat.worker_repo_registry import resolve_task_repository
            try:
                binding = resolve_task_repository(task_id)
            except Exception as exc:
                raise RuntimeError(str(exc) if type(exc).__name__ == "RepositoryBindingError"
                                   else "Trusted Task-Repo-Bindung ist nicht verfügbar") from None
            repo = Path(repo_root).resolve(strict=True)
            if repo != _safe_source_clone_path(binding):
                raise RuntimeError("Expliziter Repo-Pfad weicht von der Trusted Task-Repo-Bindung ab")
            public_record = _validate_pinned_source_clone(
                repo, binding, require_current=not target_dir.exists())
        from hub._services.chat.worker_write_guard import authorize_start, authorize_mutation
        target_dir = authorize_start(worker_task_binding, task_id, repo_root=repo,
                                     worktrees_dir=worktrees_dir)
        if target_dir.exists():
            if task_code_capability:
                read_task_public_source_registration(repo, target_dir, task_id_str)
                authorize_start(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
            return target_dir
        allowed_bases = {"main", "origin/main", binding.default_branch,
                         f"origin/{binding.default_branch}"}
        if base_branch not in allowed_bases:
            raise RuntimeError("Gebundener Worker darf nur vom konfigurierten öffentlichen Default-Branch starten")
        if worktrees_dir.is_symlink():
            raise RuntimeError("Worktree-Zielverzeichnis ist ein Link")
        worktrees_dir.mkdir(parents=True, exist_ok=True)
        authorize_start(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
        selected_base = public_record["source_sha"] if public_record else _git_text(repo, "main")
        branch = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
                                cwd=str(repo), capture_output=True, text=True, check=False, timeout=10)
        if branch.returncode == 0:
            raise RuntimeError("Task-Branch existiert bereits, ist aber nicht an diesen Worktree gebunden")
        authorize_start(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
        res = subprocess.run(
            ["git", "worktree", "add", str(target_dir), "-b", branch_name, selected_base],
            cwd=str(repo), capture_output=True, text=True, check=False, timeout=30,
        )
        if res.returncode != 0:
            raise RuntimeError("Task-Worktree konnte nicht sicher registriert werden")
        authorize_mutation(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
        if task_code_capability:
            public_record["task_id"] = task_id_str
            authorize_mutation(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
            _store_public_source_registration(repo, target_dir, task_id_str, public_record)
            read_task_public_source_registration(repo, target_dir, task_id_str)
            authorize_mutation(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
        return target_dir.resolve(strict=True)

    worktrees_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=str(repo), capture_output=True,
                       text=True, check=False, timeout=30)
    except Exception:
        pass
    if target_dir.exists() and (target_dir / ".git").exists():
        return target_dir.resolve()
    result = subprocess.run(
        ["git", "worktree", "add", str(target_dir), "-b", branch_name, base_branch],
        cwd=str(repo), capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "worktree", "add", str(target_dir), branch_name],
            cwd=str(repo), capture_output=True, text=True, check=False, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Fehler beim Erstellen des Worktrees {target_dir}: {result.stderr}")
    return target_dir.resolve()


def _git_read_bytes(worktree_path: Path, argv: list[str], *, timeout=15) -> bytes:
    try:
        result = subprocess.run(argv, cwd=str(worktree_path), capture_output=True,
                                check=False, timeout=timeout)
    except Exception:
        raise RuntimeError("Git-Leseprüfung konnte nicht vollständig ausgeführt werden") from None
    if result.returncode != 0:
        raise RuntimeError("Git-Leseprüfung konnte nicht vollständig ausgeführt werden")
    output = result.stdout or b""
    return output.encode("utf-8", errors="surrogateescape") if isinstance(output, str) else bytes(output)


def _untracked_names(worktree_path: Path) -> list[str]:
    raw = _git_read_bytes(worktree_path,
                          ["git", "ls-files", "--others", "--exclude-standard", "-z"])
    return [os.fsdecode(item) for item in raw.split(b"\x00") if item]


def _read_untracked_file(worktree_path: Path, relative: str) -> bytes:
    root = Path(worktree_path).resolve(strict=True)
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RuntimeError("Untracked-Pfad liegt außerhalb des Arbeitsbaums")
    parent = root
    for part in rel.parts[:-1]:
        parent = parent / part
        mode = parent.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise RuntimeError("Untracked-Pfad enthält einen Link oder Nichtordner")
    path = parent / rel.parts[-1]
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        return os.fsencode(os.readlink(path))
    if not stat.S_ISREG(mode):
        raise RuntimeError("Untracked-Datei ist kein regulärer Inhalt")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("Untracked-Datei änderte während der Prüfung ihren Typ")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def scan_for_secrets(worktree_path: Path) -> list[str]:
    """Check tracked changes and every nonignored untracked file before staging."""
    try:
        diff = _git_read_bytes(worktree_path,
            ["git", "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD"])
        pieces = [diff.decode("utf-8", errors="replace")]
        for relative in _untracked_names(worktree_path):
            content = _read_untracked_file(worktree_path, relative)
            pieces.append(relative + "\n" + content.decode("utf-8", errors="replace"))
    except Exception:
        return ["Git-Änderungen oder untracked Dateien konnten nicht vollständig geprüft werden"]
    diff_text = "\n".join(pieces)
    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        matches = pattern.findall(diff_text)
        if matches:
            findings.append(f"Muster erkannt: {pattern.pattern[:30]} ({len(matches)} Treffer)")
    return findings


def check_git_diff(worktree_path: Path) -> list[str]:
    """Check tracked diffs and untracked text for whitespace errors, failing closed."""
    try:
        result = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--no-textconv", "--check", "HEAD"],
            cwd=str(worktree_path), capture_output=True, check=False, timeout=15,
        )
        output = result.stdout or b""
        errors = output.decode("utf-8", errors="replace").splitlines()
        stderr = result.stderr or b""
        if result.returncode != 0 or output or stderr:
            detail = stderr.decode("utf-8", errors="replace").splitlines()
            return [line.strip() for line in errors + detail if line.strip()] or [
                "Git-Diff-Prüfung nicht bestätigt"
            ]
        for index, relative in enumerate(_untracked_names(worktree_path), start=1):
            content = _read_untracked_file(worktree_path, relative)
            for line_number, line in enumerate(content.splitlines(), start=1):
                if line.endswith((b" ", b"\t")):
                    errors.append(f"Untracked-Datei {index}, Zeile {line_number}: trailing whitespace")
                leading = line[:len(line) - len(line.lstrip(b" \t"))]
                if b" \t" in leading:
                    errors.append(f"Untracked-Datei {index}, Zeile {line_number}: space before tab")
        return errors
    except Exception:
        return ["Git-Diff- oder untracked-Datei-Prüfung konnte nicht vollständig ausgeführt werden"]



def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is not None:
        p = db_path
    else:
        from hub.bach_paths import BACH_DB
        p = BACH_DB
    conn = sqlite3.connect(str(p), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def record_task_file_change(
    task_id: int | str,
    file_path: str | Path,
    db_path: Path | None = None,
) -> None:
    """Registriert eine Dateiänderung für task_id in task_history."""
    task_id_int = int(task_id)
    now = _utc_now()
    with _get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO task_history
               (task_id, action, field_changed, old_value, new_value, changed_by, changed_at)
               VALUES (?, 'file_modified', 'file', '', ?, 'worker', ?)
            """,
            (task_id_int, str(file_path), now),
        )
        conn.commit()


def task_has_file_changes(
    task_id: int | str,
    conn_or_db_path: sqlite3.Connection | Path | None = None,
) -> bool:
    """Prüft, ob für diese Aufgabe Code- oder Dateiänderungen registriert wurden."""
    task_id_int = int(task_id)
    if isinstance(conn_or_db_path, sqlite3.Connection):
        try:
            cur = conn_or_db_path.cursor()
            cur.execute(
                "SELECT count(*) FROM task_history WHERE task_id = ? AND action = 'file_modified'",
                (task_id_int,),
            )
            count = cur.fetchone()[0]
            if count > 0:
                return True
        except Exception:
            pass
    else:
        try:
            with _get_db(conn_or_db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT count(*) FROM task_history WHERE task_id = ? AND action = 'file_modified'",
                    (task_id_int,),
                )
                count = cur.fetchone()[0]
                if count > 0:
                    return True
        except Exception:
            pass

    # Auch im Worktree prüfen falls vorhanden
    worktree = get_worktrees_dir() / f"task-{task_id_int}"
    if worktree.exists() and (worktree / ".git").exists():
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if res.stdout and res.stdout.strip():
                return True
        except Exception:
            pass

    return False


def finish_task(task_id, message, *, is_wip=False, run_tests=True, repo_root=None, db_path=None,
                worker_task_binding=None, require_task_binding=False):
    """Preserve private ownership through every Git mutation and task receipt."""
    if require_task_binding and worker_task_binding is None:
        return {"success": False, "error": "Taskbindung fehlt"}
    if worker_task_binding is None:
        # Explicit legacy/manual invocation still needs exclusive authority;
        # it cannot turn a local projection or another holder into permission.
        from hub._services.task_lease_client import TaskLeaseClient
        from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
        from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
        from hub.bach_paths import BACH_DB
        binding = None
        cleanup_confirmed = False
        try:
            if isinstance(task_id, bool) or not str(task_id).isdecimal() or int(task_id) <= 0:
                raise ValueError("Task-ID ist ungültig")
            generation = uuid.uuid4().hex
            # The lease host is a bounded machine identifier, not a full DNS
            # name. Match the short-host convention used by manual task claims.
            host = socket.gethostname().split(".", 1)[0]
            binding = WorkerLeaseBinding.acquire(TaskLeaseClient(db_path=db_path or BACH_DB), int(task_id),
                worker_id=f"worktree-finish-{generation}@{host}", host=host, generation=generation,
                is_current=lambda: True, stop_event=threading.Event())
            with WorkerLeaseSupervisor(binding):
                result = finish_task(task_id, message, is_wip=is_wip, run_tests=run_tests, repo_root=repo_root,
                                     worker_task_binding=binding, require_task_binding=True)
        except Exception:
            result = {"success": False, "error": "Kanonische Worktree-Taskbindung nicht bestätigt"}
        finally:
            if binding is not None:
                cleanup_confirmed = binding.closed or binding.return_lease()
        if binding is not None and not cleanup_confirmed:
            return {"success": False, "error": "Kanonische Taskfreigabe nicht bestätigt"}
        return result
    if worker_task_binding is not None:
        try:
            worker_task_binding.assert_active()
            if isinstance(task_id, bool) or str(task_id) != str(worker_task_binding.task_id):
                raise ValueError("Fremde Task")
            return _finish_task(task_id, message, is_wip=is_wip, run_tests=run_tests,
                                repo_root=repo_root, db_path=db_path, worker_task_binding=worker_task_binding)
        except Exception:
            return {"success": False, "error": "Worktree-Ergebnis oder Taskänderung nicht bestätigt"}


def _finish_task(
    task_id: int | str,
    message: str,
    *,
    is_wip: bool = False,
    run_tests: bool = True,
    repo_root: Path | None = None,
    db_path: Path | None = None,
    worker_task_binding=None,
) -> dict[str, Any]:
    """Schließt einen Task im Worktree ab oder sichert den WIP-Stand.

    Normaler Modus:
    1. Secrets-Scan & git diff --check
    2. Tests der geänderten Dateien ausführen
    3. git add -A && commit [task <id>] message
    4. git push -u origin bach-task/<id>
    5. gh pr create --base <trusted default branch>
    6. PR-URL in Task eintragen, Status auf review

    WIP-Modus:
    1. Secrets-Scan & git diff --check
    2. git add -A && commit [WIP] [task <id>] message
    3. git push -u origin bach-task/<id> (ohne PR)
    4. Vermerk in Task
    """
    if worker_task_binding is None:
        return {"success": False, "error": "Private Taskbindung fehlt"}

    def run_checked(cmd, **kwargs):
        if worker_task_binding is not None:
            from hub._services.chat.worker_write_guard import authorize_mutation
            bound_cwd = kwargs.get("cwd", target_dir)
            registered, _ = authorize_mutation(
                worker_task_binding, int(task_id), paths=(bound_cwd,))
            kwargs["cwd"] = str(registered)
        return subprocess.run(cmd, **kwargs)

    task_id_str = str(task_id).strip()
    target_dir = get_worktrees_dir() / f"task-{task_id_str}"
    branch_name = f"bach-task/{task_id_str}"

    if not target_dir.exists():
        return {
            "success": False,
            "error": f"Worktree {target_dir} existiert nicht. Nutze start_task_worktree({task_id_str})",
        }

    from hub._services.chat.worker_repo_registry import resolve_task_repository
    try:
        repo_binding = resolve_task_repository(task_id_str)
    except Exception as exc:
        reason = str(exc) if type(exc).__name__ == "RepositoryBindingError" else "Trusted Task-Repo-Bindung ist nicht verfügbar"
        return {"success": False, "error": reason}

    # Revalidate before all pre-commit inspection; these commands use the
    # exact registered task tree, never a caller-provided cwd.
    from hub._services.chat.worker_write_guard import authorize_mutation
    authorize_mutation(worker_task_binding, int(task_id_str), paths=(target_dir,))
    # Secrets-Scan
    secrets = scan_for_secrets(target_dir)
    if secrets:
        return {
            "success": False,
            "error": f"Secrets-Scan fehlgeschlagen: {secrets}",
        }

    # Diff-Check
    authorize_mutation(worker_task_binding, int(task_id_str), paths=(target_dir,))
    diff_errs = check_git_diff(target_dir)
    if diff_errs:
        return {
            "success": False,
            "error": f"git diff --check fehlgeschlagen: {diff_errs}",
        }

    if is_wip:
        # WIP-Commit
        commit_msg = f"[WIP] [task {task_id_str}] {message}"
        run_checked(["git", "add", "-A"], cwd=str(target_dir), check=False, timeout=15)
        res_commit = run_checked(
            ["git", "commit", "-m", commit_msg],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if res_commit.returncode != 0 and "nothing to commit" not in (res_commit.stdout or ""):
            return {"success": False, "error": "WIP-Commit nicht bestätigt"}
        res_push = run_checked(
            ["git", "push", "-u", "origin", branch_name],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        if res_push.returncode != 0:
            return {"success": False, "error": "WIP-Push nicht bestätigt"}
        worker_task_binding.record_worktree_result(int(task_id_str), f"[WIP] Stand auf {branch_name} gesichert")
        return {"success": True, "wip": True, "branch": branch_name, "status": "wip_pushed"}

    # Normaler Abschluss: Tests aller geänderten getrackten und neuen Dateien.
    if run_tests:
        try:
            diff_result = run_checked(
                ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD"],
                cwd=str(target_dir), capture_output=True, text=True, encoding="utf-8",
                errors="surrogateescape", check=False, timeout=10,
            )
            if diff_result.returncode != 0:
                raise RuntimeError("tracked Dateiänderungen nicht bestätigt")
            untracked_result = run_checked(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=str(target_dir), capture_output=True, text=True, encoding="utf-8",
                errors="surrogateescape", check=False, timeout=10,
            )
            if untracked_result.returncode != 0:
                raise RuntimeError("untracked Dateien nicht bestätigt")
            changed_paths = (diff_result.stdout or "").split("\x00")
            changed_paths += (untracked_result.stdout or "").split("\x00")
            diff_files = list(dict.fromkeys(path for path in changed_paths if path))
        except Exception:
            return {"success": False,
                    "error": "Geänderte Dateien und Testeingaben konnten nicht vollständig gelesen werden"}

        test_files = [f for f in diff_files if "test_" in f and f.endswith(".py")]
        if test_files:
            cmd_test = ["python", "-m", "pytest", "-q", "--", *test_files]
            try:
                from hub._services.chat.worker_write_guard import run_bound_check
                from core.sandbox import SandboxResult
                test_res = run_bound_check(
                    worker_task_binding, shlex.join(cmd_test), cwd=str(target_dir), timeout=60,
                    return_result=True,
                )
            except Exception:
                return {"success": False, "error": "Gebundener Testlauf nicht sicher bestätigt"}
            if (not isinstance(test_res, SandboxResult)
                    or type(getattr(test_res, "returncode", None)) is not int
                    or type(getattr(test_res, "timed_out", None)) is not bool
                    or type(getattr(test_res, "memory_exceeded", None)) is not bool):
                return {"success": False, "error": "Gebundener Testlauf nicht sicher bestätigt"}
            if test_res.timed_out or test_res.memory_exceeded or test_res.returncode != 0:
                if test_res.timed_out:
                    reason = "Timeout nach 60 Sekunden"
                elif test_res.memory_exceeded:
                    reason = "Speichergrenze"
                else:
                    reason = f"Exitcode {test_res.returncode}"
                output = test_res.stdout or test_res.stderr or ""
                detail = f": {output[:3000]}" if isinstance(output, str) and output else ""
                return {"success": False, "error": f"Tests fehlgeschlagen ({reason}){detail}"}

    # Stage & Commit
    run_checked(["git", "add", "-A"], cwd=str(target_dir), check=False, timeout=15)
    commit_msg = f"[task {task_id_str}] {message}"
    res_commit = run_checked(
        ["git", "commit", "-m", commit_msg],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if res_commit.returncode != 0 and "nothing to commit" not in res_commit.stdout:
        return {
            "success": False,
            "error": f"git commit fehlgeschlagen: {res_commit.stderr or res_commit.stdout}",
        }

    # Push
    res_push = run_checked(
        ["git", "push", "-u", "origin", branch_name],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if res_push.returncode != 0:
        return {
            "success": False,
            "error": f"git push fehlgeschlagen: {res_push.stderr}",
        }

    # PR erstellen
    cmd_pr = [
        "gh", "pr", "create",
        "--base", repo_binding.default_branch,
        "--title", commit_msg,
        "--body", f"Automatisierter PR für Task #{task_id_str}: {message}",
    ]
    res_pr = run_checked(
        cmd_pr,
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    pr_url = ""
    if res_pr.returncode == 0:
        for line in res_pr.stdout.splitlines():
            clean = line.strip()
            if clean.startswith("https://github.com/") and "/pull/" in clean:
                pr_url = clean
                break
    else:
        # Vielleicht existiert der PR schon
        if "already exists" in (res_pr.stderr or ""):
            pr_view = run_checked(
                ["gh", "pr", "view", branch_name, "--json", "url", "-q", ".url"],
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            pr_url = pr_view.stdout.strip()
        else:
            return {
                "success": False,
                "error": f"gh pr create fehlgeschlagen: {res_pr.stderr}",
            }

    worker_task_binding.record_worktree_result(int(task_id_str), f"PR: {pr_url}", review=True, result_ref=pr_url)
    return {"success": True, "pr_url": pr_url, "status": "review"}


def cleanup_task_worktree(
    task_id: int | str,
    *,
    delete_branch: bool = False,
    repo_root: Path | None = None,
    worker_task_binding=None,
    require_task_binding: bool = False,
) -> bool:
    """Remove only a registered, clean task worktree; never force-delete files."""
    if require_task_binding and worker_task_binding is None:
        return False
    if worker_task_binding is not None:
        # A live worker must leave its registered tree for independent review.
        return False
    repo = (repo_root or get_live_repo_root()).resolve()
    task_id_str = str(task_id).strip()
    try:
        tid = int(task_id_str)
        if isinstance(task_id, bool) or tid <= 0 or str(tid) != task_id_str:
            return False
        from hub._services.chat import worker_write_guard as guard
        if worker_task_binding is not None:
            target, _ = guard.authorize_mutation(worker_task_binding, tid, repo_root=repo)
        else:
            _, worktrees_dir = guard._paths(repo, get_worktrees_dir())
            target = guard._registered_tree(repo, worktrees_dir, tid)
            guard._fresh_locks(repo, worktrees_dir, target)
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(target), capture_output=True, text=True, check=False, timeout=15,
        )
        if status.returncode != 0 or status.stdout.strip():
            return False
        if worker_task_binding is not None:
            guard.authorize_mutation(worker_task_binding, tid, repo_root=repo)
        else:
            guard._fresh_locks(repo, get_worktrees_dir(), target)
        removed = subprocess.run(
            ["git", "worktree", "remove", str(target)],
            cwd=str(repo), capture_output=True, text=True, check=False, timeout=30,
        )
        if removed.returncode != 0:
            return False
        if delete_branch:
            guard._fresh_locks(repo, get_worktrees_dir(), None)
            deleted = subprocess.run(
                ["git", "branch", "-d", f"bach-task/{task_id_str}"],
                cwd=str(repo), capture_output=True, text=True, check=False, timeout=15,
            )
            if deleted.returncode != 0:
                return False
        return True
    except Exception:
        return False
