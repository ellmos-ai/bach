# -*- coding: utf-8 -*-
"""Verifiziert den Blob 5a9bd46 und stellt die Datei wieder her."""

import hashlib
import subprocess
import unittest
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
COMMIT = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"
FIX_REL = "system/tests/test_worker_scope_snapshot.py"
SHA_SOLL = "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"


class VerifyBlob(unittest.TestCase):
    def test_verify_and_restore(self):
        # Git show the blob content
        result = subprocess.run(
            ["git", "show", f"{COMMIT}:{FIX_REL}"],
            cwd=str(WORKTREE),
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, f"git show failed: {result.stderr.decode()}")
        blob_data = result.stdout
        blob_sha = hashlib.sha256(blob_data).hexdigest()
        print(f"Blob SHA: {blob_sha}")
        print(f"Expected: {SHA_SOLL}")
        self.assertEqual(blob_sha, SHA_SOLL)

        # Write back to working tree
        fix_path = WORKTREE / FIX_REL
        fix_path.write_bytes(blob_data)
        disk_sha = hashlib.sha256(fix_path.read_bytes()).hexdigest()
        self.assertEqual(disk_sha, SHA_SOLL)
        print("Datei erfolgreich restauriert!")