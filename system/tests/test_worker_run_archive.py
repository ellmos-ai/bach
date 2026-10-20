"""Private durable archive tests for terminal worker request receipts."""

import hashlib
import json
import os
import stat

import pytest

from hub._services.chat import worker_run_archive


def _terminal_record(worker_id="worker-a", request_id="a" * 32, **changes):
    record = {
        "schema": "bach.worker-model-requests.v1",
        "service_instance": "b" * 32,
        "start_request_id": request_id,
        "generation": "c" * 32,
        "worker_id": worker_id,
        "pid": 4321,
        "process_create_time": 12345.5,
        "task_id": 71,
        "task_version": None,
        "configuration_version": "d" * 64,
        "limit": 3,
        "reserved_count": 0,
        "phase": "terminal",
        "reason": "interrupted_no_dispatch",
        "sequence": 1,
    }
    record.update(changes)
    return record


def _canonical_record_bytes(record):
    return json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def test_empty_records_return_zero_without_touching_directory(tmp_path):
    directory = tmp_path / "not-created"

    assert worker_run_archive.archive_terminal_records("worker-a", [], directory) == 0
    assert not directory.exists()


def test_nonterminal_record_is_rejected_before_filesystem_mutation(tmp_path):
    directory = tmp_path / "not-created"
    active = _terminal_record(
        phase="active", task_version="e" * 64, reserved_count=1, reason="",
    )

    with pytest.raises(worker_run_archive.WorkerRunArchiveError, match="nicht terminal"):
        worker_run_archive.archive_terminal_records("worker-a", [active], directory)

    assert not directory.exists()


def test_worker_mismatch_is_rejected_before_filesystem_mutation(tmp_path):
    directory = tmp_path / "not-created"

    with pytest.raises(worker_run_archive.WorkerRunArchiveError, match="gebunden"):
        worker_run_archive.archive_terminal_records(
            "worker-b", [_terminal_record(worker_id="worker-a")], directory,
        )

    assert not directory.exists()


def test_conflicting_duplicate_request_ids_are_rejected_before_mutation(tmp_path):
    directory = tmp_path / "not-created"
    first = _terminal_record()
    second = _terminal_record(sequence=2)

    with pytest.raises(worker_run_archive.WorkerRunArchiveError, match="Konfligierende"):
        worker_run_archive.archive_terminal_records("worker-a", [first, second], directory)

    assert not directory.exists()


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX directory fsync boundary")
def test_archive_is_private_durable_idempotent_and_contains_only_receipt(tmp_path):
    directory = tmp_path / "private" / "model-request-runs"
    record = _terminal_record()

    assert worker_run_archive.archive_terminal_records("worker-a", [record, record], directory) == 1
    archive_files = list(directory.iterdir())
    assert len(archive_files) == 1
    archive_path = archive_files[0]
    original_bytes = archive_path.read_bytes()
    document = json.loads(original_bytes)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(archive_path.stat().st_mode) == 0o600
    assert set(document) == {
        "schema", "worker_id", "start_request_id", "archived_at", "record_sha256", "record",
    }
    assert document["record"] == record
    assert document["record_sha256"] == hashlib.sha256(_canonical_record_bytes(record)).hexdigest()
    assert "prompt" not in document and "profile" not in document

    # Replaying the same receipt confirms the existing immutable file without
    # changing its original archive timestamp or creating another entry.
    assert worker_run_archive.archive_terminal_records("worker-a", [record], directory) == 1
    assert archive_path.read_bytes() == original_bytes
    assert len(list(directory.iterdir())) == 1


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX directory fsync boundary")
def test_archive_rejects_changed_receipt_without_overwriting_original(tmp_path):
    directory = tmp_path / "private"
    first = _terminal_record()
    assert worker_run_archive.archive_terminal_records("worker-a", [first], directory) == 1
    archive_path = next(directory.iterdir())
    original_bytes = archive_path.read_bytes()

    with pytest.raises(worker_run_archive.WorkerRunArchiveError, match="abweichenden Beleg"):
        worker_run_archive.archive_terminal_records(
            "worker-a", [_terminal_record(sequence=2)], directory,
        )

    assert archive_path.read_bytes() == original_bytes


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX directory fsync boundary")
def test_corrupt_existing_archive_is_never_replaced(tmp_path):
    directory = tmp_path / "private"
    record = _terminal_record()
    assert worker_run_archive.archive_terminal_records("worker-a", [record], directory) == 1
    archive_path = next(directory.iterdir())
    archive_path.write_bytes(b"corrupted receipt")

    with pytest.raises(worker_run_archive.WorkerRunArchiveError, match="ungültig"):
        worker_run_archive.archive_terminal_records("worker-a", [record], directory)

    assert archive_path.read_bytes() == b"corrupted receipt"


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX symlink protections")
def test_symlink_archive_directory_is_rejected_without_following_it(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    linked_directory = linked_parent / "archive"

    with pytest.raises(OSError):
        worker_run_archive.archive_terminal_records(
            "worker-a", [_terminal_record()], linked_directory,
        )

    assert list(real_parent.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX symlink protections")
def test_symlink_archive_file_is_not_followed_or_replaced(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    victim = tmp_path / "outside.json"
    victim.write_text("leave this file alone", encoding="utf-8")
    link = directory / worker_run_archive._archive_filename("worker-a", "a" * 32)
    link.symlink_to(victim)

    with pytest.raises(OSError):
        worker_run_archive.archive_terminal_records("worker-a", [_terminal_record()], directory)

    assert victim.read_text(encoding="utf-8") == "leave this file alone"
    assert link.is_symlink()


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX exclusive file creation")
def test_temp_name_collision_does_not_remove_preexisting_file(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    collision = directory / ".tmp-fixed"
    collision.write_text("preexisting", encoding="utf-8")
    monkeypatch.setattr(worker_run_archive.secrets, "token_hex", lambda _length: "fixed")

    with pytest.raises(FileExistsError):
        worker_run_archive.archive_terminal_records("worker-a", [_terminal_record()], directory)

    assert collision.read_text(encoding="utf-8") == "preexisting"
    assert len(list(directory.iterdir())) == 1


@pytest.mark.skipif(os.name != "nt", reason="Native Windows unsupported-durability boundary")
def test_nonempty_archive_rejects_without_creating_any_path_on_windows(tmp_path):
    directory = tmp_path / "not-created"

    with pytest.raises(OSError, match="POSIX-Verzeichnissync"):
        worker_run_archive.archive_terminal_records(
            "worker-a", [_terminal_record()], directory,
        )

    assert not directory.exists()
