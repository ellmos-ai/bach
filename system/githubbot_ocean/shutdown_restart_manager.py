# SPDX-License-Identifier: MIT
"""Shutdown-/Restart-Verwaltung und Idempotenz-Ergebnisnachweis für GitHubBot-OCEAN.

Bietet idempotente Shutdown- und Restart-Operationen, eine einfaches Ergebnisprotokoll
und Absicherungen für Secrets-Scan und git diff Checks.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pfad zur Ergebnisprotokoll-Datei innerhalb dieses Moduls
_RESULT_LOG_PATH = Path(__file__).parent / "shutdown_results.jsonl"
_LOCK_FILE = Path(__file__).parent / ".shutdown_restart.lock"
def _acquire_lock() -> bool:
    """Idempotenter Lock: Erworben, wenn kein anderer Shutdown/Restart läuft.

    Gibt True zurück, wenn der Lock erfolgreich erworben wurde, andernfalls False.
    """
    if _LOCK_FILE.exists():
        # Wenn die Lock-Datei existiert, prüfen Sie, ob ein Prozess läuft.
        try:
            pid = int(_LOCK_FILE.read_text().strip())
            # Unix-only: Prüfen Sie, ob der Prozess existiert
            os.kill(pid, 0)
            logger.debug("Shutdown/Restart-Lock ist bereits belegt durch PID %s", pid)
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            # Lock-Datei veraltet – löschen
            _LOCK_FILE.unlink(missing_ok=True)
    # Erstellen Sie den Lock mit aktuellem PID
    import os as _os
    _LOCK_FILE.write_text(str(_os.getpid()))
    logger.debug("Shutdown/Restart-Lock für PID %s erworben", _os.getpid())
    return True
def _release_lock() -> None:
    _LOCK_FILE.unlink(missing_ok=True)
def record_result(operation: str, status: str, details: dict[str, Any] | None = None) -> None:
    """Schreibt einen Ergebnisdatensatz in das Idempotenz-Protokoll."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "operation": operation,
        "status": status,
        "details": details or {},
    }
    try:
        with _RESULT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info("Ergebnis aufgezeichnet: %s %s", operation, status)
    except Exception as e:
        logger.error("Fehler beim Aufzeichnen des Ergebnisses: %s", e)
def run_secrets_scan() -> bool:
    """Führt einen Secrets-Scan durch (Placeholde für tatsächliches Tool)."""
    # Beispiel: Führen Sie `detect-secrets scan` aus oder einen benutzerdefinierten Scan.
    # Für diese Implementierung simulieren wir einen Scan und geben True zurück.
    logger.info("Secrets-Scan wird durchgeführt (stub)")
    return True
def check_git_diff() -> bool:
    """Überprüft, ob es ungeprüfte Änderungen gibt (git diff --check)."""
    try:
        subprocess.run(["git", "diff", "--check"], check=True, capture_output=True)
        logger.info("Git diff --check bestanden")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("Git diff --check fehlgeschlagen: %s", e.stderr.decode())
        return False
def shutdown(reason: str = "normal", force: bool = False) -> bool:
    """Führt einen sicheren Shutdown durch, mit Idempotenz und Ergebnisprotokoll.

    Gibt True zurück, wenn der Shutdown erfolgreich war, sonst False.
    """
    if not _acquire_lock():
        logger.warning("Shutdown bereits aktiv; überspringen (idempotent)")
        return False

    try:
        record_result("shutdown", "started", {"reason": reason, "force": force})
        # Hier könnten Sie echte Shutdown-Logik einfügen (z. B. Dienste stoppen)
        # Demonstrieren Sie einen Shutdown mit echo
        subprocess.run(["echo", f"SHUTDOWN: {reason}"], check=True)
        logger.info("Shutdown abgeschlossen (%s)", reason)
        record_result("shutdown", "completed", {"reason": reason})
        # Optional: Führen Sie den Secrets-Scan und git diff Check vor dem Beenden durch
        run_secrets_scan()
        check_git_diff()
        return True
    except Exception as e:
        logger.exception("Shutdown-Fehler: %s", e)
        record_result("shutdown", "failed", {"reason": reason, "error": str(e)})
        return False
    finally:
        _release_lock()
def restart(reason: str = "normal") -> bool:
    """Führt einen sicheren Restart durch, mit Idempotenz und Ergebnisprotokoll.

    Gibt True zurück, wenn der Restart erfolgreich war, sonst False.
    """
    if not _acquire_lock():
        logger.warning("Restart bereits aktiv; überspringen (idempotent)")
        return False

    try:
        record_result("restart", "started", {"reason": reason})
        # Demonstrieren Sie einen Restart mit echo
        subprocess.run(["echo", f"RESTART: {reason}"], check=True)
        logger.info("Restart abgeschlossen (%s)", reason)
        record_result("restart", "completed", {"reason": reason})
        run_secrets_scan()
        check_git_diff()
        return True
    except Exception as e:
        logger.exception("Restart-Fehler: %s", e)
        record_result("restart", "failed", {"reason": reason, "error": str(e)})
        return False
    finally:
        _release_lock()

__all__ = ["shutdown", "restart", "record_result", "run_secrets_scan", "check_git_diff"]