# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit test for standalone inbox module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import inbox


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "inbox"
    assert data["selfcontained"] is True


def test_inbox_scanner_and_filtering(tmp_path):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()

    # Create safe candidates
    (inbox_dir / "document1.pdf").write_bytes(b"%PDF-test")
    (inbox_dir / "notes.txt").write_text("Hello inbox", encoding="utf-8")

    # Create ignored files
    (inbox_dir / ".hidden_file").write_text("secret", encoding="utf-8")
    (inbox_dir / "temp_file.tmp").write_text("tmp", encoding="utf-8")
    (inbox_dir / "LOCK.user.active").write_text("locked", encoding="utf-8")

    scanner = inbox.InboxScanner(inbox_dir)
    res = scanner.scan(dry_run=True)
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert res["candidates_count"] == 2
    assert res["ignored_count"] == 3

    names = [c["name"] for c in res["candidates"]]
    assert "document1.pdf" in names
    assert "notes.txt" in names


def test_intake_file_lifecycle(tmp_path):
    inbox_dir = tmp_path / "inbox"
    proc_dir = tmp_path / "processed"
    inbox_dir.mkdir()

    test_file = inbox_dir / "report.docx"
    test_file.write_bytes(b"PK-docx")

    scanner = inbox.InboxScanner(inbox_dir)
    intake_res = scanner.intake_file("report.docx", proc_dir)
    assert intake_res["ok"] is True
    assert not test_file.exists()
    assert (proc_dir / "report.docx").exists()
