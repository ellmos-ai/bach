"""BACH #4216: synthetic process identities and HTTP only; never signal live jobs."""
import json
import signal
from types import SimpleNamespace
import urllib.request

import psutil
import pytest

from hub import compute_lock as compute


@pytest.fixture
def processes(tmp_path, monkeypatch):
    receipt = tmp_path / "bot-paused.json"
    flag = tmp_path / "session.json"
    flag.write_text('{"model_active_inferenz": false}')
    monkeypatch.setattr(compute, "PAUSED_PIDS_FILE", str(receipt))
    monkeypatch.setattr(compute, "SESSION_FLAG_PATH", str(flag))
    monkeypatch.setattr(compute, "_PROCESS_STATE_WAIT_SECONDS", 0)
    instances, signals, before_signal = {}, [], []

    class Process:
        def __init__(self, pid, created=100.0):
            self.pid, self.created = pid, created
            self.state = psutil.STATUS_RUNNING
            self.fail_signal = set()

        def create_time(self):
            return self.created

        def is_running(self):
            return True

        def status(self):
            return self.state

        def send_signal(self, value):
            # Assert that an identity-bearing intent was durable BEFORE the
            # mocked native effect, not retroactively invented by recovery.
            saved = json.loads(receipt.read_text())
            record = next(r for r in saved["processes"] if r["pid"] == self.pid)
            assert record["create_time"] == self.created
            assert record["state"] == (
                "pause_unconfirmed" if value == signal.SIGSTOP else "resume_unconfirmed")
            before_signal.append(record.copy())
            signals.append((self.pid, value))
            if value in self.fail_signal:
                raise psutil.AccessDenied(self.pid)
            self.state = psutil.STATUS_STOPPED if value == signal.SIGSTOP else psutil.STATUS_RUNNING

    def get_process(pid):
        if pid not in instances:
            raise psutil.NoSuchProcess(pid)
        return instances[pid]

    def add(pid, created=100.0):
        process = instances[pid] = Process(pid, created)
        return process

    monkeypatch.setattr(psutil, "Process", get_process)
    monkeypatch.setattr(compute, "_check_model_loaded", lambda _url: False)
    return SimpleNamespace(add=add, instances=instances, signals=signals, before=before_signal,
                           receipt=receipt, flag=flag)


def pause(*pids):
    return compute.pause_compute_jobs({"active_compute_jobs": [{"pid": pid} for pid in pids]})


def test_pause_and_resume_require_durable_matching_identity(processes):
    processes.add(101)
    assert pause(101) == [101]
    saved = json.loads(processes.receipt.read_text())
    assert saved["schema"] == compute._PAUSE_SCHEMA
    record = saved["processes"][0]
    assert {key: record[key] for key in ("pid", "create_time", "state")} == {
        "pid": 101, "create_time": 100.0, "state": "paused"}
    assert len(record["pause_id"]) == 32
    assert saved["manual_review_required"] is False
    assert compute.resume_compute_jobs([101]) == [101]
    assert processes.signals == [(101, signal.SIGSTOP), (101, signal.SIGCONT)]
    assert not processes.receipt.exists() and not processes.flag.exists()


def test_reused_pid_is_never_resumed_and_keeps_a_manual_receipt(processes):
    processes.add(101)
    assert pause(101) == [101]
    replacement = processes.add(101, created=999.0)
    replacement.state = psutil.STATUS_STOPPED
    assert compute.resume_compute_jobs([101]) == []
    assert processes.signals == [(101, signal.SIGSTOP)]
    saved = json.loads(processes.receipt.read_text())
    assert saved["processes"][0]["create_time"] == 100.0
    assert saved["processes"][0]["state"] == "identity_unverified"
    assert saved["manual_review_required"] is True
    assert processes.flag.exists()


def test_unrecorded_or_already_stopped_jobs_cannot_be_claimed_or_resumed(processes):
    process = processes.add(101)
    process.state = psutil.STATUS_STOPPED
    with pytest.raises(compute.ComputePauseError, match="process_already_stopped"):
        pause(101)
    assert compute.resume_compute_jobs([101]) == []
    assert processes.signals == []
    assert not processes.receipt.exists()


