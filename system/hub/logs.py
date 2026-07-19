# SPDX-License-Identifier: MIT
"""
Logs Handler - Log-Verwaltung
=============================

--logs status        Übersicht der Log-Dateien
--logs show [n]      Log-Inhalt anzeigen
--logs tail [n]      Letzte n Zeilen (default: 50)
--logs clear         Alte Logs bereinigen
"""
from pathlib import Path
from datetime import datetime
import os
from .base import BaseHandler


class LogsHandler(BaseHandler):
    """Handler fuer --logs Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.logs_dir = base_path / "data" / "logs"
    
    @property
    def profile_name(self) -> str:
        return "logs"
    
    @property
    def target_file(self) -> Path:
        return self.logs_dir
    
    def get_operations(self) -> dict:
        return {
            "status": "Übersicht der Log-Dateien",
            "show": "Log-Inhalt anzeigen",
            "tail": "Letzte n Zeilen",
            "clear": "Alte Logs bereinigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "show" and args:
            return self._show(args[0])
        elif operation == "tail":
            lines = int(args[0]) if args else 50
            return self._tail(lines)
        elif operation == "clear":
            return self._clear(dry_run)
        else:
            return self._status()
    
    def _status(self) -> tuple:
        """Log-Status anzeigen."""
        results = ["LOGS STATUS", "=" * 50]
        
        if not self.logs_dir.exists():
            return True, "Logs-Verzeichnis nicht vorhanden."
        
        # Haupt-Logs
        results.append("\n[HAUPT-LOGS]")
        for log_file in sorted(self.logs_dir.glob("*.txt")):
            size = log_file.stat().st_size
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            size_str = f"{size:,} B" if size < 1024 else f"{size/1024:.1f} KB"
            results.append(f"  {log_file.name:<25} {size_str:>10}  ({mtime})")
        
        # Session-Logs
        sessions_dir = self.logs_dir / "sessions"
        if sessions_dir.exists():
            session_logs = list(sessions_dir.glob("*.txt")) + list(sessions_dir.glob("*.md"))
            results.append(f"\n[SESSION-LOGS] ({len(session_logs)} Dateien)")
            for log_file in sorted(session_logs, reverse=True)[:5]:
                size = log_file.stat().st_size
                size_str = f"{size:,} B" if size < 1024 else f"{size/1024:.1f} KB"
                results.append(f"  {log_file.name:<25} {size_str:>10}")
            if len(session_logs) > 5:
                results.append(f"  ... und {len(session_logs) - 5} weitere")
        
        results.append(f"\n{'=' * 50}")
        results.append("Anzeigen: --logs tail [n]")
        results.append("Details:  --logs show <name>")
        
        return True, "\n".join(results)
    
    def _show(self, name: str) -> tuple:
        """Log-Datei vollständig anzeigen."""
        # Log suchen
        found = None
        for log_file in self.logs_dir.rglob("*"):
            if log_file.is_file() and name.lower() in log_file.name.lower():
                found = log_file
                break
        
        if not found:
            return False, f"Log nicht gefunden: {name}"
        
        results = [f"LOG: {found.name}", "=" * 50]
        
        try:
            content = found.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')
            
            if len(lines) > 100:
                results.append(f"[Zeige letzte 100 von {len(lines)} Zeilen]\n")
                results.extend(lines[-100:])
            else:
                results.extend(lines)
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"
        
        return True, "\n".join(results)
    
    def _tail(self, lines: int = 50) -> tuple:
        """Letzte n Zeilen des Haupt-Logs."""
        auto_log = self._readable_auto_log()
        
        if not auto_log:
            return False, "Kein auto_log.txt gefunden."
        
        results = [f"LOG TAIL (letzte {lines} Zeilen: {auto_log.name})", "=" * 50]
        
        try:
            content = auto_log.read_text(encoding='utf-8', errors='ignore')
            log_lines = content.split('\n')
            results.extend(log_lines[-lines:])
        except Exception as e:
            return False, f"Fehler: {e}"
        
        return True, "\n".join(results)

    def _readable_auto_log(self) -> Path | None:
        """Return the generic auto log or a host-specific fallback if readable."""
        candidates = [self.logs_dir / "auto_log.txt"]
        host = os.environ.get("COMPUTERNAME")
        if host:
            candidates.append(self.logs_dir / f"auto_log-{host}.txt")
        candidates.extend(
            sorted(
                self.logs_dir.glob("auto_log-*.txt"),
                key=lambda path: path.stat().st_mtime if path.exists() else 0,
                reverse=True,
            )
        )

        seen = set()
        for candidate in candidates:
            if candidate in seen or not candidate.exists():
                continue
            seen.add(candidate)
            try:
                candidate.read_text(encoding="utf-8", errors="ignore")
                return candidate
            except OSError:
                continue
        return None
    
    def _clear(self, dry_run: bool) -> tuple:
        """Alte Logs bereinigen (älter als 7 Tage)."""
        from datetime import timedelta
        
        results = ["LOGS BEREINIGEN", "=" * 50]
        cutoff = datetime.now() - timedelta(days=7)
        
        to_delete = []
        sessions_dir = self.logs_dir / "sessions"
        
        if sessions_dir.exists():
            for log_file in sessions_dir.glob("*"):
                if log_file.is_file():
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if mtime < cutoff:
                        to_delete.append(log_file)
        
        if not to_delete:
            results.append("Keine alten Logs zum Löschen.")
        else:
            results.append(f"Gefunden: {len(to_delete)} Dateien älter als 7 Tage")
            
            if dry_run:
                results.append("\n[DRY-RUN] Würde löschen:")
                for f in to_delete[:10]:
                    results.append(f"  {f.name}")
            else:
                for f in to_delete:
                    f.unlink()
                results.append(f"\n[OK] {len(to_delete)} Dateien gelöscht.")
        
        return True, "\n".join(results)
