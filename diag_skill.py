#!/usr/bin/env python3
"""Temporary diagnostic script for SKILL*.md structure alignment."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
FILES = {
    "de": ROOT / "SKILL.md",
    "ja": ROOT / "SKILL_JA.md",
    "ru": ROOT / "SKILL_RU.md",
    "zh": ROOT / "SKILL_ZH.md",
}


def read_sections(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections = []
    for i, line in enumerate(lines, 1):
        if line.startswith("## ") or line.startswith("### "):
            sections.append((i, line))
    return sections


def find_workflows_path_line(path: Path):
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if "system/skills/workflows/" in line:
            return i, line
    return None, None


def count_codeblocks(path: Path):
    text = path.read_text(encoding="utf-8")
    return len(re.findall(r"^```\w*$", text, flags=re.MULTILINE))


def main():
    ok = True
    de_sections = read_sections(FILES["de"])
    print(f"SKILL.md: {len(de_sections)} header lines")

    for lang, path in FILES.items():
        sections = read_sections(path)
        workflows_line, workflows_text = find_workflows_path_line(path)
        cb_count = count_codeblocks(path)
        print(f"\n{path.name}: {len(sections)} header lines, workflows path at {workflows_line}, codeblocks={cb_count}")

        # Find the H2 following workflows path
        h2_after = None
        if workflows_line:
            for ln, hdr in sections:
                if ln > workflows_line and hdr.startswith("## "):
                    h2_after = (ln, hdr)
                    break
        print(f"  H2 after workflows path: {h2_after}")

        # Check separator exists between workflows path and H2
        if workflows_line and h2_after:
            lines = path.read_text(encoding="utf-8").splitlines()
            between = lines[workflows_line:h2_after[0] - 1]
            has_sep = "---" in between
            print(f"  has '---' separator before H2: {has_sep}")
            if not has_sep:
                ok = False
                print(f"  ERROR: missing --- separator before H2 in {path.name}")

        if lang != "de":
            if cb_count != count_codeblocks(FILES["de"]):
                ok = False
                print(f"  ERROR: codeblock count mismatch with SKILL.md")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
