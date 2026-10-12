# -*- coding: utf-8 -*-
"""hub/worker_git.py — Git-Arbeitsweise für BACH-Worker.

Implementiert:
1. start_task_worktree(task_id): Fetcht origin und erzeugt isolierten Worktree
   unter ~/services/bach-worktrees/task-<id> auf Branch bach-task/<id>.
2. finish_task(task_id, message): Secrets-Scan, git diff --check, Testlauf,
   Commit mit [task <id>], Push und PR via 'gh pr create --base main'.
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
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

DEFAULT_WORKTREES_DIR = Path.home() / "services" / "bach-worktrees"
DEFAULT_BASE_BRANCH = "origin/main"

_PUBLIC_REPO = "ellmos-ai/bach"
_PUBLIC_SOURCE_SCHEMA = "bach.task-public-source.v1"
_PUBLIC_SHA = re.compile(r"^[0-9a-f]{40}$")


def _canonical_bach_origin(value: str) -> str:
    """Return the one approved BACH GitHub identity, or fail closed."""
    raw = str(value or "").strip()
    if raw.startswith("git@github.com:"):
        host, path = raw[len("git@"):].split(":", 1)
        if host.lower() != "github.com":
            raise RuntimeError("Repositoryquelle ist nicht der kanonische öffentliche BACH-Quellstand")
    else:
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError:
            raise RuntimeError("Repositoryquelle ist nicht der kanonische öffentliche BACH-Quellstand") from None
        if parsed.scheme not in {"https", "ssh"} or parsed.hostname is None:
            raise RuntimeError("Repositoryquelle ist nicht der kanonische öffentliche BACH-Quellstand")
        if parsed.hostname.lower() != "github.com" or parsed.query or parsed.fragment:
            raise RuntimeError("Repositoryquelle ist nicht der kanonische öffentliche BACH-Quellstand")
        if parsed.scheme == "https" and (parsed.username or parsed.password or port not in (None, 443)):
            raise RuntimeError("Repositoryquelle ist nicht der kanonische öffentliche BACH-Quellstand")
        if parsed.scheme == "ssh" and (parsed.username not in (None, "git") or parsed.password or port not in (None, 22)):
            raise RuntimeError("Repositoryquelle ist nicht der kanonische öffentliche BACH-Quellstand")
        path = parsed.path.lstrip("/")
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path.removesuffix(".git")
    if path.lower() != _PUBLIC_REPO:
        raise RuntimeError("Repositoryquelle ist nicht der kanonische öffentliche BACH-Quellstand")
    return "https://github.com/ellmos-ai/bach"


def _git_text(
    repo: Path, operation: str, *, task_id: int | str | None = None, timeout: int = 8,
) -> str:
    """Run only the four fixed public-source read operations."""
    if operation == "origin":
        argv = ["git", "remote", "get-url", "origin"]
    elif operation == "main":
        argv = ["git", "rev-parse", "--verify", "refs/heads/main^{commit}"]
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


def _public_main_source(repo: Path) -> dict[str, str | bool]:
    """Pin only the exact current, anonymously verified public main commit."""
    origin = _canonical_bach_origin(_git_text(repo, "origin"))
    metadata = _github_json("https://api.github.com/repos/ellmos-ai/bach")
    full_name = metadata.get("full_name")
    if not (
        isinstance(full_name, str) and full_name.lower() == _PUBLIC_REPO
        and metadata.get("private") is False
        and metadata.get("visibility") == "public"
        and metadata.get("default_branch") == "main"
    ):
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
    branch = _github_json("https://api.github.com/repos/ellmos-ai/bach/branches/main")
    commit = branch.get("commit") if branch.get("name") == "main" else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not _PUBLIC_SHA.fullmatch(sha):
        raise RuntimeError("Öffentliche Quellbindung konnte nicht bestätigt werden")
    local_sha = _git_text(repo, "main")
    if local_sha != sha:
        raise RuntimeError("Lokale BACH-Basis entspricht nicht dem verifizierten öffentlichen main")
    return {
        "schema": _PUBLIC_SOURCE_SCHEMA,
        "task_id": "",  # set by the caller before persistence
        "repository": _PUBLIC_REPO,
        "origin": origin,
        "source_ref": "refs/heads/main",
        "source_sha": sha,
        "visibility": "public",
        "private": False,
        "metadata_verified": True,
        "ref_verified": True,
        "verified_at": _utc_now(),
    }


def _public_source_config_key(task_id: int | str) -> str:
    if not (type(task_id) is int
            or (type(task_id) is str and re.fullmatch(r"[1-9][0-9]{0,18}", task_id))):
        raise RuntimeError("Öffentliche Taskkennung ist nicht gültig")
    numeric_id = int(task_id)
    if not 0 < numeric_id <= 2**63 - 1:
        raise RuntimeError("Öffentliche Taskkennung ist nicht gültig")
    return f"branch.bach-task/{numeric_id}.bach-public-source"


def _store_public_source_registration(repo: Path, target: Path, task_id: int | str, proof: dict) -> dict:
    record = dict(proof)
    source_sha = record.get("source_sha")
    if not (
        record.get("schema") == _PUBLIC_SOURCE_SCHEMA
        and record.get("repository") == _PUBLIC_REPO
        and record.get("origin") == "https://github.com/ellmos-ai/bach"
        and record.get("source_ref") == "refs/heads/main"
        and isinstance(source_sha, str) and _PUBLIC_SHA.fullmatch(source_sha)
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
    try:
        raw = _git_text(target, "registration", task_id=task_id)
        record = json.loads(raw)
    except Exception:  # noqa: BLE001 - fehlerhafte Taskbindung bleibt unverfügbar.
        raise RuntimeError("Öffentliche Task-Quellregistrierung fehlt oder ist ungültig") from None
    if not isinstance(record, dict):
        raise RuntimeError("Öffentliche Task-Quellregistrierung fehlt oder ist ungültig")  # noqa: TRY004 - RuntimeError ist der öffentliche Fail-closed-Vertrag.
    try:
        origin = _canonical_bach_origin(_git_text(repo, "origin"))
    except Exception:  # noqa: BLE001 - fehlerhafte Taskbindung bleibt unverfügbar.
        raise RuntimeError("Öffentliche Task-Quellregistrierung fehlt oder ist ungültig") from None
    if not (
        record.get("schema") == _PUBLIC_SOURCE_SCHEMA
        and record.get("task_id") == str(task_id)
        and record.get("repository") == _PUBLIC_REPO
        and record.get("origin") == origin == "https://github.com/ellmos-ai/bach"
        and record.get("source_ref") == "refs/heads/main"
        and isinstance(record.get("source_sha"), str)
        and _PUBLIC_SHA.fullmatch(record["source_sha"])
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
    """Create the task worktree; the optional code-reader path pins public main."""
    if require_task_binding and worker_task_binding is None:
        raise RuntimeError("Private Taskbindung fehlt")
    if type(task_code_capability) is not bool or (task_code_capability and worker_task_binding is None):
        raise RuntimeError("Task-Codefähigkeit ist nicht privat gebunden")
    if task_code_capability:
        # Reject aliases before authorization, mkdir, or any Git side effect.
        _public_source_config_key(task_id)
    repo = (repo_root or get_live_repo_root()).resolve()
    task_id_str = str(task_id).strip()
    worktrees_dir = get_worktrees_dir()
    target_dir = worktrees_dir / f"task-{task_id_str}"
    branch_name = f"bach-task/{task_id_str}"

    if worker_task_binding is not None:
        from hub._services.chat.worker_write_guard import authorize_start, authorize_mutation
        target_dir = authorize_start(worker_task_binding, task_id, repo_root=repo,
                                     worktrees_dir=worktrees_dir)
        if target_dir.exists():
            if task_code_capability:
                read_task_public_source_registration(repo, target_dir, task_id_str)
                authorize_start(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
            return target_dir
        if base_branch not in {"main", "origin/main"}:
            raise RuntimeError("Gebundener Worker darf nur von main oder origin/main starten")
        if worktrees_dir.is_symlink():
            raise RuntimeError("Worktree-Zielverzeichnis ist ein Link")
        worktrees_dir.mkdir(parents=True, exist_ok=True)
        authorize_start(worker_task_binding, task_id, repo_root=repo, worktrees_dir=worktrees_dir)
        public_record = _public_main_source(repo) if task_code_capability else None
        if task_code_capability:
            selected_base = public_record["source_sha"]
        else:
            base = subprocess.run(["git", "rev-parse", "--verify", f"{base_branch}^{{commit}}"],
                                  cwd=str(repo), capture_output=True, text=True, check=False, timeout=10)
            if base.returncode != 0:
                raise RuntimeError("Task-Basisbranch ist lokal nicht verfügbar; kein Fetch wurde gestartet")
            selected_base = base.stdout.strip()
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
        if public_record is not None:
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
            host = socket.gethostname()
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
    5. gh pr create --base main
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
        "--base", "main",
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
