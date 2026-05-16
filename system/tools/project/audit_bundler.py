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
Tool: c_audit_bundler
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-05
Anthropic-Compatible: True

VERSIONS-HINWEIS: Pruefe auf neuere Versionen mit: bach tools version c_audit_bundler

Description:
    BACH Audit Bundler v1.0 - Erstellt Audit-Pakete fuer externe Reviews.

    Zwei Bundles:
    1. KONZEPT-Bundle (zuerst): Dokumentation, Konzepte, Ideen
    2. IMPLEMENTATION-Bundle (spaeter): Code, DB-Schemas, Scripts

Usage:
    python c_audit_bundler.py --konzept        # Bundle 1: Konzepte
    python c_audit_bundler.py --implementation # Bundle 2: Code
    python c_audit_bundler.py --all            # Beide Bundles
    python c_audit_bundler.py --help           # Hilfe
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

# Fix Windows Console Encoding
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

# ============ KONFIGURATION ============

BACH_ROOT = Path(__file__).parent.parent.resolve()
OUTPUT_DIR = BACH_ROOT / "_AUDIT_BUNDLES"

# ============ BUNDLE DEFINITIONEN ============

KONZEPT_BUNDLE = {
    "name": "BACH_KONZEPT_BUNDLE",
    "description": "Dokumentation, Konzepte, Ideen - ZUERST lesen",
    "sources": [
        # Docs root
        {"path": "docs", "pattern": "*", "recursive": False, "description": "Hauptdokumentation"},
        # Concepts
        {"path": "docs/_concepts_system", "pattern": "*", "recursive": False, "description": "System-Konzepte"},
        # Ideas
        {"path": "docs/_ideas", "pattern": "*", "recursive": False, "description": "Ideen und Vorschlaege"},
        # Data root (Konzepte)
        {"path": "data", "pattern": "*.md", "recursive": False, "description": "Daten-Konzepte"},
        {"path": "data", "pattern": "*.txt", "recursive": False, "description": "Daten-Docs"},
        # GUI Konzepte
        {"path": "gui", "pattern": "*.md", "recursive": False, "description": "GUI-Konzepte"},
        # User Analysen
        {"path": "user", "pattern": "*.md", "recursive": False, "description": "User-Analysen und Synopsen"},
        # Skills Docs
        {"path": "skills", "pattern": "*.md", "recursive": False, "description": "Skill-Definitionen"},
        # Tools Docs (alle .md rekursiv)
        {"path": "tools", "pattern": "*.md", "recursive": True, "description": "Tool-Dokumentation"},
        # Root Docs
        {"path": ".", "pattern": "SKILL.md", "recursive": False, "description": "Haupt-SKILL"},
        {"path": ".", "pattern": "ROADMAP*.md", "recursive": False, "description": "Roadmaps"},
        {"path": ".", "pattern": "CHANGELOG.md", "recursive": False, "description": "Changelog"},
        {"path": ".", "pattern": "BUGLOG.md", "recursive": False, "description": "Bug-Log"},
    ],
    "special": [
        # Help-Dateien nur Titel
        {"type": "titles_only", "path": "help", "pattern": "*.txt", "description": "Hilfe-Themen (nur Titel)"},
    ]
}

IMPLEMENTATION_BUNDLE = {
    "name": "BACH_IMPLEMENTATION_BUNDLE", 
    "description": "Code, Scripts, DB-Schemas - NACH Konzept-Review lesen",
    "sources": [
        # Haupt-CLI
        {"path": ".", "pattern": "bach.py", "recursive": False, "description": "CLI-Zentrale"},
        # Hub System
        {"path": "hub", "pattern": "*.py", "recursive": True, "description": "Hub und Handler"},
        # Tools (Python)
        {"path": "tools", "pattern": "*.py", "recursive": False, "description": "Tool-Scripts (root)"},
        # Agenten
        {"path": "agents", "pattern": "*.md", "recursive": True, "description": "Agenten-Definitionen"},
        {"path": "agents", "pattern": "*.txt", "recursive": True, "description": "Agenten-Configs"},
        # Services
        {"path": "skills/_services", "pattern": "*.py", "recursive": True, "description": "Service-Scripts"},
        {"path": "skills/_services", "pattern": "*.json", "recursive": True, "description": "Service-Configs"},
    ],
    "special": [
        # DB Schema
        {"type": "db_schema", "path": "data/bach.db", "description": "Datenbank-Schema"},
        # user.db wurde in bach.db konsolidiert (Task 772, v1.1.84)
    ]
}

# ============ HILFSFUNKTIONEN ============

