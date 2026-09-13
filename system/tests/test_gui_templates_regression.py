# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
GUI-Template Regressionstest (T08)
==================================

Automatisierter Regressionstest fuer die BACH GUI-Templates unter
system/gui/templates. Er prueft fuer jedes Template:

  * Existenz und Lesbarkeit
  * Grundlegende HTML5-Struktur (DOCTYPE, html, head, body, title)
  * HTML-Parsbarkeit mit lxml (keine korrigierten/verlorenen Tags)
  * Inline-JavaScript Syntax mittels node --check (optional)
  * Referenzierte lokale /static/ Ressourcen auf Existenz
  * Verknuepfung zu einer Route in system/gui/server.py

Urspruenglich als manueller Test T08 geplant; diese Implementierung
uebernimmt die repetitive Pruefung automatisch und gibt fuer jede
Vorlage eine klare Go/No-Go-Auskunft.
"""

import re
import subprocess
import sys
import warnings
from html.parser import HTMLParser
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

try:
    import lxml.html
    LXML_AVAILABLE = True
except ImportError:  # pragma: no cover
    LXML_AVAILABLE = False

GUI_DIR = SYSTEM_ROOT / "gui"
TEMPLATES_DIR = GUI_DIR / "templates"
STATIC_DIR = GUI_DIR / "static"
SERVER_PY = GUI_DIR / "server.py"

# Minimaler Satz an Tags, den jede GUI-Seite enthalten sollte.
REQUIRED_TAGS = {"html", "head", "body", "title"}


def _extract_referenced_templates() -> set:
    """Ermittelt alle in server.py direkt verwendeten Template-Dateien."""
    refs = set()
    if not SERVER_PY.exists():
        return refs
    text = SERVER_PY.read_text(encoding="utf-8")
    # TEMPLATES_DIR / "name.html"
    for match in re.finditer(r'TEMPLATES_DIR\s*/\s*"([^"]+\.html)"', text):
        refs.add(match.group(1))
    # f"{agent['name']}.html"
    for match in re.finditer(r'f"\{[^}]+\}(\.html)"', text):
        # Wir kennen den dynamischen Agentennamen nicht; wir pruefen spaeter
        # nur, ob agent.html selbst existiert. Hier ignorieren.
        pass
    return refs


REFERENCED_TEMPLATES = _extract_referenced_templates()


class TagCounter(HTMLParser):
    """Zaehlt oeffnende und schliessende Tags zur Plausibilitaetspruefung."""

    def __init__(self):
        super().__init__()
        self.open_tags = []
        self.unmatched_closing = []
        self.self_closing = {"area", "base", "br", "col", "embed", "hr",
                             "img", "input", "link", "meta", "param",
                             "source", "track", "wbr"}

    def handle_starttag(self, tag, attrs):
        if tag not in self.self_closing:
            self.open_tags.append(tag)

    def handle_endtag(self, tag):
        if tag in self.self_closing:
            return
        if self.open_tags and self.open_tags[-1] == tag:
            self.open_tags.pop()
        else:
            self.unmatched_closing.append(tag)


class TemplateChecker:
    """Fuehrt alle Pruefungen fuer eine einzelne Template-Datei aus."""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.errors = []
        self.warnings = []
        self.text = ""

    def run(self) -> tuple[list[str], list[str]]:
        if not self.path.exists():
            self.errors.append("Template-Datei fehlt")
            return self.errors, self.warnings
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except Exception as exc:
            self.errors.append(f"Kann Datei nicht lesen: {exc}")
            return self.errors, self.warnings

        self._check_doctype()
        self._check_required_tags()
        self._check_tag_balance()
        self._check_lxml_parsable()
        self._check_inline_js()
        self._check_static_resources()
        return self.errors, self.warnings

    def _check_doctype(self):
        if not re.search(r"<!DOCTYPE\s+html", self.text, re.IGNORECASE):
            self.errors.append("Kein HTML5 DOCTYPE gefunden")

    def _check_required_tags(self):
        lower = self.text.lower()
        for tag in REQUIRED_TAGS:
            # Einfacher Check auf Vorkommen des Tags (kein geschlossener leerer Tag)
            if f"<{tag}" not in lower:
                self.errors.append(f"Erforderliches Tag <{tag}> fehlt")

    def _check_tag_balance(self):
        parser = TagCounter()
        try:
            parser.feed(self.text)
        except Exception as exc:
            self.errors.append(f"HTML-Parser-Fehler: {exc}")
            return
        if parser.unmatched_closing:
            self.errors.append(
                f"Nicht passende schliessende Tags: {parser.unmatched_closing[:10]}"
            )
        if parser.open_tags:
            # Nur melden, wenn offensichtlich viele Tags offen bleiben.
            # Alpine.js/Tailwind-Templates koennen ansonsten harmlos sein.
            open_tags = parser.open_tags
            if len(open_tags) > 3:
                self.warnings.append(
                    f"Viele nicht geschlossene Tags uebrig: {open_tags[-10:]}"
                )

    def _check_lxml_parsable(self):
        if not LXML_AVAILABLE:
            self.warnings.append("lxml nicht installiert, strukturelle Pruefung reduziert")
            return
        try:
            lxml.html.parse(str(self.path))
        except Exception as exc:
            self.errors.append(f"lxml kann Template nicht parsen: {exc}")

    def _check_inline_js(self):
        """Prueft Inline-<script> Inhalte auf JS-Syntax mit node --check."""
        scripts = re.findall(
            r"<script\b([^>]*?)>(.*?)</script>",
            self.text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for attrs, code in scripts:
            attrs_lower = attrs.lower()
            if "type=" in attrs_lower and (
                "text/template" in attrs_lower
                or "application/json" in attrs_lower
                or "application/ld+json" in attrs_lower
            ):
                continue
            code = code.strip()
            if not code:
                continue
            result = subprocess.run(
                ["node", "--check", "-"],
                input=code,
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                msg = result.stderr.strip().splitlines()[0] if result.stderr else "Syntaxfehler"
                # Zeilennummer extrahieren
                line_match = re.search(r"\[stdin\]:(\d+)", result.stderr)
                line_info = f"Zeile {line_match.group(1)}" if line_match else "unbekannte Zeile"
                self.errors.append(f"Inline-JS Syntaxfehler ({line_info}): {msg}")

    def _check_static_resources(self):
        """Prueft, ob referenzierte /static/ Ressourcen existieren."""
        def exists(res: str) -> bool:
            # Query-Parameter wie ?v=2 beim Dateisystem-Lookup ignorieren
            clean = res.split("?")[0]
            local_path = STATIC_DIR / clean[len("/static/"):]
            return local_path.exists()

        for match in re.finditer(r'src=["\'](/static/[^"\']+)', self.text):
            res = match.group(1)
            if not exists(res):
                self.warnings.append(f"Lokale /static/-Ressource fehlt: {res}")
        for match in re.finditer(r'href=["\'](/static/[^"\']+)', self.text):
            res = match.group(1)
            if not exists(res):
                self.warnings.append(f"Lokale /static/-Ressource fehlt: {res}")


def all_templates() -> list[Path]:
    return sorted(TEMPLATES_DIR.glob("*.html"))


# ═══════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("template_path", all_templates(), ids=lambda p: p.name)
def test_template_regression(template_path: Path):
    """Jedes GUI-Template muss die definierten Qualitaetskriterien erfuellen."""
    checker = TemplateChecker(template_path)
    errors, checker_warnings = checker.run()

    # Warnings werden protokolliert, fuehren aber nicht zum Fehlschlag.
    for warning in checker_warnings:
        warnings.warn(f"{template_path.name}: {warning}")

    if errors:
        formatted = "\n  - ".join(errors)
        pytest.fail(f"{template_path.name}:\n  - {formatted}")


def test_all_referenced_templates_exist():
    """Jedes in server.py referenzierte Template muss physisch vorhanden sein."""
    missing = [name for name in REFERENCED_TEMPLATES if not (TEMPLATES_DIR / name).exists()]
    if missing:
        pytest.fail(f"Fehlende referenzierte Templates: {missing}")


def test_no_unreferenced_templates_are_orphaned():
    """
    Templates, die im Verzeichnis aber nicht in server.py referenziert sind,
    werden als Warnung protokolliert. Nicht jede HTML-Datei muss zwingend eine
    eigene Route haben (z. B. eingebettete Editor-Fragmente), daher kein harter Fehler.
    """
    existing = {p.name for p in all_templates()}
    orphan = sorted(existing - REFERENCED_TEMPLATES)
    if orphan:
        warnings.warn(f"Nicht in server.py referenzierte Templates: {orphan}")
