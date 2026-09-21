# SPDX-License-Identifier: MIT
"""
hub/api_prober.py -- BACH-Handler fuer ApiProber-Integration
=============================================================
Delegiert an MODULAR_AGENTS/ApiProber/ fuer die eigentliche Implementierung.

Operationen:
    bach api-prober probe <url> [--depth N] [--delay-ms N]  -- API abtasten
    bach api-prober list                                     -- Services auflisten
    bach api-prober status <service>                         -- Service-Details
    bach api-prober export <service> [--format md|json]      -- Export
    bach api-prober config [--show]                          -- Konfiguration

SQ080 | Version: 1.0.0 (B36-Fix: Timeout-Bug behoben)
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import List, Tuple

from .base import BaseHandler

# Absoluter Pfad zum MODULAR_AGENTS/ApiProber Modul
_API_PROBER_ROOT = Path.home() / "OneDrive" / ".AI" / "MODULAR_AGENTS" / "ApiProber"
_MODULAR_AGENTS_ROOT = _API_PROBER_ROOT.parent


def _ensure_api_prober_importable():
    """Stellt sicher, dass ApiProber als Package importiert werden kann.

    Fuegt MODULAR_AGENTS/ zu sys.path hinzu (nicht ApiProber/ selbst),
    damit `from ApiProber.core.config import ...` funktioniert.
    """
    modular_str = str(_MODULAR_AGENTS_ROOT)
    if modular_str not in sys.path:
        sys.path.insert(0, modular_str)


class ApiProberHandler(BaseHandler):
    """BACH-Handler fuer ApiProber -- delegiert an MODULAR_AGENTS/ApiProber.

    Implementierte Operationen:
        probe  -- API-URL abtasten (via ProbeOrchestrator)
        list   -- Bekannte Services auflisten (via Database)
        status -- Service-Details anzeigen (via Database)
        export -- Ergebnisse als Markdown/JSON exportieren
        config -- Konfiguration anzeigen
    """

    @property
    def profile_name(self) -> str:
        # Effektiver Registry-Name (vorher: totes Klassen-Attribut "api-prober",
        # das nie griff — Registry fiel auf Klassennamen zurueck. Task #1321)
        return "apiprober"

    @property
    def target_file(self) -> Path:
        return self.base_path / "hub" / "api_prober.py"

    def get_operations(self) -> dict:
        return {
            "probe":  "API-URL abtasten: probe <url> [--depth N] [--delay-ms N] [--max-requests N]",
            "list":   "Bekannte Services auflisten",
            "status": "Service-Status anzeigen: status <service-name>",
            "export": "Ergebnisse exportieren: export <service> [--format md|json]",
            "config": "Konfiguration anzeigen: config [--show]",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> Tuple[bool, str]:
        """Dispatch an die jeweilige Operation.

        Args:
            operation: Name der Operation (probe, list, status, export, config)
            args: Zusaetzliche Argumente als Liste
            dry_run: Wenn True, nur Beschreibung ausgeben

        Returns:
            (success: bool, message: str)
        """
        # Pruefen ob ApiProber-Modul existiert
        if not _API_PROBER_ROOT.exists():
            return False, (
                f"ApiProber-Modul nicht gefunden: {_API_PROBER_ROOT}\n"
                f"Erwartet unter: MODULAR_AGENTS/ApiProber/"
            )

        dispatch = {
            "probe":  self._op_probe,
            "list":   self._op_list,
            "status": self._op_status,
            "export": self._op_export,
            "config": self._op_config,
        }

        handler_fn = dispatch.get(operation)
        if handler_fn is None:
            ops_list = "\n".join(f"  {k}: {v}" for k, v in self.get_operations().items())
            return False, f"Unbekannte Operation: '{operation}'\n\nVerfuegbar:\n{ops_list}"

        if dry_run:
            return True, f"[dry-run] Wuerde ausfuehren: api-prober {operation} {' '.join(args)}"

        try:
            _ensure_api_prober_importable()
            return handler_fn(args)
        except ImportError as e:
            return False, (
                f"Import-Fehler: {e}\n"
                f"Stelle sicher, dass ApiProber korrekt installiert ist unter:\n"
                f"  {_API_PROBER_ROOT}"
            )
        except Exception as e:
            return False, f"Fehler bei api-prober {operation}: {type(e).__name__}: {e}"

    # ── Operationen ────────────────────────────────────────────────────

    def _op_probe(self, args: list) -> Tuple[bool, str]:
        """API-URL abtasten.

        Verwendung: probe <url> [--depth N] [--delay-ms N] [--max-requests N]
        """
        if not args:
            return False, (
                "Verwendung: api-prober probe <url> [--depth N] [--delay-ms N]\n"
                "Beispiel:   api-prober probe https://api.example.com --depth 2"
            )

        from ApiProber.core.config import load_config
        from ApiProber.discovery.orchestrator import ProbeOrchestrator

        url = args[0]
        config = load_config()

        # CLI-Argumente parsen (einfach Key-Value)
        i = 1
        while i < len(args):
            arg = args[i]
            if arg == "--depth" and i + 1 < len(args):
                config["max_depth"] = int(args[i + 1])
                i += 2
            elif arg == "--delay-ms" and i + 1 < len(args):
                config["delay_ms"] = int(args[i + 1])
                i += 2
            elif arg == "--max-requests" and i + 1 < len(args):
                config["max_requests"] = int(args[i + 1])
                i += 2
            elif arg == "--timeout" and i + 1 < len(args):
                timeout_val = int(args[i + 1])
                config["read_timeout_s"] = timeout_val
                config["timeout_seconds"] = timeout_val
                i += 2
            else:
                i += 1

        # Probe ausfuehren -- stdout capturen
        output = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(output):
                orchestrator = ProbeOrchestrator(config)
                result = orchestrator.probe(url, depth=config.get("max_depth"))
        except Exception as e:
            captured = output.getvalue()
            return False, f"Probe fehlgeschlagen: {e}\n\nOutput:\n{captured}"

        captured = output.getvalue()

        if result and result.get("error"):
            return False, f"Probe-Fehler: {result['error']}\n\n{captured}"

        # Zusammenfassung
        summary_lines = [captured]
        if result:
            summary_lines.append(f"\nErgebnis:")
            summary_lines.append(f"  Service:    {result.get('service', '?')}")
            summary_lines.append(f"  Endpoints:  {result.get('endpoints_found', 0)}")
            summary_lines.append(f"  Requests:   {result.get('total_requests', 0)}")
            summary_lines.append(f"  Status:     {result.get('status', '?')}")

        return True, "\n".join(summary_lines)

    def _op_list(self, args: list) -> Tuple[bool, str]:
        """Alle bekannten Services auflisten."""
        from ApiProber.core.config import load_config, get_db_path
        from ApiProber.core.database import Database

        config = load_config()
        db_path = get_db_path(config)

        if not db_path.exists():
            return True, "Keine Datenbank vorhanden. Starte zuerst: api-prober probe <url>"

        db = Database(db_path)
        services = db.list_services()

        if not services:
            return True, "Keine Services gespeichert."

        lines = []
        lines.append(f"{'Name':<25} {'Base-URL':<45} {'Endpoints':<10} {'Letztes Probing'}")
        lines.append("-" * 95)
        for svc in services:
            stats = db.get_service_stats(svc["id"])
            last = svc.get("last_probed", "-") or "-"
            if last and len(last) > 16:
                last = last[:16]
            lines.append(f"{svc['name']:<25} {svc['base_url']:<45} {stats['endpoints']:<10} {last}")

        lines.append(f"\n{len(services)} Service(s) gesamt.")
        return True, "\n".join(lines)

    def _op_status(self, args: list) -> Tuple[bool, str]:
        """Service-Status detailliert anzeigen."""
        if not args:
            return False, (
                "Verwendung: api-prober status <service-name>\n"
                "Tipp: api-prober list zeigt alle Services"
            )

        service_name = args[0]

        from ApiProber.core.config import load_config, get_db_path
        from ApiProber.core.database import Database

        config = load_config()
        db = Database(get_db_path(config))

        service = db.get_service(service_name)
        if not service:
            return False, f"Service '{service_name}' nicht gefunden.\nTipp: api-prober list"

        stats = db.get_service_stats(service["id"])
        endpoints = db.get_endpoints(service["id"])
        runs = db.get_probe_runs(service["id"])

        lines = []
        lines.append(f"Service: {service['name']}")
        lines.append(f"URL:     {service['base_url']}")
        lines.append(f"Server:  {service.get('server_header', '-')}")
        lines.append(f"Entdeckt:  {service.get('discovered_at', '-')}")
        lines.append(f"Letztes Probing: {service.get('last_probed', '-')}")
        lines.append("")
        lines.append(f"Endpoints:  {stats['endpoints']}")
        lines.append(f"Responses:  {stats['responses']}")
        lines.append(f"Parameter:  {stats['parameters']}")
        lines.append(f"Probe-Runs: {len(runs)}")

        if endpoints:
            lines.append("")
            lines.append("Endpoints:")
            for ep in endpoints:
                methods = json.loads(ep.get("methods_json", "[]"))
                auth = " [AUTH]" if ep.get("auth_required") else ""
                methods_str = ", ".join(methods) if methods else "?"
                lines.append(f"  {methods_str:<30} {ep['path']}{auth}")

        return True, "\n".join(lines)

    def _op_export(self, args: list) -> Tuple[bool, str]:
        """Ergebnisse exportieren."""
        if not args:
            return False, "Verwendung: api-prober export <service> [--format md|json]"

        service_name = args[0]
        fmt = "md"

        # Format-Argument parsen
        for i, arg in enumerate(args):
            if arg in ("--format", "-f") and i + 1 < len(args):
                fmt = args[i + 1]

        from ApiProber.core.config import load_config, get_db_path, get_export_dir
        from ApiProber.core.database import Database

        config = load_config()
        db = Database(get_db_path(config))

        service = db.get_service(service_name)
        if not service:
            return False, f"Service '{service_name}' nicht gefunden."

        export_dir = get_export_dir(config)
        export_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "md":
            from ApiProber.export.markdown import export_markdown
            output_path = export_dir / f"{service['name']}_api.md"
            export_markdown(db, service, output_path)
            return True, f"Markdown exportiert: {output_path}"

        elif fmt == "json":
            from ApiProber.export.json_export import export_json
            output_path = export_dir / f"{service['name']}_api.json"
            export_json(db, service, output_path)
            return True, f"JSON exportiert: {output_path}"

        else:
            return False, f"Unbekanntes Format: {fmt}. Unterstuetzt: md, json"

    def _op_config(self, args: list) -> Tuple[bool, str]:
        """Konfiguration anzeigen."""
        from ApiProber.core.config import load_config

        config = load_config()

        # Timeout-Info hervorheben (B36-Fix)
        lines = []
        lines.append("ApiProber-Konfiguration:")
        lines.append(json.dumps(config, indent=4, ensure_ascii=False))
        lines.append("")
        lines.append("Timeout-Konfiguration (B36-Fix):")
        lines.append(f"  connect_timeout_s: {config.get('connect_timeout_s', '?')}s")
        lines.append(f"  read_timeout_s:    {config.get('read_timeout_s', '?')}s")
        lines.append(f"  max_retries:       {config.get('max_retries', '?')}")
        lines.append(f"  timeout_seconds:   {config.get('timeout_seconds', '?')}s (Legacy-Key)")

        return True, "\n".join(lines)
