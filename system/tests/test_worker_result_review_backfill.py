import json
import sqlite3

from hub._services import worker_result_review as review
from hub._services.worker_result_review_backfill import backfill


def _setup_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(review._INTENTS_DDL)
    conn.execute(review._REVIEWS_DDL)
    return conn


def test_backfill_strips_legacy_prefix_only_for_legacy_rows():
    conn = _setup_conn()
    legacy_hash = "ab" * 32
    clean_hash = "cd" * 32
    legacy_receipt = {
        "schema": review._REVIEW_SCHEMA,
        "target_revision": "sha256:" + legacy_hash,
    }
    clean_receipt = {
        "schema": review._HASHBOUND_REVIEW_SCHEMA,
        "target_revision": clean_hash,
    }
    conn.execute(
        "INSERT INTO worker_result_model_reviews "
        "(review_task_id, target_task_id, target_result_id, target_revision, "
        "child_result_id, receipt, receipt_sha256, event_id) VALUES (?,?,?,?,?,?,?,?)",
        (
            11,
            10,
            101,
            "sha256:" + legacy_hash,
            3001,
            review._json(legacy_receipt),
            review._digest(legacy_receipt),
            "ev-legacy",
        ),
    )
    conn.execute(
        "INSERT INTO worker_result_model_reviews "
        "(review_task_id, target_task_id, target_result_id, target_revision, "
        "child_result_id, receipt, receipt_sha256, event_id) VALUES (?,?,?,?,?,?,?,?)",
        (
            22,
            20,
            202,
            clean_hash,
            3002,
            review._json(clean_receipt),
            review._digest(clean_receipt),
            "ev-clean",
        ),
    )

    assert backfill(conn) == 1

    legacy_row = conn.execute(
        "SELECT target_revision, receipt, receipt_sha256, child_result_id "
        "FROM worker_result_model_reviews WHERE review_task_id=11"
    ).fetchone()
    assert legacy_row["target_revision"] == legacy_hash
    parsed = json.loads(legacy_row["receipt"])
    assert parsed["target_revision"] == legacy_hash
    assert legacy_row["receipt_sha256"] == review._digest(parsed)

    clean_row = conn.execute(
        "SELECT target_revision, receipt, receipt_sha256, child_result_id "
        "FROM worker_result_model_reviews WHERE review_task_id=22"
    ).fetchone()
    assert clean_row["target_revision"] == clean_hash
    assert clean_row["receipt"] == review._json(clean_receipt)
    assert clean_row["receipt_sha256"] == review._digest(clean_receipt)
    assert clean_row["child_result_id"] == 3002


def test_backfill_empty_table_returns_zero():
    conn = _setup_conn()
    assert backfill(conn) == 0