# SPDX-License-Identifier: MIT
"""
BACH Data Analysis Handler
==========================
CLI-Handler fuer Datenanalyse-Funktionen.

Befehle:
    bach data load <path>           Datei laden und Infos anzeigen
    bach data describe <path>       Deskriptive Statistik
    bach data head <path> [--rows]  Erste Zeilen anzeigen
    bach data corr <path>           Korrelationsmatrix
    bach data chart <path>          Chart erstellen (geplant)
"""

import sys
from pathlib import Path
from .base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("report-forge")
class DataAnalysisHandler(BaseHandler):
    """Handler fuer bach data Befehle"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.data_dir = base_path / "user" / "data-analysis"
        self.input_dir = self.data_dir / "input"
        self.output_dir = self.data_dir / "output"
        self.charts_dir = self.data_dir / "charts"
        
        # Verzeichnisse erstellen falls noetig
        for d in [self.data_dir, self.input_dir, self.output_dir, self.charts_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    @property
    def profile_name(self) -> str:
        return "data"
    
    @property
    def target_file(self) -> Path:
        return self.data_dir
    
    def get_operations(self) -> dict:
        return {
            "load": "Datei laden und Info anzeigen",
            "describe": "Deskriptive Statistik (mean, std, min, max)",
            "head": "Erste N Zeilen anzeigen (--rows N)",
            "corr": "Korrelationsmatrix numerischer Spalten",
            "chart": "Chart erstellen (bar, line, pie) - geplant",
            "list": "Dateien im input/ Ordner anzeigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        """Verarbeitet Data-Befehle"""
        
        if operation == "list":
            return self._list_files()
        
        if operation == "load":
            if not args:
                return False, "[FEHLER] Pfad zur Datei angeben: bach data load <pfad>"
            return self._load_data(args[0])
        
        if operation == "describe":
            if not args:
                return False, "[FEHLER] Pfad zur Datei angeben: bach data describe <pfad>"
            return self._describe_data(args[0])
        
        if operation == "head":
            if not args:
                return False, "[FEHLER] Pfad zur Datei angeben: bach data head <pfad>"
            rows = 10
            if "--rows" in args:
                idx = args.index("--rows")
                if idx + 1 < len(args):
                    try:
                        rows = int(args[idx + 1])
                    except ValueError:
                        pass
            return self._head_data(args[0], rows)
        
        if operation == "corr":
            if not args:
                return False, "[FEHLER] Pfad zur Datei angeben: bach data corr <pfad>"
            return self._correlation(args[0])
        
        if operation == "chart":
            if not args:
                return False, "[FEHLER] Pfad zur Datei angeben: bach data chart <pfad> --type bar --x col --y col"
            chart_type = "bar"
            x_col = None
            y_col = None
            output_file = None
            # Args parsen
            if "--type" in args:
                idx = args.index("--type")
                if idx + 1 < len(args):
                    chart_type = args[idx + 1]
            if "--x" in args:
                idx = args.index("--x")
                if idx + 1 < len(args):
                    x_col = args[idx + 1]
            if "--y" in args:
                idx = args.index("--y")
                if idx + 1 < len(args):
                    y_col = args[idx + 1]
            if "--output" in args:
                idx = args.index("--output")
                if idx + 1 < len(args):
                    output_file = args[idx + 1]
            return self._create_chart(args[0], chart_type, x_col, y_col, output_file)
        
        return False, f"[FEHLER] Unbekannte Operation: {operation}"
    
    def _ensure_pandas(self):
        """Prueft ob pandas verfuegbar ist"""
        try:
            import pandas as pd
            return True, pd
        except ImportError:
            return False, None
    
    def _resolve_path(self, path_str: str) -> Path:
        """Loest relativen Pfad auf"""
        path = Path(path_str)
        if path.is_absolute():
            return path
        # Suche zuerst im input/ Ordner
        input_path = self.input_dir / path
        if input_path.exists():
            return input_path
        # Sonst relative zu base_path
        return self.base_path / path
    
    def _load_data(self, path_str: str) -> tuple:
        """Laedt Datei und zeigt Basisinfo"""
        ok, pd = self._ensure_pandas()
        if not ok:
            return False, "[FEHLER] pandas nicht installiert. Bitte: pip install pandas"
        
        path = self._resolve_path(path_str)
        if not path.exists():
            return False, f"[FEHLER] Datei nicht gefunden: {path}"
        
        try:
            # Format erkennen
            suffix = path.suffix.lower()
            if suffix in ['.csv', '.txt']:
                df = pd.read_csv(path)
            elif suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(path)
            elif suffix == '.json':
                df = pd.read_json(path)
            else:
                return False, f"[FEHLER] Unbekanntes Format: {suffix}"
            
            # Info zusammenstellen
            output = []
            output.append(f"\n[DATA] Geladen: {path.name}")
            output.append(f"       Groesse: {len(df)} Zeilen x {len(df.columns)} Spalten")
            output.append(f"       Speicher: {df.memory_usage(deep=True).sum() / 1024:.1f} KB")
            output.append("\n[SPALTEN]")
            
            for col in df.columns:
                dtype = str(df[col].dtype)
                nulls = df[col].isnull().sum()
                null_pct = (nulls / len(df) * 100) if len(df) > 0 else 0
                output.append(f"  {col:30} {dtype:15} {nulls} nulls ({null_pct:.1f}%)")
            
            output.append(f"\n[TIPP] Weiter mit: bach data describe \"{path_str}\"")
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[FEHLER] Laden fehlgeschlagen: {e}"
    
    def _describe_data(self, path_str: str) -> tuple:
        """Zeigt deskriptive Statistik"""
        ok, pd = self._ensure_pandas()
        if not ok:
            return False, "[FEHLER] pandas nicht installiert"
        
        path = self._resolve_path(path_str)
        if not path.exists():
            return False, f"[FEHLER] Datei nicht gefunden: {path}"
        
        try:
            suffix = path.suffix.lower()
            if suffix in ['.csv', '.txt']:
                df = pd.read_csv(path)
            elif suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(path)
            else:
                df = pd.read_json(path) if suffix == '.json' else None
                if df is None:
                    return False, f"[FEHLER] Unbekanntes Format: {suffix}"
            
            output = []
            output.append(f"\n[STATISTIK] {path.name}")
            output.append("=" * 60)
            
            desc = df.describe(include='all')
            output.append(desc.to_string())
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[FEHLER] Analyse fehlgeschlagen: {e}"
    
    def _head_data(self, path_str: str, rows: int = 10) -> tuple:
        """Zeigt erste N Zeilen"""
        ok, pd = self._ensure_pandas()
        if not ok:
            return False, "[FEHLER] pandas nicht installiert"
        
        path = self._resolve_path(path_str)
        if not path.exists():
            return False, f"[FEHLER] Datei nicht gefunden: {path}"
        
        try:
            suffix = path.suffix.lower()
            if suffix in ['.csv', '.txt']:
                df = pd.read_csv(path)
            elif suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(path)
            else:
                df = pd.read_json(path) if suffix == '.json' else None
                if df is None:
                    return False, f"[FEHLER] Unbekanntes Format: {suffix}"
            
            output = []
            output.append(f"\n[HEAD] {path.name} (erste {rows} Zeilen)")
            output.append("=" * 60)
            output.append(df.head(rows).to_string())
            
            if len(df) > rows:
                output.append(f"\n... und {len(df) - rows} weitere Zeilen")
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[FEHLER] {e}"
    
    def _correlation(self, path_str: str) -> tuple:
        """Zeigt Korrelationsmatrix"""
        ok, pd = self._ensure_pandas()
        if not ok:
            return False, "[FEHLER] pandas nicht installiert"
        
        path = self._resolve_path(path_str)
        if not path.exists():
            return False, f"[FEHLER] Datei nicht gefunden: {path}"
        
        try:
            suffix = path.suffix.lower()
            if suffix in ['.csv', '.txt']:
                df = pd.read_csv(path)
            elif suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(path)
            else:
                df = pd.read_json(path) if suffix == '.json' else None
                if df is None:
                    return False, f"[FEHLER] Unbekanntes Format: {suffix}"
            
            # Nur numerische Spalten
            numeric_df = df.select_dtypes(include=['number'])
            if numeric_df.empty:
                return False, "[INFO] Keine numerischen Spalten fuer Korrelation gefunden"
            
            output = []
            output.append(f"\n[KORRELATION] {path.name}")
            output.append("=" * 60)
            output.append(numeric_df.corr().round(3).to_string())
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[FEHLER] {e}"
    
    def _list_files(self) -> tuple:
        """Listet Dateien im input/ Ordner"""
        output = []
        output.append(f"\n[DATA] Dateien in {self.input_dir}")
        output.append("=" * 50)
        
        files = list(self.input_dir.glob("*.*"))
        if not files:
            output.append("  (keine Dateien)")
            output.append(f"\n[TIPP] Dateien hierher kopieren: {self.input_dir}")
        else:
            for f in sorted(files):
                size = f.stat().st_size / 1024
                output.append(f"  {f.name:40} {size:8.1f} KB")
        
        return True, "\n".join(output)
    
    def _create_chart(self, path_str: str, chart_type: str, x_col: str, y_col: str, output_file: str = None) -> tuple:
        """Erstellt ein Chart aus den Daten"""
        ok, pd = self._ensure_pandas()
        if not ok:
            return False, "[FEHLER] pandas nicht installiert"
        
        # Matplotlib pruefen
        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt
        except ImportError:
            return False, "[FEHLER] matplotlib nicht installiert. Bitte: pip install matplotlib"
        
        path = self._resolve_path(path_str)
        if not path.exists():
            return False, f"[FEHLER] Datei nicht gefunden: {path}"
        
        # Unterstuetzte Chart-Typen
        valid_types = ['bar', 'line', 'pie', 'scatter', 'hist']
        if chart_type not in valid_types:
            return False, f"[FEHLER] Chart-Typ '{chart_type}' nicht unterstuetzt. Verfuegbar: {', '.join(valid_types)}"
        
        try:
            # Daten laden
            suffix = path.suffix.lower()
            if suffix in ['.csv', '.txt']:
                df = pd.read_csv(path)
            elif suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(path)
            elif suffix == '.json':
                df = pd.read_json(path)
            else:
                return False, f"[FEHLER] Unbekanntes Format: {suffix}"
            
            # Spalten validieren
            if x_col and x_col not in df.columns:
                return False, f"[FEHLER] Spalte '{x_col}' nicht gefunden. Verfuegbar: {', '.join(df.columns)}"
            if y_col and y_col not in df.columns:
                return False, f"[FEHLER] Spalte '{y_col}' nicht gefunden. Verfuegbar: {', '.join(df.columns)}"
            
            # Falls keine Spalten angegeben, erste numerische/kategorische waehlen
            if not x_col:
                x_col = df.columns[0]
            if not y_col and chart_type not in ['pie', 'hist']:
                numeric_cols = df.select_dtypes(include=['number']).columns
                if len(numeric_cols) > 0:
                    y_col = numeric_cols[0] if numeric_cols[0] != x_col else (numeric_cols[1] if len(numeric_cols) > 1 else numeric_cols[0])
                else:
                    return False, "[FEHLER] Keine numerische Spalte fuer Y-Achse gefunden"
            
            # Chart erstellen
            plt.figure(figsize=(10, 6))
            
            if chart_type == 'bar':
                plt.bar(df[x_col], df[y_col])
                plt.xlabel(x_col)
                plt.ylabel(y_col)
                plt.title(f'{y_col} nach {x_col}')
                plt.xticks(rotation=45, ha='right')
            
            elif chart_type == 'line':
                plt.plot(df[x_col], df[y_col], marker='o')
                plt.xlabel(x_col)
                plt.ylabel(y_col)
                plt.title(f'{y_col} ueber {x_col}')
                plt.xticks(rotation=45, ha='right')
            
            elif chart_type == 'scatter':
                plt.scatter(df[x_col], df[y_col], alpha=0.6)
                plt.xlabel(x_col)
                plt.ylabel(y_col)
                plt.title(f'{y_col} vs {x_col}')
            
            elif chart_type == 'pie':
                # Fuer Pie: x_col als Kategorien, zaehlen oder y_col als Werte
                if y_col:
                    plt.pie(df[y_col], labels=df[x_col], autopct='%1.1f%%')
                else:
                    counts = df[x_col].value_counts()
                    plt.pie(counts.values, labels=counts.index, autopct='%1.1f%%')
                plt.title(f'Verteilung von {x_col}')
            
            elif chart_type == 'hist':
                plt.hist(df[x_col].dropna(), bins=20, edgecolor='black')
                plt.xlabel(x_col)
                plt.ylabel('Haeufigkeit')
                plt.title(f'Histogramm von {x_col}')
            
            plt.tight_layout()
            
            # Speichern
            if not output_file:
                output_file = f"chart_{path.stem}_{chart_type}.png"
            output_path = self.charts_dir / output_file
            plt.savefig(output_path, dpi=150)
            plt.close()
            
            return True, f"[CHART] Erstellt: {output_path}\n        Typ: {chart_type}\n        X: {x_col}\n        Y: {y_col if y_col else 'N/A'}"
            
        except Exception as e:
            return False, f"[FEHLER] Chart-Erstellung fehlgeschlagen: {e}"
