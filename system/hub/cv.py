# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
CV Handler - Lebenslauf-Verwaltung
==================================

--cv generate           Lebenslauf generieren (ASCII)
--cv generate --output  In Datei speichern
--cv generate --scan    Ordner automatisch scannen
--cv status             Status der Datenbasis anzeigen
"""
import sys
from pathlib import Path
from .base import BaseHandler


class CVHandler(BaseHandler):
    """Handler fuer --cv Operationen (Lebenslauf-Generierung)"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        self.expert_dir = base_path / "skills" / "_experts" / "bewerbungsexperte"

    @property
    def profile_name(self) -> str:
        return "cv"

    @property
    def target_file(self) -> Path:
        return self.expert_dir

    def get_operations(self) -> dict:
        return {
            "generate": "Lebenslauf generieren (--output DATEI, --scan)",
            "status": "Status der Datenbasis anzeigen",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "generate":
            return self._generate(args, dry_run)
        elif operation == "status":
            return self._status()
        else:
            return self._status()

    def _get_generator(self):
        """Importiert CVGenerator bei Bedarf."""
        gen_path = self.expert_dir / "cv_generator.py"
        if not gen_path.exists():
            return None, f"cv_generator.py nicht gefunden: {gen_path}"

        if str(self.expert_dir) not in sys.path:
            sys.path.insert(0, str(self.expert_dir))
        try:
            from cv_generator import CVGenerator
            return CVGenerator(str(self.db_path)), None
        except ImportError as e:
            return None, f"Import-Fehler: {e}"

    def _generate(self, args: list, dry_run: bool) -> tuple:
        """Lebenslauf generieren."""
        gen, err = self._get_generator()
        if not gen:
            return False, f"[FEHLER] {err}"

        if dry_run:
            return True, "[DRY-RUN] Wuerde Lebenslauf generieren"

        # Daten sammeln
        gen.collect_personal_data()
        gen.collect_contacts("beruflich")

        # Ordner scannen wenn --scan
        if "--scan" in args:
            self._scan_folders(gen)

        # CV generieren
        cv_text = gen.generate_ascii_cv()
        if not cv_text or not cv_text.strip():
            return False, "[FEHLER] Lebenslauf konnte nicht generiert werden (keine Daten?)"

        # Output-Datei
        output = self._get_arg(args, "--output") or self._get_arg(args, "-o")
        if output:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(cv_text, encoding="utf-8")
            lines = cv_text.count('\n')
            return True, f"[OK] Lebenslauf gespeichert: {output}\n     {len(cv_text)} Zeichen, {lines} Zeilen"

        return True, cv_text

    def _scan_folders(self, gen):
        """Scannt registrierte Ordner fuer Karrieredaten."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
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

    def _status(self) -> tuple:
        """Zeigt Status der CV-Datenbasis."""
        import sqlite3
        lines = ["=== Lebenslauf-Datenbasis ===\n"]

        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

            try:
                profile = conn.execute(
                    "SELECT COUNT(*) as cnt FROM assistant_user_profile"
                ).fetchone()
                lines.append(f"Persoenliche Daten: {profile['cnt']} Eintraege")
            except Exception:
                lines.append("Persoenliche Daten: Tabelle nicht vorhanden")

            try:
                contacts = conn.execute(
                    "SELECT COUNT(*) as cnt FROM contacts WHERE is_active=1 AND category='beruflich'"
                ).fetchone()
                lines.append(f"Berufliche Referenzen: {contacts['cnt']}")
            except Exception:
                lines.append("Berufliche Referenzen: Tabelle nicht vorhanden")

            try:
                folders = conn.execute(
                    "SELECT folder_type, folder_path FROM user_data_folders"
                ).fetchall()
                lines.append(f"Registrierte Ordner: {len(folders)}")
                for f in folders:
                    exists = Path(f["folder_path"]).exists()
                    marker = "OK" if exists else "FEHLT"
                    lines.append(f"  [{marker}] {f['folder_type']}: {f['folder_path']}")
            except Exception:
                lines.append("Registrierte Ordner: Tabelle nicht vorhanden")
        except Exception as e:
            lines.append(f"DB-Fehler: {e}")
        finally:
            if conn:
                conn.close()

        lines.append(f"\nGenerator: {self.expert_dir / 'cv_generator.py'}")
        lines.append(f"Vorhanden: {'Ja' if (self.expert_dir / 'cv_generator.py').exists() else 'Nein'}")

        return True, "\n".join(lines)

    @staticmethod
    def _get_arg(args: list, flag: str) -> str:
        """Extrahiert Wert eines --flag aus args."""
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(f"{flag}="):
                return a.split("=", 1)[1]
        return ""
