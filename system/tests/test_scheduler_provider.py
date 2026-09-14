"""Focused tests for the independent scheduler import seam."""
from __future__ import annotations

from unittest.mock import patch

from hub.scheduler_provider import probe_scheduler_provider


def test_probe_prefers_external_module_when_importable() -> None:
    with patch("hub.scheduler_provider.importlib.util.find_spec", return_value=object()):
        provider = probe_scheduler_provider()

    assert provider.name == "ellmos-scheduler"
    assert provider.external is True
    assert provider.module == "ellmos_scheduler"


def test_probe_falls_back_to_legacy_without_claiming_external_runtime() -> None:
    with patch("hub.scheduler_provider.importlib.util.find_spec", return_value=None):
        provider = probe_scheduler_provider()

    assert provider.name == "bach-legacy"
    assert provider.external is False
    assert provider.module is None
