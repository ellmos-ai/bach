# SPDX-License-Identifier: MIT
"""
Tokens Handler - Token-Tracking
===============================

--tokens status    Aktueller Verbrauch
--tokens today     Heutiger Verbrauch
--tokens week      Wochenverbrauch
--tokens report    Detaillierter Bericht
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class TokensHandler(BaseHandler):
    """Handler fuer --tokens Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "tokens"
    
    @property
    def target_file(self) -> Path:
        return self.db_path
    
    def get_operations(self) -> dict:
        return {
            "status": "Aktueller Token-Verbrauch",
            "today": "Heutiger Verbrauch",
            "week": "Wochenverbrauch",
            "report": "Detaillierter Bericht"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.db_path.exists():
            return False, "Datenbank nicht gefunden"
        
        if operation == "today":
            return self._today()
        elif operation == "week":
            return self._week()
        elif operation == "report":
            return self._report()
        else:
            return self._status()
    
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _status(self) -> tuple:
        """Token-Status."""
        results = ["TOKEN STATUS", "=" * 40]
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Heute
        cursor.execute("""
            SELECT SUM(tokens_total) as total, SUM(cost_eur) as cost
            FROM monitor_tokens WHERE date(timestamp) = date('now')
        """)
        today = cursor.fetchone()
        
        # Woche
        cursor.execute("""
            SELECT SUM(tokens_total) as total, SUM(cost_eur) as cost
            FROM monitor_tokens WHERE timestamp >= date('now', '-7 days')
        """)
        week = cursor.fetchone()
        
        # Monat
        cursor.execute("""
            SELECT SUM(tokens_total) as total, SUM(cost_eur) as cost
            FROM monitor_tokens WHERE timestamp >= date('now', '-30 days')
        """)
        month = cursor.fetchone()
        
        results.append(f"Heute:  {today['total'] or 0:>10,} Tokens ({today['cost'] or 0:.2f} EUR)")
        results.append(f"Woche:  {week['total'] or 0:>10,} Tokens ({week['cost'] or 0:.2f} EUR)")
        results.append(f"Monat:  {month['total'] or 0:>10,} Tokens ({month['cost'] or 0:.2f} EUR)")
        
        conn.close()
        return True, "\n".join(results)
    
    def _today(self) -> tuple:
        """Heutiger Verbrauch detailliert."""
        results = ["HEUTE", "=" * 40]
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT timestamp, model, tokens_input, tokens_output, cost_eur
            FROM monitor_tokens 
            WHERE date(timestamp) = date('now')
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()
        
        if not rows:
            results.append("Keine Eintraege heute.")
        else:
            for row in rows:
                time = row['timestamp'].split("T")[1][:5] if "T" in row['timestamp'] else row['timestamp'][-8:-3]
                results.append(f"  {time} {row['model'][:15]:<15} {row['tokens_input']:>6}+{row['tokens_output']:<6} {row['cost_eur']:.3f}EUR")
        
        conn.close()
        return True, "\n".join(results)
    
    def _week(self) -> tuple:
        """Wochenverbrauch nach Tag."""
        results = ["LETZTE 7 TAGE", "=" * 40]
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT date(timestamp) as day, 
                   SUM(tokens_total) as total, 
                   SUM(cost_eur) as cost,
                   COUNT(*) as calls
            FROM monitor_tokens 
            WHERE timestamp >= date('now', '-7 days')
            GROUP BY date(timestamp)
            ORDER BY day DESC
        """)
        rows = cursor.fetchall()
        
        if not rows:
            results.append("Keine Eintraege.")
        else:
            results.append(f"  {'Tag':<12} {'Tokens':>10} {'Kosten':>8} {'Calls':>6}")
            results.append("  " + "-" * 38)
            for row in rows:
                results.append(f"  {row['day']:<12} {row['total']:>10,} {row['cost']:>7.2f}EUR {row['calls']:>6}")
        
        conn.close()
        return True, "\n".join(results)
    
    def _report(self) -> tuple:
        """Detaillierter Bericht."""
        results = ["TOKEN REPORT", "=" * 40]
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Nach Model
        results.append("\nNach Model:")
        cursor.execute("""
            SELECT model, SUM(tokens_total) as total, SUM(cost_eur) as cost
            FROM monitor_tokens 
            WHERE timestamp >= date('now', '-30 days')
            GROUP BY model
            ORDER BY total DESC
        """)
        for row in cursor.fetchall():
            results.append(f"  {row['model']:<25} {row['total']:>10,} ({row['cost']:.2f}EUR)")
        
        # Preise
        results.append("\nAktuelle Preise:")
        cursor.execute("SELECT model, input_price, output_price FROM monitor_pricing")
        for row in cursor.fetchall():
            results.append(f"  {row['model']:<25} In: {row['input_price']:.4f} Out: {row['output_price']:.4f}")
        
        conn.close()
        return True, "\n".join(results)
