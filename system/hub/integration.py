# SPDX-License-Identifier: MIT
"""
Integration Handler - LLM-Partner-Brücke
=========================================

bach integration status          Zeige Integration-Status
bach integration push-claude     Push BACH-Block zu CLAUDE.md
bach integration push-gemini     Push BACH-Block zu GEMINI.md
bach integration push-ollama     Push BACH-Block zu OLLAMA.md
bach integration pull-claude     Pull manueller Content aus CLAUDE.md
bach integration config          Zeige/Ändere Integration-Konfiguration

Teil von SQ038: Claude Code Integration & LLM-Partner-Brücke
Referenz: BACH_Dev/BACH_Memory_Architektur_Konzept.md
"""
from pathlib import Path
from .base import BaseHandler
import sqlite3


class IntegrationHandler(BaseHandler):
    """Handler für LLM-Partner-Integration (SQ038)"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "integration"

    @property
    def target_file(self) -> Path:
        return self.base_path / "tools" / "claude_md_sync.py"

    def get_operations(self) -> dict:
        return {
            "status": "Zeige Integration-Status",
            "push-claude": "Push BACH-Block zu CLAUDE.md (Stufe 2 Managed)",
            "push-gemini": "Push BACH-Block zu GEMINI.md (Stufe 2 Managed)",
            "push-ollama": "Push BACH-Block zu OLLAMA.md (Stufe 2 Managed)",
            "pull-claude": "Pull manuellen Content aus CLAUDE.md (noch nicht implementiert)",
            "config": "Zeige/Ändere Integration-Konfiguration",
            "set": "Setze Integration-Level: bach integration set <partner> <level>"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "status" or operation is None or operation == "":
            return self._status()
        elif operation == "push-claude":
            return self._push_partner("CLAUDE")
        elif operation == "push-gemini":
            return self._push_partner("GEMINI")
        elif operation == "push-ollama":
            return self._push_partner("OLLAMA")
        elif operation == "pull-claude":
            return False, "Pull-Claude noch nicht implementiert (Stufe 3)"
        elif operation == "config":
            return self._config()
        elif operation == "set":
            if len(args) < 2:
                return False, "Usage: bach integration set <partner> <level>\n  Level: off|sync|managed|full"
            return self._set_level(args[0], args[1])
        else:
            return False, f"Unbekannte Operation: {operation}\n\nVerfügbar: {', '.join(self.get_operations().keys())}"

    def _status(self) -> tuple:
        """Zeige Integration-Status."""
        try:
            # Hole Config aus DB
            conn = sqlite3.connect(str(self._canonical_db))
            cur = conn.cursor()

            # Prüfe ob integration-Config existiert
            cur.execute("""
                SELECT key, value FROM system_config
                WHERE key LIKE 'integration.%'
                ORDER BY key
            """)
            config_items = cur.fetchall()

            conn.close()

            # Output
            results = ["INTEGRATION STATUS", "=" * 60, ""]

            if config_items:
                results.append("KONFIGURATION")
                results.append("-" * 40)
                for key, value in config_items:
                    results.append(f"  {key:<40} {value}")
                results.append("")
            else:
                results.append("Keine Integration konfiguriert (Standard: Off)")
                results.append("")

            # CLAUDE.md Status
            claude_md = self.base_path.parent / "CLAUDE.md"
            results.append("CLAUDE.md")
            results.append("-" * 40)
            if claude_md.exists():
                size = claude_md.stat().st_size
                results.append(f"  Existiert: Ja ({size} Bytes)")

                # Prüfe ob BACH-Marker vorhanden
                content = claude_md.read_text(encoding="utf-8")
                has_marker = "<!-- BACH:START" in content and "<!-- BACH:END" in content
                results.append(f"  BACH-Block: {'Ja' if has_marker else 'Nein'}")
            else:
                results.append("  Existiert: Nein")
                results.append("  → Nutze 'bach integration push-claude' zum Erstellen")

            results.append("")
            results.append("STUFEN-MODELL (SQ038)")
            results.append("-" * 40)
            results.append("  Stufe 0 (Off):     Kein BACH-Eingriff")
            results.append("  Stufe 1 (Sync):    MEMORY.md aus DB (siehe SQ065)")
            results.append("  Stufe 2 (Managed): CLAUDE.md BACH-Block (← aktuell verfügbar)")
            results.append("  Stufe 3 (Full):    Hooks + Kontext-Injektion (geplant)")
            results.append("")
            results.append("Kommandos:")
            results.append("  bach integration push-claude    → BACH-Block aktualisieren")
            results.append("  bach integration set claude-code managed → Stufe 2 aktivieren")

            return True, "\n".join(results)

        except Exception as e:
            return False, f"Fehler bei Status-Abfrage: {e}"

    def _push_partner(self, partner_name: str) -> tuple:
        """Push BACH-Block zu Partner.md (generisch)."""
        try:
            import sys
            from pathlib import Path

            # Füge tools/ zum Python-Path hinzu (falls nicht bereits vorhanden)
            tools_path = str(self.base_path / "tools")
            if tools_path not in sys.path:
                sys.path.insert(0, tools_path)

            from claude_md_sync import ClaudeMdSync

            syncer = ClaudeMdSync(self.base_path.parent, partner_name=partner_name)
            success, msg = syncer.push()

            if success:
                return True, f"✓ {partner_name}.md aktualisiert\n  {msg}"
            else:
                return False, f"✗ Fehler: {msg}"

        except Exception as e:
            return False, f"Fehler bei {partner_name}-Push: {e}"

    def _config(self) -> tuple:
        """Zeige/Ändere Integration-Konfiguration."""
        try:
            conn = sqlite3.connect(str(self._canonical_db))
            cur = conn.cursor()

            cur.execute("""
                SELECT key, value, description FROM system_config
                WHERE key LIKE 'integration.%'
                ORDER BY key
            """)
            items = cur.fetchall()

            conn.close()

            if not items:
                return True, "Keine Integration-Config vorhanden.\n\nErstelle mit: bach integration set <partner> <level>"

            results = ["INTEGRATION CONFIG", "=" * 60, ""]
            for key, value, description in items:
                results.append(f"{key}")
                results.append(f"  Wert: {value}")
                if description:
                    results.append(f"  Info: {description}")
                results.append("")

            results.append("Ändern mit: bach integration set <partner> <level>")

            return True, "\n".join(results)

        except Exception as e:
            return False, f"Fehler bei Config-Abfrage: {e}"

    def _set_level(self, partner: str, level: str) -> tuple:
        """Setze Integration-Level."""
        valid_levels = ["off", "sync", "managed", "full"]
        if level not in valid_levels:
            return False, f"Ungültiges Level: {level}\n\nGültig: {', '.join(valid_levels)}"

        try:
            conn = sqlite3.connect(str(self._canonical_db))
            cur = conn.cursor()

            # Key erstellen
            key = f"integration.{partner}.level"

            # Prüfe ob bereits vorhanden
            cur.execute("SELECT value FROM system_config WHERE key=?", (key,))
            existing = cur.fetchone()

            if existing:
                # Update
                cur.execute("UPDATE system_config SET value=? WHERE key=?", (level, key))
                action = "aktualisiert"
            else:
                # Insert
                cur.execute(
                    "INSERT INTO system_config (key, value, category) VALUES (?, ?, 'integration')",
                    (key, level)
                )
                action = "gesetzt"

            conn.commit()
            conn.close()

            msg = f"✓ Integration-Level {action}: {partner} → {level}"
            if level == "managed":
                msg += "\n\n→ Nutze 'bach integration push-claude' zum Aktualisieren"

            return True, msg

        except Exception as e:
            return False, f"Fehler beim Setzen: {e}"
