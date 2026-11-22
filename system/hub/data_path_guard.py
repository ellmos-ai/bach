# -*- coding: utf-8 -*-
"""hub/data_path_guard.py — keeps runtime data out of commits and pushes.

Anlass SEC-bach-rescue-tag-2026-11-22: a pre-deploy snapshot committed the Mac
live tree with ``git add -A``; subscription list, chat dump, user decisions and
mail rules ended up in a public tag. ``.gitignore`` is the first line, this
guard is the second: worker staging (``hub/worker_git.py``) and CI
(``.github/workflows/data-path-guard.yml``) both refuse these paths, so a
missing ignore entry or a foreign agent cannot push them again.

Stdlib only, so CI can run it without installing BACH:
    python system/hub/data_path_guard.py --base origin/main   # PR diff
    python system/hub/data_path_guard.py --staged             # index
Exit 0 = clean, 1 = data paths found, 2 = git could not be read (fail closed).
"""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Iterable

# Same idea as SNAPSHOT_DENY in system/bin/harvest-local-commits.sh, extended by
# the 14 path patterns from the leak finding.
DATA_PATH_PATTERNS = tuple(re.compile(p) for p in (
    r"\.(db|sqlite3?)(-wal|-shm|-journal)?$",            # databases
    r"^data/",                                             # top-level runtime data
    r"(^|/)data/temp/",                                    # temp dumps and scratch
    r"(^|/)data/.*\.csv$",                                 # csv exports under data
    r"^system/data/[^/]*export",                           # system/data/*export*
    r"^system/data/inbox_",                                # mail rules, folder lists
    r"(^|/)inbox_config[^/]*\.json$",
    r"^system/data/[^/]*\.pre-",                           # config backups (*.json.pre-*)
    # message/db dumps; only data endings (or none), so json_dump.py stays code
    r"(^|/)[^/]*dump[^/]*\.(json|jsonl|sql|txt|csv|tsv|db|log|xml|ya?ml|gz|zip|tar)$",
    r"(^|/)[^/.]*dump[^/.]*$",
    r"\.dump$",                                            # pg_dump, core.dump, heap.dump
    r"(^|/)TO-DECIDE-USER",                                # user decisions
    r"(^|/)exports/",                                      # exports/**, system/exports/**
    r"(^|/)\.pytest_tmp/",
    r"(^|/)staging/(.+/)?backup/",
    r"\.bak([._\-0-9]|$)",                                 # *.bak, *.bak.*, *.bak-*
    r"^system/scripts/[^/]*(_output|out[0-9]*)\.txt$",     # ad-hoc query output
    r"[:\\]",                                              # Windows path used as file name
))

# Tracked on main on purpose (release translations, placeholders).
ALLOWED_PATHS = tuple(re.compile(p) for p in (
    r"^system/exports/translations/",
    r"(^|/)\.gitkeep$",
))


def is_data_path(path: str) -> bool:
    path = str(path)
    if any(p.search(path) for p in ALLOWED_PATHS):
        return False
    return any(p.search(path) for p in DATA_PATH_PATTERNS)


def data_paths(paths: Iterable[str]) -> list[str]:
    """Return the given repo-relative paths that must never be committed."""
    return sorted({p for p in paths if p and is_data_path(p)})


def _git_paths(argv: list[str], cwd: str | None = None) -> list[str]:
    res = subprocess.run(["git", *argv, "-z"], cwd=cwd, capture_output=True, check=False, timeout=60)
    if res.returncode != 0:
        raise RuntimeError("git diff failed")
    out = res.stdout or b""
    if isinstance(out, str):
        out = out.encode("utf-8", errors="surrogateescape")
    return [item.decode("utf-8", errors="surrogateescape") for item in out.split(b"\x00") if item]


def staged_data_paths(cwd: str | None = None) -> list[str]:
    """Data paths added/changed in the index (deletions are allowed: they remove leaks)."""
    return data_paths(_git_paths(["diff", "--cached", "--name-only", "--no-renames", "--diff-filter=ACMRT"], cwd))


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="check paths added/changed in BASE...HEAD")
    group.add_argument("--staged", action="store_true", help="check the index")
    args = parser.parse_args(argv)
    try:
        if args.staged:
            found = staged_data_paths()
        else:
            found = data_paths(_git_paths(["diff", "--name-only", "--no-renames", "--diff-filter=ACMRT",
                                           f"{args.base}...HEAD"]))
    except Exception as exc:
        print(f"data-path-guard: git konnte nicht gelesen werden: {exc}", file=sys.stderr)
        return 2
    if found:
        print("data-path-guard: Datenpfade im Diff, Commit/Push verweigert:", file=sys.stderr)
        for path in found:
            print(f"  {path}", file=sys.stderr)
        return 1
    print("data-path-guard: keine Datenpfade im Diff")
    return 0


if __name__ == "__main__":
    sys.exit(main())
