"""Parity-Checks zwischen SKILL.md und den Sprachfassungen.

Zwei Stufen, weil die Sprachfassungen unterschiedlich vollstaendig sind:

* STRICT_TARGETS  -- Vollfassungen. Codebloecke und Heading-Ebenen muessen
  exakt identisch mit SKILL.md sein (Code wird nicht uebersetzt).
* SOFT_TARGETS    -- Kurz- bzw. Teilfassungen (JA/ZH ~346 Zeilen, RU mit
  reduziertem Datei-Inventar). Hier ist exakte Gleichheit technisch nicht
  erreichbar; geprueft werden Frontmatter-Gleichstand, nicht-leerer Inhalt
  und dass keine Dateinamen erfunden wurden.

Zusaetzlich gilt fuer ALLE Sprachfassungen: jeder dort genannte *.md-Dateiname
muss auch in SKILL.md vorkommen (keine uebersetzten Fantasienamen).
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "SKILL.md"

STRICT_TARGETS = ["SKILL_EN.md", "SKILL_ES.md"]
SOFT_TARGETS = ["SKILL_JA.md", "SKILL_RU.md", "SKILL_ZH.md"]
ALL_TARGETS = STRICT_TARGETS + SOFT_TARGETS

CODE_BLOCK = re.compile(r"```[^\n]*\n.*?```", re.S)
HEADING_PREFIX = re.compile(r"^(#{1,6}) ", re.M)
DOC_NAME = re.compile(r"[A-ZÄÖÜ][A-ZÄÖÜ0-9_-]{3,}\.md")
VERSION = re.compile(r"^version:\s*(\S+)\s*$", re.M)
UPDATED = re.compile(r"^updated:\s*(\S+)\s*$", re.M)


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def meta(text):
    """version/updated aus dem YAML-Kopf ziehen (nur die ersten Zeilen)."""
    head = "\n".join(text.splitlines()[:20])
    version = VERSION.search(head)
    updated = UPDATED.search(head)
    return (
        version.group(1) if version else None,
        updated.group(1) if updated else None,
    )


class ParityTest(unittest.TestCase):
    def test_strict_parity(self):
        source = read(SOURCE)
        source_code_blocks = CODE_BLOCK.findall(source)
        source_heading_prefixes = HEADING_PREFIX.findall(source)
        for target in STRICT_TARGETS:
            with self.subTest(target=target):
                text = read(target)
                self.assertEqual(source_code_blocks, CODE_BLOCK.findall(text))
                self.assertEqual(
                    source_heading_prefixes, HEADING_PREFIX.findall(text)
                )

    def test_soft_parity(self):
        source = read(SOURCE)
        source_version, source_updated = meta(source)
        self.assertIsNotNone(source_version, "SKILL.md ohne version-Feld")
        for target in SOFT_TARGETS:
            with self.subTest(target=target):
                text = read(target)
                self.assertGreater(
                    len(text.strip()), 1000, f"{target} ist (fast) leer"
                )
                self.assertEqual(
                    (source_version, source_updated),
                    meta(text),
                    f"{target} hat abweichenden Frontmatter-Stand",
                )

    def test_doc_names_not_invented(self):
        """Keine uebersetzten/erfundenen Dateinamen in den Sprachfassungen."""
        source_names = set(DOC_NAME.findall(read(SOURCE)))
        for target in ALL_TARGETS:
            with self.subTest(target=target):
                names = set(DOC_NAME.findall(read(target)))
                self.assertTrue(names, f"{target} nennt keine Dokumentnamen")
                self.assertEqual(
                    set(), names - source_names,
                    f"{target} nennt unbekannte Dokumentnamen",
                )


if __name__ == "__main__":
    unittest.main()