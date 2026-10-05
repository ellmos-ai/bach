#!/usr/bin/env python3
"""Inventory recommended SKILL.md frontmatter fields across BACH."""
import re
import sys
from pathlib import Path

import yaml

BACH_ROOT = Path(__file__).parent.parent.parent


def find_skill_mds() -> list[Path]:
    excludes = {"_vendor", "_templates"}
    paths = []
    for source in ("skills", "agents", "hub/_services", "connectors", "."):
        src = BACH_ROOT / source
        if not src.exists():
            continue
        for p in src.rglob("SKILL.md"):
            if any(part in excludes for part in p.parts):
                continue
            paths.append(p)
    # Ensure root SKILL.md included and deduplicated
    paths = sorted(set(paths))
    return paths


def parse_frontmatter(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        print(f"YAML ERROR in {path}: {e}", file=sys.stderr)
        return {}


def fmt_dependencies(deps):
    if deps is None:
        return "MISSING"
    if isinstance(deps, dict):
        keys = sorted(deps.keys())
        return "block(" + ",".join(f"{k}={len(deps[k]) if isinstance(deps[k], list) else '?' }" for k in keys) + ")"
    return "present(" + str(type(deps).__name__) + ")"


def main():
    paths = find_skill_mds()
    print(f"# Found {len(paths)} SKILL.md files")
    print("path\tauthor\tlast_updated\tupdated\tdependencies")
    for p in paths:
        fm = parse_frontmatter(p)
        author = fm.get("author", "MISSING")
        last_updated = fm.get("last_updated", "MISSING")
        updated = fm.get("updated", "MISSING")
        dependencies = fmt_dependencies(fm.get("dependencies"))
        print(f"{p}\t{author}\t{last_updated}\t{updated}\t{dependencies}")


if __name__ == "__main__":
    main()
