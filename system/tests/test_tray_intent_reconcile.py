"""Explicit tray-intent reconciliation never invents a terminal execution."""
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from hub import agent_process_provider
from hub._services.chat import slots_config, telegram_chat
from hub._services.chat.tray_worker_execution import NativeWorkerObserver

OLD = "a" * 32
REQUEST = "b" * 32
GENERATION = "c" * 32
CURRENT = "d" * 32
VERSION = "e" * 64
TASK = 2034
WORKER = "buddha_always_on"


def request(mode="retire_unconfirmed"):
    return {"schema": "bach.tray-intent-reconcile-request.v1", "mode": mode,
            "actor": "operator@example", "worker_id": WORKER,
            "service_instance": OLD, "start_request_id": REQUEST,
            "generation": None, "intent_sha256": "f" * 64,
            "expected_current_service_instance": CURRENT,
            "target_task_id": TASK, "target_task_version": VERSION}


class NativeClient:
    def __init__(self):
        self.leased = False
        self.result = None
        self.worker_lease_rows = []

    def read(self, task_id):
        assert task_id == TASK
        return SimpleNamespace(leased=self.leased, status="pending", task_version=VERSION)

    def task_result_snapshot(self, task_id):
        assert task_id == TASK
        return {"verified": True, "status": "pending", "task_version": VERSION,
                "result": self.result}

    def worker_leases(self, worker_id):
        assert worker_id == "worker-" + "1" * 32 + "@testhost"
        return {"leases": self.worker_lease_rows}


@pytest.fixture
def backend(monkeypatch):
    client = NativeClient()
    slot = {"id": WORKER, "enabled": False, "task_id": None}

    @contextmanager
    def transaction():
        yield lambda **kwargs: None

    monkeypatch.setattr(telegram_chat, "_WORKER_SERVICE_INSTANCE", CURRENT)
    monkeypatch.setattr(telegram_chat, "_WORKER_EXECUTIONS", {})
    monkeypatch.setattr(telegram_chat, "_active_worker_control", lambda worker: (None, None))
    monkeypatch.setattr(telegram_chat, "_native_task_client", lambda: client)
    monkeypatch.setattr(slots_config, "worker_admission_transaction", transaction)
    monkeypatch.setattr(slots_config, "get_always_on_execution_slot", lambda: slot)
    monkeypatch.setattr(agent_process_provider, "inspect_process_identity",
                        lambda record: ("gone", None))
    monkeypatch.setattr(telegram_chat.socket, "gethostname", lambda: "testhost")
    return client, slot


def marker():
    return {"schema": "bach.worker-controller-run.v1", "phase": "admitted",
            "worker_id": WORKER, "host": "testhost", "pid": 1234,
            "process_create_time": 1.0, "durable": True,
            "prior_runs_unconfirmed": False, "service_instance": OLD,
            "start_request_id": REQUEST, "generation": GENERATION,
            "physical_worker_id": "worker-" + "1" * 32,
            "lease_worker_id": "worker-" + "1" * 32 + "@testhost"}


def test_legacy_requires_explicit_retire_and_does_not_complete_task(backend):
    client, _ = backend
    response, code = telegram_chat.prepare_tray_intent_reconciliation(request())
    assert code == 200 and response["proof"]["mode"] == "retire_unconfirmed"
    assert response["proof"]["effect"] == "tray_intent_only"
    assert response["proof"]["old_execution_terminal"] is False
    assert response["proof"]["claimed_actor"] == "operator@example"
    assert response["proof"]["actor_verified"] is False
    assert response["proof"]["authority_kind"] == "control_api_authorized"
    assert client.result is None
    assert telegram_chat.prepare_tray_intent_reconciliation(request("confirmed_inactive"))[1] == 409


