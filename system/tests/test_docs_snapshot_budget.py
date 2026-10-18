"""Regression coverage for documentation deltas after a source deployment."""
from types import SimpleNamespace

import pytest

from hub._services.docs import maintenance_dispatch as dispatch


def snapshot(monkeypatch, tmp_path, names):
    def run(command, **_kwargs):
        if command[1:] == ["rev-parse", "HEAD"]:
            output = ("a" * 40 + "\n").encode()
        elif command[1] == "diff" and "-z" in command:
            output = ("\0".join(names) + "\0").encode()
        else:
            assert command[1] in {"diff", "ls-files"}
            output = b""
        return SimpleNamespace(stdout=output, returncode=0)

    monkeypatch.setattr(dispatch.subprocess, "run", run)
    return dispatch.git_snapshot(tmp_path, "b" * 40)


def test_snapshot_counts_relevant_files_after_excluding_data_and_tests(monkeypatch, tmp_path):
    relevant = [f"system/gui/api/changed_{index}.py" for index in range(159)]
    excluded = [f"system/tests/test_changed_{index}.py" for index in range(49)]
    excluded += [f"system/data/changed_{index}.json" for index in range(49)]
    assert len(relevant + excluded) == 257

    revision, names = snapshot(monkeypatch, tmp_path, relevant + excluded)

    assert revision == "a" * 40
    assert names == relevant


def test_snapshot_still_rejects_more_than_256_relevant_files(monkeypatch, tmp_path):
    names = [f"system/gui/api/changed_{index}.py" for index in range(257)]

    with pytest.raises(ValueError, match="Documentation delta exceeds file budget"):
        snapshot(monkeypatch, tmp_path, names)
