# -*- coding: utf-8 -*-
"""Regression tests for inbox.html cookie auth and real API error reporting (Task #2584)."""
from pathlib import Path

INBOX_HTML = Path(__file__).resolve().parents[1] / "gui" / "templates" / "inbox.html"


def test_inbox_html_uses_httponly_cookie_credentials_without_localstorage_token():
    content = INBOX_HTML.read_text(encoding="utf-8")
    assert len(content) > 10000
    assert "credentials: 'same-origin'" in content
    assert "localStorage.getItem('bach_device_token')" not in content
    assert "if (!token) throw new Error" not in content


def test_inbox_html_surfaces_real_api_error_details_instead_of_generic_api_fehler():
    content = INBOX_HTML.read_text(encoding="utf-8")
    assert "errData.detail || errData.error || errData.message" in content
    assert "alert('API Fehler')" not in content
    assert ">API Fehler</td>" not in content
