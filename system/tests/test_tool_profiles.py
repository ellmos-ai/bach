"""Task #2510: Toolsets als benannte Profile + read-evidence-Entkoppelung."""

import types

import pytest

from hub._services.chat import bach_tools, slots_config as slots


def _mock_binding():
    """Duck-Typed-Binding ohne echte Lease (isinstance-Gate: immer fail-closed)."""
    return types.SimpleNamespace(assert_active=lambda: None)


def _read_tools_union():
    return set(bach_tools._READ_EVIDENCE_READ_ONLY_TOOLS) | set(
        bach_tools._READ_EVIDENCE_EXTRA_READ_TOOLS
    )


class TestToolProfiles:
    def test_profile_shapes(self):
        for name in bach_tools.TOOL_PROFILES:
            res = bach_tools.resolve_tool_profile(name)
            assert isinstance(res, list)
            assert res == sorted(res)
            assert len(res) == len(set(res))

        assert sorted(bach_tools.TOOL_PROFILES["readonly"]) == sorted(
            ["get_datetime", "list_directory", "read_file", "search_text", "task_manage"]
        )

        files = set(bach_tools.TOOL_PROFILES["files"])
        readonly = set(bach_tools.TOOL_PROFILES["readonly"])
        assert files >= readonly | {
            "write_file",
            "edit_file",
            "recycle",
            "move_file",
            "copy_file",
            "file_info",
        }

        code_delivery = set(bach_tools.TOOL_PROFILES["code_delivery"])
        assert code_delivery >= {"execute_command", "start_task_worktree", "finish_task"}

        standard = set(bach_tools.TOOL_PROFILES["standard"])
        all_tools = set(bach_tools.TOOL_PROFILES["all"])
        assert standard <= all_tools

        for name in bach_tools.TOOL_PROFILES:
            res = bach_tools.resolve_tool_profile(name)
            bound = bach_tools.resolve_tool_profile(name, bound_worker=True)
            assert set(bound) <= set(res)
            assert "delegate" not in bound
            assert "cleanup_task_worktree" not in bound

    def test_unknown_profile_is_none(self):
        assert bach_tools.resolve_tool_profile("superprofile") is None
        assert bach_tools.resolve_tool_profile(7) is None
        assert bach_tools.resolve_tool_profile(None) is None

    def test_readonly_subset_of_read_tools(self):
        assert set(bach_tools.TOOL_PROFILES["readonly"]) <= _read_tools_union()
        assert bach_tools._READ_EVIDENCE_EXTRA_READ_TOOLS == {"list_directory", "get_datetime"}

    def test_extra_read_tools_decoupled_from_exact_match(self):
        # SimpleNamespace-Binding ueberlebt das isinstance-Gate nicht -> fail-closed False.
        binding = _mock_binding()
        grants = ["read_file", "search_text", "task_manage", "list_directory"]
        assert bach_tools._read_evidence_readonly_worker_enabled(binding, grants) is False
        # Entkoppelung: list_directory ist Teil der erlaubten Read-Tools (EXTRA),
        # der exakte 3-Werkzeug-Match ist entfallen.
        assert {"read_file", "list_directory"} <= _read_tools_union()

    def test_false_cases(self):
        binding = _mock_binding()
        cases = [
            None,
            "read_file",
            [],
            ["search_text", "task_manage"],
            ["read_file", "write_file"],
        ]
        for grants in cases:
            assert bach_tools._read_evidence_readonly_worker_enabled(binding, grants) is False

    def test_slots_validates_tool_profile(self):
        result = slots._validated_core_edits({"tool_profile": "readonly"})
        assert result is None or (
            isinstance(result, dict) and result.get("tool_profile") == "readonly"
        )
        slots._validated_core_edits({"tool_profile": None})
        with pytest.raises(ValueError):
            slots._validated_core_edits({"tool_profile": "superprofile"})
        with pytest.raises(ValueError):
            slots._validated_core_edits({"tool_profile": 7})

    def test_resolve_tool_profile_bound_worker_filters_delegate(self):
        assert set(bach_tools.TOOL_PROFILES) == {
            "standard", "readonly", "files", "code_delivery", "all",
        }
        assert bach_tools.resolve_tool_profile("does-not-exist") is None
        assert bach_tools.resolve_tool_profile(
            "does-not-exist", bound_worker=True
        ) is None
        for name, grants in bach_tools.TOOL_PROFILES.items():
            full = bach_tools.resolve_tool_profile(name)
            assert full == sorted(grants)
            bound = bach_tools.resolve_tool_profile(name, bound_worker=True)
            assert bound == sorted(grants - {"delegate", "cleanup_task_worktree"})
            assert "delegate" not in bound
            assert "cleanup_task_worktree" not in bound
        # Der Filter muss in mindestens einem Profil wirklich Werkzeuge entfernen.
        assert any(
            "delegate" in g or "cleanup_task_worktree" in g
            for g in bach_tools.TOOL_PROFILES.values()
        )