@pytest.mark.parametrize("raw", [
    '{"paused_pids": [101], "source": "bach_telegram_bot"}',
    '{"paused_pids": [101], "source": "unknown"}',
    '{"paused_pids": [101, true]}',
    '{"paused_pids": [101], "paused_pids": []}',
    'not json',
])
def test_legacy_and_invalid_receipts_remain_without_signals(processes, raw, caplog):
    processes.add(101).state = psutil.STATUS_STOPPED
    processes.receipt.write_text(raw)
    assert compute.recover_paused_jobs() == []
    assert processes.signals == []
    assert processes.receipt.read_text() == raw
    assert processes.flag.exists()
    assert "compute_resume_deferred" in caplog.text


def test_resuming_new_job_preserves_legacy_manual_rest_and_short_keep_alive(processes):
    processes.receipt.write_text('{"paused_pids": [99]}')
    processes.add(101)
    assert pause(101) == [101]
    assert compute.resume_compute_jobs([101]) == [101]
    saved = json.loads(processes.receipt.read_text())
    assert saved["paused_pids"] == [99]
    assert saved["processes"] == [{"pid": 99, "state": "legacy_unverified"}]
    assert saved["manual_review_required"] is True
    assert compute.get_effective_keep_alive() == "5m"
    assert processes.flag.exists()


def test_partial_resume_preserves_failed_identity_and_never_replays_ambiguous_signal(processes):
    first, second = processes.add(101), processes.add(102)
    assert pause(101, 102) == [101, 102]
    first.fail_signal.add(signal.SIGCONT)
    assert compute.resume_compute_jobs([101, 102]) == [102]
    saved = json.loads(processes.receipt.read_text())
    assert saved["paused_pids"] == [101]
    assert saved["processes"][0]["state"] == "resume_unconfirmed"
    assert second.state == psutil.STATUS_RUNNING
    before = list(processes.signals)
    assert compute.recover_paused_jobs() == []
    assert processes.signals == before
    assert processes.receipt.exists() and processes.flag.exists()


def test_recovery_requires_fresh_confirmed_empty_ollama(processes, monkeypatch, caplog):
    processes.add(101)
    assert pause(101) == [101]
    observed_urls = []
    for observation in (True, None):
        monkeypatch.setattr(compute, "_check_model_loaded",
                            lambda url, value=observation: observed_urls.append(url) or value)
        assert compute.recover_paused_jobs("http://127.0.0.1:11434") == []
        assert processes.receipt.exists() and processes.flag.exists()
        assert processes.signals == [(101, signal.SIGSTOP)]
    assert observed_urls == ["http://127.0.0.1:11434"] * 2
    assert "compute_recovery_deferred" in caplog.text
    monkeypatch.setattr(compute, "_check_model_loaded", lambda _url: False)
    assert compute.recover_paused_jobs() == [101]
    assert not processes.receipt.exists()


def test_paused_process_that_exited_is_removed_without_signalling_reused_targets(processes):
    processes.add(101)
    assert pause(101) == [101]
    del processes.instances[101]
    assert compute.recover_paused_jobs() == []
    assert processes.signals == [(101, signal.SIGSTOP)]
    assert not processes.receipt.exists()


@pytest.mark.parametrize("state", [None, "unrecognized", psutil.STATUS_TRACING_STOP])
def test_unknown_or_traced_native_process_state_never_authorizes_cleanup(processes, state):
    process = processes.add(101)
    assert pause(101) == [101]
    process.state = state
    assert compute.resume_compute_jobs([101]) == []
    assert processes.signals == [(101, signal.SIGSTOP)]
    assert processes.receipt.exists() and processes.flag.exists()


def test_pause_persistence_failure_precedes_any_signal(processes, monkeypatch):
    processes.add(101)
    def unavailable(*_args):
        raise OSError("isolated persistence failure")
    monkeypatch.setattr(compute, "_write_paused_records", unavailable)
    with pytest.raises(compute.ComputePauseError, match="pause_intent_unrecorded") as refusal:
        pause(101)
    assert refusal.value.paused_pids == []
    assert processes.signals == []


