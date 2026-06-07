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
bach_paths.py - Zentrale Self-Healing Pfad-Konfiguration v2.0.0
================================================================

EINE Datei für ALLE Pfade in BACH - Single Source of Truth.

STRUKTUR:
    BACH_ROOT/              <- Repository Root
    ├── system/             <- SYSTEM_ROOT
    │   ├── hub/            <- Dieses Verzeichnis (wo bach_paths.py liegt)
    │   ├── data/
    │   ├── gui/
    │   ├── agents/         <- Agent-Definitionen (Boss-Agenten + Experten)
    │   │   └── _experts/
    │   ├── connectors/     <- Adapter-Code (Telegram, Discord, etc.)
    │   ├── partners/       <- Partner-Infrastruktur (claude, gemini, ollama)
    │   ├── tools/
    │   └── skills/
    │       ├── workflows/ <- Textuelle Anleitungen (ehem. _workflows)
    │       ├── _services/  <- Service-Skills (.md)
    │       ├── _templates/
    │       ├── _os/
    │       └── docs/help/
    └── user/
        └── documents/

IMPORT VON ÜBERALL:
    # Methode 1: Direkt wenn im sys.path
    from hub.bach_paths import BACH_ROOT, DATA_DIR

    # Methode 2: Universal (funktioniert von überall)
    import sys
    from pathlib import Path
    # Finde bach_paths.py automatisch
    _current = Path(__file__).resolve()
    for _parent in [_current] + list(_current.parents):
        _hub = _parent / "system" / "hub"
        if _hub.exists():
            if str(_hub) not in sys.path:
                sys.path.insert(0, str(_hub))
            break
    from bach_paths import BACH_ROOT, get_path

    # Methode 3: Einfachster Weg - get_path() nutzen
    template = get_path("templates") / "mein_template.docx"
    berichte = get_path("berichte")

Features:
- Self-Healing: Pfade relativ zum Script-Standort berechnet
- Keine hartcodierten absoluten Pfade nötig
- get_path(name) für einfachen Zugriff auf alle Pfade
- Validierung gegen directory_truth.json
- Domain-spezifische Pfade (Steuer, Berichte, Partners, etc.)

