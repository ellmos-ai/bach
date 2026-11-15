# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for foerderplaner_provider module."""
import importlib.util
import json
import os
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from foerderplaner_provider import FoerderplanerProvider, probe_foerderplaner_provider

ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_FOERDERPLANER"
def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "foerderplaner_provider"
    assert data["selfcontained"] is True
    # Validate version
    assert data["version"] == "0.2.0"
    # Validate boundaries
    assert data["boundaries"]["data"] == "user-local"
    assert data["boundaries"]["network"] == "none"
    assert set(data["boundaries"]["platforms"]) == {"windows", "macos", "linux"}
    # Validate consumers
    consumers = {c["name"]: c["minimum_version"] for c in data["consumers"]}
    assert consumers.get("BACH") == "3.15.0"
    assert consumers.get("Ocean") == "1.0.0"
def test_foerderplaner_provider_probe():
    prov = probe_foerderplaner_provider()
    assert isinstance(prov, FoerderplanerProvider)
    # The provider name should be either the external module name or the internal legacy name
    assert prov.name in ("foerderplaner", "foerderplaner-legacy")
def test_probe_external_switch():
    # Test that the rollback environment variable switches to internal/legacy mode
    original = os.environ.get(ROLLBACK_ENV_VAR)
    try:
        os.environ[ROLLBACK_ENV_VAR] = "0"
        prov = probe_foerderplaner_provider()
        assert prov.external is False
        assert prov.name == "foerderplaner-legacy"
    finally:
        if original is None:
            os.environ.pop(ROLLBACK_ENV_VAR, None)
        else:
            os.environ[ROLLBACK_ENV_VAR] = original
def test_probe_external_present():
    # If the external module is importable, probe should return external provider
    spec = importlib.util.find_spec("foerderplaner")
    if spec is not None:
        prov = probe_foerderplaner_provider()
        assert prov.external is True
        assert prov.name == "foerderplaner"
    else:
        # If not available, internal/legacy mode should be used
        prov = probe_foerderplaner_provider()
        assert prov.external is False
        assert prov.name == "foerderplaner-legacy"