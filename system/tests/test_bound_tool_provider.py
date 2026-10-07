"""Module/managed tool providers must preserve the private native task context."""
import pytest

from system.tests.test_worker_lease_binding import binding, mem_db
from hub._services.chat import bach_tools


class NoLegacyTaskApp:
    def execute(self, *args):
        pytest.fail("Unfenced legacy handler executed")


@pytest.mark.parametrize("operation,args", [("done", None), ("block", None),
                                            ("show", None), ("list", []),
                                            ("edit", ["--title", "Neuer Titel"]),
                                            ("priority", ["P1"]), ("assign", ["BACH"])])
def test_bach_task_commands_use_private_binding_before_legacy_app(binding, operation, args):
    arguments = [] if operation == "list" else [str(binding.task_id)]
    arguments += args or []
    result = bach_tools.exec_tool("bach_command", {"handler": "task", "operation": operation,
                                                    "args": arguments}, "safe",
                                  bach_app=NoLegacyTaskApp(), worker_task_binding=binding)
    assert "BLOCKIERT" not in result and "Fehler" not in result
    if operation == "done": assert binding.completed_task_ids == (binding.task_id,)
    elif operation == "block": assert binding.closed and not binding.completed_task_ids
    elif operation == "edit": assert binding.task_snapshot()["title"] == "Neuer Titel"
    elif operation == "priority": assert binding.task_snapshot()["priority"] == "P1"
    elif operation == "assign": assert binding.task_snapshot()["assigned_to"] == "BACH"


@pytest.mark.parametrize("operation,args", [("done", ["9999"]), ("done", ["1", "--local"]),
                                            ("edit", ["1", "--db", "projection.db"]),
                                            ("delete", ["1"]), ("claim", ["1"]),
                                            ("lease-release", ["1"]), ("sync", []),
                                            ("edit", ["1", "--unknown", "x"])])
def test_unsupported_or_foreign_task_cli_never_falls_back(binding, operation, args):
    result = bach_tools.exec_tool("bach_command", {"handler": "task", "operation": operation, "args": args},
                                  "safe", bach_app=NoLegacyTaskApp(), worker_task_binding=binding)
    assert "BLOCKIERT" in result
    assert not binding.closed


def test_bound_provider_executes_actual_fenced_completion(binding):
    provider = bach_tools.BachToolProvider(NoLegacyTaskApp(), worker_task_binding=binding,
                                          require_task_binding=True)
    result = provider.execute("task_manage", {"action": "done", "task_id": binding.task_id}, "safe")
    assert result == f"Task #{binding.task_id} erledigt."
    assert binding.completed_task_ids == (binding.task_id,)


@pytest.mark.parametrize("name,args", [("task_manage", {"action": "done", "task_id": 1}),
                                       ("bach_command", {"handler": "task", "operation": "done", "args": ["1"]})])
def test_required_provider_without_binding_never_accesses_projection(monkeypatch, name, args):
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection accessed"))
    provider = bach_tools.BachToolProvider(NoLegacyTaskApp(), require_task_binding=True)
    result = provider.execute(name, args, "safe")
    assert "Taskbindung fehlt" in result


def test_provider_stop_prevents_every_tool_dispatch(binding, monkeypatch):
    calls = []
    monkeypatch.setattr(bach_tools, "run_shell", lambda *args: calls.append(args) or "status")
    provider = bach_tools.BachToolProvider(worker_task_binding=binding, require_task_binding=True)
    binding._stop_event.set()
    assert "BLOCKIERT" in provider.execute("system_status", {}, "safe")
    assert not calls


@pytest.mark.parametrize("name,args", [("bach_command", {"handler": "task", "operation": "done", "args": ["1"]}),
                                       ("delegate", {"target": "codex", "prompt": "Auftrag"}),
                                       ("execute_command", {"command": "echo test"}),
                                       ("edit_file", {"path": "not-opened", "old_text": "a", "new_text": "b"})])
def test_bound_plan_provider_only_accepts_its_offered_tools(binding, monkeypatch, name, args):
    monkeypatch.setattr(bach_tools.subprocess, "run", lambda *a, **kw: pytest.fail("Process started"))
    provider = bach_tools.BachToolProvider(NoLegacyTaskApp(), worker_task_binding=binding, require_task_binding=True)
    assert "BLOCKIERT" in provider.execute(name, args, "plan")
    assert not binding.closed


