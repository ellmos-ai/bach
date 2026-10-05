import copy
import json
from pathlib import Path

from tools.check_parity_evidence import RUN_COMMAND, referenced_tests, row_state, validate

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads((ROOT / "architecture" / "bach-parity-evidence.v1.json").read_text(encoding="utf-8"))
MATRIX = json.loads((ROOT / "architecture" / "bach-composition-matrix.v1.json").read_text(encoding="utf-8"))


def _problems(evidence=None, matrix=None, ci_text=None):
    return validate(evidence or EVIDENCE, matrix or MATRIX, ROOT, ci_text)


def _matrix_row(matrix, name):
    return next(row for row in matrix["rows"] if row["name"] == name)


def test_recorded_evidence_and_matrix_pass_the_gate():
    assert _problems() == []


def test_ci_runs_the_referenced_tests_without_skips():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert RUN_COMMAND in ci and "REQUIRE_PARITY_EVIDENCE" in ci
    assert _problems(ci_text="jobs: {}") == ["CI must run the parity-evidence job with REQUIRE_PARITY_EVIDENCE"]
    assert referenced_tests(EVIDENCE)


def test_matrix_state_cannot_claim_evidence_without_the_register():
    matrix = copy.deepcopy(MATRIX)
    _matrix_row(matrix, "snapshot")["use_case_state"] = "evidenced"
    assert any("snapshot" in problem and "without an entry" in problem for problem in _problems(matrix=matrix))


def test_historic_accepted_is_not_a_state():
    matrix = copy.deepcopy(MATRIX)
    _matrix_row(matrix, "backup")["use_case_state"] = "accepted"
    assert any("unknown use_case_state 'accepted'" in problem for problem in _problems(matrix=matrix))

    evidence = copy.deepcopy(EVIDENCE)
    evidence["rows"]["dbsync"]["use_cases"][0]["state"] = "accepted"
    assert any("not an evidence state" in problem for problem in _problems(evidence=evidence))


def test_missing_test_or_baseline_reference_fails_closed():
    evidence = copy.deepcopy(EVIDENCE)
    evidence["rows"]["dbsync"]["use_cases"][0]["test"] = "tests/test_bach_k9_dbsync_parity.py::test_nope"
    assert any("test function 'test_nope' missing" in problem for problem in _problems(evidence=evidence))

    evidence = copy.deepcopy(EVIDENCE)
    evidence["rows"]["dbsync"]["use_cases"][0]["fixture"] = "architecture/bach-parity-baseline.v1.json"
    assert any("baseline is not evidence" in problem for problem in _problems(evidence=evidence))


def test_row_is_only_fully_evidenced_when_every_operation_is_covered():
    row = copy.deepcopy(EVIDENCE["rows"]["dbsync"])
    assert row_state(row) == "partially-evidenced"
    row["use_cases"] = [dict(case, state="divergent") for case in row["use_cases"]]
    assert row_state(row) == "not-evidenced"
    row = copy.deepcopy(EVIDENCE["rows"]["dbsync"])
    row["operations_in_scope"] = ["push", "pull"]
    assert row_state(row) == "evidenced"


def test_matrix_state_must_match_the_register():
    matrix = copy.deepcopy(MATRIX)
    _matrix_row(matrix, "dbsync")["use_case_state"] = "evidenced"
    assert any("dbsync: matrix use_case_state" in problem for problem in _problems(matrix=matrix))
