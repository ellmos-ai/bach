# SPDX-License-Identifier: MIT
"""
BACH_STREAM Feature-Mapping Database - Initial Data Population
"""
import sqlite3
import json
import os
from pathlib import Path

MAPPING_ROOT = Path(
    os.getenv(
        "BACH_FEATURE_MAPPING_ROOT",
        Path.home() / "OneDrive" / ".AI" / "BACH_STREAM" / "MAPPING",
    )
)
DB_PATH = str(MAPPING_ROOT / "feature_mapping.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# ═══════════════════════════════════════════════════════════════════════════
# SYSTEME
# ═══════════════════════════════════════════════════════════════════════════
systems = [
    ("_CHIAH", "system", "3.1", "SKILL.md", r"%SOFTWARE_ROOT%\_CHIAH"),
    ("_BATCH", "system", "2.5", "SKILL.md", r"%SOFTWARE_ROOT%\_BATCH"),
    ("recludOS", "system", "3.3.0", "boot/SKILL.md", r"%ONEDRIVE_AI_ROOT%\BACH\main\system"),
    ("BACH_STREAM", "meta", "1.1", "SKILL.txt", r"%ONEDRIVE_AI_ROOT%\BACH_STREAM"),
    ("AI-Portable", "utility", "1.0", None, r"%ONEDRIVE_AI_ROOT%\AI-Portable"),
    ("Templates", "utility", "1.0", None, r"%ONEDRIVE_AI_ROOT%\Templates"),
    ("recludos-filecommander-mcp", "utility", "1.0", "src/index.ts", r"%ONEDRIVE_AI_ROOT%\recludos-filecommander-mcp"),
]

cursor.executemany("""
    INSERT OR IGNORE INTO systems (name, type, version, entry_point, base_path) 
    VALUES (?, ?, ?, ?, ?)
""", systems)

# ═══════════════════════════════════════════════════════════════════════════
# FEATURE-KATEGORIEN
# ═══════════════════════════════════════════════════════════════════════════
categories = [
    (1, "Task-Management", None, "Aufgabenverwaltung und -tracking"),
    (2, "Memory", None, "Gedächtnis und Kontext-Systeme"),
    (3, "Session-Management", None, "Session-Steuerung und Protokolle"),
    (4, "GUI", None, "Grafische Benutzeroberflächen"),
    (5, "Daemon/Automatisierung", None, "Hintergrund-Prozesse und Automatisierung"),
    (6, "Tools", None, "Utilities und Werkzeuge"),
    (7, "Kommunikation", None, "Messaging und Schnittstellen"),
    (8, "Dokumentation", None, "System-Dokumentation und Regeln"),
    (9, "Agenten/Services", None, "Agenten-Systeme und Services"),
    (10, "Backup/Sicherheit", None, "Backup und Sicherheits-Features"),
    (11, "RAG/Embeddings", None, "Retrieval Augmented Generation"),
    (12, "Datei-Operationen", None, "Datei-System Operationen"),
    
    # Sub-Kategorien
    (21, "Memory-Kurzzeit", 2, "Session-basiertes Gedächtnis"),
    (22, "Memory-Langzeit", 2, "Persistentes Gedächtnis"),
    (23, "Memory-Kontext", 2, "Kontext-Quellen und -Gewichtung"),
]

cursor.executemany("""
    INSERT OR IGNORE INTO feature_categories (id, name, parent_id, description) 
    VALUES (?, ?, ?, ?)
""", categories)

# ═══════════════════════════════════════════════════════════════════════════
# FEATURES
# ═══════════════════════════════════════════════════════════════════════════
features = [
    # Task-Management (1)
    ("task_system", "Task-System", 1, "Grundlegendes Task-Management"),
    ("task_priorities", "Task-Priorisierung", 1, "Prioritäten für Aufgaben"),
    ("task_scanner", "Task-Scanner", 1, "Automatische Task-Erkennung"),
    ("task_delegation", "Task-Delegation", 1, "Aufgaben an andere delegieren"),
    ("task_recurring", "Wiederkehrende Tasks", 1, "Periodische Aufgaben"),
    
    # Memory (2)
    ("memory_short_term", "Kurzzeit-Memory", 21, "Session-basiertes Gedächtnis"),
    ("memory_long_term", "Langzeit-Memory", 22, "Persistentes Gedächtnis"),
    ("memory_context_sources", "Kontext-Quellen", 23, "Gewichtete Kontext-Quellen"),
    ("memory_lessons_learned", "Lessons Learned", 2, "Gelernte Lektionen speichern"),
    ("memory_archive", "Memory-Archivierung", 2, "Archivierung alter Einträge"),
    
    # Session-Management (3)
    ("session_dual_mode", "Dual-Mode Sessions", 3, "Headless und Interactive"),
    ("session_start_protocol", "Start-Protokoll", 3, "Strukturiertes Hochfahren"),
    ("session_shutdown_protocol", "Shutdown-Protokoll", 3, "Strukturiertes Herunterfahren"),
    ("session_crash_recovery", "Crash-Recovery", 3, "Wiederherstellung nach Absturz"),
    ("session_snapshots", "Session-Snapshots", 3, "Zustandssicherung"),
    
    # GUI (4)
    ("gui_main", "Haupt-GUI", 4, "Grafische Hauptoberfläche"),
    ("gui_systray", "System Tray", 4, "Tray-Icon Integration"),
    ("gui_dashboard", "Dashboard", 4, "Übersichts-Dashboard"),
    ("gui_html_viewer", "HTML-Viewer", 4, "HTML-basierte Ansichten"),
    
    # Daemon (5)
    ("daemon_headless", "Headless Daemon", 5, "Hintergrund-Daemon"),
    ("daemon_auto_session", "Auto-Session", 5, "Automatische Sessions"),
    ("daemon_time_budget", "Zeitbudget-System", 5, "Budget für Session-Zeit"),
    
    # Tools (6)
    ("tools_registry", "Tool-Registry", 6, "Registrierung verfügbarer Tools"),
    ("tools_action_hub", "Action Hub", 6, "Zentrales Tool-Interface"),
    ("tools_dev", "DEV-Tools", 6, "Entwickler-Werkzeuge"),
    ("tools_maintenance", "Wartungs-Tools", 6, "System-Wartung"),
    
    # Kommunikation (7)
    ("comm_async_messaging", "Async Messaging", 7, "Asynchrone Nachrichten"),
    ("comm_message_box", "MessageBox", 7, "User-Nachrichtenbox"),
    ("comm_multi_ai", "Multi-AI Support", 7, "Mehrere KIs verbinden"),
    ("comm_contacts", "Contacts Database", 7, "Kontakt-Verwaltung"),
    
    # Dokumentation (8)
    ("docs_system", "System-Dokumentation", 8, "Allgemeine Doku"),
    ("docs_directory_truth", "Directory Truth", 8, "Wahrheitsquelle für Struktur"),
    ("docs_rules", "Regelwerke", 8, "Naming, Format, etc."),
    ("docs_best_practices", "Best Practices", 8, "Bewährte Praktiken"),
    
    # Agenten (9)
    ("agents_system", "Agenten-System", 9, "Multi-Agenten Architektur"),
    ("agents_services", "Services", 9, "Service-Komponenten"),
    ("agents_actors_model", "Akteure-Modell", 9, "Austauschbare Akteure/AI"),
    ("agents_think_modules", "Think-Submodule", 9, "Verschiedene Denkweisen"),
    
    # Backup (10)
    ("backup_auto", "Auto-Backup", 10, "Automatische Sicherung"),
    ("backup_nas", "NAS-Integration", 10, "Netzwerk-Speicher"),
    ("backup_trash", "Papierkorb-System", 10, "Sichere Löschung"),
    
    # RAG (11)
    ("rag_pipeline", "RAG-Pipeline", 11, "Retrieval-Pipeline"),
    ("rag_vector_store", "Vector Store", 11, "Vektor-Datenbank"),
    ("rag_local_models", "Lokale Modelle", 11, "Offline LLMs/Embeddings"),
    
    # Datei-Ops (12)
    ("file_crud", "Datei CRUD", 12, "Create/Read/Update/Delete"),
    ("file_search", "Datei-Suche", 12, "Suche mit Wildcards"),
    ("file_sessions", "Interaktive Sessions", 12, "REPL-Sessions"),
    ("file_process_mgmt", "Prozess-Management", 12, "Prozesse starten/stoppen"),
    
    # Spezial
    ("special_injectors", "Injektoren", 23, "Dynamischer Kontext-Inject"),
    ("special_problems_first", "Problems First", 1, "Proaktive Fehlererkennung"),
    ("special_directory_watcher", "Directory Watcher", 6, "Datei-Änderungs-Überwachung"),
    ("special_ollama", "Ollama-Integration", 11, "Lokale LLM-Anbindung"),
    ("special_transfer_port", "Transfer-Port", 8, "System-Element-Transfer"),
    ("special_mapping", "System-Kartographie", 8, "System-Dokumentation"),
]

cursor.executemany("""
    INSERT OR IGNORE INTO features (canonical_name, display_name, category_id, description) 
    VALUES (?, ?, ?, ?)
""", features)

# ═══════════════════════════════════════════════════════════════════════════
# FEATURE-ALIASE
# ═══════════════════════════════════════════════════════════════════════════

# Hole Feature-IDs
cursor.execute("SELECT id, canonical_name FROM features")
feature_ids = {row[1]: row[0] for row in cursor.fetchall()}

# Hole System-IDs
cursor.execute("SELECT id, name FROM systems")
system_ids = {row[1]: row[0] for row in cursor.fetchall()}

aliases = [
    # Task-System
    (feature_ids["task_system"], "CONNI", "concept", system_ids["_CHIAH"]),
    (feature_ids["task_system"], "tasks.json", "filename", None),
    (feature_ids["task_system"], "tasks_done.json", "filename", None),
    (feature_ids["task_system"], "AUFGABEN.txt", "filename", system_ids["BACH_STREAM"]),
    
    # Memory
    (feature_ids["memory_short_term"], "MEMORY.md", "filename", system_ids["_BATCH"]),
    (feature_ids["memory_short_term"], "short_term.md", "filename", system_ids["recludOS"]),
    (feature_ids["memory_short_term"], "SESSION_MEMORY.txt", "filename", system_ids["BACH_STREAM"]),
    
    (feature_ids["memory_long_term"], "LONGTERM-MEMORY", "foldername", system_ids["_BATCH"]),
    (feature_ids["memory_long_term"], "storage/", "foldername", system_ids["recludOS"]),
    (feature_ids["memory_long_term"], "GLOBAL_KONTEXT.txt", "filename", system_ids["BACH_STREAM"]),
    
    # Session
    (feature_ids["session_start_protocol"], "START-PROTOCOLL.md", "filename", system_ids["_BATCH"]),
    (feature_ids["session_start_protocol"], "bootstrap", "concept", system_ids["recludOS"]),
    
    (feature_ids["session_shutdown_protocol"], "SHUTDOWN-PROTOCOLL.md", "filename", system_ids["_BATCH"]),
    
    # GUI
    (feature_ids["gui_main"], "batch_manager.py", "filename", system_ids["_BATCH"]),
    (feature_ids["gui_main"], "ControlCenter.py", "filename", system_ids["recludOS"]),
    
    (feature_ids["gui_dashboard"], "dashboard.py", "filename", None),
    (feature_ids["gui_dashboard"], "boot-dashboard.html", "filename", system_ids["recludOS"]),
    
    # Daemon
    (feature_ids["daemon_headless"], "session_daemon.py", "filename", system_ids["_BATCH"]),
    (feature_ids["daemon_headless"], "chat_daemon.py", "filename", system_ids["_CHIAH"]),
    
    # Tools
    (feature_ids["tools_action_hub"], "claude_action_hub.py", "filename", system_ids["_BATCH"]),
    (feature_ids["tools_registry"], "python_tools.json", "filename", system_ids["_BATCH"]),
    
    # Special
    (feature_ids["special_directory_watcher"], "directory_watcher", "concept", system_ids["recludOS"]),
    (feature_ids["special_injectors"], "strategy_injector", "concept", system_ids["_CHIAH"]),
    (feature_ids["special_injectors"], "between_injector", "concept", system_ids["_CHIAH"]),
    (feature_ids["special_injectors"], "time_injector", "concept", system_ids["_CHIAH"]),
]

cursor.executemany("""
    INSERT OR IGNORE INTO feature_aliases (feature_id, alias, alias_type, system_id) 
    VALUES (?, ?, ?, ?)
""", aliases)

# ═══════════════════════════════════════════════════════════════════════════
# IMPLEMENTIERUNGEN
# ═══════════════════════════════════════════════════════════════════════════

implementations = [
    # _CHIAH
    (feature_ids["task_system"], system_ids["_CHIAH"], "database/", "sqlite", "implemented"),
    (feature_ids["task_priorities"], system_ids["_CHIAH"], None, None, "implemented"),
    (feature_ids["memory_short_term"], system_ids["_CHIAH"], None, "txt", "implemented"),
    (feature_ids["memory_long_term"], system_ids["_CHIAH"], None, "txt", "implemented"),
    (feature_ids["memory_context_sources"], system_ids["_CHIAH"], None, "python", "implemented"),
    (feature_ids["special_injectors"], system_ids["_CHIAH"], "injectors/", "python", "implemented"),
    (feature_ids["special_problems_first"], system_ids["_CHIAH"], None, "python", "implemented"),
    (feature_ids["comm_contacts"], system_ids["_CHIAH"], "database/", "sqlite", "implemented"),
    (feature_ids["daemon_headless"], system_ids["_CHIAH"], "chat_daemon.py", "python", "partial"),
    
    # _BATCH
    (feature_ids["task_system"], system_ids["_BATCH"], "_data/tasks.json", "json", "implemented"),
    (feature_ids["task_priorities"], system_ids["_BATCH"], None, "json", "implemented"),
    (feature_ids["task_scanner"], system_ids["_BATCH"], "scanner.py", "python", "implemented"),
    (feature_ids["memory_short_term"], system_ids["_BATCH"], "MEMORY.md", "markdown", "implemented"),
    (feature_ids["memory_long_term"], system_ids["_BATCH"], "LONGTERM-MEMORY/", "markdown", "implemented"),
    (feature_ids["session_dual_mode"], system_ids["_BATCH"], None, "python", "implemented"),
    (feature_ids["session_start_protocol"], system_ids["_BATCH"], "SYSTEM/START-PROTOCOLL.md", "markdown", "implemented"),
    (feature_ids["session_shutdown_protocol"], system_ids["_BATCH"], "SYSTEM/SHUTDOWN-PROTOCOLL.md", "markdown", "implemented"),
    (feature_ids["gui_main"], system_ids["_BATCH"], "batch_manager.py", "python", "implemented"),
    (feature_ids["daemon_headless"], system_ids["_BATCH"], "session_daemon.py", "python", "implemented"),
    (feature_ids["daemon_auto_session"], system_ids["_BATCH"], "auto_session.py", "python", "implemented"),
    (feature_ids["daemon_time_budget"], system_ids["_BATCH"], None, "python", "implemented"),
    (feature_ids["tools_action_hub"], system_ids["_BATCH"], "claude_action_hub.py", "python", "implemented"),
    (feature_ids["tools_registry"], system_ids["_BATCH"], "python_tools.json", "json", "implemented"),
    (feature_ids["docs_directory_truth"], system_ids["_BATCH"], "SYSTEM/DIRECTORY_TRUTH.md", "markdown", "implemented"),
    (feature_ids["docs_rules"], system_ids["_BATCH"], "SYSTEM/", "markdown", "implemented"),
    (feature_ids["backup_auto"], system_ids["_BATCH"], "BACKUPS/", "folders", "implemented"),
    
    # recludOS
    (feature_ids["task_system"], system_ids["recludOS"], "controll/data/tasks/", "json", "implemented"),
    (feature_ids["task_delegation"], system_ids["recludOS"], "controll/delegate/", "python", "implemented"),
    (feature_ids["task_recurring"], system_ids["recludOS"], "controll/data/intervals.json", "json", "implemented"),
    (feature_ids["memory_short_term"], system_ids["recludOS"], "_memory/short_term.md", "markdown", "implemented"),
    (feature_ids["memory_long_term"], system_ids["recludOS"], "_memory/storage/", "mixed", "implemented"),
    (feature_ids["session_start_protocol"], system_ids["recludOS"], "boot/", "python", "implemented"),
    (feature_ids["session_snapshots"], system_ids["recludOS"], "snapshots/", "json", "implemented"),
    (feature_ids["gui_main"], system_ids["recludOS"], "gui/ControlCenter.py", "python", "implemented"),
    (feature_ids["gui_systray"], system_ids["recludOS"], "gui/", "python", "implemented"),
    (feature_ids["gui_dashboard"], system_ids["recludOS"], "gui/dashboards/", "html", "implemented"),
    (feature_ids["tools_registry"], system_ids["recludOS"], "controll/registry/", "json", "implemented"),
    (feature_ids["comm_message_box"], system_ids["recludOS"], "User/MessageBox/", "mixed", "implemented"),
    (feature_ids["comm_multi_ai"], system_ids["recludOS"], "connections/connected_AIs/", "json", "implemented"),
    (feature_ids["agents_system"], system_ids["recludOS"], "actors/agents/", "python", "implemented"),
    (feature_ids["agents_services"], system_ids["recludOS"], "actors/services/", "python", "implemented"),
    (feature_ids["agents_actors_model"], system_ids["recludOS"], "actors/", "conceptual", "implemented"),
    (feature_ids["agents_think_modules"], system_ids["recludOS"], "act/think/", "python", "implemented"),
    (feature_ids["special_directory_watcher"], system_ids["recludOS"], None, "python", "implemented"),
    (feature_ids["special_ollama"], system_ids["recludOS"], None, "api", "implemented"),
    (feature_ids["backup_nas"], system_ids["recludOS"], None, "network", "implemented"),
    (feature_ids["backup_trash"], system_ids["recludOS"], "_PAPIERKORB/", "folder", "implemented"),
    
    # BACH_STREAM
    (feature_ids["task_system"], system_ids["BACH_STREAM"], "AUFGABEN.txt", "txt", "partial"),
    (feature_ids["memory_short_term"], system_ids["BACH_STREAM"], "SESSION_MEMORY.txt", "txt", "implemented"),
    (feature_ids["memory_long_term"], system_ids["BACH_STREAM"], "MEMORY/GLOBAL/", "txt", "implemented"),
    (feature_ids["memory_archive"], system_ids["BACH_STREAM"], "MEMORY/ARCHIV/", "folder", "implemented"),
    (feature_ids["special_transfer_port"], system_ids["BACH_STREAM"], "TRANSFER_PORT/", "folder", "implemented"),
    (feature_ids["special_mapping"], system_ids["BACH_STREAM"], "MAPPING/", "folder", "implemented"),
    (feature_ids["backup_trash"], system_ids["BACH_STREAM"], "MEMORY/_PAPIERKORB/", "folder", "implemented"),
    
    # AI-Portable
    (feature_ids["rag_pipeline"], system_ids["AI-Portable"], "rag/", "python", "implemented"),
    (feature_ids["rag_vector_store"], system_ids["AI-Portable"], "db/", "mixed", "implemented"),
    (feature_ids["rag_local_models"], system_ids["AI-Portable"], "models/", "folder", "implemented"),
    
    # recludos-filecommander-mcp
    (feature_ids["file_crud"], system_ids["recludos-filecommander-mcp"], "src/index.ts", "typescript", "implemented"),
    (feature_ids["file_search"], system_ids["recludos-filecommander-mcp"], "src/index.ts", "typescript", "implemented"),
    (feature_ids["file_sessions"], system_ids["recludos-filecommander-mcp"], "src/index.ts", "typescript", "implemented"),
    (feature_ids["file_process_mgmt"], system_ids["recludos-filecommander-mcp"], "src/index.ts", "typescript", "implemented"),
    (feature_ids["backup_trash"], system_ids["recludos-filecommander-mcp"], "fc_safe_delete", "typescript", "implemented"),
]

cursor.executemany("""
    INSERT OR IGNORE INTO implementations (feature_id, system_id, path, technology, status) 
    VALUES (?, ?, ?, ?, ?)
""", implementations)

conn.commit()

# ═══════════════════════════════════════════════════════════════════════════
# STATISTIK
# ═══════════════════════════════════════════════════════════════════════════
cursor.execute("SELECT COUNT(*) FROM systems")
print(f"Systeme: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM features")
print(f"Features: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM feature_aliases")
print(f"Aliase: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM implementations")
print(f"Implementierungen: {cursor.fetchone()[0]}")

conn.close()
print("\nDatenbank erfolgreich befuellt!")
