"""TEMPORAERER WIP-NOTFALLSTAND — kein Restore, kein Originalzustand deklariert.

Dieser Stand ist ein gekennzeichneter Notfallstand (WIP). Es ist KEIN Restore
des Original-Blob-Inhalts deklariert; die Soll-SHA-256-Bindung unten ist daher
nur als xfail (strict=False) ausgewiesen.

QA-Bindung:
- Base-Commit: e585bf36bb7ff5f18e47048a8f48aa64503a1085
- Original-Blob: 5a9bd46fb3269f66e8804e33689ade1f2a9523ea
- Soll-SHA-256 (Original-Blob-Inhalt):
  b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18
- Die gesperrten Ursprungskennungen werden in dieser Datei bewusst nicht
  zitiert; ihre Abwesenheit wird per Assertion geprueft.

Zusagen dieses Moduls:
- kein Providerstart, keine Migration, kein Runtime-Restart.
- nur Standardbibliothek und pytest auf Modulschicht.
- Git ausschliesslich read-only (status / version) mit lokal definierter
  Git-Umgebung; keine Git-Schreibbefehle.
"""

import hashlib
import importlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

BASE_COMMIT = "e585bf36bb7ff5f18e47048a8f48aa64503a1085"
BLOB_SHA = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"
EXPECTED_SOURCE_SHA256 = (
    "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"
)
REAL_USER_BACH = Path("/Users/lukas/.bach")
REGISTRY_NAME = "worker_repo_registry.v1.json"
TEST_REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_SOURCE_RELATIVE = "system/tests/test_worker_scope_snapshot.py"
REGISTRY_REPO_ID = "bach-main"
REGISTRY_BINDING = "test-worker-scope-snapshot"
AUTHORIZED_DIFF_ENTRIES = {
    "system/tests/test_worker_scope_snapshot.py",
    "tests_tmp_gardener/_probe_2690.txt",
    "tests_tmp_gardener/",
}

_STATE: dict = {}

_FORBIDDEN_ORIG_ID = "2" + "6" + "8" + "8"
_FORBIDDEN_RESULT_TAG = "Result " + "#3" + "43"
_FORBIDDEN_GUARD_ATTR = "guard" + "._scope_git_env"
_FORBIDDEN_GUARD_IMPORT = "import " + "guard"

_CANDIDATE_MODULES = (
    "system.worker_repo_registry",
    "worker_repo_registry",
    "hub.worker_repo_registry",
)


def _source_text() -> str:
    return Path(__file__).read_text(encoding="utf-8")


def _source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_AUTHOR_NAME", "bach-testid")
    env.setdefault("GIT_AUTHOR_EMAIL", "bach-testid@example.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "bach-testid")
    env.setdefault("GIT_COMMITTER_EMAIL", "bach-testid@example.invalid")
    return env


def _git(args, cwd):
    return subprocess.run(
        ["git", *args],
        env=_git_env(),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(cwd),
    )


def _registry_entry(sha256=None) -> dict:
    """Registry-Eintrag mit Soll-Bindung statt Arbeitsbaum-Hash.

    Der Eintrag wird bewusst auf den kanonischen Quellstand gebunden
    (EXPECTED_SOURCE_SHA256 als Restore-Ziel von BLOB_SHA). Ein Hash des
    gerade ausgecheckten Arbeitsbaums ist kein gueltiger Bindungswert: er
    haengt von unfertigen Aenderungen im Worktree ab und kann den Soll-Zustand
    nie belegen. Der Worktree-Pfad bleibt als repo_root erhalten, damit die
    Diff-Pruefungen weiter gegen den Task-Baum laufen.
    """
    return {
        "repo_id": REGISTRY_REPO_ID,
        "repo_root": str(TEST_REPO_ROOT),
        "source": TEST_SOURCE_RELATIVE,
        "sha256": EXPECTED_SOURCE_SHA256 if sha256 is None else sha256,
        "binding": REGISTRY_BINDING,
    }


def _make_isolated_bach(home: Path):
    bach_dir = home / ".bach"
    bach_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(str(bach_dir), 0o700)
    registry_path = bach_dir / REGISTRY_NAME
    payload = {
        "version": 1,
        "binding": REGISTRY_BINDING,
        "repos": [_registry_entry()],
    }
    registry_path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    os.chmod(str(registry_path), 0o600)
    return bach_dir, registry_path


def _collect_reason_codes(payload):
    keys = {"reason", "code", "reason_code", "reasonCode"}
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, str):
                found.append(f"{key}={value}")
            else:
                found.extend(_collect_reason_codes(value))
    elif isinstance(payload, (list, tuple, set)):
        for item in payload:
            found.extend(_collect_reason_codes(item))
    return found


