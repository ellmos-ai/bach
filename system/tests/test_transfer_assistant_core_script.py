# SPDX-License-Identifier: MIT
"""Regressionstests fuer das assistant-core Transfer-Skript."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

BACH_ROOT = Path.home() / "services" / "bach"
SCRIPT = BACH_ROOT / "system" / "bin" / "transfer-assistant-core-444a1ff.sh"
RUNBOOK = BACH_ROOT / "docs" / "OPERATOR-1240-ssh-transfer.md"


@pytest.fixture
def script_path() -> Path:
    assert SCRIPT.exists(), f"Transfer-Skript nicht gefunden: {SCRIPT}"
    assert SCRIPT.stat().st_mode & 0o111, f"Transfer-Skript nicht ausfuehrbar: {SCRIPT}"
    return SCRIPT


def test_script_exists_and_executable(script_path: Path) -> None:
    assert script_path.is_file()


def test_script_syntax_ok(script_path: Path) -> None:
    result = subprocess.run(
        ["bash", "-n", str(script_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax-Fehler: {result.stderr}"


def test_script_help(script_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(script_path), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_script_dry_run_reports_missing_ssh_auth(script_path: Path) -> None:
    """Dry-run muss wegen fehlender SSH-Auth mit Exit-Code 1 abbrechen.

    Das Skript darf NICHT mit Syntax- oder Logikfehlern crashen.
    """
    result = subprocess.run(
        ["bash", str(script_path), "--dry-run"],
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr
    assert "DRY-RUN" in combined
    assert "SSH-Authentifizierung" in combined
    # Erwartet: fehlgeschlagen, weil Key nicht bei GitHub registriert
    assert result.returncode == 1


def test_script_contains_target_pin(script_path: Path) -> None:
    content = script_path.read_text()
    assert "444a1fffd56236078988d088f6237f706c3e15a9" in content
    assert "444a1ff" in content


def test_script_contains_ssh_remote(script_path: Path) -> None:
    content = script_path.read_text()
    assert "git@github.com:ellmos-ai/assistant-core.git" in content


def test_runbook_exists_and_covers_steps() -> None:
    assert RUNBOOK.exists(), f"Runbook nicht gefunden: {RUNBOOK}"
    content = RUNBOOK.read_text()
    assert "https://github.com/settings/ssh/new" in content
    assert "444a1ff" in content
    assert "--dry-run" in content
    assert "Rollback" in content


def test_deprecated_wrapper_delegates_to_new_script() -> None:
    wrapper = BACH_ROOT / "system" / "scripts" / "task1254_checkout_444a1ff.sh"
    assert wrapper.exists()
    content = wrapper.read_text()
    assert "system/bin/transfer-assistant-core-444a1ff.sh" in content
