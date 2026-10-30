#!/usr/bin/env python3
"""
Lock Scanner - Identifiziert Locks und Scan-Depth-Status für Verzeichnisbaumüberprüfungen.
Kanonische Quelle: ellmos-ai/lock-master (pure-locking/lock_scan.py)
Rootdatei ist nur ein Kompatibilitätsshim.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


# Sicherheitsgrenze, um Zyklen zu vermeiden
MAX_SYMLINK_DEPTH = 20


def classify_symlink(path: Path) -> str | None:
    """Klassifiziert einen Symlink ohne ihm rekursiv zu folgen.

    Gibt None zurück, wenn der Pfad kein Symlink ist.
    Für einen Datei-Symlink (Ziel ist reguläre Datei) liefert "symlink_to_file".
    Für ein Verzeichnis-/Junction-Symlink liefert "symlink_to_directory".
    Für unlesbare, kaputte oder unklare Ziele liefert "symlink_broken".
    """
    if not path.is_symlink():
        return None
    try:
        st = path.lstat()
    except OSError:
        return "symlink_broken"

    from stat import S_ISDIR, S_ISREG, S_ISLNK

    if S_ISLNK(st.st_mode):
        try:
            target_st = path.stat()  # folgt dem Symlink einmal
        except OSError:
            return "symlink_broken"
        if S_ISREG(target_st.st_mode):
            return "symlink_to_file"
        if S_ISDIR(target_st.st_mode):
            return "symlink_to_directory"
        return "symlink_other"
    return None


def scan_directory(root_path: Path) -> Dict[str, Any]:
    """Scannt root_path und gibt einen JSON-kompatiblen Payload zurück.

    Regeln:
    - Reguläre Dateien und Verzeichnisse werden vollständig gezählt.
    - Ein Datei-Symlink (symlink_to_file) zählt als reguläre Datei; er verhindert
      NICHT den vollständigen Scan (kein descendants_complete=false).
    - Ein Verzeichnis-Symlink / Junction (symlink_to_directory) wird NICHT
      rekursiv verfolgt; twin_status="not-applicable" (descendants_complete=false).
    - Kaputte/unlesbare/unklare Symlinks (symlink_broken, symlink_other) bleiben
      fail-closed: twin_status="not-applicable", sie blockieren den Scan.
    - Abfragepfad-/Vorfahren-Umleitungen (Symlinks im Pfad selbst) bleiben gesperrt:
      twin_status="not-applicable".
    - Echte Locks (LOCK.*, Hookguards) werden weiterhin ausgewertet.
    """
    root = Path(root_path).resolve()
    result: Dict[str, Any] = {
        "checked": str(root),
        "twin_status": "ok",
        "locks": [],
        "hookguards": [],
        "symlinks": [],
        "regular_files": [],
        "regular_dirs": [],
    }

    try:
        for entry in root.rglob("*"):
            rel = entry.relative_to(root)
            link_type = classify_symlink(entry)

            # Symlink im Abfragepfad selbst (Vorfahren-Umleitung) -> fail-closed
            # prüfen: ist irgendein Elternteil ein Symlink?
            try:
                parent = entry.parent
                while parent != root and parent != root.parent:
                    if classify_symlink(parent):
                        result["twin_status"] = "not-applicable"
                        result["path_redirect"] = str(parent.relative_to(root))
                        break
                    parent = parent.parent
            except Exception:
                pass

            if link_type == "symlink_to_file":
                # Datei-Symlink auf reguläre Datei: zählt als reguläre Datei,
                # blockiert NICHT den Scan. twin_status bleibt "ok" (sofern keine
                # anderen Probleme).
                result["symlinks"].append({
                    "path": str(rel),
                    "type": "symlink_to_file",
                    "target": str(entry.resolve(strict=False)),
                })
                result["regular_files"].append({
                    "path": str(rel),
                    "is_symlink": True,
                    "target": str(entry.resolve(strict=False)),
                    "size": entry.stat().st_size if entry.exists() else 0,
                })
                continue

            if link_type in ("symlink_to_directory", "symlink_broken", "symlink_other"):
                # Verzeichnis-Symlink, Junction, kaputter/unlesbarer/unklare Link:
                # fail-closed, NICHT rekursiv verfolgen, twin_status="not-applicable"
                result["symlinks"].append({
                    "path": str(rel),
                    "type": link_type,
                    "target": str(entry.resolve(strict=False)) if entry.is_symlink() else None,
                })
                result["twin_status"] = "not-applicable"
                continue

            # Kein Symlink: reguläre Datei / Verzeichnis
            if entry.is_file():
                result["regular_files"].append({
                    "path": str(rel),
                    "is_symlink": False,
                    "size": entry.stat().st_size,
                })
            elif entry.is_dir():
                result["regular_dirs"].append({
                    "path": str(rel),
                })
            # Nicht-Dateien oder andere Typen werden ignoriert
    except Exception as e:
        # Unerwarteter Fehler -> unknown
        result["twin_status"] = "unknown"
        result["error"] = str(e)

    # Entferne leere Listen für kompakte Ausgabe
    result = {k: v for k, v in result.items() if v}
    return result


def main() -> None:
    """Eingabe: Pfad des zu scannenden Verzeichnisses.
    Ausgabe: JSON auf stdout.
    Exit-Code: 0 = twin_status=ok, 1 = twin_status!=ok, 2 = fehlerhafte Argumente."""
    if len(sys.argv) < 2:
        print(json.dumps({
            "twin_status": "not-applicable",
            "locks": [],
            "hookguards": [],
            "checked": "",
            "error": "Missing directory path argument",
        }), file=sys.stderr)
        sys.exit(2)

    target = Path(sys.argv[1])
    if not target.exists():
        print(json.dumps({
            "twin_status": "not-applicable",
            "checked": str(target),
            "error": f"Path does not exist: {target}",
        }), file=sys.stderr)
        sys.exit(1)

    payload = scan_directory(target)
    print(json.dumps(payload, ensure_ascii=False))
    if payload.get("twin_status") == "ok":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()