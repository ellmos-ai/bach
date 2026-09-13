# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Security Handler - Statischer Sicherheits-Scan fuer BACH
========================================================

Scannt BACH-eigene Code-Pfade auf gefaehrliche Muster und erzeugt
einen kategorisierten Report. Verwendet das Capability-System
(core.capabilities) fuer die eigentliche Pattern-Erkennung.

Usage:
    bach security scan                  Scannt Standard-Pfade
    bach security scan tools/           Scannt bestimmtes Verzeichnis
    bach security scan --json           JSON-Report
    bach security scan --dry-run        Zeigt was gescannt wuerde
    bach security status                Letzten Report anzeigen
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from .base import BaseHandler


class SecurityHandler(BaseHandler):
    """Handler fuer statische Sicherheits-Scans."""

    DEFAULT_PATHS = ("tools", "skills", "hub", "core", "scripts", "bin")
    REPORT_FILE = "security_scan_latest.json"

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self._report_path = self.base_path / "data" / self.REPORT_FILE

    @property
    def profile_name(self) -> str:
        return "security"

    @property
    def target_file(self) -> Path:
        return self.base_path / "core" / "capabilities.py"

    def get_operations(self) -> dict:
        return {
            "scan": "Sicherheits-Scan starten: scan [PATH] [--json] [--dry-run]",
            "status": "Letzten Scan-Report anzeigen",
            "report": "Report ausgeben: report [--json]",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "scan":
            return self._scan(args, dry_run)
        if operation == "status":
            return self._status(args)
        if operation == "report":
            return self._report(args)
        return False, f"[ERROR] Unbekannte Operation: {operation}"

    def _scan(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        use_json = "--json" in args
        # remove flags from path detection
        positional = [a for a in args if not a.startswith("-")]

        if dry_run:
            paths = positional or list(self.DEFAULT_PATHS)
            return True, (
                "[DRY-RUN] Sicherheits-Scan wuerde folgende Pfade pruefen:\n"
                + "\n".join(f"  - {p}" for p in paths)
            )

        try:
            from core.capabilities import capability_manager
        except Exception as e:
            return False, f"[ERROR] Capability-Manager nicht ladbar: {e}"

        paths = []
        for p in positional:
            candidate = Path(p)
            if not candidate.is_absolute():
                candidate = self.base_path / candidate
            if candidate.exists():
                paths.append(candidate)
            else:
                return False, f"[ERROR] Pfad nicht gefunden: {candidate}"

        if not paths:
            for name in self.DEFAULT_PATHS:
                candidate = self.base_path / name
                if candidate.exists():
                    paths.append(candidate)

        report: dict = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scanner": "core.capabilities.security_scan",
            "paths": [str(p) for p in paths],
            "findings_by_file": {},
            "summary": {"critical": 0, "warning": 0, "info": 0, "total_files": 0},
        }

        for path in paths:
            findings_by_file = capability_manager.scan_tree_detailed(path)
            for file_path, findings in findings_by_file.items():
                if file_path not in report["findings_by_file"]:
                    report["findings_by_file"][file_path] = []
                for severity, message in findings:
                    report["findings_by_file"][file_path].append(
                        {"severity": severity, "message": message}
                    )
                    report["summary"][severity] = report["summary"].get(severity, 0) + 1
                    report["summary"]["total_files"] += 1

        self._save_report(report)

        if use_json:
            return True, json.dumps(report, indent=2, ensure_ascii=False)
        return True, self._render_text_report(report)

    def _status(self, args: list) -> Tuple[bool, str]:
        use_json = "--json" in args
        report = self._load_report()
        if not report:
            return True, "[INFO] Noch kein Sicherheits-Report vorhanden. Fuehre 'bach security scan' aus."
        if use_json:
            return True, json.dumps(report, indent=2, ensure_ascii=False)
        return True, self._render_text_report(report)

    def _report(self, args: list) -> Tuple[bool, str]:
        return self._status(args)

    def _render_text_report(self, report: dict) -> str:
        lines = [
            "BACH Security Scan Report",
            "=" * 50,
            f"Erzeugt: {report.get('generated_at', 'unbekannt')}",
            f"Gepruefte Pfade: {len(report.get('paths', []))}",
            "",
            "Zusammenfassung:",
            f"  CRITICAL: {report['summary'].get('critical', 0)}",
            f"  WARNING:  {report['summary'].get('warning', 0)}",
            f"  INFO:     {report['summary'].get('info', 0)}",
            "",
        ]

        findings = report.get("findings_by_file", {})
        if not findings:
            lines.append("Keine Findings. BACH-Code ist aus Scanner-Sicht sauber.")
            return "\n".join(lines)

        lines.append("Findings:")
        for file_path in sorted(findings):
            lines.append(f"\n  {file_path}")
            for item in findings[file_path]:
                sev = item.get("severity", "info").upper()
                msg = item.get("message", "")
                lines.append(f"    [{sev}] {msg}")
        return "\n".join(lines)

    def _save_report(self, report: dict) -> None:
        try:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            self._report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_report(self) -> dict | None:
        try:
            if not self._report_path.exists():
                return None
            return json.loads(self._report_path.read_text(encoding="utf-8"))
        except Exception:
            return None
