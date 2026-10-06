"""Trithon Phase 4: kuratierte Muschelgrund-Projektion.

Hinweis zur Herkunft: Das Plan-Dokument TRITHON-MUSCHELGRUND-UMSETZUNGSPLAN-
2026-09-16.md ist lokal nicht auffindbar (vergeblich gesucht in bach/, docs/,
_archive/, services/). Das Design ist daher aus den Task-Anforderungen
(Task #1448) abgeleitet:

  a) Nur angenommene Abschluss-Receipts (status == "done") werden zu
     Facts/Lessons projiziert. Pending/Claimed/Blocked erzeugen nichts.
  b) Jeder Fact traegt Provenienz (Ledger-Quelle), einen Redaktionsstatus
     (redacted) und laeuft durch eine Datenschutz-Allowlist
     (privacy_allowlist). Ohne Allowlist wird fail-closed projiziert:
     evidence ist leer und redacted=True.
  c) Outbox/Retry ist idempotent und fuehrt NIEMALS ein Taskrollback durch:
     Facts werden write-ahead in facts.jsonl persistiert, bevor eine
     Zustellung versucht wird. Schlaegt die Zustellung fehl, bleibt der
     Outbox-Eintrag pending und wird beim naechsten Lauf erneut versucht.
  d) Ausfall-, Replay- und Epochensicherheit:
     - Crash zwischen Fact-Persistierung und Zustellung -> Outbox-Replay.
     - Idempotenz ueber Dedupe-Key f"{ticket_id}:{signature}" im Cursor;
       ein zweiter Lauf projiziert keine Duplikate.
     - Epochenwechsel (neues assignment_id/run_id im Ledger) wird in der
       Provenienz mitprotokolliert. reset_epoch() markiert eine neue
       Epoche, loescht aber NIEMALS den processed-Cursor (alte Receipts
       duerfen nie erneut projiziert werden).

Die Zustellung selbst (deliver-Callback) muss empfaengerseitig anhand der
fact_id idempotent sein; muschelgrund garantiert At-Least-Once.

State-Dateien in state_dir:
  facts.jsonl   -- append-only kuratierte Projektion (Fact/Lesson-Records)
  outbox.jsonl  -- Dispatch-Puffer (pro Lauf atomar neu geschrieben)
  cursor.json   -- {"processed": {dedupe_key: occurred_at}, "last_line": int,
                    "epoch": int}
  epochs.jsonl  -- Epochen-Marker (reset_epoch), rein append-only
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Set, Tuple

from hub._services.trithon.routing_contract import LedgerEntry, read_ledger

# Evidence-Schluessel, die einen Record als Lesson (statt Fact) markieren.
LESSON_KEYS = ("lesson", "lessons", "learnings")

FACTS_FILE = "facts.jsonl"
OUTBOX_FILE = "outbox.jsonl"
CURSOR_FILE = "cursor.json"
EPOCHS_FILE = "epochs.jsonl"

DeliverFn = Callable[[Dict[str, Any]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(state_dir: str | Path, name: str) -> Path:
    return Path(state_dir) / name


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _filter_evidence(
    evidence: Optional[Dict[str, Any]],
    allowlist: Optional[Set[str]],
) -> Tuple[Dict[str, Any], bool]:
    """Projiziert evidence durch die Datenschutz-Allowlist.

    Rueckgabe: (gefilterte_evidence, redacted). Ohne Allowlist (None) gilt
    fail-closed: evidence ist leer und redacted=True.
    """
    if allowlist is None:
        return {}, True
    evidence = evidence or {}
    filtered = {k: v for k, v in evidence.items() if k in allowlist}
    redacted = len(filtered) != len(evidence)
    return filtered, redacted


def _load_cursor(state_dir: str | Path) -> Dict[str, Any]:
    path = _state_path(state_dir, CURSOR_FILE)
    if not path.exists():
        return {"processed": {}, "last_line": 0, "epoch": 0}
    with path.open("r", encoding="utf-8") as fh:
        cursor = json.load(fh)
    cursor.setdefault("processed", {})
    cursor.setdefault("last_line", 0)
    cursor.setdefault("epoch", 0)
    return cursor


def _save_cursor(state_dir: str | Path, cursor: Dict[str, Any]) -> None:
    path = _state_path(state_dir, CURSOR_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(cursor, fh, ensure_ascii=False, sort_keys=True, indent=2)
    os.replace(tmp, path)


def _write_outbox(state_dir: str | Path, records: list) -> None:
    """Schreibt den Outbox-Puffer atomar neu (mit aktualisiertem Status)."""
    path = _state_path(state_dir, OUTBOX_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _deliver_one(record: Dict[str, Any], deliver: Optional[DeliverFn]) -> bool:
    """Versucht einen Outbox-Eintrag zuzustellen. True bei Erfolg."""
    if deliver is None:
        # Kein Dispatcher konfiguriert: Eintrag bleibt gepuffert.
        return False
    try:
        deliver(record["record"])
    except Exception as exc:  # noqa: BLE001 - Outbox darf nie den Lauf brechen
        record["attempts"] = record.get("attempts", 0) + 1
        record["last_error"] = f"{type(exc).__name__}: {exc}"
        return False
    record["attempts"] = record.get("attempts", 0) + 1
    record["delivered_at"] = _utc_now()
    record["last_error"] = None
    return True


def replay_outbox(
    state_dir: str | Path,
    deliver: Optional[DeliverFn] = None,
) -> Dict[str, int]:
    """Stellt gepufferte Outbox-Eintraege erneut zu (idempotent, fail-safe).

    Fehlschlagende Zustellungen bleiben pending und brechen den Lauf nicht.
    """
    records = list(_read_jsonl(_state_path(state_dir, OUTBOX_FILE)))
    delivered = 0
    for rec in records:
        if rec.get("delivered_at"):
            continue
        if _deliver_one(rec, deliver):
            delivered += 1
    _write_outbox(state_dir, records)
    pending = sum(1 for r in records if not r.get("delivered_at"))
    return {"outbox_total": len(records), "outbox_delivered": delivered, "outbox_pending": pending}


def _build_fact(
    entry: LedgerEntry,
    dedupe_key: str,
    allowlist: Optional[Set[str]],
    epoch: int,
    now: str,
) -> Dict[str, Any]:
    evidence_filtered, redacted = _filter_evidence(entry.evidence, allowlist)
    kind = "lesson" if any(k in evidence_filtered for k in LESSON_KEYS) else "fact"
    return {
        "fact_id": dedupe_key,
        "kind": kind,
        "ticket_id": entry.ticket_id,
        "assignment_id": entry.assignment_id,
        "run_id": entry.run_id,
        "executed_by": entry.executed_by,
        "actual_provider": entry.actual_provider,
        "actual_model": entry.actual_model,
        "occurred_at": entry.occurred_at,
        "projected_at": now,
        "evidence": evidence_filtered,
        "redacted": redacted,
        "provenance": {
            "source": "routing_contract.ledger",
            "ledger_line": entry.line_number,
            "signature": entry.signature,
            "status": entry.status,
            "epoch": epoch,
        },
    }


def project_ledger(
    ledger_path: str | Path,
    ticket_id: str,
    *,
    state_dir: str | Path,
    privacy_allowlist: Optional[Set[str]] = None,
    deliver: Optional[DeliverFn] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Projiziert angenommene Abschluss-Receipts des Ledgers in den Muschelgrund.

    Ablauf:
      1. Outbox-Replay bisher unzugestellter Eintraege.
      2. Neue done-Receipts (mit Signatur) -> Fact/Lesson write-ahead in
         facts.jsonl + Outbox-Eintrag, danach Zustellversuch.
      3. Cursor (processed-Set, last_line) atomar speichern.

    Kein Taskrollback: Schlaegt die Zustellung fehl, bleibt der Fact
    persistiert und der Outbox-Eintrag pending.
    """
    now = now or _utc_now()
    stats: Dict[str, Any] = {
        "facts_new": 0,
        "skipped_duplicates": 0,
        "delivered": 0,
        "outbox_pending": 0,
    }

    replay = replay_outbox(state_dir, deliver)
    stats["delivered"] += replay["outbox_delivered"]

    cursor = _load_cursor(state_dir)
    processed: Dict[str, str] = cursor["processed"]

    outbox_records = list(_read_jsonl(_state_path(state_dir, OUTBOX_FILE)))

    entries = read_ledger(ledger_path, ticket_id)
    last_line = cursor.get("last_line", 0)

    for entry in entries:
        last_line = max(last_line, entry.line_number)
        if entry.status != "done" or not entry.signature:
            continue
        dedupe_key = f"{ticket_id}:{entry.signature}"
        if dedupe_key in processed:
            stats["skipped_duplicates"] += 1
            continue

        fact = _build_fact(entry, dedupe_key, privacy_allowlist, cursor.get("epoch", 0), now)

        # Write-ahead: Fact persistieren, BEVOR zugestellt wird.
        _append_jsonl(_state_path(state_dir, FACTS_FILE), fact)
        outbox_entry = {
            "fact_id": dedupe_key,
            "record": fact,
            "attempts": 0,
            "delivered_at": None,
            "last_error": None,
            "queued_at": now,
        }
        outbox_records.append(outbox_entry)

        if _deliver_one(outbox_entry, deliver):
            stats["delivered"] += 1

        processed[dedupe_key] = entry.occurred_at or now
        stats["facts_new"] += 1

    _write_outbox(state_dir, outbox_records)
    cursor["last_line"] = last_line
    _save_cursor(state_dir, cursor)

    stats["outbox_pending"] = sum(1 for r in outbox_records if not r.get("delivered_at"))
    stats["facts_total"] = len(processed)
    stats["epoch"] = cursor.get("epoch", 0)
    return stats


def reset_epoch(
    state_dir: str | Path,
    *,
    reason: Optional[str] = None,
    now: Optional[str] = None,
) -> int:
    """Markiert einen Epochenwechsel. Erhoeht die Epoche im Cursor und
    haengt einen Marker an epochs.jsonl an.

    WICHTIG: Der processed-Cursor wird NIEMALS geloescht -- bereits
    projizierte Receipts duerfen auch ueber Epochen hinweg nicht erneut
    projiziert werden.
    """
    now = now or _utc_now()
    cursor = _load_cursor(state_dir)
    cursor["epoch"] = cursor.get("epoch", 0) + 1
    _save_cursor(state_dir, cursor)
    _append_jsonl(
        _state_path(state_dir, EPOCHS_FILE),
        {"epoch": cursor["epoch"], "reason": reason, "marked_at": now},
    )
    return cursor["epoch"]
