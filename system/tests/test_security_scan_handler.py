# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests fuer den Security-Scan Handler (hub/security.py)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Stelle sicher, dass hub/ und core/ importierbar sind
BACH_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACH_ROOT))
sys.path.insert(0, str(BACH_ROOT / "system"))

from hub.security import SecurityHandler
from core.capabilities import capability_manager


BASE_SYSTEM = BACH_ROOT / "system"


@pytest.fixture
def handler(tmp_path: Path) -> SecurityHandler:
    return SecurityHandler(BASE_SYSTEM)


def test_security_handler_operations(handler: SecurityHandler) -> None:
    ops = handler.get_operations()
    assert "scan" in ops
    assert "status" in ops
    assert "report" in ops


def test_security_scan_dry_run(handler: SecurityHandler) -> None:
    ok, output = handler.handle("scan", ["--dry-run"], dry_run=True)
    assert ok is True
    assert "tools" in output
    assert "skills" in output
    assert "hub" in output


def test_security_scan_single_path_json(handler: SecurityHandler, tmp_path: Path) -> None:
    # Erstelle einen sauberen Test-Ordner
    test_dir = tmp_path / "clean_pkg"
    test_dir.mkdir()
    (test_dir / "__init__.py").write_text("# nothing\n", encoding="utf-8")

    ok, output = handler.handle("scan", [str(test_dir), "--json"], dry_run=False)
    assert ok is True
    report = json.loads(output)
    assert report["summary"]["critical"] == 0
    assert report["summary"]["warning"] == 0
    assert report["summary"]["info"] == 0


def test_security_scan_finds_critical_pattern(handler: SecurityHandler, tmp_path: Path) -> None:
    test_dir = tmp_path / "bad_pkg"
    test_dir.mkdir()
    (test_dir / "danger.py").write_text("import os\nos.system('rm -rf /')\n", encoding="utf-8")

    ok, output = handler.handle("scan", [str(test_dir), "--json"], dry_run=False)
    assert ok is True
    report = json.loads(output)
    assert report["summary"]["critical"] >= 1
    findings = report["findings_by_file"]
    assert any("os.system" in str(f) for file_findings in findings.values() for f in file_findings)


def test_security_scan_ignores_pyqt_exec_false_positive(handler: SecurityHandler, tmp_path: Path) -> None:
    test_dir = tmp_path / "qt_pkg"
    test_dir.mkdir()
    (test_dir / "app.py").write_text("import sys\nfrom PyQt6.QtWidgets import QApplication\napp = QApplication([])\nsys.exit(app.exec())\n", encoding="utf-8")

    ok, output = handler.handle("scan", [str(test_dir), "--json"], dry_run=False)
    assert ok is True
    report = json.loads(output)
    assert report["summary"]["critical"] == 0


def test_security_scan_excludes_archive(handler: SecurityHandler, tmp_path: Path) -> None:
    test_dir = tmp_path / "pkg_with_archive"
    test_dir.mkdir()
    archive = test_dir / "_archive"
    archive.mkdir()
    (archive / "old.py").write_text("import os\nos.system('evil')\n", encoding="utf-8")
    (test_dir / "current.py").write_text("print('hello')\n", encoding="utf-8")

    ok, output = handler.handle("scan", [str(test_dir), "--json"], dry_run=False)
    assert ok is True
    report = json.loads(output)
    assert report["summary"]["critical"] == 0
    # Der gepruefte Pfad darf das Archiv-Verzeichnis nicht als Teil enthalten
    assert "/_archive/" not in output


def test_security_status_without_report(handler: SecurityHandler, tmp_path: Path) -> None:
    h = SecurityHandler(tmp_path)
    ok, output = h.handle("status", [], dry_run=False)
    assert ok is True
    assert "Noch kein Sicherheits-Report" in output


def test_capabilities_detailed_masking() -> None:
    content = '''
# os.system("evil")  # kommentar
x = "os.system('also evil')"
import os
os.system("real")
'''
    masked = capability_manager._mask_content(content, mask_comments=True, mask_strings=True)
    assert "evil" not in masked
    assert "also evil" not in masked
    assert "os.system" in masked
    assert "import os" in masked
