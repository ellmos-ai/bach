# SPDX-License-Identifier: MIT
"""Einziger Weg, eine laufende SQLite-DB zu kopieren (Backup, Restore, API).

Dateikopie (shutil.copy2) verliert Zeilen aus dem WAL; die SQLite-Backup-API
nicht. Jede Kopie wird per integrity_check geprueft (T-20261122-100577457).
ponytail: integrity_check liest die ganze DB (~Sekunden pro 100 MB),
quick_check waere schneller, wenn das je stoert.
"""
import sqlite3
from pathlib import Path


def verify_db(path) -> None:
    """Wirft RuntimeError, wenn path keine intakte SQLite-DB ist (read-only)."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as e:
        raise RuntimeError(f"DB nicht lesbar: {e}") from e
    finally:
        conn.close()
    if result != "ok":
        raise RuntimeError(f"DB defekt: integrity_check={result}")


def snapshot_db(src, dst) -> Path:
    """Konsistente, gepruefte Kopie von src nach dst. Bei Fehler wird dst entfernt."""
    src, dst = Path(src), Path(dst)
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    except Exception:
        d.close()
        s.close()
        dst.unlink(missing_ok=True)
        raise
    d.close()
    s.close()
    try:
        verify_db(dst)
    except Exception:
        dst.unlink(missing_ok=True)
        raise
    return dst
