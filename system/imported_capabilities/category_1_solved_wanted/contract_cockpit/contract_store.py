"""Reusable local SQLite store for evidenced statements and transactions."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

from folderhome.contracts import (
    DateRange,
    FinanceCoverage,
    FinanceImportAction,
    FinanceImportApproval,
    FinancePeriodReport,
    FinanceStatementRecord,
    FinanceTransactionRecord,
)

_SCHEMA_VERSION = "folderhome.finance-store.v1"


class FinanceStoreError(RuntimeError):
    """Raised when local finance state is stale, unsafe, or inconsistent."""


class FinanceStore:
    """Read and transactionally append local statement evidence."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = _safe_state_root(state_dir)
        self.path = self.state_dir / "finance" / "finance.sqlite3"

    def revision(self) -> str:
        return _revision(self.list_statements(), self.list_transactions())

    def list_statements(
        self,
        *,
        profile_id: str | None = None,
        account_ref: str | None = None,
    ) -> tuple[FinanceStatementRecord, ...]:
        if not self.path.exists():
            return ()
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            clauses = []
            parameters: list[str] = []
            if profile_id is not None:
                clauses.append("profile_id = ?")
                parameters.append(profile_id)
            if account_ref is not None:
                clauses.append("account_ref = ?")
                parameters.append(account_ref)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = connection.execute(
                "SELECT * FROM statements"
                f"{where} ORDER BY period_start, period_end, statement_id",
                parameters,
            ).fetchall()
            return tuple(_statement_record(row) for row in rows)
        except sqlite3.Error as exc:
            raise FinanceStoreError(f"Finanz-State ist nicht lesbar: {exc}") from exc
        finally:
            connection.close()

    def list_transactions(
        self,
        *,
        profile_id: str | None = None,
        account_ref: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[FinanceTransactionRecord, ...]:
        if not self.path.exists():
            return ()
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            clauses = []
            parameters: list[str] = []
            for column, value in (
                ("profile_id", profile_id),
                ("account_ref", account_ref),
            ):
                if value is not None:
                    clauses.append(f"{column} = ?")
                    parameters.append(value)
            if date_from is not None:
                clauses.append("booking_date >= ?")
                parameters.append(date_from)
            if date_to is not None:
                clauses.append("booking_date <= ?")
                parameters.append(date_to)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = connection.execute(
                "SELECT * FROM transactions"
                f"{where} ORDER BY booking_date, transaction_id",
                parameters,
            ).fetchall()
            return tuple(_transaction_record(row) for row in rows)
        except sqlite3.Error as exc:
            raise FinanceStoreError(f"Finanz-State ist nicht lesbar: {exc}") from exc
        finally:
            connection.close()

    def count_audit_events(self) -> int:
        if not self.path.exists():
            return 0
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            return int(
                connection.execute("SELECT COUNT(*) FROM finance_audit_events").fetchone()[0]
            )
        finally:
            connection.close()

    def booking_references(self) -> dict[tuple[str, str], FinanceTransactionRecord]:
        return {
            (transaction.account_ref, transaction.booking_reference): transaction
            for transaction in self.list_transactions()
        }

    def validate_execution(self, *, expected_revision: str, approval_id: str) -> None:
        if not self.path.exists():
            if expected_revision != EMPTY_FINANCE_REVISION:
                raise FinanceStoreError("Finanz-State wurde seit der Planung verändert.")
            return
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            if self._revision_from_connection(connection) != expected_revision:
                raise FinanceStoreError("Finanz-State wurde seit der Planung verändert.")
            if connection.execute(
                "SELECT 1 FROM finance_audit_events WHERE approval_id = ? LIMIT 1",
                (approval_id,),
            ).fetchone():
                raise FinanceStoreError("Finanzfreigabe wurde bereits verwendet.")
        finally:
            connection.close()

    def apply(
        self,
        *,
        expected_revision: str,
        actions: tuple[FinanceImportAction, ...],
        approval: FinanceImportApproval,
    ) -> tuple[tuple[str, ...], tuple[str, ...], str]:
        connection = self._write_connection()
        statement_ids: list[str] = []
        transaction_ids: list[str] = []
        try:
            _initialize_schema(connection)
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            if self._revision_from_connection(connection) != expected_revision:
                raise FinanceStoreError("Finanz-State wurde seit der Planung verändert.")
            if connection.execute(
                "SELECT 1 FROM finance_audit_events WHERE approval_id = ? LIMIT 1",
                (approval.approval_id,),
            ).fetchone():
                raise FinanceStoreError("Finanzfreigabe wurde bereits verwendet.")
            for action in actions:
                statement = action.statement
                _upsert_account(connection, statement)
                connection.execute(
                    "INSERT INTO statements "
                    "(statement_id, profile_id, account_ref, institution, account_suffix, "
                    "period_start, period_end, opening_balance_cents, closing_balance_cents, "
                    "currency, source_document_id, source_sha256, source_path, imported_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        statement.statement_id,
                        statement.profile_id,
                        statement.account_ref,
                        statement.institution,
                        statement.account_suffix,
                        statement.period_start,
                        statement.period_end,
                        statement.opening_balance_cents,
                        statement.closing_balance_cents,
                        statement.currency,
                        statement.source_document_id,
                        statement.source_sha256,
                        str(statement.source_path),
                        approval.approved_at,
                    ),
                )
                statement_ids.append(statement.statement_id)
                for transaction in statement.transactions:
                    connection.execute(
                        "INSERT INTO transactions "
                        "(transaction_id, statement_id, profile_id, account_ref, booking_date, "
                        "amount_cents, counterparty, category, booking_reference, "
                        "source_document_id, source_sha256, source_line) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            transaction.transaction_id,
                            statement.statement_id,
                            statement.profile_id,
                            statement.account_ref,
                            transaction.booking_date,
                            transaction.amount_cents,
                            transaction.counterparty,
                            transaction.category,
                            transaction.booking_reference,
                            statement.source_document_id,
                            statement.source_sha256,
                            transaction.evidence.line_number,
                        ),
                    )
                    transaction_ids.append(transaction.transaction_id)
                audit_material = f"{approval.approval_id}\0{action.action_id}"
                connection.execute(
                    "INSERT INTO finance_audit_events "
                    "(audit_id, approval_id, plan_id, action_id, statement_id, imported_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        f"finance_audit_{sha256(audit_material.encode('utf-8')).hexdigest()}",
                        approval.approval_id,
                        approval.plan_id,
                        action.action_id,
                        statement.statement_id,
                        approval.approved_at,
                    ),
                )
            revision_after = self._revision_from_connection(connection)
            connection.commit()
            return tuple(statement_ids), tuple(transaction_ids), revision_after
        except FinanceStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise FinanceStoreError(f"Finanz-State konnte nicht ergänzt werden: {exc}") from exc
        finally:
            connection.close()

    def coverage(
        self,
        *,
        account_ref: str,
        date_from: str,
        date_to: str,
    ) -> FinanceCoverage:
        requested_start = date.fromisoformat(date_from)
        requested_end = date.fromisoformat(date_to)
        if requested_end < requested_start:
            raise FinanceStoreError("Abdeckungszeitraum ist umgekehrt.")
        clipped = []
        for statement in self.list_statements(account_ref=account_ref):
            start = max(requested_start, date.fromisoformat(statement.period_start))
            end = min(requested_end, date.fromisoformat(statement.period_end))
            if start <= end:
                clipped.append((start, end))
        merged: list[tuple[date, date]] = []
        for start, end in sorted(clipped):
            if merged and start <= merged[-1][1] + timedelta(days=1):
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        gaps = []
        cursor = requested_start
        for start, end in merged:
            if cursor < start:
                gaps.append((cursor, start - timedelta(days=1)))
            cursor = max(cursor, end + timedelta(days=1))
        if cursor <= requested_end:
            gaps.append((cursor, requested_end))
        return FinanceCoverage(
            account_ref=account_ref,
            requested_range=DateRange(date_from, date_to),
            covered_ranges=tuple(DateRange(a.isoformat(), b.isoformat()) for a, b in merged),
            gaps=tuple(DateRange(a.isoformat(), b.isoformat()) for a, b in gaps),
            complete=not gaps,
        )

    def period_report(
        self,
        *,
        account_ref: str,
        date_from: str,
        date_to: str,
    ) -> FinancePeriodReport:
        """Return movements and only continuity-proven boundary balances."""

        requested_start = date.fromisoformat(date_from)
        requested_end = date.fromisoformat(date_to)
        coverage = self.coverage(
            account_ref=account_ref,
            date_from=date_from,
            date_to=date_to,
        )
        statements = tuple(
            statement
            for statement in self.list_statements(account_ref=account_ref)
            if date.fromisoformat(statement.period_start) <= requested_end
            and date.fromisoformat(statement.period_end) >= requested_start
        )
        transactions = self.list_transactions(
            account_ref=account_ref,
            date_from=date_from,
            date_to=date_to,
        )
        ordered = tuple(sorted(statements, key=lambda item: item.period_start))
        continuity = coverage.complete and bool(ordered)
        for first, second in zip(ordered, ordered[1:], strict=False):
            first_end = date.fromisoformat(first.period_end)
            second_start = date.fromisoformat(second.period_start)
            if (
                second_start != first_end + timedelta(days=1)
                or first.closing_balance_cents != second.opening_balance_cents
            ):
                continuity = False
        opening = None
        closing = None
        if continuity:
            first = ordered[0]
            last = ordered[-1]
            first_transactions = self.list_transactions(
                account_ref=account_ref,
                date_from=first.period_start,
                date_to=(requested_start - timedelta(days=1)).isoformat(),
            ) if date.fromisoformat(first.period_start) < requested_start else ()
            last_transactions = self.list_transactions(
                account_ref=account_ref,
                date_from=last.period_start,
                date_to=date_to,
            )
            opening = first.opening_balance_cents + sum(
                item.amount_cents for item in first_transactions
            )
            closing = last.opening_balance_cents + sum(
                item.amount_cents for item in last_transactions
            )
        return FinancePeriodReport(
            account_ref=account_ref,
            date_from=date_from,
            date_to=date_to,
            coverage=coverage,
            statement_ids=tuple(item.statement_id for item in ordered),
            transactions=transactions,
            opening_balance_cents=opening,
            closing_balance_cents=closing,
            balance_continuity_verified=continuity,
        )

    def _revision_from_connection(self, connection: sqlite3.Connection) -> str:
        statements = tuple(
            _statement_record(row)
            for row in connection.execute(
                "SELECT * FROM statements ORDER BY period_start, period_end, statement_id"
            ).fetchall()
        )
        transactions = tuple(
            _transaction_record(row)
            for row in connection.execute(
                "SELECT * FROM transactions ORDER BY booking_date, transaction_id"
            ).fetchall()
        )
        return _revision(statements, transactions)

    def _write_connection(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise FinanceStoreError("Finanz-State darf kein symbolischer Link sein.")
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _read_connection(self) -> sqlite3.Connection:
        if self.path.is_symlink() or not self.path.is_file():
            raise FinanceStoreError(
                f"Finanz-State fehlt oder ist keine reguläre Datei: {self.path}"
            )
        connection = sqlite3.connect(
            f"{self.path.as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        return connection


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accounts (
            account_ref TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            institution TEXT NOT NULL,
            account_suffix TEXT NOT NULL,
            currency TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS statements (
            statement_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            account_ref TEXT NOT NULL REFERENCES accounts(account_ref),
            institution TEXT NOT NULL,
            account_suffix TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            opening_balance_cents INTEGER NOT NULL,
            closing_balance_cents INTEGER NOT NULL,
            currency TEXT NOT NULL,
            source_document_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_path TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            statement_id TEXT NOT NULL REFERENCES statements(statement_id),
            profile_id TEXT NOT NULL,
            account_ref TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            counterparty TEXT NOT NULL,
            category TEXT NOT NULL,
            booking_reference TEXT NOT NULL,
            source_document_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_line INTEGER NOT NULL,
            UNIQUE(account_ref, booking_reference)
        );
        CREATE TABLE IF NOT EXISTS finance_audit_events (
            audit_id TEXT PRIMARY KEY,
            approval_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            action_id TEXT NOT NULL UNIQUE,
            statement_id TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        """
    )
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'schema'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO metadata (key, value) VALUES ('schema', ?)",
            (_SCHEMA_VERSION,),
        )
    elif row[0] != _SCHEMA_VERSION:
        raise FinanceStoreError("Finanz-State verwendet ein unbekanntes Schema.")


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise FinanceStoreError("Finanz-State besitzt kein gültiges Schema.") from exc
    if row is None or row[0] != _SCHEMA_VERSION:
        raise FinanceStoreError("Finanz-State verwendet ein unbekanntes Schema.")


def _upsert_account(connection: sqlite3.Connection, statement: object) -> None:
    existing = connection.execute(
        "SELECT profile_id, institution, account_suffix, currency FROM accounts "
        "WHERE account_ref = ?",
        (statement.account_ref,),
    ).fetchone()
    values = (
        statement.profile_id,
        statement.institution,
        statement.account_suffix,
        statement.currency,
    )
    if existing is None:
        connection.execute(
            "INSERT INTO accounts "
            "(account_ref, profile_id, institution, account_suffix, currency) "
            "VALUES (?, ?, ?, ?, ?)",
            (statement.account_ref, *values),
        )
    elif tuple(existing) != values:
        raise FinanceStoreError(
            f"Kontometadaten widersprechen dem vorhandenen Konto {statement.account_ref}."
        )


def _statement_record(row: sqlite3.Row) -> FinanceStatementRecord:
    return FinanceStatementRecord(
        statement_id=str(row["statement_id"]),
        profile_id=str(row["profile_id"]),
        account_ref=str(row["account_ref"]),
        institution=str(row["institution"]),
        account_suffix=str(row["account_suffix"]),
        period_start=str(row["period_start"]),
        period_end=str(row["period_end"]),
        opening_balance_cents=int(row["opening_balance_cents"]),
        closing_balance_cents=int(row["closing_balance_cents"]),
        currency=str(row["currency"]),
        source_document_id=str(row["source_document_id"]),
        source_sha256=str(row["source_sha256"]),
        source_path=Path(str(row["source_path"])),
        imported_at=str(row["imported_at"]),
    )


def _transaction_record(row: sqlite3.Row) -> FinanceTransactionRecord:
    return FinanceTransactionRecord(
        transaction_id=str(row["transaction_id"]),
        statement_id=str(row["statement_id"]),
        profile_id=str(row["profile_id"]),
        account_ref=str(row["account_ref"]),
        booking_date=str(row["booking_date"]),
        amount_cents=int(row["amount_cents"]),
        counterparty=str(row["counterparty"]),
        category=str(row["category"]),
        booking_reference=str(row["booking_reference"]),
        source_document_id=str(row["source_document_id"]),
        source_sha256=str(row["source_sha256"]),
        source_line=int(row["source_line"]),
    )


def _revision(
    statements: tuple[FinanceStatementRecord, ...],
    transactions: tuple[FinanceTransactionRecord, ...],
) -> str:
    payload = {
        "statements": [item.to_dict() for item in statements],
        "transactions": [item.to_dict() for item in transactions],
    }
    material = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"finance_revision_{sha256(material).hexdigest()}"


def _safe_state_root(state_dir: Path) -> Path:
    absolute = Path(os.path.abspath(state_dir))
    if absolute.is_symlink() or absolute.resolve(strict=False) != absolute:
        raise FinanceStoreError(
            f"State-Verzeichnis enthält einen symbolischen Link oder Alias: {absolute}"
        )
    return absolute


EMPTY_FINANCE_REVISION = _revision((), ())
