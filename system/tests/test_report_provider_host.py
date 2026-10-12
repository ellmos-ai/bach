from __future__ import annotations

import asyncio

import pytest

from hub._services.document.report_provider_host import (
    ReportProviderHost,
    ReportProviderRpcError,
    create_report_provider_host,
)
from hub._services.document.report_provider_contract import SCHEMA
from hub._services.document import report_provider_host
from hub._services.document.report_provider_adapter import (
    OwnerExecutionProfileReader,
    ReportProviderAdapter,
)


class _Provider:
    def __init__(self):
        self.calls = []

    async def capabilities(self):
        self.calls.append(("capabilities", asyncio.get_running_loop()))
        return {
            "schema": SCHEMA,
            "available": False,
            "modes": [],
            "watcher_available": False,
            "mode_statuses": {
                mode: {"available": False, "reason_code": "provider_unavailable"}
                for mode in ("local", "cloud", "hybrid")
            },
            "reason_code": "provider_unavailable",
        }

    async def list_sources(self, _subject_ref):
        return {"schema": SCHEMA, "complete": False, "sources": []}

    async def watcher_status(self):
        return {"schema": SCHEMA, "status": "disabled", "enabled": False}


@pytest.mark.asyncio
async def test_control_thread_bridge_runs_on_explicit_owner_loop():
    provider = _Provider()
    host = ReportProviderHost(provider, owner_loop=asyncio.get_running_loop())

    result = await asyncio.to_thread(host.call_from_control, "capabilities", {})

    assert result["schema"] == SCHEMA
    assert result["available"] is False
    assert provider.calls == [("capabilities", asyncio.get_running_loop())]


@pytest.mark.asyncio
async def test_control_dispatch_rejects_extra_fields_and_unknown_operation():
    host = ReportProviderHost(_Provider(), owner_loop=asyncio.get_running_loop())

    with pytest.raises(ReportProviderRpcError) as extra:
        await host.dispatch("watcher_tick", {"now": "client-controlled"})
    with pytest.raises(ReportProviderRpcError) as unknown:
        await host.dispatch("start_worker", {})

    assert extra.value.status_code == 422
    assert extra.value.reason_code == "invalid_report_request"
    assert unknown.value.status_code == 404
    assert unknown.value.reason_code == "report_operation_unknown"


def test_host_factory_fails_closed_without_actual_control_runtime_or_owner_loop():
    reader = OwnerExecutionProfileReader(
        "report-worker",
        lambda: {
            "id": "report-worker",
            "enabled": True,
            "system": True,
            "execution_kind": "worker",
            "blueprint_id": 7,
            "blueprint_version": 1,
            "governance_binding": {
                "legacy": False,
                "effective_sha256": "a" * 64,
                "refs": [{"id": "P-1", "role": "agent"}],
            },
        },
    )

    host = create_report_provider_host(
        owner_runtime=object(),
        owner_agent_id="report-worker",
        owner_profile_reader=reader,
        host_dependencies={},
        provider_name="foerderplaner",
        owner_loop=None,
    )

    assert host.owner_bound is False
    assert host.call_from_control("capabilities", {})["available"] is False


@pytest.mark.asyncio
async def test_host_factory_binds_fixed_owner_runtime_and_profile_reader(monkeypatch):
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.llm.model_backend import OllamaBackend

    backend = OllamaBackend(default_model="report-worker-model")
    runtime = ChatRuntime(backend)
    profile = {
        "id": "system-blueprint-7",
        "enabled": True,
        "system": True,
        "execution_kind": "worker",
        "blueprint_id": 7,
        "blueprint_version": 3,
        "backend": "ollama",
        "model": "report-worker-model",
        "governance_binding": {
            "legacy": False,
            "effective_sha256": "b" * 64,
            "refs": [{"id": "P-7", "role": "agent"}],
        },
    }
    reader = OwnerExecutionProfileReader("system-blueprint-7", lambda: dict(profile))
    captured = {}

    def load(_ports, *, provider_name):
        captured["provider_name"] = provider_name
        captured["ports"] = _ports
        return ReportProviderAdapter.unavailable("provider_missing")

    monkeypatch.setattr(report_provider_host, "load_report_provider", load)
    host = create_report_provider_host(
        owner_runtime=runtime,
        owner_agent_id="system-blueprint-7",
        owner_profile_reader=reader,
        host_dependencies={},
        provider_name="foerderplaner",
        owner_loop=asyncio.get_running_loop(),
    )

    # The owner binding is valid even if the optional provider is unavailable.
    assert host.owner_bound is True
    assert captured["provider_name"] == "foerderplaner"
    assert captured["ports"]["local_model"]._runtime is runtime
    assert captured["ports"]["local_model"]._backend is backend
    assert captured["ports"]["local_model"]._agent_id == "system-blueprint-7"
    assert captured["ports"]["local_model"]._execution_profile_reader is reader


@pytest.mark.asyncio
async def test_host_loop_mismatch_is_rejected_before_provider_call():
    provider = _Provider()
    foreign_loop = asyncio.new_event_loop()
    try:
        host = ReportProviderHost(provider, owner_loop=foreign_loop)
        with pytest.raises(ReportProviderRpcError) as error:
            await host.capabilities()
    finally:
        foreign_loop.close()

    assert error.value.reason_code == "provider_unavailable"
    assert not provider.calls
