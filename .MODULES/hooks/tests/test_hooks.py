# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone hooks module."""
from pathlib import Path
import pytest
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from hooks import HookRegistry


def test_hook_registry_dispatch_and_priority():
    reg = HookRegistry()
    calls = []

    def first(payload):
        calls.append(("first", payload))
        return "r1"

    def second(payload):
        calls.append(("second", payload))
        return "r2"

    reg.on("test_event", second, priority=200, name="second_listener")
    reg.on("test_event", first, priority=50, name="first_listener")

    res = reg.emit("test_event", {"msg": "hello"})
    assert res == ["r1", "r2"]
    assert calls[0] == ("first", {"msg": "hello"})
    assert calls[1] == ("second", {"msg": "hello"})


def test_hook_once_and_off():
    reg = HookRegistry()
    fired = []

    reg.once("single", lambda p: fired.append("once"))
    reg.emit("single")
    assert fired == ["once"]

    # Second emit: should not fire again
    reg.emit("single")
    assert fired == ["once"]

    # off by name
    reg.on("removable", lambda: None, name="to_remove")
    assert reg.listener_count("removable") == 1
    removed = reg.off("removable", "to_remove")
    assert removed == 1
    assert reg.listener_count("removable") == 0


def test_hook_error_containment_and_logging():
    reg = HookRegistry()

    def buggy(payload):
        raise ValueError("Simulated hook failure")

    def good(payload):
        return "success"

    reg.on("err_event", buggy, priority=10)
    reg.on("err_event", good, priority=20)

    res = reg.emit("err_event")
    assert len(res) == 2
    assert "error" in res[0]
    assert res[1] == "success"

    log = reg.get_log()
    assert len(log) == 1
    assert log[0]["event"] == "err_event"
    assert log[0]["listeners"] == 2
