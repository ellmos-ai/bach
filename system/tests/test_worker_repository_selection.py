"""Tests fuer die fail-closed Repository-Allowlist vor dem Worker-Lease.

Diese Tests laufen bewusst gegen das ECHTE Gate: das Modul ist absichtlich
NICHT in der Autouse-Fixture ``_legacy_selector_tests_use_test_repository``
aus ``system/tests/conftest.py`` gelistet. Dadurch werden
``worker_queue_status.worker_selection_policy`` und
``worker_repo_registry.resolve_task_repository`` pro Test gezielt gepatcht,
statt global durch die Legacy-Fixture ersetzt zu werden.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from system.hub._services.chat import worker_lease_binding, worker_repo_registry
from system.hub._services.chat.worker_repo_registry import RepositoryBindingError
from system.tests.test_worker_start_admission import admission  # noqa: F401  (Fixture)

ALLOWED_REPO = "ellmos-ai/bach"
OTHER_REPO = "other/repo"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def snapshot() -> dict:
    """Minimaler Task-Snapshot, wie ihn das Gate erwartet."""
    return {"id": 2692, "assigned_to": None, "assigned_slot": None, "status": "pending"}


@pytest.fixture
def set_allowed_repositories(monkeypatch):
    """Patcht ``worker_selection_policy`` im Quellmodul (Import erfolgt lokal)."""

    def _apply(repositories):
        def _policy(slot):
            return {"allowed_repositories": repositories}

        monkeypatch.setattr(
            "system.hub._services.chat.worker_queue_status.worker_selection_policy",
            _policy,
        )
        return _policy

    return _apply


@pytest.fixture
def set_resolved_repository(monkeypatch):
    """Patcht ``resolve_task_repository`` im Quellmodul."""

    def _apply(repository):
        def _resolve(task_id, **kwargs):
            return SimpleNamespace(
                task_id=task_id,
                repository=repository,
                origin="origin",
                default_branch="main",
                source_sha="0" * 40,
            )

        monkeypatch.setattr(worker_repo_registry, "resolve_task_repository", _resolve)
        return _resolve

    return _apply


@pytest.fixture
def set_binding_error(monkeypatch):
    """Laesst ``resolve_task_repository`` mit ``RepositoryBindingError`` scheitern."""

    def _apply(message="keine Bindung"):
        def _resolve(task_id, **kwargs):
            raise RepositoryBindingError(message)

        monkeypatch.setattr(worker_repo_registry, "resolve_task_repository", _resolve)
        return _resolve

    return _apply


def _reason(snapshot: dict, slot: dict):
    """Ruft den Gate-Helfer direkt auf."""
    return worker_lease_binding.TaskLeaseClient._repository_rejection_reason(snapshot, slot)


# --------------------------------------------------------------------------
# a) / b) Capability fehlt oder ist leer -> repository_capability_missing
# --------------------------------------------------------------------------


def test_missing_allowed_repositories_is_capability_missing(
    snapshot, monkeypatch, set_resolved_repository
):
    monkeypatch.setattr(
        "system.hub._services.chat.worker_queue_status.worker_selection_policy",
        lambda slot: {},
    )
    set_resolved_repository(ALLOWED_REPO)

    assert _reason(snapshot, {"id": "slot-a"}) == "repository_capability_missing"


def test_empty_allowed_repositories_is_capability_missing(
    snapshot, set_allowed_repositories, set_resolved_repository
):
    set_allowed_repositories([])
    set_resolved_repository(ALLOWED_REPO)

    assert _reason(snapshot, {"id": "slot-b"}) == "repository_capability_missing"


def test_policy_exception_is_capability_missing(
    snapshot, monkeypatch, set_resolved_repository
):
    def _boom(slot):
        raise RuntimeError("Policy nicht verfuegbar")

    monkeypatch.setattr(
        "system.hub._services.chat.worker_queue_status.worker_selection_policy",
        _boom,
    )
    set_resolved_repository(ALLOWED_REPO)

    assert _reason(snapshot, {"id": "slot-c"}) == "repository_capability_missing"


# --------------------------------------------------------------------------
# c) Registry-Ausfall -> repository_unverified
# --------------------------------------------------------------------------


def test_binding_error_is_unverified(snapshot, set_allowed_repositories, set_binding_error):
    set_allowed_repositories([ALLOWED_REPO])
    set_binding_error()

    assert _reason(snapshot, {"id": "slot-d"}) == "repository_unverified"


# --------------------------------------------------------------------------
# d) / e) Allowlist entscheidet ueber Kandidatur
# --------------------------------------------------------------------------


def test_repository_not_in_allowlist_is_rejected(
    snapshot, set_allowed_repositories, set_resolved_repository
):
    set_allowed_repositories([ALLOWED_REPO])
    set_resolved_repository(OTHER_REPO)

    assert _reason(snapshot, {"id": "slot-e"}) == "repository_not_allowed"


def test_repository_in_allowlist_is_accepted(
    snapshot, set_allowed_repositories, set_resolved_repository
):
    set_allowed_repositories([ALLOWED_REPO])
    set_resolved_repository(ALLOWED_REPO)

    assert _reason(snapshot, {"id": "slot-f"}) is None


def test_binding_error_takes_precedence_over_allowlist(
    snapshot, set_allowed_repositories, set_binding_error
):
    set_allowed_repositories([ALLOWED_REPO, OTHER_REPO])
    set_binding_error()

    assert _reason(snapshot, {"id": "slot-g"}) == "repository_unverified"


# --------------------------------------------------------------------------
# f) Kandidatenfilter-Wirkung in _automatic_matches_slot
# --------------------------------------------------------------------------


def test_automatic_matches_slot_rejects_wrong_repository(
    snapshot, set_allowed_repositories, set_resolved_repository
):
    set_allowed_repositories([ALLOWED_REPO])
    set_resolved_repository(OTHER_REPO)

    slot = {"id": "slot-h", "automatic": {"enabled": True, "pickup": {"enabled": True}}}
    assert worker_lease_binding.TaskLeaseClient._automatic_matches_slot(snapshot, slot) is False


def test_automatic_matches_slot_accepts_allowed_repository(
    snapshot, set_allowed_repositories, set_resolved_repository
):
    set_allowed_repositories([ALLOWED_REPO])
    set_resolved_repository(ALLOWED_REPO)

    slot = {"id": "slot-i", "automatic": {"enabled": True, "pickup": {"enabled": True}}}
    assert worker_lease_binding.TaskLeaseClient._automatic_matches_slot(snapshot, slot) is True


# --------------------------------------------------------------------------
# g) Fail-closed-Reihenfolge: Repo-Check vor Ownership
# --------------------------------------------------------------------------


def test_repository_check_runs_before_ownership(
    snapshot, set_allowed_repositories, set_resolved_repository
):
    """Ownership wuerde passen, die Allowlist aber nicht -> Repo-Reason gewinnt."""
    set_allowed_repositories([ALLOWED_REPO])
    set_resolved_repository(OTHER_REPO)

    owned = dict(snapshot)
    owned["assigned_to"] = "slot-j"
    owned["assigned_slot"] = "slot-j"

    slot = {"id": "slot-j", "worker": "slot-j"}
    reason = worker_lease_binding.TaskLeaseClient._selection_rejection_reason(owned, slot)
    assert reason == "repository_not_allowed"


def test_repository_rejection_reasons_are_stable():
    """Die Reasoncodes bleiben im Rejection-Set registriert (API-Stabilitaet)."""
    for code in (
        "repository_capability_missing",
        "repository_unverified",
        "repository_not_allowed",
    ):
        assert code in worker_lease_binding._REPOSITORY_REJECTIONS
