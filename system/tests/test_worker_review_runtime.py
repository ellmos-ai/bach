# SPDX-License-Identifier: MIT
"""Runtime behavior for bound, independent result-review workers.

The HTTP adapter is exercised through a deterministic in-process transport;
lease persistence is an isolated fake transport. No provider, local task DB,
or native worker is started by these tests.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.llm.controller_route import bind_controller_backend, route_snapshot
from hub._services.llm.model_backend import OpenAIBackend
from hub._services.task_lease_client import LeaseAck, LeaseReleaseAck, WorkerResultAck
from hub._services.worker_result_review import ReviewGrant, _SEAL as REVIEW_GRANT_SEAL


CHAT_ID = "runtime-review-slot"
MODEL = "review-model-2026"
GENERATION = "review-generation-1"
WORKER_ID = "review-worker@HOST"
HOST = "HOST"
REVIEW_TASK_ID = 240
TARGET_TASK_ID = 120
TARGET_RESULT_ID = 901
TARGET_REVISION = "f" * 64
REVIEW_TASK_VERSION = "d" * 64


class _HTTPResponse:
    def __init__(self, body):
        self._body = copy.deepcopy(body)

    def json(self):
        return copy.deepcopy(self._body)


def _mock_openai_http(monkeypatch, responses):
    import httpx

    queue = list(copy.deepcopy(responses))
    requests = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, *, json, headers, timeout):
            requests.append({
                "url": url,
                "json": copy.deepcopy(json),
                "headers": dict(headers),
                "timeout": timeout,
            })
            if not queue:
                raise AssertionError("Unexpected extra HTTP model request")
            return _HTTPResponse(queue.pop(0))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return requests


def _tool_reply(model, name, arguments):
    return {
        "model": model,
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "fixture-call",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }],
            },
        }],
    }


class _ReviewExecutionClient:
    """In-memory stand-in for the private lease transport used by one binding."""

    mode = "local"

    def __init__(self, *, route, slot_id):
        self.route = copy.deepcopy(route)
        self.slot_id = slot_id
        self.review_task = {
            "id": REVIEW_TASK_ID,
            "title": "Independent review",
            "description": "Check the submitted result",
            "category": "WORKER-REVIEW",
            "priority": "P1",
            "project": "fixture",
            "status": "open",
            "assigned_to": "BACH",
            "assigned_slot": slot_id,
            "required_model": MODEL,
            "task_version": REVIEW_TASK_VERSION,
        }
        self.target_task = {
            "id": TARGET_TASK_ID,
            "title": "Target work",
            "description": "The task being reviewed",
            "category": "WORKER",
            "priority": "P1",
            "project": "fixture",
            "status": "review",
        }
        self.guard_calls = []
        self.start_calls = []
        self.finish_calls = []
        self.link_calls = []
        self.recorded_review_answers = []
        self.result_record = None

    def task_snapshot(self, task_id):
        if task_id == TARGET_TASK_ID:
            return copy.deepcopy(self.target_task)
        if task_id == REVIEW_TASK_ID:
            return copy.deepcopy(self.review_task)
        raise AssertionError(f"Unexpected task snapshot: {task_id}")

    def acquire(self, task_id, *, worker_id, host, task_version,
                result_generation, **_kwargs):
        assert task_id == REVIEW_TASK_ID
        now = datetime.now(timezone.utc)
        fmt = lambda value: value.isoformat(timespec="seconds").replace("+00:00", "Z")
        return LeaseAck(
            task_id=task_id,
            lease_id=str(uuid.uuid4()),
            fence=77,
            worker_id=worker_id,
            host=host,
            issued_at=fmt(now),
            expires_at=fmt(now + timedelta(minutes=10)),
            ttl_profile="fixture",
            server_now=fmt(now),
            local_receive_time=now,
            task_version=task_version,
            result_generation=result_generation,
        )

    def _guard_review_dispatch(self, binding, *, route, requested_model):
        self.guard_calls.append((copy.deepcopy(route), requested_model))
        grant = getattr(binding, "_review_grant", None)
        return bool(
            grant is not None
            and isinstance(route, dict)
            and route == grant.route
            and requested_model == grant.requested_model
            and not binding.stop_requested
        )

    def _start_model_execution(self, binding, **kwargs):
        handle = object()
        self.start_calls.append((binding, copy.deepcopy(kwargs), handle))
        return handle

    def _finish_model_execution(self, binding, handle, *, result=None, failed=False, **kwargs):
        self.finish_calls.append((binding, handle, copy.deepcopy(result), failed, kwargs))
        return failed is False and isinstance(result, dict) and not result.get("error")

    def _link_model_execution(self, binding, handle):
        self.link_calls.append((binding, handle))
        return True

    def submit_result(self, task_id, *, lease_id, fence, task_version, generation, result,
                      _review_binding=None):
        from hub._services.task_result_service import validate_submission

        assert task_id == REVIEW_TASK_ID
        assert _review_binding is not None
        assert _review_binding._client is self
        assert _review_binding.task_id == task_id
        assert lease_id
        assert fence == 77
        assert task_version == REVIEW_TASK_VERSION
        _, text, digest = validate_submission({"generation": generation, "result": result})
        self.result_record = {
            "result_id": 501,
            "task_id": task_id,
            "fence": fence,
            "generation": generation,
            "task_version": task_version,
            "result_sha256": digest,
            "result": text,
            "accepted": False,
            "reason": "awaiting_review",
            "result_revision": "a" * 64,
        }
        release = LeaseReleaseAck(
            released=True,
            task_id=task_id,
            outcome="review",
            status="review",
            fence=fence,
            server_now=datetime.now(timezone.utc).isoformat(),
        )
        return WorkerResultAck(release=release, record=copy.deepcopy(self.result_record))

    def task_result_snapshot(self, task_id):
        assert task_id == REVIEW_TASK_ID
        return {
            "status": "review" if self.result_record else "open",
            "task_version": REVIEW_TASK_VERSION,
            "result": copy.deepcopy(self.result_record),
        }

    def _record_result_review(self, binding):
        grant = binding._review_grant
        self.recorded_review_answers.append(copy.deepcopy(grant._last_answer))
        return True


def _backend(*, stamp=True):
    backend = OpenAIBackend(
        base_url="https://api.openai.com/v1",
        api_key="fixture-secret-never-sent-to-route-snapshot",
        default_model=MODEL,
    )
    if stamp:
        bind_controller_backend(backend, credential_ref="env:OPENAI_API_KEY")
    return backend


def _review_binding(backend, *, slot_id=CHAT_ID, route_override=None, stop_event=None):
    route = route_snapshot(backend)
    grant_route = copy.deepcopy(route_override if route_override is not None else route)
    stop = stop_event or threading.Event()
    client = _ReviewExecutionClient(route=grant_route, slot_id=slot_id)
    grant = ReviewGrant(
        _seal=REVIEW_GRANT_SEAL,
        task_id=REVIEW_TASK_ID,
        task_version=REVIEW_TASK_VERSION,
        target_task_id=TARGET_TASK_ID,
        target_result_id=TARGET_RESULT_ID,
        target_revision=TARGET_REVISION,
        worker_id=WORKER_ID,
        host=HOST,
        generation=GENERATION,
        slot_id=slot_id,
        route=grant_route,
        requested_model=MODEL,
        principal_id="reviewer-principal",
        policy_version=3,
        identity_version=4,
        _is_current=lambda: True,
        _stop_event=stop,
    )
    binding = WorkerLeaseBinding.acquire(
        client,
        REVIEW_TASK_ID,
        worker_id=WORKER_ID,
        host=HOST,
        generation=GENERATION,
        is_current=lambda: True,
        stop_event=stop,
        slot={"id": slot_id, "model": MODEL},
        _review_grant=grant,
    )
    return client, binding, stop, route


def _runtime_for(backend, binding, *, allowed_tools=None):
    runtime = ChatRuntime(backend)
    runtime.max_tool_rounds = 3
    runtime.hook_every = 999
    runtime._get_bach_context = lambda *_args: ""
    runtime._get_memory_hook_context = lambda *_args: ""
    session = runtime.get_session(CHAT_ID)
    session.model = MODEL
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.allow_tools = True
    session.allowed_tools = allowed_tools
    return runtime, session


def _task_manage_tool():
    return {
        "type": "function",
        "function": {
            "name": "task_manage",
            "description": "Read or submit the bound review task",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "done", "submit_result", "detail", "update", "decompose"],
                    },
                    "task_id": {"type": "integer"},
                    "result": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    }


def test_chat_runtime_captures_second_http_route_and_submits_its_confirmed_answer(monkeypatch):
    backend = _backend()
    route = route_snapshot(backend)
    client, binding, _stop, _ = _review_binding(backend)
    runtime, session = _runtime_for(
        backend, binding, allowed_tools=["task_manage", "read_file", "search_text"],
    )

    review_result = json.dumps({
        "status": "findings",
        "summary": "The checked evidence supports the requested behavior.",
        "task_contract_met": False,
    }, ensure_ascii=False)
    responses = [
        _tool_reply(MODEL, "task_manage", {"action": "detail", "task_id": TARGET_TASK_ID}),
        _tool_reply(MODEL, "task_manage", {
            "action": "submit_result",
            "task_id": REVIEW_TASK_ID,
            "result": review_result,
        }),
    ]
    requests = _mock_openai_http(monkeypatch, responses)

    from hub._services.chat import worker_tool_dispatch_trace, slots_config
    from hub._services.chat.chat_runtime import _completion_reserve_tools
    from hub._services.chat.worker_tool_dispatch_trace import TracedToolOutcome

    def execute_review_tool(active_binding, name, arguments, _execute):
        assert name == "task_manage"
        return TracedToolOutcome(
            status="returned",
            result=active_binding.execute_task_manage(arguments),
            _binding=active_binding,
        )

    monkeypatch.setattr(worker_tool_dispatch_trace, "execute_normal_tool", execute_review_tool)
    monkeypatch.setattr(
        worker_tool_dispatch_trace, "acknowledge_normal_tool_result", lambda *_args: True,
    )
    monkeypatch.setattr(slots_config, "update_slot", lambda *_args, **_kwargs: None)
    def bound_worker_tools(_session, _backend, *, enabled, completion_reserve=False):
        if not enabled:
            return []
        tools = [_task_manage_tool()]
        if completion_reserve:
            return _completion_reserve_tools(tools, _session.worker_task_binding)
        return tools

    monkeypatch.setattr(runtime, "_bound_worker_tools_for_request", bound_worker_tools)

    token = runtime._compute_turn_context.set((CHAT_ID, "background"))
    try:
        answer = asyncio.run(runtime._tool_loop(
            [{"role": "system", "content": "Review only the bound target."},
             {"role": "user", "content": "Inspect target and submit findings."}],
            session,
            [_task_manage_tool()],
            backend=backend,
            model=MODEL,
        ))
    finally:
        runtime._compute_turn_context.reset(token)

    assert "Abschlussstatus wird nach Policy ermittelt" in str(answer)
    assert len(requests) == 2
    offered_actions = [
        request["json"]["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        for request in requests
    ]
    assert "detail" in offered_actions[0]
    assert offered_actions[1] == ["submit_result"]
    assert [item[1] for item in client.guard_calls if item[0] == route]  # repeated live route checks
    assert all(item[0] == route and item[1] == MODEL for item in client.guard_calls)
    assert len(client.start_calls) == 2
    assert [item[1]["route_sha256"] for item in client.start_calls] == [
        route["route_sha256"], route["route_sha256"],
    ]
    assert len(client.finish_calls) == 2
    assert all(item[3] is False for item in client.finish_calls)
    assert all(item[2]["provider_reported_model"] == MODEL for item in client.finish_calls)
    assert [item[4].get("route_sha256") for item in client.finish_calls] == [
        route["route_sha256"], route["route_sha256"],
    ]
    assert len(client.link_calls) == 1
    assert len(client.recorded_review_answers) == 1

    submitted_answer = client.recorded_review_answers[0]
    raw_arguments = json.loads(
        submitted_answer["raw_message"]["tool_calls"][0]["function"]["arguments"]
    )
    assert raw_arguments == {
        "action": "submit_result",
        "task_id": REVIEW_TASK_ID,
        "result": review_result,
    }
    assert submitted_answer["tool_calls"] == [{
        "function": {
            "name": "task_manage",
            "arguments": raw_arguments,
        },
    }]
    assert client.result_record["result"] == review_result
    assert client.link_calls[0][1] is client.start_calls[1][2]


@pytest.mark.parametrize(
    "denial", ["stopped", "route_mismatch", "unstamped_backend", "mutated_native_route"],
)
def test_review_dispatch_denies_stop_or_unverified_native_route_before_http(monkeypatch, denial):
    backend = _backend(stamp=denial != "unstamped_backend")
    route = route_snapshot(backend)
    route_override = route
    if denial == "route_mismatch":
        route_override = {**route, "route_sha256": "b" * 64}
    client, binding, stop, _ = _review_binding(
        backend, route_override=route_override,
    )
    if denial == "stopped":
        stop.set()
    if denial == "route_mismatch":
        assert route_override != route
    if denial == "mutated_native_route":
        backend.base_url = "https://unexpected.example/v1"

    requests = _mock_openai_http(monkeypatch, [])
    runtime, session = _runtime_for(backend, binding)
    token = runtime._compute_turn_context.set((CHAT_ID, "background"))
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(runtime._chat_with_compute_turn(backend, [], model=MODEL))
    finally:
        runtime._compute_turn_context.reset(token)

    assert requests == []
    assert client.start_calls == []
    if denial == "stopped":
        assert client.guard_calls == []
    elif denial == "route_mismatch":
        assert client.guard_calls[-1][0] == route
        assert client.guard_calls[-1][0] != binding._review_grant.route
    elif denial == "unstamped_backend":
        assert client.guard_calls[-1][0] is None
    else:
        assert client.guard_calls[-1][0] is None


def test_review_grants_narrow_advertised_tools_and_block_hallucinated_write(monkeypatch):
    backend = _backend()
    client, binding, _stop, _route = _review_binding(backend)
    broad_grants = [
        "read_file", "search_text", "task_manage",
        "write_file", "run_shell", "safe_shell", "bach_command",
    ]
    runtime, session = _runtime_for(backend, binding, allowed_tools=broad_grants)
    requests = _mock_openai_http(monkeypatch, [
        _tool_reply(MODEL, "write_file", {"path": "out.txt", "content": "must not run"}),
    ])

    from hub._services.chat import chat_runtime, slots_config

    executed = []
    monkeypatch.setattr(chat_runtime, "exec_tool",
                        lambda *args, **kwargs: executed.append((args, kwargs)))
    monkeypatch.setattr(slots_config, "update_slot", lambda *_args, **_kwargs: None)

    token = runtime._compute_turn_context.set((CHAT_ID, "background"))
    try:
        answer = asyncio.run(runtime._tool_loop(
            [{"role": "system", "content": "Review read-only."},
             {"role": "user", "content": "Review the target."}],
            session,
            [
                _task_manage_tool(),
                {"type": "function", "function": {"name": "write_file", "parameters": {}}},
            ],
            backend=backend,
            model=MODEL,
        ))
    finally:
        runtime._compute_turn_context.reset(token)

    names = {
        item["function"]["name"]
        for item in requests[0]["json"].get("tools", [])
    }
    assert "task_manage" in names
    assert names.isdisjoint({"write_file", "run_shell", "safe_shell", "bach_command"})
    assert isinstance(answer, FailedAnswer)
    assert "nicht freigegeben" in str(answer)
    assert executed == []
    assert client.result_record is None


def test_bach_tool_provider_and_direct_exec_tool_recheck_review_grants():
    from hub._services.chat.bach_tools import BachToolProvider, exec_tool

    backend = _backend()
    _client, binding, _stop, _route = _review_binding(backend)
    broad_grants = {
        "read_file", "write_file", "run_shell", "safe_shell", "bach_command",
    }
    provider = BachToolProvider(
        worker_task_binding=binding,
        require_task_binding=True,
        allowed_tools=broad_grants,
    )

    offered = {
        item["function"]["name"]
        for item in provider.get_tools("safe")
    }
    assert offered == {"read_file"}

    provider_result = provider.execute(
        "write_file", {"path": "out.txt", "content": "must not be written"}, "safe",
    )
    direct_result = exec_tool(
        "write_file",
        {"path": "out.txt", "content": "must not be written"},
        "safe",
        worker_task_binding=binding,
        require_task_binding=True,
        allowed_tools=broad_grants,
    )
    assert "BLOCKIERT" in provider_result and "nicht freigegeben" in provider_result
    assert "BLOCKIERT" in direct_result and "nicht freigegeben" in direct_result


class _QueueProbeClient:
    mode = "local"

    def __init__(self, *, ordinary, review, grant_available=True):
        self.ordinary = ordinary
        self.review = review
        self.grant_available = grant_available
        self.events = []

    def task_candidates(self, *, limit, offset):
        assert limit == 100 and offset == 0
        self.events.append("ordinary_candidates")
        return {"tasks": copy.deepcopy(self.ordinary), "has_more": False, "offset": 0}

    def _review_candidates(self, *, limit, offset):
        assert limit == 100 and offset == 0
        self.events.append("review_candidates")
        return {"tasks": copy.deepcopy(self.review), "has_more": False, "offset": 0}

    def _issue_review_grant(self, task_id, **_kwargs):
        self.events.append(("grant", task_id))
        return SimpleNamespace(task_id=task_id) if self.grant_available else None


def _queue_task(task_id, *, assigned_to="BACH", assigned_slot=None, required_model=None):
    return {
        "id": task_id,
        "task_version": f"task-v{task_id}",
        "assigned_to": assigned_to,
        "assigned_slot": assigned_slot,
        "required_model": required_model,
        "status": "pending",
    }


def _probe_acquire(monkeypatch, client, slot):
    acquired = []

    def acquire(cls, active_client, task_id, **kwargs):
        active_client.events.append(("acquire", task_id, kwargs.get("_review_grant")))
        binding = SimpleNamespace(task_id=task_id)
        acquired.append((task_id, kwargs.get("_review_grant"), binding))
        return binding

    monkeypatch.setattr(WorkerLeaseBinding, "acquire", classmethod(acquire))
    route = {"backend_id": "openai", "route_sha256": "c" * 64}
    binding = WorkerLeaseBinding.acquire_next(
        client,
        slot,
        review_route=route,
        review_requested_model=MODEL,
        worker_id=WORKER_ID,
        host=HOST,
        generation=GENERATION,
        is_current=lambda: True,
        stop_event=threading.Event(),
    )
    return binding, acquired


def test_worker_queue_tries_normal_work_before_review_fallback(monkeypatch):
    normal = _queue_task(31)
    review = _queue_task(REVIEW_TASK_ID, assigned_slot=CHAT_ID, required_model=MODEL)
    client = _QueueProbeClient(ordinary=[normal], review=[review])
    binding, acquired = _probe_acquire(
        monkeypatch,
        client,
        {"id": CHAT_ID, "model": MODEL, "pickup_filter": {"enabled": False}},
    )

    assert binding.task_id == normal["id"]
    assert [event for event in client.events if event == "review_candidates"] == []
    assert [item[0] for item in acquired] == [normal["id"]]
    assert client.events[0] == "ordinary_candidates"


@pytest.mark.parametrize("grant_available", [True, False])
def test_review_queue_is_considered_only_after_no_normal_match_and_needs_grant(
    monkeypatch, grant_available,
):
    unsuitable = _queue_task(32, assigned_to="claude")
    review = _queue_task(REVIEW_TASK_ID, assigned_slot=CHAT_ID, required_model=MODEL)
    client = _QueueProbeClient(
        ordinary=[unsuitable], review=[review], grant_available=grant_available,
    )
    binding, acquired = _probe_acquire(
        monkeypatch,
        client,
        {"id": CHAT_ID, "model": MODEL, "pickup_filter": {"enabled": False}},
    )

    assert client.events[:2] == ["ordinary_candidates", "review_candidates"]
    assert ("grant", REVIEW_TASK_ID) in client.events
    if grant_available:
        assert binding.task_id == REVIEW_TASK_ID
        assert [item[0] for item in acquired] == [REVIEW_TASK_ID]
        assert acquired[0][1] is not None
    else:
        assert binding is None
        assert acquired == []
