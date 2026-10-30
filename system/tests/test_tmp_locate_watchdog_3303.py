"""TEMPORAErer Locator fuer Task #3303 (kein dauerhafter Test).

Sucht read-only:
1. git ls-files (*.sh-Vorkommen, Dateinamen mit memory_pressure/watchdog)
2. git grep nach memory_pressure_watchdog / memory_pressure_unload_guard / watchdog
3. os.walk im Repo nach Dateinamen-Mustern
Der Test endet bewusst mit Assertion, damit die Sammlung im pytest-Output sichtbar ist.
"""
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "_dev", "user", "node_modules"}
NAME_RE = re.compile(r"memory_pressure|watchdog", re.IGNORECASE)


def _git(args):
    try:
        p = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, timeout=30)
    except Exception as exc:  # pragma: no cover
        return 999, "", repr(exc)
    return p.returncode, p.stdout, p.stderr.strip()


def _walk_by_name():
    hits = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if NAME_RE.search(name):
                hits.append(os.path.relpath(os.path.join(root, name), REPO))
    return hits


def test_locate_watchdog_and_guard():
    out_lines = ["REPO=" + REPO]

    rc, out, err = _git(["ls-files"])
    all_files = out.splitlines()
    sh_files = [f for f in all_files if f.endswith(".sh")]
    name_matches = [f for f in all_files if NAME_RE.search(os.path.basename(f))]
    out_lines.append("ls-files total=%d sh=%d name-hits=%d err=%r" % (len(all_files), len(sh_files), len(name_matches), err))
    out_lines += ["  SH " + f for f in sh_files[:40]]
    out_lines += ["  NM " + f for f in name_matches[:40]]

    for pattern in ("memory_pressure_watchdog", "memory_pressure_unload_guard"):
        rc, out, err = _git(["grep", "-n", "-I", "-i", "--", pattern])
        g = out.splitlines()
        out_lines.append("git grep %s rc=%d lines=%d err=%r" % (pattern, rc, len(g), err))
        out_lines += ["  " + line for line in g[:60]]

    rc, out, err = _git(["grep", "-n", "-I", "-i", "--", "watchdog"])
    g = out.splitlines()
    out_lines.append("git grep watchdog rc=%d lines=%d err=%r" % (rc, len(g), err))
    out_lines += ["  WD " + line for line in g[:50]]

    walk = _walk_by_name()
    out_lines.append("os.walk name-hits=%d" % len(walk))
    out_lines += ["  WK " + h for h in walk[:60]]

    detail = "\n".join(out_lines)
    raise AssertionError("SAMMLER-AUSGABE Task#3303:\n" + detail[:3000])