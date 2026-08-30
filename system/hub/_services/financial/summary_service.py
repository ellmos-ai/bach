"""Fail-closed monthly and yearly summaries for the Financial Mail data."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


MONEY_QUANTUM = Decimal("0.01")
_SUBSCRIPTION_IDENTITY_COLUMNS = (
    "provider_name",
    "category",
    "betrag_monatlich",
    "betrag_jaehrlich",
    "zahlungsintervall",
    "naechste_zahlung",
    "kuendigungslink",
    "letzte_rechnung_id",
    "letzte_zahlung",
    "aktiv",
    "bestaetigt",
    "steuer_relevant",
)


class FinancialSummaryError(RuntimeError):
    """The source data cannot be summarized without an unsafe assumption."""


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not math.isfinite(float(amount)):
        return None
    return amount


def _rounded(value: Decimal) -> float:
    return float(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


class FinancialSummaryService:
    """Builds current month and year-to-date summary snapshots.

    ``total_ausgaben`` is observed, non-ignored mail-derived expenditure and
    does not include ``total_abos`` again.  Subscription totals are a current
    recurring-cost snapshot: monthly in the month row and annualized in the
    year row.  Historical subscription state cannot be reconstructed from the
    source table and is therefore not invented.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _require_tables(conn: sqlite3.Connection) -> None:
        required = {
            "financial_emails",
            "financial_subscriptions",
            "financial_summary",
        }
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = sorted(required - present)
        if missing:
            raise FinancialSummaryError(
                "Fehlende Finanztabellen: " + ", ".join(missing)
            )
        duplicate_periods = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT jahr, COALESCE(monat, -1)
                FROM financial_summary
                GROUP BY jahr, COALESCE(monat, -1)
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        if duplicate_periods:
            raise FinancialSummaryError(
                f"{duplicate_periods} Summary-Perioden sind mehrfach vorhanden; "
                "Aktualisierung abgebrochen."
            )

    @staticmethod
    def _subscription_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
        rows = conn.execute(
            "SELECT * FROM financial_subscriptions ORDER BY provider_id, id"
        ).fetchall()
        by_provider: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_provider.setdefault(str(row["provider_id"]), []).append(row)

        duplicate_rows = sum(max(0, len(group) - 1) for group in by_provider.values())
        conflicting_groups = 0
        canonical_rows = []
        for group in by_provider.values():
            signatures = {
                tuple(row[column] for column in _SUBSCRIPTION_IDENTITY_COLUMNS)
                for row in group
            }
            if len(signatures) > 1:
                conflicting_groups += 1
                continue
            # The legacy trigger updated every duplicate but incremented
            # zahlungen_count unevenly.  The oldest row has the fullest count.
            canonical_rows.append(group[0])

        if conflicting_groups:
            raise FinancialSummaryError(
                f"{conflicting_groups} Providergruppen enthalten fachlich "
                "widersprüchliche Abo-Duplikate; Zusammenfassung abgebrochen."
            )

        monthly_total = Decimal("0")
        active_count = 0
        invalid_amounts = 0
        for row in canonical_rows:
            if not row["aktiv"]:
                continue
            monthly = _money(row["betrag_monatlich"])
            if monthly is None:
                yearly = _money(row["betrag_jaehrlich"])
                monthly = yearly / Decimal(12) if yearly is not None else None
            if monthly is None:
                invalid_amounts += 1
                continue
            monthly_total += monthly
            active_count += 1

        return {
            "monthly_total": monthly_total,
            "active_count": active_count,
            "duplicate_rows": duplicate_rows,
            "invalid_amounts": invalid_amounts,
        }

    @staticmethod
    def _mail_snapshot(
        conn: sqlite3.Connection, today: date
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
        month = {
            "total": Decimal("0"),
            "steuer": Decimal("0"),
            "categories": {},
            "invoices": 0,
        }
        year = {
            "total": Decimal("0"),
            "steuer": Decimal("0"),
            "categories": {},
            "invoices": 0,
        }
        invalid_dates = 0
        invalid_amounts = 0
        rows = conn.execute(
            """
            SELECT email_date, category, document_type, betrag, steuer_relevant, status
            FROM financial_emails
            """
        ).fetchall()
        for row in rows:
            if str(row["status"] or "").strip().lower() == "ignoriert":
                continue
            amount = _money(row["betrag"])
            if amount is None:
                if row["betrag"] is not None:
                    invalid_amounts += 1
                continue
            try:
                observed = date.fromisoformat(str(row["email_date"] or "")[:10])
            except ValueError:
                invalid_dates += 1
                continue
            if observed.year != today.year:
                continue

            targets = [year]
            if observed.month == today.month:
                targets.append(month)
            category = str(row["category"] or "").strip() or "ohne_kategorie"
            is_invoice = str(row["document_type"] or "").strip().lower() == "rechnung"
            for target in targets:
                target["total"] += amount
                if row["steuer_relevant"]:
                    target["steuer"] += amount
                target["categories"][category] = (
                    target["categories"].get(category, Decimal("0")) + amount
                )
                if is_invoice:
                    target["invoices"] += 1

        diagnostics = {
            "invalid_dates": invalid_dates,
            "invalid_mail_amounts": invalid_amounts,
        }
        return month, year, diagnostics

    def calculate(self, *, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        with self._connect() as conn:
            self._require_tables(conn)
            subscriptions = self._subscription_snapshot(conn)
            month, year, diagnostics = self._mail_snapshot(conn, today)

        monthly_subscriptions = subscriptions["monthly_total"]
        summaries = []
        for period_month, source, subscription_total in (
            (today.month, month, monthly_subscriptions),
            (None, year, monthly_subscriptions * Decimal(12)),
        ):
            category_totals = {
                key: _rounded(value)
                for key, value in sorted(source["categories"].items())
            }
            summaries.append(
                {
                    "jahr": today.year,
                    "monat": period_month,
                    "summen_kategorie": json.dumps(
                        category_totals, ensure_ascii=False, sort_keys=True
                    ),
                    "total_ausgaben": _rounded(source["total"]),
                    "total_steuer_relevant": _rounded(source["steuer"]),
                    "total_abos": _rounded(subscription_total),
                    "anzahl_rechnungen": source["invoices"],
                    "anzahl_abos": subscriptions["active_count"],
                }
            )
        return {
            "summaries": summaries,
            "duplicate_subscription_rows": subscriptions["duplicate_rows"],
            "invalid_subscription_amounts": subscriptions["invalid_amounts"],
            **diagnostics,
        }

    def refresh(
        self, *, dry_run: bool = False, today: date | None = None
    ) -> dict[str, Any]:
        result = self.calculate(today=today)
        if dry_run:
            return result

        calculated_at = datetime.now().isoformat()
        with self._connect() as conn:
            self._require_tables(conn)
            for summary in result["summaries"]:
                existing = conn.execute(
                    """
                    SELECT id FROM financial_summary
                    WHERE jahr = ? AND (
                        (monat IS NULL AND ? IS NULL) OR monat = ?
                    )
                    ORDER BY id LIMIT 1
                    """,
                    (summary["jahr"], summary["monat"], summary["monat"]),
                ).fetchone()
                values = (
                    summary["summen_kategorie"],
                    summary["total_ausgaben"],
                    summary["total_steuer_relevant"],
                    summary["total_abos"],
                    summary["anzahl_rechnungen"],
                    summary["anzahl_abos"],
                    calculated_at,
                )
                if existing:
                    conn.execute(
                        """
                        UPDATE financial_summary
                        SET summen_kategorie = ?, total_ausgaben = ?,
                            total_steuer_relevant = ?, total_abos = ?,
                            anzahl_rechnungen = ?, anzahl_abos = ?,
                            berechnet_am = ?
                        WHERE id = ?
                        """,
                        (*values, existing["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO financial_summary
                            (jahr, monat, summen_kategorie, total_ausgaben,
                             total_steuer_relevant, total_abos,
                             anzahl_rechnungen, anzahl_abos, berechnet_am)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (summary["jahr"], summary["monat"], *values),
                    )
            conn.commit()
        return result

    def read(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._require_tables(conn)
            rows = conn.execute(
                """
                SELECT jahr, monat, summen_kategorie, total_ausgaben,
                       total_steuer_relevant, total_abos,
                       anzahl_rechnungen, anzahl_abos, berechnet_am
                FROM financial_summary
                ORDER BY jahr DESC, monat IS NULL, monat DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]
