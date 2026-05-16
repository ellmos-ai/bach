# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for N8nManagerHandler (hub/n8n_manager.py)."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from hub.n8n_manager import N8nManagerHandler


class TestN8nManagerInit:
    def test_default_url(self):
        h = N8nManagerHandler()
        assert h.n8n_base_url == "http://localhost:5678"

    def test_custom_url(self):
        h = N8nManagerHandler(n8n_base_url="http://myhost:9999")
        assert h.n8n_base_url == "http://myhost:9999"

    def test_profile_name(self):
        h = N8nManagerHandler()
        assert h.profile_name == "n8n-manager"


class TestGetOperations:
    def test_operations_keys(self):
        h = N8nManagerHandler()
        ops = h.get_operations()
        assert "status" in ops
        assert "list" in ops
        assert "sync" in ops

    def test_operations_descriptions(self):
        h = N8nManagerHandler()
        ops = h.get_operations()
        for key, desc in ops.items():
            assert isinstance(desc, str)
            assert len(desc) > 5


class TestIsMcpInstalled:
    @patch("hub.n8n_manager.shutil.which", return_value=None)
    def test_no_npm(self, mock_which):
        h = N8nManagerHandler()
        assert h.is_mcp_installed() is False

    @patch("hub.n8n_manager.subprocess.run")
    @patch("hub.n8n_manager.shutil.which", return_value="/usr/bin/npm")
    def test_mcp_installed(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="n8n-manager-mcp@1.0.0"
        )
        h = N8nManagerHandler()
        assert h.is_mcp_installed() is True

    @patch("hub.n8n_manager.subprocess.run")
    @patch("hub.n8n_manager.shutil.which", return_value="/usr/bin/npm")
    def test_mcp_not_installed(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="(empty)")
        h = N8nManagerHandler()
        assert h.is_mcp_installed() is False

    @patch("hub.n8n_manager.shutil.which", return_value="/usr/bin/npm")
    def test_caches_result(self, mock_which):
        h = N8nManagerHandler()
        h._mcp_installed = True
        assert h.is_mcp_installed() is True


class TestCheckN8nRunning:
    @patch("hub.n8n_manager.urllib.request.urlopen")
    def test_healthz_ok(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp
        h = N8nManagerHandler()
        assert h._check_n8n_running() is True

    @patch("hub.n8n_manager.urllib.request.urlopen")
    def test_not_reachable(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        h = N8nManagerHandler()
        assert h._check_n8n_running() is False


class TestNotInstalledMessage:
    def test_message_structure(self):
        h = N8nManagerHandler()
        result = h._not_installed_message()
        assert result["status"] == "not_installed"
        assert "bach setup n8n" in result["message"]


class TestListWorkflows:
    @patch("hub.n8n_manager.urllib.request.urlopen")
    def test_empty_workflows(self, mock_urlopen):
        import json
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": []}).encode()
        mock_urlopen.return_value = mock_resp
        h = N8nManagerHandler()
        result = h._list_workflows()
        assert result["status"] == "ok"
        assert result["count"] == 0

    @patch("hub.n8n_manager.urllib.request.urlopen")
    def test_workflows_found(self, mock_urlopen):
        import json
        workflows = [
            {"id": "1", "name": "Test WF", "active": True},
            {"id": "2", "name": "Inactive", "active": False},
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": workflows}).encode()
        mock_urlopen.return_value = mock_resp
        h = N8nManagerHandler()
        result = h._list_workflows()
        assert result["status"] == "ok"
        assert result["count"] == 2
        assert result["workflows"][0]["name"] == "Test WF"

    @patch("hub.n8n_manager.urllib.request.urlopen")
    def test_api_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None
        )
        h = N8nManagerHandler()
        result = h._list_workflows()
        assert result["status"] == "error"
        assert "401" in result["message"]
