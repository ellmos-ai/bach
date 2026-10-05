# SPDX-License-Identifier: MIT
"""hub/_services/contract_dates.py - Gemeinsame Fristen- & Kosten-Engine für Verträge.

Wird verwendet von:
- hub/contract_cockpit.py (generisches Vertrags-Cockpit)
- hub/versicherung.py (Legacy-Versicherungsdaten)
- hub/abo.py (Legacy-Abo-Daten)

Alle Datumsoperationen arbeiten mit `datetime.date`. Konvertierung aus/vom
Datenbank-Stringformat (ISO 8601: YYYY-MM-DD) erfolgt über `_parse_date` und
`_format_date`.
"""

from datetime import date, datetime
from typing import Any, Optional


def _add_months(d: date, months: int) -> date:
    """Addiert Monate auf ein Datum (Schaltjahre berücksichtigt)."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(
        d.day,
        [31, 29 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 28,
         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    )
    return d.replace(year=year, month=month, day=day)


def _parse_date(value: Any) -> Optional[date]:
    """Wandelt einen beliebigen Wert in `date` um (ISO/DE/DateTime-Strings)."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _format_date(d: Optional[date]) -> Optional[str]:
    """Formatiert `date` als ISO-String (YYYY-MM-DD) oder `None`."""
    if d is None:
        return None
    return d.isoformat()


def calc_next_cancellation(
    beginn: Optional[date],
    ablauf: Optional[date],
    kuendigungsfrist_monate: Optional[int],
    verlaengerung_monate: Optional[int],
    today: Optional[date] = None,
) -> Optional[date]:
    """Berechnet das nächstmögliche Kündigungsdatum."""
    today = today or date.today()
    frist = kuendigungsfrist_monate if kuendigungsfrist_monate is not None else 1
    verlaengerung = verlaengerung_monate if verlaengerung_monate is not None else 12
    if frist < 0:
        frist = 0
    if verlaengerung <= 0:
        verlaengerung = 12

    if ablauf:
        deadline = _add_months(ablauf, -frist)
        if deadline < today:
            return None
        return deadline

    if not beginn:
        return None

    candidate = beginn
    # Springe zum aktuellen/laufenden Verlängerungsintervall.
    while candidate <= today:
        candidate = _add_months(candidate, verlaengerung)

    # Kündigungsfrist vor Intervallende.
    deadline = _add_months(candidate, -frist)
    while deadline < today:
        candidate = _add_months(candidate, verlaengerung)
        deadline = _add_months(candidate, -frist)
    return deadline


def calc_monthly(betrag: Optional[float], zahlungsintervall: Optional[str]) -> Optional[float]:
    """Wandelt einen Betrag in monatliche Kosten um."""
    if betrag is None:
        return None
    interval = (zahlungsintervall or "monatlich").lower()
    if interval in ("monatlich", "monthly", "pro monat"):
        return float(betrag)
    if interval in ("jährlich", "jaehrlich", "yearly", "annual", "pro jahr"):
        return float(betrag) / 12.0
    if interval in ("halbjährlich", "halbjaehrlich", "half-yearly"):
        return float(betrag) / 6.0
    if interval in ("vierteljährlich", "vierteljaehrlich", "quartal", "quartalsweise", "quarterly"):
        return float(betrag) / 3.0
    if interval in ("wöchentlich", "weekly"):
        return float(betrag) * 52.0 / 12.0
    if interval in ("täglich", "daily"):
        return float(betrag) * 365.0 / 12.0
    return float(betrag)


def calc_yearly(betrag: Optional[float], zahlungsintervall: Optional[str]) -> Optional[float]:
    """Wandelt einen Betrag in jährliche Kosten um."""
    monthly = calc_monthly(betrag, zahlungsintervall)
    return monthly * 12.0 if monthly is not None else None