def get_db_schema(db_path: Path) -> str:
    """Extrahiert DB-Schema als Text."""
    if not db_path.exists():
        return f"[DB nicht gefunden: {db_path}]"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        lines = [f"# Database Schema: {db_path.name}", ""]
        
        # Alle Tabellen
        tables = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        
        lines.append(f"## Tabellen ({len(tables)})")
        lines.append("")
        
        for (table_name,) in tables:
            lines.append(f"### {table_name}")
            lines.append("```sql")
            
            # Schema der Tabelle
            schema = cursor.execute(
                f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            ).fetchone()
            
            if schema and schema[0]:
                lines.append(schema[0])
            
            lines.append("```")
            
            # Anzahl Eintraege
            try:
                count = cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
                lines.append(f"*{count} Eintraege*")
            except Exception:
                pass
            
            lines.append("")
        
        conn.close()
        return "\n".join(lines)
    
    except Exception as e:
        return f"[DB-Fehler: {e}]"


def get_file_titles(folder: Path, pattern: str) -> str:
    """Gibt nur Dateinamen zurueck."""
    if not folder.exists():
        return f"[Ordner nicht gefunden: {folder}]"
    
    files = list(folder.glob(pattern))
    files.sort()
    
    lines = [f"# Dateien in {folder.name}/ ({len(files)} Dateien)", ""]
    
    for f in files:
        lines.append(f"- {f.name}")
    
    return "\n".join(lines)