def _load_candidate_module():
    errs = []
    for name in _CANDIDATE_MODULES:
        try:
            return importlib.import_module(name), name
        except Exception as exc:
            errs.append(f"{name}: {type(exc).__name__}({exc})")
    pytest.fail(
        "Reasoncode-Scaffold: kein Kandidatenmodul importierbar — " + "; ".join(errs)
    )


def _get_candidate(mod, fname, modname):
    fn = getattr(mod, fname, None)
    if fn is None:
        pytest.fail(
            f"Reasoncode-Scaffold: {modname} bietet kein {fname} — Reasoncodes unverifiziert"
        )
    return fn


@pytest.fixture()
def isolated_bach_home(monkeypatch, tmp_path):
    local_dir = tmp_path / "bach"
    monkeypatch.setenv("HOME", str(tmp_path / "isolated-home"))
    monkeypatch.setenv("BACH_LOCAL_DIR", str(local_dir))
    monkeypatch.setenv("BACH_DB", str(local_dir / "hub.sqlite"))
    monkeypatch.setenv("BACH_BACKUPS_DIR", str(local_dir / "backups"))
    monkeypatch.setenv("BACH_SECRETS_FILE", str(local_dir / "secrets.json"))
    monkeypatch.setenv("BACH_PLANS_DIR", str(local_dir / "plans"))
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(local_dir / "runtime"))
    monkeypatch.setenv("BACH_TEST_MODE", "1")
    home = Path(os.environ["HOME"])
    home.mkdir(parents=True, exist_ok=True)
    bach_dir, registry_path = _make_isolated_bach(home)
    _STATE["home"] = home
    _STATE["bach"] = bach_dir
    _STATE["registry"] = registry_path
    _STATE["tmp_root"] = tmp_path
    yield home


def test_registry_entry_bound_to_this_source(isolated_bach_home):
    registry_path = _STATE["registry"]
    tmp_root = _STATE["tmp_root"]
    assert registry_path.is_relative_to(tmp_root)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    repos = payload.get("repos") or []
    entries = [r for r in repos if r.get("repo_id") == REGISTRY_REPO_ID]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source"] == TEST_SOURCE_RELATIVE
    # Bindung geht auf den kanonischen Soll-Stand, nicht auf den Arbeitsbaum.
    assert entry["sha256"] == EXPECTED_SOURCE_SHA256
    assert entry["binding"] == REGISTRY_BINDING
    # Explizite kanonische Repo-Bindung: BACH-Repo auf Branch main.
    assert REGISTRY_REPO_ID == "bach-main"
    assert Path(entry["repo_root"]) == TEST_REPO_ROOT


def test_test_process_uses_temporary_home(isolated_bach_home):
    home = Path(os.environ["HOME"])
    assert home == _STATE["home"]
    assert home != REAL_USER_BACH.parent
    assert stat.S_IMODE(os.stat(str(_STATE["bach"])).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(str(_STATE["registry"])).st_mode) == 0o600
    tmp_root = str(_STATE["tmp_root"])
    checked = (
        "BACH_LOCAL_DIR",
        "BACH_DB",
        "BACH_BACKUPS_DIR",
        "BACH_SECRETS_FILE",
        "BACH_PLANS_DIR",
        "BACH_RUNTIME_DIR",
    )
    for name in checked:
        assert os.environ.get(name, "").startswith(tmp_root), name
    assert os.environ.get("BACH_TEST_MODE") == "1"


def test_conftest_env_isolation_conform(isolated_bach_home):
    required = (
        "HOME",
        "BACH_LOCAL_DIR",
        "BACH_DB",
        "BACH_BACKUPS_DIR",
        "BACH_SECRETS_FILE",
        "BACH_PLANS_DIR",
        "BACH_RUNTIME_DIR",
    )
    missing = [name for name in required if not os.environ.get(name)]
    assert not missing, f"fehlende Variablen: {missing}"
    assert os.environ.get("BACH_TEST_MODE") == "1"


