# SPDX-License-Identifier: MIT
"""Regression tests for Buddha chat tools, error transparency, agy delegation, and self-healing prompts."""

import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat import bach_tools, chat_runtime, slots_config
from hub._services.chat.bach_tools import exec_tool
from hub._services.chat.worker_tool_errors import ToolErrorText


@pytest.fixture
def task_db(tmp_path, monkeypatch):
    p = tmp_path / "bach.db"
    conn = sqlite3.connect(str(p))
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            category TEXT,
            depends_on TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'pending',
            assigned_to TEXT DEFAULT 'bach',
            assigned_slot TEXT,
            required_model TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
        INSERT INTO tasks (title, description, status, priority)
        VALUES ('Sperre aufloesen', 'Originaltext mit Abnahmekriterium.', 'pending', 'P2');
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(chat_runtime, "RUNTIME_BACH_DB", str(p))
    return p


class TestListDirectoryErrors:
    def test_missing_directory_returns_resource_not_found_not_unconfirmed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(chat_runtime, "_ALLOWED_FS_ROOTS", chat_runtime._ALLOWED_FS_ROOTS + (tmp_path.resolve(),))
        missing = tmp_path / "does-not-exist" / "workers"
        result = exec_tool("list_directory", {"path": str(missing)}, mode="safe")
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "resource_not_found"
        assert result._effect_state == "not_applied"
        assert "nicht gefunden" in str(result)

    def test_file_path_returns_directory_expected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(chat_runtime, "_ALLOWED_FS_ROOTS", chat_runtime._ALLOWED_FS_ROOTS + (tmp_path.resolve(),))
        file_path = tmp_path / "plain.txt"
        file_path.write_text("hello", encoding="utf-8")
        result = exec_tool("list_directory", {"path": str(file_path)}, mode="safe")
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "directory_expected"
        assert result._effect_state == "not_applied"


class TestAgentManagePolicyErrors:
    def test_cloud_start_permission_error_is_returned_explicitly(self):
        def fake_ops(_args, **_kwargs):
            raise PermissionError("Agenten starten ausschließlich verfügbare lokale Worker")

        result = exec_tool(
            "agent_manage",
            {"action": "start_local", "slot_id": "worker-cloud", "configuration_version": "abc"},
            mode="safe",
            agent_operations=fake_ops,
        )
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "tool_not_authorized"
        assert result._effect_state == "not_applied"
        assert "ausschließlich verfügbare lokale Worker" in str(result)

    def test_unlisted_permission_error_redacts_arbitrary_details(self):
        secret = "INTERNAL_PRIVATE_TOKEN_LEAK"

        def fake_ops(_args, **_kwargs):
            raise PermissionError(secret)

        result = exec_tool("agent_manage", {"action": "list"}, mode="safe", agent_operations=fake_ops)
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "tool_not_authorized"
        assert secret not in str(result)

    def test_configuration_version_conflict_is_state_conflict(self):
        def fake_ops(_args, **_kwargs):
            raise RuntimeError("configuration_version_conflict")

        result = exec_tool("agent_manage", {"action": "start_local"}, mode="safe", agent_operations=fake_ops)
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "state_conflict"
        assert "agent_manage(action='list')" in str(result)

    def test_unconfirmed_start_runtime_error_remains_unknown_effect(self):
        def fake_ops(_args, **_kwargs):
            raise RuntimeError("Lokaler Workerstart nicht bestätigt")

        result = exec_tool("agent_manage", {"action": "start_local"}, mode="safe", agent_operations=fake_ops)
        assert type(result) is ToolErrorText
        assert result._code == "bach_tool_effect_unconfirmed"
        assert result._effect_state == "unknown"


class TestTaskManageChatSafety:
    def test_unbound_done_with_result_explains_chat_usage(self, task_db):
        result = exec_tool(
            "task_manage",
            {"action": "done", "task_id": 1, "result": "Erledigt", "complete": True},
            mode="safe",
        )
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "task_binding_required"
        assert "result" in str(result) and "weglassen" in str(result)

    def test_update_append_description_preserves_original_text(self, task_db):
        result = exec_tool(
            "task_manage",
            {"action": "update", "task_id": 1, "append_description": "Pruefnotiz: Review ist offen."},
            mode="safe",
        )
        assert "aktualisiert" in result
        with sqlite3.connect(task_db) as conn:
            desc = conn.execute("SELECT description FROM tasks WHERE id=1").fetchone()[0]
        assert "Originaltext mit Abnahmekriterium." in desc
        assert "Pruefnotiz: Review ist offen." in desc

    @pytest.mark.parametrize("slot", ["buddha_chat", "buddha_connector", "buddha_talk"])
    def test_update_rejects_interface_slot_as_assigned_slot(self, task_db, slot):
        result = exec_tool(
            "task_manage",
            {"action": "update", "task_id": 1, "assigned_slot": slot},
            mode="safe",
        )
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "invalid_arguments"
        with sqlite3.connect(task_db) as conn:
            assigned = conn.execute("SELECT assigned_slot FROM tasks WHERE id=1").fetchone()[0]
        assert assigned is None


