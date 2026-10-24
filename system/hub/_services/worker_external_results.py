# SPDX-License-Identifier: MIT
"""Operator entry points. Git observations never hold a SQLite transaction.

Only these adapters choose the canonical database; clients cannot submit a
database, repository path or scope snapshot. No worker/model is started here.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import worker_external_attestation as attestation
from . import worker_external_evidence as evidence
from . import worker_policy_settings as settings
from . import worker_result_review as review
from . import worker_review_identity as identity
from .task_result_service import read_result
from .worker_scope_evidence import project_scope_evidence


@contextmanager
def _connection(db_path=None):
    if db_path is None:
        from hub.bach_paths import BACH_DB
        db_path = BACH_DB
    conn = None
    try:
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=rw", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as exc:
        raise settings.PolicyUnavailable("Kanonischer Ergebnisspeicher nicht verfügbar") from exc
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


def authorize(*, operator_token, db_path=None):
    # A read-only check before parsing private request bodies. Writers check
    # again under their own transaction, so this is not the mutation authority.
    with settings._connection(db_path) as conn:
        return identity.require_operator(conn, operator_token)


def read_catalog(*, operator_token, db_path=None):
    with settings._connection(db_path) as conn:
        identity.require_operator(conn, operator_token)
        return identity.model_principal_catalog(conn)


def read_sources(*, operator_token, db_path=None):
    with settings._connection(db_path) as conn:
        identity.require_operator(conn, operator_token)
        return evidence.registry_snapshot(conn)


def attest(task_id, payload, *, operator_token, db_path=None):
    with _connection(db_path) as conn:
        recorded = attestation.attest_external_result(conn, task_id, payload,
                                                     operator_token=operator_token)
        # Never serialize the internal receipt: it contains private artifact,
        # tenant/account and run/turn identifiers and repository paths.
        public = read_result(conn, task_id)
    public = project_scope_evidence(public)
    return {"schema": "bach.worker-external-attestation-ack.v1", "task_id": task_id,
            "attested_result_id": payload["result_id"], "created": recorded["created"],
            "readback": public}


def prepare_review(task_id, payload, *, operator_token, db_path=None):
    expected = review.validate_external_review_target(payload)
    if expected["task_id"] != task_id:
        raise ValueError("Task-ID stimmt nicht mit dem Reviewziel überein")
    with _connection(db_path) as conn:
        prepared = review.prepare_external_review_task(conn, task_id,
            operator_token=operator_token, expected=expected)
    if prepared is None:
        raise evidence.ExternalEvidenceConflict("Aktuelles externes Reviewziel ist nicht verfügbar")
    return {"schema": "bach.worker-external-review-ack.v1", "worker_started": False,
            "accepted": False, "review": prepared}
