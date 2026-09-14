# SPDX-License-Identifier: MIT
"""
Tests fuer den BACH Cloud Control Service & CloudHandler.
"""

import sys
import time
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from hub._services.cloud.cloud_manager import (
    CloudManager,
    CloudAdapter,
    OneDriveAdapter,
    GoogleDriveAdapter,
    ICloudAdapter,
    DropboxAdapter,
    NextcloudAdapter,
    get_cloud_manager,
    cloud_pause,
)
from hub.cloud import CloudHandler


class DummyAdapter(CloudAdapter):
    name = "dummy"
    display_name = "Dummy Cloud"

    def __init__(self, running=True):
        self._running = running
        self._paused = False

    def is_installed(self) -> bool:
        return True

    def is_running(self) -> bool:
        return self._running and not self._paused

    def pause(self) -> bool:
        self._paused = True
        return True

    def resume(self) -> bool:
        self._paused = False
        return True


class TestCloudAdapters:
    def test_onedrive_adapter_info(self):
        adapter = OneDriveAdapter()
        info = adapter.get_info()
        assert info["name"] == "onedrive"
        assert info["display_name"] == "Microsoft OneDrive"
        assert "installed" in info
        assert "running" in info

    def test_icloud_adapter_info(self):
        adapter = ICloudAdapter()
        info = adapter.get_info()
        assert info["name"] == "icloud"
        assert info["display_name"] == "Apple iCloud Drive"

    def test_googledrive_adapter_info(self):
        adapter = GoogleDriveAdapter()
        assert adapter.name == "googledrive"

    def test_dropbox_adapter_info(self):
        adapter = DropboxAdapter()
        assert adapter.name == "dropbox"

    def test_nextcloud_adapter_info(self):
        adapter = NextcloudAdapter()
        assert adapter.name == "nextcloud"


class TestCloudManager:
    def test_manager_status_structure(self):
        mgr = CloudManager()
        status = mgr.get_status()
        assert "active_providers_count" in status
        assert "paused_providers_count" in status
        assert "has_paused_sync" in status
        assert "providers" in status
        assert "onedrive" in status["providers"]
        assert "icloud" in status["providers"]

    def test_manager_pause_and_resume_all(self):
        mgr = CloudManager()
        dummy = DummyAdapter(running=True)
        mgr.adapters = {"dummy": dummy}

        assert dummy.is_running() is True
        res = mgr.pause(timeout_seconds=60)
        assert res.get("dummy") is True
        assert dummy.is_running() is False
        assert mgr.get_status()["has_paused_sync"] is True

        res_resume = mgr.resume()
        assert res_resume.get("dummy") is True
        assert dummy.is_running() is True
        assert mgr.get_status()["has_paused_sync"] is False

    def test_manager_pause_specific_provider(self):
        mgr = CloudManager()
        dummy1 = DummyAdapter(running=True)
        dummy2 = DummyAdapter(running=True)
        dummy1.name = "d1"
        dummy2.name = "d2"
        mgr.adapters = {"d1": dummy1, "d2": dummy2}

        mgr.pause("d1", timeout_seconds=60)
        assert dummy1.is_running() is False
        assert dummy2.is_running() is True

        mgr.resume("d1")
        assert dummy1.is_running() is True
        assert dummy2.is_running() is True

    def test_context_manager_cloud_pause(self):
        mgr = CloudManager()
        dummy = DummyAdapter(running=True)
        mgr.adapters = {"dummy": dummy}

        with patch("hub._services.cloud.cloud_manager.get_cloud_manager", return_value=mgr):
            assert dummy.is_running() is True
            with cloud_pause(timeout=60):
                assert dummy.is_running() is False
            assert dummy.is_running() is True

    def test_watchdog_auto_resumes(self):
        mgr = CloudManager()
        dummy = DummyAdapter(running=True)
        mgr.adapters = {"dummy": dummy}

        mgr.pause(timeout_seconds=1)
        assert dummy.is_running() is False
        time.sleep(1.2)
        assert dummy.is_running() is True
        assert mgr.get_status()["has_paused_sync"] is False


class TestCloudHandler:
    @pytest.fixture
    def handler(self, tmp_path):
        return CloudHandler(tmp_path)

    def test_status_output(self, handler):
        ok, out = handler.handle("status", [])
        assert ok is True
        assert "CLOUD SYNC STATUS" in out
        assert "Microsoft OneDrive" in out

    def test_status_json(self, handler):
        ok, out = handler.handle("status", ["--json"])
        assert ok is True
        assert '"providers"' in out

    def test_dry_run_pause(self, handler):
        ok, out = handler.handle("pause", ["onedrive"], dry_run=True)
        assert ok is True
        assert "[Dry-Run]" in out
        assert "onedrive" in out

    def test_dry_run_resume(self, handler):
        ok, out = handler.handle("resume", [], dry_run=True)
        assert ok is True
        assert "[Dry-Run]" in out

    def test_dry_run_toggle(self, handler):
        ok, out = handler.handle("toggle", [], dry_run=True)
        assert ok is True
        assert "[Dry-Run]" in out

    def test_help_output(self, handler):
        ok, out = handler.handle("help", [])
        assert ok is True
        assert "BACH Cloud Control CLI" in out
