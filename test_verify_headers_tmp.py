"""Temporary pytest verification for SKILL*.md topic-package header."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES = {
    "de": ROOT / "SKILL.md",
    "ja": ROOT / "SKILL_JA.md",
    "ru": ROOT / "SKILL_RU.md",
    "zh": ROOT / "SKILL_ZH.md",
}


def find_workflows_path_line(path: Path):
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if "system/skills/workflows/" in line:
            return i, line
    return None, None


def find_next_h2(path: Path, after_line: int):
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if i > after_line and line.startswith("## "):
            return i, line
    return None, None


def has_separator_before(path: Path, target_line: int, after_line: int):
    lines = path.read_text(encoding="utf-8").splitlines()
    return any(line.strip() == "---" for line in lines[after_line:target_line - 1])


def test_topic_package_header_structure():
    for lang, path in FILES.items():
        wf_line, wf_text = find_workflows_path_line(path)
        assert wf_line is not None, f"{path.name}: workflows path line not found"

        h2_line, h2_text = find_next_h2(path, wf_line)
        assert h2_line is not None, f"{path.name}: no H2 after workflows path"
        assert h2_text.startswith("## "), f"{path.name}: expected H2, got {h2_text!r}"

        assert has_separator_before(path, h2_line, wf_line), (
            f"{path.name}: missing --- separator before H2 at {h2_line}"
        )