def test_failed_post_pause_persistence_keeps_nonreplayable_intent(processes, monkeypatch):
    processes.add(101)
    write = compute._write_paused_records
    def fail_confirmation(path, records):
        if any(record["state"] == "paused" for record in records):
            raise OSError("isolated confirmation failure")
        return write(path, records)
    monkeypatch.setattr(compute, "_write_paused_records", fail_confirmation)
    with pytest.raises(compute.ComputePauseError, match="pause_confirmation_unrecorded") as refusal:
        pause(101)
    assert refusal.value.paused_pids == []
    assert json.loads(processes.receipt.read_text())["processes"][0]["state"] == "pause_unconfirmed"
    assert compute.resume_compute_jobs([101]) == []
    assert processes.signals == [(101, signal.SIGSTOP)]


def test_missing_job_does_not_prevent_pausing_other_declared_jobs(processes):
    processes.add(102)
    assert pause(101, 102) == [102]
    assert processes.signals == [(102, signal.SIGSTOP)]


@pytest.mark.parametrize("raw,expected", [
    (b'{"models":[]}', False),
    (b'{"models":[{"name":"another-model:latest"}]}', True),
    (b'{"models":[{"name":"qwen3.8:27b-mlx"}]}', True),
    (b'{}', None), (b'null', None), (b'[]', None), (b'not json', None),
    (b'{"models":null}', None), (b'{"models":{}}', None),
    (b'{"models":[{}]}', None), (b'{"models":[null]}', None),
    (b'{"models":[{"name":null}]}', None), (b'{"models":[{"name":""}]}', None),
    (b'{"models":[],"models":[]}', None), (b'{"models":[],"extra":NaN}', None),
])
def test_ollama_probe_is_strictly_tri_state(monkeypatch, raw, expected):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def read(self, size):
            return raw[:size]
    observed = []
    def open_request(request, timeout):
        observed.append((request.full_url, timeout))
        return Response()
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *_args: SimpleNamespace(open=open_request))
    assert compute._check_model_loaded("http://127.0.0.1:11434/") is expected
    assert observed == [("http://127.0.0.1:11434/api/ps", 5)]


def test_ollama_transport_failure_is_unknown(monkeypatch):
    def failed(*_args, **_kwargs):
        raise OSError("synthetic transport failure")
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *_args: SimpleNamespace(open=failed))
    assert compute._check_model_loaded("http://127.0.0.1:11434") is None


@pytest.fixture
def monitor(monkeypatch, tmp_path):
    state = SimpleNamespace(now=0.0, observations=[], resumes=[], callbacks=[])
    path = tmp_path / "pending.json"
    path.write_text("pending pause evidence")
    monkeypatch.setattr(compute, "PAUSED_PIDS_FILE", str(path))
    monkeypatch.setattr(compute.time, "monotonic", lambda: state.now)

    def sleep(seconds):
        assert seconds >= 0
        state.now += seconds

    class InlineThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target
        def start(self):
            self.target()

    monkeypatch.setattr(compute.time, "sleep", sleep)
    monkeypatch.setattr(compute.threading, "Thread", InlineThread)
    monkeypatch.setattr(compute, "delete_session_flag",
                        lambda: pytest.fail("monitor must not clear unconfirmed pause evidence"))

    def run(values, *, timeout=30, resumed=None):
        sequence = iter(values)
        def observation(_url):
            value = next(sequence, None)
            state.observations.append((state.now, value))
            return value
        def resume(pids):
            state.resumes.append((state.now, list(pids)))
            return [102] if resumed is None else resumed
        monkeypatch.setattr(compute, "_check_model_loaded", observation)
        monkeypatch.setattr(compute, "resume_compute_jobs", resume)
        compute.start_resume_monitor("model", [101, 102], callback=state.callbacks.append,
                                     poll_interval=1, idle_wait=2, timeout=timeout)
        assert path.read_text() == "pending pause evidence"
        return state
    return run


@pytest.mark.parametrize("interruption", [None, True])
def test_unknown_or_loaded_observation_restarts_full_idle_window(monitor, interruption):
    result = monitor([False, False, interruption, False, False, False, False])
    assert result.resumes == [(11.0, [101, 102])]
    assert result.callbacks == [[102]]  # only identities actually confirmed by resume


def test_monitor_timeout_keeps_receipts_and_never_resumes(monitor, caplog):
    result = monitor([None, None, None], timeout=4)
    assert result.resumes == [] and result.callbacks == []
    assert "reason=monitor_timeout" in caplog.text


