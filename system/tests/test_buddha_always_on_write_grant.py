import json

from hub._services.chat.slots_config import DEFAULT_CORE_SLOTS, load_slots_config


def test_default_slot_grants_write_tools():
    allowed_tools = DEFAULT_CORE_SLOTS["buddha_always_on"]["allowed_tools"]
    for tool in (
        "read_file",
        "write_file",
        "edit_file",
        "start_task_worktree",
        "execute_command",
        "task_manage",
    ):
        assert tool in allowed_tools


def test_v3_migrates_to_v4_with_default_tools(tmp_path):
    path = tmp_path / "slots_config.json"
    path.write_text(
        json.dumps(
            {
                "version": 3,
                "slots": {"buddha_always_on": {"id": "buddha_always_on"}},
                "dynamic_workers": [],
                "activity_history": [],
            }
        ),
        encoding="utf-8",
    )
    data = load_slots_config(str(path))
    assert data["version"] == 4
    assert data["slots"]["buddha_always_on"]["allowed_tools"] == list(
        DEFAULT_CORE_SLOTS["buddha_always_on"]["allowed_tools"]
    )


def test_v4_custom_tools_unchanged(tmp_path):
    path = tmp_path / "slots_config.json"
    path.write_text(
        json.dumps(
            {
                "version": 4,
                "slots": {
                    "buddha_always_on": {
                        "id": "buddha_always_on",
                        "allowed_tools": ["read_file"],
                    }
                },
                "dynamic_workers": [],
                "activity_history": [],
            }
        ),
        encoding="utf-8",
    )
    data = load_slots_config(str(path))
    assert data["version"] == 4
    assert data["slots"]["buddha_always_on"]["allowed_tools"] == ["read_file"]
