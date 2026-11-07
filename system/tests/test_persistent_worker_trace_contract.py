"""Persistenter Worker-Trace-Contract (bach.worker-tool-trace.v1).

Der Contract validiert, dass der persistente Worker-Runner die
Pflicht-Tokens für die Task-Bindung enthält und darf von den
Startup-/Admission-Gates (8305/8669) nicht stillschweigend abgeschwächt
werden. Dieser Test sichert die rohe Contract-Quelle gegen Regressionen.
"""

import inspect

from hub._services.chat import telegram_chat


def test_worker_runner_source_contains_binding_tokens():
    source = inspect.getsource(telegram_chat._start_reserved_worker_execution)
    assert "require_task_binding = True" in source
    assert "_acquire_worker_task(" in source


def test_persistent_worker_trace_contract_returns_payload():
    assert telegram_chat._persistent_worker_trace_contract() is not None
