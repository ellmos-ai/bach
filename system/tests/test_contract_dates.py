# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for contract_dates service (hub/_services/contract_dates.py)."""

from datetime import date, datetime
from pathlib import Path
import sys

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.contract_dates import (
    _add_months,
    _format_date,
    _parse_date,
    calc_monthly,
    calc_next_cancellation,
    calc_yearly,
)


class TestParseDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2025-03-15", date(2025, 3, 15)),
            ("2025-03-15T12:34:56", date(2025, 3, 15)),
            ("2025-03-15 12:34:56", date(2025, 3, 15)),
            ("15.03.2025", date(2025, 3, 15)),
            ("  2025-03-15  ", date(2025, 3, 15)),
            (date(2025, 3, 15), date(2025, 3, 15)),
            (datetime(2025, 3, 15, 12, 0), date(2025, 3, 15)),
            (None, None),
            ("", None),
            ("   ", None),
            ("not a date", None),
            ("31.02.2025", None),
            (object(), None),
        ],
    )
    def test_parse_date(self, value, expected):
        assert _parse_date(value) == expected


class TestFormatDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (date(2025, 3, 15), "2025-03-15"),
            (None, None),
        ],
    )
    def test_format_date(self, value, expected):
        assert _format_date(value) == expected


class TestAddMonths:
    @pytest.mark.parametrize(
        "start,months,expected",
        [
            (date(2025, 1, 15), 1, date(2025, 2, 15)),
            (date(2025, 1, 15), 12, date(2026, 1, 15)),
            (date(2025, 1, 15), -1, date(2024, 12, 15)),
            (date(2025, 1, 31), 1, date(2025, 2, 28)),
            (date(2024, 2, 29), 12, date(2025, 2, 28)),
            (date(2023, 1, 31), 1, date(2023, 2, 28)),
            (date(2023, 5, 31), 1, date(2023, 6, 30)),
            (date(2024, 1, 31), 2, date(2024, 3, 31)),
        ],
    )
    def test_add_months(self, start, months, expected):
        assert _add_months(start, months) == expected


class TestCalcNextCancellation:
    @pytest.mark.parametrize(
        "beginn,ablauf,frist,verlaengerung,today,expected",
        [
            # Ablauf vorhanden und zukuenftig -> Deadline = ablauf - frist
            (date(2022, 1, 1), date(2026, 6, 30), 3, 12, date(2025, 3, 1), date(2026, 3, 30)),
            # Ablauf in der Vergangenheit -> None
            (date(2022, 1, 1), date(2024, 6, 30), 3, 12, date(2025, 3, 1), None),
            # Ohne Ablauf: monatlich, Beginn in der Vergangenheit
            (date(2025, 1, 1), None, 1, 1, date(2025, 3, 15), date(2025, 4, 1)),
            # Ohne Ablauf: jaehrlich, Beginn in der Vergangenheit
            (date(2024, 1, 1), None, 1, 12, date(2025, 3, 15), date(2025, 12, 1)),
            # Ohne Ablauf: quartalsweise
            (date(2025, 1, 1), None, 1, 3, date(2025, 3, 15), date(2025, 6, 1)),
            # frist=0 -> deadline faellt auf Intervallende/Ablauf
            (date(2025, 1, 1), None, 0, 1, date(2025, 3, 15), date(2025, 4, 1)),
            # Kein Beginn und kein Ablauf -> None
            (None, None, 1, 12, date(2025, 3, 15), None),
            # Negative Frist wird auf 0 hochgesetzt
            (date(2025, 1, 1), None, -3, 12, date(2025, 3, 15), date(2026, 1, 1)),
            # Verlaengerung <= 0 wird auf 12 hochgesetzt
            (date(2025, 1, 1), None, 1, 0, date(2025, 3, 15), date(2025, 12, 1)),
        ],
    )
    def test_calc_next_cancellation(self, beginn, ablauf, frist, verlaengerung, today, expected):
        assert calc_next_cancellation(beginn, ablauf, frist, verlaengerung, today) == expected


class TestCalcMonthly:
    @pytest.mark.parametrize(
        "betrag,interval,expected",
        [
            (120.0, "monatlich", 120.0),
            (120.0, "monthly", 120.0),
            (120.0, "pro monat", 120.0),
            (1200.0, "jaehrlich", 100.0),
            (1200.0, "jährlich", 100.0),
            (1200.0, "yearly", 100.0),
            (1200.0, "annual", 100.0),
            (1200.0, "pro jahr", 100.0),
            (300.0, "quartalsweise", 100.0),
            (300.0, "vierteljährlich", 100.0),
            (300.0, "quartal", 100.0),
            (300.0, "quarterly", 100.0),
            (600.0, "halbjährlich", 100.0),
            (600.0, "half-yearly", 100.0),
            (120.0, "wöchentlich", 120.0 * 52.0 / 12.0),
            (120.0, "weekly", 120.0 * 52.0 / 12.0),
            (120.0, "täglich", 120.0 * 365.0 / 12.0),
            (120.0, "daily", 120.0 * 365.0 / 12.0),
            (120.0, None, 120.0),
            (120.0, "unbekannt", 120.0),
            (None, "monatlich", None),
            (0.0, "jaehrlich", 0.0),
        ],
    )
    def test_calc_monthly(self, betrag, interval, expected):
        result = calc_monthly(betrag, interval)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected)


class TestCalcYearly:
    @pytest.mark.parametrize(
        "betrag,interval,expected",
        [
            (120.0, "monatlich", 1440.0),
            (1200.0, "jaehrlich", 1200.0),
            (300.0, "quartalsweise", 1200.0),
            (None, "monatlich", None),
            (None, None, None),
        ],
    )
    def test_calc_yearly(self, betrag, interval, expected):
        result = calc_yearly(betrag, interval)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected)
