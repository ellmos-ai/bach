"""Version-bound candidate reviews in the existing BACH database.

Review accepts candidate content. It neither validates execution empirically nor
publishes a skill, chain or lesson. Native provider promotion is a separate step.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone


class LearningConflict(ValueError):
    code = "learning_conflict"
    http_status = 409


class LearningNotFound(LearningConflict):
    code = "candidate_not_found"
    http_status = 404


class LearningPromotionUnavailable(LearningConflict):
    code = "native_learning_promotion_unavailable"


_TABLES = {
    "hermes": "hermes_skill_candidates",
    "nemofold": "nemofold_workflow_candidates",
}
_FIELDS = {
    "hermes": (
        "name", "category", "role", "version", "description", "trigger_phrases",
        "frontmatter", "content", "confidence", "source_session",
        "noise_reduction_ratio", "lessons_draft_json",
    ),
    "nemofold": (
        "chain_name", "title", "description", "trigger_type", "steps_json",
        "confidence_score", "tuv_status", "tuv_report_json", "provenance_json",
    ),
}
_JSON_FIELDS = {
    "trigger_phrases", "frontmatter", "lessons_draft_json", "steps_json",
    "tuv_report_json", "provenance_json",
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def candidate_payload(provider, row):
    item = dict(row)
    result = {key: item.get(key) for key in _FIELDS[provider]}
    for key in _JSON_FIELDS.intersection(result):
        result[key] = json.loads(result[key]) if isinstance(result[key], str) else result[key]
    payload = {"provider": provider, "proposal_schema": 1, "candidate": result}
    # Preserve Phase-A bindings for historical rows without a common contract.
    if item.get("candidate_contract_json"):
        payload["common_contract"] = json.loads(item["candidate_contract_json"])
    return payload


def proposal_binding(provider, row):
    payload = encoded(candidate_payload(provider, row))
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_review_schema(conn, provider):
    # Serialize the column snapshot and ALTER operations across service instances.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    table = _TABLES[provider]
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    additions = {
        "candidate_revision": "INTEGER NOT NULL DEFAULT 0",
        "candidate_digest": "TEXT NOT NULL DEFAULT ''",
        "proposal_json": "TEXT NOT NULL DEFAULT ''",
        "candidate_contract_json": "TEXT NOT NULL DEFAULT ''",
    }
    if provider == "hermes":
        additions["lessons_draft_json"] = "TEXT NOT NULL DEFAULT '[]'"
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    conn.execute("""CREATE TABLE IF NOT EXISTS learning_candidate_reviews (
        provider TEXT NOT NULL, request_id TEXT NOT NULL,
        candidate_id INTEGER NOT NULL, candidate_revision INTEGER NOT NULL,
        candidate_digest TEXT NOT NULL, request_digest TEXT NOT NULL,
        decision TEXT NOT NULL, actor TEXT NOT NULL, notes TEXT NOT NULL,
        proposal_json TEXT NOT NULL, receipt_json TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(provider, request_id)
    )""")


def project_candidate(provider, row):
    item = dict(row)
    try:
        payload, digest = proposal_binding(provider, item)
        bound = (
            type(item.get("candidate_revision")) is int and item["candidate_revision"] > 0
            and digest == item.get("candidate_digest") and payload == item.get("proposal_json")
        )
    except (TypeError, ValueError):
        bound = False
    item.update(
        review_state=item["status"] if bound else "legacy_unverified",
        review_available=bound and item["status"] == "pending",
        promotion_available=False,
        promotion_unavailable_reason="Native Veröffentlichung und Rücknahme sind noch nicht angebunden.",
    )
    return item


def prohibit_legacy_promotion(conn, provider, candidate_id):
    row = conn.execute(f"SELECT * FROM {_TABLES[provider]} WHERE id=?", (candidate_id,)).fetchone()
    if row is None:
        raise LearningNotFound(f"Kandidat #{candidate_id} nicht gefunden")
    if row["status"] not in {"pending", "reviewed"}:
        raise LearningConflict("Dieser Kandidatenstatus erlaubt keine neue Veröffentlichung.")
    raise LearningPromotionUnavailable(
        "Keine native Veröffentlichung verfügbar. Ein statischer Prüfbericht oder ein "
        "Review veröffentlicht weder Skill, Kette noch Lesson."
    )


def record_review(conn, provider, candidate_id, *, expected_revision, expected_digest,
                  request_id, actor, decision, notes=""):
    """CAS and request replay share one transaction; no target writes occur."""
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("Aktuelle Kandidatenrevision erforderlich")
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("Aktueller Kandidatendigest erforderlich")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
        raise ValueError("Explizite Review-Request-ID erforderlich")
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 180:
        raise ValueError("Review-Akteur erforderlich")
    if decision not in {"reviewed", "rejected"}:
        raise ValueError("Ungültige Reviewentscheidung")
    if not isinstance(notes, str) or len(notes) > 12000 or "\x00" in notes:
        raise ValueError("Ungültige Reviewnotizen")
    if decision == "reviewed" and not notes.strip():
        raise ValueError("Begründung des Inhaltsreviews erforderlich")
    request = encoded({
        "candidate_id": candidate_id, "expected_revision": expected_revision,
        "expected_digest": expected_digest, "actor": actor, "decision": decision, "notes": notes,
    })
    request_digest = hashlib.sha256(request.encode("utf-8")).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        prior = conn.execute(
            "SELECT request_digest,receipt_json FROM learning_candidate_reviews WHERE provider=? AND request_id=?",
            (provider, request_id),
        ).fetchone()
        if prior is not None:
            if prior["request_digest"] != request_digest:
                raise LearningConflict("Review-Request-ID bereits anders verwendet")
            receipt = json.loads(prior["receipt_json"])
            conn.commit()
            return {**receipt, "replayed": True}
        table = _TABLES[provider]
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (candidate_id,)).fetchone()
        if row is None:
            raise LearningNotFound(f"Kandidat #{candidate_id} nicht gefunden")
        item = project_candidate(provider, row)
        if not item["review_available"]:
            raise LearningConflict("Kandidat ist ungeprüft archiviert oder bereits entschieden.")
        if item["candidate_revision"] != expected_revision or item["candidate_digest"] != expected_digest:
            raise LearningConflict("Kandidateninhalt inzwischen geändert; neu laden")
        stamp = datetime.now(timezone.utc).isoformat()
        receipt = {
            "status": decision, "candidate_id": candidate_id,
            "candidate_revision": expected_revision, "candidate_digest": expected_digest,
            "request_id": request_id, "actor": actor, "notes": notes,
            "review_scope": "candidate_content_only", "empirically_validated": False,
            "promotion_available": False, "targets_published": False,
            "replayed": False, "created_at": stamp,
        }
        if provider == "hermes":
            extra = ",rejection_reason=?" if decision == "rejected" else ""
            params = [decision, *([notes] if extra else []), candidate_id, expected_revision, expected_digest]
        else:
            extra = ",reviewed_by=?,review_notes=?"
            params = [decision, actor, notes, candidate_id, expected_revision, expected_digest]
        cur = conn.execute(
            f"UPDATE {table} SET status=?{extra} WHERE id=? AND candidate_revision=? AND candidate_digest=? AND status='pending'",
            params,
        )
        if cur.rowcount != 1:
            raise LearningConflict("Kandidatenentscheidung inzwischen geändert")
        conn.execute("""INSERT INTO learning_candidate_reviews (
            provider,request_id,candidate_id,candidate_revision,candidate_digest,request_digest,
            decision,actor,notes,proposal_json,receipt_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            provider, request_id, candidate_id, expected_revision, expected_digest,
            request_digest, decision, actor, notes, item["proposal_json"], encoded(receipt), stamp,
        ))
        conn.commit()
        return receipt
    except BaseException:
        conn.rollback()
        raise
