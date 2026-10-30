# -*- coding: utf-8 -*-
"""Restore- und Bindungsprobe für Task #2690 (Korrekturrunde 1).

Nur Git-LESEkommandos (subprocess, cwd=Worktree). KEINE Git-Schreibbefehle.
KEIN Schreibzugriff auf /Users/lukas/.bach oder Produktpfade – von ~/.bach nur
read-only stat zum Beleg. Ziel: Fixture system/tests/test_worker_scope_snapshot.py
aus Commit 5a9bd46f restaurieren (SHA-geprüft), QA-Receipt nach
probe_2690_receipt.txt (append) im Task-Worktree, danach räumt sich die Probe selbst weg
(eigene pyc-Dateien + diese Datei; zusätzlich wird die obsolete Vorgängerprobe
test_git_probe_2690.py entfernt). Fehler werden gesammelt, Receipt wird
IMMER geschrieben.
"""

import hashlib
import os
import platform
import subprocess
import sys
import time
import unittest
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
FIX_REL = "system/tests/test_worker_scope_snapshot.py"
COMMIT = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"
BASE = "e585bf36bb7ff5f18e47048a8f48aa64503a1085"
SHA_SOLL = "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"
RECEIPT = WORKTREE / "probe_2690_receipt.txt"


def _git(args, text=True):
    """Git-Lesekommando im Worktree ausführen (niemals Schreibbefehle)."""
    return subprocess.run(["git", *args], cwd=str(WORKTREE),
                          capture_output=True, text=text)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


