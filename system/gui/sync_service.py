# SPDX-License-Identifier: MIT
"""
BACH GUI Sync Service - Synchronisiert TXT-Dateien mit Datenbank

Teil von Phase 4.3 GUI Live-Updates (ROADMAP Task GUI_002)

Funktionen:
- TXT -> DB: Erkennt Änderungen in user/*.txt und aktualisiert DB
- DB -> TXT: Optional - Exportiert DB-Änderungen zurück zu TXT

Verwendung mit file_watcher.py für automatische Synchronisation.
"""

import os
import sqlite3
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# BACH Root-Verzeichnis
BACH_ROOT = Path(__file__).parent.parent
DB_PATH = BACH_ROOT / 'data' / 'bach.db'


class SyncService:
    """
    Synchronisiert TXT-Dateien mit der BACH-Datenbank.
    
    Unterstützte Sync-Mappings:
    - user/steuer/*.txt -> steuer_belege/steuer_posten Tabellen
    - memory/notes.txt -> memory_working Tabelle (optional)
    """
    
    def __init__(self, db_path: Path = None):
        """
        Args:
            db_path: Pfad zur SQLite-Datenbank (default: data/bach.db)
        """
        self.db_path = db_path or DB_PATH
        self._content_hashes: Dict[str, str] = {}  # path -> hash für Change Detection
        
        # Sync-Mappings: TXT-Pattern -> (DB-Tabelle, Parser-Funktion)
        self.sync_mappings = {
            'user/steuer/belege/*.txt': ('steuer_belege', self._parse_beleg_txt),
            'user/steuer/listen/*.txt': ('steuer_posten', self._parse_posten_txt),
        }
    
    def _get_db_connection(self) -> sqlite3.Connection:
        """Erstellt eine DB-Verbindung."""
        return sqlite3.connect(str(self.db_path))
    
    def _compute_hash(self, content: str) -> str:
        """Berechnet MD5-Hash für Change Detection."""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _has_changed(self, path: str, content: str) -> bool:
        """Prüft ob Dateiinhalt sich geändert hat."""
        new_hash = self._compute_hash(content)
        old_hash = self._content_hashes.get(path)
        
        if old_hash != new_hash:
            self._content_hashes[path] = new_hash
            return True
        return False
    
    # ============== PARSER FUNKTIONEN ==============
    
    def _parse_beleg_txt(self, content: str) -> List[Dict]:
        """
        Parst Beleg-TXT-Datei.
        
        Erwartetes Format:
        DATUM: 2026-01-15
        BETRAG: 49.99
        BESCHREIBUNG: Büromaterial
        KATEGORIE: Werbungskosten
        ---
        """
        belege = []
        current = {}
        
        for line in content.split('\n'):
            line = line.strip()
            
            if line == '---':
                if current:
                    belege.append(current)
                    current = {}
                continue
            
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'datum':
                    current['datum'] = value
                elif key == 'betrag':
                    try:
                        current['betrag'] = float(value.replace(',', '.'))
                    except ValueError:
                        current['betrag'] = 0.0
                elif key == 'beschreibung':
                    current['beschreibung'] = value
                elif key == 'kategorie':
                    current['kategorie'] = value
        
        # Letzten Eintrag nicht vergessen
        if current:
            belege.append(current)
        
        return belege
    
    def _parse_posten_txt(self, content: str) -> List[Dict]:
        """
        Parst Posten-TXT-Datei.
        
        Erwartetes Format:
        TITEL: Arbeitsmittel Computer
        BETRAG: 899.00
        LISTE: W
        STATUS: OFFEN
        ---
        """
        posten = []
        current = {}
        
        for line in content.split('\n'):
            line = line.strip()
            
            if line == '---':
                if current:
                    posten.append(current)
                    current = {}
                continue
            
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'titel':
                    current['titel'] = value
                elif key == 'betrag':
                    try:
                        current['betrag'] = float(value.replace(',', '.'))
                    except ValueError:
                        current['betrag'] = 0.0
                elif key == 'liste':
                    current['liste'] = value
                elif key == 'status':
                    current['status'] = value
        
        if current:
            posten.append(current)
        
        return posten
    
    # ============== SYNC FUNKTIONEN ==============
    
    def sync_file_to_db(self, file_path: str) -> Tuple[bool, str]:
        """
        Synchronisiert eine TXT-Datei zur Datenbank.
        
        Args:
            file_path: Absoluter Pfad zur TXT-Datei
            
        Returns:
            (success, message)
        """
        try:
            path = Path(file_path)
            
            if not path.exists():
                return False, f"Datei nicht gefunden: {file_path}"
            
            if path.suffix != '.txt':
                return False, f"Keine TXT-Datei: {file_path}"
            
            # Datei lesen
            content = path.read_text(encoding='utf-8')
            
            # Change Detection
            if not self._has_changed(file_path, content):
                return True, "Keine Änderungen erkannt"
            
            # Mapping finden
            rel_path = str(path.relative_to(BACH_ROOT)).replace('\\', '/')
            
            for pattern, (table, parser) in self.sync_mappings.items():
                if self._matches_pattern(rel_path, pattern):
                    data = parser(content)
                    if data:
                        self._upsert_to_db(table, data, source_file=rel_path)
                        return True, f"{len(data)} Einträge nach {table} synchronisiert"
                    else:
                        return True, "Keine Daten zum Synchronisieren"
            
            return False, f"Kein Sync-Mapping für: {rel_path}"
            
        except Exception as e:
            logger.error(f"Sync-Fehler: {e}")
            return False, f"Fehler: {str(e)}"
    
    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Prüft ob Pfad zu Pattern passt (einfaches Glob-Matching)."""
        import fnmatch
        return fnmatch.fnmatch(path, pattern)
    
    def _upsert_to_db(self, table: str, data: List[Dict], source_file: str = None):
        """
        Fügt Daten in DB ein oder aktualisiert sie.
        
        Hinweis: Dies ist ein einfaches Insert. Für echtes Upsert
        müsste die Tabelle einen eindeutigen Schlüssel haben.
        """
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        try:
            for item in data:
                # Füge source_file hinzu für Tracking
                if source_file:
                    item['source_file'] = source_file
                item['synced_at'] = datetime.now().isoformat()
                
                columns = ', '.join(item.keys())
                placeholders = ', '.join(['?' for _ in item])
                
                # INSERT OR REPLACE für einfaches Upsert
                sql = f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})"
                
                try:
                    cursor.execute(sql, list(item.values()))
                except sqlite3.OperationalError as e:
                    # Tabelle oder Spalte existiert nicht
                    logger.warning(f"DB-Fehler bei {table}: {e}")
            
            conn.commit()
            
        finally:
            conn.close()
    
    # ============== DB -> TXT EXPORT ==============
    
    def export_db_to_txt(self, table: str, output_path: str) -> Tuple[bool, str]:
        """
        Exportiert DB-Tabelle zu TXT-Datei.
        
        Args:
            table: Name der DB-Tabelle
            output_path: Zielpfad für TXT-Datei
            
        Returns:
            (success, message)
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            
            conn.close()
            
            if not rows:
                return True, "Keine Daten zum Exportieren"
            
            # Formatiere als TXT
            lines = []
            for row in rows:
                for col, val in zip(columns, row):
                    if val is not None:
                        lines.append(f"{col.upper()}: {val}")
                lines.append("---")
            
            Path(output_path).write_text('\n'.join(lines), encoding='utf-8')
            return True, f"{len(rows)} Einträge exportiert"
            
        except Exception as e:
            logger.error(f"Export-Fehler: {e}")
            return False, f"Fehler: {str(e)}"


