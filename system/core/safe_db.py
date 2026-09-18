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
Safe DB Access Layer
====================
Validierte Schnellspur fuer direkten DB-Zugriff.
Fuehlt sich wie SQL an, ist aber sicher:

    from bach_api import db
    db.select("tasks", where={"status": "pending"})
    db.update("bach_experts", {"persona": "Neuer Text"}, where={"name": "mr_tiktak"})
    db.insert("tasks", {"title": "Aufgabe", "priority": "high"})
    db.delete("tasks", where={"id": 42})

Sicherheitsschichten:
1. Tabellen-Whitelist (nur bekannte BACH-Tabellen)
2. Schema-Validierung (Spalten gegen PRAGMA table_info)
3. WHERE-Pflicht bei UPDATE/DELETE
4. Hook-Trigger (after_memory_write, after_task_create etc.)
5. Audit-Log (monitor_db_changes)
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# Tabellen die NIEMALS ueber SafeDB beschrieben werden duerfen
_BLOCKED_TABLES = frozenset({
    "_migrations",
    "sqlite_master",
    "sqlite_sequence",
})

# Hook-Mapping: Tabelle+Operation -> Hook-Event
_HOOK_MAP = {
    ("tasks", "insert"): "after_task_create",
    ("tasks", "delete"): "after_task_delete",
    ("memory_working", "insert"): "after_memory_write",
    ("memory_working", "update"): "after_memory_write",
    ("memory_facts", "insert"): "after_memory_write",
    ("memory_lessons", "insert"): "after_lesson_add",
}


class SafeDBError(Exception):
    """Fehler bei SafeDB-Operationen."""
    pass


