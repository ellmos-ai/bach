#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Tool: cv_generator
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version cv_generator

Description:
    [Beschreibung hinzufügen]

Usage:
    python cv_generator.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
CV Generator - ASCII-Lebenslauf aus BACH-Daten generieren
==========================================================

Generiert einen strukturierten Lebenslauf aus:
  - assistant_user_profile (Persoenliche Daten)
  - contacts (Referenzen, category='beruflich')
  - user_data_folders (Arbeitgeber-Ordner scannen)
  - Ordnerstruktur-Analyse (Zeugnisse, Fortbildungen)

Systemisch: Funktioniert fuer jeden BACH-User.

Usage:
  python tools/cv_generator.py
  python tools/cv_generator.py --output user/bewerbung/lebenslauf.txt
  python tools/cv_generator.py --scan-folders

Ref: docs/WICHTIG_SYSTEMISCH_FIRST.md
"""

import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import re


class CVGenerator:
    """Generiert ASCII-Lebenslauf aus BACH-Daten und Ordnerstruktur."""

    def __init__(self, user_db_path: str):
        self.user_db_path = user_db_path
        self.sections = {}

    def _get_db(self):
        conn = sqlite3.connect(self.user_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Daten sammeln
    # ------------------------------------------------------------------

    def collect_personal_data(self) -> Dict:
        """Persoenliche Daten aus assistant_user_profile."""
        conn = self._get_db()
        try:
            rows = conn.execute(
                "SELECT key, value FROM assistant_user_profile"
            ).fetchall()
            data = {r["key"]: r["value"] for r in rows}
            self.sections["personal"] = data
            return data
        except Exception:
            self.sections["personal"] = {}
            return {}
        finally:
            conn.close()

    def collect_contacts(self, category: str = "beruflich") -> List[Dict]:
        """Berufliche Kontakte als potenzielle Referenzen."""
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT name, organization, position, phone, email
                FROM contacts
                WHERE is_active = 1 AND category = ?
                ORDER BY name
            """, (category,)).fetchall()
            contacts = [dict(r) for r in rows]
            self.sections["references"] = contacts
            return contacts
        except Exception:
            self.sections["references"] = []
            return []
        finally:
            conn.close()

    def scan_career_folders(self, base_path: str) -> List[Dict]:
        """
        Scannt Arbeitgeber-Ordner und extrahiert Karriere-Stationen.

        Erwartet Ordnerstruktur:
          _Arbeitgeber/
            Firma_A/
              Vertrag.pdf
              Zeugnis.pdf
            Firma_B/
              ...
        """
        career = []
        base = Path(base_path)

        if not base.exists():
            self.sections["career"] = []
            return []

        for folder in sorted(base.iterdir()):
            if not folder.is_dir():
                continue
            if folder.name.startswith("."):
                continue

            entry = {
                "name": folder.name,
                "path": str(folder),
                "documents": [],
            }

            # Unterordner und Dateien zaehlen
            for f in folder.rglob("*"):
                if f.is_file() and not f.name.startswith(".") and f.name != "desktop.ini":
                    entry["documents"].append({
                        "name": f.name,
                        "ext": f.suffix.lower(),
                        "size": f.stat().st_size,
                    })

            # Versuche Zeitraum aus Ordnernamen zu extrahieren
            years = re.findall(r"20\d{2}|19\d{2}", folder.name)
            if years:
                entry["years"] = years

            career.append(entry)

        self.sections["career"] = career
        return career

    def scan_education_folders(self, base_path: str) -> List[Dict]:
        """Scannt Zeugnisse/Abschluesse-Ordner."""
        education = []
        base = Path(base_path)

        if not base.exists():
            self.sections["education"] = []
            return []

        for folder in sorted(base.iterdir()):
            if not folder.is_dir():
                continue
            if folder.name.startswith("."):
                continue

            entry = {
                "name": folder.name,
                "documents": [
                    f.name for f in folder.rglob("*")
                    if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".jpg")
                    and f.name != "desktop.ini"
                ],
            }
            education.append(entry)

        self.sections["education"] = education
        return education

    def scan_certifications(self, base_path: str) -> List[str]:
        """Scannt Fortbildungen-Ordner."""
        certs = []
        base = Path(base_path)

        if not base.exists():
            self.sections["certifications"] = []
            return []

        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".pdf", ".docx"):
                if f.name != "desktop.ini":
                    # Bereinige Dateinamen
                    name = f.stem.replace("_", " ").replace("-", " ")
                    name = re.sub(r"\d{8}_\d{4}", "", name).strip()
                    certs.append(name)

        self.sections["certifications"] = certs
        return certs

    # ------------------------------------------------------------------
    # CV generieren
    # ------------------------------------------------------------------

    def generate_ascii_cv(self) -> str:
        """Generiert ASCII-formatierten Lebenslauf."""
        lines = []
        width = 60

        # Header
        lines.append("=" * width)
        lines.append("L E B E N S L A U F".center(width))
        lines.append("=" * width)
        lines.append("")

        # Persoenliche Daten
        personal = self.sections.get("personal", {})
        if personal:
            lines.append("PERSOENLICHE DATEN")
            lines.append("-" * width)
            field_map = {
                "name": "Name",
                "full_name": "Name",
                "email": "E-Mail",
                "phone": "Telefon",
                "address": "Adresse",
                "birthday": "Geburtsdatum",
                "birth_date": "Geburtsdatum",
                "nationality": "Staatsangehoerigkeit",
                "marital_status": "Familienstand",
            }
            for key, label in field_map.items():
                if key in personal and personal[key]:
                    lines.append(f"  {label:<25} {personal[key]}")
            lines.append("")

        # Berufserfahrung
        career = self.sections.get("career", [])
        if career:
            lines.append("BERUFSERFAHRUNG")
            lines.append("-" * width)
            for entry in career:
                name = entry["name"].lstrip("_")
                doc_count = len(entry.get("documents", []))
                years_str = ""
                if entry.get("years"):
                    years_str = f" ({', '.join(entry['years'])})"

                lines.append(f"  {name}{years_str}")
                if doc_count > 0:
                    lines.append(f"    Dokumente: {doc_count}")

                # Zeige wichtige Dokumente
                docs = entry.get("documents", [])
                important = [
                    d for d in docs
                    if any(kw in d["name"].lower()
                           for kw in ["zeugnis", "vertrag", "arbeits", "bescheinigung"])
                ]
                for d in important[:3]:
                    lines.append(f"    -> {d['name']}")

                lines.append("")

        # Ausbildung
        education = self.sections.get("education", [])
        if education:
            lines.append("AUSBILDUNG / ABSCHLUESSE")
            lines.append("-" * width)
            for entry in education:
                name = entry["name"].lstrip("0123456789 ")
                lines.append(f"  {name}")
                for doc in entry.get("documents", [])[:5]:
                    doc_clean = doc.replace(".pdf", "").replace(".docx", "")
                    lines.append(f"    - {doc_clean}")
            lines.append("")

        # Fortbildungen
        certs = self.sections.get("certifications", [])
        if certs:
            lines.append("FORTBILDUNGEN / ZERTIFIKATE")
            lines.append("-" * width)
            for cert in certs[:15]:
                lines.append(f"  - {cert}")
            if len(certs) > 15:
                lines.append(f"  ... und {len(certs) - 15} weitere")
            lines.append("")

        # Referenzen
        refs = self.sections.get("references", [])
        if refs:
            lines.append("REFERENZEN")
            lines.append("-" * width)
            for ref in refs[:5]:
                company = f" ({ref['company']})" if ref.get("company") else ""
                pos = f", {ref['position']}" if ref.get("position") else ""
                contact = ref.get("email") or ref.get("phone") or ""
                lines.append(f"  {ref['name']}{pos}{company}")
                if contact:
                    lines.append(f"    {contact}")
            lines.append("")

        # Footer
        lines.append("-" * width)
        lines.append(f"Stand: {datetime.now().strftime('%d.%m.%Y')}")
        lines.append(f"Generiert mit BACH Personal Assistant")
        lines.append("")

        return "\n".join(lines)


