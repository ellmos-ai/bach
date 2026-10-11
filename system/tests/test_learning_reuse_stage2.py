"""Contract tests for Stage 2 scheduling and privacy boundaries.

The injected test backend is synthetic. These tests do not call a model or
measure answer quality.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from learning_reuse_stage2 import (
    BLIND_SCHEMA,
    Stage2ProtocolError,
    deterministic_schedule,
    execute_runs,
    prepare_runs,
)


FIXTURES = Path(__file__).parent / "fixtures" / "learning_reuse"
BLIND_KEYS = {"schema", "case_id", "blind_submission_id", "prompt", "response"}
RAW_KEYS = {
    "schema", "plan_sha256", "pair_id", "run_index", "order_seed", "case_id",
    "blind_submission_id", "arm_code", "model", "tokenizer", "parameters",
    "prompt_sha256", "context_sha256", "context_tokens", "input_tokens", "outcome",
    "elapsed_ms", "retry_count", "output_tokens", "raw_output_sha256", "source_artifact",
}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _ready_plan_bytes(**overrides) -> bytes:
    plan = json.loads((FIXTURES / "paired-experiment-plan-v1.json").read_text(encoding="utf-8"))
    plan["execution_binding"] = {
        "model": {
            "provider": "synthetic-test-backend",
            "model_id": "synthetic-model-only",
            "model_revision": "synthetic-model-revision-v1",
        },
        "tokenizer": {
            "tokenizer_id": "synthetic-tokenizer-only",
            "tokenizer_revision": "synthetic-tokenizer-revision-v1",
        },
        "source_artifact": {
            "candidate_revision": 1,
            "candidate_digest": "a" * 64,
            "target_version": "synthetic-lessons-v1",
        },
    }
    for key, value in overrides.items():
        plan[key] = value
    return _json_bytes(plan)


def _token_count(text: str, _tokenizer: dict[str, str]) -> int:
    return len(text.split())


def _validate_synthetic_bindings(model: dict[str, str], tokenizer: dict[str, str]) -> bool:
    return (
        model == {
            "provider": "synthetic-test-backend",
            "model_id": "synthetic-model-only",
            "model_revision": "synthetic-model-revision-v1",
        }
        and tokenizer == {
            "tokenizer_id": "synthetic-tokenizer-only",
            "tokenizer_revision": "synthetic-tokenizer-revision-v1",
        }
    )


def _context_builder(plan_bytes: bytes):
    plan = json.loads(plan_bytes)
    artifact = plan["execution_binding"]["source_artifact"]

    def build(_case: dict, arm: str) -> dict:
        prefix = "neutral" if arm == "A" else "lesson"
        return {
            "text": prefix + " " + "x " * 127,
            "source_artifact": None if arm == "A" else artifact,
        }

    return build


def _prepare(plan_bytes: bytes | None = None, *, context_builder=None, binding_validator=None):
    plan_bytes = plan_bytes or _ready_plan_bytes()
    context_builder = context_builder or _context_builder(plan_bytes)
    if binding_validator is None:
        binding_validator = _validate_synthetic_bindings
    return prepare_runs(
        plan_bytes,
        (FIXTURES / "source-session-v1.json").read_bytes(),
        (FIXTURES / "panel-v1.json").read_bytes(),
        binding_validator=binding_validator,
        context_builder=context_builder,
        input_serializer=lambda prompt, context: prompt + "\n" + context,
        token_counter=_token_count,
    )


def test_fixed_plan_binds_sources_budget_and_preseeded_schedule():
    plan = json.loads((FIXTURES / "paired-experiment-plan-v1.json").read_text(encoding="utf-8"))
    source_bytes = (FIXTURES / "source-session-v1.json").read_bytes()
    panel_bytes = (FIXTURES / "panel-v1.json").read_bytes()
    assert plan["source_binding"]["sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert plan["panel_binding"]["sha256"] == hashlib.sha256(panel_bytes).hexdigest()
    assert plan["budget"] == {
        "context_slot_tokens": 128,
        "max_input_tokens": 512,
        "max_output_tokens": 512,
    }
    assert plan["execution_binding"] == {"model": None, "tokenizer": None, "source_artifact": None}
    assert plan["execution_policy"] == {"retry_count": 0, "fallback_allowed": False}
    schedule = deterministic_schedule(plan)
    encoded = json.dumps(schedule, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == plan["randomization"]["run_order_sha256"]
    assert len(schedule) == 16
    assert {item["arm_code"] for item in schedule} == {"A", "B"}
    assert all(sum(item["case_id"] == case_id for item in schedule) == 2
               for case_id in plan["case_ids"])


def test_unknown_model_or_tokenizer_revision_stops_before_context_preparation():
    for binding, field in [
        ("model", "model_revision"),
        ("tokenizer", "tokenizer_revision"),
    ]:
        called = []
        original = json.loads(_ready_plan_bytes())
        original["execution_binding"][binding][field] = "unregistered-build-2026-10"
        validation_calls = []

        def reject_unregistered(model, tokenizer):
            validation_calls.append((model, tokenizer))
            return _validate_synthetic_bindings(model, tokenizer)

        with pytest.raises(Stage2ProtocolError, match="nicht exakt verfügbar"):
            _prepare(
                _json_bytes(original),
                context_builder=lambda *_args: called.append(True),
                binding_validator=reject_unregistered,
            )

        assert validation_calls
        assert called == []


def test_binding_validator_errors_fail_closed_before_context_preparation():
    context_calls = []

    def failed_registry_read(_model, _tokenizer):
        raise OSError("synthetic registry read failure")

    with pytest.raises(Stage2ProtocolError, match="konnte nicht bestätigt werden"):
        _prepare(
            context_builder=lambda *_args: context_calls.append(True),
            binding_validator=failed_registry_read,
        )

    assert context_calls == []


def test_unresolved_preregistered_plan_is_not_runnable():
    plan_bytes = (FIXTURES / "paired-experiment-plan-v1.json").read_bytes()
    with pytest.raises(Stage2ProtocolError, match="Modellrevision"):
        _prepare(plan_bytes, context_builder=lambda *_args: pytest.fail("Kontext darf nicht gelesen werden"))


def test_pair_token_mismatch_fails_before_any_backend_can_be_invoked():
    plan_bytes = _ready_plan_bytes()
    base = _context_builder(plan_bytes)

    def unequal(case, arm):
        result = base(case, arm)
        if arm == "B":
            result["text"] = "lesson " + "x " * 126
        return result

    with pytest.raises(Stage2ProtocolError, match="präregistrierte Tokenzahl"):
        _prepare(plan_bytes, context_builder=unequal)


def test_injected_backend_runs_each_arm_once_and_returns_blind_allowlist_only():
    prepared = _prepare()
    calls = []
    private_rows = []

    def backend(model, tokenizer, model_input, parameters):
        calls.append((model, tokenizer, model_input, parameters))
        if len(calls) == 1:
            raise TimeoutError("synthetic timeout")
        if len(calls) == 2:
            raise RuntimeError("synthetic provider failure")
        return "Synthetische Testantwort mit Beleg."

    result = execute_runs(
        prepared,
        backend=backend,
        private_sink=lambda row, output: private_rows.append((dict(row), output)),
        token_counter=_token_count,
    )

    assert len(calls) == len(prepared) == 16
    assert result["attempt_count"] == 16
    assert len(private_rows) == len(result["blind_submissions"]) == 16
    assert {tuple(sorted(row)) for row, _ in private_rows} == {tuple(sorted(RAW_KEYS))}
    assert sum(row["outcome"] == "timeout" for row, _ in private_rows) == 1
    assert sum(row["outcome"] == "provider_error" for row, _ in private_rows) == 1
    assert all(row["retry_count"] == 0 for row, _ in private_rows)
    assert all(row["plan_sha256"] == prepared[0].plan_sha256 for row, _ in private_rows)
    assert all(row["input_tokens"] == 128 + len(row_prompt.split())
               for (row, _), row_prompt in zip(private_rows, [run.prompt for run in prepared]))
    assert all(set(submission) == BLIND_KEYS for submission in result["blind_submissions"])
    assert all(submission["schema"] == BLIND_SCHEMA for submission in result["blind_submissions"])
    assert not {"arm_code", "model", "tokenizer", "provider", "source_artifact", "run_index"}.intersection(
        set().union(*(submission.keys() for submission in result["blind_submissions"]))
    )
    outcomes_by_id = {row["blind_submission_id"]: row["outcome"] for row, _ in private_rows}
    assert all(
        submission["response"] == "" if outcomes_by_id[submission["blind_submission_id"]] != "success"
        else submission["response"] == "Synthetische Testantwort mit Beleg."
        for submission in result["blind_submissions"]
    )


def test_private_sink_failure_aborts_without_replaying_backend():
    prepared = _prepare()
    calls = []

    def backend(*_args):
        calls.append(1)
        return "synthetic"

    def rejecting_sink(_row, _output):
        raise OSError("synthetic private sink failure")

    with pytest.raises(OSError, match="private sink"):
        execute_runs(prepared, backend=backend, private_sink=rejecting_sink, token_counter=_token_count)
    assert len(calls) == 1


def test_partial_pairs_are_rejected_before_backend_invocation():
    prepared = _prepare()
    calls = []
    with pytest.raises(Stage2ProtocolError, match="16-Lauf-Satz"):
        execute_runs(
            prepared[:1],
            backend=lambda *_args: calls.append(True),
            private_sink=lambda *_args: None,
            token_counter=_token_count,
        )
    assert calls == []


def test_mixed_plan_or_order_seed_is_rejected_before_backend_invocation():
    prepared = _prepare()
    pair_ids = sorted({run.pair_id for run in prepared})

    for field, other_value in (("plan_sha256", "a" * 64), ("order_seed", 2003)):
        mixed = tuple(
            replace(run, **{field: other_value}) if run.pair_id in set(pair_ids[4:]) else run
            for run in prepared
        )
        calls = []
        with pytest.raises(Stage2ProtocolError, match="präregistrierten Plan und Reihenfolgen-Seed"):
            execute_runs(
                mixed,
                backend=lambda *_args: calls.append(True),
                private_sink=lambda *_args: None,
                token_counter=_token_count,
            )
        assert calls == []
