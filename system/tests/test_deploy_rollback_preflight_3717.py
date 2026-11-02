# SPDX-License-Identifier: MIT
"""Contract tests for the Deployment Preflight & Rollback Boundary Tool (#3717)."""
from __future__ import annotations

from pathlib import Path

from tools.deploy_rollback_preflight import (
    PREFLIGHT_SCHEMA,
    run_deploy_preflight,
    validate_rollback_paths,
)


def test_rollback_boundary_blocks_taskdb_and_userdata():
    check = validate_rollback_paths(
        [
            "~/.bach/bach.db",
            "data/skill_sources.json",
            "user/profile.json",
            "../outside.txt",
            "system/gui/kit_manifest.json",
        ]
    )
    assert check["ok"] is False
    assert check["allowed_paths"] == ["system/gui/kit_manifest.json"]
    reasons = {item["path"]: item["reason"] for item in check["rejected_paths"]}
    assert reasons["~/.bach/bach.db"] == "protected_taskdb_or_user_data"
    assert reasons["data/skill_sources.json"] == "protected_taskdb_or_user_data"
    assert reasons["user/profile.json"] == "protected_taskdb_or_user_data"
    assert reasons["../outside.txt"] == "path_traversal_or_empty"


def test_deploy_preflight_receipt_and_artifact(tmp_path: Path):
    out_file = tmp_path / "preflight_receipt.json"
    receipt = run_deploy_preflight(require_clean_git=False, artifact_output=out_file)
    assert receipt["schema"] == PREFLIGHT_SCHEMA
    assert receipt["preflight_ok"] is True
    assert receipt["pin_parity"]["pins_identical"] is True
    assert receipt["rollback_boundary"]["taskdb_and_userdata_excluded"] is True
    assert receipt["scope_boundary"]["preflight_replaces_worker_acceptance"] is False
    assert receipt["scope_boundary"]["preflight_replaces_browser_acceptance"] is False
    assert receipt["scope_boundary"]["preflight_replaces_tray_acceptance"] is False
    assert out_file.is_file()