class TestDelegateAgy:
    def test_delegate_agy_builds_flag_order_and_omits_payload_from_logs(self, monkeypatch, caplog):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="OK von agy", stderr="")

        monkeypatch.setattr(bach_tools.subprocess, "run", fake_run)
        caplog.set_level("INFO")
        result = exec_tool(
            "delegate",
            {"target": "agy", "model": "gemini-4-carbon-high", "prompt": "SECRET_PROMPT_42"},
            mode="full",
        )
        assert result == "OK von agy"
        assert captured["cmd"] == ["agy", "--model=gemini-4-carbon-high", "--print", "SECRET_PROMPT_42"]
        assert "SECRET_PROMPT_42" not in caplog.text
        assert "DELEGATE: execution requested (payload omitted)" in caplog.text

    @pytest.mark.parametrize("bad_model", ["--dangerously-skip-permissions", "bad model", ";rm -rf /"])
    def test_delegate_rejects_invalid_model_name(self, monkeypatch, bad_model):
        monkeypatch.setattr(bach_tools.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")))
        result = exec_tool(
            "delegate",
            {"target": "agy", "model": bad_model, "prompt": "Pruefen"},
            mode="full",
        )
        assert type(result) is ToolErrorText
        assert result._code == "tool_policy_denied"
        assert result._reason == "invalid_arguments"

    def test_delegate_agy_nonzero_exit_is_unconfirmed_and_redacted(self, monkeypatch):
        secret = "RAW_AGY_STDERR_SECRET"
        monkeypatch.setattr(
            bach_tools.subprocess,
            "run",
            lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=secret),
        )
        result = exec_tool("delegate", {"target": "agy", "prompt": "Test"}, mode="full")
        assert type(result) is ToolErrorText
        assert result._code == "bach_tool_effect_unconfirmed"
        assert secret not in str(result)


class TestSelfHealingSystemPrompts:
    def test_factory_system_prompt_is_self_healing_without_frozen_models(self):
        prompt = slots_config.DEFAULT_SYSTEM_PROMPT
        for stale in ("Qwen 3.5", "qwen3.8", "openrouter/free", "v3.9.1"):
            assert stale not in prompt
        for pointer in ("CLAUDE.md", "SYSTEM-MANIFEST.md", "agent_manage(action='list')", "ollama_info", "agy"):
            assert pointer in prompt

    def test_chat_runtime_reads_live_edited_system_prompt_immediately(self, tmp_path):
        cfg_path = str(tmp_path / "slots.json")
        slots_config.initialize_slots_config(cfg_path)
        backend = SimpleNamespace(get_default_model=lambda: "test-model")
        rt = chat_runtime.ChatRuntime(
            backend=backend,
            system_prompt="statischer fallback",
            base_system_reader=lambda: slots_config.get_prompt_templates(cfg_path)["system_default"]["text"],
        )
        session = chat_runtime.ChatSession()
        initial = rt.build_system_prompt(session)
        assert "SELBSTHEILENDE SYSTEMORIENTIERUNG" in initial

        snap = slots_config.core_prompt_snapshot(cfg_path)
        slots_config.change_core_prompt(
            "system_default",
            snap["configuration_version"],
            text="Eigener Live-Systemprompt aus der GUI.",
            path=cfg_path,
        )
        edited = rt.build_system_prompt(session)
        assert edited.startswith("Eigener Live-Systemprompt aus der GUI.")

        snap2 = slots_config.core_prompt_snapshot(cfg_path)
        slots_config.change_core_prompt(
            "system_default",
            snap2["configuration_version"],
            reset=True,
            path=cfg_path,
        )
        restored = rt.build_system_prompt(session)
        assert "SELBSTHEILENDE SYSTEMORIENTIERUNG" in restored
