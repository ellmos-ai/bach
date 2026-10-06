"""T437: actual manual tool and isolated startup sample block, only temp data."""
import ast
import hashlib
import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace

import pytest

SYSTEM = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("seal_fixture_tool", SYSTEM / "tests/seal_release_check.py")
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)


def make_release(tmp_path, count=5, versions=True):
    root = tmp_path / "repo"
    paths = ["README.md", "requirements.txt", "start/bach.bat", "system/hub/base.py", "hub/extra.py"]
    paths += [f"system/tools/fixture_{i}.py" for i in range(5, count)]
    actual = []
    for name in paths[:count]:
        location = root / name if name.startswith("system/") or name in paths[:3] else root / "system" / name
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(("fixture " + name).encode())
        actual.append(location)
    db = tmp_path / "release.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE distribution_manifest(path TEXT PRIMARY KEY,dist_type INTEGER,template_hash TEXT);
        CREATE TABLE dist_file_versions(id INTEGER PRIMARY KEY,file_path TEXT,file_hash TEXT);
        CREATE TABLE instance_identity(kernel_hash TEXT);
        INSERT INTO instance_identity VALUES('synthetic-fixture-only');
    """)
    for name, location in zip(paths, actual):
        digest = hashlib.sha256(location.read_bytes()).hexdigest()
        conn.execute("INSERT INTO distribution_manifest VALUES(?,2,?)", (name, digest))
        if versions:
            conn.execute("INSERT INTO dist_file_versions(file_path,file_hash) VALUES(?,?)", (name, "old-snapshot"))
            conn.execute("INSERT INTO dist_file_versions(file_path,file_hash) VALUES(?,?)", (name, digest))
    conn.commit()
    conn.close()
    tool = manual.SealSystemTests(root)
    tool.db_path = db
    return tool, actual


def startup_sample_report(tool):
    """Execute only the unchanged 0.75 AST block, never startup/lifecycle."""
    source = SYSTEM / "hub/startup.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.BoolOp):
            continue
        flags = node.test.values
        if (isinstance(node.test.op, ast.And) and len(flags) == 2
                and all(isinstance(flag, ast.UnaryOp) and isinstance(flag.op, ast.Not)
                        and isinstance(flag.operand, ast.Name) for flag in flags)
                and [flag.operand.id for flag in flags] == ["quick", "dry_run"]
                and any(isinstance(part, ast.Constant) and isinstance(part.value, str)
                        and "SELECT kernel_hash FROM instance_identity LIMIT 1" in part.value
                        for part in ast.walk(node))):
            matches.append(node)
    assert len(matches) == 1, "startup sample block changed; review this fixture explicitly"
    # Wrap only this fixed source block as a callable; no module/lifecycle code.
    function = ast.FunctionDef(
        name="fixture_sample", decorator_list=[], body=matches,
        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=name) for name in
                           ("self", "quick", "dry_run", "results")],
                           kwonlyargs=[], kw_defaults=[], defaults=[]))
    block = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    compiled = compile(block, str(source), "exec")
    code = next(value for value in compiled.co_consts if isinstance(value, CodeType))
    results = []
    FunctionType(code, {})(SimpleNamespace(base_path=tool.system_root, _get_conn=tool._ro_connect),
                           False, False, results)
    return "\n".join(results)


@pytest.mark.parametrize("missing", range(6))
def test_manual_sample_matches_startup_for_every_missing_count(tmp_path, capsys, missing):
    tool, files = make_release(tmp_path)
    for path in files[:missing]:
        path.unlink()
    before = tool.db_path.read_bytes()
    report = startup_sample_report(tool)
    tool.test_startup_check_sampling()
    output = capsys.readouterr().out
    assert tool.tests_failed == (1 if missing else 0)
    assert tool.tests_passed == (0 if missing else 1)
    if missing:
        assert f"{missing}/5 CORE-Dateien fehlen" in report
        assert "FAIL" in output
    else:
        assert report == ""
        assert "Hash-Match: 5/5" in output
    assert tool.db_path.read_bytes() == before


def test_root_system_prefix_and_fallback_use_actual_files(tmp_path):
    tool, files = make_release(tmp_path)
    names = ["README.md", "requirements.txt", "start/bach.bat", "system/hub/base.py", "hub/extra.py"]
    assert [tool._resolve_path(name) for name in names] == files
    # Preserve existing system-first behavior when both locations exist.
    collision = tool.system_root / "README.md"
    collision.write_text("system candidate", encoding="utf-8")
    assert tool._resolve_path("README.md") == collision
    assert startup_sample_report(tool) == ""
    assert tool._resolve_path("missing.py") == tool.system_root / "missing.py"


@pytest.mark.parametrize("versions", [True, False])
def test_latest_version_overrides_old_hash_or_template_fallback(tmp_path, capsys, versions):
    tool, _ = make_release(tmp_path, versions=versions)
    before = tool.db_path.read_bytes()
    tool.test_startup_check_sampling()
    assert tool.tests_passed == 1
    assert "Hash-Match: 5/5" in capsys.readouterr().out
    assert tool.db_path.read_bytes() == before


def test_hash_drift_is_reported_but_presence_gate_is_preserved(tmp_path, capsys):
    tool, files = make_release(tmp_path)
    for path in files:
        path.write_bytes(b"legitimate post-snapshot fixture change")
    before = tool.db_path.read_bytes()
    tool.test_startup_check_sampling()
    assert tool.tests_passed == 1
    assert "Hash-Match: 0/5" in capsys.readouterr().out
    assert startup_sample_report(tool) == ""
    assert tool.db_path.read_bytes() == before


def test_too_few_samples_fail_even_when_all_present(tmp_path, capsys):
    tool, _ = make_release(tmp_path, count=4)
    tool.test_startup_check_sampling()
    assert tool.tests_failed == 1
    assert "Nicht genug CORE-Dateien" in capsys.readouterr().out


def test_manual_ro_connection_never_creates_or_writes_database(tmp_path):
    tool, _ = make_release(tmp_path)
    with closing(tool._ro_connect()) as conn, pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM distribution_manifest")
    tool.db_path = tmp_path / "must-not-be-created.db"
    with pytest.raises(sqlite3.OperationalError):
        tool._ro_connect()
    assert not tool.db_path.exists()


@pytest.mark.parametrize("iteration", range(10))
def test_all_four_manual_checks_ten_runs_on_complete_synthetic_release(tmp_path, capsys, iteration):
    tool, _ = make_release(tmp_path / str(iteration), count=200)
    before = tool.db_path.read_bytes()
    assert tool.run_all() == 0
    assert (tool.tests_passed, tool.tests_failed) == (4, 0)
    assert "ERGEBNIS: 4 PASS, 0 FAIL" in capsys.readouterr().out
    assert tool.db_path.read_bytes() == before