class SafeDB:
    """Validierter DB-Zugriff mit Whitelist, Schema-Check und Audit-Log.

    Args:
        db_path: Pfad zur bach.db
        partner: Aufrufender Partner (fuer Audit-Log)
    """

    def __init__(self, db_path: Path, partner: str = "unknown"):
        self.db_path = Path(db_path)
        self.partner = partner
        self._schema_cache: dict[str, list[str]] = {}
        self._hooks = None

    def _connect(self, read_only: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        if read_only:
            conn.execute("PRAGMA query_only = ON")
        return conn

    def _get_columns(self, conn: sqlite3.Connection, table: str) -> list[str]:
        """Gibt gueltige Spaltennamen fuer eine Tabelle zurueck (gecacht)."""
        if table not in self._schema_cache:
            rows = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
            if not rows:
                raise SafeDBError(f"Tabelle '{table}' existiert nicht")
            self._schema_cache[table] = [row[1] for row in rows]
        return self._schema_cache[table]

    def _validate_table(self, table: str):
        """Prueft ob Tabelle erlaubt ist."""
        if table in _BLOCKED_TABLES:
            raise SafeDBError(f"Tabelle '{table}' ist gesperrt")
        if not table.replace("_", "").replace("-", "").isalnum():
            raise SafeDBError(f"Ungueltiger Tabellenname: '{table}'")

    def _validate_columns(self, conn: sqlite3.Connection, table: str,
                          columns: list[str]):
        """Prueft ob alle Spalten in der Tabelle existieren."""
        valid = self._get_columns(conn, table)
        for col in columns:
            if col not in valid:
                raise SafeDBError(
                    f"Spalte '{col}' existiert nicht in '{table}'. "
                    f"Gueltig: {', '.join(valid)}"
                )

    def _build_where(self, where: dict) -> tuple[str, list]:
        """Baut WHERE-Klausel aus dict. Gibt (sql, params) zurueck."""
        if not where:
            raise SafeDBError("WHERE-Bedingung ist Pflicht bei UPDATE/DELETE")
        clauses = []
        params = []
        for col, val in where.items():
            if val is None:
                clauses.append(f"[{col}] IS NULL")
            else:
                clauses.append(f"[{col}] = ?")
                params.append(val)
        return " AND ".join(clauses), params

    def _fire_hook(self, table: str, operation: str, data: dict = None):
        """Feuert BACH-Hook wenn konfiguriert."""
        event = _HOOK_MAP.get((table, operation))
        if not event:
            return
        try:
            if self._hooks is None:
                from core.hooks import hooks
                self._hooks = hooks
            self._hooks.emit(event, data or {})
        except (ImportError, Exception):
            pass

    def _audit_log(self, conn: sqlite3.Connection, table: str,
                   operation: str, affected_rows: int, details: str = ""):
        """Schreibt Audit-Log in monitor_db_changes."""
        try:
            conn.execute("""
                INSERT INTO monitor_db_changes
                (timestamp, partner, table_name, operation, affected_rows, details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                self.partner,
                table,
                operation,
                affected_rows,
                details[:500] if details else ""
            ))
        except sqlite3.OperationalError:
            # Tabelle existiert noch nicht -- wird bei erster Nutzung erstellt
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS monitor_db_changes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        partner TEXT DEFAULT 'unknown',
                        table_name TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        affected_rows INTEGER DEFAULT 0,
                        details TEXT DEFAULT ''
                    )
                """)
                conn.execute("""
                    INSERT INTO monitor_db_changes
                    (timestamp, partner, table_name, operation, affected_rows, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    self.partner,
                    table,
                    operation,
                    affected_rows,
                    details[:500] if details else ""
                ))
            except Exception:
                pass

    # --- Public API ---

    def select(self, table: str, columns: list[str] = None,
               where: dict = None, order_by: str = None,
               limit: int = None) -> list[dict]:
        """SELECT mit optionalem WHERE, ORDER BY, LIMIT.

        Args:
            table: Tabellenname
            columns: Spaltenliste (None = alle)
            where: Filter als dict (col: value)
            order_by: Sortierung (z.B. "created_at DESC")
            limit: Maximale Zeilenanzahl

        Returns:
            Liste von Dicts
        """
        self._validate_table(table)
        conn = self._connect(read_only=True)
        try:
            if columns:
                self._validate_columns(conn, table, columns)
                col_str = ", ".join(f"[{c}]" for c in columns)
            else:
                col_str = "*"

            sql = f"SELECT {col_str} FROM [{table}]"
            params = []

            if where:
                self._validate_columns(conn, table, list(where.keys()))
                where_sql, where_params = self._build_where(where)
                sql += f" WHERE {where_sql}"
                params.extend(where_params)

            if order_by:
                # Einfache Validierung: nur Spaltenname + ASC/DESC
                parts = order_by.strip().split()
                col_name = parts[0]
                self._validate_columns(conn, table, [col_name])
                direction = parts[1].upper() if len(parts) > 1 else "ASC"
                if direction not in ("ASC", "DESC"):
                    direction = "ASC"
                sql += f" ORDER BY [{col_name}] {direction}"

            if limit and isinstance(limit, int) and limit > 0:
                sql += f" LIMIT {limit}"

            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def insert(self, table: str, data: dict) -> int:
        """INSERT mit Schema-Validierung und Audit-Log.

        Args:
            table: Tabellenname
            data: Dict mit {spalte: wert}

        Returns:
            lastrowid (ID des neuen Eintrags)
        """
        self._validate_table(table)
        if not data:
            raise SafeDBError("Keine Daten zum Einfuegen")

        conn = self._connect()
        try:
            self._validate_columns(conn, table, list(data.keys()))

            columns = ", ".join(f"[{c}]" for c in data.keys())
            placeholders = ", ".join("?" for _ in data)
            sql = f"INSERT INTO [{table}] ({columns}) VALUES ({placeholders})"

            cursor = conn.execute(sql, list(data.values()))
            rowid = cursor.lastrowid
            self._audit_log(conn, table, "INSERT", 1,
                            f"id={rowid}, keys={list(data.keys())}")
            conn.commit()
            self._fire_hook(table, "insert", data)
            return rowid
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise SafeDBError(f"Integritaetsfehler: {e}")
        finally:
            conn.close()

    def update(self, table: str, data: dict, where: dict) -> int:
        """UPDATE mit WHERE-Pflicht, Schema-Validierung und Audit-Log.

        Args:
            table: Tabellenname
            data: Dict mit {spalte: neuer_wert}
            where: Filter als dict (Pflicht!)

        Returns:
            Anzahl geaenderter Zeilen
        """
        self._validate_table(table)
        if not data:
            raise SafeDBError("Keine Daten zum Aktualisieren")
        if not where:
            raise SafeDBError("WHERE-Bedingung ist Pflicht bei UPDATE")

        conn = self._connect()
        try:
            all_cols = list(data.keys()) + list(where.keys())
            self._validate_columns(conn, table, all_cols)

            set_clause = ", ".join(f"[{c}] = ?" for c in data.keys())
            where_sql, where_params = self._build_where(where)
            sql = f"UPDATE [{table}] SET {set_clause} WHERE {where_sql}"
            params = list(data.values()) + where_params

            cursor = conn.execute(sql, params)
            affected = cursor.rowcount
            self._audit_log(conn, table, "UPDATE", affected,
                            f"set={list(data.keys())}, where={where}")
            conn.commit()
            self._fire_hook(table, "update", {**data, **where})
            return affected
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise SafeDBError(f"Integritaetsfehler: {e}")
        finally:
            conn.close()

    def delete(self, table: str, where: dict) -> int:
        """DELETE mit WHERE-Pflicht und Audit-Log.

        Args:
            table: Tabellenname
            where: Filter als dict (Pflicht!)

        Returns:
            Anzahl geloeschter Zeilen
        """
        self._validate_table(table)
        if not where:
            raise SafeDBError("WHERE-Bedingung ist Pflicht bei DELETE")

        conn = self._connect()
        try:
            self._validate_columns(conn, table, list(where.keys()))
            where_sql, where_params = self._build_where(where)
            sql = f"DELETE FROM [{table}] WHERE {where_sql}"

            cursor = conn.execute(sql, where_params)
            affected = cursor.rowcount
            self._audit_log(conn, table, "DELETE", affected,
                            f"where={where}")
            conn.commit()
            self._fire_hook(table, "delete", where)
            return affected
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise SafeDBError(f"Integritaetsfehler: {e}")
        finally:
            conn.close()

    def count(self, table: str, where: dict = None) -> int:
        """COUNT mit optionalem WHERE.

        Args:
            table: Tabellenname
            where: Optionaler Filter

        Returns:
            Anzahl der Zeilen
        """
        self._validate_table(table)
        conn = self._connect()
        try:
            sql = f"SELECT COUNT(*) FROM [{table}]"
            params = []
            if where:
                self._validate_columns(conn, table, list(where.keys()))
                where_sql, where_params = self._build_where(where)
                sql += f" WHERE {where_sql}"
                params.extend(where_params)
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def exists(self, table: str, where: dict) -> bool:
        """Prueft ob mindestens ein Eintrag existiert.

        Args:
            table: Tabellenname
            where: Filter als dict

        Returns:
            True wenn mindestens ein Eintrag existiert
        """
        return self.count(table, where) > 0

    def tables(self) -> list[str]:
        """Gibt alle Tabellennamen zurueck."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()

    def schema(self, table: str) -> list[dict]:
        """Gibt Schema-Info fuer eine Tabelle zurueck.

        Returns:
            Liste von {name, type, notnull, default, pk}
        """
        self._validate_table(table)
        conn = self._connect()
        try:
            rows = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
            return [
                {"name": r[1], "type": r[2], "notnull": bool(r[3]),
                 "default": r[4], "pk": bool(r[5])}
                for r in rows
            ]
        finally:
            conn.close()