def test_exact_durable_dead_owner_and_free_leases_can_confirm(backend):
    _, slot = backend
    slot["_controller_run"] = marker()
    response, code = telegram_chat.prepare_tray_intent_reconciliation(request("confirmed_inactive"))
    assert code == 200 and response["proof"]["mode"] == "confirmed_inactive"
    assert telegram_chat.prepare_tray_intent_reconciliation(request())[1] == 409


@pytest.mark.parametrize("change", ["lease", "result", "enabled", "task", "service", "actor",
                                     "marker_lease", "marker_foreign"])
def test_conflicting_or_unverified_proof_fails_closed(backend, change):
    client, slot = backend
    value = request()
    if change == "lease":
        client.leased = True
    if change == "result":
        client.result = {"id": 1}
    if change == "enabled":
        slot["enabled"] = True
    if change == "task":
        slot["task_id"] = TASK + 1
    if change == "service":
        value["expected_current_service_instance"] = "1" * 32
    if change == "actor":
        value["actor"] = ""
    if change == "marker_lease":
        slot["_controller_run"] = marker()
        client.worker_lease_rows = [{"task_id": 1}]
    if change == "marker_foreign":
        slot["_controller_run"] = {**marker(), "host": "otherhost"}
    assert telegram_chat.prepare_tray_intent_reconciliation(value)[1] in {400, 409, 503}


def _idle():
    return {"schema": "bach.worker-execution.v1", "service_instance": CURRENT,
            "worker_id": WORKER, "start_request_id": None, "generation": None,
            "state": "idle", "terminal": False, "worker_thread_started": None,
            "completed_task_ids": [], "reviewed_task_ids": []}


def _running():
    return {**_idle(), "start_request_id": "1" * 32, "generation": "2" * 32,
            "state": "running", "worker_thread_started": True}


def _intent_file(tmp_path):
    path = tmp_path / "intent.json"
    path.write_text(json.dumps({"schema": "bach.tray-intent.v1",
        "base_url": "http://testhost:8081", "intent": {"worker_id": WORKER,
        "service_instance": OLD, "start_request_id": REQUEST,
        "generation": None}}) + "\n", encoding="utf-8")
    return path


