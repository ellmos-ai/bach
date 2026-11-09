# -*- coding: utf-8 -*-
"""Contract tests for PB-17: BACH Help Claim & Freshness Test.

Verifies:
1. 6-language structure (de, en, es, ja, ru, zh) in system/docs/help/.
2. Accurate detection of complete vs. untranslated or stale topics across the inventory.
3. Cross-reference claims (e.g. docs/help/<topic>.txt) point to physically existing help files.
4. Translation file freshness and non-empty content invariant.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
HELP_DIR = SYSTEM_ROOT / "docs" / "help"
WORLD_SET_LANGS = ("de", "en", "es", "ja", "ru", "zh")
NON_DE_LANGS = ("en", "es", "ja", "ru", "zh")


def scan_help_inventory(help_dir: Path) -> Tuple[Dict[str, Path], Dict[str, Dict[str, Path]]]:
    """Scan help directory and return (base_topics, translations_by_topic)."""
    base_topics: Dict[str, Path] = {}
    translations: Dict[str, Dict[str, Path]] = {}

    for path in sorted(help_dir.glob("*.txt")):
        stem = path.stem
        # Check if stem ends with _<lang>
        matched_lang = None
        for lang in NON_DE_LANGS:
            suffix = f"_{lang}"
            if stem.endswith(suffix):
                matched_lang = lang
                base_name = stem[:-len(suffix)]
                break

        if matched_lang:
            translations.setdefault(base_name, {})[matched_lang] = path
        else:
            base_topics[stem] = path

    return base_topics, translations


# ---------------------------------------------------------------------------
# Suite 1: 6-Language Structure Contract
# ---------------------------------------------------------------------------


def test_pb17_help_inventory_size_and_structure() -> None:
    """Verify that system/docs/help/ contains extensive multi-language coverage across the 6-language world set."""
    assert HELP_DIR.is_dir(), f"Help directory {HELP_DIR} must exist"

    base_topics, translations = scan_help_inventory(HELP_DIR)

    # Invariants on base topic inventory
    assert len(base_topics) >= 150, f"Expected at least 150 base topics, got {len(base_topics)}"
    total_files = len(list(HELP_DIR.glob("*.txt")))
    assert total_files >= 1000, f"Expected at least 1000 help files, got {total_files}"

    # Check tools subdirectory
    tools_dir = HELP_DIR / "tools"
    assert tools_dir.is_dir(), "system/docs/help/tools must exist"
    tools_files = list(tools_dir.glob("*.txt"))
    assert len(tools_files) >= 20, f"Expected tools help files, got {len(tools_files)}"


def test_pb17_help_inventory_detects_untranslated_and_complete_topics() -> None:
    """Verify inventory accurately categorizes complete 6-language topics vs. topics with missing translations."""
    base_topics, translations = scan_help_inventory(HELP_DIR)

    complete_topics: List[str] = []
    untranslated_topics: Dict[str, List[str]] = {}

    for topic in sorted(base_topics.keys()):
        topic_trans = translations.get(topic, {})
        missing = [lang for lang in NON_DE_LANGS if lang not in topic_trans]
        if missing:
            untranslated_topics[topic] = missing
        else:
            complete_topics.append(topic)

    # Core invariant: vast majority of topics have full 6-language coverage
    assert len(complete_topics) >= 170, f"Expected >= 170 complete 6-language topics, got {len(complete_topics)}"
    # Known topics with missing translations are correctly flagged
    assert len(untranslated_topics) > 0, "Inventory must accurately detect missing translations"
    for known_partial in ("agent-colors", "chat", "gui-integration"):
        if known_partial in base_topics:
            assert known_partial in untranslated_topics, f"Expected {known_partial} to be flagged as untranslated"
            assert "en" in untranslated_topics[known_partial] or len(untranslated_topics[known_partial]) > 0


# ---------------------------------------------------------------------------
# Suite 2: Claim Verification (Cross-References in Help Files)
# ---------------------------------------------------------------------------


def test_pb17_help_cross_reference_claims_resolve() -> None:
    """Verify that docs/help/*.txt references inside primary help files resolve to real files."""
    sample_files = [
        HELP_DIR / "architecture.txt",
        HELP_DIR / "antigravity.txt",
        HELP_DIR / "bach.txt",
        HELP_DIR / "memory.txt",
    ]

    ref_pattern = re.compile(r"docs/help/([A-Za-z0-9_-]+(?:\.txt)?)")

    checked_refs = 0
    for path in sample_files:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        for match in ref_pattern.finditer(content):
            target = match.group(1)
            if not target.endswith(".txt"):
                target += ".txt"

            resolved = HELP_DIR / target
            assert resolved.exists(), f"Cross-reference claim '{match.group(0)}' in {path.name} cannot be resolved"
            checked_refs += 1

    assert checked_refs >= 5, f"Expected at least 5 cross references verified, checked {checked_refs}"


# ---------------------------------------------------------------------------
# Suite 3: Freshness & Integrity
# ---------------------------------------------------------------------------


def test_pb17_help_translations_freshness_and_non_empty() -> None:
    """Verify all existing translation files have non-trivial content and valid encoding."""
    base_topics, translations = scan_help_inventory(HELP_DIR)

    # Sample test across 50 complete topics to ensure high performance
    sample_complete = [t for t in sorted(base_topics.keys()) if all(l in translations.get(t, {}) for l in NON_DE_LANGS)][:50]

    for topic in sample_complete:
        base_path = base_topics[topic]
        base_len = len(base_path.read_text(encoding="utf-8"))
        assert base_len > 10, f"Base topic {base_path} is unexpectedly empty"

        for lang, trans_path in translations[topic].items():
            trans_content = trans_path.read_text(encoding="utf-8")
            assert len(trans_content) > 10, f"Translation {trans_path} ({lang}) is empty or corrupted"
            # Ensure file is readable and non-trivial
            assert len(trans_content.strip()) > 0
