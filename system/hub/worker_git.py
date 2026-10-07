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

import os
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

DEFAULT_WORKTREES_DIR = Path.home() / "services" / "bach-worktrees"
DEFAULT_BASE_BRANCH = "origin/main"

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
) -> Path:
    """Erzeugt oder aktualisiert einen isolierten Git-Worktree für task_id.

    Befehl:
      git fetch origin
      git worktree add ~/services/bach-worktrees/task-<id> -b bach-task/<id> <base_branch>
    """
    repo = (repo_root or get_live_repo_root()).resolve()
    task_id_str = str(task_id).strip()
    worktrees_dir = get_worktrees_dir()
    target_dir = worktrees_dir / f"task-{task_id_str}"
    branch_name = f"bach-task/{task_id_str}"

    worktrees_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch origin
    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except Exception:
        pass

    # 2. Wenn Worktree bereits existiert, diesen zurückgeben
    if target_dir.exists() and (target_dir / ".git").exists():
        return target_dir.resolve()

    # 3. Worktree anlegen
    cmd_new_branch = [
        "git", "worktree", "add",
        str(target_dir),
        "-b", branch_name,
        base_branch,
    ]
    res = subprocess.run(
        cmd_new_branch,
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if res.returncode != 0:
        # Branch existiert womöglich schon -> ohne -b versuchen
        cmd_existing_branch = [
            "git", "worktree", "add",
            str(target_dir),
            branch_name,
        ]
        res2 = subprocess.run(
            cmd_existing_branch,
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if res2.returncode != 0:
            raise RuntimeError(
                f"Fehler beim Erstellen des Worktrees {target_dir}: {res2.stderr or res.stderr}"
            )

    return target_dir.resolve()


def scan_for_secrets(worktree_path: Path) -> list[str]:
    """Prüft geänderte/staged Dateien auf mögliche Zugangsdaten."""
    findings: list[str] = []
    # diff gegen HEAD bzw. unstaged
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        diff_text = res.stdout or ""
    except Exception as exc:
        return [f"Fehler beim Lesen von git diff: {exc}"]

    for pattern in SECRET_PATTERNS:
        matches = pattern.findall(diff_text)
        if matches:
            findings.append(f"Muster erkannt: {pattern.pattern[:30]} ({len(matches)} Treffer)")

    return findings


def check_git_diff(worktree_path: Path) -> list[str]:
    """Führt 'git diff --check' aus, um Whitespace- und Syntaxkonflikte abzufangen."""
    try:
        res = subprocess.run(
            ["git", "diff", "--check"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if res.returncode != 0:
            lines = [l.strip() for l in (res.stdout or res.stderr).splitlines() if l.strip()]
            return lines or ["git diff --check Fehler gemeldet"]
    except Exception as exc:
        return [f"Fehler bei git diff --check: {exc}"]
    return []


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
            worker_task_binding.assert_active()
        return subprocess.run(cmd, **kwargs)

    task_id_str = str(task_id).strip()
    target_dir = get_worktrees_dir() / f"task-{task_id_str}"
    branch_name = f"bach-task/{task_id_str}"

    if not target_dir.exists():
        return {
            "success": False,
            "error": f"Worktree {target_dir} existiert nicht. Nutze start_task_worktree({task_id_str})",
        }

    # Secrets-Scan
    secrets = scan_for_secrets(target_dir)
    if secrets:
        return {
            "success": False,
            "error": f"Secrets-Scan fehlgeschlagen: {secrets}",
        }

    # Diff-Check
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

    # Normaler Abschluss: Tests laufen lassen
    if run_tests:
        # Finde geänderte Dateien
        try:
            diff_files = run_checked(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            ).stdout.splitlines()
        except Exception:
            diff_files = []

        test_files = [f for f in diff_files if "test_" in f and f.endswith(".py")]
        if test_files:
            cmd_test = ["pytest", "-q"] + test_files
            test_res = run_checked(
                cmd_test,
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if test_res.returncode != 0:
                return {
                    "success": False,
                    "error": f"Tests fehlgeschlagen: {test_res.stdout or test_res.stderr}",
                }

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
) -> bool:
    """Entfernt den Worktree für task_id und optional den Branch."""
    repo = (repo_root or get_live_repo_root()).resolve()
    task_id_str = str(task_id).strip()
    target_dir = get_worktrees_dir() / f"task-{task_id_str}"
    branch_name = f"bach-task/{task_id_str}"

    if not target_dir.exists():
        return False

    res = subprocess.run(
        ["git", "worktree", "remove", str(target_dir), "--force"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if res.returncode != 0:
        # Fallback: Ordner löschen und prune
        shutil.rmtree(str(target_dir), ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(repo), check=False, timeout=10)

    if delete_branch:
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    return True