def test_tray_retires_only_matching_bytes_after_two_idle_reads(tmp_path):
    path = _intent_file(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []
    def transport(method, route, body=None):
        calls.append(method)
        if method == "GET":
            return 200, {"ok": True, "execution": _idle()}
        assert body["intent_sha256"] == digest
        proof = {**body, "schema": "bach.tray-intent-reconcile-proof.v1",
                 "claimed_actor": body["actor"], "actor_verified": False,
                 "authority_kind": "control_api_authorized",
                 "current_service_instance": body["expected_current_service_instance"],
                 "target_binding": "guarded_reference",
                 "effect": "tray_intent_only", "old_execution_terminal": False}
        del proof["expected_current_service_instance"]
        del proof["actor"]
        return 200, {"ok": True, "proof": proof}
    observer = NativeWorkerObserver("http://testhost:8081", path, transport)
    proof = observer.retire_unconfirmed(actor="operator@example", intent_sha256=digest,
                                        target_task_id=TASK, target_task_version=VERSION)
    assert calls == ["GET", "POST", "GET"]
    assert observer.intent is None and observer.status == "retired_unconfirmed"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema"] == "bach.tray-intent.v2" and saved["intent"] is None
    assert saved["retired_unconfirmed"] == proof
    assert proof["old_execution_terminal"] is False


def test_tray_aborts_if_current_run_changes_between_proof_and_cas(tmp_path):
    path = _intent_file(tmp_path)
    before = path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    count = 0
    def transport(method, route, body=None):
        nonlocal count
        if method == "GET":
            count += 1
            return 200, {"ok": True, "execution": _idle() if count == 1 else _running()}
        proof = {**body, "schema": "bach.tray-intent-reconcile-proof.v1",
                 "claimed_actor": body["actor"], "actor_verified": False,
                 "authority_kind": "control_api_authorized",
                 "current_service_instance": CURRENT,
                 "target_binding": "guarded_reference",
                 "effect": "tray_intent_only", "old_execution_terminal": False}
        del proof["expected_current_service_instance"]
        del proof["actor"]
        return 200, {"ok": True, "proof": proof}
    observer = NativeWorkerObserver("http://testhost:8081", path, transport)
    with pytest.raises(ValueError, match="changed"):
        observer.retire_unconfirmed(actor="operator@example", intent_sha256=digest,
                                    target_task_id=TASK, target_task_version=VERSION)
    assert path.read_bytes() == before


def test_tray_aborts_if_intent_changes_during_server_readback(tmp_path):
    path = _intent_file(tmp_path)
    before = path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    def transport(method, route, body=None):
        if method == "GET":
            return 200, {"ok": True, "execution": _idle()}
        path.write_bytes(before + b" ")
        proof = {**body, "schema": "bach.tray-intent-reconcile-proof.v1",
                 "claimed_actor": body["actor"], "actor_verified": False,
                 "authority_kind": "control_api_authorized",
                 "current_service_instance": CURRENT, "target_binding": "guarded_reference",
                 "effect": "tray_intent_only", "old_execution_terminal": False}
        del proof["expected_current_service_instance"]
        del proof["actor"]
        return 200, {"ok": True, "proof": proof}
    observer = NativeWorkerObserver("http://testhost:8081", path, transport)
    with pytest.raises(ValueError):
        observer.retire_unconfirmed(actor="operator@example", intent_sha256=digest,
                                    target_task_id=TASK, target_task_version=VERSION)
    assert path.read_bytes() != before


def test_core_admission_record_is_durable_in_existing_slot(tmp_path):
    path = tmp_path / "slots.json"
    slots_config.initialize_slots_config(str(path))
    with slots_config.worker_admission_transaction(str(path)) as advance:
        advance(controller_run=marker())
    stored = slots_config.load_slots_config(str(path), strict=True)
    assert stored["slots"][WORKER]["_controller_run"] == marker()
    assert stored["admission_revision"]


def test_running_tray_observes_only_exact_external_retirement(tmp_path):
    path = _intent_file(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []
    def transport(method, route, body=None):
        calls.append((method, route))
        if method == "GET" and "start_request_id=" in route:
            return 409, {"service_instance": CURRENT}
        if method == "GET":
            return 200, {"ok": True, "execution": _idle()}
        proof = {**body, "schema": "bach.tray-intent-reconcile-proof.v1",
                 "claimed_actor": body["actor"], "actor_verified": False,
                 "authority_kind": "control_api_authorized",
                 "current_service_instance": CURRENT,
                 "target_binding": "guarded_reference",
                 "effect": "tray_intent_only", "old_execution_terminal": False}
        del proof["expected_current_service_instance"]
        del proof["actor"]
        return 200, {"ok": True, "proof": proof}
    tray = NativeWorkerObserver("http://testhost:8081", path, transport)
    tray.step(allow_start=False)
    assert tray.intent is not None and tray.status == "unconfirmed"
    operator = NativeWorkerObserver("http://testhost:8081", path, transport)
    operator.retire_unconfirmed(actor="operator@example", intent_sha256=digest,
                                target_task_id=TASK, target_task_version=VERSION)
    before = len(calls)
    tray.step(allow_start=True)
    assert len(calls) == before
    assert tray.intent is None and tray.status == "retired_unconfirmed"


def test_local_cli_inspect_reads_only_canonical_intent(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    from hub._services.chat.tray_worker_execution import main
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    base_url = "http://127.0.0.1:8081"
    path = tmp_path / ".bach" / f"bach_worker_{hashlib.sha256(base_url.encode()).hexdigest()[:24]}.json"
    path.parent.mkdir()
    raw = json.dumps({"schema": "bach.tray-intent.v1", "base_url": base_url,
        "intent": {"worker_id": WORKER, "service_instance": OLD,
                   "start_request_id": REQUEST, "generation": None}}).encode()
    path.write_bytes(raw)
    assert main(["inspect"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["intent_sha256"] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw


def test_malformed_public_reconcile_mode_is_controlled(backend):
    value = request()
    value["mode"] = []
    response, code = telegram_chat.prepare_tray_intent_reconciliation(value)
    assert code == 400 and "error" in response


def test_foreign_generation_cannot_confirm_old_admission(backend):
    _, slot = backend
    slot["_controller_run"] = marker()
    value = request("confirmed_inactive")
    value["generation"] = "1" * 32
    assert telegram_chat.prepare_tray_intent_reconciliation(value)[1] == 409


def test_malformed_tray_schema_blocks_without_network(tmp_path):
    path = _intent_file(tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["schema"] = []
    path.write_text(json.dumps(saved), encoding="utf-8")
    calls = []
    client = NativeWorkerObserver("http://testhost:8081", path,
                                  lambda *args: calls.append(args))
    client.step(allow_start=True)
    assert client.status == "unconfirmed" and client.intent is None and calls == []


def test_reconcile_route_is_behind_control_auth_gate(monkeypatch):
    called = []
    handler = telegram_chat.ControlHandler.__new__(telegram_chat.ControlHandler)
    handler.path = "/api/workers/tray-intent/reconcile"
    handler._allow_json_post = lambda: False
    monkeypatch.setattr(telegram_chat, "prepare_tray_intent_reconciliation",
                        lambda _body: called.append(True))
    handler.do_POST()
    assert called == []


def test_unknown_old_process_cannot_use_confirmed_mode(backend, monkeypatch):
    _, slot = backend
    slot["_controller_run"] = marker()
    monkeypatch.setattr(agent_process_provider, "inspect_process_identity",
                        lambda _record: ("unavailable", None))
    assert telegram_chat.prepare_tray_intent_reconciliation(request("confirmed_inactive"))[1] == 409


def test_retirement_replay_does_not_rewrite_tombstone(tmp_path):
    path = _intent_file(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    def transport(method, route, body=None):
        if method == "GET":
            return 200, {"ok": True, "execution": _idle()}
        proof = {**body, "schema": "bach.tray-intent-reconcile-proof.v1",
                 "claimed_actor": body["actor"], "actor_verified": False,
                 "authority_kind": "control_api_authorized",
                 "current_service_instance": CURRENT, "target_binding": "guarded_reference",
                 "effect": "tray_intent_only", "old_execution_terminal": False}
        del proof["expected_current_service_instance"]
        del proof["actor"]
        return 200, {"ok": True, "proof": proof}
    first = NativeWorkerObserver("http://testhost:8081", path, transport)
    first.retire_unconfirmed(actor="operator@example", intent_sha256=digest,
                             target_task_id=TASK, target_task_version=VERSION)
    after = path.read_bytes()
    replay = NativeWorkerObserver("http://testhost:8081", path, transport)
    with pytest.raises(ValueError):
        replay.retire_unconfirmed(actor="operator@example", intent_sha256=digest,
                                  target_task_id=TASK, target_task_version=VERSION)
    assert path.read_bytes() == after


def test_actor_label_change_cannot_create_identity_authority(backend):
    one = request()
    two = request()
    two["actor"] = "another-operator"
    first, first_code = telegram_chat.prepare_tray_intent_reconciliation(one)
    second, second_code = telegram_chat.prepare_tray_intent_reconciliation(two)
    assert first_code == second_code == 200
    assert first["proof"]["claimed_actor"] != second["proof"]["claimed_actor"]
    assert first["proof"]["actor_verified"] is second["proof"]["actor_verified"] is False
    assert first["proof"]["authority_kind"] == second["proof"]["authority_kind"] == "control_api_authorized"
