"""Fail-closed authorization for task-bound worker mutations and checks."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
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


def _run_readonly(argv, cwd, timeout=8):
    try:
        result = _RUN(
            argv, cwd=str(cwd), shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            timeout=timeout,
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
    state = task_root / ".worker-check"
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
        "BACH_DB": state / "bach.db",
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
    state_dir = target / ".worker-check"
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
        else:
            raise WorkerWriteGuardError("Prüfbefehl ist nicht sicher gebunden")
    timeout = min(max(int(timeout), 1), 120)
    authorize_mutation(binding, paths=(run_cwd, *checked))
    from core import sandbox
    if os.name == "nt" and not sandbox.HAS_PSUTIL:
        raise WorkerWriteGuardError("Prozessbaum kann auf Windows ohne psutil nicht sicher beendet werden")
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
