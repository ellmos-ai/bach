"""Paritaetspruefung: SKILL-Uebersetzungen muessen strukturell zur DE-Quelle passen.

Geprueft wird je Sprache:
* gleiche Abfolge der Ueberschriften-Ebenen (Abschnittsstruktur),
* identische Codebloecke (Befehle, Pfade, Bezeichner bleiben unuebersetzt),
* identischer YAML-Kopf-Schluesselsatz.

Die Ueberschriftentexte selbst duerfen uebersetzt sein, ihre Ebenenfolge nicht.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "SKILL.md"

TRANSLATIONS = {
    "en": ROOT / "SKILL_EN.md",
    "es": ROOT / "SKILL_ES.md",
    "ja": ROOT / "SKILL_JA.md",
    "ru": ROOT / "SKILL_RU.md",
    "zh": ROOT / "SKILL_ZH.md",
}

FENCE_RE = re.compile(r"^\s*```")
HEADING_RE = re.compile(r"^(#{1,6})\s")


def parse_structure(text: str) -> dict:
    """Liefert Ueberschriften-Ebenen, Codebloecke und YAML-Kopfzeilen."""
    levels: list[int] = []
    heading_lines: list[tuple[int, str]] = []
    code_blocks: list[str] = []
    in_code = False
    block: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            if in_code:
                block.append(line)
                code_blocks.append("\n".join(block))
                block = []
                in_code = False
            else:
                in_code = True
                block = [line]
            continue
        if in_code:
            block.append(line)
            continue
        match = HEADING_RE.match(line)
        if match:
            levels.append(len(match.group(1)))
            heading_lines.append((number, line.rstrip()))
    if in_code:  # unbalancierter Zaun: als Block sichern, damit der Test meckert
        block.append("```")
        code_blocks.append("\n".join(block))
    return {
        "levels": levels,
        "headings": heading_lines,
        "code_blocks": code_blocks,
        "yaml": _yaml_keys(text),
    }


def _yaml_keys(text: str) -> list[str]:
    if not text.startswith("---"):
        return []
    keys = []
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        if match:
            keys.append(match.group(1))
    return keys


def _levels_as_text(levels: list[int]) -> list[str]:
    counts: dict[int, int] = {}
    out = []
    for level in levels:
        counts[level] = counts.get(level, 0) + 1
        out.append(f"H{level} #{counts[level]}")
    return out


def _report(name: str, source: dict, target: dict) -> str:
    parts = [f"--- {name}: SKILL.md vs {name} ---"]
    if source["levels"] != target["levels"]:
        diff = difflib.unified_diff(
            _levels_as_text(source["levels"]),
            _levels_as_text(target["levels"]),
            fromfile="SKILL.md",
            tofile=name,
            lineterm="",
        )
        parts.append("Ueberschriften-Ebenen weichen ab:\n" + "\n".join(diff))
        parts.append(
            f"Quelle: {len(source['levels'])} Ueberschriften, "
            f"Ziel: {len(target['levels'])}"
        )
    if source["code_blocks"] != target["code_blocks"]:
        diff = difflib.unified_diff(
            source["code_blocks"],
            target["code_blocks"],
            fromfile="SKILL.md-code",
            tofile=f"{name}-code",
            lineterm="",
            n=2,
        )
        parts.append("Codebloecke weichen ab:\n" + "\n".join(diff))
    if source["yaml"] != target["yaml"]:
        parts.append(
            f"YAML-Kopf weicht ab: Quelle {source['yaml']} / Ziel {target['yaml']}"
        )
    return "\n".join(parts)


def test_source_has_structure():
    """Die DE-Quelle muss ueberhaupt Ueberschriften und Codebloecke liefern."""
    structure = parse_structure(SOURCE.read_text(encoding="utf-8"))
    assert structure["levels"], "SKILL.md enthaelt keine Ueberschriften"
    assert structure["code_blocks"], "SKILL.md enthaelt keine Codebloecke"


@pytest.mark.parametrize("language", sorted(TRANSLATIONS))
def test_translation_matches_source(language: str):
    path = TRANSLATIONS[language]
    if not path.exists():
        if language != "en":
            pytest.skip(f"{path.name} noch nicht angelegt")
        pytest.fail(f"{path.name} fehlt")
    source = parse_structure(SOURCE.read_text(encoding="utf-8"))
    target = parse_structure(path.read_text(encoding="utf-8"))
    message = _report(path.name, source, target)
    assert source["levels"] == target["levels"], message
    assert source["code_blocks"] == target["code_blocks"], message
    assert source["yaml"] == target["yaml"], message


def test_diagnose_en(capsys=None):
    """Diagnoseausgabe: Strukturdifferenz DE/EN im Klartext."""
    source = parse_structure(SOURCE.read_text(encoding="utf-8"))
    target = parse_structure(TRANSLATIONS["en"].read_text(encoding="utf-8"))
    print(_report("SKILL_EN.md", source, target))
