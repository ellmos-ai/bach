"""A slow authority must not keep a preview alive across hundreds of reads."""
from types import SimpleNamespace

import pytest

from hub._services.chat import worker_selection_preview as preview


VERSION = "a" * 64


class Authority:
    mode = "remote"

    def __init__(self, *, count=2, depends_on=None, delay=0, fail=False):
        self.tasks = [dict(id=i, task_version=VERSION, status="pending",
                           assigned_to="BACH", depends_on=depends_on)
                      for i in range(1, count + 1)]
        self.calls = []
        self.now = 0
        self.delay = delay
        self.fail = fail

    def task_candidates(self, **kwargs):
        self.calls.append("candidates")
        self.now += self.delay
        return dict(tasks=self.tasks, total=len(self.tasks), offset=0, has_more=False)

    def read(self, task_id):
        self.calls.append(("lease", task_id))
        self.now += self.delay
        if self.fail:
            raise OSError("private authority failure")
        return SimpleNamespace(task_version=VERSION, leased=False)

    def task_snapshot(self, task_id):
        self.calls.append(("snapshot", task_id))
        self.now += self.delay
        if self.fail:
            raise OSError("private authority failure")
        return dict(id=task_id, task_version=VERSION, status="done")


def run(client, **kwargs):
    return preview.preview_worker_selection(
        client, {"id": "our-slot"}, configuration_version=VERSION,
        execution_profile_version=VERSION, **kwargs)


@pytest.mark.parametrize("fail", [False, True])
def test_slow_lease_aborts_instead_of_continuing(monkeypatch, fail):
    client = Authority(delay=3, fail=fail)
    monkeypatch.setattr(preview, "monotonic", lambda: client.now, raising=False)
    with pytest.raises(preview.PreviewUnavailable):
        run(client)
    assert client.calls == ["candidates", ("lease", 1)]


def test_slow_candidate_page_never_starts_a_lease_read(monkeypatch):
    client = Authority(delay=6)
    monkeypatch.setattr(preview, "monotonic", lambda: client.now, raising=False)
    with pytest.raises(preview.PreviewUnavailable):
        run(client)
    assert client.calls == ["candidates"]


@pytest.mark.parametrize("fail", [False, True])
def test_dependency_reads_share_deadline_with_page_and_lease(monkeypatch, fail):
    client = Authority(count=1, depends_on="101,102", delay=2)
    original = client.task_snapshot

    def snapshot(task_id):
        client.fail = fail
        return original(task_id)

    client.task_snapshot = snapshot
    monkeypatch.setattr(preview, "monotonic", lambda: client.now, raising=False)
    with pytest.raises(preview.PreviewUnavailable):
        run(client)
    assert client.calls == ["candidates", ("lease", 1), ("snapshot", 101)]


def test_fast_remote_reads_have_a_hard_shared_count_limit(monkeypatch):
    client = Authority(count=100, depends_on=",".join(str(i) for i in range(101, 133)))
    monkeypatch.setattr(preview, "monotonic", lambda: 0, raising=False)
    with pytest.raises(preview.PreviewUnavailable):
        run(client, limit=100)
    assert len(client.calls) == 128


def test_fast_preview_preserves_projection_and_caches_dependencies(monkeypatch):
    client = Authority(depends_on="101")
    monkeypatch.setattr(preview, "monotonic", lambda: 0, raising=False)
    result = run(client)
    assert client.calls == ["candidates", ("lease", 1), ("snapshot", 101), ("lease", 2)]
    assert result["candidate_count"] == 2
    assert result["claimability"] == "not_checked"
    assert preview.project_selection_preview(result, "our-slot") == result


def test_fast_errors_remain_unavailable_observations(monkeypatch):
    client = Authority(count=1, fail=True)
    monkeypatch.setattr(preview, "monotonic", lambda: 0, raising=False)
    result = run(client)
    assert result["items"][0]["observations"] == ["lease_unavailable"]


def test_pinned_snapshot_is_charged_to_same_budget(monkeypatch):
    client = Authority(delay=6)
    monkeypatch.setattr(preview, "monotonic", lambda: client.now, raising=False)
    with pytest.raises(preview.PreviewUnavailable):
        preview.preview_worker_selection(client, {"id": "our-slot", "task_id": 1},
            configuration_version=VERSION, execution_profile_version=VERSION)
    assert client.calls == [("snapshot", 1)]
