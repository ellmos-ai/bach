#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Bridge-Fackel-Wrapper
=====================
Erweitert bridge_daemon.py mit Fackel-Funktionalität OHNE den Original-Code zu ändern.

Dieser Wrapper:
1. Prüft Fackel vor Start
2. Startet Heartbeat-Thread
3. Gibt Fackel bei Shutdown frei
4. Ruft dann Original-Daemon auf
"""

import sys
import time
import signal
import atexit
from pathlib import Path
from threading import Thread, Event

# Fackel-Modul importieren
try:
    from .fackel import acquire_fackel, heartbeat, release_fackel, get_fackel_holder
except ImportError:
    from fackel import acquire_fackel, heartbeat, release_fackel, get_fackel_holder

# Logger
def log(msg: str, level: str = "INFO"):
    print(f"[{level}] {msg}")

# Heartbeat-Thread
stop_event = Event()

def heartbeat_loop():
    """Sendet alle 60s Heartbeat."""
    while not stop_event.is_set():
        if heartbeat('bridge'):
            log("Heartbeat gesendet", "DEBUG")
        else:
            log("Heartbeat fehlgeschlagen - Fackel verloren?", "WARN")

        # Sleep in kleinen Intervallen für schnelleres Shutdown
        for _ in range(60):
            if stop_event.is_set():
                break
            time.sleep(1)

def cleanup():
    """Cleanup beim Beenden."""
    log("Stoppe Heartbeat-Thread...", "INFO")
    stop_event.set()

    log("Gebe Fackel frei...", "INFO")
    if release_fackel('bridge'):
        log("Fackel freigegeben", "INFO")
    else:
        log("Fackel konnte nicht freigegeben werden", "WARN")

def signal_handler(signum, frame):
    """Signal-Handler für SIGINT/SIGTERM."""
    log(f"Signal {signum} empfangen", "INFO")
    cleanup()
    sys.exit(0)

def main():
    """Hauptfunktion mit Fackel-Integration."""

    # 1. Fackel prüfen
    log("Prüfe Fackel...", "INFO")
    success, msg = acquire_fackel(session_type='bridge')

    if not success:
        holder = get_fackel_holder('bridge')
        log(f"Fackel blockiert von {holder}. Bridge startet NICHT.", "ERROR")
        print(f"\n[FACKEL] {msg}")
        print(f"[FACKEL] Bitte Bridge auf {holder} stoppen oder Fackel anfordern.\n")
        sys.exit(1)

    log(f"Fackel erworben: {msg}", "INFO")

    # 2. Cleanup-Handler registrieren
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 3. Heartbeat-Thread starten
    heartbeat_thread = Thread(target=heartbeat_loop, daemon=True, name="FackelHeartbeat")
    heartbeat_thread.start()
    log("Heartbeat-Thread gestartet", "INFO")

    # 4. Bridge-Daemon importieren und starten
    log("Starte Bridge-Daemon...", "INFO")
    try:
        import bridge_daemon
        bridge_daemon.main()
    except KeyboardInterrupt:
        log("KeyboardInterrupt empfangen", "INFO")
    except Exception as e:
        log(f"Fehler beim Daemon-Start: {e}", "ERROR")
    finally:
        cleanup()

if __name__ == "__main__":
    main()
