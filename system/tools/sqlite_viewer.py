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
Tool: sqlite_viewer
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version sqlite_viewer

Description:
    [Beschreibung hinzufügen]

Usage:
    python sqlite_viewer.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
sqlite_viewer_cli.py - CLI-Adapter für SQLite Viewer

Zeigt und exportiert SQLite Datenbankinhalte.
Kernlogik extrahiert aus show_user_sqlite.py

Usage:
    python sqlite_viewer_cli.py <database.db> --tables
    python sqlite_viewer_cli.py <database.db> --table <name> [--limit 100]
    python sqlite_viewer_cli.py <database.db> --query "SELECT * FROM users"
    python sqlite_viewer_cli.py <database.db> --schema
    python sqlite_viewer_cli.py <database.db> --export <table> --format csv
"""

import os
import sys
import sqlite3
import argparse
import json
import csv
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple


def connect_db(db_path: str) -> Tuple[Optional[sqlite3.Connection], str]:
    """Verbindet zu SQLite Datenbank"""
    path = Path(db_path)
    if not path.exists():
        return None, f"Datenbank nicht gefunden: {db_path}"
    
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn, "OK"
    except Exception as e:
        return None, f"Verbindungsfehler: {e}"


def get_tables(conn: sqlite3.Connection) -> List[str]:
    """Liste aller Tabellen"""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def get_table_info(conn: sqlite3.Connection, table: str) -> List[Dict]:
    """Spalteninformationen einer Tabelle"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = []
    for row in cursor.fetchall():
        columns.append({
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": bool(row[3]),
            "default": row[4],
            "pk": bool(row[5])
        })
    return columns


def get_table_count(conn: sqlite3.Connection, table: str) -> int:
    """Anzahl Zeilen in Tabelle"""
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0]


def query_table(conn: sqlite3.Connection, table: str, 
                limit: int = 100, offset: int = 0) -> Tuple[List[str], List[Dict]]:
    """Abfrage einer Tabelle mit Limit/Offset"""
    cursor = conn.execute(f"SELECT * FROM {table} LIMIT ? OFFSET ?", (limit, offset))
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(row) for row in cursor.fetchall()]
    return columns, rows


def execute_query(conn: sqlite3.Connection, query: str) -> Tuple[List[str], List[Dict], str]:
    """Führt beliebige SQL-Query aus"""
    try:
        cursor = conn.execute(query)
        if cursor.description:
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(row) for row in cursor.fetchall()]
            return columns, rows, "OK"
        else:
            conn.commit()
            return [], [], f"Befehl ausgeführt. Zeilen betroffen: {cursor.rowcount}"
    except Exception as e:
        return [], [], f"SQL-Fehler: {e}"


def get_schema(conn: sqlite3.Connection) -> Dict:
    """Komplettes Datenbankschema"""
    schema = {}
    for table in get_tables(conn):
        schema[table] = {
            "columns": get_table_info(conn, table),
            "row_count": get_table_count(conn, table)
        }
    return schema


def export_table_csv(conn: sqlite3.Connection, table: str, 
                     output_path: str, limit: Optional[int] = None) -> Tuple[bool, str]:
    """Exportiert Tabelle als CSV"""
    try:
        query = f"SELECT * FROM {table}"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor = conn.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        
        return True, f"Exportiert: {len(rows)} Zeilen"
    except Exception as e:
        return False, f"Export-Fehler: {e}"


def export_table_json(conn: sqlite3.Connection, table: str,
                      output_path: str, limit: Optional[int] = None) -> Tuple[bool, str]:
    """Exportiert Tabelle als JSON"""
    try:
        query = f"SELECT * FROM {table}"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor = conn.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(rows, f, indent=2, ensure_ascii=False, default=str)
        
        return True, f"Exportiert: {len(rows)} Zeilen"
    except Exception as e:
        return False, f"Export-Fehler: {e}"


