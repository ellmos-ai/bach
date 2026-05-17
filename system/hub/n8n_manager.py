# SPDX-License-Identifier: MIT
"""
n8n_manager.py -- n8n Workflow Manager BACH-Integration
=======================================================

Bietet BACH-Handler-Interface fuer n8n-Workflow-Verwaltung.
Setzt voraus, dass n8n-manager-mcp optional installiert wurde (bach setup n8n).

n8n laeuft standardmaessig auf Port 5678.
Verbindung: http://localhost:5678 (konfigurierbar via n8n_base_url)

B37: Von STUB zu funktionierendem Handler umgebaut.
     MCP-Server wird optional via `bach setup n8n` installiert.

Referenz: MODULAR_AGENTS/n8nManager/README.md
SQ081: n8n Workflow Manager
"""
from __future__ import annotations

import json
import subprocess
import shutil
import urllib.request
import urllib.error
from typing import Optional


class N8nManagerHandler:
    """
    BACH-Handler fuer n8n Workflow Manager Integration.

    Stellt n8n-Operationen bereit:
    - status: n8n-Instanz pruefen + MCP-Installation pruefen
    - list:   Workflows auflisten (via n8n REST API)
    - sync:   Workflows synchronisieren (delegiert an MCP-Server)

    Voraussetzung: n8n-manager-mcp muss installiert sein (bach setup n8n).
    Verbindung: konfigurierbar, Standard http://localhost:5678
    """

    profile_name = "n8n-manager"
    N8N_DEFAULT_URL = 'http://localhost:5678'
    MCP_PACKAGE = 'n8n-manager-mcp'

    def __init__(self, n8n_base_url: str = None):
        self.n8n_base_url = n8n_base_url or self.N8N_DEFAULT_URL
        self._mcp_installed = None  # Cache

    def get_operations(self) -> dict:
        """Gibt verfuegbare Operationen zurueck."""
        return {
            "status": "n8n Status pruefen (Instanz + MCP-Server)",
            "list":   "Workflows auflisten via n8n API",
            "sync":   "Workflows synchronisieren via MCP-Server",
        }

    def is_mcp_installed(self) -> bool:
        """Prueft ob n8n-manager-mcp global installiert ist (cached)."""
        if self._mcp_installed is not None:
            return self._mcp_installed

        npm_path = shutil.which("npm")
        if not npm_path:
            self._mcp_installed = False
            return False

        try:
            proc = subprocess.run(
                ["npm", "list", "-g", self.MCP_PACKAGE, "--depth=0"],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=15
            )
            self._mcp_installed = (
                proc.returncode == 0 and self.MCP_PACKAGE in proc.stdout
            )
        except Exception:
            self._mcp_installed = False

        return self._mcp_installed

    def _check_n8n_running(self) -> bool:
        """Prueft ob n8n erreichbar ist."""
        try:
            req = urllib.request.urlopen(
                f'{self.n8n_base_url}/healthz',
                timeout=3
            )
            return req.status == 200
        except (urllib.error.URLError, Exception):
            pass
        # Fallback: /api/v1/workflows pruefen
        try:
            req = urllib.request.urlopen(
                f'{self.n8n_base_url}/api/v1/workflows',
                timeout=3
            )
            return True
        except Exception:
            return False

    def _not_installed_message(self) -> dict:
        """Gibt Hinweis zurueck wenn MCP-Server nicht installiert ist."""
        return {
            'status': 'not_installed',
            'message': (
                f'{self.MCP_PACKAGE} ist nicht installiert.\n'
                f'Installation mit: bach setup n8n\n'
                f'\n'
                f'Das installiert den n8n MCP-Server global via npm\n'
                f'und konfiguriert Claude Code automatisch.'
            ),
        }

    def _list_workflows(self) -> dict:
        """Listet n8n-Workflows via REST API auf."""
        try:
            req = urllib.request.urlopen(
                f'{self.n8n_base_url}/api/v1/workflows',
                timeout=10
            )
            data = json.loads(req.read().decode('utf-8'))
            workflows = data.get('data', data) if isinstance(data, dict) else data

            if not workflows:
                return {
                    'status': 'ok',
                    'workflows': [],
                    'count': 0,
                    'message': 'Keine Workflows gefunden',
                }

            # Workflow-Zusammenfassung erstellen
            summary = []
            for wf in workflows:
                wf_info = {
                    'id': wf.get('id', '?'),
                    'name': wf.get('name', 'Unbenannt'),
                    'active': wf.get('active', False),
                }
                summary.append(wf_info)

            return {
                'status': 'ok',
                'workflows': summary,
                'count': len(summary),
                'message': f'{len(summary)} Workflow(s) gefunden',
            }
        except urllib.error.HTTPError as e:
            return {
                'status': 'error',
                'message': f'n8n API Fehler: HTTP {e.code} - {e.reason}',
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Fehler beim Abrufen der Workflows: {e}',
            }

    def handle(self, operation: str = 'status', **kwargs) -> dict:
        """
        Hauptentrypoint fuer BACH-Handler-Aufrufe.

        Args:
            operation: 'status' | 'list' | 'sync'
            **kwargs:  Operation-spezifische Parameter

        Returns:
            dict mit Ergebnis
        """
        if operation == 'status':
            mcp_installed = self.is_mcp_installed()
            n8n_running = self._check_n8n_running()

            status = 'ok' if (mcp_installed and n8n_running) else 'warning'
            parts = []
            if mcp_installed:
                parts.append(f'[OK] {self.MCP_PACKAGE} installiert')
            else:
                parts.append(f'[!!] {self.MCP_PACKAGE} nicht installiert (bach setup n8n)')
            if n8n_running:
                parts.append(f'[OK] n8n erreichbar ({self.n8n_base_url})')
            else:
                parts.append(f'[!!] n8n nicht erreichbar ({self.n8n_base_url})')

            return {
                'status': status,
                'mcp_installed': mcp_installed,
                'n8n_running': n8n_running,
                'n8n_url': self.n8n_base_url,
                'message': '\n'.join(parts),
            }

        elif operation == 'list':
            # MCP-Server muss nicht installiert sein fuer list -- direkter API-Zugriff
            if not self._check_n8n_running():
                return {
                    'status': 'error',
                    'message': (
                        'n8n nicht erreichbar -- bitte n8n starten.\n'
                        f'Erwartete Adresse: {self.n8n_base_url}'
                    ),
                }
            return self._list_workflows()

        elif operation == 'sync':
            if not self.is_mcp_installed():
                return self._not_installed_message()
            if not self._check_n8n_running():
                return {
                    'status': 'error',
                    'message': (
                        'n8n nicht erreichbar -- bitte n8n starten.\n'
                        f'Erwartete Adresse: {self.n8n_base_url}'
                    ),
                }
            # Sync delegiert an MCP-Server (der ueber Claude Code laeuft)
            return {
                'status': 'ok',
                'message': (
                    'n8n-manager-mcp ist installiert und n8n ist erreichbar.\n'
                    'Sync-Operationen laufen ueber den MCP-Server in Claude Code.\n'
                    'Nutze die n8n-manager MCP-Tools direkt in Claude Code:\n'
                    '  - n8n_list_workflows\n'
                    '  - n8n_get_workflow\n'
                    '  - n8n_create_workflow\n'
                    '  - n8n_activate_workflow\n'
                    '  - n8n_export_workflow / n8n_import_workflow'
                ),
            }

        else:
            ops = list(self.get_operations().keys())
            return {
                'status': 'error',
                'message': f"Unbekannte Operation: '{operation}'. Verfuegbar: {ops}",
            }

    def get_info(self) -> dict:
        """Gibt Handler-Info zurueck."""
        mcp_installed = self.is_mcp_installed()
        return {
            'handler': 'N8nManagerHandler',
            'profile': self.profile_name,
            'n8n_url': self.n8n_base_url,
            'mcp_package': self.MCP_PACKAGE,
            'mcp_installed': mcp_installed,
            'status': 'active' if mcp_installed else 'not_installed',
            'operations': list(self.get_operations().keys()),
        }