@pytest.mark.parametrize("method", ["stopped", "missing"])
def test_bound_provider_does_not_offer_tools_without_current_authority(binding, method):
    provider = bach_tools.BachToolProvider(worker_task_binding=None if method == "missing" else binding,
                                          require_task_binding=True)
    if method == "stopped": binding._stop_event.set()
    assert provider.get_tools("safe") == []


def test_native_task_add_creates_fenced_child_and_preserves_parent(binding):
    result = bach_tools.exec_tool("bach_command", {"handler": "task", "operation": "add",
                                                    "args": ["Folgeauftrag", "--priority=P1", "--description", "Prüfen"]},
                                  "safe", bach_app=NoLegacyTaskApp(), worker_task_binding=binding)
    assert "erstellt" in result
    assert not binding.closed
    children = [task for task in binding._client.task_candidates()["tasks"] if task["id"] != binding.task_id]
    assert len(children) == 1 and children[0]["title"] == "Folgeauftrag"


@pytest.mark.parametrize("operation", ["show", "add", "clear", "remove"])
def test_dependency_commands_use_canonical_versioned_content(binding, mem_db, operation):
    from system.tests.test_task_lease_client import _insert_task
    dependency = _insert_task(mem_db)
    if operation in {"clear", "remove", "show"}:
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id, "depends_on": str(dependency)})
    args = [str(binding.task_id)]
    if operation == "clear": args += ["--clear"]
    elif operation in {"add", "remove"}: args += ["--on" if operation == "add" else "--remove", str(dependency)]
    result = bach_tools.exec_tool("bach_command", {"handler": "task", "operation": "depends", "args": args},
                                  "safe", bach_app=NoLegacyTaskApp(), worker_task_binding=binding)
    assert "BLOCKIERT" not in result
    assert (binding.task_snapshot()["depends_on"] or "") == (str(dependency) if operation in {"add", "show"} else "")


def test_private_provider_policy_guard_is_checked_before_every_operation(binding, monkeypatch):
    allowed = [True]
    def guard():
        if not allowed[0]: raise ValueError("PRIVATE POLICY DETAIL")
    provider = bach_tools.BachToolProvider(worker_task_binding=binding, require_task_binding=True, guard=guard)
    assert provider.get_tools("safe")
    allowed[0] = False
    monkeypatch.setattr(bach_tools, "run_shell", lambda *a: pytest.fail("Tool dispatched after downgrade"))
    assert provider.get_tools("safe") == []
    result = provider.execute("system_status", {}, "safe")
    assert "BLOCKIERT" in result and "PRIVATE" not in result


@pytest.mark.parametrize("serialized", [False, True])
def test_real_native_process_accepts_only_actual_cli_completion_ack(binding, serialized):
    import asyncio
    import json
    from hub._services.chat.chat_runtime import ChatRuntime
    calls = []
    class Backend:
        def get_default_model(self): return "isolated-model"
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            args = {"handler": "task", "operation": "done", "args": [str(binding.task_id)]}
            tools = [{"function": {"name": "bach_command", "arguments": json.dumps(args) if serialized else args}}]
            return {"content": "", "tool_calls": tools,
                    "raw_message": {"role": "assistant", "content": "", "tool_calls": tools}}
    runtime = ChatRuntime(Backend(), bach_app=NoLegacyTaskApp())
    session = runtime.get_session("worker-bound")
    session.worker_task_binding = binding
    session.require_task_binding = True
    answer = asyncio.run(runtime.process("Auftrag", "worker-bound", work_priority="background"))
    assert str(answer) == f"Task #{binding.task_id} erledigt."
    assert answer.completed_task_ids == (binding.task_id,)
    assert len(calls) == 1


@pytest.mark.parametrize("tail", [["--title", "one", "-t", "two"], ["--description"],
                                   ["--required-model", "x", "--local"], ["--on", "1", "--clear"]])
def test_invalid_options_cannot_partially_mutate_content(binding, tail):
    before = binding._client.task_snapshot(binding.task_id)
    result = bach_tools.exec_tool("bach_command", {"handler": "task", "operation": "edit",
                                                    "args": [str(binding.task_id), *tail]},
                                  "safe", bach_app=NoLegacyTaskApp(), worker_task_binding=binding)
    assert "BLOCKIERT" in result
    assert binding._client.task_snapshot(binding.task_id) == before
