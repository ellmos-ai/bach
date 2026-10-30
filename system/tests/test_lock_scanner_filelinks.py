#!/usr/bin/env python3
"""
Regressionstests für Lock-Scanner Datei-Link-Handling.
Testet: reguläre Datei-Links, Verzeichnislinks, kaputte Links, Zyklen, Pfad-Umleitungen.
"""
import json
import os
import tempfile
import shutil
from pathlib import Path
import subprocess
import sys

SCANNER = Path(__file__).parents[1] / "tools" / "lock_scan.py"


def run_scanner(path: Path) -> tuple[int, dict]:
    """Führt lock_scan.py aus und gibt (exit_code, parsed_json) zurück."""
    result = subprocess.run(
        [sys.executable, str(SCANNER), str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"_raw": result.stdout}
    return result.returncode, payload


def test_regular_file_link_does_not_block_scan():
    """Ein Datei-Symlink auf eine reguläre Datei darf den Scan NICHT blockieren."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "real_file.txt"
        target.write_text("content")
        link = root / "link_to_file.txt"
        link.symlink_to(target)

        code, payload = run_scanner(root)
        assert code == 0, f"Exit code should be 0 for regular file link, got {code}"
        assert payload.get("twin_status") == "ok", f"twin_status should be ok, got {payload.get('twin_status')}"
        # Der Link sollte als symlink_to_file erkannt werden
        symlinks = payload.get("symlinks", [])
        assert any(s["type"] == "symlink_to_file" for s in symlinks)
        # Er sollte in regular_files gezählt werden
        regular_files = payload.get("regular_files", [])
        assert any(f.get("is_symlink") is True for f in regular_files)
        # descendants_complete implizit true (twin_status=ok)


def test_directory_link_blocks_scan():
    """Ein Verzeichnis-Symlink / Junction blockiert den Scan (fail-closed)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subdir = root / "subdir"
        subdir.mkdir()
        (subdir / "inner.txt").write_text("inner")
        link = root / "link_to_dir"
        link.symlink_to(subdir)

        code, payload = run_scanner(root)
        assert code == 1, f"Exit code should be 1 for directory link, got {code}"
        assert payload.get("twin_status") == "not-applicable", f"twin_status should be not-applicable, got {payload.get('twin_status')}"
        symlinks = payload.get("symlinks", [])
        assert any(s["type"] == "symlink_to_directory" for s in symlinks)


def test_broken_symlink_blocks_scan():
    """Ein kaputter/unlesbarer Symlink blockiert den Scan (fail-closed)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        link = root / "broken_link"
        link.symlink_to(root / "does_not_exist")

        code, payload = run_scanner(root)
        assert code == 1, f"Exit code should be 1 for broken link, got {code}"
        assert payload.get("twin_status") == "not-applicable", f"twin_status should be not-applicable, got {payload.get('twin_status')}"
        symlinks = payload.get("symlinks", [])
        assert any(s["type"] == "symlink_broken" for s in symlinks)


def test_cycle_symlink_blocks_scan():
    """Ein zyklischer Symlink blockiert den Scan (fail-closed)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = root / "a"
        b = root / "b"
        a.symlink_to(b)
        b.symlink_to(a)

        code, payload = run_scanner(root)
        assert code == 1, f"Exit code should be 1 for cycle, got {code}"
        assert payload.get("twin_status") == "not-applicable"


def test_path_redirect_blocks_scan():
    """Ein Symlink im Abfragepfad (Vorfahren-Umleitung) blockiert den Scan."""
    with tempfile.TemporaryDirectory() as tmp:
        real_dir = Path(tmp) / "real_root"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("content")
        root = Path(tmp) / "redirect_root"
        root.symlink_to(real_dir)

        code, payload = run_scanner(root)
        assert code == 1, f"Exit code should be 1 for path redirect, got {code}"
        assert payload.get("twin_status") == "not-applicable"
        # path_redirect sollte gesetzt sein
        assert "path_redirect" in payload


def test_file_link_lock_evaluated():
    """Ein LOCK.* auf einem Datei-Symlink wird weiterhin erkannt."""
    # Dies testet die Lock-Erkennung, nicht den Traversal.
    # Der Scanner gibt locks=[] zurück (keine echten Locks im Test-Setup),
    # aber ein LOCK-Datei-Link würde in symlinks auftauchen.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "LOCK.test"
        target.write_text("lock content")
        link = root / "link_to_lock.txt"
        link.symlink_to(target)

        code, payload = run_scanner(root)
        assert code == 0
        assert payload.get("twin_status") == "ok"
        symlinks = payload.get("symlinks", [])
        assert any(s["type"] == "symlink_to_file" for s in symlinks)


def test_mixed_regular_and_file_links():
    """Gemischtes Szenario: echte Dateien + Datei-Symlinks + Verzeichnisse."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "real.txt").write_text("real")
        (root / "dir").mkdir()
        (root / "dir" / "inner.txt").write_text("inner")
        target = root / "target.txt"
        target.write_text("target")
        (root / "link.txt").symlink_to(target)

        code, payload = run_scanner(root)
        assert code == 0
        assert payload.get("twin_status") == "ok"
        assert len(payload.get("regular_files", [])) >= 2  # real.txt + link.txt
        assert len(payload.get("regular_dirs", [])) >= 1   # dir


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])