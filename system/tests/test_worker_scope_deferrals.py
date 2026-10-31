"""Preparation recovery uses the real selector; post-model deferrals stay sticky."""
from types import SimpleNamespace

import pytest

from hub._services.chat.worker_queue_status import QueueObservation
from hub._services.chat.worker_scope_deferrals import ScopePreparationDeferrals
from hub._services.task_lease_client import TaskLeaseClient
from system.tests.test_worker_queue_status import mem_db, _insert_task


def exhausted(*task_ids):
    records = []
    observation = QueueObservation(SimpleNamespace(mode='local'), records.append)
    for tid in task_ids:
        observation.candidate(tid)
        observation.reject('deferred_version')
    observation.waiting()
    observation.publish()
    return records[0]


def test_expiry_alone_does_not_reenter_a_fresh_scan():
    now = [0.0]
    cache = ScopePreparationDeferrals(clock=lambda: now[0])
    assert cache.defer(1, 'version', tool_dispatch_count=0)
    now[0] = 100
    assert cache.combined({}) == {1: 'version'}
    assert cache.after_exhausted_scan(exhausted(1)) == (1,)
    assert cache.combined({}) == {}


@pytest.mark.parametrize('count', [None, -1, 1, 2, True, False, '0', 0.0])
def test_unknown_or_possible_tool_dispatch_cannot_be_temporary(count):
    cache = ScopePreparationDeferrals()
    assert cache.defer(1, 'version', tool_dispatch_count=count) is False
    assert cache.combined({}) == {}


def test_ordinary_deferrals_are_never_cleared_or_overridden():
    now = [0.0]
    cache = ScopePreparationDeferrals(clock=lambda: now[0])
    assert cache.defer(1, 'scope-version', tool_dispatch_count=0)
    ordinary = {1: 'returned-model-version', 2: 'fixed-rejection-version'}
    assert cache.combined(ordinary) == ordinary
    now[0] = 100
    assert cache.after_exhausted_scan(exhausted(1, 2)) == (1,)
    assert cache.combined(ordinary) is ordinary
    assert ordinary == {1: 'returned-model-version', 2: 'fixed-rejection-version'}


@pytest.mark.parametrize('record', [None, {}, {'state': 'waiting', 'scan_complete': True},
    {**exhausted(1), 'scan_complete': False}, {**exhausted(1), 'state': 'error'},
    {**exhausted(1), 'source': 'untrusted'}, {**exhausted(1), 'candidate_count': 0}])
def test_incomplete_or_invalid_observation_does_not_reopen(record):
    now = [0.0]
    cache = ScopePreparationDeferrals(clock=lambda: now[0])
    cache.defer(1, 'version', tool_dispatch_count=0)
    now[0] = 100
    assert cache.after_exhausted_scan(record) == ()
    assert cache.combined({}) == {1: 'version'}


def test_not_yet_due_and_successfully_prepared_entries():
    now = [0.0]
    cache = ScopePreparationDeferrals(clock=lambda: now[0])
    cache.defer(1, 'v1', tool_dispatch_count=0)
    now[0] = 20
    cache.defer(2, 'v2', tool_dispatch_count=0)
    now[0] = 30
    assert cache.after_exhausted_scan(exhausted(1, 2)) == (1,)
    assert cache.combined({}) == {2: 'v2'}
    cache.resolved(2)
    assert cache.combined({}) == {}


def controller_context(mem_db, monkeypatch, now):
    from hub._services.chat import telegram_chat as controller
    client = TaskLeaseClient(conn=mem_db)
    control = controller._WorkerControl('our-slot')
    control.thread = SimpleNamespace(is_alive=lambda: True)
    control.worker_thread_started = True
    control.scope_preparation_deferrals = ScopePreparationDeferrals(clock=lambda: now[0])
    monkeypatch.setattr(controller, '_native_task_client', lambda: client)
    monkeypatch.setattr(controller, '_WORKER_CONTROLS', {'our-slot': control})
    monkeypatch.setattr(controller, '_WORKER_EXECUTIONS', {'our-slot': control})
    return controller, client, control


def test_real_selector_considers_fresh_task_before_expired_scope_retry(mem_db, monkeypatch):
    now = [0.0]
    controller, client, control = controller_context(mem_db, monkeypatch, now)
    first, later = _insert_task(mem_db), _insert_task(mem_db)
    first_version = client.task_snapshot(first)['task_version']
    control.scope_preparation_deferrals.defer(first, first_version, tool_dispatch_count=0)
    now[0] = 100
    acquired = controller._acquire_worker_task(control, {'id': 'our-slot'}, 'physical')
    assert acquired.task_id == later and client.read(later).leased
    assert control.scope_preparation_deferrals.combined({}) == {first: first_version}
    assert acquired.return_lease()
    # A real post-model return continues to use the ordinary controller map.
    control.deferred_task_versions[later] = client.task_snapshot(later)['task_version']
    assert controller._acquire_worker_task(control, {'id': 'our-slot'}, 'physical') is None
    assert control.queue_status['state'] == 'waiting' and control.queue_status['scan_complete']
    assert control.scope_preparation_deferrals.combined({}) == {}
    retried = controller._acquire_worker_task(control, {'id': 'our-slot'}, 'physical')
    assert retried.task_id == first and client.read(first).leased
    assert later in control.deferred_task_versions
    assert retried.return_lease()


def test_stale_observation_cannot_reopen_preparation(mem_db, monkeypatch):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    now = [0.0]
    controller, client, control = controller_context(mem_db, monkeypatch, now)
    control.scope_preparation_deferrals.defer(1, 'version', tool_dispatch_count=0)
    control.queue_status = exhausted(1)
    now[0] = 100
    monkeypatch.setattr(WorkerLeaseBinding, 'acquire_next', lambda *a, **kw: None)
    assert controller._acquire_worker_task(control, {'id': 'our-slot'}, 'physical') is None
    assert control.scope_preparation_deferrals.combined({}) == {1: 'version'}
