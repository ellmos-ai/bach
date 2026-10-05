import json
from pathlib import Path

import pytest

from tools.build_bach_composition_matrix import classify, source_locators, validate_carriers


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "architecture" / "bach-parity-baseline.v1.json"
MATRIX = ROOT / "architecture" / "bach-composition-matrix.v1.json"
EVIDENCE = ROOT / "architecture" / "bach-parity-evidence.v1.json"


def test_matrix_covers_the_historic_surface_and_current_additions():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    historic = baseline["source_audit"]["registered_name_set"]
    source = matrix["source_audit"]

    assert len(historic) == 114
    assert source["historic_114_names"] == historic
    assert source["additions_since_historic_114"] == ["cloud", "mcp", "security", "theme"]
    assert len(source["registered_names"]) == 118
    assert set(historic).issubset(source["registered_names"])


def test_every_current_name_has_one_explicit_non_equivalence_classification():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows = matrix["rows"]

    assert [row["name"] for row in rows] == matrix["source_audit"]["registered_names"]
    assert len({row["name"] for row in rows}) == 118
    assert {row["class"] for row in rows} <= {"carrier", "gap", "not-adopted"}
    assert all(row["source_locator"] for row in rows)
    evidence_rows = json.loads(EVIDENCE.read_text(encoding="utf-8"))["rows"]
    assert all(row["use_case_state"] == "not-evidenced"
               for row in rows if row["class"] != "not-adopted" and row["name"] not in evidence_rows)
    assert "accepted" not in {row["use_case_state"] for row in rows}
    assert all(row.get("carrier") for row in rows if row["class"] == "carrier")
    assert all(row.get("finding") for row in rows if row["class"] == "gap")
    assert all(row.get("decision_ref") for row in rows if row["class"] == "not-adopted")


def test_builder_remains_exhaustive_for_the_recorded_current_surface():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    locators = {row["name"]: row["source_locator"] for row in matrix["rows"]}
    evidence_rows = json.loads(EVIDENCE.read_text(encoding="utf-8"))["rows"]
    rows = classify(matrix["source_audit"]["registered_names"], locators, evidence_rows)
    assert rows == matrix["rows"]


def test_catalog_validation_rejects_a_declared_carrier_missing_from_its_catalog():
    rows = [{"class": "carrier", "carrier": "missing", "carrier_locator": "module:missing"}]
    with pytest.raises(ValueError, match="missing"):
        validate_carriers(rows, modules=[], skills=[])


def test_matrix_uses_host_neutral_fingerprints_and_static_bach_sources():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    assert len(matrix["source_audit"]["bach_commit"]) == 40
    assert all("path" not in catalog for catalog in matrix["catalogues"].values())
    assert all(catalog["locator"].startswith("catalog://") for catalog in matrix["catalogues"].values())
    assert all(row["source_locator"].startswith("bach://") for row in matrix["rows"])


def test_source_locators_reject_ambiguous_or_partially_parsed_audits():
    source = {
        "diagnostics": {
            "parse_errors": [{"file": "broken.py", "error": "invalid syntax"}],
            "duplicate_profiles": [],
        },
        "handlers": [],
        "effective_aliases": {},
    }
    with pytest.raises(ValueError, match="not clean"):
        source_locators(source, "a" * 40)
