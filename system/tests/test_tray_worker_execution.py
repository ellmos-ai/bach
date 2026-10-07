"""Tray coordination has no TaskDB writes, model calls or timeout retries."""
import json
from unittest.mock import Mock

import pytest

from hub._services.chat.tray_worker_execution import NativeWorkerObserver


INSTANCE = "a" * 32
REQUEST = "b" * 32
GENERATION = "c" * 32
WORKER = "buddha_always_on"


def receipt(state="idle", request_id=None, instance=INSTANCE, generation=None):
    return {"schema": "bach.worker-execution.v1", "service_instance": instance,
            "worker_id": WORKER, "start_request_id": request_id, "generation": generation,
            "state": state, "terminal": state == "terminal",
            "worker_thread_started": True if state in ("running", "finishing", "terminal") else None,
            "worker_status": "running" if state == "running" else "idle",
            "completed_task_ids": [], "reviewed_task_ids": [], "error_code": None}


def response(value):
    return 200, {"ok": True, "execution": value}


def observer(tmp_path, request):
    return NativeWorkerObserver("http://testhost:8081", tmp_path / "intent.json", request)


def test_intent_is_durable_before_the_single_start_post(tmp_path):
    calls = []
    def request(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return response(receipt())
        saved = json.loads((tmp_path / "intent.json").read_text(encoding="utf-8"))
        assert saved["intent"]["start_request_id"] == body["start_request_id"]
        assert body == {"id": WORKER, "start_request_id": saved["intent"]["start_request_id"],
                        "expected_service_instance": INSTANCE}
        return response(receipt("running", body["start_request_id"], generation=GENERATION))
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    assert client.execution["state"] == "running"
    assert client.intent["generation"] == GENERATION
    assert [c[0] for c in calls] == ["GET", "POST"]


def test_lost_start_response_is_only_read_back_even_after_tray_restart(tmp_path):
    calls = []
    def request(method, path, body=None):
        calls.append((method, path, body))
        return response(receipt()) if method == "GET" else (None, None)
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    intent = dict(client.intent)
    assert client.status == "unconfirmed"
    calls.clear()
    restarted = observer(tmp_path, lambda *args: (calls.append(args) or (409, {"service_instance": INSTANCE})))
    restarted.step(allow_start=True)
    restarted.step(allow_start=True)
    assert restarted.intent == intent
    assert calls and all(c[0] == "GET" and "start_request_id=" + intent["start_request_id"] in c[1] for c in calls)


@pytest.mark.parametrize("result", [(None, None), (404, {}), (409, {"service_instance": "d" * 32}),
    response(receipt("running", REQUEST, generation=GENERATION)),
    response(receipt("terminal", REQUEST, instance="d" * 32, generation=GENERATION))])
def test_missing_or_foreign_receipt_never_releases_unknown_start(tmp_path, result):
    client = observer(tmp_path, Mock(side_effect=[response(receipt()), (None, None)]))
    client.step(allow_start=True)
    original = dict(client.intent)
    client.request = Mock(return_value=result)
    client.step(allow_start=True)
    assert client.intent == original and client.status == "unconfirmed"
    assert client.request.call_count == 1 and client.request.call_args.args[0] == "GET"


def test_existing_native_run_is_adopted_without_another_start(tmp_path):
    request = Mock(return_value=response(receipt("running", REQUEST, generation=GENERATION)))
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    client.step(allow_start=True)
    assert client.intent["start_request_id"] == REQUEST
    assert all(c.args[0] == "GET" for c in request.call_args_list)


def test_finishing_is_not_terminal_and_generation_cannot_change(tmp_path):
    request = Mock(return_value=response(receipt("running", REQUEST, generation=GENERATION)))
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    request.return_value = response(receipt("finishing", REQUEST, generation=GENERATION))
    client.step(allow_start=False)
    assert client.intent is not None and client.status == "finishing"
    request.return_value = response(receipt("terminal", REQUEST, generation="d" * 32))
    client.step(allow_start=True)
    assert client.intent is not None and client.status == "unconfirmed"
    request.return_value = response(receipt("terminal", REQUEST, generation=GENERATION))
    client.step(allow_start=False)
    assert client.intent is None and client.status == "terminal"
    assert json.loads((tmp_path / "intent.json").read_text(encoding="utf-8"))["intent"] is None


@pytest.mark.parametrize("data", ["bad JSON", "{}", '{"schema":"bach.tray-intent.v1","base_url":"foreign","intent":null}'])
def test_corrupt_or_foreign_durable_state_blocks_all_network(tmp_path, data):
    (tmp_path / "intent.json").write_text(data, encoding="utf-8")
    request = Mock()
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    assert client.status == "unconfirmed"
    request.assert_not_called()
    assert (tmp_path / "intent.json").read_text(encoding="utf-8") == data


def test_persistence_failure_prevents_post(tmp_path, monkeypatch):
    request = Mock(return_value=response(receipt()))
    client = observer(tmp_path, request)
    monkeypatch.setattr(client, "_save", Mock(side_effect=OSError("disk unavailable")))
    client.step(allow_start=True)
    client.step(allow_start=True)
    assert client.status == "unconfirmed"
    assert request.call_count == 1 and request.call_args.args[0] == "GET"


@pytest.mark.parametrize("changes", [{"terminal": True}, {"worker_id": "other"},
    {"worker_thread_started": 1}, {"start_request_id": True}, {"generation": "wrong"},
    {"service_instance": None}, {"state": "other"}, {"completed_task_ids": [True]}])
def test_malformed_receipts_do_not_authorize_start(tmp_path, changes):
    value = receipt()
    value.update(changes)
    request = Mock(return_value=response(value))
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    assert client.status == "unconfirmed"
    assert request.call_count == 1 and request.call_args.args[0] == "GET"


def test_disabled_observer_never_creates_an_execution(tmp_path):
    request = Mock(return_value=response(receipt()))
    client = observer(tmp_path, request)
    client.step(allow_start=False)
    assert all(c.args[0] == "GET" for c in request.call_args_list)
    assert not (tmp_path / "intent.json").exists()


def tray(tmp_path, monkeypatch):
    import sys
    from unittest.mock import MagicMock
    for name in ("pystray", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont"):
        monkeypatch.setitem(sys.modules, name, MagicMock())
    from hub._services.chat.chat_tray import BACHTray
    client = BACHTray(host="testhost", execution_state_path=tmp_path / "intent.json")
    client.state["connected"] = True
    client.slots = {WORKER: {"id": WORKER, "enabled": True, "pause_info": {"is_paused": False},
                           "model": "actual-model", "mode": "safe", "max_tool_rounds": 7}}
    client._update_icon = Mock()
    return client


def test_tray_only_starts_the_native_controller_and_does_not_count_or_commit(tmp_path, monkeypatch):
    client = tray(tmp_path, monkeypatch)
    calls = []
    def request(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return response(receipt())
        return response(receipt("running", body["start_request_id"], generation=GENERATION))
    client._worker_request = request
    client._api = Mock(side_effect=AssertionError("Tray must not claim tasks or call chat"))
    client._process_idle_task()
    assert [c[1] for c in calls] == ["/api/workers/execution?id=" + WORKER, "/api/workers/run"]
    assert set(calls[-1][2]) == {"id", "start_request_id", "expected_service_instance"}
    assert client.idle_processing is False
    assert client._native_worker.status == "running"


@pytest.mark.parametrize("gate", ["disabled", "pause", "host", "disconnected", "missing", "malformed"])
def test_tray_checks_actual_slot_and_host_gates_before_start(tmp_path, monkeypatch, gate):
    client = tray(tmp_path, monkeypatch)
    if gate == "disabled": client.slots[WORKER]["enabled"] = False
    if gate == "pause": client.slots[WORKER]["pause_info"]["is_paused"] = True
    if gate == "host": client.idle_enabled = False
    if gate == "disconnected": client.state["connected"] = False
    if gate == "missing": client.slots = {}
    if gate == "malformed": client.slots[WORKER]["enabled"] = "true"
    request = Mock(return_value=response(receipt()))
    client._worker_request = request
    client._process_idle_task()
    assert all(c.args[0] == "GET" for c in request.call_args_list)


def test_tray_legacy_timeout_is_not_released_by_history_or_elapsed_time(tmp_path, monkeypatch):
    client = tray(tmp_path, monkeypatch)
    client.idle_pending = (42, 0, "Old task", "idle-bach-42-old")
    client._api = Mock(return_value={"ok": True, "completed_task_ids": [42]})
    client._worker_request = Mock()
    client._process_idle_task()
    assert client.idle_pending is not None
    assert client._settle_pending_task() is False
    client._worker_request.assert_not_called()
    client._api.assert_not_called()


def test_tray_running_label_needs_actual_native_inference(tmp_path, monkeypatch):
    client = tray(tmp_path, monkeypatch)
    slot = client.slots[WORKER]
    client.idle_processing = True
    client.state["connected"] = False
    assert "Running" not in client._always_on_runtime_label(slot)
    client.state["connected"] = True
    client.state["compute_turn"] = {"active": True, "priority": "background", "chat_id": "idle-old"}
    assert "Running" not in client._always_on_runtime_label(slot)
    client.state["compute_turn"]["chat_id"] = WORKER
    assert client._always_on_runtime_label(slot) == "Running · bearbeitet eine Aufgabe"


def test_disabling_slot_does_not_hide_an_inference_still_ending(tmp_path, monkeypatch):
    client = tray(tmp_path, monkeypatch)
    slot = client.slots[WORKER]
    slot["enabled"] = False
    client.state["compute_turn"] = {"active": True, "priority": "background", "chat_id": WORKER}
    assert client._always_on_runtime_label(slot) == "Running · beendet aktuellen Schritt"


@pytest.mark.parametrize("state, label", [("starting", "Living · Start wird geprüft"),
    ("stopping", "Living · Beendigung läuft"), ("finishing", "Living · Beendigung läuft"),
    ("unconfirmed", "Living · Laufstatus nicht bestätigt")])
def test_tray_labels_admission_and_thread_tail_without_claiming_inference(tmp_path, monkeypatch, state, label):
    client = tray(tmp_path, monkeypatch)
    client._native_worker.intent = {"start_request_id": REQUEST}
    client._native_worker.status = state
    assert client._always_on_runtime_label(client.slots[WORKER]) == label


@pytest.mark.parametrize("gate", ["disabled", "pause", "host"])
def test_disabled_tray_observes_but_does_not_create_recurring_tasks(tmp_path, monkeypatch, gate):
    from hub._services.chat import chat_tray
    client = tray(tmp_path, monkeypatch)
    if gate == "disabled": client.slots[WORKER]["enabled"] = False
    if gate == "pause": client.slots[WORKER]["pause_info"]["is_paused"] = True
    if gate == "host": client.idle_enabled = False
    client._recurring_tick = 179
    recurring = Mock()
    monkeypatch.setattr(chat_tray, "HAS_RECURRING", True)
    monkeypatch.setattr(chat_tray, "check_recurring_tasks", recurring, raising=False)
    start = Mock()
    monkeypatch.setattr(chat_tray.threading, "Thread", Mock(return_value=Mock(start=start)))
    client._idle_tick()
    recurring.assert_not_called()
    start.assert_called_once()


def test_host_start_flag_does_not_claim_existing_worker_has_stopped(tmp_path, monkeypatch):
    client = tray(tmp_path, monkeypatch)
    client.idle_enabled = False
    client.state["compute_turn"] = {"active": True, "priority": "background", "chat_id": WORKER}
    assert client._always_on_runtime_label(client.slots[WORKER]) == "Running · Hoststart deaktiviert"


@pytest.mark.parametrize("result", [(200, None), (200, []), (True, {"ok": True, "execution": receipt()})])
def test_non_object_or_non_http_receipt_is_unknown(tmp_path, result):
    client = observer(tmp_path, Mock(return_value=result))
    client.step(allow_start=True)
    assert client.status == "unconfirmed" and client.intent is None


@pytest.mark.parametrize("result", [(200, None), (200, []), (200, {"ok": True})])
def test_malformed_pending_readback_keeps_the_durable_intent(tmp_path, result):
    client = observer(tmp_path, Mock(side_effect=[response(receipt()), (None, None)]))
    client.step(allow_start=True)
    original = dict(client.intent)
    client.request = Mock(return_value=result)
    client.step(allow_start=True)
    assert client.intent == original and client.status == "unconfirmed"


def test_competing_native_reservation_is_observed_after_definitive_409(tmp_path):
    def request(method, path, body=None):
        if method == "GET": return response(receipt())
        return 409, {"ok": False, "execution": receipt("running", REQUEST, generation=GENERATION),
                    "admission": {"admitted": False, "worker_id": WORKER,
                        "start_request_id": body["start_request_id"], "service_instance": INSTANCE}}
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    assert client.intent["start_request_id"] == REQUEST
    assert client.status == "running"
    client.request = Mock(return_value=response(receipt("running", REQUEST, generation=GENERATION)))
    client.step(allow_start=True)
    assert client.request.call_args.args[0] == "GET"


@pytest.mark.parametrize("state", ["starting", "stopping", "unconfirmed"])
def test_native_nonterminal_states_always_retain_ownership(tmp_path, state):
    request = Mock(return_value=response(receipt(state, REQUEST, generation=GENERATION)))
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    client.step(allow_start=True)
    assert client.intent is not None and client.status == state
    assert all(c.args[0] == "GET" for c in request.call_args_list)


@pytest.mark.parametrize("code", [None, 301, 302, 500])
def test_unknown_post_status_cannot_supply_terminal_proof(tmp_path, code):
    def request(method, path, body=None):
        if method == "GET": return response(receipt())
        return code, {"execution": receipt("terminal", body["start_request_id"], generation=GENERATION)}
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    assert client.intent is not None and client.status == "unconfirmed"


@pytest.mark.parametrize("code", [403, 404, 503])
def test_correlated_pre_admission_denial_clears_only_this_start_intent(tmp_path, code):
    def request(method, path, body=None):
        if method == "GET": return response(receipt())
        return code, {"admission": {"admitted": False, "worker_id": WORKER,
            "start_request_id": body["start_request_id"], "service_instance": INSTANCE}}
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    assert client.intent is None and client.status == "denied"


@pytest.mark.parametrize("change", [{"admitted": 0}, {"start_request_id": REQUEST},
                                  {"service_instance": "d" * 32}, {"worker_id": "other"}])
def test_unmatched_no_admission_claim_is_not_a_restart_permission(tmp_path, change):
    def request(method, path, body=None):
        if method == "GET": return response(receipt())
        admission = {"admitted": False, "worker_id": WORKER,
                     "start_request_id": body["start_request_id"], "service_instance": INSTANCE}
        return 403, {"admission": {**admission, **change}}
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    assert client.intent is not None and client.status == "unconfirmed"


def test_worker_http_preserves_denied_status_and_uses_only_control_auth(tmp_path, monkeypatch):
    import io
    import urllib.error
    from hub._services.chat import chat_tray
    client = tray(tmp_path, monkeypatch)
    client.control_api_auth_header = "Bearer control-test"
    client.gui_auth_header = "Bearer gui-test"
    seen = []
    class Opener:
        def open(self, request, timeout):
            seen.append((request, timeout))
            raise urllib.error.HTTPError(request.full_url, 409, "Conflict", {},
                                         io.BytesIO(b'{"error":"start unknown"}'))
    handlers = []
    def opener(*args):
        handlers.extend(args)
        return Opener()
    monkeypatch.setattr(chat_tray.urllib.request, "build_opener", opener)
    assert client._worker_request("POST", "/api/workers/run", {"id": WORKER}) == (
        409, {"error": "start unknown"})
    assert len(seen) == 1 and seen[0][0].get_header("Authorization") == "Bearer control-test"
    assert seen[0][0].full_url == client.base_url + "/api/workers/run"
    assert handlers[0].proxies == {}
    assert handlers[1].redirect_request(None, None, 302, "", {}, "http://foreign") is None


@pytest.mark.parametrize("body", [b"bad json", b"[]", b"x" * (1024 * 1024 + 1)],
                         ids=["invalid-json", "non-object", "over-cap"])
def test_worker_http_has_bounded_object_responses(tmp_path, monkeypatch, body):
    import io
    from hub._services.chat import chat_tray
    client = tray(tmp_path, monkeypatch)
    response_file = io.BytesIO(body)
    response_file.code = 200
    opener = Mock()
    opener.open.return_value = response_file
    monkeypatch.setattr(chat_tray.urllib.request, "build_opener", Mock(return_value=opener))
    code, value = client._worker_request("GET", "/api/workers/execution?id=" + WORKER)
    assert value is None
    opener.open.assert_called_once()


def test_host_stop_is_durable_and_fenced_to_the_observed_generation(tmp_path):
    calls = []
    def request(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET": return response(receipt("running", REQUEST, generation=GENERATION))
        saved = json.loads((tmp_path / "intent.json").read_text(encoding="utf-8"))
        assert saved["intent"]["stop_requested"] is True
        assert path == "/api/workers/stop"
        assert body == {"id": WORKER, "expected_service_instance": INSTANCE,
                        "expected_start_request_id": REQUEST, "expected_generation": GENERATION}
        return 409, {"ok": False, "execution": receipt("stopping", REQUEST, generation=GENERATION)}
    client = observer(tmp_path, request)
    client.step(allow_start=False, request_stop=True)
    assert client.intent["stop_requested"] is True and client.status == "stopping"
    assert [c[0] for c in calls] == ["GET", "POST"]


@pytest.mark.parametrize("result", [(None, None), (403, {}), (409, {}),
    response(receipt("terminal", REQUEST, instance="d" * 32, generation=GENERATION))])
def test_unknown_stop_is_not_repeated_after_timeout_or_restart(tmp_path, result):
    request = Mock(side_effect=[response(receipt("running", REQUEST, generation=GENERATION)), result])
    client = observer(tmp_path, request)
    client.step(allow_start=False, request_stop=True)
    assert client.intent is not None and client.intent["stop_requested"] is True
    restarted = observer(tmp_path, Mock(return_value=response(receipt("running", REQUEST, generation=GENERATION))))
    for _ in range(3): restarted.step(allow_start=False, request_stop=True)
    assert all(c.args[0] == "GET" for c in restarted.request.call_args_list)
    restarted.request.return_value = response(receipt("terminal", REQUEST, generation=GENERATION))
    restarted.step(allow_start=False, request_stop=True)
    assert restarted.intent is None


def test_unconfirmed_start_without_generation_cannot_receive_stop(tmp_path):
    request = Mock(side_effect=[response(receipt()), (None, None)])
    client = observer(tmp_path, request)
    client.step(allow_start=True)
    client.request = Mock(return_value=(409, {}))
    client.step(allow_start=False, request_stop=True)
    assert client.intent["generation"] is None
    assert all(c.args[0] == "GET" for c in client.request.call_args_list)


@pytest.mark.parametrize("state", ["idle", "terminal", "stopping", "finishing"])
def test_stop_gate_never_starts_or_repeats_an_ending_worker(tmp_path, state):
    value = receipt(state, REQUEST if state != "idle" else None,
                    generation=GENERATION if state != "idle" else None)
    request = Mock(return_value=response(value))
    client = observer(tmp_path, request)
    client.step(allow_start=True, request_stop=True)
    assert all(c.args[0] == "GET" for c in request.call_args_list)


@pytest.mark.parametrize("gate", ["disabled", "host", "pause", "foreground"])
def test_tray_stops_disabled_host_or_slot_but_preserves_cooldown_and_foreground(tmp_path, monkeypatch, gate):
    client = tray(tmp_path, monkeypatch)
    if gate == "disabled": client.slots[WORKER]["enabled"] = False
    if gate == "host": client.idle_enabled = False
    if gate == "pause": client.slots[WORKER]["pause_info"]["is_paused"] = True
    if gate == "foreground": client.state["compute_turn"] = {"active": True, "priority": "foreground"}
    client._worker_request = Mock(return_value=response(receipt("running", REQUEST, generation=GENERATION)))
    client._process_idle_task()
    posts = [c for c in client._worker_request.call_args_list if c.args[0] == "POST"]
    assert bool(posts) == (gate in {"disabled", "host"})
    if posts: assert posts[0].args[1] == "/api/workers/stop"
