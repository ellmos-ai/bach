"""Zuschnittregel für lokale Modelle ist in Rolle, Zerlegungshinweisen und Blueprint verankert (Plan 25.10., Punkt 5)."""
from hub._services.chat.chat_runtime import SELF_DECOMPOSE_INSTRUCTION
from hub._services.chat.slots_config import DEFAULT_ROLE_PROMPTS
from hub._services.chat.task_cut_rule import TASK_CUT_RULE, TASK_CUT_RULE_SHORT
from hub._services.chat.worker_lease_binding import WorkerTaskManageArgumentError

# Die vier gemessenen Bedingungen plus Bauort: jede muss in Voll- und Kurzfassung erkennbar sein.
FULL_MARKERS = ("zwei Kontextübergaben", "4000 Zeichen", "Arbeitsbaum", "3000 Zeichen", "Datei plus PR",
                "assigned_to OLLAMA", "Themenwort", "Bauort", "ellmos-system-gui")
SHORT_MARKERS = ("zwei Kontextübergaben", "4000 Zeichen", "Arbeitsbaum", "3000 Zeichen", "Datei plus PR",
                 "assigned_to OLLAMA", "Themenwort", "Bauort")


def test_rule_texts_carry_every_condition():
    for marker in FULL_MARKERS:
        assert marker in TASK_CUT_RULE, marker
    for marker in SHORT_MARKERS:
        assert marker in TASK_CUT_RULE_SHORT, marker


def test_task_divider_role_prompt_contains_the_full_rule_and_keeps_its_core():
    prompt = DEFAULT_ROLE_PROMPTS["task-divider"]
    assert TASK_CUT_RULE in prompt
    assert prompt.startswith("Du agierst als Task-Divider")
    assert "task_manage(action='decompose'" in prompt


def test_other_roles_are_not_changed():
    for role, prompt in DEFAULT_ROLE_PROMPTS.items():
        if role != "task-divider":
            assert TASK_CUT_RULE not in prompt, role


def test_worker_decompose_hints_carry_the_short_rule():
    assert TASK_CUT_RULE_SHORT in SELF_DECOMPOSE_INSTRUCTION
    assert TASK_CUT_RULE_SHORT in WorkerTaskManageArgumentError("decompose_fields").user_message
    # the parent-return hint stays focused on close_parent
    assert TASK_CUT_RULE_SHORT not in WorkerTaskManageArgumentError("decompose_parent").user_message