# Singleton-Instanz
_sync_instance: Optional[SyncService] = None


def get_sync_service() -> SyncService:
    """Gibt die globale SyncService-Instanz zurück."""
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = SyncService()
    return _sync_instance


def on_file_change(event_type: str, file_path: str, file_type: str):
    """
    Callback für file_watcher.py Integration.
    
    Verwendung in server.py:
        from gui.file_watcher import init_watcher
        from gui.sync_service import on_file_change
        
        watcher = init_watcher(on_file_change)
        watcher.start()
    """
    if file_type != 'text':
        return
    
    if event_type in ('modified', 'created'):
        service = get_sync_service()
        success, message = service.sync_file_to_db(file_path)
        if success:
            logger.info(f"Sync: {message}")
        elif "Kein Sync-Mapping" in message:
            logger.debug(f"Sync übersprungen: {message}")
        else:
            logger.warning(f"Sync fehlgeschlagen: {message}")


# CLI-Test
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    service = SyncService()
    
    # Test: Parse Beispiel-Content
    test_content = """
DATUM: 2026-01-15
BETRAG: 49.99
BESCHREIBUNG: Büromaterial
KATEGORIE: Werbungskosten
---
DATUM: 2026-01-20
BETRAG: 150.00
BESCHREIBUNG: Fachliteratur
KATEGORIE: Fortbildung
"""
    
    belege = service._parse_beleg_txt(test_content)
    print(f"Geparste Belege: {len(belege)}")
    for b in belege:
        print(f"  - {b}")
