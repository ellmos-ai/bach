"""Tests für die Schreibfreigabe des buddha_always_on-Slots (allowed_tools, versionunabhängiger Einzug).

Prüfen:
- Neue Slots-Config enthält allowed_tools mit Schreib-/Worktree-Tools.
- Fehlendes allowed_tools beim Laden wird versionunabhängig ergänzt (keine Versionsanhebung).
- worker_write_guard akzeptiert die geladene Liste und lehnt fehlende Freigaben ab.
"""

import json

import pytest

from hub._services.chat import slots_config, worker_write_guard
from hub._services.chat.worker_write_guard import WorkerWriteGuardError


def _initialized_cfg(tmp_path, name="slots.json"):
    path = str(tmp_path / name)
    slots_config.initialize_slots_config(path)
    return slots_config.load_slots_config(path, strict=True)


def test_fresh_config_grants_write_tools(tmp_path):
    cfg = _initialized_cfg(tmp_path)
    allowed = cfg["slots"]["buddha_always_on"]["allowed_tools"]
    assert "write_file" in allowed
    assert "edit_file" in allowed
    assert "start_task_worktree" in allowed
    assert "execute_command" in allowed


def test_migration_v3_adds_allowed_tools(tmp_path):
    cfg = slots_config._fresh_slots_config()
    cfg["version"] = 3
    del cfg["slots"]["buddha_always_on"]["allowed_tools"]
    path = str(tmp_path / "slots_v3.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle)

    loaded = slots_config.load_slots_config(path, strict=True)
    allowed = loaded["slots"]["buddha_always_on"]["allowed_tools"]
    assert "write_file" in allowed
    assert "start_task_worktree" in allowed
    assert "execute_command" in allowed
    # Keine Versionsanhebung: v4 bleibt die model_sockets-Marke.
    assert loaded["version"] == 3


def test_worker_write_guard_with_slot_tools(tmp_path):
    cfg = _initialized_cfg(tmp_path)
    allowed = cfg["slots"]["buddha_always_on"]["allowed_tools"]
    # Schreibfreigabe vorhanden: Guard darf nicht werfen.
    worker_write_guard.require_write_grant("write_file", allowed)
    worker_write_guard.require_write_grant("start_task_worktree", allowed)

    # Ohne Liste bzw. ohne write_file in der Liste muss der Guard werfen.
    with pytest.raises(WorkerWriteGuardError):
        worker_write_guard.require_write_grant("write_file", None)
    without_write = [tool for tool in allowed if tool != "write_file"]
    with pytest.raises(WorkerWriteGuardError):
        worker_write_guard.require_write_grant("write_file", without_write)