class Task2690Probe(unittest.TestCase):

    def setUp(self):
        self.failed = []
        self.lines = []
        self.log("probe " + time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z")
        self.log("platform=%s node=%s" % (platform.system(), platform.node()))
        self.log("python=%s executable=%s" % (sys.version.split()[0], sys.executable))
        self.log("env_home=%s" % os.environ.get("HOME"))
        self.log("worktree=%s" % WORKTREE)

    def log(self, msg):
        self.lines.append(str(msg))

    def check(self, label, ok, detail=""):
        self.log("check [%s] %s %s" % (label, "OK" if ok else "FAIL", detail))
        if not ok:
            self.failed.append(label)

    def _stat_home_bach(self):
        """Read-only stat von ~/.bach zum Beleg 'kein Schreibzugriff'."""
        home = Path.home()
        for rel in (".bach", ".bach/worker_repo_registry.v1.json"):
            p = home / rel
            try:
                st = p.stat()
                self.log("stat %s: size=%d mtime_ns=%d" % (rel, st.st_size, st.st_mtime_ns))
            except OSError as exc:
                self.log("stat %s: error=%r" % (rel, exc))

    def _write_receipt(self):
        try:
            with open(RECEIPT, "a", encoding="utf-8") as fh:
                fh.write("\n".join(self.lines) + "\n")
            return True
        except Exception as exc:
            sys.stderr.write("receipt error: %r\n" % (exc,))
            self.failed.append("receipt_write")
            return False

    def _cleanup(self):
        probe = Path(__file__).resolve()
        pycache = probe.parent / "__pycache__"
        try:
            if pycache.is_dir():
                for pattern in ("test_git_probe_2690*.pyc", "test_probe_2690*.pyc"):
                    for pyc in sorted(pycache.glob(pattern)):
                        pyc.unlink()
                        self.log("cleanup_removed=%s" % pyc.name)
        except Exception as exc:
            self.log("cleanup_pycache_error=%r" % (exc,))
        try:
            probe.unlink()
            self.log("cleanup_removed_probe_file")
        except Exception as exc:
            self.log("cleanup_probe_file_error=%r" % (exc,))
        try:
            old = probe.parent / "test_git_probe_2690.py"
            old.unlink()
            self.log("cleanup_removed_old_probe_file")
        except Exception as exc:
            self.log("cleanup_old_probe_file_error=%r" % (exc,))

    def test_2690_restore_and_bindung(self):
        try:
            # read-only stat von ~/.bach vor der Arbeit
            self._stat_home_bach()

            # Status vor Restaurierung (untracked separat)
            res = _git(["status", "--porcelain"])
            lines = [l for l in res.stdout.splitlines() if l.strip()]
            self.log("status_before_tracked=%r" % ([l for l in lines if not l.startswith("??")],))
            self.log("status_before_untracked=%r" % ([l for l in lines if l.startswith("??")],))

            # Check 1: kanonische Worktree-Bindung
            res = _git(["rev-parse", "--show-toplevel"])
            toplevel = res.stdout.strip()
            ok = res.returncode == 0 and Path(toplevel).resolve() == WORKTREE
            self.check("worktree_binding", ok, "toplevel=%s rc=%d" % (toplevel, res.returncode))

            # Check 2: Commit-Objekt existiert lokal
            res = _git(["cat-file", "-t", COMMIT])
            self.check("commit_exists",
                        res.returncode == 0 and res.stdout.strip() == "commit",
                        "type=%r rc=%d" % (res.stdout.strip(), res.returncode))

            # Check 3: Eltern-Commit ist BASE e585bf36...
            res = _git(["rev-parse", COMMIT + "^"])
            parent = res.stdout.strip()
            self.check("parent_is_base",
                        res.returncode == 0 and parent.startswith(BASE),
                        "parent=%s" % parent)

            # Check 4: Ein-Datei-Commit (nur die Fixture)
            res = _git(["diff-tree", "--no-commit-id", "--name-only", "-r", COMMIT])
            files = [l.strip() for l in res.stdout.splitlines() if l.strip()]
            self.check("single_file_commit",
                        res.returncode == 0 and files == [FIX_REL],
                        "files=%r" % (files,))

            # Check 5: Blob-Inhalt exakt Soll-SHA
            res = _git(["show", COMMIT + ":" + FIX_REL], text=False)
            blob = res.stdout or b""
            blob_sha = _sha256(blob)
            self.log("blob_size=%d" % len(blob))
            self.check("blob_sha256",
                        res.returncode == 0 and blob_sha == SHA_SOLL,
                        "sha=%s" % blob_sha)

            # Restore + Check 6: Disk-SHA nach write_bytes
            fix_path = WORKTREE / FIX_REL
            try:
                fix_path.write_bytes(blob)
                disk_sha = _sha256(fix_path.read_bytes())
                self.log("disk_size=%d" % fix_path.stat().st_size)
                self.check("disk_sha256_restored", disk_sha == SHA_SOLL, "sha=%s" % disk_sha)
            except Exception as exc:
                self.check("disk_sha256_restored", False, "error=%r" % (exc,))

            # Check 7: danach nur Fixture als tracked-Änderung erlaubt
            res = _git(["status", "--porcelain"])
            lines = [l for l in res.stdout.splitlines() if l.strip()]
            tracked_after = [l for l in lines if not l.startswith("??")]
            untracked_after = [l for l in lines if l.startswith("??")]
            self.log("status_after_tracked=%r" % (tracked_after,))
            self.log("status_after_untracked=%r" % (untracked_after,))
            bad = [l for l in tracked_after if l[3:].strip() != FIX_REL]
            self.check("status_tracked_only_fixture",
                        res.returncode == 0 and not bad,
                        "bad=%r" % (bad,))

            # --- nur dokumentieren ---
            res = _git(["rev-parse", "HEAD"])
            head = res.stdout.strip()
            self.log("head=%s" % head)
            self.log("head_is_commit=%s" % (head == COMMIT))
            res = _git(["branch", "--show-current"])
            self.log("branch=%r rc=%d" % (res.stdout.strip(), res.returncode))
            res = _git(["log", "--oneline", "-10"])
            self.log("log_oneline=%r" % (res.stdout.splitlines(),))
            res = _git(["log", "origin/bach-task/2690", "-5"])
            if res.returncode == 0:
                self.log("origin_log=%r" % (res.stdout.splitlines(),))
            else:
                self.log("origin_log_missing rc=%d err=%r"
                         % (res.returncode, res.stderr.strip()[:160]))
            res = _git(["diff", "--name-only", BASE, "HEAD"])
            self.log("diff_base_head=%r" % (res.stdout.splitlines(),))
            res = _git(["ls-files", "--", "*worker_git.py", "*worker_write_guard.py",
                        "*worker_scope_evidence.py", "*worker_repo_registry.py"])
            self.log("lsfiles_products=%r" % (res.stdout.splitlines(),))

            # read-only stat von ~/.bach nach der Arbeit
            self._stat_home_bach()
        except Exception as exc:
            self.failed.append("unexpected:%r" % (exc,))
            self.log("unexpected_error=%r" % (exc,))
        finally:
            self.log("checks_failed=%r" % (self.failed,))
            self._cleanup()
            self._write_receipt()
            self.assertEqual(self.failed, [])


if __name__ == "__main__":
    unittest.main()