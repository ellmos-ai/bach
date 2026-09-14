# SPDX-License-Identifier: MIT
"""
BACH Cloud Control Service
==========================
Providerneutraler Cloud-Sync-Manager zur Vermeidung von Dateisperren,
Sync-Konflikten und WAL-Kollisionen bei schreibintensiven Operationen.

Unterstuetzte Provider:
  - onedrive    (Microsoft OneDrive)
  - googledrive (Google Drive)
  - icloud      (Apple iCloud Drive)
  - dropbox     (Dropbox)
  - nextcloud   (Nextcloud / ownCloud)

Usage:
  from hub._services.cloud import get_cloud_manager, cloud_pause

  # Status abfragen
  mgr = get_cloud_manager()
  status = mgr.get_status()

  # Context Manager fuer punktuellen Schreibschutz
  with cloud_pause(timeout=180):
      # Schreibintensive Dateioperationen
      ...
"""

import os
import sys
import time
import shutil
import logging
import subprocess
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

logger = logging.getLogger("bach.cloud")


# ═══════════════════════════════════════════════════════════════
# Basis-Adapter
# ═══════════════════════════════════════════════════════════════

class CloudAdapter(ABC):
    """Abstrakter Adapter fuer einen Cloud-Sync-Provider."""

    name: str = "base"
    display_name: str = "Base Cloud"

    @abstractmethod
    def is_installed(self) -> bool:
        """Prueft, ob der Cloud-Client auf dem System vorhanden ist."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Prueft, ob der Sync-Client aktuell aktiv laeuft."""
        pass

    @abstractmethod
    def pause(self) -> bool:
        """Pausiert oder beendet den Sync-Client sauber."""
        pass

    @abstractmethod
    def resume(self) -> bool:
        """Setzt den Sync-Client im Hintergrund wieder fort."""
        pass

    def get_info(self) -> Dict[str, Any]:
        """Liefert strukturierte Statusinformationen."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "installed": self.is_installed(),
            "running": self.is_running(),
            "platform": sys.platform,
        }

    @staticmethod
    def _find_process(names: List[str]) -> bool:
        """Prueft, ob ein Prozess aus der Namensliste laeuft."""
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                pname = (proc.info.get('name') or '').lower()
                for target in names:
                    if target.lower() in pname:
                        return True
            return False
        except Exception:
            # Fallback fuer UNIX via pgrep
            if sys.platform != 'win32':
                for target in names:
                    res = subprocess.run(['pgrep', '-f', target], capture_output=True)
                    if res.returncode == 0:
                        return True
            return False


# ═══════════════════════════════════════════════════════════════
# Provider-Adapter
# ═══════════════════════════════════════════════════════════════

class OneDriveAdapter(CloudAdapter):
    name = "onedrive"
    display_name = "Microsoft OneDrive"

    def __init__(self):
        self._paused = False

    def is_installed(self) -> bool:
        if sys.platform == "win32":
            return self._find_win_exe() is not None
        elif sys.platform == "darwin":
            return os.path.exists("/Applications/OneDrive.app")
        return shutil.which("onedrive") is not None

    def is_running(self) -> bool:
        if self._paused:
            return False
        return self._find_process(["OneDrive", "OneDrive File Provider", "OneDrive Sync Service"])

    def pause(self) -> bool:
        if not self.is_running():
            return True
        try:
            if sys.platform == "win32":
                exe = self._find_win_exe()
                if exe:
                    subprocess.run([exe, "/shutdown"], timeout=10, capture_output=True)
                    time.sleep(2)
                    self._paused = True
                    return True
            elif sys.platform == "darwin":
                res = subprocess.run(
                    ["osascript", "-e", 'quit app "OneDrive"'],
                    capture_output=True, timeout=10
                )
                time.sleep(1)
                self._paused = True
                return True
            else:
                # Linux onedrive CLI
                subprocess.run(["pkill", "-STOP", "onedrive"], capture_output=True)
                self._paused = True
                return True
        except Exception as e:
            logger.warning(f"OneDrive Pause fehlgeschlagen: {e}")
            return False
        return False

    def resume(self) -> bool:
        try:
            if sys.platform == "win32":
                exe = self._find_win_exe()
                if exe:
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
                    subprocess.Popen([exe, "/background"], creationflags=flags)
                    self._paused = False
                    return True
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "OneDrive", "--background"])
                self._paused = False
                return True
            else:
                subprocess.run(["pkill", "-CONT", "onedrive"], capture_output=True)
                self._paused = False
                return True
        except Exception as e:
            logger.warning(f"OneDrive Resume fehlgeschlagen: {e}")
            return False
        finally:
            self._paused = False
        return False

    @staticmethod
    def _find_win_exe() -> Optional[str]:
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\OneDrive\OneDrive.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft OneDrive\OneDrive.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft OneDrive\OneDrive.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return shutil.which("OneDrive.exe")


class GoogleDriveAdapter(CloudAdapter):
    name = "googledrive"
    display_name = "Google Drive"

    def __init__(self):
        self._paused = False

    def is_installed(self) -> bool:
        if sys.platform == "win32":
            return os.path.exists(os.path.expandvars(r"%PROGRAMFILES%\Google\Drive File Stream"))
        elif sys.platform == "darwin":
            return os.path.exists("/Applications/Google Drive.app")
        return False

    def is_running(self) -> bool:
        if self._paused:
            return False
        return self._find_process(["GoogleDriveFS", "Google Drive"])

    def pause(self) -> bool:
        if not self.is_running():
            return True
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/IM", "GoogleDriveFS.exe"], capture_output=True, timeout=10)
                self._paused = True
                return True
            elif sys.platform == "darwin":
                subprocess.run(["osascript", "-e", 'quit app "Google Drive"'], capture_output=True, timeout=10)
                self._paused = True
                return True
        except Exception as e:
            logger.warning(f"Google Drive Pause fehlgeschlagen: {e}")
            return False
        return False

    def resume(self) -> bool:
        try:
            if sys.platform == "win32":
                app_path = os.path.expandvars(r"%PROGRAMFILES%\Google\Drive File Stream\launch.bat")
                if os.path.exists(app_path):
                    subprocess.Popen([app_path], shell=True)
                self._paused = False
                return True
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Google Drive", "--background"])
                self._paused = False
                return True
        except Exception as e:
            logger.warning(f"Google Drive Resume fehlgeschlagen: {e}")
            return False
        finally:
            self._paused = False
        return False


class ICloudAdapter(CloudAdapter):
    name = "icloud"
    display_name = "Apple iCloud Drive"

    def __init__(self):
        self._paused = False

    def is_installed(self) -> bool:
        if sys.platform == "darwin":
            return True  # Native Bestandteil von macOS
        elif sys.platform == "win32":
            return os.path.exists(os.path.expandvars(r"%PROGRAMFILES%\WindowsApps\AppleInc.iCloud"))
        return False

    def is_running(self) -> bool:
        if self._paused:
            return False
        if sys.platform == "darwin":
            return self._find_process(["bird", "CloudDocs"])
        elif sys.platform == "win32":
            return self._find_process(["iCloud.exe", "iCloudDrive.exe"])
        return False

    def pause(self) -> bool:
        if not self.is_running():
            return True
        try:
            if sys.platform == "darwin":
                # bird ist der Hintergrund-Dienst fuer iCloud Docs auf macOS
                subprocess.run(["killall", "-STOP", "bird"], capture_output=True)
                self._paused = True
                return True
            elif sys.platform == "win32":
                subprocess.run(["taskkill", "/IM", "iCloudDrive.exe"], capture_output=True)
                self._paused = True
                return True
        except Exception as e:
            logger.warning(f"iCloud Pause fehlgeschlagen: {e}")
            return False
        return False

    def resume(self) -> bool:
        try:
            if sys.platform == "darwin":
                subprocess.run(["killall", "-CONT", "bird"], capture_output=True)
                self._paused = False
                return True
            elif sys.platform == "win32":
                app = shutil.which("iCloud.exe")
                if app:
                    subprocess.Popen([app])
                self._paused = False
                return True
        except Exception as e:
            logger.warning(f"iCloud Resume fehlgeschlagen: {e}")
            return False
        finally:
            self._paused = False
        return False


class DropboxAdapter(CloudAdapter):
    name = "dropbox"
    display_name = "Dropbox"

    def __init__(self):
        self._paused = False

    def is_installed(self) -> bool:
        if sys.platform == "win32":
            return os.path.exists(os.path.expandvars(r"%APPDATA%\Dropbox\bin\Dropbox.exe"))
        elif sys.platform == "darwin":
            return os.path.exists("/Applications/Dropbox.app")
        return shutil.which("dropbox") is not None

    def is_running(self) -> bool:
        if self._paused:
            return False
        return self._find_process(["Dropbox", "Dropbox.exe"])

    def pause(self) -> bool:
        if not self.is_running():
            return True
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/IM", "Dropbox.exe"], capture_output=True)
                self._paused = True
                return True
            elif sys.platform == "darwin":
                subprocess.run(["osascript", "-e", 'quit app "Dropbox"'], capture_output=True)
                self._paused = True
                return True
            else:
                subprocess.run(["dropbox", "stop"], capture_output=True)
                self._paused = True
                return True
        except Exception as e:
            logger.warning(f"Dropbox Pause fehlgeschlagen: {e}")
            return False
        return False

    def resume(self) -> bool:
        try:
            if sys.platform == "win32":
                exe = os.path.expandvars(r"%APPDATA%\Dropbox\bin\Dropbox.exe")
                if os.path.exists(exe):
                    subprocess.Popen([exe])
                self._paused = False
                return True
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Dropbox", "--background"])
                self._paused = False
                return True
            else:
                subprocess.run(["dropbox", "start"], capture_output=True)
                self._paused = False
                return True
        except Exception as e:
            logger.warning(f"Dropbox Resume fehlgeschlagen: {e}")
            return False
        finally:
            self._paused = False
        return False


class NextcloudAdapter(CloudAdapter):
    name = "nextcloud"
    display_name = "Nextcloud / ownCloud"

    def __init__(self):
        self._paused = False

    def is_installed(self) -> bool:
        if sys.platform == "win32":
            return os.path.exists(os.path.expandvars(r"%PROGRAMFILES%\Nextcloud\nextcloud.exe"))
        elif sys.platform == "darwin":
            return os.path.exists("/Applications/nextcloud.app")
        return shutil.which("nextcloud") is not None

    def is_running(self) -> bool:
        if self._paused:
            return False
        return self._find_process(["nextcloud", "nextcloud.exe"])

    def pause(self) -> bool:
        if not self.is_running():
            return True
        try:
            if sys.platform == "win32":
                subprocess.run(["nextcloud.exe", "--quit"], capture_output=True)
                self._paused = True
                return True
            elif sys.platform == "darwin":
                subprocess.run(["osascript", "-e", 'quit app "nextcloud"'], capture_output=True)
                self._paused = True
                return True
            else:
                subprocess.run(["pkill", "-STOP", "nextcloud"], capture_output=True)
                self._paused = True
                return True
        except Exception as e:
            logger.warning(f"Nextcloud Pause fehlgeschlagen: {e}")
            return False
        return False

    def resume(self) -> bool:
        try:
            if sys.platform == "win32":
                exe = os.path.expandvars(r"%PROGRAMFILES%\Nextcloud\nextcloud.exe")
                if os.path.exists(exe):
                    subprocess.Popen([exe, "--background"])
                self._paused = False
                return True
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "nextcloud", "--background"])
                self._paused = False
                return True
            else:
                subprocess.run(["pkill", "-CONT", "nextcloud"], capture_output=True)
                self._paused = False
                return True
        except Exception as e:
            logger.warning(f"Nextcloud Resume fehlgeschlagen: {e}")
            return False
        finally:
            self._paused = False
        return False


# ═══════════════════════════════════════════════════════════════
# Cloud Manager & Safety Watchdog
# ═══════════════════════════════════════════════════════════════

class CloudManager:
    """Zentraler Manager fuer alle Cloud-Sync-Adapter mit Auto-Resume-Watchdog."""

    def __init__(self):
        self.adapters: Dict[str, CloudAdapter] = {
            "onedrive": OneDriveAdapter(),
            "googledrive": GoogleDriveAdapter(),
            "icloud": ICloudAdapter(),
            "dropbox": DropboxAdapter(),
            "nextcloud": NextcloudAdapter(),
        }
        self._paused_at: Dict[str, float] = {}
        self._watchdog_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def get_status(self) -> Dict[str, Any]:
        """Liefert den Gesamtstatus aller Provider zurueck."""
        with self._lock:
            providers = {}
            active_count = 0
            paused_count = len(self._paused_at)

            for key, adapter in self.adapters.items():
                info = adapter.get_info()
                info["is_paused"] = key in self._paused_at
                info["paused_since"] = self._paused_at.get(key)
                if info["running"]:
                    active_count += 1
                providers[key] = info

            return {
                "active_providers_count": active_count,
                "paused_providers_count": paused_count,
                "has_paused_sync": paused_count > 0,
                "providers": providers,
                "platform": sys.platform,
            }

    def pause(self, provider: Optional[str] = None, timeout_seconds: int = 300) -> Dict[str, bool]:
        """
        Pausiert entweder einen bestimmten oder alle laufenden Provider.
        Startet automatisch einen Sicherheits-Watchdog.
        """
        results = {}
        targets = [provider.lower()] if provider and provider.lower() in self.adapters else list(self.adapters.keys())

        with self._lock:
            now = time.time()
            for key in targets:
                adapter = self.adapters[key]
                if adapter.is_running() or key in self._paused_at:
                    ok = adapter.pause()
                    results[key] = ok
                    if ok:
                        self._paused_at[key] = now
                        logger.info(f"[CloudControl] {adapter.display_name} pausiert (Timeout: {timeout_seconds}s)")

            # Safety Watchdog starten/erneuern
            self._arm_watchdog(timeout_seconds)

        return results

    def resume(self, provider: Optional[str] = None) -> Dict[str, bool]:
        """Reaktiviert entweder einen bestimmten oder alle pausierten Provider."""
        results = {}
        targets = [provider.lower()] if provider and provider.lower() in self.adapters else list(self.adapters.keys())

        with self._lock:
            for key in targets:
                if key in self._paused_at or not self.adapters[key].is_running():
                    adapter = self.adapters[key]
                    ok = adapter.resume()
                    results[key] = ok
                    if key in self._paused_at:
                        del self._paused_at[key]
                    logger.info(f"[CloudControl] {adapter.display_name} fortgesetzt")

            if not self._paused_at:
                self._disarm_watchdog()

        return results

    def toggle(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Schaltet zwischen Pause und Resume um."""
        with self._lock:
            status = self.get_status()
            if status["has_paused_sync"]:
                return self.resume(provider)
            else:
                return self.pause(provider)

    def _arm_watchdog(self, timeout_seconds: int):
        self._disarm_watchdog()
        if timeout_seconds > 0:
            self._watchdog_timer = threading.Timer(timeout_seconds, self._watchdog_trigger)
            self._watchdog_timer.daemon = True
            self._watchdog_timer.start()

    def _disarm_watchdog(self):
        if self._watchdog_timer:
            self._watchdog_timer.cancel()
            self._watchdog_timer = None

    def _watchdog_trigger(self):
        logger.warning("[CloudControl] Sicherheits-Watchdog ausgeloest: Pausierte Cloud-Dienste werden reaktiviert!")
        self.resume()


# Singleton-Instanz
_MANAGER: Optional[CloudManager] = None
_INIT_LOCK = threading.Lock()

def get_cloud_manager() -> CloudManager:
    global _MANAGER
    with _INIT_LOCK:
        if _MANAGER is None:
            _MANAGER = CloudManager()
        return _MANAGER


@contextmanager
def cloud_pause(provider: Optional[str] = None, timeout: int = 300):
    """
    Context-Manager fuer schreibintensive Operationen.
    Pausiert Cloud-Dienste fuer die Dauer des Blocks und setzt sie garantiert fort.
    """
    manager = get_cloud_manager()
    manager.pause(provider, timeout_seconds=timeout)
    try:
        yield manager
    finally:
        manager.resume(provider)
