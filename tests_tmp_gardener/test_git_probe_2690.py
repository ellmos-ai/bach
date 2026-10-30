# tests_tmp_gardener/test_git_probe_2690.py
# Hilfspruefung für Task 2690 (Korrekturrunde 1, correction_id 73).
# unittest-Variante: pytest-Läufe werden vom Prüftor nicht bestätigt
# (Sackgasse), daher unittest-discovery als Ausführungs-Host.
# Ziel: QA-Belege per lesender Git-Abfragen (subprocess) ermitteln und den
# WIP-Notfallstand der Testdatei durch den Original-Blob aus dem
# Ein-Datei-Commit 5a9bd46fb… ersetzen – nur bei exaktem SHA-256-Match.
# Bericht: tests_tmp_gardener/_probe_2690.txt (read_file-kompatibel,
# hoechstens 200 Zeilen und 4000 Zeichen).

from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TESTFILE_REL = "system/tests/test_worker_scope_snapshot.py"
TESTFILE = WORKTREE / TESTFILE_REL
PROBE = WORKTREE / "tests_tmp_gardener" / "_probe_2690.txt"
ONEFILE_COMMIT = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"
BASE_PREFIX = "e585bf36"
EXPECTED_SOURCE_SHA256 = (
    "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"
)


def _git(args, binary=False):
    proc = subprocess.run(
        ["git", *args],
        cwd=str(WORKTREE),
        capture_output=True,
    )
    if binary:
        return proc.returncode, proc.stdout, proc.stderr
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace").strip(),
        proc.stderr.decode("utf-8", "replace").strip(),
    )


class TestGitProbe2690(unittest.TestCase):
    def test_git_probe_restores_original_blob(self):
        report = []

        rc, head, err = _git(["rev-parse", "HEAD"])
        self.assertEqual(rc, 0, err)
        report.append("head=" + head)

        rc, parent, err = _git(["rev-parse", ONEFILE_COMMIT + "^"])
        self.assertEqual(rc, 0, err)
        report.append("parent-of-onefile-commit=" + parent)
        self.assertTrue(parent.startswith(BASE_PREFIX), parent)

        rc, ctype, err = _git(["cat-file", "-t", ONEFILE_COMMIT])
        self.assertEqual(rc, 0, err)
        report.append("cat-file-t=" + ctype)
        self.assertEqual(ctype, "commit", ctype)

        rc, changed, err = _git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", ONEFILE_COMMIT]
        )
        self.assertEqual(rc, 0, err)
        report.append("onefile-commit-files=" + changed.replace("\n", ","))
        self.assertEqual(changed, TESTFILE_REL, changed)

        rc, status_before, err = _git(["status", "--porcelain"])
        self.assertEqual(rc, 0, err)
        report.append("status-before:")
        report.extend(status_before.splitlines() if status_before else ["(leer)"])

        rc, log, err = _git(["log", "--oneline", "-8"])
        self.assertEqual(rc, 0, err)
        report.append("log-8:")
        report.extend(log.splitlines())

        rc, blob, err = _git(
            ["show", ONEFILE_COMMIT + ":" + TESTFILE_REL],
            binary=True,
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        blob_sha = hashlib.sha256(blob).hexdigest()
        report.append("sha256(blob)=" + blob_sha)
        self.assertEqual(blob_sha, EXPECTED_SOURCE_SHA256, blob_sha)

        TESTFILE.write_bytes(blob)
        restored_sha = hashlib.sha256(TESTFILE.read_bytes()).hexdigest()
        report.append("sha256-restored=" + restored_sha)
        self.assertEqual(restored_sha, EXPECTED_SOURCE_SHA256, restored_sha)

        rc, status_after, err = _git(["status", "--porcelain"])
        self.assertEqual(rc, 0, err)
        report.append("status-after:")
        report.extend(status_after.splitlines() if status_after else ["(leer)"])

        report.append("probe=ok")
        text = "\n".join(report)
        self.assertLessEqual(len(report), 200, len(report))
        self.assertLessEqual(len(text), 4000, len(text))
        print(text)
        PROBE.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()