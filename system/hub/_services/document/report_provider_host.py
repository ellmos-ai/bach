"""Owner-bound facade for an optional report provider.

The facade is created only by the existing Control owner with its real
``ChatRuntime`` and an owner-supplied governance reader. It does not create a
runtime, event loop, consent issuer, or persistent store. Control HTTP threads
submit calls to the already-running owner loop through ``call_from_control``.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import re
from typing import Any, Mapping

from .report_provider_adapter import (
    OwnerExecutionProfileReader,
    ReportHostPortError,
    ReportProviderAdapter,
    build_report_host_ports,
    load_report_provider,
    report_result_for_error,
)
from .report_provider_contract import (
    SCHEMA,
    PreparedRun,
    ProviderCapabilities,
    ReportContractError,
    ReportRequest,
    ReportResult,
    WatcherConfig,
    _opaque,
)


_PROVIDER_DEPENDENCY_KEYS = frozenset({
    "word_template", "anonymizer", "document_reader", "operator_confirmation", "cloud_model",
})
_OPERATIONS = frozenset({
    "capabilities", "sources", "prepare", "finish", "status", "cleanup",
    "watcher_status", "watcher_configure", "watcher_tick",
})


class ReportProviderRpcError(ValueError):
    """Safe Control-RPC rejection with an HTTP status and neutral code."""

    def __init__(self, status_code: int, reason_code: str) -> None:
        self.status_code = status_code
        self.reason_code = reason_code
        super().__init__(reason_code)


def _object(value: Any, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ReportProviderRpcError(422, reason)
    return dict(value)


def _exact(value: Mapping[str, Any], expected: set[str], reason: str) -> None:
    if set(value) != expected:
        raise ReportProviderRpcError(422, reason)


class ReportProviderHost:
    """Async lifecycle facade and synchronous Control-thread bridge."""

    def __init__(
        self,
        adapter: ReportProviderAdapter,
        *,
        owner_loop: asyncio.AbstractEventLoop | None,
        unavailable_reason: str | None = None,
    ) -> None:
        self._adapter = adapter
        self._owner_loop = owner_loop
        self._unavailable_reason = unavailable_reason

    @property
    def owner_bound(self) -> bool:
        """Whether the trusted runtime/profile binding was accepted.

        This does not imply that an optional report-provider EntryPoint or
        its host ports are available.
        """
        return self._unavailable_reason is None

    def _require_owner_loop(self) -> None:
        if self._unavailable_reason is not None:
            raise ReportProviderRpcError(503, self._unavailable_reason)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            raise ReportProviderRpcError(503, "provider_unavailable") from None
        if running is not self._owner_loop:
            raise ReportProviderRpcError(503, "provider_unavailable")

    async def capabilities(self) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.capabilities()

    async def list_sources(self, subject_ref: str) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.list_sources(subject_ref)

    async def prepare(self, request: Mapping[str, Any]) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.prepare(request)

    async def finish(self, run_id: str, approval: Mapping[str, Any]) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.finish(run_id, approval)

    async def status(self, run_id: str) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.status(run_id)

    async def cleanup(self, run_id: str, approval: Mapping[str, Any]) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.cleanup(run_id, approval)

    async def watcher_status(self) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.watcher_status()

    async def watcher_configure(self, config: Mapping[str, Any]) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.watcher_configure(config)

    async def watcher_tick(self) -> dict[str, Any]:
        self._require_owner_loop()
        return await self._adapter.watcher_tick()

    async def dispatch(self, operation: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Validate one fixed RPC operation and return its public DTO."""
        self._require_owner_loop()
        if operation not in _OPERATIONS:
            raise ReportProviderRpcError(404, "report_operation_unknown")
        data = _object(payload or {}, "invalid_report_request")
        if operation in {"capabilities", "watcher_status", "watcher_tick"}:
            _exact(data, set(), "invalid_report_request")
            if operation == "capabilities":
                return await self._adapter.capabilities()
            if operation == "watcher_status":
                return await self._adapter.watcher_status()
            return await self._adapter.watcher_tick()
        if operation == "sources":
            _exact(data, {"subject_ref"}, "invalid_report_request")
            return await self._adapter.list_sources(_opaque(data["subject_ref"], "subject_ref"))
        if operation == "prepare":
            ReportRequest.from_wire(data)
            return await self._adapter.prepare(data)
        if operation == "finish":
            _exact(data, {"run_id", "approval"}, "invalid_report_request")
            run_id = _opaque(data["run_id"], "run_id")
            approval = _object(data["approval"], "invalid_report_approval")
            return await self._adapter.finish(run_id, approval)
        if operation == "status":
            _exact(data, {"run_id"}, "invalid_report_request")
            return await self._adapter.status(_opaque(data["run_id"], "run_id"))
        if operation == "cleanup":
            _exact(data, {"run_id", "approval"}, "invalid_report_request")
            run_id = _opaque(data["run_id"], "run_id")
            approval = _object(data["approval"], "invalid_report_approval")
            return await self._adapter.cleanup(run_id, approval)
        if operation == "watcher_configure":
            WatcherConfig.from_wire(data)
            return await self._adapter.watcher_configure(data)
        raise ReportProviderRpcError(404, "report_operation_unknown")

    def call_from_control(
        self,
        operation: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Submit from a synchronous Control HTTP thread to the owner loop.

        A timed-out future is deliberately not cancelled: finish/tick may have
        crossed an effect boundary, so their response must say ``unknown``.
        """
        loop = self._owner_loop
        if (self._unavailable_reason is not None or loop is None
                or loop.is_closed() or not loop.is_running()):
            return self._timeout_response(operation, payload, "provider_unavailable")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            return self._timeout_response(operation, payload, "provider_unavailable")
        try:
            future = asyncio.run_coroutine_threadsafe(self.dispatch(operation, payload), loop)
            return future.result(timeout=max(0.1, min(float(timeout), 120.0)))
        except concurrent.futures.TimeoutError:
            return self._timeout_response(operation, payload, "provider_effect_unknown")
        except ReportProviderRpcError as exc:
            raise exc
        except ReportContractError:
            raise ReportProviderRpcError(422, "invalid_report_request") from None
        except Exception:
            return self._timeout_response(operation, payload, "provider_unavailable")

    @staticmethod
    def _timeout_response(
        operation: str,
        payload: Mapping[str, Any] | None,
        reason_code: str,
    ) -> dict[str, Any]:
        data = dict(payload) if isinstance(payload, Mapping) else {}
        if operation == "capabilities":
            return ProviderCapabilities.from_wire({
                "schema": SCHEMA,
                "available": False,
                "modes": [],
                "watcher_available": False,
                "mode_statuses": {
                    mode: {"available": False, "reason_code": "provider_unavailable"}
                    for mode in ("local", "cloud", "hybrid")
                },
                "reason_code": "provider_unavailable",
            }).to_wire()
        if operation == "prepare":
            try:
                request = ReportRequest.from_wire(data)
                digest = request.digest
            except Exception:
                digest = "0" * 64
            return PreparedRun(
                None, "unavailable", None, None, digest, None, None, 0,
                "provider_unavailable",
            ).to_wire()
        if operation in {"finish", "cleanup", "status"}:
            run_id = data.get("run_id")
            if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}", run_id) is None:
                run_id = "unknown"
            if operation == "finish":
                return report_result_for_error(run_id, reason_code, effect="unknown")
            if operation == "cleanup":
                return {
                    "schema": SCHEMA,
                    "run_id": run_id,
                    "status": "unknown",
                    "reason_code": "provider_unavailable",
                    "sources_retained": True,
                }
            return {
                "schema": SCHEMA,
                "run_id": run_id,
                "status": "unknown",
                "reason_code": "provider_unavailable",
                "review_required": True,
            }
        if operation in {"watcher_status", "watcher_configure", "watcher_tick"}:
            return {
                "schema": SCHEMA,
                "status": "unknown",
                "enabled": False,
                "reason_code": "provider_watcher_unavailable",
            }
        if operation == "sources":
            return {"schema": SCHEMA, "complete": False, "sources": []}
        return {"schema": SCHEMA, "status": "unavailable", "reason_code": "provider_unavailable"}


def create_report_provider_host(
    *,
    owner_runtime: Any,
    owner_agent_id: str,
    owner_profile_reader: OwnerExecutionProfileReader,
    host_dependencies: Mapping[str, Any],
    provider_name: str,
    owner_loop: asyncio.AbstractEventLoop | None,
) -> ReportProviderHost:
    """Bind the optional provider to one trusted Control-owner runtime/profile.

    ``owner_profile_reader`` is constructed only in the real owner from its
    execution-slot reader. ``host_dependencies`` contains app-created generic
    Word/anonymization/document/consent ports, never request values. This
    function does not create the owner loop or a second ChatRuntime.
    """
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.llm.model_backend import backend_identifier

    if (type(owner_runtime) is not ChatRuntime
            or not isinstance(owner_loop, asyncio.AbstractEventLoop)
            or owner_loop.is_closed() or not owner_loop.is_running()
            or type(owner_profile_reader) is not OwnerExecutionProfileReader
            or owner_profile_reader.agent_id != owner_agent_id):
        return ReportProviderHost(
            ReportProviderAdapter.unavailable("provider_unavailable"),
            owner_loop=None,
            unavailable_reason="provider_unavailable",
        )
    try:
        profile = owner_profile_reader.read()
        backend = owner_runtime.backend
        if profile.get("backend") != backend_identifier(backend):
            raise ReportHostPortError("provider_route_unverified")
        model = profile.get("model")
        if not isinstance(model, str) or not model:
            raise ReportHostPortError("provider_route_unverified")
        if not isinstance(host_dependencies, Mapping) or set(host_dependencies) - _PROVIDER_DEPENDENCY_KEYS:
            raise ReportHostPortError("provider_unavailable")
        configured = dict(host_dependencies)
        host_ports = build_report_host_ports(
            word_template=configured.get("word_template"),
            anonymizer=configured.get("anonymizer"),
            document_reader=configured.get("document_reader"),
            operator_confirmation=configured.get("operator_confirmation"),
            local_model={
                "backend": backend,
                "model": model,
                "runtime": owner_runtime,
                "agent_id": owner_agent_id,
                "execution_profile_reader": owner_profile_reader,
            },
            cloud_model=configured.get("cloud_model"),
        )
        adapter = load_report_provider(host_ports, provider_name=provider_name)
        return ReportProviderHost(adapter, owner_loop=owner_loop)
    except Exception:
        return ReportProviderHost(
            ReportProviderAdapter.unavailable("provider_unavailable"),
            owner_loop=owner_loop,
            unavailable_reason="provider_unavailable",
        )