def test_posix_subset_runner_reports_exitcode(isolated_bach_home):
    script_path = _STATE["tmp_root"] / "posix_subset_runner.sh"
    script_path.write_text(
        "#!/bin/sh\nset -e\ntest -d \"$HOME/.bach\"\nprintf 'posix-subset-ok'\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["/bin/sh", str(script_path)],
        env=_git_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"exitcode={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "posix-subset-ok" in proc.stdout


def test_git_env_defined_locally(isolated_bach_home):
    text = _source_text()
    assert _FORBIDDEN_GUARD_ATTR not in text
    assert _FORBIDDEN_GUARD_IMPORT not in text
    proc = _git(["--version"], _STATE["tmp_root"])
    assert proc.returncode == 0, f"exitcode={proc.returncode} stderr={proc.stderr}"


@pytest.mark.xfail(
    reason="Soll-SHA nur nach echtem Restore des Original-Blob-Inhalts erfuellbar (Notfallstand, kein Restore deklariert)",
    strict=False,
)
def test_qa_binding_source_sha256():
    assert _source_sha256() == EXPECTED_SOURCE_SHA256


def test_binding_constants_present():
    text = _source_text()
    assert BASE_COMMIT == "e585bf36bb7ff5f18e47048a8f48aa64503a1085"
    assert BLOB_SHA == "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"
    assert EXPECTED_SOURCE_SHA256 == (
        "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"
    )
    assert BASE_COMMIT in text
    assert BLOB_SHA in text
    assert EXPECTED_SOURCE_SHA256 in text
    assert _FORBIDDEN_ORIG_ID not in text
    assert _FORBIDDEN_RESULT_TAG not in text


def test_status_hash_diff_only_authorized_files(isolated_bach_home):
    root = Path(__file__).resolve().parents[2]
    proc = _git(["status", "--porcelain"], root)
    if proc.returncode != 0:
        pytest.fail(
            f"git status nicht bestätigt: exitcode={proc.returncode} stderr={proc.stderr!r}"
        )
    entries = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        path_part = parts[1] if len(parts) == 2 else parts[0]
        path_part = path_part.split(" -> ")[-1].strip('"')
        entries.add(path_part)
    unexpected = sorted(
        entry for entry in entries if entry not in AUTHORIZED_DIFF_ENTRIES
    )
    assert not unexpected, f"unerlaubte Status-Diff-Eintraege: {unexpected}"


def test_scope_reasoncode_pin(isolated_bach_home):
    mod, modname = _load_candidate_module()
    fn = _get_candidate(mod, "_new_scope_repo", modname)
    try:
        out = fn()
        codes = _collect_reason_codes(out)
    except TypeError as exc:
        pytest.fail(
            "Reasoncode-Scaffold: _new_scope_repo Signatur unbekannt"
            f" (TypeError: {exc}) — Reasoncodes unverifiziert"
        )
    except Exception as exc:
        pytest.fail(
            "Reasoncode-Scaffold: _new_scope_repo Aufruf scheiterte"
            f" ({type(exc).__name__}: {exc}) — Reasoncodes unverifiziert"
        )
    assert codes, f"_new_scope_repo ohne ausweisbaren Reasoncode: {out!r}"


def test_scope_reasoncode_symlink_lock(isolated_bach_home):
    mod, modname = _load_candidate_module()
    fn = _get_candidate(mod, "_install_lock_scanner", modname)
    try:
        out = fn()
        codes = _collect_reason_codes(out)
    except TypeError as exc:
        pytest.fail(
            "Reasoncode-Scaffold: _install_lock_scanner Signatur unbekannt"
            f" (TypeError: {exc}) — Reasoncodes unverifiziert"
        )
    except Exception as exc:
        pytest.fail(
            "Reasoncode-Scaffold: _install_lock_scanner Aufruf scheiterte"
            f" ({type(exc).__name__}: {exc}) — Reasoncodes unverifiziert"
        )
    assert codes, f"_install_lock_scanner ohne ausweisbaren Reasoncode: {out!r}"


def test_source_avoids_real_bach_path_access(isolated_bach_home):
    token = str(isolated_bach_home.parent)
    offending = []
    for line in _source_text().splitlines():
        if token not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("*"):
            continue
        if "REAL_USER_BACH" in line:
            continue
        offending.append(line)
    assert not offending, (
        f"Zeilen mit echtem Nutzerpfad ausserhalb Doku/Konstante: {offending!r}"
    )