def test_monitor_needs_budget_for_final_double_check(monitor):
    result = monitor([False, False, False], timeout=6)
    assert result.resumes == [] and result.callbacks == []


def test_unknown_final_double_check_cannot_resume(monitor):
    result = monitor([False, False, False, None], timeout=10)
    assert result.resumes == [] and result.callbacks == []


def test_old_pause_handle_cannot_resume_a_later_pause_of_the_same_process(processes):
    processes.add(101)
    original = pause(101)
    assert compute.resume_compute_jobs(original) == [101]
    replacement = pause(101)
    before = processes.receipt.read_bytes()
    assert compute.resume_compute_jobs(original) == []
    assert processes.receipt.read_bytes() == before
    assert processes.signals == [(101, signal.SIGSTOP), (101, signal.SIGCONT),
                                 (101, signal.SIGSTOP)]
    assert compute.resume_compute_jobs(replacement) == [101]


@pytest.mark.parametrize("plain_pid_list", [False, True])
def test_delayed_monitor_cannot_adopt_a_replacement_pause(processes, monkeypatch, plain_pid_list):
    processes.add(101)
    original = pause(101)
    threads = []
    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target
            threads.append(self)
        def start(self):
            pass
    monkeypatch.setattr(compute.threading, "Thread", DeferredThread)
    compute.start_resume_monitor("model", list(original) if plain_pid_list else original,
                                 poll_interval=1, idle_wait=2, timeout=20)
    assert compute.resume_compute_jobs(original) == [101]
    replacement = pause(101)
    before = processes.receipt.read_bytes()
    now = [0.0]
    monkeypatch.setattr(compute.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(compute.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    threads[0].target()
    assert processes.receipt.read_bytes() == before
    assert processes.signals == [(101, signal.SIGSTOP), (101, signal.SIGCONT),
                                 (101, signal.SIGSTOP)]
    assert compute.resume_compute_jobs(replacement) == [101]


@pytest.mark.parametrize("status", [
    None, {}, {"active_compute_jobs": None}, {"active_compute_jobs": {}},
    {"active_compute_jobs": ["invalid"]}, {"active_compute_jobs": [{}]},
    {"active_compute_jobs": [{"pid": True}]}, {"active_compute_jobs": [{"pid": 0}]},
    {"active_compute_jobs": [{"pid": 101}, {"pid": 101}]},
])
def test_malformed_active_compute_status_is_not_empty_pause_admission(processes, status):
    processes.add(101)
    with pytest.raises(compute.ComputePauseError) as refusal:
        compute.pause_compute_jobs(status)
    assert refusal.value.paused_pids == []
    assert processes.signals == []


def test_unsupported_platform_is_pause_refusal(processes, monkeypatch):
    monkeypatch.delattr(signal, "SIGSTOP")
    with pytest.raises(compute.ComputePauseError, match="unsupported_platform"):
        pause(101)
    assert processes.signals == []


def test_partial_pause_refusal_exposes_only_confirmed_owned_pids_for_selective_recovery(processes):
    processes.add(101)
    second = processes.add(102)
    second.fail_signal.add(signal.SIGSTOP)
    with pytest.raises(compute.ComputePauseError, match="pause_signal_unconfirmed") as refusal:
        pause(101, 102)
    owned = refusal.value.paused_pids
    assert owned == [101]
    assert len(owned.pause_receipts) == 1
    assert compute.recover_paused_jobs(paused_pids=owned) == [101]
    saved = json.loads(processes.receipt.read_text())
    assert saved["paused_pids"] == [102]
    assert saved["processes"][0]["state"] == "pause_unconfirmed"
    assert compute.get_effective_keep_alive() == "5m"


def test_selected_recovery_does_not_adopt_unrelated_confirmed_pauses(processes):
    processes.add(101)
    processes.add(102)
    first, second = pause(101), pause(102)
    assert compute.recover_paused_jobs(paused_pids=first) == [101]
    assert json.loads(processes.receipt.read_text())["paused_pids"] == [102]
    assert processes.instances[102].state == psutil.STATUS_STOPPED
    assert compute.recover_paused_jobs(paused_pids=[]) == []
    assert compute.recover_paused_jobs(paused_pids=second) == [102]