def read_file_safe(path: Path) -> str:
    """Liest Datei mit Fehlerbehandlung."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[Lesefehler: {e}]"


def collect_files(source: dict, base_path: Path) -> list:
    """Sammelt Dateien basierend auf Source-Definition."""
    folder = base_path / source["path"]
    pattern = source["pattern"]
    recursive = source.get("recursive", False)
    
    if not folder.exists():
        return []
    
    if recursive:
        files = list(folder.rglob(pattern))
    else:
        files = list(folder.glob(pattern))
    
    # Sortieren und filtern
    files = [f for f in files if f.is_file()]
    files.sort()
    
    return files


# ============ BUNDLE ERSTELLUNG ============

def create_bundle(bundle_def: dict, output_path: Path):
    """Erstellt ein Bundle als TXT-Datei."""
    
    name = bundle_def["name"]
    description = bundle_def["description"]
    
    print(f"\n{'='*60}")
    print(f"📦 Erstelle: {name}")
    print(f"   {description}")
    print(f"{'='*60}")
    
    lines = []
    file_count = 0
    
    # Header
    lines.append(f"# {name}")
    lines.append(f"# {description}")
    lines.append(f"# Erstellt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# BACH Version: 1.1.x")
    lines.append("=" * 70)
    lines.append("")
    
    # Inhaltsverzeichnis
    lines.append("## INHALTSVERZEICHNIS")
    lines.append("")
    
    toc_entries = []
    
    # Normale Quellen verarbeiten
    for source in bundle_def.get("sources", []):
        files = collect_files(source, BACH_ROOT)
        if files:
            toc_entries.append(f"- {source['description']}: {len(files)} Dateien")
    
    # Spezielle Quellen
    for special in bundle_def.get("special", []):
        toc_entries.append(f"- {special['description']}")
    
    lines.extend(toc_entries)
    lines.append("")
    lines.append("=" * 70)
    lines.append("")
    
    # Dateien sammeln
    for source in bundle_def.get("sources", []):
        files = collect_files(source, BACH_ROOT)
        
        if not files:
            continue
        
        lines.append("")
        lines.append(f"## {source['description'].upper()}")
        lines.append(f"## Pfad: {source['path']}  |  Pattern: {source['pattern']}")
        lines.append("")
        
        for file_path in files:
            rel_path = file_path.relative_to(BACH_ROOT)
            
            lines.append("")
            lines.append("=" * 20 + f" START: {rel_path} " + "=" * 20)
            lines.append("")
            
            content = read_file_safe(file_path)
            lines.append(content)
            
            lines.append("")
            lines.append("=" * 20 + f" END: {rel_path} " + "=" * 20)
            lines.append("")
            
            file_count += 1
            print(f"  + {rel_path}")
    
    # Spezielle Quellen verarbeiten
    for special in bundle_def.get("special", []):
        special_type = special["type"]
        
        lines.append("")
        lines.append(f"## {special['description'].upper()}")
        lines.append("")
        
        if special_type == "titles_only":
            folder = BACH_ROOT / special["path"]
            content = get_file_titles(folder, special["pattern"])
            lines.append(content)
            file_count += 1
            print(f"  + {special['path']}/ (nur Titel)")
        
        elif special_type == "db_schema":
            db_path = BACH_ROOT / special["path"]
            content = get_db_schema(db_path)
            lines.append(content)
            file_count += 1
            print(f"  + {special['path']} (Schema)")
        
        lines.append("")
        lines.append("=" * 70)
        lines.append("")
    
    # Schreiben
    output_file = output_path / f"{name}_{datetime.now().strftime('%Y%m%d')}.txt"
    output_file.write_text("\n".join(lines), encoding="utf-8")
    
    print(f"\n✅ Bundle erstellt: {output_file}")
    print(f"   📄 {file_count} Quellen verarbeitet")
    print(f"   📏 {len(lines)} Zeilen")
    
    return output_file


def create_audit_mission(output_path: Path):
    """Erstellt die Audit-Mission-Datei."""
    
    mission = f'''# 🕵️ BACH SYSTEM AUDIT - Externe Überprüfung

**Erstellt:** {datetime.now().strftime('%Y-%m-%d')}
**System:** BACH v1.1 (Best-of aus _BATCH, _CHIAH, recludOS)

---

## Deine Rolle

Du bist ein externer Auditor. Deine Aufgabe ist eine unvoreingenommene Analyse des BACH-Systems.

**WICHTIG:** Lies zuerst NUR das KONZEPT-Bundle. Das IMPLEMENTATION-Bundle kommt später.

---

## Phase 1: Konzept-Review (KONZEPT_BUNDLE)

Bitte prüfe:

### 1. Vision und Ziel
- Was will BACH sein?
- Ist das Ziel klar definiert?
- Macht die Architektur Sinn für das Ziel?

### 2. Dokumentationsqualität
- Sind die Konzepte verständlich?
- Widersprechen sich Dokumente?
- Fehlen wichtige Informationen?

### 3. Roadmap-Analyse
- Sind die geplanten Features sinnvoll?
- Gibt es Over-Engineering?
- Was fehlt wirklich?

### 4. Konzept-Kritik
- Wo sind Logik-Lücken?
- Was ist unrealistisch?
- Was sollte gestrichen werden?

---

## Phase 2: Implementation-Review (IMPLEMENTATION_BUNDLE)

**ERST NACH Phase 1 öffnen!**

Prüfe dann:
- Entspricht der Code den Konzepten?
- Gibt es toten Code?
- Ist die Struktur konsistent?
- DB-Schema: Sind alle Tabellen sinnvoll?

---

## Output-Format

Erstelle einen Bericht:

### 🔴 Kritisch
- Fundamentale Probleme

### 🟡 Wichtig  
- Verbesserungsbedarf

### 🟢 Vorschläge
- Nice-to-have

### 📊 Gesamtbewertung
- Score 1-10
- Top 3 Stärken
- Top 3 Schwächen
- Empfehlung: Weiter so / Kurs korrigieren / Neustart

---

## Kontext

BACH entstand als Zusammenführung von 3 Systemen:
- **_BATCH:** Hub-System, Session-Management
- **_CHIAH:** CLI-First, Injektoren
- **recludOS:** Agent-Framework, Selbstheilung

Die Frage ist: Hat BACH das Beste übernommen oder nur Komplexität kopiert?

---

*Audit-Mission generiert von audit_bundler.py*
'''
    
    mission_file = output_path / "00_AUDIT_MISSION.md"
    mission_file.write_text(mission, encoding="utf-8")
    print(f"\n📋 Audit-Mission erstellt: {mission_file}")


# ============ MAIN ============

def main():
    """Hauptfunktion."""
    
    # Output-Verzeichnis erstellen
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    if len(sys.argv) < 2:
        print_help()
        return
    
    arg = sys.argv[1].lower()
    
    if arg in ("--help", "-h"):
        print_help()
    
    elif arg == "--konzept":
        create_audit_mission(OUTPUT_DIR)
        create_bundle(KONZEPT_BUNDLE, OUTPUT_DIR)
    
    elif arg == "--implementation":
        create_bundle(IMPLEMENTATION_BUNDLE, OUTPUT_DIR)
    
    elif arg == "--all":
        create_audit_mission(OUTPUT_DIR)
        create_bundle(KONZEPT_BUNDLE, OUTPUT_DIR)
        create_bundle(IMPLEMENTATION_BUNDLE, OUTPUT_DIR)
    
    else:
        print(f"Unbekanntes Argument: {arg}")
        print_help()


def print_help():
    """Zeigt Hilfe."""
    print("""
BACH Audit Bundler v1.0
=======================

Erstellt Audit-Pakete für externe Reviews.

Verwendung:
    python audit_bundler.py --konzept        # Bundle 1: Konzepte (ZUERST)
    python audit_bundler.py --implementation # Bundle 2: Code (DANACH)
    python audit_bundler.py --all            # Beide Bundles
    python audit_bundler.py --help           # Diese Hilfe

Workflow für externes Audit:
    1. --konzept ausführen
    2. KONZEPT_BUNDLE an Auditor geben
    3. Auditor bewertet Konzepte
    4. --implementation ausführen  
    5. IMPLEMENTATION_BUNDLE an Auditor geben
    6. Auditor bewertet Implementation

Output: _AUDIT_BUNDLES/
    """)


if __name__ == "__main__":
    main()
