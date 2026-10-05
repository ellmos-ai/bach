#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests für das user_id-Gate in acquire_fackel() (Nicht-24h-Session-Typen)."""

import pytest

from hub._services.claude_bridge.fackel import acquire_fackel, release_fackel


SESSION_TYPE = "focus_session"


@pytest.fixture(autouse=True)
def _cleanup_focus_session():
    """Stellt sicher, dass jeder Test mit einem leeren focus_session-State startet."""
    release_fackel(SESSION_TYPE)
    yield
    release_fackel(SESSION_TYPE)


def test_gate_blocks_foreign_user_for_non_h24_session():
    ok1, msg1 = acquire_fackel(SESSION_TYPE, user_id="user_a")
    assert ok1 is True, msg1

    ok2, msg2 = acquire_fackel(SESSION_TYPE, user_id="user_b")
    assert ok2 is False
    assert "Fackel von anderem Benutzer 'user_a' gehalten" in msg2


def test_gate_allows_same_user_for_non_h24_session():
    ok1, msg1 = acquire_fackel(SESSION_TYPE, user_id="user_a")
    assert ok1 is True, msg1

    ok2, msg2 = acquire_fackel(SESSION_TYPE, user_id="user_a")
    assert ok2 is True, msg2


def test_gate_allows_acquire_when_no_holder():
    ok, msg = acquire_fackel(SESSION_TYPE, user_id="user_a")
    assert ok is True, msg
