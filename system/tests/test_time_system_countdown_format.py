# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionstest: CountdownModule.format_remaining darf keine Floats mit :d formatieren.

Bug #1256: `python3 bach.py --status` warf sporadisch
`[ERROR] Unknown format code 'd' for object of type 'float'`,
weil `_format_remaining` Division statt Ganzzahl-Division verwendete und
anschließend `{hours:02d}` auf float-Werte anwendete.
"""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from tools.time_system import CountdownModule


@pytest.fixture
def cd(tmp_path):
    """CountdownModule mit isoliertem data/ Verzeichnis."""
    (tmp_path / "data").mkdir()
    return CountdownModule(tmp_path)


class TestFormatRemainingRegression:
    def test_format_remaining_seconds_only(self, cd):
        assert cd._format_remaining(45) == "00:45"

    def test_format_remaining_minutes_and_seconds(self, cd):
        assert cd._format_remaining(125) == "02:05"

    def test_format_remaining_hours_minutes_seconds(self, cd):
        # Wichtig: Werte > 3600 erfordern Stunden und triggerten den Bug.
        assert cd._format_remaining(3665) == "01:01:05"

    def test_format_remaining_exact_hour(self, cd):
        assert cd._format_remaining(3600) == "01:00:00"

    def test_format_remaining_large_duration(self, cd):
        # TRANSFER-09-Haltefrist-ähnliche Dauer (ca. 30 Tage).
        seconds = 30 * 24 * 3600 + 12 * 3600 + 34 * 60 + 56
        assert cd._format_remaining(seconds) == "732:34:56"

    def test_format_remaining_expired(self, cd):
        assert cd._format_remaining(-1) == "ABGELAUFEN"

    def test_format_remaining_returns_string_no_exception(self, cd):
        # Sicherstellen, dass für beliebige positive ints kein ValueError fliegt.
        for seconds in [0, 1, 59, 60, 61, 3599, 3600, 3601, 86400, 2592000]:
            result = cd._format_remaining(seconds)
            assert isinstance(result, str)
            assert "d" not in result  # keine rohen Format-Codes im Output

    def test_format_remaining_accepts_float_total_seconds(self, cd):
        # get_display/check_expired übergeben total_seconds() als float.
        assert cd._format_remaining(3665.7) == "01:01:05"
        assert cd._format_remaining(125.0) == "02:05"
        assert cd._format_remaining(-0.5) == "ABGELAUFEN"