def format_cv_report(cv_text: str, sections: Dict) -> str:
    """Gibt CV mit Metadaten-Report aus."""
    lines = [
        "[CV-GENERATOR] Lebenslauf generiert",
        f"  Sektionen:    {len(sections)}",
    ]

    for name, data in sections.items():
        if isinstance(data, list):
            lines.append(f"    {name}: {len(data)} Eintraege")
        elif isinstance(data, dict):
            lines.append(f"    {name}: {len(data)} Felder")

    lines.append("")
    lines.append(cv_text)
    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    import argparse
    parser = argparse.ArgumentParser(description="BACH CV Generator")
    parser.add_argument("--output", "-o", help="Output-Datei")
    parser.add_argument("--career-path", help="Pfad zum Arbeitgeber-Ordner")
    parser.add_argument("--education-path", help="Pfad zum Abschluesse-Ordner")
    parser.add_argument("--certs-path", help="Pfad zum Fortbildungen-Ordner")
    parser.add_argument("--scan-folders", action="store_true",
                        help="Automatisch bekannte Ordner scannen")
    args = parser.parse_args()

    # Pfad zur DB: agents/_experts/bewerbungsexperte -> system/
    base_path = Path(__file__).parent.parent.parent.parent
    db_path = str(base_path / "data" / "bach.db")  # Unified DB seit v1.1.84

    gen = CVGenerator(db_path)

    # Persoenliche Daten immer laden
    gen.collect_personal_data()
    gen.collect_contacts("beruflich")

    # Ordner scannen
    if args.scan_folders:
        # Aus user_data_folders oder Standard-Pfade
        conn = gen._get_db()
        try:
            folders = conn.execute(
                "SELECT folder_path, folder_type FROM user_data_folders"
            ).fetchall()

            for f in folders:
                fp = f["folder_path"]
                ft = f["folder_type"]
                if "arbeitgeber" in ft.lower() or "career" in ft.lower():
                    gen.scan_career_folders(fp)
                elif "zeugnis" in ft.lower() or "education" in ft.lower():
                    gen.scan_education_folders(fp)
                elif "fortbildung" in ft.lower() or "cert" in ft.lower():
                    gen.scan_certifications(fp)
        except Exception:
            pass
        finally:
            conn.close()

    if args.career_path:
        gen.scan_career_folders(args.career_path)

    if args.education_path:
        gen.scan_education_folders(args.education_path)

    if args.certs_path:
        gen.scan_certifications(args.certs_path)

    # CV generieren
    cv_text = gen.generate_ascii_cv()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(cv_text)
        print(f"[OK] Lebenslauf gespeichert: {args.output}")
        print(f"     {len(cv_text)} Zeichen, {cv_text.count(chr(10))} Zeilen")
    else:
        print(format_cv_report(cv_text, gen.sections))
