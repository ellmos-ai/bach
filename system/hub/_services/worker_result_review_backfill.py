"""Backfill: Legacy-Review-Zeilen auf hash-bound target_revision migrieren.

Migriert Zeilen in worker_result_model_reviews, deren target_revision noch den
Legacy-Prefix "sha256:" traegt (Bindung ueber submission_revision) auf die
hash-bound Variante (reiner Hex-Digest) um und spieelt den Wert auch in das
Receipt. Nicht migrierbare Zeilen werden uebersprungen.
"""

import json
import re

from hub._services.worker_result_review import _digest, _json

_PREFIX_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")


def backfill(conn) -> int:
    """Strippt den Legacy-Prefix aus target_revision, aktualisiert Receipt+Digest.

    Gibt die Anzahl der aktualisierten Zeilen zurueck. Committed nicht; die
    Transaktion liegt beim Aufrufer.
    """
    cursor = conn.execute(
        "SELECT review_task_id, target_revision, child_result_id, receipt "
        "FROM worker_result_model_reviews"
    )
    count = 0
    for row in cursor.fetchall():
        review_task_id = row[0]
        target_revision = row[1]
        child_result_id = row[2]
        receipt_text = row[3]
        if not isinstance(target_revision, str):
            continue
        try:
            receipt = json.loads(receipt_text)
        except (TypeError, ValueError):
            continue
        if not isinstance(receipt, dict):
            continue
        if not _PREFIX_RE.fullmatch(target_revision):
            continue
        stripped = target_revision[7:]
        receipt["target_revision"] = stripped
        if child_result_id is None:
            try:
                from .task_result_service import read_result

                receipt["result_id"] = read_result(conn, review_task_id)["result"]["result_id"]
            except Exception:
                continue
        updated = conn.execute(
            "UPDATE worker_result_model_reviews SET target_revision=?, receipt=?, "
            "receipt_sha256=? WHERE review_task_id=?",
            (stripped, _json(receipt), _digest(receipt), review_task_id),
        )
        if updated.rowcount > 0:
            count += updated.rowcount
    return count