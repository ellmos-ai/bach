"""Old/new parity test for the K9 dbsync push/pull use case (D-20260906-003).

The same anonymized fixture runs through three implementations, each in its own
process (see tools/parity_probes/bach_k9_dbsync_probe.py):

* BACH native ProSync (old),
* BACH through its sqlite-transit-sync provider seam (new, BACH side),
* sqlite-transit-sync used directly (new, OCEAN side).

Requires BACH_PARITY_ROOT and TRANSIT_SYNC_ROOT checked out at the pinned
commits of architecture/bach-parity-evidence.v1.json.  Without them the test
skips, unless REQUIRE_PARITY_EVIDENCE=1 (set by the parity-evidence CI job),
which turns a skip into a failure so that evidence can never rest on a skip.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "parity_probes" / "bach_k9_dbsync_probe.py"
EVIDENCE = json.loads((ROOT / "architecture" / "bach-parity-evidence.v1.json").read_text(encoding="utf-8"))
PINS = EVIDENCE["rows"]["dbsync"]["use_cases"][0]["pins"]
MODES = ("bach-legacy", "bach-module", "ocean-module")


def _root(variable: str, commit: str) -> Path:
    value = os.environ.get(variable)
    if not value:
        if os.environ.get("REQUIRE_PARITY_EVIDENCE") == "1":
            pytest.fail(f"{variable} is required for parity evidence")
        pytest.skip(f"set {variable} to run the K9 dbsync parity test")
    root = Path(value).resolve()
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    assert head == commit, f"{variable} must be at {commit}, got {head}"
    return root


@pytest.fixture(scope="module")
def roots() -> tuple[Path, Path]:
    return _root("BACH_PARITY_ROOT", PINS["bach_commit"]), _root("TRANSIT_SYNC_ROOT", PINS["carrier_commit"])


def _probe(mode: str, fixture: str, roots: tuple[Path, Path], use_case: str = "push-pull") -> dict:
    with tempfile.TemporaryDirectory(prefix="k9-parity-") as work:
        completed = subprocess.run(
            [sys.executable, str(PROBE), "--mode", mode, "--bach-root", str(roots[0]),
             "--transit-root", str(roots[1]), "--fixture", str(ROOT / fixture),
             "--workdir", str(Path(work) / "run"), "--use-case", use_case],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _observed(result: dict) -> dict:
    return {key: value for key, value in result.items() if key not in ("mode", "provider")}


def test_push_pull_is_identical_in_bach_legacy_bach_module_and_ocean(roots):
    results = {mode: _probe(mode, "tests/fixtures/k9_data", roots) for mode in MODES}
    expected = json.loads((ROOT / "tests/fixtures/k9_data/expected.json").read_text(encoding="utf-8"))

    assert results["bach-legacy"]["provider"] == "bach-legacy"
    assert results["bach-module"]["provider"] == "sqlite-transit-sync"
    assert _observed(results["bach-legacy"]) == _observed(results["bach-module"]) == _observed(results["ocean-module"])

    observed = _observed(results["ocean-module"])
    assert observed["push_ok"] and observed["pull_ok"]
    assert observed["target_items"] == expected["target_items"]
    assert len(observed["target_secrets"]) == expected["target_secret_rows"]
    assert observed["published_secret_rows"] == expected["source_snapshot_secret_rows"]
    assert observed["first_pull_changed"] == expected["merge_inserted"] + expected["merge_updated"]
    assert observed["repeat_pull_changed"] == 0


def test_pull_with_newer_local_rows_is_identical_after_bach_row_merge_fix(roots):
    results = {mode: _probe(mode, "tests/fixtures/k9_data_newer_local", roots) for mode in MODES}

    assert results["bach-legacy"]["provider"] == "bach-legacy"
    assert results["bach-module"]["provider"] == "sqlite-transit-sync"
    assert _observed(results["bach-legacy"]) == _observed(results["bach-module"]) == _observed(results["ocean-module"])
    # Before BACH e619345 native ProSync dropped the two newer foreign rows here.
    assert results["bach-legacy"]["target_items"] == [
        ["shared", "source-newer"], ["source-only", "source-value"], ["target-only", "target-value"]]
    assert results["bach-legacy"]["first_pull_changed"] == 2
    assert results["bach-legacy"]["repeat_pull_changed"] == 0


def test_sync_roundtrip_is_identical_in_bach_legacy_bach_module_and_ocean(roots):
    results = {mode: _probe(mode, "tests/fixtures/k9_data", roots, "sync-roundtrip") for mode in MODES}

    assert results["bach-legacy"]["provider"] == "bach-legacy"
    assert results["bach-module"]["provider"] == "sqlite-transit-sync"
    assert _observed(results["bach-legacy"]) == _observed(results["bach-module"]) == _observed(results["ocean-module"])

    merged = [["shared", "source-newer"], ["source-only", "source-value"], ["target-only", "target-value"]]
    observed = _observed(results["ocean-module"])
    assert observed["target_items"] == observed["target_snapshot_items"] == observed["source_items"] == merged
    assert observed["source_snapshot_secret_rows"] == observed["target_snapshot_secret_rows"] == 0
    assert observed["target_secrets"] == [["local-placeholder", "target-local-placeholder"]]
    assert observed["source_secrets"] == [["placeholder", "synthetic-secret-placeholder"]]
