# SPDX-License-Identifier: MIT
"""
DB Handler - Datenbank-Operationen (ersetzt Supabase MCP)
==========================================================

bach db status              Datenbank-Status
bach db tables              Tabellen mit Counts
bach db info <tabelle>      Schema + Beispieldaten + dist_type
bach db query "SQL"         SQL-Query ausfuehren
bach db schema <tabelle>    CREATE TABLE Statement
bach db count <tabelle>     Zeilenanzahl
bach db export <tabelle>    Tabelle exportieren (--format csv|json)
bach db insert <tabelle>    Datensatz einfuegen (JSON)
bach db backup              Quick-Backup

Task: 998
"""
import os
import sys
import csv
import io
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler
from .bach_paths import BACKUPS_DIR

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class DbHandler(BaseHandler):
    """Handler fuer --db Operationen"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "db"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "status": "Datenbank-Status anzeigen",
            "tables": "Alle Tabellen mit Counts",
            "info": "Tabellen-Details: info <tabelle> (Schema + Beispieldaten)",
            "query": "SQL-Query ausfuehren",
            "schema": "CREATE TABLE anzeigen: schema <tabelle>",
            "count": "Zeilenanzahl: count <tabelle>",
            "export": "Tabelle exportieren: export <tabelle> [--format csv|json]",
            "insert": "Datensatz einfuegen: insert <tabelle> '{\"col\":\"val\"}'",
            "backup": "Quick-Backup der Datenbank",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.db_path.exists():
            return False, f"Datenbank nicht gefunden: {self.db_path}"

        if operation == "status" or not operation:
            return self._status()
        elif operation == "tables":
            return self._tables()
        elif operation == "query" and args:
            if dry_run:
                return True, f"[DRY-RUN] Query: {' '.join(args)}"
            return self._query(" ".join(args))
        elif operation == "info" and args:
            return self._info(args[0])
        elif operation == "schema" and args:
            return self._schema(args[0])
        elif operation == "count" and args:
            return self._count(args[0])
        elif operation == "export" and args:
            fmt = "csv"
            for a in args[1:]:
                if a.startswith("--format="):
                    fmt = a.split("=", 1)[1]
                elif a in ("csv", "json"):
                    fmt = a
            if dry_run:
                return True, f"[DRY-RUN] Export {args[0]} als {fmt}"
            return self._export(args[0], fmt)
        elif operation == "insert" and len(args) >= 2:
            if dry_run:
                return True, f"[DRY-RUN] Insert in {args[0]}"
            return self._insert(args[0], " ".join(args[1:]))
        elif operation == "backup":
            if dry_run:
                return True, "[DRY-RUN] Backup"
            return self._backup()
        else:
            return self._status()

    def _get_conn(self):
        """DB-Verbindung holen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _status(self) -> tuple:
        """Datenbank-Status."""
        results = ["BACH DATABASE", "=" * 40]
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            tables = cursor.fetchall()
            results.append(f"Tabellen: {len(tables)}")

            size_kb = self.db_path.stat().st_size / 1024
            if size_kb > 1024:
                results.append(f"Groesse:  {size_kb / 1024:.1f} MB")
            else:
                results.append(f"Groesse:  {size_kb:.1f} KB")

            try:
                cursor.execute("SELECT instance_name, version FROM system_identity WHERE id = 1")
                row = cursor.fetchone()
                if row:
                    results.append(f"Instance: {row['instance_name']} v{row['version']}")
            except Exception:
                pass

            views = cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='view'"
            ).fetchone()[0]
            results.append(f"Views:    {views}")

            indices = cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index'"
            ).fetchone()[0]
            results.append(f"Indices:  {indices}")
        finally:
            if conn:
                conn.close()
        return True, "\n".join(results)

    def _tables(self) -> tuple:
        """Tabellen mit Counts."""
        results = ["TABELLEN", "=" * 40]
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
            tables = cursor.fetchall()

            for t in tables:
                name = t['name']
                try:
                    cursor.execute(f"SELECT COUNT(*) as cnt FROM [{name}]")
                    count = cursor.fetchone()['cnt']
                    results.append(f"  {name:<40} {count:>6}")
                except Exception:
                    results.append(f"  {name:<40}  ERROR")
        finally:
            if conn:
                conn.close()
        return True, "\n".join(results)

    def _info(self, table: str) -> tuple:
        """Tabellen-Details: Schema, Spalten, Beispieldaten, dist_type."""
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not row:
                return False, f"Tabelle '{table}' nicht gefunden."

            results = [f"TABELLE: {table}", "=" * 50]

            count = cursor.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            results.append(f"Zeilen: {count}")

            columns = cursor.execute(f"PRAGMA table_info([{table}])").fetchall()
            results.append(f"Spalten: {len(columns)}")
            results.append("")
            results.append("SPALTEN:")
            results.append(f"  {'Name':<30} {'Typ':<15} {'NotNull':<8} {'Default'}")
            results.append("  " + "-" * 70)
            has_dist_type = False
            for col in columns:
                nn = "YES" if col['notnull'] else ""
                dflt = col['dflt_value'] if col['dflt_value'] else ""
                pk = " [PK]" if col['pk'] else ""
                results.append(f"  {col['name']:<30} {(col['type'] or 'ANY'):<15} {nn:<8} {dflt}{pk}")
                if col['name'] == 'dist_type':
                    has_dist_type = True

            if has_dist_type:
                results.append("")
                results.append("DIST_TYPE Verteilung:")
                try:
                    dist_counts = cursor.execute(
                        f"SELECT dist_type, COUNT(*) as cnt FROM [{table}] GROUP BY dist_type ORDER BY dist_type"
                    ).fetchall()
                    labels = {0: "USER", 1: "TEMPLATE", 2: "CORE"}
                    for dc in dist_counts:
                        dt = dc['dist_type'] if dc['dist_type'] is not None else '?'
                        label = labels.get(dc['dist_type'], str(dt))
                        results.append(f"  {label} ({dt}): {dc['cnt']}")
                except Exception:
                    pass

            indices = cursor.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)
            ).fetchall()
            if indices:
                results.append("")
                results.append(f"INDICES ({len(indices)}):")
                for idx in indices:
                    results.append(f"  {idx['name']}")

            if count > 0:
                results.append("")
                results.append(f"BEISPIELDATEN (max 5):")
                try:
                    sample = cursor.execute(f"SELECT * FROM [{table}] LIMIT 5").fetchall()
                    keys = sample[0].keys()
                    show_keys = []
                    for k in keys:
                        show_keys.append(k)
                        if len(show_keys) >= 6:
                            break
                    results.append("  " + " | ".join(f"{k[:20]}" for k in show_keys))
                    results.append("  " + "-" * min(len(show_keys) * 22, 130))
                    for s in sample:
                        vals = []
                        for k in show_keys:
                            v = str(s[k]) if s[k] is not None else "NULL"
                            if len(v) > 20:
                                v = v[:17] + "..."
                            vals.append(v)
                        results.append("  " + " | ".join(f"{v:<20}" for v in vals))
                    if len(show_keys) < len(keys):
                        results.append(f"  ... +{len(keys) - len(show_keys)} weitere Spalten")
                except Exception as e:
                    results.append(f"  (Fehler beim Lesen: {e})")

            return True, "\n".join(results)
        finally:
            if conn:
                conn.close()

    def _query(self, sql: str) -> tuple:
        """SQL-Query ausfuehren."""
        results = []
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            try:
                cursor.execute(sql)

                if sql.strip().upper().startswith("SELECT"):
                    rows = cursor.fetchall()
                    if rows:
                        keys = rows[0].keys()
                        results.append(" | ".join(keys))
                        results.append("-" * 50)
                        for row in rows[:50]:
                            results.append(" | ".join(str(row[k]) for k in keys))
                        if len(rows) > 50:
                            results.append(f"... und {len(rows) - 50} weitere")
                    else:
                        results.append("Keine Ergebnisse.")
                else:
                    conn.commit()
                    results.append(f"[OK] {cursor.rowcount} Zeilen betroffen.")

            except Exception as e:
                results.append(f"[FEHLER] {e}")
        finally:
            if conn:
                conn.close()
        return True, "\n".join(results)

    def _schema(self, table: str) -> tuple:
        """Zeigt CREATE TABLE Statement."""
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()

            if not row:
                return False, f"Tabelle '{table}' nicht gefunden."

            indices = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)
            ).fetchall()

            result = [row['sql'] + ";"]
            for idx in indices:
                result.append(idx['sql'] + ";")
            return True, "\n".join(result)
        finally:
            if conn:
                conn.close()

    def _count(self, table: str) -> tuple:
        """Zeilenanzahl einer Tabelle."""
        conn = None
        try:
            conn = self._get_conn()
            count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            return True, f"{table}: {count} Eintraege"
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            if conn:
                conn.close()

    def _export(self, table: str, fmt: str = "csv") -> tuple:
        """Tabelle als CSV oder JSON exportieren."""
        conn = None
        try:
            conn = self._get_conn()
            rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            if conn:
                conn.close()

        if not rows:
            return True, f"Tabelle '{table}' ist leer."

        keys = rows[0].keys()

        export_dir = self.base_path / "data" / "export"
        export_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            if fmt == "json":
                data = [dict(row) for row in rows]
                out_file = export_dir / f"{table}_{ts}.json"
                out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            else:
                out_file = export_dir / f"{table}_{ts}.csv"
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(keys)
                for row in rows:
                    writer.writerow([row[k] for k in keys])
                out_file.write_text(output.getvalue(), encoding='utf-8')
        except Exception as e:
            return False, f"Fehler: {e}"

        return True, f"Exportiert: {out_file}\n  {len(rows)} Eintraege, Format: {fmt}"

    def _insert(self, table: str, json_str: str) -> tuple:
        """Datensatz einfuegen."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return False, f"Ungueltige JSON-Daten: {e}\nBeispiel: bach db insert tasks '{{\"title\":\"Test\"}}'"

        if not isinstance(data, dict):
            return False, "JSON muss ein Objekt sein: {\"spalte\": \"wert\"}"

        conn = self._get_conn()
        try:
            # Validierung: Spalten pruefen
            info = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
            if not info:
                return False, f"Tabelle '{table}' nicht gefunden."

            valid_cols = {row['name'] for row in info}
            invalid = set(data.keys()) - valid_cols
            if invalid:
                return False, f"Unbekannte Spalten: {invalid}\nErlaubt: {valid_cols}"

            cols = list(data.keys())
            vals = [data[c] for c in cols]
            placeholders = ','.join(['?' for _ in cols])
            col_names = ','.join([f'[{c}]' for c in cols])

            conn.execute(f"INSERT INTO [{table}] ({col_names}) VALUES ({placeholders})", vals)
            conn.commit()
            return True, f"[OK] Datensatz in '{table}' eingefuegt."
        except Exception as e:
            return False, f"Insert-Fehler: {e}"
        finally:
            conn.close()

    def _backup(self) -> tuple:
        """Quick-Backup der Datenbank."""
        # Backups LOKAL speichern — NICHT in OneDrive
        backup_dir = BACKUPS_DIR / "db_quick"
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"bach_quick_{ts}.db"

        try:
            shutil.copy2(str(self.db_path), str(backup_file))
            size_kb = backup_file.stat().st_size / 1024
            return True, f"[OK] Backup: {backup_file} ({size_kb:.0f}KB)"
        except Exception as e:
            return False, f"Backup-Fehler: {e}"
