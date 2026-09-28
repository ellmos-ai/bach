"""Trithon Phase 5.2: Receipt-Provider (git / native / db) + deterministische Faltung.

Provider liefern Receipt-Rohdaten aus verschiedenen Quellen; fold_receipts
reduziert die Stroeme reihenfolgeunabhaengig und deterministisch (Dedupe nach
Signatur, ungueltige Receipts werden ausgeschlossen). Angelehnt an
ExecutionReceipt/_validate_receipt aus routing_contract.py.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .routing_contract import ExecutionReceipt

_FINAL_STATUSES = {"done", "blocked"}


class ProviderUnavailable(Exception):
    """Quelle nicht erreichbar/lesbar (fail-closed-Signal fuer Aufrufer)."""


def _utc_iso(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def is_valid_receipt(raw: dict) -> bool:
    """Spiegelt _validate_receipt: status final, evidence nicht-falsy."""
    if not isinstance(raw, dict):
        return False
    if raw.get("status") not in _FINAL_STATUSES:
        return False
    return bool(raw.get("evidence"))


def _normalize(raw: dict, source: str) -> Optional[dict]:
    """Normalisiert auf ExecutionReceipt-artiges dict; ungueltig -> None."""
    if not is_valid_receipt(raw):
        return None
    receipt = ExecutionReceipt(
        signature=str(raw.get("signature") or ""),
        status=str(raw["status"]),
        executed_by=str(raw.get("executed_by") or ""),
        actual_provider=str(raw.get("actual_provider") or source),
        actual_model=str(raw.get("actual_model") or ""),
        occurred_at=str(raw.get("occurred_at") or ""),
        evidence=dict(raw["evidence"]),
        assignment_id=str(raw.get("assignment_id") or ""),
        run_id=str(raw.get("run_id") or ""),
        ticket_id=str(raw.get("ticket_id") or ""),
    )
    if not receipt.signature:
        return None
    out = receipt.__dict__.copy()
    out["provider_source"] = source
    return out


def git_receipts(repo_dir: str | Path, max_count: int = 200, ticket_id: str = "") -> list[dict]:
    """Liest git log als Receipt-Strom (Signatur = Commit-Hash)."""
    fmt = "%H%x1f%ct%x1f%an"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "log", f"-{int(max_count)}", f"--format={fmt}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProviderUnavailable(f"git nicht erreichbar: {exc}") from exc
    if proc.returncode != 0:
        raise ProviderUnavailable(f"git log fehlgeschlagen: {proc.stderr.strip()}")
    receipts = []
    for line in proc.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        commit, epoch_s, author = parts
        try:
            occurred = _utc_iso(int(epoch_s))
        except ValueError:
            continue
        normalized = _normalize(
            {
                "signature": commit,
                "status": "done",
                "executed_by": author,
                "actual_provider": "git",
                "occurred_at": occurred,
                "evidence": {"rev": commit, "repo": str(repo_dir)},
                "ticket_id": ticket_id,
            },
            source="git",
        )
        if normalized is not None:
            receipts.append(normalized)
    return receipts


def native_receipts(helpers: Iterable[Callable[[], dict]]) -> list[dict]:
    """Fuehrt lokale Helfer aus; jeder Helfer liefert ein Receipt-Rohdict."""
    receipts = []
    for helper in helpers:
        try:
            raw = helper()
        except Exception as exc:
            raise ProviderUnavailable(
                f"nativer Helfer {getattr(helper, '__name__', '?')} fehlgeschlagen: {exc}"
            ) from exc
        normalized = _normalize(raw, source="native")
        if normalized is not None:
            receipts.append(normalized)
    return receipts


def db_receipts(db_path: str | Path, table: str = "receipts") -> list[dict]:
    """Liest Receipts aus einer SQLite-Tabelle (eine JSON-Spalte 'payload')."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ProviderUnavailable(f"db nicht erreichbar: {exc}") from exc
    try:
        try:
            rows = conn.execute(f"SELECT payload FROM {table}").fetchall()
        except sqlite3.Error as exc:
            raise ProviderUnavailable(f"db-Query fehlgeschlagen: {exc}") from exc
    finally:
        conn.close()
    receipts = []
    for (payload,) in rows:
        try:
            raw = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        normalized = _normalize(raw, source="db")
        if normalized is not None:
            receipts.append(normalized)
    return receipts


def _winner_key(receipt: dict) -> tuple:
    evidence = json.dumps(receipt.get("evidence") or {}, sort_keys=True)
    return (
        str(receipt.get("occurred_at") or ""),
        str(receipt.get("executed_by") or ""),
        str(receipt.get("provider_source") or ""),
        evidence,
    )


def fold_receipts(streams: Iterable[Iterable[dict]]) -> dict:
    """Deterministische, reihenfolgeunabhaengige Faltung der Receipt-Stroeme.

    - alle Stroeme werden flach zusammengefuehrt und vor der Reduktion
      nach Signatur sortiert (Reihenfolge der Eingabe egal)
    - Duplikate (gleiche Signatur): deterministischer Gewinner via _winner_key
    - ungueltige Roheintraege (status nicht final / evidence falsy) fliegen raus
    Rueckgabe: {"receipts": [...], "by_ticket": {ticket_id: receipt}, "stats": {...}}
    """
    flat: list[dict] = []
    count_in = 0
    invalid = 0
    for stream in streams:
        for raw in stream:
            count_in += 1
            if isinstance(raw, dict) and "provider_source" in raw and is_valid_receipt(raw):
                flat.append(raw)
            else:
                source = str(raw.get("actual_provider") or "?") if isinstance(raw, dict) else "?"
                normalized = _normalize(raw, source=source)
                if normalized is None:
                    invalid += 1
                else:
                    flat.append(normalized)
    flat.sort(key=lambda r: str(r.get("signature") or ""))
    winners: dict[str, dict] = {}
    for receipt in flat:
        sig = str(receipt.get("signature") or "")
        if not sig:
            invalid += 1
            continue
        current = winners.get(sig)
        if current is None or _winner_key(receipt) < _winner_key(current):
            winners[sig] = receipt
    receipts = sorted(
        winners.values(),
        key=lambda r: (str(r.get("occurred_at") or ""), str(r.get("signature") or "")),
    )
    by_ticket: dict[str, dict] = {}
    for receipt in receipts:
        ticket = str(receipt.get("ticket_id") or "")
        if ticket and ticket not in by_ticket:
            by_ticket[ticket] = receipt
    return {
        "receipts": receipts,
        "by_ticket": by_ticket,
        "stats": {
            "count_in": count_in,
            "count_out": len(receipts),
            "duplicates": count_in - invalid - len(receipts),
            "invalid": invalid,
        },
    }
