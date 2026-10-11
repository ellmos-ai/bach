"""Pre-registered paired-run harness primitives; no provider is selected here.

This module is test-only. A future authorized run must inject an existing
backend, an exact tokenizer, contexts, and a private raw-data sink.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping


PLAN_SCHEMA = "bach.learning-reuse.paired-plan.v1"
RAW_SCHEMA = "bach.learning-reuse.raw-run.v1"
BLIND_SCHEMA = "bach.learning-reuse.blind-submission.v1"
ORDER_ALGORITHM = "sha256-rank-v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_BLIND_ID = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
_PLACEHOLDERS = {"unknown", "unresolved", "tbd", "none", "null"}


class Stage2ProtocolError(ValueError):
    """A preregistration or run input cannot be verified exactly."""


@dataclass(frozen=True, slots=True)
class PreparedRun:
    plan_sha256: str
    order_seed: int
    pair_id: str
    run_index: int
    case_id: str
    arm_code: str
    blind_submission_id: str
    prompt: str
    context: str
    model_input: str
    context_tokens: int
    input_tokens: int
    model_binding: Mapping[str, str]
    tokenizer_binding: Mapping[str, str]
    parameters: Mapping[str, Any]
    source_artifact: Mapping[str, Any] | None
    max_input_tokens: int
    max_output_tokens: int
    blind_display_seed: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _rank(seed: int, namespace: str, value: str) -> str:
    material = f"{seed}\0{namespace}\0{value}".encode("utf-8")
    return _sha256(material)


def deterministic_schedule(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    randomization = plan.get("randomization")
    case_ids = plan.get("case_ids")
    if not isinstance(randomization, Mapping) or randomization.get("algorithm") != ORDER_ALGORITHM:
        raise Stage2ProtocolError("Randomisierungsalgorithmus fehlt oder ist unbekannt")
    seed = randomization.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise Stage2ProtocolError("Vorab-Seed muss eine feste Ganzzahl sein")
    if (not isinstance(case_ids, list) or not case_ids
            or any(not isinstance(item, str) or not item for item in case_ids)
            or len(set(case_ids)) != len(case_ids)):
        raise Stage2ProtocolError("Fall-IDs müssen eindeutig und festgeschrieben sein")
    arms = plan.get("arms")
    if arms != ["A", "B"]:
        raise Stage2ProtocolError("Das feste Vergleichspanel benötigt genau A und B")

    ordered_cases = sorted(case_ids, key=lambda case_id: _rank(seed, "case", case_id))
    schedule: list[dict[str, Any]] = []
    for case_id in ordered_cases:
        ordered_arms = sorted(
            arms,
            key=lambda arm: _rank(seed, f"arm:{case_id}", arm),
        )
        for arm in ordered_arms:
            schedule.append({
                "run_index": len(schedule) + 1,
                "pair_id": f"pair-{case_id}",
                "case_id": case_id,
                "arm_code": arm,
            })
    return schedule


def _require_binding(value: Any, keys: set[str], label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise Stage2ProtocolError(f"{label}: vollständige explizite Bindung erforderlich")
    result: dict[str, str] = {}
    for key in keys:
        item = value.get(key)
        if (not isinstance(item, str) or not item.strip()
                or item.strip().casefold() in _PLACEHOLDERS):
            raise Stage2ProtocolError(f"{label}: {key} ist unbekannt; Abbruch vor Inferenz")
        result[key] = item.strip()
    return result


def _require_source_artifact(value: Any) -> dict[str, Any]:
    keys = {"candidate_revision", "candidate_digest", "target_version"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise Stage2ProtocolError("Eine geprüfte und promovierte Quellrevision fehlt")
    revision = value.get("candidate_revision")
    digest = value.get("candidate_digest")
    target_version = value.get("target_version")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise Stage2ProtocolError("Quellrevision ist ungültig")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise Stage2ProtocolError("Quelldigest ist ungültig")
    if not isinstance(target_version, str) or not target_version.strip():
        raise Stage2ProtocolError("Zielversion fehlt")
    return {
        "candidate_revision": revision,
        "candidate_digest": digest,
        "target_version": target_version.strip(),
    }


def _checked_count(token_counter: Callable[..., Any], text: str,
                   tokenizer_binding: Mapping[str, str]) -> int:
    try:
        count = token_counter(text, tokenizer_binding)
    except Exception as exc:
        raise Stage2ProtocolError("Tokenisierung konnte nicht exakt bestätigt werden") from exc
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise Stage2ProtocolError("Tokenizer lieferte keine gültige Ganzzahl")
    return count


def prepare_runs(
    plan_bytes: bytes,
    source_bytes: bytes,
    panel_bytes: bytes,
    *,
    binding_validator: Callable[[Mapping[str, str], Mapping[str, str]], bool],
    context_builder: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
    input_serializer: Callable[[str, str], str],
    token_counter: Callable[[str, Mapping[str, str]], int],
) -> tuple[PreparedRun, ...]:
    """Verify all bindings and paired token budgets before any backend call."""
    if not all(isinstance(item, bytes) for item in (plan_bytes, source_bytes, panel_bytes)):
        raise Stage2ProtocolError("Plan, Quelle und Panel müssen als unveränderte Bytes vorliegen")
    try:
        plan = json.loads(plan_bytes)
        source = json.loads(source_bytes)
        panel = json.loads(panel_bytes)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise Stage2ProtocolError("Plan, Quelle oder Panel ist kein gültiges JSON") from exc
    if not isinstance(plan, Mapping) or plan.get("schema") != PLAN_SCHEMA:
        raise Stage2ProtocolError("Unbekanntes Experimentplan-Schema")
    if not isinstance(source, Mapping) or source.get("schema") != "bach.learning-reuse.synthetic-source.v1":
        raise Stage2ProtocolError("Unerwartete Quellsitzung")
    if not isinstance(panel, Mapping) or panel.get("schema") != "bach.learning-reuse.panel.v1":
        raise Stage2ProtocolError("Unerwartetes Panel")
    if plan.get("provenance") != "synthetic" or source.get("provenance") != "synthetic" or panel.get("provenance") != "synthetic":
        raise Stage2ProtocolError("Dieses Harness akzeptiert nur die festgelegten synthetischen Quellen")

    source_binding = plan.get("source_binding")
    panel_binding = plan.get("panel_binding")
    if not isinstance(source_binding, Mapping) or set(source_binding) != {"path", "sha256"}:
        raise Stage2ProtocolError("Quellbindung fehlt")
    if not isinstance(panel_binding, Mapping) or set(panel_binding) != {"path", "sha256"}:
        raise Stage2ProtocolError("Panelbindung fehlt")
    if source_binding.get("path") != "source-session-v1.json" or panel_binding.get("path") != "panel-v1.json":
        raise Stage2ProtocolError("Quell- und Panelpfade müssen die festgeschriebenen Fixturedateien benennen")
    if source_binding.get("sha256") != _sha256(source_bytes):
        raise Stage2ProtocolError("Quellsitzung stimmt nicht mit der vorab gebundenen Version überein")
    if panel_binding.get("sha256") != _sha256(panel_bytes):
        raise Stage2ProtocolError("Panel stimmt nicht mit der vorab gebundenen Version überein")

    cases = panel.get("cases")
    if not isinstance(cases, list) or any(not isinstance(case, Mapping) for case in cases):
        raise Stage2ProtocolError("Panel enthält keine gültige Fallliste")
    case_ids = [case.get("case_id") for case in cases]
    if (not case_ids or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
            or len(set(case_ids)) != len(case_ids)
            or plan.get("case_ids") != case_ids
            or any(not isinstance(case.get("prompt"), str) or not case["prompt"] for case in cases)):
        raise Stage2ProtocolError("Festgelegte Panel-Fälle und Prompts stimmen nicht überein")
    cases_by_id = {case["case_id"]: case for case in cases}
    conditions = plan.get("conditions")
    if (not isinstance(conditions, Mapping) or set(conditions) != {"A", "B"}
            or any(not isinstance(text, str) or not text.strip() for text in conditions.values())):
        raise Stage2ProtocolError("Kontroll- und Wiederverwendungsbedingung müssen festgeschrieben sein")

    execution = plan.get("execution_binding")
    if not isinstance(execution, Mapping) or set(execution) != {"model", "tokenizer", "source_artifact"}:
        raise Stage2ProtocolError("Ausführungsbindung fehlt; vor Inferenz muss sie präregistriert sein")
    model_binding = _require_binding(
        execution.get("model"), {"provider", "model_id", "model_revision"}, "Modellrevision"
    )
    tokenizer_binding = _require_binding(
        execution.get("tokenizer"), {"tokenizer_id", "tokenizer_revision"}, "Tokenizerrevision"
    )
    if not callable(binding_validator):
        raise Stage2ProtocolError("Read-only Prüfung der Modell- und Tokenizerrevision ist erforderlich")
    try:
        binding_valid = binding_validator(dict(model_binding), dict(tokenizer_binding))
    except Exception as exc:
        raise Stage2ProtocolError("Modell- oder Tokenizerrevision konnte nicht bestätigt werden") from exc
    if binding_valid is not True:
        raise Stage2ProtocolError("Modell- oder Tokenizerrevision ist nicht exakt verfügbar")
    source_artifact = _require_source_artifact(execution.get("source_artifact"))

    budget = plan.get("budget")
    if not isinstance(budget, Mapping) or set(budget) != {
        "context_slot_tokens", "max_input_tokens", "max_output_tokens"
    }:
        raise Stage2ProtocolError("Festes Tokenbudget fehlt")
    context_budget = budget.get("context_slot_tokens")
    input_budget = budget.get("max_input_tokens")
    output_budget = budget.get("max_output_tokens")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in (context_budget, input_budget, output_budget)):
        raise Stage2ProtocolError("Tokenbudgets müssen positive feste Ganzzahlen sein")
    if context_budget > input_budget:
        raise Stage2ProtocolError("Kontextbudget überschreitet das Eingabebudget")

    parameters = plan.get("inference_parameters")
    parameter_keys = {"temperature", "top_p", "max_output_tokens", "seed"}
    if not isinstance(parameters, Mapping) or set(parameters) != parameter_keys:
        raise Stage2ProtocolError("Inferenzparameter sind nicht vollständig festgelegt")
    temperature = parameters.get("temperature")
    top_p = parameters.get("top_p")
    max_output = parameters.get("max_output_tokens")
    parameter_seed = parameters.get("seed")
    if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature) or temperature < 0):
        raise Stage2ProtocolError("Temperatur ist ungültig")
    if (isinstance(top_p, bool) or not isinstance(top_p, (int, float))
            or not math.isfinite(top_p) or not 0 < top_p <= 1):
        raise Stage2ProtocolError("top_p ist ungültig")
    if (isinstance(max_output, bool) or not isinstance(max_output, int)
            or max_output != output_budget):
        raise Stage2ProtocolError("Ausgabelimit stimmt nicht mit dem Budget überein")
    if isinstance(parameter_seed, bool) or not isinstance(parameter_seed, int):
        raise Stage2ProtocolError("Inferenzseed muss festgeschrieben sein")
    execution_policy = plan.get("execution_policy")
    if (not isinstance(execution_policy, Mapping)
            or set(execution_policy) != {"retry_count", "fallback_allowed"}
            or execution_policy.get("retry_count") != 0
            or isinstance(execution_policy.get("retry_count"), bool)
            or execution_policy.get("fallback_allowed") is not False):
        raise Stage2ProtocolError("Retries und Fallbacks müssen präregistriert ausgeschlossen sein")

    randomization = plan.get("randomization")
    if not isinstance(randomization, Mapping):
        raise Stage2ProtocolError("Vorab-Randomisierung fehlt")
    blind_seed = randomization.get("blind_display_seed")
    if isinstance(blind_seed, bool) or not isinstance(blind_seed, int):
        raise Stage2ProtocolError("Seed für die verblindete Anzeige fehlt")
    schedule = deterministic_schedule(plan)
    schedule_digest = _sha256(_canonical_json_bytes(schedule))
    if randomization.get("run_order_sha256") != schedule_digest:
        raise Stage2ProtocolError("Vorab-Runreihenfolge stimmt nicht mit Seed und Algorithmus überein")

    if not callable(context_builder) or not callable(input_serializer) or not callable(token_counter):
        raise Stage2ProtocolError("Kontext, Eingabeserialisierung und Tokenizer müssen explizit injiziert sein")

    pair_input_counts: dict[str, list[int]] = {}
    prepared: list[PreparedRun] = []
    ids: set[str] = set()
    plan_digest = _sha256(plan_bytes)
    for item in schedule:
        case_id = item["case_id"]
        arm = item["arm_code"]
        case = cases_by_id[case_id]
        try:
            context_spec = context_builder(case, arm)
        except Exception as exc:
            raise Stage2ProtocolError("Kontext konnte vorab nicht gebunden werden") from exc
        if not isinstance(context_spec, Mapping) or set(context_spec) != {"text", "source_artifact"}:
            raise Stage2ProtocolError("Kontext muss Text und Quellartefakt getrennt liefern")
        context = context_spec.get("text")
        if not isinstance(context, str) or not context.strip() or "\x00" in context:
            raise Stage2ProtocolError("Kontext ist leer oder ungültig")
        actual_artifact = context_spec.get("source_artifact")
        expected_artifact = source_artifact if arm == "B" else None
        if actual_artifact != expected_artifact:
            raise Stage2ProtocolError("Kontextquelle stimmt nicht mit der vorab gebundenen Bedingung überein")
        context_tokens = _checked_count(token_counter, context, tokenizer_binding)
        if context_tokens != context_budget:
            raise Stage2ProtocolError("Kontextslot hat nicht die präregistrierte Tokenzahl")
        prompt = case["prompt"]
        try:
            model_input = input_serializer(prompt, context)
        except Exception as exc:
            raise Stage2ProtocolError("Modelleingabe konnte nicht vorab serialisiert werden") from exc
        if not isinstance(model_input, str) or not model_input:
            raise Stage2ProtocolError("Serialisierte Modelleingabe ist ungültig")
        input_tokens = _checked_count(token_counter, model_input, tokenizer_binding)
        if input_tokens > input_budget:
            raise Stage2ProtocolError("Modelleingabe überschreitet das präregistrierte Budget")
        pair_input_counts.setdefault(item["pair_id"], []).append(input_tokens)
        blind_id = secrets.token_urlsafe(24)
        while blind_id in ids or not _BLIND_ID.fullmatch(blind_id):
            blind_id = secrets.token_urlsafe(24)
        ids.add(blind_id)
        prepared.append(PreparedRun(
            plan_sha256=plan_digest,
            order_seed=randomization["seed"],
            pair_id=item["pair_id"],
            run_index=item["run_index"],
            case_id=case_id,
            arm_code=arm,
            blind_submission_id=blind_id,
            prompt=prompt,
            context=context,
            model_input=model_input,
            context_tokens=context_tokens,
            input_tokens=input_tokens,
            model_binding=model_binding,
            tokenizer_binding=tokenizer_binding,
            parameters=dict(parameters),
            source_artifact=dict(actual_artifact) if actual_artifact is not None else None,
            max_input_tokens=input_budget,
            max_output_tokens=output_budget,
            blind_display_seed=blind_seed,
        ))

    if len(prepared) != len(case_ids) * 2 or any(
        len(counts) != 2 or counts[0] != counts[1]
        for counts in pair_input_counts.values()
    ):
        raise Stage2ProtocolError("Paarzahl oder gleiche Eingabetokenzahl ist nicht erfüllt")
    return tuple(prepared)


def execute_runs(
    prepared_runs: tuple[PreparedRun, ...],
    *,
    backend: Callable[..., Any],
    private_sink: Callable[[Mapping[str, Any], str | None], None],
    token_counter: Callable[[str, Mapping[str, str]], int],
) -> dict[str, Any]:
    """Attempt each prepared run once; raw data only goes to the injected sink."""
    if not prepared_runs or not callable(backend) or not callable(private_sink) or not callable(token_counter):
        raise Stage2ProtocolError("Bestehendes Backend, privater Rohdatenspeicher und Tokenizer sind Pflicht")
    if len(prepared_runs) != 16 or [run.run_index for run in prepared_runs] != list(range(1, 17)):
        raise Stage2ProtocolError("Der vollständige präregistrierte 16-Lauf-Satz ist erforderlich")
    if len({run.plan_sha256 for run in prepared_runs}) != 1 or len(
        {run.order_seed for run in prepared_runs}
    ) != 1:
        raise Stage2ProtocolError("Alle Läufe müssen denselben präregistrierten Plan und Reihenfolgen-Seed binden")
    pairs: dict[str, list[PreparedRun]] = {}
    for run in prepared_runs:
        pairs.setdefault(run.pair_id, []).append(run)
    if len(pairs) != 8 or any(
        len(pair) != 2
        or {run.arm_code for run in pair} != {"A", "B"}
        or len({run.case_id for run in pair}) != 1
        or len({run.input_tokens for run in pair}) != 1
        or len({run.context_tokens for run in pair}) != 1
        or len({run.plan_sha256 for run in pair}) != 1
        or len({run.order_seed for run in pair}) != 1
        for pair in pairs.values()
    ):
        raise Stage2ProtocolError("Vollständige Paare mit gleicher Tokenzahl sind erforderlich")
    if len({run.blind_submission_id for run in prepared_runs}) != 16:
        raise Stage2ProtocolError("Verblindete Einreichungs-IDs müssen eindeutig sein")
    first = prepared_runs[0]
    if any(
        run.model_binding != first.model_binding
        or run.tokenizer_binding != first.tokenizer_binding
        or dict(run.parameters) != dict(first.parameters)
        or run.blind_display_seed != first.blind_display_seed
        or run.pair_id != f"pair-{run.case_id}"
        for run in prepared_runs
    ):
        raise Stage2ProtocolError("Modell-, Tokenizer- oder Parameterbindung weicht innerhalb des Plans ab")

    blind_submissions: list[dict[str, str]] = []
    for run in prepared_runs:
        started = time.monotonic()
        raw_output: str | None = None
        output_tokens: int | None = None
        outcome = "success"
        try:
            value = backend(
                dict(run.model_binding),
                dict(run.tokenizer_binding),
                run.model_input,
                dict(run.parameters),
            )
        except TimeoutError:
            outcome = "timeout"
        except Exception:
            outcome = "provider_error"
        else:
            if not isinstance(value, str):
                outcome = "provider_error"
            else:
                raw_output = value
                try:
                    output_tokens = _checked_count(token_counter, raw_output, run.tokenizer_binding)
                except Stage2ProtocolError:
                    outcome = "provider_error"
                else:
                    if not raw_output.strip():
                        outcome = "empty_response"
                    elif output_tokens > run.max_output_tokens:
                        outcome = "budget_violation"

        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        record = {
            "schema": RAW_SCHEMA,
            "plan_sha256": run.plan_sha256,
            "pair_id": run.pair_id,
            "run_index": run.run_index,
            "order_seed": run.order_seed,
            "case_id": run.case_id,
            "blind_submission_id": run.blind_submission_id,
            "arm_code": run.arm_code,
            "model": dict(run.model_binding),
            "tokenizer": dict(run.tokenizer_binding),
            "parameters": dict(run.parameters),
            "prompt_sha256": _sha256(run.prompt.encode("utf-8")),
            "context_sha256": _sha256(run.context.encode("utf-8")),
            "context_tokens": run.context_tokens,
            "input_tokens": run.input_tokens,
            "outcome": outcome,
            "elapsed_ms": elapsed_ms,
            "retry_count": 0,
            "output_tokens": output_tokens,
            "raw_output_sha256": _sha256(raw_output.encode("utf-8")) if raw_output is not None else None,
            "source_artifact": dict(run.source_artifact) if run.source_artifact is not None else None,
        }
        # A sink error aborts without replay. Private run/model/condition
        # metadata go only to the sink; blinded answer text is returned for rating.
        private_sink(record, raw_output)
        blind_submissions.append({
            "schema": BLIND_SCHEMA,
            "case_id": run.case_id,
            "blind_submission_id": run.blind_submission_id,
            "prompt": run.prompt,
            "response": raw_output if outcome == "success" else "",
        })

    blind_submissions.sort(
        key=lambda item: _rank(prepared_runs[0].blind_display_seed, "blind", item["blind_submission_id"])
    )
    return {"blind_submissions": blind_submissions, "attempt_count": len(prepared_runs)}
