#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bridge Reset Tool
=================
Bereinigt alle Bridge-Sperren nach einem Force-Kill (taskkill /F).

Was wird zurueckgesetzt:
  - Alle laufenden pythonw3.12.exe Prozesse (Tray + Daemon)
  - bach_bridge.lock  (Daemon-Prozess-Lock, in Temp)
  - bach_bridge_tray.lock  (Tray-Prozess-Lock, in Temp)
  - bridge_session_lock in bach.db (Fackel, System-Ebene)

Danach: Tray normal starten (pythonw bridge_tray.py)
"""

import subprocess
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

BRIDGE_DIR = Path(__file__).parent.resolve()
DB_PATH = BACH_DB


def main():
    print("=== Bridge Reset ===")

    # 1. Laufende pythonw Prozesse anzeigen und beenden
    result = subprocess.run(
        'tasklist /FI "IMAGENAME eq pythonw3.12.exe" /FO CSV',
        shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    lines = [l for l in result.stdout.strip().splitlines() if 'pythonw' in l.lower()]
    if lines:
        print(f"Beende {len(lines)} pythonw-Prozess(e)...")
        kill = subprocess.run(
            ['taskkill', '/IM', 'pythonw3.12.exe', '/F'],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        print(" ", kill.stdout.strip() or kill.stderr.strip())
        time.sleep(2)
    else:
        print("Keine laufenden pythonw-Prozesse.")

    # 2. Lock-Dateien loeschen
    locks = [
        Path(tempfile.gettempdir()) / "bach_bridge.lock",
        Path(tempfile.gettempdir()) / "bach_bridge_tray.lock",
    ]
    for f in locks:
        if f.exists():
            try:
                f.unlink()
                print(f"Geloescht: {f.name}")
            except Exception as e:
                print(f"Fehler: {f.name}: {e}")
        else:
            print(f"Nicht vorhanden (ok): {f.name}")

    # 3. Fackel in DB zuruecksetzen
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("UPDATE bridge_session_lock SET is_active=0 WHERE session_type='bridge'")
            conn.commit()
            rows = conn.execute("SELECT pc_name, is_active FROM bridge_session_lock").fetchall()
            conn.close()
            print(f"Fackel zurueckgesetzt: {rows}")
        except Exception as e:
            print(f"Fehler beim Fackel-Reset: {e}")
    else:
        print(f"DB nicht gefunden: {DB_PATH}")

    print()
    print("Fertig. Tray jetzt starten:")
    print(f"  pythonw {BRIDGE_DIR / 'bridge_tray.py'}")


if __name__ == "__main__":
    main()
