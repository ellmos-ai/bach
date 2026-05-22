"""
BACH Claude Remote Control Starter
===================================
Aktiviert das Remote-Control Permission-Profil aus der BACH-DB,
startet Claude Code mit --dangerously-skip-permissions und stellt
nach Beendigung automatisch das Normal-Profil wieder her.

Ablauf:
  1. Remote-Control-Profil aus BACH-DB laden und in settings.json schreiben
  2. Claude Code mit --dangerously-skip-permissions starten
  3. Nach Beendigung: Normal-Profil wiederherstellen (auch bei Ctrl+C)

Profile werden in BACH verwaltet:
  bach permissions list          - Profile anzeigen
  bach permissions show <name>   - Profil-Details
  bach permissions set <name>    - Regeln aendern
  bach permissions status        - Aktuellen Status pruefen
"""

import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path

# BACH system/ Verzeichnis ermitteln
SCRIPT_DIR = Path(__file__).parent
BACH_START_DIR = SCRIPT_DIR.parent
BACH_ROOT = BACH_START_DIR.parent
SYSTEM_DIR = BACH_ROOT / "system"

# sys.path fuer BACH-Imports
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))


def _restore_permissions():
    """Stellt das Normal-Profil wieder her (atexit/signal Handler)."""
    try:
        from hub.claude_permissions import deactivate_remote_control
        success, msg = deactivate_remote_control()
        print(f"\n  {msg}")
    except Exception as e:
        print(f"\n  [WARN] Permissions konnten nicht wiederhergestellt werden: {e}")
        print(f"         Manuell: bach permissions deactivate")


# Guard gegen mehrfache atexit-Registrierung
_atexit_registered = False


def main():
    global _atexit_registered

    print()
    print("  ============================================")
    print("  BACH Remote Control Starter")
    print("  ============================================")
    print()

    # 1. Remote-Control-Profil aktivieren
    print("  [1/3] Aktiviere Remote-Control-Profil...", end=" ")
    try:
        from hub.claude_permissions import activate_remote_control
        success, msg = activate_remote_control()
        if success:
            print("OK")
            for line in msg.split("\n"):
                print(f"        {line}")
        else:
            print(f"FEHLER: {msg}")
            sys.exit(1)
    except Exception as e:
        print(f"FEHLER: {e}")
        print("        Ist BACH korrekt installiert?")
        sys.exit(1)

    # 2. Restore bei Beendigung registrieren (einmalig)
    if not _atexit_registered:
        atexit.register(_restore_permissions)
        _atexit_registered = True

    # Signal-Handler fuer Ctrl+C
    original_sigint = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum, frame):
        _restore_permissions()
        # Original-Handler aufrufen
        if callable(original_sigint):
            original_sigint(signum, frame)
        else:
            sys.exit(0)

    signal.signal(signal.SIGINT, _sigint_handler)

    # 3. Claude Code starten
    print()
    print("  [2/3] Starte Claude Code...")
    print()
    print("  ============================================")
    print("  Nach dem Start: /rc eingeben")
    print("  QR-Code mit Claude App scannen")
    print("  Alle Permissions sind vorfreigeschaltet!")
    print("  ============================================")
    print()

    # Arbeitsverzeichnis bestimmen
    if len(sys.argv) > 1 and sys.argv[1] == "--desktop":
        cwd = os.path.expanduser("~/OneDrive/Desktop")
    elif len(sys.argv) > 1 and sys.argv[1] == "--bach":
        cwd = str(BACH_ROOT)
    else:
        cwd = str(BACH_ROOT)

    os.environ["PYTHONIOENCODING"] = "utf-8"

    cmd = ["claude", "--dangerously-skip-permissions"]

    try:
        result = subprocess.run(cmd, cwd=cwd)
    except FileNotFoundError:
        print("  [FEHLER] 'claude' nicht gefunden!")
        print("  Ist Claude Code installiert und im PATH?")
        # Permissions trotzdem wiederherstellen (via atexit)
        sys.exit(1)
    except KeyboardInterrupt:
        pass  # atexit kuemmert sich um Restore

    # 3. Permissions wiederherstellen (explizit, atexit ist Fallback)
    print()
    print("  [3/3] Stelle Normal-Profil wieder her...", end=" ")
    try:
        from hub.claude_permissions import deactivate_remote_control
        success, msg = deactivate_remote_control()
        # atexit abmelden da wir es schon gemacht haben
        atexit.unregister(_restore_permissions)
        if success:
            print("OK")
        else:
            print(f"WARNUNG: {msg}")
    except Exception as e:
        print(f"WARNUNG: {e}")

    print()
    print("  Session beendet.")
    sys.exit(getattr(result, "returncode", 0) if "result" in dir() else 0)


if __name__ == "__main__":
    main()
