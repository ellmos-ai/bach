# SPDX-License-Identifier: MIT
"""
Scan Handler - Scanner-Verwaltung
=================================

DEPRECATED: Dieser Handler bleibt fuer Backward-Compatibility.
            Neu: bach ati scan (ATI Agent)

bach scan run              Scanner starten
bach scan status           Letzten Scan-Status anzeigen
bach scan tasks [--tool X] Gescannte Tasks anzeigen
bach scan tools            Registrierte Tools anzeigen
"""
import sys
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class ScanHandler(BaseHandler):
    """Handler fuer scan Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.data_dir = base_path / "data"
        self.user_db = self.data_dir / "user.db"
        self.scanner_dir = base_path / "scanner"
    
    @property
    def profile_name(self) -> str:
        return "scan"
    
    @property
    def target_file(self) -> Path:
        return self.scanner_dir
    
    def get_operations(self) -> dict:
        return {
            "run": "Scanner starten",
            "status": "Letzten Scan-Status anzeigen",
            "tasks": "Gescannte Tasks anzeigen (--tool X fuer Filter)",
            "tools": "Registrierte Tools anzeigen",
            "dir": "Verzeichnis scannen (bach scan dir PATH)"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "run":
            return self._run_scan(dry_run)
        elif operation == "status":
            return self._show_status()
        elif operation == "tasks":
            tool_filter = None
            if "--tool" in args:
                idx = args.index("--tool")
                if idx + 1 < len(args):
                    tool_filter = args[idx + 1]
            return self._show_tasks(tool_filter)
        elif operation == "tools":
            return self._show_tools()
        elif operation == "dir":
            # bach scan dir PATH
            if not args:
                return (False, "[ERROR] Pfad fehlt. Nutzung: bach scan dir PATH")
            return self._scan_directory(args[0], dry_run)
        else:
            return self._show_status()
    
    def _run_scan(self, dry_run: bool) -> tuple:
        """Fuehrt Scanner aus."""
        if dry_run:
            return (True, "[DRY-RUN] Wuerde Scanner starten")
        
        try:
            # ATI-Scanner verwenden (scanner/task_scanner.py ist deprecated)
            sys.path.insert(0, str(self.base_path))
            from agents.ati.scanner.task_scanner import TaskScanner

            scanner = TaskScanner(self.user_db)
            result = scanner.scan_all()

            output = [
                "[OK] ATI-Scan abgeschlossen",
                f"    Tools gescannt: {result['tools_scanned']}",
                f"    Tasks gefunden: {result['tasks_found']}",
                f"    Neu: {result['tasks_new']}",
                f"    Aktualisiert: {result['tasks_updated']}",
                "",
                "[HINWEIS] 'bach scan' ist deprecated -> verwende: bach ati scan"
            ]
            
            if result['errors']:
                output.append(f"    Fehler: {len(result['errors'])}")
            
            return (True, "\n".join(output))
            
        except Exception as e:
            return (False, f"[ERROR] Scan fehlgeschlagen: {e}")
    
    def _show_status(self) -> tuple:
        """Zeigt Status des letzten Scans."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.user_db)
            
            # Letzter Scan
            last_scan = conn.execute("""
                SELECT started_at, finished_at, duration_seconds, 
                       tools_scanned, tasks_found, tasks_new, tasks_updated
                FROM scan_runs 
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            
            if not last_scan:
                conn.close()
                return (True, "[INFO] Noch kein Scan durchgefuehrt")
            
            # Gesamtstatistik
            total_tasks = conn.execute("SELECT COUNT(*) FROM scanned_tasks").fetchone()[0]
            total_tools = conn.execute("SELECT COUNT(*) FROM tool_registry").fetchone()[0]
            open_tasks = conn.execute(
                "SELECT COUNT(*) FROM scanned_tasks WHERE status IN ('offen', 'in_arbeit')"
            ).fetchone()[0]
            
            conn.close()
            
            output = [
                "=== SCAN STATUS ===",
                "",
                f"Letzter Scan: {last_scan[0]}",
                f"Dauer: {last_scan[2]:.2f}s" if last_scan[2] else "Dauer: -",
                f"Tools gescannt: {last_scan[3]}",
                f"Tasks gefunden: {last_scan[4]}",
                "",
                "--- Gesamt ---",
                f"Registrierte Tools: {total_tools}",
                f"Gescannte Tasks: {total_tasks}",
                f"Offene Tasks: {open_tasks}"
            ]
            
            return (True, "\n".join(output))
            
        except Exception as e:
            return (False, f"[ERROR] Status-Abfrage fehlgeschlagen: {e}")
    
    def _show_tasks(self, tool_filter: str = None) -> tuple:
        """Zeigt gescannte Tasks."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.user_db)
            
            if tool_filter:
                tasks = conn.execute("""
                    SELECT tool_name, task_text, aufwand, status, priority_score
                    FROM scanned_tasks 
                    WHERE tool_name LIKE ? AND status IN ('offen', 'in_arbeit')
                    ORDER BY priority_score DESC
                    LIMIT 20
                """, (f"%{tool_filter}%",)).fetchall()
            else:
                tasks = conn.execute("""
                    SELECT tool_name, task_text, aufwand, status, priority_score
                    FROM scanned_tasks 
                    WHERE status IN ('offen', 'in_arbeit')
                    ORDER BY priority_score DESC
                    LIMIT 20
                """).fetchall()
            
            conn.close()
            
            if not tasks:
                return (True, "[INFO] Keine offenen Tasks gefunden")
            
            output = ["=== GESCANNTE TASKS ===", ""]
            
            for tool, text, aufwand, status, prio in tasks:
                # Text kuerzen
                short_text = text[:60] + "..." if len(text) > 60 else text
                output.append(f"[{aufwand[0].upper()}] {tool}: {short_text}")
            
            output.append(f"\nGesamt: {len(tasks)} Tasks angezeigt")
            
            return (True, "\n".join(output))
            
        except Exception as e:
            return (False, f"[ERROR] Task-Abfrage fehlgeschlagen: {e}")
    
    def _show_tools(self) -> tuple:
        """Zeigt registrierte Tools."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.user_db)
            
            tools = conn.execute("""
                SELECT name, status, task_count, last_scan
                FROM tool_registry 
                ORDER BY task_count DESC
                LIMIT 30
            """).fetchall()
            
            conn.close()
            
            if not tools:
                return (True, "[INFO] Keine Tools registriert")
            
            output = ["=== REGISTRIERTE TOOLS ===", ""]
            
            for name, status, task_count, last_scan in tools:
                scan_date = last_scan[:10] if last_scan else "-"
                output.append(f"  {name}: {task_count} Tasks ({status}) - {scan_date}")
            
            output.append(f"\nGesamt: {len(tools)} Tools")
            
            return (True, "\n".join(output))
            
        except Exception as e:
            return (False, f"[ERROR] Tool-Abfrage fehlgeschlagen: {e}")
    
    def _scan_directory(self, path: str, dry_run: bool) -> tuple:
        """Scannt ein beliebiges Verzeichnis mit dirscan.py."""
        from pathlib import Path as P
        
        target_path = P(path)
        if not target_path.exists():
            return (False, f"[ERROR] Pfad existiert nicht: {path}")
        if not target_path.is_dir():
            return (False, f"[ERROR] Kein Verzeichnis: {path}")
        
        if dry_run:
            return (True, f"[DRY-RUN] Wuerde scannen: {target_path}")
        
        try:
            # DirectoryScanner importieren
            sys.path.insert(0, str(self.base_path / "tools"))
            from dirscan import DirectoryScanner
            
            scanner = DirectoryScanner(target_path)
            current = scanner.scan()
            
            # Statistiken
            dir_count = len(current.get("directories", []))
            file_count = len(current.get("files", {}))
            
            output = [
                f"=== DIRECTORY SCAN: {target_path.name} ===",
                "",
                f"Gescannt: {current['timestamp'][:19]}",
                f"Verzeichnisse: {dir_count}",
                f"Dateien: {file_count}",
                ""
            ]
            
            # Top-Level Verzeichnisse
            top_dirs = [d for d in current.get("directories", []) if "/" not in d and "\\" not in d]
            if top_dirs[:10]:
                output.append("--- Unterordner ---")
                for d in sorted(top_dirs)[:10]:
                    output.append(f"  📁 {d}")
                if len(top_dirs) > 10:
                    output.append(f"  ... und {len(top_dirs) - 10} weitere")
                output.append("")
            
            # Dateien im Root
            root_files = [f for f in current.get("files", {}).keys() if "/" not in f and "\" not in f]
            if root_files[:10]:
                output.append("--- Dateien (root) ---")
                for f in sorted(root_files)[:10]:
                    size = current["files"][f].get("size", 0)
                    size_str = f"{size:,}".replace(",", ".") + " B"
                    if size > 1024:
                        size_str = f"{size/1024:.1f} KB"
                    if size > 1024*1024:
                        size_str = f"{size/1024/1024:.1f} MB"
                    output.append(f"  📄 {f} ({size_str})")
                if len(root_files) > 10:
                    output.append(f"  ... und {len(root_files) - 10} weitere")
            
            return (True, "\n".join(output))
            
        except Exception as e:
            return (False, f"[ERROR] Directory-Scan fehlgeschlagen: {e}")
