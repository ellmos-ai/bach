"""Probe: Blob 5a9bd46fb3269f66e8804e33689ade1f2a9523ea aus .git/objects dekodieren.

Einmaliger Diagnose-Helfer fuer Task 3292. Wird nicht committet.
"""
import hashlib
import os
import zlib

SHA = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"


def _git_common_dir(worktree_root):
    dotgit = os.path.join(worktree_root, ".git")
    if os.path.isdir(dotgit):
        return dotgit
    with open(dotgit, "r", encoding="utf-8") as fh:
        line = fh.read().strip()
    gitdir = line.split("gitdir:", 1)[1].strip()
    common = os.path.join(gitdir, "commondir")
    if os.path.exists(common):
        with open(common, "r", encoding="utf-8") as fh:
            rel = fh.read().strip()
        return os.path.normpath(os.path.join(gitdir, rel))
    return gitdir


def _read_object(common_dir, sha):
    path = os.path.join(common_dir, "objects", sha[:2], sha[2:])
    with open(path, "rb") as fh:
        raw = fh.read()
    data = zlib.decompress(raw)
    header, _, body = data.partition(b"\x00")
    kind, _, size = header.partition(b" ")
    return path, raw, kind.decode(), int(size), body


def test_probe():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    common = _git_common_dir(root)
    print("COMMON_DIR:", common)
    path, raw, kind, size, body = _read_object(common, SHA)
    print("OBJECT_PATH:", path)
    print("KIND:", kind, "SIZE:", size, "BODY_LEN:", len(body))
    print("SHA1_RECOMPUTED:", hashlib.sha1(
        ("%s %d" % (kind, size)).encode() + b"\x00" + body).hexdigest())
    print("SHA256:", hashlib.sha256(body).hexdigest())
    text = body.decode("utf-8", "replace")
    lines = text.splitlines()
    print("LINE_COUNT:", len(lines))
    print("--- HEAD 20 ---")
    for i, ln in enumerate(lines[:20], 1):
        print("%4d| %s" % (i, ln))
    print("--- TAIL 10 ---")
    for i, ln in enumerate(lines[-10:], len(lines) - len(lines[-10:]) + 1):
        print("%4d| %s" % (i, ln))
    assert kind == "blob"
    assert len(body) == size
