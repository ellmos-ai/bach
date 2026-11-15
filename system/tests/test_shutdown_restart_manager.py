"""Tests fuer system.githubbot_ocean.shutdown_restart_manager.

Neu angelegt im Rahmen von Task #2061 (Tickets #4056/#4057): deckt das
Lock-Handling (_acquire_lock/_release_lock), das JSONL-Resultlog
(record_result), die Stubs (run_secrets_scan), check_git_diff sowie
shutdown()/restart() inkl. Idempotenz und Fehlerweg ab. Lock-Datei und
Resultlog werden pro Test in ein temporaeres Verzeichnis umgeleitet.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from system.githubbot_ocean import shutdown_restart_manager as srm


class _IsolatedPathsTest(unittest.TestCase):
    """Basis: Lock- und Resultlog-Pfad in temporaeres Verzeichnis umleiten."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original_lock = srm._LOCK_FILE
        original_log = srm._RESULT_LOG_PATH
        self.addCleanup(setattr, srm, "_LOCK_FILE", original_lock)
        self.addCleanup(setattr, srm, "_RESULT_LOG_PATH", original_log)
        srm._LOCK_FILE = Path(tmp.name) / ".shutdown_restart.lock"
        srm._RESULT_LOG_PATH = Path(tmp.name) / "shutdown_results.jsonl"

    def read_log_entries(self):
        if not srm._RESULT_LOG_PATH.exists():
            return []
        with open(srm._RESULT_LOG_PATH, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


class LockTest(_IsolatedPathsTest):
    def test_acquire_lock_schreibt_eigene_pid(self):
        self.assertTrue(srm._acquire_lock())
        self.assertTrue(srm._LOCK_FILE.exists())
        self.assertEqual(
            srm._LOCK_FILE.read_text(encoding="utf-8").strip(), str(os.getpid())
        )

    def test_acquire_lock_blokiert_bei_laufendem_vorgang(self):
        srm._LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        self.assertFalse(srm._acquire_lock())

    def test_acquire_lock_beseitigt_veralteten_lock(self):
        srm._LOCK_FILE.write_text("keine-zahl", encoding="utf-8")
        self.assertTrue(srm._acquire_lock())
        self.assertEqual(
            srm._LOCK_FILE.read_text(encoding="utf-8").strip(), str(os.getpid())
        )

    def test_release_lock_entfernt_datei_idempotent(self):
        self.assertTrue(srm._acquire_lock())
        srm._release_lock()
        self.assertFalse(srm._LOCK_FILE.exists())
        srm._release_lock()  # idempotent, kein Fehler


class LogAndStubTest(_IsolatedPathsTest):
    def test_record_result_schreibt_jsonl_zeilen(self):
        srm.record_result("shutdown", "started", {"reason": "test"})
        srm.record_result("restart", "completed")
        entries = self.read_log_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["operation"], "shutdown")
        self.assertEqual(entries[0]["status"], "started")
        self.assertEqual(entries[0]["details"], {"reason": "test"})
        self.assertTrue(entries[0]["timestamp"].endswith("Z"))
        self.assertEqual(entries[1]["operation"], "restart")
        self.assertEqual(entries[1]["details"], {})

    def test_run_secrets_scan_stub_liefert_true(self):
        self.assertTrue(srm.run_secrets_scan())

    def test_check_git_diff_ok(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(args=[], returncode=0)
            self.assertTrue(srm.check_git_diff())
        self.assertEqual(mock_run.call_args.args[0], ["git", "diff", "--check"])

    def test_check_git_diff_scheitert_bei_git_fehler(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = CalledProcessError(1, "git", stderr=b"x")
            self.assertFalse(srm.check_git_diff())


class ShutdownTest(_IsolatedPathsTest):
    def test_shutdown_ok_schreibt_started_und_completed(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(args=[], returncode=0)
            self.assertTrue(srm.shutdown("wartung"))
        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["echo", "SHUTDOWN: wartung"], commands)
        entries = self.read_log_entries()
        self.assertEqual(
            [entry["status"] for entry in entries], ["started", "completed"]
        )
        self.assertEqual(entries[0]["details"], {"reason": "wartung", "force": False})
        self.assertFalse(srm._LOCK_FILE.exists())

    def test_shutdown_ist_idempotent_bei_offenem_lock(self):
        srm._LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            self.assertFalse(srm.shutdown("test"))
        mock_run.assert_not_called()
        self.assertEqual(self.read_log_entries(), [])

    def test_shutdown_fehler_wird_als_failed_geloggt(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = CalledProcessError(1, "echo", stderr=b"x")
            self.assertFalse(srm.shutdown("fehler"))
        entries = self.read_log_entries()
        self.assertEqual(
            [entry["status"] for entry in entries], ["started", "failed"]
        )
        self.assertIn("error", entries[1]["details"])
        self.assertFalse(srm._LOCK_FILE.exists())


class RestartTest(_IsolatedPathsTest):
    def test_restart_ok_schreibt_started_und_completed(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(args=[], returncode=0)
            self.assertTrue(srm.restart("update"))
        entries = self.read_log_entries()
        self.assertEqual(
            [entry["operation"] for entry in entries], ["restart", "restart"]
        )
        self.assertEqual(
            [entry["status"] for entry in entries], ["started", "completed"]
        )
        self.assertEqual(mock_run.call_args_list[0].args[0][0], "echo")
        self.assertFalse(srm._LOCK_FILE.exists())

    def test_restart_ist_idempotent_bei_offenem_lock(self):
        srm._LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        self.assertFalse(srm.restart())
        self.assertEqual(self.read_log_entries(), [])


if __name__ == "__main__":
    unittest.main()
