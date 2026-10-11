from pathlib import Path
from types import SimpleNamespace

import pytest

from hub._services import skill_source_service as source


def _scanner_paths(tmp_path: Path, monkeypatch):
    tools = tmp_path / "lock-tools"
    tools.mkdir()
    scanner = tools / "lock_scan.py"
    scanner.write_text("# isolated scanner path fixture\n", encoding="utf-8")
    (tools / "lock_roots.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("BACH_LOCK_TOOLS_ROOT", str(tools))
    monkeypatch.setenv("BACH_LOCK_GUARD_TEST_SENTINEL", "inherited")
    target = tmp_path / "skills" / "example" / "SKILL.md"
    target.parent.mkdir(parents=True)
    return scanner, target


def test_scanner_child_uses_configured_python_with_inherited_guard_environment(tmp_path, monkeypatch):
    scanner, target = _scanner_paths(tmp_path, monkeypatch)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"locks": [], "twin_status": "ok"}', stderr="")

    monkeypatch.setattr(source.subprocess, "run", run)
    source.check_write_locks(target)

    assert calls
    for args, kwargs in calls:
        assert args[0] == source.sys.executable
        assert args[1:] == [str(scanner), "--check-dir", args[3], "--json"]
        assert "-S" not in args
        assert kwargs["env"]["BACH_LOCK_GUARD_TEST_SENTINEL"] == "inherited"
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert kwargs["timeout"] == 15


@pytest.mark.parametrize(
    "returncode,stdout",
    [
        (1, '{"locks": [], "twin_status": "ok"}'),
        (0, '{"locks": [{"scope": "unknown"}], "twin_status": "ok"}'),
        (0, '{"locks": [], "twin_status": "unknown"}'),
        (0, "not-json"),
    ],
    ids=["scanner-denied", "locked", "unknown-twin", "invalid-readback"],
)
def test_denied_or_unknown_scanner_readback_fails_closed(tmp_path, monkeypatch, returncode, stdout):
    _, target = _scanner_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(
        source.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=""),
    )

    with pytest.raises(PermissionError):
        source.check_write_locks(target)
