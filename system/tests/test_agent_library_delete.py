"""Regressionstests für die agent-library-profillöschung (Task #2332).

Deckt den kanonischen Löschpfad delete_worker_profile ab: Erfolg inklusive
striktem Readback, Guard-Ablehnungen, Adapter-Fehlercodes und den
fail-closed Readback nach der Löschung.
"""

import copy
import os
import socket
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import pytest

import hub._services.agent_library as agent_library_adapter
from hub._services.chat import telegram_chat
from hub._services.chat.slots_config import (
    initialize_slots_config,
    load_slots_config,
    remove_worker,
    save_slots_config,
)
from hub.agent_process_provider import capture_process_create_time


def _controller_run(worker_id):
    return {
        "schema": "bach.worker-controller-run.v1",
        "phase": "never_admitted",
        "worker_id": worker_id,
        "pid": os.getpid(),
        "process_create_time": capture_process_create_time(os.getpid()),
        "host": socket.gethostname(),
        "durable": os.name == "posix",
        "prior_runs_unconfirmed": False,
    }


def _add_profile(tmp_path, profile):
    initialize_slots_config(str(tmp_path / "slots.json"))
    cfg = load_slots_config(None)
    cfg.setdefault("dynamic_workers", []).append(copy.deepcopy(profile))
    save_slots_config(cfg)
    return cfg


def test_delete_success_removes_profile_and_invokes_archive(tmp_path, monkeypatch):
    worker_id = "agent-library-delete-ok"
    profile = {"id": worker_id, "_controller_run": _controller_run(worker_id)}
    _add_profile(tmp_path, profile)

    calls = []
    real_archive = agent_library_adapter.archive_then_remove_profile

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_archive(*args, **kwargs)

    monkeypatch.setattr(agent_library_adapter, "archive_then_remove_profile", spy)

    result, status = telegram_chat.delete_worker_profile(worker_id)

    assert status == 200
    assert result == {"ok": True, "id": worker_id}
    assert len(calls) == 1
    survivors = load_slots_config(None, strict=True).get("dynamic_workers")
    assert isinstance(survivors, list)
    assert all(entry.get("id") != worker_id for entry in survivors)


def test_delete_rejects_profile_without_controller_run(tmp_path):
    worker_id = "agent-library-delete-unconfirmed"
    _add_profile(tmp_path, {"id": worker_id})

    result, status = telegram_chat.delete_worker_profile(worker_id)

    assert status == 409
    assert result["error_code"] == "worker_delete_execution_unconfirmed"
    survivors = load_slots_config(None, strict=True).get("dynamic_workers")
    assert any(entry.get("id") == worker_id for entry in survivors)


def test_delete_rejects_invalid_worker_id():
    result, status = telegram_chat.delete_worker_profile("bad id!")
    assert status == 400
    assert result == {"error": "Worker-ID ist ungültig"}


def test_delete_rejects_unknown_and_core_ids(tmp_path):
    _add_profile(tmp_path, {"id": "agent-library-keep"})

    result, status = telegram_chat.delete_worker_profile("agent-library-missing")
    assert status == 404
    assert result == {"error": "Workerprofil nicht gefunden"}

    result, status = telegram_chat.delete_worker_profile("buddha_always_on")
    assert status == 404
    assert result == {"error": "Workerprofil nicht gefunden"}


def test_remove_worker_without_guard_requires_execution_proof(tmp_path):
    worker_id = "agent-library-direct-remove"
    _add_profile(tmp_path, {"id": worker_id})

    with pytest.raises(RuntimeError, match="worker_delete_execution_unconfirmed"):
        remove_worker(worker_id)

    survivors = load_slots_config(None, strict=True).get("dynamic_workers")
    assert any(entry.get("id") == worker_id for entry in survivors)


def test_delete_maps_archive_failure_to_http_codes(tmp_path, monkeypatch):
    worker_id = "agent-library-archive-fail"
    _add_profile(tmp_path, {"id": worker_id, "_controller_run": _controller_run(worker_id)})

    def fail_budget(*args, **kwargs):
        raise RuntimeError("worker_delete_budget_unconfirmed")

    monkeypatch.setattr(agent_library_adapter, "archive_then_remove_profile", fail_budget)
    result, status = telegram_chat.delete_worker_profile(worker_id)
    assert status == 409
    assert result["error_code"] == "worker_delete_budget_unconfirmed"

    def fail_value(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(agent_library_adapter, "archive_then_remove_profile", fail_value)
    result, status = telegram_chat.delete_worker_profile(worker_id)
    assert status == 503
    assert result == {"error": "Worker-Löschung oder Belegarchiv nicht verifizierbar"}


def test_delete_readback_failure_answers_503(tmp_path, monkeypatch):
    worker_id = "agent-library-readback-ghost"
    before = _add_profile(
        tmp_path, {"id": worker_id, "_controller_run": _controller_run(worker_id)}
    )

    def fake_load(*args, **kwargs):
        return copy.deepcopy(before)

    monkeypatch.setattr(telegram_chat, "load_slots_config", fake_load)

    result, status = telegram_chat.delete_worker_profile(worker_id)

    assert status == 503
    assert result == {"error": "Worker-Löschung oder Belegarchiv nicht verifizierbar"}