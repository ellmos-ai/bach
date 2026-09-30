"""T797: real byte/reopen evidence on temporary resources only."""
import inspect
import json
from pathlib import Path

import pytest

from imported_capabilities.category_2_superior_solutions.action_journal.adapter_bach import (
    BachActionJournal, FileActionStep, file_sha256,
)


def journal(tmp_path, run_id="safe", guard=None):
    # The new explicit safety context is supplied when supported. This keeps
    # the original data-loss assertions runnable against the old API too.
    options = {}
    if "allowed_roots" in inspect.signature(BachActionJournal).parameters:
        options = {"allowed_roots": (tmp_path,), "mutation_guard": guard or (lambda paths: True)}
    return BachActionJournal(tmp_path / "journals", run_id, **options)


def source(tmp_path, name="source.bin", data=b"original\x00bytes\xff"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_success_reopen_undo_and_idempotence(tmp_path, operation):
    src = source(tmp_path)
    original = src.read_bytes()
    target = tmp_path / "out.bin"
    j = journal(tmp_path)
    assert j.execute_actions([FileActionStep(operation, str(src), str(target))])
    assert target.read_bytes() == original
    assert src.exists() == (operation == "copy")
    reopened = journal(tmp_path)
    reopened.rollback()
    assert src.read_bytes() == original
    assert not target.exists()
    reopened.rollback()
    assert src.read_bytes() == original


@pytest.mark.parametrize("operation", ["write", "delete", "unknown"])
def test_unsupported_operation_rejected_before_mutation(tmp_path, operation):
    src = source(tmp_path)
    target = source(tmp_path, "old.bin", b"old resource")
    j = journal(tmp_path)
    with pytest.raises((ValueError, PermissionError)):
        j.execute_actions([FileActionStep(operation, str(src), str(target))])
    assert src.read_bytes() == b"original\x00bytes\xff"
    assert target.read_bytes() == b"old resource"
    assert not j.journal_file.exists()


def test_expected_source_hash_preserved_and_checked(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "target"
    step = FileActionStep("copy", str(src), str(target), source_sha256="0" * 64)
    j = journal(tmp_path)
    with pytest.raises((ValueError, RuntimeError)):
        j.execute_actions([step])
    assert step.source_sha256 == "0" * 64
    assert not target.exists() and not j.journal_file.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_occupied_target_is_never_overwritten(tmp_path, operation):
    src = source(tmp_path)
    target = source(tmp_path, "old.bin", b"protected old bytes")
    j = journal(tmp_path)
    with pytest.raises((ValueError, FileExistsError, PermissionError)):
        j.execute_actions([FileActionStep(operation, str(src), str(target))])
    assert target.read_bytes() == b"protected old bytes"
    assert src.read_bytes() == b"original\x00bytes\xff"
    assert not j.journal_file.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_rollback_refuses_changed_target_without_touching_any_step(tmp_path, operation):
    a = source(tmp_path, "a")
    b = source(tmp_path, "b")
    ta, tb = tmp_path / "ta", tmp_path / "tb"
    j = journal(tmp_path)
    assert j.execute_actions([FileActionStep(operation, str(a), str(ta)), FileActionStep(operation, str(b), str(tb))])
    ta.write_bytes(b"foreign replacement")
    before = {path: path.read_bytes() if path.exists() else None for path in (a, b, ta, tb)}
    with pytest.raises((RuntimeError, PermissionError)):
        journal(tmp_path).rollback()
    assert {path: path.read_bytes() if path.exists() else None for path in before} == before


def test_rollback_refuses_occupied_move_source(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "target"
    j = journal(tmp_path)
    j.execute_actions([FileActionStep("move", str(src), str(target))])
    src.write_bytes(b"new foreign source")
    with pytest.raises((RuntimeError, PermissionError)):
        j.rollback()
    assert src.read_bytes() == b"new foreign source"
    assert target.read_bytes() == b"original\x00bytes\xff"


@pytest.mark.parametrize("run_id", ["../escape", "..", "bad/name", "bad\\name", "", "unsafe:name"])
def test_invalid_run_id_does_not_create_directories(tmp_path, run_id):
    with pytest.raises(ValueError):
        journal(tmp_path, run_id)
    assert not (tmp_path / "journals").exists()


def test_all_sources_validated_before_first_move(tmp_path):
    src = source(tmp_path)
    j = journal(tmp_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        j.execute_actions([FileActionStep("move", str(src), str(tmp_path / "out")), FileActionStep("copy", str(tmp_path / "missing"), str(tmp_path / "out2"))])
    assert src.read_bytes() == b"original\x00bytes\xff"
    assert not (tmp_path / "out").exists()


def test_self_alias_and_cross_step_alias_rejected(tmp_path):
    a, b = source(tmp_path, "a"), source(tmp_path, "b")
    j = journal(tmp_path)
    with pytest.raises((ValueError, PermissionError)):
        j.execute_actions([FileActionStep("move", str(a), str(a.parent / "." / a.name))])
    with pytest.raises((ValueError, PermissionError, FileExistsError)):
        j.execute_actions([FileActionStep("move", str(a), str(b)), FileActionStep("move", str(b), str(tmp_path / "out"))])
    assert a.read_bytes() == b.read_bytes() == b"original\x00bytes\xff"


@pytest.mark.parametrize("result", [False, None, "FREE"])
def test_lock_or_unknown_guard_fail_closed(tmp_path, result):
    src = source(tmp_path)
    j = journal(tmp_path, guard=lambda paths: result)
    with pytest.raises(PermissionError):
        j.execute_actions([FileActionStep("copy", str(src), str(tmp_path / "out"))])
    assert not (tmp_path / "out").exists() and not j.journal_file.exists()


def test_reopen_checks_lock_again_before_undo(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "out"
    j = journal(tmp_path)
    j.execute_actions([FileActionStep("move", str(src), str(target))])
    with pytest.raises(PermissionError):
        journal(tmp_path, guard=lambda paths: False).rollback()
    assert not src.exists() and target.read_bytes() == b"original\x00bytes\xff"
