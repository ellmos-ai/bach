# SPDX-License-Identifier: MIT
"""
Telemetry Handler - Low-cardinality, privacy-first Zaehler (OPS-TELEM-001)
===========================================================================

Subcommands:
  bach telemetry report [days]      - Zaehler der letzten N Tage (Default 7)
  bach telemetry status             - Erfassungs-/Schema-Status
  bach telemetry reset --confirm    - alle Zaehler loeschen

Privacy: Es werden NUR aggregierte Zaehler mit validierten Labels
(Counter: agent_starts/model_calls/tool_calls; outcome: ok/error/dummy/timeout)
gespeichert -- keine Payloads, Prompts, Pfade oder Nutzerdaten.
Opt-Out: BACH_TELEMETRY_DISABLED=1

v1.0.0: Initial Implementation (OPS-TELEM-001, ROADMAP Security-Prio-1, Task #1315)
"""
from pathlib import Path
from .base import BaseHandler


class TelemetryHandler(BaseHandler):
    """Handler fuer bach telemetry"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "telemetry"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / ".telemetry"

    def get_operations(self) -> dict:
        return {
            "report": "Zaehler der letzten N Tage anzeigen (Default 7)",
            "status": "Erfassungs-/Schema-Status anzeigen",
            "reset": "Alle Zaehler loeschen (erfordert --confirm)"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            from core.telemetry import report, status, reset
        except Exception as e:
            return False, f"Telemetrie-Modul nicht verfuegbar: {e}"

        if operation == "report" or not operation:
            days = 7
            for arg in args:
                if arg.isdigit():
                    days = int(arg)
                    break
            if dry_run:
                return True, f"[DRY-RUN] Wuerde Telemetrie-Report ({days} Tage) zeigen"
            return report(days=days)

        elif operation == "status":
            if dry_run:
                return True, "[DRY-RUN] Wuerde Telemetrie-Status zeigen"
            return status()

        elif operation == "reset":
            if dry_run:
                return True, "[DRY-RUN] Wuerde alle Telemetrie-Zaehler loeschen"
            return reset(confirm="--confirm" in args)

        elif operation == "help":
            return True, self._help()

        return False, (
            f"Unbekannte Operation: {operation}\n" + self._help()
        )

    def _help(self) -> str:
        return "\n".join([
            "",
            "[TELEMETRIE] Low-cardinality Zaehler (OPS-TELEM-001)",
            "=" * 50,
            "  Befehle:",
            "    bach telemetry report [days]    - Report (Default 7 Tage)",
            "    bach telemetry status           - Status",
            "    bach telemetry reset --confirm  - Zaehler loeschen",
            "",
            "  Privacy: Nur Zaehler, keine Payloads.",
            "  Opt-Out: BACH_TELEMETRY_DISABLED=1",
        ])