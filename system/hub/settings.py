# SPDX-License-Identifier: MIT
"""
Settings Handler - Systemeinstellungen verwalten
=================================================

bach settings list              Alle Einstellungen anzeigen
bach settings list --category X Einstellungen einer Kategorie
bach settings get <key>         Einzelnen Wert lesen
bach settings set key=value     Wert setzen
bach settings reset <key>       Wert auf Default zuruecksetzen
bach settings export            Settings als JSON exportieren

Referenz: SQ037, ENT-17
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("ellmos-core")
class SettingsHandler(BaseHandler):
    """Handler fuer bach settings Operationen."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        from .bach_paths import BACH_DB
        self.db_path = BACH_DB

    @property
    def profile_name(self) -> str:
        return "settings"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Einstellungen anzeigen [--category=CAT]",
            "get": "Setting lesen: get <key>",
            "set": "Setting setzen: set <key>=<value> [--category=CAT] [--desc=TEXT]",
            "reset": "Setting loeschen: reset <key>",
            "export": "Settings als JSON exportieren",
            "import": "Settings aus JSON importieren: import <datei>",
            "categories": "Alle Kategorien auflisten",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list":
            return self._list(args)
        elif operation == "get" and args:
            return self._get(args[0])
        elif operation == "set" and args:
            return self._set(args, dry_run)
        elif operation == "reset" and args:
            return self._reset(args[0], dry_run)
        elif operation == "export":
            return self._export(args)
        elif operation == "import" and args:
            return self._import_settings(args[0], dry_run)
        elif operation == "categories":
            return self._categories()
        else:
            ops = self.get_operations()
            lines = ["SETTINGS - Systemeinstellungen", "=" * 50, ""]
            for op, desc in ops.items():
                lines.append(f"  bach settings {op:12s} {desc}")
            return True, "\n".join(lines)

    def _get_conn(self):
        """DB-Verbindung oeffnen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _list(self, args: list) -> tuple:
        """Alle Einstellungen auflisten."""
        category = None
        for arg in args:
            if arg.startswith("--category="):
                category = arg.split("=", 1)[1]

        conn = self._get_conn()

        if category:
            rows = conn.execute(
                "SELECT key, value, type, category, description, dist_type "
                "FROM system_config WHERE category = ? ORDER BY key",
                (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, value, type, category, description, dist_type "
                "FROM system_config ORDER BY category, key"
            ).fetchall()

        conn.close()

        if not rows:
            return True, "Keine Einstellungen gefunden."

        lines = ["SYSTEM-EINSTELLUNGEN", "=" * 70, ""]

        current_cat = None
        for row in rows:
            cat = row['category'] or '(ohne Kategorie)'
            if cat != current_cat:
                current_cat = cat
                lines.append(f"  [{cat}]")

            dt_label = {0: 'USER', 1: 'TMPL', 2: 'CORE'}.get(row['dist_type'], '?')
            value = row['value'] or ''
            if len(value) > 40:
                value = value[:37] + '...'
            desc = row['description'] or ''
            if len(desc) > 30:
                desc = desc[:27] + '...'

            lines.append(f"    {row['key']:30s} = {value:40s} [{dt_label}] {desc}")

        lines.append("")
        lines.append(f"{len(rows)} Einstellungen")

        return True, "\n".join(lines)

    def _get(self, key: str) -> tuple:
        """Einzelnen Wert lesen."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT key, value, type, category, description, dist_type, updated_at "
            "FROM system_config WHERE key = ?",
            (key,)
        ).fetchone()
        conn.close()

        if not row:
            return False, f"Setting '{key}' nicht gefunden."

        dt_label = {0: 'USER', 1: 'TEMPLATE', 2: 'CORE'}.get(row['dist_type'], '?')
        lines = [
            f"Key:         {row['key']}",
            f"Value:       {row['value']}",
            f"Type:        {row['type'] or 'string'}",
            f"Category:    {row['category'] or '-'}",
            f"Description: {row['description'] or '-'}",
            f"Dist-Type:   {row['dist_type']} ({dt_label})",
            f"Updated:     {row['updated_at'] or '-'}",
        ]
        return True, "\n".join(lines)

    def _set(self, args: list, dry_run: bool) -> tuple:
        """Setting setzen: key=value."""
        # Erstes Argument: key=value
        kv = args[0]
        if '=' not in kv:
            return False, "Format: bach settings set <key>=<value>"

        key, value = kv.split('=', 1)
        key = key.strip()
        value = value.strip()

        if not key:
            return False, "Key darf nicht leer sein."

        # Optionale Parameter
        category = None
        description = None
        for arg in args[1:]:
            if arg.startswith("--category="):
                category = arg.split("=", 1)[1]
            elif arg.startswith("--desc="):
                description = arg.split("=", 1)[1]

        if dry_run:
            return True, f"[DRY-RUN] Wuerde setzen: {key} = {value}"

        conn = self._get_conn()

        # Pruefen ob der Key CORE ist (dist_type=2)
        existing = conn.execute(
            "SELECT dist_type FROM system_config WHERE key = ?",
            (key,)
        ).fetchone()

        if existing and existing['dist_type'] == 2:
            conn.close()
            return False, f"Setting '{key}' ist CORE (dist_type=2) und kann nicht geaendert werden."

        now = datetime.now().isoformat()

        if existing:
            # Update
            updates = ["value = ?", "updated_at = ?"]
            params = [value, now]
            if category:
                updates.append("category = ?")
                params.append(category)
            if description:
                updates.append("description = ?")
                params.append(description)
            params.append(key)

            conn.execute(
                f"UPDATE system_config SET {', '.join(updates)} WHERE key = ?",
                params
            )
        else:
            # Insert (neue Settings sind USER = dist_type 0)
            conn.execute(
                "INSERT INTO system_config (key, value, type, category, description, updated_at, dist_type) "
                "VALUES (?, ?, 'string', ?, ?, ?, 0)",
                (key, value, category, description, now)
            )

        conn.commit()
        conn.close()

        action = "aktualisiert" if existing else "erstellt"
        msg = f"[OK] Setting {action}: {key} = {value}"

        # SQ037 Stufe 1: Trigger Partner-MD Update (bei Integration-Settings)
        if key.startswith('integration.'):
            self._trigger_partner_md_update()

        return True, msg

    def _trigger_partner_md_update(self):
        """Triggert Partner-MD Update (CLAUDE.md, GEMINI.md etc.)."""
        try:
            import sys

            # Füge tools/ zum Python-Path hinzu
            tools_path = str(self.base_path / "tools")
            if tools_path not in sys.path:
                sys.path.insert(0, tools_path)

            from claude_md_sync import ClaudeMdSync

            # Update alle Partner-Dateien die existieren
            partners = ["CLAUDE", "GEMINI", "OLLAMA"]
            for partner in partners:
                partner_file = self.base_path.parent / f"{partner}.md"
                if partner_file.exists():
                    syncer = ClaudeMdSync(self.base_path.parent, partner_name=partner)
                    syncer.push()

        except Exception:
            # Graceful Degradation: Fehler nicht propagieren
            pass

    def _reset(self, key: str, dry_run: bool) -> tuple:
        """Setting loeschen (nur USER/TEMPLATE, nicht CORE)."""
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT dist_type FROM system_config WHERE key = ?",
            (key,)
        ).fetchone()

        if not existing:
            conn.close()
            return False, f"Setting '{key}' nicht gefunden."

        if existing['dist_type'] == 2:
            conn.close()
            return False, f"Setting '{key}' ist CORE und kann nicht geloescht werden."

        if dry_run:
            conn.close()
            return True, f"[DRY-RUN] Wuerde loeschen: {key}"

        conn.execute("DELETE FROM system_config WHERE key = ?", (key,))
        conn.commit()
        conn.close()

        return True, f"[OK] Setting geloescht: {key}"

    def _export(self, args: list) -> tuple:
        """Settings als JSON exportieren."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT key, value, type, category, description, dist_type "
            "FROM system_config ORDER BY key"
        ).fetchall()
        conn.close()

        data = {}
        for row in rows:
            data[row['key']] = {
                'value': row['value'],
                'type': row['type'],
                'category': row['category'],
                'description': row['description'],
                'dist_type': row['dist_type'],
            }

        output = json.dumps(data, indent=2, ensure_ascii=False)

        # Optional in Datei schreiben
        if args and not args[0].startswith('--'):
            outfile = Path(args[0])
            outfile.write_text(output, encoding='utf-8')
            return True, f"[OK] {len(data)} Settings exportiert nach: {outfile}"

        return True, output

    def _import_settings(self, filepath: str, dry_run: bool) -> tuple:
        """Settings aus JSON importieren (nur USER/TEMPLATE)."""
        path = Path(filepath)
        if not path.exists():
            return False, f"Datei nicht gefunden: {filepath}"

        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            return False, f"Fehler beim Lesen: {e}"

        if dry_run:
            return True, f"[DRY-RUN] Wuerde {len(data)} Settings importieren"

        conn = self._get_conn()
        imported = 0
        skipped = 0
        now = datetime.now().isoformat()

        for key, entry in data.items():
            value = entry.get('value', '')
            dist_type = entry.get('dist_type', 0)

            # CORE-Settings nicht ueberschreiben
            existing = conn.execute(
                "SELECT dist_type FROM system_config WHERE key = ?", (key,)
            ).fetchone()

            if existing and existing['dist_type'] == 2:
                skipped += 1
                continue

            conn.execute(
                "INSERT OR REPLACE INTO system_config "
                "(key, value, type, category, description, updated_at, dist_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, value, entry.get('type', 'string'),
                 entry.get('category'), entry.get('description'),
                 now, min(dist_type, 1))  # Importierte max TEMPLATE
            )
            imported += 1

        conn.commit()
        conn.close()

        return True, f"[OK] {imported} Settings importiert, {skipped} CORE uebersprungen"

    def _categories(self) -> tuple:
        """Alle Kategorien auflisten."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt "
            "FROM system_config "
            "GROUP BY category ORDER BY category"
        ).fetchall()
        conn.close()

        if not rows:
            return True, "Keine Kategorien gefunden."

        lines = ["SETTINGS-KATEGORIEN", "=" * 40, ""]
        for row in rows:
            cat = row['category'] or '(ohne Kategorie)'
            lines.append(f"  {cat:30s} ({row['cnt']} Eintraege)")

        lines.append("")
        lines.append(f"{len(rows)} Kategorien")

        return True, "\n".join(lines)

    def get_settings_summary(self, top_n: int = 10) -> dict:
        """Erstellt eine Zusammenfassung der wichtigsten Settings (für BACH-Block Injektion).

        Args:
            top_n: Anzahl der wichtigsten Settings (Standard: 10)

        Returns:
            Dict mit Kategorien und Settings
        """
        conn = self._get_conn()

        # Hole Settings sortiert nach Wichtigkeit (Kategorie-Priorität + Alphabetisch)
        # Priorisierung: security > behavior > integration > limits > backup > misc
        category_priority = {
            'security': 1,
            'behavior': 2,
            'integration': 3,
            'limits': 4,
            'backup': 5,
        }

        rows = conn.execute(
            "SELECT key, value, category, description "
            "FROM system_config "
            "WHERE value IS NOT NULL "
            "ORDER BY category, key"
        ).fetchall()

        conn.close()

        # Nach Priorität sortieren
        def sort_key(row):
            cat = row['category'] or 'misc'
            prio = category_priority.get(cat, 99)
            return (prio, cat, row['key'])

        sorted_rows = sorted(rows, key=sort_key)[:top_n]

        # Gruppieren nach Kategorie
        result = {}
        for row in sorted_rows:
            cat = row['category'] or 'misc'
            if cat not in result:
                result[cat] = []

            result[cat].append({
                'key': row['key'],
                'value': row['value'],
                'description': row['description']
            })

        return result


def handle_settings_command(args: list):
    """CLI-Wrapper für bach settings Befehle."""
    from pathlib import Path

    # Base-Path (system/)
    base_path = Path(__file__).parent.parent

    handler = SettingsHandler(base_path)

    # Operation und Argumente extrahieren
    if not args:
        success, message = handler.handle("", [], dry_run=False)
    else:
        operation = args[0]
        rest = args[1:]
        success, message = handler.handle(operation, rest, dry_run=False)

    print(message)
    return 0 if success else 1
