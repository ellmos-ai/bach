"""Beweislauf fuer Task 2690 (laeuft in tests_tmp_gardener/, untracked).

Stellt system/tests/test_worker_scope_snapshot.py aus der Soll-Quelle
wieder her, entfernt illegitime Helper-Dateien und belegt, dass der
git-Statusausschnitt nur noch autorisierte Eintraege enthaelt.
Loescht sich am Ende selbst (finally), damit er niemals Teil eines
Commits werden kann. Alle git-Aufrufe sind read-only.
"""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
SOURCE_REV = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"
TARGET_REL = "system/tests/test_worker_scope_snapshot.py"
EXPECTED_SHA256 = "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"
AUTHORIZED = {
    "system/tests/test_worker_scope_snapshot.py",
    "tests_tmp_gardener/_probe_2690.txt",
    "tests_tmp_gardener/",
}

ILLEGAL_IN_SYSTEM_TESTS = [
    "test_git_probe_2690.py",
    "test_2690_fix_restore.py",
    "test_2690_launcher_2690.py",
    "test_2690_minimal_2690.py",
    "test_2690_probe_restore.py",
    "test_2690_receipt_evidence.py",
]


def _git(*args):
    return subprocess.run(["git", *args], cwd=WORKTREE, capture_output=True)


def test_2690_restore_and_cleanup():
    try:
        # (a) Fixture aus Soll-Quelle wiederherstellen (git show -> rohe Bytes)
        proc = _git("show", f"{SOURCE_REV}:{TARGET_REL}")
        assert proc.returncode == 0, (
            "git show failed: " + proc.stderr.decode(errors="replace"))
        data = proc.stdout
        digest = hashlib.sha256(data).hexdigest()
        assert digest == EXPECTED_SHA256, f"blob sha256 mismatch: {digest}"
        target = WORKTREE / TARGET_REL
        target.write_bytes(data)
        on_disk = hashlib.sha256(target.read_bytes()).hexdigest()
        assert on_disk == EXPECTED_SHA256, f"file sha256 mismatch: {on_disk}"
        print(f"[2690] restored {TARGET_REL}: {len(data)} bytes, sha256 ok")

        # (b) illegitime Helper entfernen (nur untracked per FS loeschen)
        for name in ILLEGAL_IN_SYSTEM_TESTS:
            rel = f"system/tests/{name}"
            path = WORKTREE / rel
            if not path.exists():
                print(f"[2690] skip (absent): {rel}")
                continue
            tracked = _git("ls-files", "--error-unmatch", rel)
            assert tracked.returncode != 0, f"{rel} is tracked; FS-delete refused"
            os.remove(path)
            assert not path.exists()
            print(f"[2690] deleted: {rel}")

        receipt = WORKTREE / "probe_2690_receipt.txt"
        if receipt.exists():
            tracked = _git("ls-files", "--error-unmatch", "probe_2690_receipt.txt")
            assert tracked.returncode != 0, "probe_2690_receipt.txt is tracked"
            os.remove(receipt)
            print("[2690] deleted: probe_2690_receipt.txt")
        else:
            print("[2690] no probe_2690_receipt.txt present")

        # illegitime Probe-Datei im autorisierten Verzeichnis (kein autorisierter Eintrag)
        stray = WORKTREE / "tests_tmp_gardener" / "test_git_probe_2690.py"
        if stray.exists():
            os.remove(stray)
            print("[2690] deleted: tests_tmp_gardener/test_git_probe_2690.py")

        # autorisierte Nebendateien MUESSEN bleiben
        for k in ("tests_tmp_gardener/_probe_2690.txt",
                  "tests_tmp_gardener/test_gardener_adapter.py"):
            assert (WORKTREE / k).exists(), f"authorized file missing: {k}"

        # (c) tests_tmp_gardener darf in der Soll-Quelle nicht existieren
        tree = _git("ls-tree", SOURCE_REV, "tests_tmp_gardener")
        assert tree.returncode == 0, (
            "ls-tree failed: " + tree.stderr.decode(errors="replace"))
        assert tree.stdout.strip() == b"", f"unexpected tree entries: {tree.stdout!r}"

        # (d) git status: nur autorisierte Eintraege
        st = _git("status", "--porcelain")
        assert st.returncode == 0, st.stderr.decode(errors="replace")
        lines = [ln for ln in st.stdout.decode().splitlines() if ln.strip()]
        print("[2690] porcelain BEFORE normalization:")
        for ln in lines:
            print(f"      {ln}")
        for ln in lines:
            code, path = ln[:2], ln[3:]
            if path == "task_result.md":
                assert code == "??", (f"task_result.md tracked with status {code!r};"
                                      " FS-only fix impossible")
                os.remove(WORKTREE / "task_result.md")
                print("[2690] removed untracked task_result.md (re-written later)")

        st2 = _git("status", "--porcelain")
        assert st2.returncode == 0, st2.stderr.decode(errors="replace")
        status_lines = [ln for ln in st2.stdout.decode().splitlines() if ln.strip()]
        paths = {ln[3:] for ln in status_lines}
        print("[2690] final porcelain:")
        for ln in status_lines:
            print(f"      {ln}")
        unexpected = paths - AUTHORIZED
        assert not unexpected, f"unexpected status paths: {unexpected}"
        assert TARGET_REL in paths, f"restored fixture invisible in status: {paths}"
        assert "?? tests_tmp_gardener/" in status_lines, "untracked dir entry missing"

        # (e) diff --check muss sauber sein
        chk = _git("diff", "--check")
        print(f"[2690] git diff --check rc={chk.returncode}")
        assert chk.returncode == 0, chk.stderr.decode(errors="replace")

        print("[2690] restore + cleanup verified")
    finally:
        # (f) Selbstloeschung + Bytecode-Aufräumen, egal wie der Lauf endet
        shutil.rmtree(WORKTREE / "tests_tmp_gardener" / "__pycache__",
                      ignore_errors=True)
        try:
            os.remove(__file__)
        except OSError:
            pass