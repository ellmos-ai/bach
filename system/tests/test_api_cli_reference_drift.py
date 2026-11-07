# -*- coding: utf-8 -*-
"""Drift test for automatic API & CLI reference generation (#2556)."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "system" / "tools" / "generate_api_cli_reference.py"
MANIFEST = REPO_ROOT / "docs" / "api" / "reference-manifest.json"


def test_api_cli_reference_generator_has_no_drift():
    res = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"API/CLI reference drifted:\n{res.stderr}\n{res.stdout}"


def test_reference_manifest_counts_and_canonical_modules():
    assert MANIFEST.exists()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["cli_handler_count"] >= 80
    assert data["http_route_count"] >= 200
    assert data["canonical_module_count"] == 12  # + agents-heart (docs were stale at 11)
    assert "ocean-resources" in data["canonical_modules"]
    assert "doc-keeper" in data["canonical_modules"]