def print_table(columns: List[str], rows: List[Dict], max_width: int = 40):
    """Gibt Tabelle formatiert aus"""
    if not rows:
        print("(keine Daten)")
        return
    
    # Spaltenbreiten berechnen
    widths = {col: len(col) for col in columns}
    for row in rows[:100]:  # Nur erste 100 für Breitenberechnung
        for col in columns:
            val = str(row.get(col, ''))[:max_width]
            widths[col] = max(widths[col], len(val))
    
    # Header
    header = " | ".join(col.ljust(widths[col])[:max_width] for col in columns)
    print(header)
    print("-" * len(header))
    
    # Daten
    for row in rows:
        line = " | ".join(
            str(row.get(col, '')).ljust(widths[col])[:max_width] 
            for col in columns
        )
        print(line)


def main():
    parser = argparse.ArgumentParser(
        description="SQLite Viewer - Zeigt und exportiert Datenbankinhalte"
    )
    parser.add_argument("database", help="SQLite Datenbankdatei")
    parser.add_argument("--tables", action="store_true", help="Liste alle Tabellen")
    parser.add_argument("--table", "-t", help="Zeige Tabelleninhalt")
    parser.add_argument("--query", "-q", help="SQL-Query ausführen")
    parser.add_argument("--schema", action="store_true", help="Zeige Datenbankschema")
    parser.add_argument("--limit", "-l", type=int, default=100, help="Zeilenlimit (default: 100)")
    parser.add_argument("--offset", type=int, default=0, help="Offset für Paginierung")
    parser.add_argument("--export", "-e", help="Tabelle exportieren")
    parser.add_argument("--format", "-f", choices=["csv", "json"], default="csv",
                       help="Exportformat (default: csv)")
    parser.add_argument("--output", "-o", help="Ausgabedatei")
    parser.add_argument("--json", action="store_true", help="JSON-Ausgabe")
    
    args = parser.parse_args()
    
    conn, error = connect_db(args.database)
    if not conn:
        print(f"ERROR: {error}")
        sys.exit(1)
    
    try:
        if args.tables:
            tables = get_tables(conn)
            if args.json:
                print(json.dumps(tables, indent=2))
            else:
                print(f"Tabellen ({len(tables)}):")
                for t in tables:
                    count = get_table_count(conn, t)
                    print(f"  {t} ({count} Zeilen)")
        
        elif args.schema:
            schema = get_schema(conn)
            if args.json:
                print(json.dumps(schema, indent=2))
            else:
                for table, info in schema.items():
                    print(f"\n=== {table} ({info['row_count']} Zeilen) ===")
                    for col in info['columns']:
                        pk = " [PK]" if col['pk'] else ""
                        nn = " NOT NULL" if col['notnull'] else ""
                        print(f"  {col['name']}: {col['type']}{pk}{nn}")
        
        elif args.export:
            output = args.output or f"{args.export}.{args.format}"
            if args.format == "csv":
                success, msg = export_table_csv(conn, args.export, output, args.limit)
            else:
                success, msg = export_table_json(conn, args.export, output, args.limit)
            
            if success:
                print(f"✅ {msg} → {output}")
            else:
                print(f"❌ {msg}")
        
        elif args.query:
            columns, rows, msg = execute_query(conn, args.query)
            if args.json:
                print(json.dumps({"columns": columns, "rows": rows, "message": msg}, 
                               indent=2, default=str))
            elif rows:
                print_table(columns, rows)
                print(f"\n({len(rows)} Zeilen)")
            else:
                print(msg)
        
        elif args.table:
            columns, rows = query_table(conn, args.table, args.limit, args.offset)
            total = get_table_count(conn, args.table)
            
            if args.json:
                print(json.dumps({"table": args.table, "columns": columns, 
                                "rows": rows, "total": total}, indent=2, default=str))
            else:
                print(f"Tabelle: {args.table} ({total} Zeilen total)")
                print(f"Zeige: {args.offset+1}-{args.offset+len(rows)}\n")
                print_table(columns, rows)
        
        else:
            parser.print_help()
    
    finally:
        conn.close()


if __name__ == "__main__":
    main()
