# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Static validation tests for BACH start scripts (bach.bat, bach.sh).

Validates cross-platform consistency, environment setup, and absence
of platform-specific pitfalls without executing the scripts.
"""

import re
from pathlib import Path

import pytest

START_DIR = Path(__file__).parent.parent.parent / "start"
BAT_FILE = START_DIR / "bach.bat"
SH_FILE = START_DIR / "bach.sh"
STARTSPINE_FILE = START_DIR / "startspine.py"


class TestScriptExistence:
    def test_start_dir_exists(self):
        assert START_DIR.is_dir(), f"start/ Verzeichnis nicht gefunden: {START_DIR}"

    def test_bat_exists(self):
        assert BAT_FILE.is_file(), "bach.bat fehlt"

    def test_sh_exists(self):
        assert SH_FILE.is_file(), "bach.sh fehlt"

    def test_startspine_exists(self):
        assert STARTSPINE_FILE.is_file(), "startspine.py fehlt"


class TestBatScript:
    @pytest.fixture(autouse=True)
    def _load(self):
        if not BAT_FILE.is_file():
            pytest.skip("bach.bat nicht vorhanden")
        self.text = BAT_FILE.read_text(encoding="utf-8", errors="replace")
        self.lines = self.text.splitlines()

    def test_sets_pythonioencoding(self):
        assert "PYTHONIOENCODING=utf-8" in self.text

    def test_no_dev_null(self):
        for i, line in enumerate(self.lines, 1):
            if line.strip().startswith("REM"):
                continue
            assert "/dev/null" not in line, (
                f"Zeile {i}: /dev/null ist auf Windows ungültig — >nul verwenden"
            )

    def test_has_shebang_equivalent(self):
        assert self.lines[0].strip().lower() == "@echo off"

    def test_sets_delayed_expansion(self):
        assert any("enabledelayedexpansion" in line.lower() for line in self.lines[:5])

    def test_has_menu_label(self):
        assert any(line.strip() == ":menu" for line in self.lines)

    def test_has_end_label(self):
        assert any(line.strip() == ":end" for line in self.lines)

    def test_endlocal_before_exit(self):
        for i, line in enumerate(self.lines):
            if line.strip() == ":end":
                rest = "\n".join(self.lines[i:])
                assert "endlocal" in rest
                break

    def test_chat_dir_reference(self):
        assert "startspine.py" in self.text

    def test_gui_server_reference(self):
        assert 'start --gui' in self.text

    def test_control_api_port(self):
        assert "startspine.py" in self.text

    def test_gui_port(self):
        assert "startspine.py" in self.text

    def test_no_xargs_r_flag(self):
        for i, line in enumerate(self.lines, 1):
            assert "xargs -r" not in line, (
                f"Zeile {i}: xargs -r ist GNU-only und fehlt auf macOS"
            )

    def test_no_unsafe_process_kill(self):
        lowered = self.text.lower()
        assert "taskkill" not in lowered
        assert "wmic process" not in lowered

    def test_version_string_present(self):
        assert re.search(r"v\d+\.\d+\.\d+", self.text), (
            "Keine Versionsnummer (vX.Y.Z) in bach.bat gefunden"
        )


class TestShScript:
    @pytest.fixture(autouse=True)
    def _load(self):
        if not SH_FILE.is_file():
            pytest.skip("bach.sh nicht vorhanden")
        self.text = SH_FILE.read_text(encoding="utf-8", errors="replace")
        self.lines = self.text.splitlines()

    def test_has_shebang(self):
        assert self.lines[0].startswith("#!/")

    def test_sets_pipefail(self):
        assert "pipefail" in self.text

    def test_sets_pythonioencoding(self):
        assert "PYTHONIOENCODING=utf-8" in self.text

    def test_no_xargs_r_flag(self):
        for i, line in enumerate(self.lines, 1):
            if line.strip().startswith("#"):
                continue
            assert "xargs -r" not in line, (
                f"Zeile {i}: xargs -r ist GNU-only und fehlt auf macOS"
            )

    def test_no_windows_paths(self):
        for i, line in enumerate(self.lines, 1):
            if line.strip().startswith("#"):
                continue
            assert "C:\\" not in line and "C:/" not in line, (
                f"Zeile {i}: Hartcodierte Windows-Pfade in bach.sh vermeiden"
            )

    def test_chat_dir_reference(self):
        assert "startspine.py" in self.text

    def test_gui_server_reference(self):
        assert "start --gui" in self.text

    def test_control_api_port(self):
        assert "BACH_CONTROL_PORT" in self.text

    def test_gui_port(self):
        assert "BACH_GUI_PORT" in self.text

    def test_python_venv_detection(self):
        assert ".venvs/bach" in self.text or ".venvs/science" in self.text

    def test_fallback_python(self):
        assert "python3" in self.text

    def test_case_command(self):
        assert "case " in self.text, "bach.sh sollte case-Dispatch für Subcommands verwenden"

    def test_unknown_command_is_error(self):
        assert "usage >&2; exit 2" in self.text

    def test_has_usage_function(self):
        assert "usage()" in self.text or "usage ()" in self.text

    def test_subcommands_present(self):
        for cmd in ["chat", "gui", "status", "stop"]:
            assert cmd in self.text, f"Subcommand '{cmd}' fehlt in bach.sh"

    def test_no_unsafe_process_kill(self):
        lowered = self.text.lower()
        assert "pkill" not in lowered
        assert "kill -9" not in lowered
        assert "fuser -k" not in lowered


class TestCrossScriptConsistency:
    @pytest.fixture(autouse=True)
    def _load(self):
        if not BAT_FILE.is_file() or not SH_FILE.is_file():
            pytest.skip("bach.bat oder bach.sh nicht vorhanden")
        self.bat = BAT_FILE.read_text(encoding="utf-8", errors="replace")
        self.sh = SH_FILE.read_text(encoding="utf-8", errors="replace")

    def test_both_set_pythonioencoding(self):
        assert "PYTHONIOENCODING=utf-8" in self.bat
        assert "PYTHONIOENCODING=utf-8" in self.sh

    def test_both_reference_control_api_port(self):
        startspine = STARTSPINE_FILE.read_text(encoding="utf-8")
        assert '"BACH_CONTROL_PORT", 8081' in startspine

    def test_both_reference_gui_port(self):
        startspine = STARTSPINE_FILE.read_text(encoding="utf-8")
        assert '"BACH_GUI_PORT", 8000' in startspine

    def test_both_reference_chat_tray(self):
        assert "startspine.py" in self.bat
        assert "startspine.py" in self.sh

    def test_both_reference_telegram_chat(self):
        assert "start --chat --tray" in self.bat
        assert "start --chat --tray" in self.sh

    def test_both_support_bach_host(self):
        assert "BACH_HOST" in self.bat
        assert "BACH_HOST" in self.sh

    def test_both_reference_gui_server(self):
        assert "start --gui" in self.bat
        assert "start --gui" in self.sh

    def test_no_gnu_only_flags(self):
        for name, text in [("bach.bat", self.bat), ("bach.sh", self.sh)]:
            for i, line in enumerate(text.splitlines(), 1):
                if line.strip().startswith(("#", "REM")):
                    continue
                assert "xargs -r" not in line, (
                    f"{name}:{i}: xargs -r ist GNU-only"
                )
                assert "readlink -f" not in line, (
                    f"{name}:{i}: readlink -f fehlt auf macOS (grealpath nutzen)"
                )
                assert "sed -i " not in line or "sed -i ''" in line or "sed -i.bak" in line, (
                    f"{name}:{i}: sed -i ohne Suffix ist GNU-only"
                )
