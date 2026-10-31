"""Regression tests for Cut-and-Close partial completion, decompose guard, and repo-binding inheritance."""
import json
import re
from types import SimpleNamespace
import pytest
from hub._services.chat.chat_runtime import SELF_DECOMPOSE_INSTRUCTION
from hub._services.chat.worker_lease_binding import (
    WorkerLeaseBinding,
    WorkerTaskManageArgumentError,
)


def test_self_decompose_instruction_teaches_cut_and_close_and_blocker_return():
    assert "TEILERFOLG GESCHAFFT" in SELF_DECOMPOSE_INSTRUCTION
    assert "task_manage(action='add'" in SELF_DECOMPOSE_INSTRUCTION
    assert "task_manage(action='update'" in SELF_DECOMPOSE_INSTRUCTION
    assert "NICHT MACHBAR / BLOCKER" in SELF_DECOMPOSE_INSTRUCTION
    assert "zerlege die Aufgabe NICHT" in SELF_DECOMPOSE_INSTRUCTION
    assert "task_manage(action='decompose'" in SELF_DECOMPOSE_INSTRUCTION
    assert "complete=false)" in SELF_DECOMPOSE_INSTRUCTION
    assert "complete=true" not in SELF_DECOMPOSE_INSTRUCTION


def test_worker_decompose_rejects_already_decomposed_task_but_allows_fresh_subtask():
    err = WorkerTaskManageArgumentError("decompose_already_decomposed")
    assert "bereits in Teilaufgaben zerlegt" in err.user_message
    assert "submit_result(complete=false)" in err.user_message

    decomposed_parent_desc = "Aufgabe\n[In 3 Teilaufgaben zerlegt: [3305, 3306, 3307]]"
    fresh_subtask_desc = "Teilaufgabe 1: Konkrete Prüfung im Worktree"
    assert re.search(r"\[In \d+ Teilaufgaben zerlegt: \[", decomposed_parent_desc)
    assert not re.search(r"\[In \d+ Teilaufgaben zerlegt: \[", fresh_subtask_desc)


def test_inherit_decomposed_subtask_bindings_propagates_parent_repo_pin_for_add_and_decompose(tmp_path):
    reg_file = tmp_path / "worker_repo_registry.v1.json"
    reg_file.write_text(json.dumps({
        "schema": "bach.worker-repo-registry.v2",
        "repositories": {
            "ellmos-ai/bach": {
                "origin": "https://github.com/ellmos-ai/bach",
                "default_branch": "main",
                "visibility": "public",
            }
        },
        "tasks": {
            "2690": {
                "repository": "ellmos-ai/bach",
                "source_sha": "be6253571111f21e66c15ad422ea0c98f3d0d82a",
                "task_version": "a" * 64,
                "operator": "operator:test",
                "registered_at": "2026-10-30T18:00:00+00:00",
                "source_proof_sha256": "b" * 64,
            }
        }
    }), encoding="utf-8")

    class DummyClient:
        def _task_policy_snapshot(self, tid):
            return {"task_version": f"{tid:064x}"}

    binding = object.__new__(WorkerLeaseBinding)
    binding._ack = SimpleNamespace(task_id=2690)
    binding._client = DummyClient()

    # Single follow-up task from action='add' inherits parent repo binding
    ok = binding._inherit_decomposed_subtask_bindings((3320,), registry_file=reg_file)
    assert ok is True
    updated = json.loads(reg_file.read_text(encoding="utf-8"))
    assert updated["tasks"]["3320"]["repository"] == "ellmos-ai/bach"
    assert updated["tasks"]["3320"]["source_sha"] == "be6253571111f21e66c15ad422ea0c98f3d0d82a"
    assert updated["tasks"]["3320"]["task_version"] == f"{3320:064x}"
