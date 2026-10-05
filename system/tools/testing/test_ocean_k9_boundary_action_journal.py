#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für tools.ocean.k9_boundary.action_journal."""

import base64
import hashlib
import json
from pathlib import Path

import pytest

from tools.ocean.k9_boundary import ActionJournal, FileOp, JournalState
from tools.ocean.k9_boundary.action_journal import (
    ActionJournalError,
    ExecuteError,
    PreflightError,
    RollbackError,
    _sha256_bytes,
    _sha256_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def workspace(tmp_path):
    return tmp_path / "workspace"


@pytest.fixture
def journal(workspace):
    return ActionJournal(workspace)


# ---------------------------------------------------------------------------
# Checksummen-Helfer
# ---------------------------------------------------------------------------

def test_sha256_bytes_roundtrip():
    data = b"hello k9-boundary"
    assert _sha256_bytes(data) == hashlib.sha256(data).hexdigest()


def test_sha256_file(tmp_path):
    path = tmp_path / "f.txt"
    _write_file(path, b"ocean")
    assert _sha256_file(path) == hashlib.sha256(b"ocean").hexdigest()


# ---------------------------------------------------------------------------
# Journal-Initialisierung
# ---------------------------------------------------------------------------

def test_journal_init_state(journal):
    assert journal.state == JournalState.EMPTY
    assert journal.ops == []
    assert journal.workspace.exists() is False


def test_journal_add_copy_records_op(journal, workspace):
    src = Path("/tmp/src.txt")
    dst = workspace / "dst.txt"
    journal.add_copy(src, dst)
    assert len(journal.ops) == 1
    op = journal.ops[0]
    assert op.op == "copy"
    assert op.src == str(src.resolve())
    assert op.dst == str(dst.resolve())


def test_journal_add_move_records_op(journal, workspace):
    src = Path("/tmp/src.txt")
    dst = workspace / "dst.txt"
    journal.add_move(src, dst)
    op = journal.ops[0]
    assert op.op == "move"
    assert op.src == str(src.resolve())
    assert op.dst == str(dst.resolve())


def test_journal_add_write_records_base64_content(journal, workspace):
    dst = workspace / "out.txt"
    content = b"\x00\xffbinary"
    journal.add_write(dst, content)
    op = journal.ops[0]
    assert op.op == "write"
    assert op.dst == str(dst.resolve())
    assert op.content == base64.b64encode(content).decode("ascii")
    assert op.checksum == _sha256(content)


def test_journal_add_delete_records_op(journal, tmp_path):
    src = tmp_path / "x.txt"
    _write_file(src, b"x")
    journal.add_delete(src)
    op = journal.ops[0]
    assert op.op == "delete"
    assert op.src == str(src.resolve())


def test_journal_add_mkdir_records_op(journal, workspace):
    dst = workspace / "newdir"
    journal.add_mkdir(dst)
    op = journal.ops[0]
    assert op.op == "mkdir"
    assert op.dst == str(dst.resolve())


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def test_preflight_ok_for_simple_write(journal, workspace):
    journal.add_write(workspace / "a.txt", b"hi")
    ok, errors = journal.preflight()
    assert ok is True
    assert errors == []


def test_preflight_rejects_missing_source(journal, tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    journal.add_copy(missing, tmp_path / "out.txt")
    ok, errors = journal.preflight()
    assert ok is False
    assert any("existiert nicht" in e for e in errors)


def test_preflight_rejects_destination_outside_workspace(journal, tmp_path):
    src = tmp_path / "src.txt"
    _write_file(src, b"s")
    outside = Path("/tmp/k9_outside.txt")
    journal.add_copy(src, outside)
    ok, errors = journal.preflight()
    assert ok is False
    assert any("außerhalb" in e for e in errors)


def test_preflight_rejects_collision_targets(journal, workspace):
    src1 = workspace / "s1.txt"
    src2 = workspace / "s2.txt"
    _write_file(src1, b"1")
    _write_file(src2, b"2")
    journal.add_copy(src1, workspace / "same.txt")
    journal.add_copy(src2, workspace / "same.txt")
    ok, errors = journal.preflight()
    assert ok is False
    assert any("doppeltes Ziel" in e for e in errors)


def test_preflight_rejects_checksum_mismatch(journal, tmp_path):
    src = tmp_path / "src.txt"
    _write_file(src, b"real")
    journal.add_copy(src, tmp_path / "workspace" / "out.txt", checksum="0" * 64)
    ok, errors = journal.preflight()
    assert ok is False
    assert any("Checksum" in e for e in errors)


def test_preflight_rejects_non_empty_dir_delete(journal, tmp_path):
    src = tmp_path / "dir"
    _write_file(src / "nested.txt", b"x")
    journal.add_delete(src)
    ok, errors = journal.preflight()
    assert ok is False
    assert any("nicht leer" in e for e in errors)


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def test_prepare_creates_workspace_backup_dir_and_journal(journal, workspace):
    journal.add_write(workspace / "a.txt", b"hello")
    journal.prepare()
    assert workspace.exists()
    assert (workspace / ActionJournal.BACKUP_DIR).exists()
    assert journal.journal_path.exists()
    assert journal.state == JournalState.PREPARED


def test_prepare_refuses_existing_prepared_state(journal, workspace):
    journal.add_write(workspace / "a.txt", b"hello")
    journal.prepare()
    with pytest.raises(ActionJournalError):
        journal.prepare()


def test_prepare_raises_preflight_error(journal):
    journal.add_copy(Path("/nonexistent"), journal.workspace / "x.txt")
    with pytest.raises(PreflightError):
        journal.prepare()


# ---------------------------------------------------------------------------
# execute copy / write / mkdir
# ---------------------------------------------------------------------------

def test_execute_copy_success(journal, tmp_path):
    src = tmp_path / "src.txt"
    _write_file(src, b"copy-me")
    dst = journal.workspace / "dst.txt"
    journal.add_copy(src, dst)
    journal.prepare()
    journal.execute()
    assert dst.read_bytes() == b"copy-me"
    assert journal.state == JournalState.EXECUTED


def test_execute_move_success(journal, tmp_path):
    src = tmp_path / "src.txt"
    _write_file(src, b"move-me")
    dst = journal.workspace / "dst.txt"
    journal.add_move(src, dst)
    journal.prepare()
    journal.execute()
    assert dst.read_bytes() == b"move-me"
    assert not src.exists()


def test_execute_write_success(journal, workspace):
    dst = workspace / "out.txt"
    content = b"written-by-action-journal"
    journal.add_write(dst, content)
    journal.prepare()
    journal.execute()
    assert dst.read_bytes() == content


def test_execute_mkdir_success(journal, workspace):
    dst = workspace / "nested" / "dir"
    journal.add_mkdir(dst)
    journal.prepare()
    journal.execute()
    assert dst.is_dir()


# ---------------------------------------------------------------------------
# delete with backup
# ---------------------------------------------------------------------------

def test_execute_delete_success(journal, tmp_path):
    src = tmp_path / "src.txt"
    _write_file(src, b"delete-me")
    journal.add_delete(src)
    journal.prepare()
    journal.execute()
    assert not src.exists()


def test_delete_backup_restored_on_rollback(journal, tmp_path):
    src = tmp_path / "src.txt"
    original = b"precious"
    _write_file(src, original)
    journal.add_delete(src)
    journal.prepare()
    journal.rollback()
    assert src.read_bytes() == original
    assert journal.state == JournalState.ROLLED_BACK


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def test_rollback_restores_overwritten_file(journal, workspace):
    dst = workspace / "file.txt"
    _write_file(dst, b"original")
    journal.add_write(dst, b"new")
    journal.prepare()
    journal.execute()
    assert dst.read_bytes() == b"new"
    journal.rollback()
    assert dst.read_bytes() == b"original"


def test_rollback_restores_copied_over_existing(journal, tmp_path, workspace):
    src = tmp_path / "src.txt"
    _write_file(src, b"new-content")
    dst = workspace / "existing.txt"
    _write_file(dst, b"old-content")
    journal.add_copy(src, dst)
    journal.prepare()
    journal.execute()
    assert dst.read_bytes() == b"new-content"
    journal.rollback()
    assert dst.read_bytes() == b"old-content"


def test_rollback_removes_newly_created_files(journal, workspace):
    dst = workspace / "new.txt"
    journal.add_write(dst, b"x")
    journal.prepare()
    journal.execute()
    assert dst.exists()
    journal.rollback()
    assert not dst.exists()


def test_rollback_removes_newly_created_directories(journal, workspace):
    dst = workspace / "newdir"
    journal.add_mkdir(dst)
    journal.prepare()
    journal.execute()
    assert dst.is_dir()
    journal.rollback()
    assert not dst.exists()


def test_rollback_moves_file_back_to_source(journal, tmp_path, workspace):
    src = tmp_path / "src.txt"
    _write_file(src, b"data")
    dst = workspace / "dst.txt"
    journal.add_move(src, dst)
    journal.prepare()
    journal.execute()
    assert dst.exists()
    assert not src.exists()
    journal.rollback()
    assert src.exists()
    assert not dst.exists()
    assert src.read_bytes() == b"data"


# ---------------------------------------------------------------------------
# Auto-Rollback bei execute-Fehler
# ---------------------------------------------------------------------------

def test_execute_auto_rollback_on_integrity_failure(journal, tmp_path):
    """Simuliert Schreibfehler: checksummen-Feld wird verändert, rollback prüfen."""
    dst = journal.workspace / "out.txt"
    _write_file(dst, b"old")  # Backup wird angelegt
    journal.add_write(dst, b"new", checksum="0" * 64)
    journal.prepare()
    with pytest.raises(ExecuteError):
        journal.execute()
    assert journal.state == JournalState.ROLLED_BACK
    assert dst.read_bytes() == b"old"


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def test_recover_rolls_back_prepared_journal(workspace):
    journal = ActionJournal(workspace)
    dst = workspace / "out.txt"
    _write_file(dst, b"old")
    journal.add_write(dst, b"new")
    journal.prepare()
    del journal  # Verbindung trennen

    recovered = ActionJournal(workspace)
    state = recovered.recover()
    assert state == JournalState.ROLLED_BACK
    assert dst.read_bytes() == b"old"


def test_recover_returns_empty_if_no_journal(tmp_path):
    journal = ActionJournal(tmp_path / "empty")
    assert journal.recover() == JournalState.EMPTY


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

def test_reset_clears_journal_and_backups(journal, workspace):
    dst = workspace / "a.txt"
    journal.add_write(dst, b"x")
    journal.prepare()
    journal.execute()
    assert journal.journal_path.exists()
    assert journal.backup_dir.exists()
    journal.reset()
    assert not journal.journal_path.exists()
    assert not journal.backup_dir.exists()
    assert journal.state == JournalState.EMPTY


def test_reset_refuses_prepared_state(journal, workspace):
    dst = workspace / "a.txt"
    journal.add_write(dst, b"x")
    journal.prepare()
    with pytest.raises(ActionJournalError):
        journal.reset()


# ---------------------------------------------------------------------------
# Journal-Persistenz
# ---------------------------------------------------------------------------

def test_journal_file_is_valid_json(journal, workspace):
    dst = workspace / "a.txt"
    journal.add_write(dst, b"x")
    journal.prepare()
    data = json.loads(journal.journal_path.read_text(encoding="utf-8"))
    assert data["state"] == "prepared"
    assert data["workspace"] == str(workspace.resolve())
    assert len(data["ops"]) == 1


def test_journal_ops_roundtrip(journal, workspace):
    dst = workspace / "a.txt"
    journal.add_write(dst, b"x")
    journal.prepare()
    journal.execute()
    journal.reset()
    journal.add_copy(dst, workspace / "b.txt")
    ok, _ = journal.preflight()
    assert ok is True  # dst existiert nach reset noch, Kopie ist möglich


# ---------------------------------------------------------------------------
# Edge-Cases
# ---------------------------------------------------------------------------

def test_journal_state_after_successful_execute(journal, workspace):
    journal.add_write(workspace / "x.txt", b"1")
    journal.prepare()
    journal.execute()
    assert journal.state == JournalState.EXECUTED


def test_add_write_with_explicit_checksum(journal, workspace):
    dst = workspace / "x.txt"
    content = b"explicit"
    checksum = _sha256(content)
    journal.add_write(dst, content, checksum=checksum)
    journal.prepare()
    journal.execute()
    assert dst.read_bytes() == content


def test_add_write_with_wrong_explicit_checksum_fails_execute(journal, workspace):
    dst = workspace / "x.txt"
    content = b"explicit"
    journal.add_write(dst, content, checksum="0" * 64)
    ok, errors = journal.preflight()
    assert ok is True  # content-checksum-Mismatch wird nicht mehr in preflight abgelehnt
    journal.prepare()
    with pytest.raises(ExecuteError):
        journal.execute()
