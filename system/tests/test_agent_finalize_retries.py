# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for BaseAgent.before_agent_finalize retry logic."""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from core.agent_runtime import AgentConfig, AgentStatus, BaseAgent


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


class _TestAgent(BaseAgent):
    """Concrete agent subclass for testing the finalize hook."""

    def __init__(self, config, hook):
        super().__init__(config)
        self.hook = hook
        self.hook_calls = 0

    def connect(self) -> bool:
        return True

    def execute(self, operation, args):
        return True, "ok"

    def before_agent_finalize(self) -> bool:
        self.hook_calls += 1
        return self.hook(self.hook_calls)


def _make_config(name="test-agent"):
    return AgentConfig(name=name, agent_type="worker")


@pytest.fixture(autouse=True)
def _fast_finalize():
    """Speed up finalize retry settings for tests."""
    original = {
        "max": BaseAgent._FINALIZE_MAX_RETRIES,
        "timeout": BaseAgent._FINALIZE_TIMEOUT,
        "delay": BaseAgent._FINALIZE_BASE_DELAY,
    }
    BaseAgent._FINALIZE_MAX_RETRIES = 3
    BaseAgent._FINALIZE_TIMEOUT = 0.05
    BaseAgent._FINALIZE_BASE_DELAY = 0.001
    yield
    BaseAgent._FINALIZE_MAX_RETRIES = original["max"]
    BaseAgent._FINALIZE_TIMEOUT = original["timeout"]
    BaseAgent._FINALIZE_BASE_DELAY = original["delay"]


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════


def test_hook_successful():
    agent = _TestAgent(_make_config(), hook=lambda call: True)
    assert agent.disconnect() is True
    assert agent.status == AgentStatus.DISCONNECTED
    assert agent.hook_calls == 1


def test_hook_permanently_fails():
    agent = _TestAgent(_make_config(), hook=lambda call: False)
    assert agent.disconnect() is False
    assert agent.status == AgentStatus.ERROR
    assert agent.hook_calls == 3


def test_hook_needs_retry():
    agent = _TestAgent(_make_config(), hook=lambda call: call >= 2)
    assert agent.disconnect() is True
    assert agent.status == AgentStatus.DISCONNECTED
    assert agent.hook_calls == 2


def test_max_retries_exceeded_with_exception():
    def _raise(_call):
        raise RuntimeError("finalize error")

    agent = _TestAgent(_make_config(), hook=_raise)
    assert agent.disconnect() is False
    assert agent.status == AgentStatus.ERROR
    assert agent.hook_calls == 3


def test_disconnect_status_after_success():
    agent = _TestAgent(_make_config(), hook=lambda call: True)
    agent.disconnect()
    assert agent.status == AgentStatus.DISCONNECTED


def test_disconnect_status_after_failure():
    agent = _TestAgent(_make_config(), hook=lambda call: False)
    agent.disconnect()
    assert agent.status == AgentStatus.ERROR