Version: 2.0.0
Updated: 2026-02-02
"""
import os
from pathlib import Path
import sys

# ============================================================================
# HIERARCHIE-EBENEN
# ============================================================================

# Diese Datei liegt in: system/hub/bach_paths.py
# Daher: hub/ -> system/ -> BACH_ROOT

HUB_DIR = Path(__file__).parent.resolve()           # system/hub/
SYSTEM_ROOT = HUB_DIR.parent.resolve()              # system/
BACH_ROOT = SYSTEM_ROOT.parent.resolve()            # Repository Root (BACH_test/)

# ============================================================================
# SYSTEM-VERZEICHNISSE (innerhalb system/)
# ============================================================================

DATA_DIR = SYSTEM_ROOT / "data"
GUI_DIR = SYSTEM_ROOT / "gui"
SKILLS_DIR = SYSTEM_ROOT / "skills"
DIST_DIR = SYSTEM_ROOT / "dist"
TEMPLATES_DIR = SYSTEM_ROOT / "_templates"

# Help liegt unter system/docs/help/
HELP_DIR = SYSTEM_ROOT / "docs" / "help"

# Tools-Verzeichnis (direkt unter system/, NICHT unter skills/)
# KORRIGIERT 2026-02-05: Tools liegen unter system/tools/, nicht skills/tools/
TOOLS_DIR = SYSTEM_ROOT / "tools"
AGENTS_DIR = SYSTEM_ROOT / "agents"
EXPERTS_DIR = AGENTS_DIR / "_experts"
PROTOCOLS_DIR = SKILLS_DIR / "workflows"
WORKFLOWS_DIR = PROTOCOLS_DIR  # Alias fuer Rueckwaertskompatibilitaet
PARTNERS_DIR = SYSTEM_ROOT / "partners"
CONNECTORS_DIR = SYSTEM_ROOT / "connectors"
SERVICES_DIR = SKILLS_DIR / "_services"

# Data-Unterverzeichnisse
LOGS_DIR = DATA_DIR / "logs"


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


BACKUPS_DIR = _env_path("BACH_BACKUPS_DIR", Path.home() / ".bach" / "backups")
ARCHIVE_DIR = DATA_DIR / "_archive"
TRASH_DIR = DATA_DIR / "_trash"
MESSAGES_DIR = DATA_DIR / "messages"
INSTANCES_DIR = DATA_DIR / "instances"

# ============================================================================
# PROSYNC (Lokale DB + OneDrive-Transit)
# ============================================================================

LOCAL_BACH_DIR = Path.home() / ".bach"
_LOCAL_DB = LOCAL_BACH_DIR / "bach.db"
_ONEDRIVE_CANDIDATES = [
    BACH_ROOT.parent.parent.parent.parent,
    Path.home() / "OneDrive",
    Path.home() / "Library" / "CloudStorage" / "OneDrive-Persönlich",
]
_ONEDRIVE_SYNC_DIR = next(
    (c / ".SYNC" for c in _ONEDRIVE_CANDIDATES if (c / ".SYNC").exists()), None
)
PROSYNC_TRANSIT_DIR = (
    _ONEDRIVE_SYNC_DIR / "bach_db_transit" if _ONEDRIVE_SYNC_DIR
    else LOCAL_BACH_DIR / "transit"
)

# ============================================================================
# ROOT-VERZEICHNISSE (auf Repository-Ebene)
# ============================================================================

USER_DIR = BACH_ROOT / "user"
DOCS_DIR = BACH_ROOT / "docs"
EXPORTS_DIR = BACH_ROOT / "exports"
EXTENSIONS_DIR = BACH_ROOT / "extensions"

# ============================================================================
# DATENBANKEN
# ============================================================================

# ProSync: Lokale DB bevorzugen, OneDrive-DB als Fallback
ONEDRIVE_DB = DATA_DIR / "bach.db"
if _LOCAL_DB.exists():
    BACH_DB = _LOCAL_DB
else:
    BACH_DB = ONEDRIVE_DB
# USER_DB deprecated seit v1.1.84 - alle Daten jetzt in bach.db (Task 772)
USER_DB = BACH_DB  # Alias fuer Rueckwaertskompatibilitaet
ARCHIVE_DB = BACH_DB  # Konsolidiert v2.0: Archive-Tabellen jetzt in bach.db (Task 980)

# ============================================================================
# USER-DOKUMENTE (neue Struktur)
# ============================================================================

USER_DOCUMENTS_DIR = USER_DIR / "documents"
USER_PERSOENLICH_DIR = USER_DOCUMENTS_DIR / "persoenlicher_assistent"

# ============================================================================
# STEUER-VERZEICHNISSE (Domain-spezifisch)
# ============================================================================

STEUER_DIR = USER_PERSOENLICH_DIR / "steuer"
STEUER_2025 = STEUER_DIR / "2025"
BELEGE_DIR = STEUER_2025 / "Werbungskosten" / "belege"
BUNDLES_DIR = STEUER_2025 / "Werbungskosten" / "belege" / "_bundles"
TXT_DIR = STEUER_2025 / "Werbungskosten" / "export"

# ============================================================================
# PARTNER-VERZEICHNISSE
# ============================================================================

GEMINI_DIR = PARTNERS_DIR / "gemini"
CLAUDE_DIR = PARTNERS_DIR / "claude"
OLLAMA_DIR = PARTNERS_DIR / "ollama"

# ============================================================================
# ANONYMISIERUNG & FOERDERPLANUNG
# ============================================================================

FOERDERPLANUNG_DIR = USER_DOCUMENTS_DIR / "foerderplaner"
QUARANTINE_DIR = FOERDERPLANUNG_DIR / "_incoming_quarantine"
KLIENTEN_DIR = FOERDERPLANUNG_DIR / "klienten"
EXPORT_PREPARE_DIR = FOERDERPLANUNG_DIR / "_prepare_for_export"
EXPORT_READY_DIR = FOERDERPLANUNG_DIR / "_ready_for_export"
ANON_JOBS_DIR = USER_DIR / "anonymization_jobs"

# Berichte-Verzeichnisse (für Förderbericht-Generator)
BERICHTE_DIR = FOERDERPLANUNG_DIR / "Berichte"
BERICHTE_KLIENTEN_DIR = BERICHTE_DIR / "Klienten"
BERICHTE_BUNDLES_DIR = BERICHTE_DIR / "bundles"     # Anonymisierte Bundles

# Pipeline-Ordner (v3 Struktur)
BERICHTE_DATA_ROH_DIR = BERICHTE_DIR / "data_roh"
BERICHTE_DATA_ANO_DIR = BERICHTE_DIR / "data_ano"
BERICHTE_DATA_BUNDLED_DIR = BERICHTE_DIR / "data_bundled"
BERICHTE_OUTPUT_DIR = BERICHTE_DIR / "output_berichte"

# Legacy-Aliase (Rueckwaertskompatibilitaet)
BERICHTE_DATA_DIR = BERICHTE_DATA_ROH_DIR
BERICHTE_ANO_DIR = BERICHTE_DIR / "Berichte_ano"      # Deprecated, nicht mehr aktiv
BERICHTE_CLEAN_DIR = BERICHTE_OUTPUT_DIR               # Alias fuer output_berichte

# ============================================================================
# TEMPLATES (in skills/_templates/)
# ============================================================================

SKILL_TEMPLATES_DIR = SKILLS_DIR / "_templates"
BERICHT_TEMPLATE = SKILL_TEMPLATES_DIR / "bericht_template_geiger_universal.docx"

# ============================================================================
# EXTERNE PFADE (User-spezifisch, können fehlen)
# ============================================================================

# Wissensdatenbank - externer Pfad außerhalb von BACH
WISSENSDATENBANK_DIR = Path.home() / "OneDrive" / "Dokumente" / "_Wissensdatenbank"

# ============================================================================
# PFAD-REGISTRY (Single Source of Truth)
# ============================================================================

# Alle bekannten Pfade zentral registriert - get_path() nutzt diese
_PATH_REGISTRY = {
    # Hierarchie
    "root": BACH_ROOT,
    "bach": BACH_ROOT,
    "system": SYSTEM_ROOT,
    "hub": HUB_DIR,

    # System-Verzeichnisse
    "data": DATA_DIR,
    "gui": GUI_DIR,
    "skills": SKILLS_DIR,
    "dist": DIST_DIR,

    # Skills-Unterverzeichnisse
    "tools": TOOLS_DIR,
    "help": HELP_DIR,
    "templates": SKILL_TEMPLATES_DIR,

    # Top-Level Verzeichnisse (v2.5 Restructuring)
    "agents": AGENTS_DIR,
    "experts": EXPERTS_DIR,
    "protocols": PROTOCOLS_DIR,
    "workflows": WORKFLOWS_DIR,  # Alias -> protocols
    "partners": PARTNERS_DIR,
    "connectors": CONNECTORS_DIR,
    "services": SERVICES_DIR,

    # Data-Unterverzeichnisse
    "logs": LOGS_DIR,
    "backups": BACKUPS_DIR,
    "archive": ARCHIVE_DIR,
    "trash": TRASH_DIR,
    "messages": MESSAGES_DIR,
    "instances": INSTANCES_DIR,

    # Root-Verzeichnisse
    "user": USER_DIR,
    "docs": DOCS_DIR,
    "exports": EXPORTS_DIR,
    "extensions": EXTENSIONS_DIR,

    # Datenbanken
    "db": BACH_DB,
    "bach_db": BACH_DB,
    "onedrive_db": ONEDRIVE_DB,
    "archive_db": ARCHIVE_DB,

    # ProSync
    "local_bach": LOCAL_BACH_DIR,
    "prosync_transit": PROSYNC_TRANSIT_DIR,

    # User-Dokumente
    "user_documents": USER_DOCUMENTS_DIR,
    "persoenlich": USER_PERSOENLICH_DIR,

    # Steuer
    "steuer": STEUER_DIR,
    "steuer_2025": STEUER_2025,
    "belege": BELEGE_DIR,
    "bundles": BUNDLES_DIR,

    # Partner
    "gemini": GEMINI_DIR,
    "claude": CLAUDE_DIR,
    "ollama": OLLAMA_DIR,

    # Förderplanung / Berichte
    "foerderplanung": FOERDERPLANUNG_DIR,
    "berichte": BERICHTE_DIR,
    "berichte_output": BERICHTE_OUTPUT_DIR,
    "berichte_klienten": BERICHTE_KLIENTEN_DIR,
    "berichte_data": BERICHTE_DATA_DIR,         # Legacy -> data_roh
    "berichte_bundles": BERICHTE_BUNDLES_DIR,   # Anonymisierte Bundles
    "berichte_data_roh": BERICHTE_DATA_ROH_DIR,
    "berichte_data_ano": BERICHTE_DATA_ANO_DIR,
    "berichte_data_bundled": BERICHTE_DATA_BUNDLED_DIR,
    "berichte_output": BERICHTE_OUTPUT_DIR,
    "berichte_ano": BERICHTE_ANO_DIR,       # Deprecated
    "berichte_clean": BERICHTE_CLEAN_DIR,   # Alias fuer output_berichte
    "klienten": KLIENTEN_DIR,
    "quarantine": QUARANTINE_DIR,

    # Templates
    "bericht_template": BERICHT_TEMPLATE,

    # Extern
    "wissensdatenbank": WISSENSDATENBANK_DIR,

    # Distribution
    "distribution": TOOLS_DIR / "distribution.py",
}


# ============================================================================
# HELPER FUNKTIONEN
# ============================================================================

def get_path(name: str) -> Path:
    """
    Zentrale Funktion zum Abrufen von BACH-Pfaden.

    Diese Funktion ist der EMPFOHLENE Weg, Pfade abzurufen.
    Sie funktioniert von überall im System.

    Args:
        name: Name des Pfades (case-insensitive), z.B.:
              "root", "system", "data", "tools", "templates",
              "berichte", "klienten", "bericht_template", etc.

    Returns:
        Path zum Verzeichnis/zur Datei

    Raises:
        KeyError: Wenn der Pfadname unbekannt ist

    Example:
        template = get_path("bericht_template")
        output_dir = get_path("berichte_output")
        db = get_path("db")

    Available paths:
        Hierarchie: root, bach, system, hub
        System: data, gui, skills, dist
        Skills: tools, help, templates
        Top-Level: agents, experts, protocols, workflows, partners, connectors, services
        Data: logs, backups, archive, trash, messages
        Root: user, docs, exports, extensions
        DB: db, bach_db, archive_db
        User: user_documents, persoenlich
        Steuer: steuer, steuer_2025, belege, bundles
        Partner: gemini, claude, ollama
        Berichte: foerderplanung, berichte, berichte_output, berichte_klienten, klienten
        Extern: wissensdatenbank
    """
    key = name.lower().replace("-", "_").replace(" ", "_")
    if key not in _PATH_REGISTRY:
        available = ", ".join(sorted(_PATH_REGISTRY.keys()))
        raise KeyError(f"Unbekannter Pfad: '{name}'. Verfügbar: {available}")
    return _PATH_REGISTRY[key]


def list_paths() -> dict:
    """
    Listet alle verfügbaren Pfade auf.

    Returns:
        Dict mit Pfadnamen und deren Werten
    """
    return {k: str(v) for k, v in _PATH_REGISTRY.items()}


def get_db(name: str = "bach") -> Path:
    """
    Gibt Pfad zur Datenbank zurueck.

    Args:
        name: "bach" oder "user" (beide zeigen jetzt auf bach.db)

    Returns:
        Path zur DB

    Note:
        Seit v1.1.84 (Task 772) sind user.db und bach.db zusammengefuehrt.
        "user" wird aus Kompatibilitaet akzeptiert, zeigt aber auf bach.db.
    """
    # Alle Daten jetzt in bach.db
    return BACH_DB


def get_tool_path(tool_name: str) -> Path:
    """
    Findet ein Tool mit Self-Healing (durchsucht Unterordner).

    Args:
        tool_name: Name des Tools (mit oder ohne .py)

    Returns:
        Path zum Tool oder None wenn nicht gefunden
    """
    if not tool_name.endswith('.py'):
        tool_name = f"{tool_name}.py"

    # Direkt in tools/
    direct = TOOLS_DIR / tool_name
    if direct.exists():
        return direct

    # In Unterordnern suchen
    for subdir in TOOLS_DIR.iterdir():
        if subdir.is_dir() and not subdir.name.startswith('__'):
            candidate = subdir / tool_name
            if candidate.exists():
                return candidate

    return None


def get_partner_dir(partner: str) -> Path:
    """
    Gibt Partner-Verzeichnis zurück.

    Args:
        partner: "gemini", "claude", "ollama", etc.

    Returns:
        Path zum Partner-Verzeichnis
    """
    return PARTNERS_DIR / partner


def get_belege_path(anbieter: str = None) -> Path:
    """
    Gibt Pfad zum Belege-Ordner zurück.

    Args:
        anbieter: Optional - Unterordner für Anbieter

    Returns:
        Path zum Belege-Verzeichnis
    """
    if anbieter:
        return BELEGE_DIR / anbieter
    return BELEGE_DIR


def resolve(relative_path: str, from_root: bool = False) -> Path:
    """
    Löst relativen Pfad auf.

    Args:
        relative_path: z.B. "skills/tools/autolog.py"
        from_root: True = ab BACH_ROOT, False = ab SYSTEM_ROOT (default)

    Returns:
        Absoluter Path
    """
    base = BACH_ROOT if from_root else SYSTEM_ROOT
    return base / relative_path


# ============================================================================
# DEPLOYMENT MODE DETECTION
# ============================================================================

import os as _os

def get_deployment_mode() -> str:
    """
    Erkennt den Deployment-Modus von BACH.

    Returns:
        "server"  — BACH_SERVER_MODE env var gesetzt oder als Service laufend
        "onedrive" — System liegt in einem OneDrive-synced Verzeichnis
        "local"   — Standalone lokale Installation (z.B. ~/.bach/)
    """
    if _os.environ.get("BACH_SERVER_MODE") or _os.environ.get("BACH_HOST"):
        return "server"
    system_str = str(SYSTEM_ROOT).lower()
    if "onedrive" in system_str or "cloudstorage" in system_str:
        return "onedrive"
    return "local"


def is_server_mode() -> bool:
    """True wenn BACH im Server-Modus laeuft."""
    return get_deployment_mode() == "server"


def is_onedrive_mode() -> bool:
    """True wenn BACH aus einem OneDrive-Verzeichnis laeuft."""
    return get_deployment_mode() == "onedrive"


DEPLOYMENT_MODE = get_deployment_mode()


# ============================================================================
# FILE ACCESS HOOK (Anonymisierte Dateizugriffe)
# ============================================================================

def get_safe_klient_path(original_path: str) -> Path:
    """
    Übersetzt einen Klienten-Dateipfad auf das anonymisierte Bundle.

    WICHTIG: Nutze diese Funktion für ALLE Zugriffe auf Klientendaten!
    Sie stellt sicher, dass nur anonymisierte Daten gelesen werden.

    Args:
        original_path: Pfad zur Klienten-Datei (kann echte Namen enthalten)

    Returns:
        Sicherer Pfad zum anonymisierten Bundle

    Example:
        # Statt: open(DATA_DIR / "Mustermann, Max/doc.docx")
        safe_path = get_safe_klient_path("Mustermann, Max/doc.docx")
        open(safe_path)
    """
    try:
        from _services.document.file_access_hook import get_safe_path
        return get_safe_path(original_path)
    except ImportError:
        # Fallback: Original-Pfad zurückgeben
        return Path(original_path)


def read_safe_klient_data(klient_name: str, filename: str = None) -> str:
    """
    Liest Klientendaten sicher aus dem anonymisierten Bundle.

    Der Chatbot und das LLM sehen NUR anonymisierte Daten (Tarnnamen).
    Echte Namen werden niemals zurückgegeben.

    Args:
        klient_name: Name des Klienten (kann echter Name sein)
        filename: Optionaler Dateiname

    Returns:
        Anonymisierter Textinhalt
    """
    try:
        from _services.document.file_access_hook import read_safe_file
        return read_safe_file(klient_name, filename)
    except ImportError:
        return f"[FEHLER] File Access Hook nicht verfügbar"


def get_klient_tarnname(klient_name: str) -> str:
    """
    Gibt den Tarnnamen für einen Klienten zurück.

    Der Chatbot sollte IMMER den Tarnnamen verwenden, niemals den echten.

    Args:
        klient_name: Echter Klientenname

    Returns:
        Tarnname oder None
    """
    try:
        from _services.document.file_access_hook import get_tarnname
        return get_tarnname(klient_name)
    except ImportError:
        return None


# ============================================================================
# DB-INTEGRATION (Optional - für User-spezifische Overrides)
# ============================================================================

_db_overrides_loaded = False
_db_overrides = {}


def load_path_overrides_from_db() -> dict:
    """
    Lädt Pfad-Overrides aus der system_config Tabelle.

    Die DB kann Pfade überschreiben für User-spezifische Anpassungen.
    Format in DB: key="path.<name>", value="<absoluter_pfad>"

    Returns:
        Dict mit Overrides {name: Path}
    """
    global _db_overrides_loaded, _db_overrides

    if _db_overrides_loaded:
        return _db_overrides

    try:
        import sqlite3
        if not BACH_DB.exists():
            _db_overrides_loaded = True
            return {}

        conn = sqlite3.connect(str(BACH_DB))
        c = conn.cursor()

        # Prüfen ob system_config Tabelle existiert
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='system_config'")
        if not c.fetchone():
            conn.close()
            _db_overrides_loaded = True
            return {}

        # Pfad-Overrides laden
        c.execute("SELECT key, value FROM system_config WHERE key LIKE 'path.%'")
        for key, value in c.fetchall():
            path_name = key.replace("path.", "")
            _db_overrides[path_name] = Path(value)

        conn.close()
        _db_overrides_loaded = True
        return _db_overrides

    except Exception:
        _db_overrides_loaded = True
        return {}


def get_path_with_override(name: str) -> Path:
    """
    Wie get_path(), aber prüft zuerst DB-Overrides.

    Args:
        name: Pfadname

    Returns:
        Path (Override aus DB falls vorhanden, sonst Standard)
    """
    overrides = load_path_overrides_from_db()
    key = name.lower().replace("-", "_").replace(" ", "_")

    if key in overrides:
        return overrides[key]

    return get_path(name)


def set_path_override(name: str, path: str) -> bool:
    """
    Setzt einen Pfad-Override in der DB.

    Args:
        name: Pfadname (z.B. "wissensdatenbank")
        path: Neuer absoluter Pfad

    Returns:
        True wenn erfolgreich
    """
    try:
        import sqlite3
        conn = sqlite3.connect(str(BACH_DB))
        c = conn.cursor()

        # system_config Tabelle erstellen falls nicht vorhanden
        c.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Override setzen
        key = f"path.{name.lower()}"
        c.execute("""
            INSERT OR REPLACE INTO system_config (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
        """, (key, path))

        conn.commit()
        conn.close()

        # Cache invalidieren
        global _db_overrides_loaded
        _db_overrides_loaded = False

        return True
    except Exception:
        return False


# ============================================================================
# VALIDIERUNG
# ============================================================================

def validate() -> list:
    """
    Validiert wichtige Pfade.

    Returns:
        Liste von Warnungen (leer wenn alles ok)
    """
    warnings = []

    critical = [
        (BACH_ROOT, "BACH_ROOT"),
        (SYSTEM_ROOT, "SYSTEM_ROOT"),
        (DATA_DIR, "DATA_DIR"),
        (BACH_DB, "BACH_DB"),
        (HUB_DIR, "HUB_DIR"),
    ]

    important = [
        (SKILLS_DIR, "SKILLS_DIR"),
        (TOOLS_DIR, "TOOLS_DIR"),
        (HELP_DIR, "HELP_DIR"),
        (USER_DIR, "USER_DIR"),
    ]

    optional = [
        (PARTNERS_DIR, "PARTNERS_DIR"),
        (CONNECTORS_DIR, "CONNECTORS_DIR"),
        (AGENTS_DIR, "AGENTS_DIR"),
        (LOGS_DIR, "LOGS_DIR"),
        (STEUER_DIR, "STEUER_DIR"),
    ]

    for path, name in critical:
        if not path.exists():
            warnings.append(f"[FEHLER] {name} nicht gefunden: {path}")

    for path, name in important:
        if not path.exists():
            warnings.append(f"[WARN] {name} nicht gefunden: {path}")

    for path, name in optional:
        if not path.exists():
            warnings.append(f"[INFO] {name} nicht gefunden: {path}")

    return warnings


# ============================================================================
# DEBUG / CLI
# ============================================================================

def main():
    """CLI Einstiegspunkt."""
    import argparse

    parser = argparse.ArgumentParser(
        description="BACH Path Configuration v2.0.0 - Single Source of Truth"
    )
    parser.add_argument("name", nargs="?", help="Pfadname zum Abrufen (z.B. 'templates', 'berichte')")
    parser.add_argument("--list", "-l", action="store_true", help="Alle verfügbaren Pfade auflisten")
    parser.add_argument("--validate", "-v", action="store_true", help="Alle Pfade validieren")
    parser.add_argument("--json", "-j", action="store_true", help="Ausgabe als JSON")
    parser.add_argument("--set", "-s", metavar="PATH", help="Pfad-Override setzen (mit name)")
    parser.add_argument("--overrides", action="store_true", help="DB-Overrides anzeigen")

    args = parser.parse_args()

    # Einzelnen Pfad abrufen
    if args.name and not args.set:
        try:
            path = get_path(args.name)
            if args.json:
                import json
                print(json.dumps({"name": args.name, "path": str(path), "exists": path.exists()}))
            else:
                status = "[OK]" if path.exists() else "[MISSING]"
                print(f"{path} {status}")
        except KeyError as e:
            print(f"[FEHLER] {e}")
            return 1
        return 0

    # Override setzen
    if args.set and args.name:
        if set_path_override(args.name, args.set):
            print(f"[OK] Override gesetzt: {args.name} -> {args.set}")
        else:
            print(f"[FEHLER] Konnte Override nicht setzen")
            return 1
        return 0

    # DB-Overrides anzeigen
    if args.overrides:
        overrides = load_path_overrides_from_db()
        if overrides:
            print("DB-Overrides:")
            for name, path in overrides.items():
                print(f"  {name}: {path}")
        else:
            print("Keine DB-Overrides gesetzt.")
        return 0

    # Alle Pfade auflisten
    if args.list:
        if args.json:
            import json
            print(json.dumps(list_paths(), indent=2))
        else:
            print("Verfügbare Pfade:")
            print("-" * 60)
            for name, path in sorted(list_paths().items()):
                p = Path(path)
                status = "✓" if p.exists() else "✗"
                print(f"  {name:20} {status} {path}")
        return 0

    # Validierung
    if args.validate:
        warnings = validate()
        if args.json:
            import json
            print(json.dumps({"valid": len(warnings) == 0, "warnings": warnings}))
        else:
            if warnings:
                print("VALIDIERUNG - Warnungen:")
                for w in warnings:
                    print(f"  {w}")
            else:
                print("[OK] Alle kritischen Pfade valide")
        return 0 if not warnings else 1

    # Standard-Ausgabe
    print("=" * 70)
    print("BACH PATH CONFIGURATION v2.0.0 (Single Source of Truth)")
    print("=" * 70)

    groups = {
        "HIERARCHIE": ["root", "system", "hub"],
        "SYSTEM": ["data", "skills", "tools", "templates", "gui"],
        "DATENBANKEN": ["db", "archive_db"],
        "USER": ["user", "user_documents"],
        "BERICHTE": ["foerderplanung", "berichte", "berichte_output", "bericht_template"],
        "PARTNER": ["gemini", "claude", "ollama"],
    }

    for group_name, path_names in groups.items():
        print(f"\n--- {group_name} ---")
        for name in path_names:
            try:
                path = get_path(name)
                status = "[OK]" if path.exists() else "[MISSING]"
                print(f"  {name:20} {path} {status}")
            except KeyError:
                pass

    print("\n" + "=" * 70)
    print("Nutzung: python bach_paths.py <name>     # Einzelnen Pfad abrufen")
    print("         python bach_paths.py --list    # Alle Pfade auflisten")
    print("         python bach_paths.py --validate # Pfade validieren")

    warnings = validate()
    if warnings:
        print("\n[WARNUNG] Einige Pfade fehlen:")
        for w in warnings[:3]:
            print(f"  {w}")
    else:
        print("\n[OK] Alle kritischen Pfade valide")

    return 0


if __name__ == "__main__":
    sys.exit(main())
