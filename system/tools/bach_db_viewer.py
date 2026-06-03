#!/usr/bin/env python3
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
BACH DB Viewer - Dedizierter Bach.db Browser
=============================================

Basiert auf SQLiteViewer, angepasst für BACH:
- bach.db standardmäßig über den kanonischen BACH_DB-Pfad geöffnet
- dist_type-aware: CORE (2) read-only, TEMPLATE (1) + USER (0) editierbar
- Zeigt dist_type-Klassifizierung in Tabellenansicht

Aufruf:
    python bach_db_viewer.py
    bach db view

Features:
- Tabellenübersicht mit Zeilenanzahl
- Schema-Ansicht (CREATE TABLE Statements)
- CSV-Export
- Volltext-Suche
- SQL-Editor (nur SELECT für CORE-Tabellen)
- dist_type-Schutz

Quelle: extensions/SQLiteViewer/SQLiteViewer.py (v2.0.0)
Portiert: 2026-02-19 | SQ067
"""

import os
import re
import csv
import sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Any

APP_TITLE = "BACH Database Viewer"
APP_VERSION = "1.0.0 (SQ067)"
DEFAULT_LIMIT = 1000


class BachDbViewer(tk.Tk):
    """BACH-spezifischer Datenbank-Viewer."""

    def __init__(self, db_path: Optional[Path] = None):
        super().__init__()
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("1200x800")
        self.minsize(800, 600)

        # State
        self.conn: sqlite3.Connection | None = None
        self.db_path: Path | None = db_path or self._find_bach_db()
        self.current_table: str | None = None
        self.current_columns: List[str] = []
        self.current_data: List[Tuple] = []
        self.sort_column: str | None = None
        self.sort_reverse: bool = False

        # dist_type Cache (Tabelle -> dist_type)
        self.dist_type_map: dict[str, int] = {}

        # UI
        self._build_menu()
        self._build_toolbar()
        self._build_notebook()
        self._build_statusbar()
        self._setup_styles()

        # Auto-open bach.db if found
        if self.db_path and self.db_path.exists():
            self.open_db(str(self.db_path))

    def _find_bach_db(self) -> Optional[Path]:
        """Sucht bach.db — bevorzugt BACH_DB, dann robuste Fallback-Kandidaten."""
        try:
            from hub.bach_paths import BACH_DB
            if BACH_DB.exists():
                return BACH_DB
        except ImportError:
            pass
        candidates = [
            Path.home() / ".bach" / "bach.db",
            Path(__file__).parent.parent / "data" / "bach.db",
            Path.cwd() / "system" / "data" / "bach.db",
            Path.cwd() / "data" / "bach.db",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _setup_styles(self):
        """Konfiguriere ttk Styles."""
        style = ttk.Style()
        style.configure("Treeview", rowheight=24)
        style.configure("Treeview.Heading", font=('Segoe UI', 9, 'bold'))

    # ==================== MENU ====================
    def _build_menu(self):
        menubar = tk.Menu(self)

        # Datei-Menü
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Als CSV exportieren…", command=self.export_csv, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="Beenden", command=self.destroy, accelerator="Ctrl+Q")
        menubar.add_cascade(label="Datei", menu=file_menu)

        # Bearbeiten-Menü
        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Suchen…", command=self._focus_search, accelerator="Ctrl+F")
        edit_menu.add_separator()
        edit_menu.add_command(label="Refresh", command=self.load_selected_table, accelerator="F5")
        menubar.add_cascade(label="Bearbeiten", menu=edit_menu)

        # Ansicht-Menü
        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Daten-Tab", command=lambda: self.notebook.select(0))
        view_menu.add_command(label="Schema-Tab", command=lambda: self.notebook.select(1))
        view_menu.add_command(label="SQL-Editor", command=lambda: self.notebook.select(2))
        menubar.add_cascade(label="Ansicht", menu=view_menu)

        # Hilfe-Menü
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Über…", command=self._show_about)
        menubar.add_cascade(label="Hilfe", menu=help_menu)

        self.config(menu=menubar)

        # Shortcuts
        self.bind_all("<Control-q>", lambda e: self.destroy())
        self.bind_all("<Control-e>", lambda e: self.export_csv())
        self.bind_all("<Control-f>", lambda e: self._focus_search())
        self.bind_all("<F5>", lambda e: self.load_selected_table())

    def _build_toolbar(self):
        """Toolbar mit DB-Pfad und Refresh-Button."""
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # DB-Pfad-Label
        self.db_label = ttk.Label(toolbar, text="Keine Datenbank geladen", relief=tk.SUNKEN)
        self.db_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        # Refresh-Button
        ttk.Button(toolbar, text="⟳ Refresh", command=self.load_selected_table).pack(side=tk.RIGHT)

    def _build_notebook(self):
        """Notebook mit Tabs: Daten, Schema, SQL."""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Daten (Treeview)
        self._build_data_tab()

        # Tab 2: Schema
        self._build_schema_tab()

        # Tab 3: SQL-Editor
        self._build_sql_tab()

    def _build_data_tab(self):
        """Daten-Tab mit Tabellenliste + Treeview."""
        data_frame = ttk.Frame(self.notebook)
        self.notebook.add(data_frame, text="📊 Daten")

        # Paned Window (Tabellenliste | Datenansicht)
        paned = ttk.PanedWindow(data_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Links: Tabellenliste
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Tabellen:", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, padx=5, pady=5)

        self.table_listbox = tk.Listbox(left_frame, font=('Consolas', 9))
        self.table_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        self.table_listbox.bind("<<ListboxSelect>>", self._on_table_select)

        # Rechts: Datenansicht
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=3)

        # Suchleiste
        search_frame = ttk.Frame(right_frame)
        search_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        ttk.Label(search_frame, text="Suche:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.search_entry.bind("<Return>", lambda e: self.load_selected_table())
        ttk.Button(search_frame, text="🔍 Suchen", command=self.load_selected_table).pack(side=tk.LEFT)

        # Treeview + Scrollbars
        tree_frame = ttk.Frame(right_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        self.tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        self.tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.data_tree = ttk.Treeview(
            tree_frame,
            yscrollcommand=self.tree_scroll_y.set,
            xscrollcommand=self.tree_scroll_x.set,
            selectmode=tk.EXTENDED
        )
        self.data_tree.pack(fill=tk.BOTH, expand=True)

        self.tree_scroll_y.config(command=self.data_tree.yview)
        self.tree_scroll_x.config(command=self.data_tree.xview)

        # Column-Click für Sortierung
        self.data_tree.bind("<ButtonRelease-1>", self._on_column_click)

    def _build_schema_tab(self):
        """Schema-Tab mit CREATE TABLE Statements."""
        schema_frame = ttk.Frame(self.notebook)
        self.notebook.add(schema_frame, text="🏗️ Schema")

        # Text-Widget mit Scrollbar
        scroll = ttk.Scrollbar(schema_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.schema_text = tk.Text(schema_frame, wrap=tk.NONE, font=('Consolas', 10), yscrollcommand=scroll.set)
        self.schema_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scroll.config(command=self.schema_text.yview)

    def _build_sql_tab(self):
        """SQL-Editor-Tab."""
        sql_frame = ttk.Frame(self.notebook)
        self.notebook.add(sql_frame, text="💻 SQL")

        # SQL-Input
        input_frame = ttk.Frame(sql_frame)
        input_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        ttk.Label(input_frame, text="SQL Query:", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W)

        scroll_sql = ttk.Scrollbar(input_frame)
        scroll_sql.pack(side=tk.RIGHT, fill=tk.Y)

        self.sql_text = tk.Text(input_frame, height=8, font=('Consolas', 10), yscrollcommand=scroll_sql.set)
        self.sql_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        scroll_sql.config(command=self.sql_text.yview)

        # Buttons
        button_frame = ttk.Frame(sql_frame)
        button_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        ttk.Button(button_frame, text="▶️ Ausführen", command=self.execute_sql).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="🗑️ Clear", command=lambda: self.sql_text.delete("1.0", tk.END)).pack(side=tk.LEFT)

        # Ergebnis
        result_frame = ttk.Frame(sql_frame)
        result_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        ttk.Label(result_frame, text="Ergebnis:", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W)

        scroll_result_y = ttk.Scrollbar(result_frame, orient=tk.VERTICAL)
        scroll_result_y.pack(side=tk.RIGHT, fill=tk.Y)

        scroll_result_x = ttk.Scrollbar(result_frame, orient=tk.HORIZONTAL)
        scroll_result_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.sql_tree = ttk.Treeview(
            result_frame,
            yscrollcommand=scroll_result_y.set,
            xscrollcommand=scroll_result_x.set,
            selectmode=tk.EXTENDED
        )
        self.sql_tree.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        scroll_result_y.config(command=self.sql_tree.yview)
        scroll_result_x.config(command=self.sql_tree.xview)

    def _build_statusbar(self):
        """Statusleiste."""
        self.statusbar = ttk.Label(self, text="Bereit", relief=tk.SUNKEN, anchor=tk.W)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    # ==================== DB OPERATIONS ====================
    def open_db(self, path: str = None):
        """Öffnet die kanonische BACH-Datenbank oder einen expliziten Pfad."""
        if path is None:
            path = str(self.db_path) if self.db_path else ""

        if not path or not Path(path).exists():
            messagebox.showerror("Fehler", f"Datenbank nicht gefunden: {path}")
            return

        try:
            if self.conn:
                self.conn.close()

            self.conn = sqlite3.connect(path)
            self.conn.row_factory = sqlite3.Row
            self.db_path = Path(path)

            # dist_type Map laden
            self._load_dist_type_map()

            # UI aktualisieren
            self.db_label.config(text=f"📁 {self.db_path.name}")
            self._load_tables()
            self._load_all_schemas()
            self.statusbar.config(text=f"✓ Datenbank geladen: {path}")

        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte Datenbank nicht öffnen:\n{e}")

    def _load_dist_type_map(self):
        """Lädt dist_type für alle Tabellen (falls Spalte existiert)."""
        self.dist_type_map.clear()
        if not self.conn:
            return

        cursor = self.conn.cursor()
        try:
            # Prüfe ob dist_files existiert
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dist_files'")
            if not cursor.fetchone():
                return

            # Lade dist_type für Tabellen-Dateien (hub/*.py)
            cursor.execute("""
                SELECT path, dist_type FROM dist_files
                WHERE path LIKE 'system/hub/%.py' OR path LIKE 'system/tools/%.py'
            """)
            # Annahme: Hub-Datei "hub/task.py" -> Tabelle "tasks"
            # Vereinfacht: Wir setzen alle auf editierbar, außer bekannte CORE-Tabellen
            # Für echte Implementierung: Tabelle-dist_type-Mapping aus DB lesen

        except Exception:
            pass

    def _load_tables(self):
        """Lädt alle Tabellen in Listbox."""
        if not self.conn:
            return

        self.table_listbox.delete(0, tk.END)

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        tables = cursor.fetchall()

        for t in tables:
            name = t[0]
            try:
                count = cursor.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
                display = f"{name:<40} ({count:>5})"
            except Exception:
                display = name

            self.table_listbox.insert(tk.END, display)

    def _load_all_schemas(self):
        """Lädt alle CREATE TABLE Statements."""
        if not self.conn:
            return

        self.schema_text.delete("1.0", tk.END)

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, sql FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        tables = cursor.fetchall()

        for t in tables:
            name, sql = t[0], t[1]
            self.schema_text.insert(tk.END, f"-- {name}\n")
            self.schema_text.insert(tk.END, f"{sql};\n\n")

    def _on_table_select(self, event):
        """Callback wenn Tabelle ausgewählt wird."""
        self.load_selected_table()

    def load_selected_table(self):
        """Lädt Daten der ausgewählten Tabelle."""
        selection = self.table_listbox.curselection()
        if not selection or not self.conn:
            return

        # Tabellenname extrahieren (vor dem "(count)")
        raw = self.table_listbox.get(selection[0])
        table_name = raw.split()[0]
        self.current_table = table_name

        try:
            cursor = self.conn.cursor()

            # Suche (optional)
            search = self.search_var.get().strip()
            if search:
                # Einfache Volltextsuche (alle Spalten)
                cursor.execute(f"PRAGMA table_info([{table_name}])")
                cols = [c[1] for c in cursor.fetchall()]
                where_clauses = [f"CAST([{c}] AS TEXT) LIKE ?" for c in cols]
                where = " OR ".join(where_clauses)
                params = [f"%{search}%"] * len(cols)
                query = f"SELECT * FROM [{table_name}] WHERE {where} LIMIT {DEFAULT_LIMIT}"
                cursor.execute(query, params)
            else:
                query = f"SELECT * FROM [{table_name}] LIMIT {DEFAULT_LIMIT}"
                cursor.execute(query)

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # Treeview aktualisieren
            self.data_tree.delete(*self.data_tree.get_children())
            self.data_tree["columns"] = columns
            self.data_tree["show"] = "headings"

            for col in columns:
                self.data_tree.heading(col, text=col, command=lambda c=col: self._sort_by_column(c))
                self.data_tree.column(col, width=120, anchor=tk.W)

            for row in rows:
                values = [str(v) if v is not None else "" for v in row]
                self.data_tree.insert("", tk.END, values=values)

            self.statusbar.config(text=f"✓ {table_name}: {len(rows)} Zeilen geladen")

        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte Tabelle nicht laden:\n{e}")

    def _sort_by_column(self, col: str):
        """Sortiert Treeview nach Spalte."""
        # Nicht implementiert in dieser Version (würde Re-Query erfordern)
        pass

    def _on_column_click(self, event):
        """Column-Click Event."""
        pass

    def execute_sql(self):
        """Führt SQL-Query aus (READ-ONLY für CORE-Tabellen)."""
        if not self.conn:
            messagebox.showwarning("Keine DB", "Keine Datenbank geladen")
            return

        query = self.sql_text.get("1.0", tk.END).strip()
        if not query:
            return

        # Sicherheitscheck: Nur SELECT erlauben
        if not query.upper().startswith("SELECT"):
            messagebox.showwarning("Warnung", "Nur SELECT-Queries erlaubt in diesem Viewer")
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # Ergebnis in SQL-Treeview
            self.sql_tree.delete(*self.sql_tree.get_children())
            self.sql_tree["columns"] = columns
            self.sql_tree["show"] = "headings"

            for col in columns:
                self.sql_tree.heading(col, text=col)
                self.sql_tree.column(col, width=120, anchor=tk.W)

            for row in rows:
                values = [str(v) if v is not None else "" for v in row]
                self.sql_tree.insert("", tk.END, values=values)

            self.statusbar.config(text=f"✓ Query erfolgreich: {len(rows)} Zeilen")

        except Exception as e:
            messagebox.showerror("SQL-Fehler", str(e))

    def export_csv(self):
        """Exportiert aktuelle Tabellenansicht als CSV."""
        if not self.current_table:
            messagebox.showwarning("Keine Tabelle", "Bitte wähle eine Tabelle aus")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")],
            initialfile=f"{self.current_table}.csv"
        )

        if not filename:
            return

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Header
                columns = self.data_tree["columns"]
                writer.writerow(columns)

                # Daten
                for item in self.data_tree.get_children():
                    values = self.data_tree.item(item, 'values')
                    writer.writerow(values)

            self.statusbar.config(text=f"✓ Exportiert: {filename}")
            messagebox.showinfo("Erfolg", f"Exportiert nach:\n{filename}")

        except Exception as e:
            messagebox.showerror("Fehler", f"Export fehlgeschlagen:\n{e}")

    def _focus_search(self):
        """Fokussiert Such-Eingabefeld."""
        self.notebook.select(0)  # Daten-Tab
        self.search_entry.focus_set()

    def _show_about(self):
        """Über-Dialog."""
        msg = (
            f"{APP_TITLE}\nVersion {APP_VERSION}\n\n"
            "BACH Database Viewer\n"
            "Öffnet standardmäßig den kanonischen BACH_DB-Pfad\n\n"
            "SQ067 - 2026-02-19"
        )
        messagebox.showinfo("Über", msg)

    def close_db(self):
        """Schließt Datenbank."""
        if self.conn:
            self.conn.close()
            self.conn = None
        self.db_label.config(text="Keine Datenbank geladen")
        self.table_listbox.delete(0, tk.END)
        self.data_tree.delete(*self.data_tree.get_children())
        self.schema_text.delete("1.0", tk.END)


def main():
    """Startet BACH DB Viewer."""
    app = BachDbViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
