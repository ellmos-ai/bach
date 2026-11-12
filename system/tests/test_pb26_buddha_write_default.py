"""Buddha Always-On: Standard-Schreibweg im Task-Arbeitsbaum (PB-26 Paket A).

#327 (Oktober 2026) macht ``allowed_tools=None`` fuer gebundene Worker zu
"keine Schreibfreigabe". Der Tray-Schalter "Full-Modus (Schreibrechte)" setzt
nur ``mode``; ohne Standardliste blieb Buddha deshalb im Full-Modus lesend.
"""
import json

import pytest

from hub._services.chat import slots_config, worker_write_guard

CORE = "buddha_always_on"
BOUND_WRITE = {"safe_shell", "start_task_worktree", "write_file", "edit_file",
               "execute_command", "finish_task"}


@pytest.fixture
def core_file(tmp_path):
    path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(path)
    return path


def _set_stored(path, **fields):
    with open(path, encoding="utf-8") as stream:
        config = json.load(stream)
    config["slots"][CORE].update(fields)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(config, stream)


def test_full_mode_without_explicit_grants_gets_task_worktree_write_path(core_file):
    _set_stored(core_file, mode="full", allowed_tools=None)  # Zustand auf dem Mac
    grants = slots_config.get_always_on_execution_slot(core_file)["allowed_tools"]
    assert BOUND_WRITE <= set(grants) and "task_manage" in grants
    for name in BOUND_WRITE:
        worker_write_guard.require_write_grant(name, grants)  # wirft nicht


def test_full_mode_grants_stay_inside_the_guarded_path(core_file):
    _set_stored(core_file, mode="full", allowed_tools=None)
    grants = set(slots_config.get_always_on_execution_slot(core_file)["allowed_tools"])
    # Kein freies Schreiben: nur Worktree-gebundene Werkzeuge, nichts Destruktives.
    assert not grants & {"move_file", "copy_file", "recycle", "create_directory",
                         "cleanup_task_worktree", "delegate"}
    # Alle Namen muessen vom Slot-Validator akzeptiert werden.
    slots_config._validated_core_edits({"allowed_tools": sorted(grants)})


def test_safe_mode_stays_without_write_rights(core_file):
    _set_stored(core_file, mode="safe", allowed_tools=None)
    grants = slots_config.get_always_on_execution_slot(core_file)["allowed_tools"]
    assert "task_manage" in grants and "read_file" in grants
    assert not any(worker_write_guard.is_write_tool(name) for name in grants)


def test_explicit_grants_win_and_reader_does_not_rewrite_storage(core_file):
    _set_stored(core_file, mode="full", allowed_tools=["task_manage", "read_file"])
    assert slots_config.get_always_on_execution_slot(core_file)["allowed_tools"] == ["task_manage", "read_file"]
    _set_stored(core_file, allowed_tools=None)
    slots_config.get_always_on_execution_slot(core_file)
    assert slots_config.get_slot(CORE, core_file).get("allowed_tools") is None
