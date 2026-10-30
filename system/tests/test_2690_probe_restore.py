# -*- coding: utf-8 -*-
"""Probe: Blob 5a9bd46 aus Git-Objektdatenbank abrufen (nur Lesezugriff)."""

import hashlib
import json
import unittest
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
COMMIT = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"
FIX_REL = "system/tests/test_worker_scope_snapshot.py"
SHA_SOLL = "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"


class ProbeRestore(unittest.TestCase):
    def test_blob_lookup(self):
        try:
            import git
            repo = git.Repo(str(WORKTREE))
        except Exception as exc:
            self.fail("GitPython nicht verfügbar: %r" % exc)
        try:
            commit = repo.commit(COMMIT)
            blob = commit.tree[FIX_REL]
            data = blob.data_stream.read()
        except Exception as exc:
            self.fail("Blob-Abruf fehlgeschlagen: %r" % exc)
        sha = hashlib.sha256(data).hexdigest()
        print("BLOB_SIZE:", len(data))
        print("BLOB_SHA:", sha)
        print("MATCH:", sha == SHA_SOLL)
        self.assertEqual(sha, SHA_SOLL)
