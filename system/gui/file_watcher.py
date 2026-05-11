# SPDX-License-Identifier: MIT
"""
BACH GUI File Watcher - Überwacht Dateiänderungen für Live-Updates

Teil von Phase 4.3 GUI Live-Updates (ROADMAP Task GUI_001a/b)

Überwacht:
- data/bach.db (SQLite-Datenbank)
- user/*.txt (User-Dateien)

Meldet Änderungen via Callback an server.py

Abhängigkeit: pip install watchdog
"""

import os
import time
import logging
from pathlib import Path
from typing import Callable, Optional, Set
from threading import Thread, Event

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object
    FileSystemEvent = None

logger = logging.getLogger(__name__)

# BACH Root-Verzeichnis (relativ zu diesem Modul)
BACH_ROOT = Path(__file__).parent.parent


class BachFileHandler(FileSystemEventHandler):
    """Handler für Dateiänderungen in BACH-Verzeichnissen."""
    
    def __init__(self, callback: Callable[[str, str, str], None], 
                 watched_extensions: Set[str] = None,
                 debounce_seconds: float = 0.5):
        """
        Args:
            callback: Funktion(event_type, file_path, file_type) die bei Änderung aufgerufen wird
            watched_extensions: Set von Dateiendungen (z.B. {'.db', '.txt', '.json'})
            debounce_seconds: Wartezeit für Debouncing (verhindert Mehrfach-Events)
        """
        super().__init__()
        self.callback = callback
        self.watched_extensions = watched_extensions or {'.db', '.txt', '.json', '.md'}
        self.debounce_seconds = debounce_seconds
        self._last_events = {}  # path -> timestamp für Debouncing
    
    _IGNORED_DIRS = {'logs', '__pycache__', 'backups', '.git'}

    def _should_process(self, path: str) -> bool:
        """Prüft ob Event verarbeitet werden soll (Extension + Debouncing)."""
        path_parts = Path(path).parts
        if any(part in self._IGNORED_DIRS for part in path_parts):
            return False
        ext = Path(path).suffix.lower()
        if ext not in self.watched_extensions:
            return False
        
        # Debouncing: Ignoriere Events die zu schnell hintereinander kommen
        now = time.time()
        last_time = self._last_events.get(path, 0)
        if now - last_time < self.debounce_seconds:
            return False
        
        self._last_events[path] = now
        return True
    
    def _get_file_type(self, path: str) -> str:
        """Bestimmt den BACH-relevanten Dateityp."""
        path_obj = Path(path)
        
        if path_obj.name == 'bach.db':
            return 'database'
        elif path_obj.suffix == '.txt':
            return 'text'
        elif path_obj.suffix == '.json':
            return 'json'
        elif path_obj.suffix == '.md':
            return 'markdown'
        else:
            return 'other'
    
    def on_modified(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if self._should_process(event.src_path):
            file_type = self._get_file_type(event.src_path)
            logger.debug(f"File modified: {event.src_path} ({file_type})")
            self.callback('modified', event.src_path, file_type)
    
    def on_created(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if self._should_process(event.src_path):
            file_type = self._get_file_type(event.src_path)
            logger.debug(f"File created: {event.src_path} ({file_type})")
            self.callback('created', event.src_path, file_type)
    
    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if self._should_process(event.src_path):
            file_type = self._get_file_type(event.src_path)
            logger.debug(f"File deleted: {event.src_path} ({file_type})")
            self.callback('deleted', event.src_path, file_type)


class BachFileWatcher:
    """
    Haupt-Klasse für BACH File Watching.
    
    Verwendung:
        def on_change(event_type, path, file_type):
            print(f"{event_type}: {path}")
        
        watcher = BachFileWatcher(on_change)
        watcher.start()
        # ... später ...
        watcher.stop()
    """
    
    def __init__(self, callback: Callable[[str, str, str], None]):
        """
        Args:
            callback: Funktion die bei Dateiänderungen aufgerufen wird
                     Signatur: callback(event_type, file_path, file_type)
                     event_type: 'modified', 'created', 'deleted'
                     file_type: 'database', 'text', 'json', 'markdown', 'other'
        """
        if not WATCHDOG_AVAILABLE:
            raise ImportError(
                "watchdog nicht installiert. Bitte ausführen: pip install watchdog"
            )
        
        self.callback = callback
        self._observer: Optional[Observer] = None
        self._stop_event = Event()
        self._running = False
    
    def _get_watch_paths(self) -> list:
        """Gibt die zu überwachenden Pfade zurück."""
        paths = []
        
        # data/ Verzeichnis (enthält bach.db)
        data_path = BACH_ROOT / 'data'
        if data_path.exists():
            paths.append(str(data_path))
        
        # user/ Verzeichnis (User-Dateien)
        user_path = BACH_ROOT / 'user'
        if user_path.exists():
            paths.append(str(user_path))
        
        return paths
    
    def start(self) -> bool:
        """
        Startet den File Watcher.
        
        Returns:
            True wenn erfolgreich gestartet, False bei Fehler
        """
        if self._running:
            logger.warning("File Watcher läuft bereits")
            return True
        
        try:
            self._observer = Observer()
            handler = BachFileHandler(self.callback)
            
            watch_paths = self._get_watch_paths()
            if not watch_paths:
                logger.error("Keine zu überwachenden Pfade gefunden")
                return False
            
            for path in watch_paths:
                self._observer.schedule(handler, path, recursive=True)
                logger.info(f"Überwache: {path}")
            
            self._observer.start()
            self._running = True
            self._stop_event.clear()
            
            logger.info(f"File Watcher gestartet ({len(watch_paths)} Pfade)")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Starten des File Watchers: {e}")
            return False
    
    def stop(self):
        """Stoppt den File Watcher."""
        if not self._running:
            return
        
        self._stop_event.set()
        
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        
        self._running = False
        logger.info("File Watcher gestoppt")
    
    @property
    def is_running(self) -> bool:
        """Gibt zurück ob der Watcher läuft."""
        return self._running


# Singleton-Instanz für Server-Integration
_watcher_instance: Optional[BachFileWatcher] = None


def get_watcher() -> Optional[BachFileWatcher]:
    """Gibt die globale Watcher-Instanz zurück."""
    return _watcher_instance


def init_watcher(callback: Callable[[str, str, str], None]) -> BachFileWatcher:
    """
    Initialisiert den globalen File Watcher.
    
    Wird von server.py beim Start aufgerufen.
    """
    global _watcher_instance
    
    if _watcher_instance is not None:
        _watcher_instance.stop()
    
    _watcher_instance = BachFileWatcher(callback)
    return _watcher_instance


# CLI-Test
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    def test_callback(event_type: str, path: str, file_type: str):
        print(f"[{event_type.upper()}] {file_type}: {path}")
    
    if not WATCHDOG_AVAILABLE:
        print("ERROR: watchdog nicht installiert")
        print("Installieren mit: pip install watchdog")
        exit(1)
    
    watcher = BachFileWatcher(test_callback)
    if watcher.start():
        print("File Watcher läuft. Drücke Ctrl+C zum Beenden.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nBeende...")
        finally:
            watcher.stop()
    else:
        print("Fehler beim Starten des File Watchers")
