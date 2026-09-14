# SPDX-License-Identifier: MIT
"""
CloudHandler - Providerneutrale Cloud-Sync-Steuerung
=====================================================
Kommandozeilen-Schnittstelle zur Steuerung von Cloud-Sync-Diensten
(OneDrive, Google Drive, iCloud, Dropbox, Nextcloud).

Befehle:
  bach cloud status                     Status aller erkannten Cloud-Dienste
  bach cloud pause [provider] [-t SEC]  Sync pausieren (mit Timeout)
  bach cloud resume [provider]          Sync fortsetzen
  bach cloud toggle [provider]          Umschalten
"""

import sys
import json
from pathlib import Path
from typing import Tuple, List, Optional
from hub.base import BaseHandler
from hub._services.cloud.cloud_manager import get_cloud_manager


class CloudHandler(BaseHandler):
    """Handler fuer Cloud-Sync Operationen."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.manager = get_cloud_manager()

    @property
    def profile_name(self) -> str:
        return "cloud"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data"

    def get_operations(self) -> dict:
        return {
            "status": "Status aller erkannten Cloud-Dienste anzeigen",
            "pause": "Sync pausieren (Standard: alle, optional: <provider> [-t SEK])",
            "resume": "Sync fortsetzen (Standard: alle, optional: <provider>)",
            "toggle": "Sync zwischen Pause und Aktiv umschalten",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        op = (operation or "status").lower()

        if op == "status":
            return self._status(args)
        elif op == "pause":
            return self._pause(args, dry_run)
        elif op == "resume":
            return self._resume(args, dry_run)
        elif op == "toggle":
            return self._toggle(args, dry_run)
        elif op == "help":
            return self._help()
        else:
            return self._status(args)

    def _status(self, args: List[str]) -> Tuple[bool, str]:
        status = self.manager.get_status()
        if "--json" in args or "-j" in args:
            return True, json.dumps(status, indent=2, ensure_ascii=False)

        lines = [
            "=== CLOUD SYNC STATUS ===",
            f"Plattform:          {status['platform']}",
            f"Aktive Provider:    {status['active_providers_count']}",
            f"Pausierte Provider: {status['paused_providers_count']}",
            "",
            "Provider-Details:",
            f"{'Provider':<15} {'Installiert':<12} {'Laeuft':<10} {'Status':<15}",
            "-" * 55,
        ]

        for key, p in status["providers"].items():
            inst_str = "Ja" if p["installed"] else "Nein"
            run_str = "Ja" if p["running"] else "Nein"
            state_str = "Pausiert" if p.get("is_paused") else ("Aktiv" if p["running"] else "Inaktiv")
            lines.append(f"{p['display_name']:<15} {inst_str:<12} {run_str:<10} {state_str:<15}")

        lines.append("")
        lines.append("Hinweis: Nutzen Sie 'bach cloud pause' vor Massen-Schreiboperationen.")
        return True, "\n".join(lines)

    def _pause(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        provider, timeout = self._parse_args(args)
        if dry_run:
            return True, f"[Dry-Run] Wuerde Cloud-Sync pausieren (Provider: {provider or 'alle'}, Timeout: {timeout}s)"

        results = self.manager.pause(provider, timeout_seconds=timeout)
        if not results:
            return True, "Keine aktiven Cloud-Dienste zum Pausieren gefunden."

        items = [f"{k}: {'OK' if v else 'Fehlgeschlagen'}" for k, v in results.items()]
        return True, f"Cloud-Sync pausiert (Timeout: {timeout}s) -> {', '.join(items)}"

    def _resume(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        provider, _ = self._parse_args(args)
        if dry_run:
            return True, f"[Dry-Run] Wuerde Cloud-Sync fortsetzen (Provider: {provider or 'alle'})"

        results = self.manager.resume(provider)
        if not results:
            return True, "Keine pausierten Cloud-Dienste vorhanden (oder Dienste laufen bereits)."

        items = [f"{k}: {'OK' if v else 'Fehlgeschlagen'}" for k, v in results.items()]
        return True, f"Cloud-Sync fortgesetzt -> {', '.join(items)}"

    def _toggle(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        provider, _ = self._parse_args(args)
        if dry_run:
            return True, f"[Dry-Run] Wuerde Cloud-Sync umschalten (Provider: {provider or 'alle'})"

        res = self.manager.toggle(provider)
        status = self.manager.get_status()
        state = "PAUSIERT" if status["has_paused_sync"] else "AKTIV"
        return True, f"Cloud-Sync Status ist nun: {state}"

    def _parse_args(self, args: List[str]) -> Tuple[Optional[str], int]:
        provider = None
        timeout = 300
        skip_next = False

        for i, a in enumerate(args):
            if skip_next:
                skip_next = False
                continue
            if a in ("-t", "--timeout") and i + 1 < len(args):
                try:
                    timeout = int(args[i + 1])
                    skip_next = True
                except ValueError:
                    pass
            elif not a.startswith("-") and provider is None:
                provider = a

        return provider, timeout

    def _help(self) -> Tuple[bool, str]:
        return True, (
            "BACH Cloud Control CLI\n"
            "======================\n"
            "  bach cloud status                     Zeigt Status aller erkannten Provider\n"
            "  bach cloud pause [provider] [-t SEC]  Pausiert Cloud-Sync mit Timeout (Standard: 300s)\n"
            "  bach cloud resume [provider]          Setzt Cloud-Sync fort\n"
            "  bach cloud toggle [provider]          Schaltet zwischen Pause und Resume um\n"
        )
