# SPDX-License-Identifier: MIT
"""Contract tests for the 7-Step Module Transfer Contract (#3716, #1854-#1916)."""
from __future__ import annotations

from tools.module_transfer_contract import (
    CONTRACT_SCHEMA,
    OCEAN_TRANSFER_TASK_MODULES,
    REQUIRED_STEPS,
    build_policy_registry_reference_contract,
    list_all_transfer_contracts,
    validate_module_transfer_contract,
)


def test_policy_registry_reference_contract_calibrated():
    contract = build_policy_registry_reference_contract()
    assert contract["schema"] == CONTRACT_SCHEMA
    assert contract["module_id"] == "policy-registry"
    assert contract["invariants"]["no_cloud_worker_autostart"] is True
    assert contract["invariants"]["no_paid_model_fallback"] is True
    res = validate_module_transfer_contract(contract)
    assert res["valid"] is True, f"Reference contract errors: {res['errors']}"


def test_all_54_ocean_transfer_contracts_valid():
    assert len(OCEAN_TRANSFER_TASK_MODULES) == 54
    catalog = list_all_transfer_contracts()
    assert catalog["total_contracts"] == 55  # policy-registry + 54 ocean-transfer cuts
    assert catalog["all_valid"] is True
    for c in catalog["contracts"]:
        assert set(c["steps"].keys()) == set(REQUIRED_STEPS)
        assert c["invariants"]["no_cloud_worker_autostart"] is True
        assert c["invariants"]["no_paid_model_fallback"] is True


def test_contract_rejects_cloud_autostart_or_missing_deprecated_step():
    bad = build_policy_registry_reference_contract()
    bad["invariants"]["no_cloud_worker_autostart"] = False
    bad["steps"]["step_6_deprecated_registry"]["deprecated_file"] = "WRONG.md"
    res = validate_module_transfer_contract(bad)
    assert res["valid"] is False
    assert any("no_cloud_worker_autostart" in err for err in res["errors"])
    assert any("step_6_deprecated_registry" in err for err in res["errors"])
