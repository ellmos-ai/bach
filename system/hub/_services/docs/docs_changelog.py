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
BACH Docs Changelog Service v1.0
================================

Automatisches Logging von Help- und Wiki-Aenderungen.

Verwendung:
  python docs_changelog.py log "docs/help/workflow.txt" "added" "Steuer-Workflows hinzugefuegt"
  python docs_changelog.py log "wiki/steuer/fortbildung.txt" "created" "Neuer Wiki-Artikel"
  python docs_changelog.py show                    # Zeige letzte Aenderungen
  python docs_changelog.py report                  # Erstelle Monatsbericht

Log-Speicherort:
  logs/docs/YYYY-MM_docs_changes.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Pfade
DOCS_SERVICE_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = DOCS_SERVICE_DIR.parent
SKILLS_DIR = SERVICES_DIR.parent
BACH_DIR = SKILLS_DIR.parent
LOGS_DIR = BACH_DIR / "data" / "logs" / "docs"

# ============ LOGGING ============

def get_log_file() -> Path:
    """Gibt den aktuellen Monat-Log-Pfad zurueck."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    month = datetime.now().strftime("%Y-%m")
    return LOGS_DIR / f"{month}_docs_changes.json"


def load_log() -> Dict:
    """Laedt das aktuelle Log."""
    log_file = get_log_file()
    if log_file.exists():
        try:
            return json.loads(log_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {"entries": [], "created": datetime.now().isoformat()}


def save_log(data: Dict):
    """Speichert das Log."""
    log_file = get_log_file()
    data["last_updated"] = datetime.now().isoformat()
    log_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def log_change(file_path: str, action: str, description: str, author: str = "claude") -> bool:
    """
    Loggt eine Aenderung an einer Help/Wiki-Datei.

    Args:
        file_path: Relativer Pfad zur Datei (z.B. "wiki/steuer/fortbildung.txt")
        action: Art der Aenderung ("created", "updated", "deleted", "moved")
        description: Beschreibung der Aenderung
        author: Wer hat die Aenderung gemacht

    Returns:
        True bei Erfolg
    """
    log_data = load_log()

    entry = {
        "timestamp": datetime.now().isoformat(),
        "file": file_path,
        "action": action,
        "description": description,
        "author": author
    }

    log_data["entries"].append(entry)
    save_log(log_data)

    print(f"[DOCS] {action.upper()}: {file_path}")
    print(f"       {description}")
    return True


def log_batch(changes: List[Dict]) -> int:
    """
    Loggt mehrere Aenderungen auf einmal.

    Args:
        changes: Liste von {"file": str, "action": str, "description": str}

    Returns:
        Anzahl geloggter Aenderungen
    """
    log_data = load_log()
    timestamp = datetime.now().isoformat()
    count = 0

    for change in changes:
        entry = {
            "timestamp": timestamp,
            "file": change.get("file", "unknown"),
            "action": change.get("action", "updated"),
            "description": change.get("description", ""),
            "author": change.get("author", "claude"),
            "batch": True
        }
        log_data["entries"].append(entry)
        count += 1

    save_log(log_data)
    print(f"[DOCS] {count} Aenderungen geloggt")
    return count


# ============ REPORTS ============

def show_recent(count: int = 10) -> List[Dict]:
    """Zeigt die letzten N Aenderungen."""
    log_data = load_log()
    entries = log_data.get("entries", [])

    recent = entries[-count:] if entries else []
    recent.reverse()  # Neueste zuerst

    print(f"[DOCS] Letzte {len(recent)} Aenderungen:")
    print("-" * 60)

    for entry in recent:
        ts = entry.get("timestamp", "")[:16]
        action = entry.get("action", "?").upper()
        file = entry.get("file", "?")
        desc = entry.get("description", "")[:40]
        print(f"{ts} | {action:8} | {file}")
        if desc:
            print(f"                            {desc}")

    return recent


def generate_report() -> str:
    """Generiert einen Monatsbericht."""
    log_data = load_log()
    entries = log_data.get("entries", [])

    if not entries:
        return "Keine Aenderungen im aktuellen Monat."

    # Statistiken
    stats = {
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "moved": 0,
        "other": 0
    }

    files_changed = set()
    wiki_changes = []
    help_changes = []

    for entry in entries:
        action = entry.get("action", "other")
        if action in stats:
            stats[action] += 1
        else:
            stats["other"] += 1

        file_path = entry.get("file", "")
        files_changed.add(file_path)

        if "wiki/" in file_path:
            wiki_changes.append(entry)
        elif "docs/help/" in file_path:
            help_changes.append(entry)

    # Report generieren
    month = datetime.now().strftime("%Y-%m")
    report = f"""# BACH Dokumentations-Aenderungen {month}

## Zusammenfassung

- Gesamte Aenderungen: {len(entries)}
- Betroffene Dateien: {len(files_changed)}
- Neue Dateien: {stats['created']}
- Aktualisierungen: {stats['updated']}
- Geloeschte Dateien: {stats['deleted']}

## Help-Dateien ({len(help_changes)} Aenderungen)

"""

    for entry in help_changes[-10:]:
        report += f"- {entry.get('file')}: {entry.get('description', '')}\n"

    report += f"""
## Wiki-Artikel ({len(wiki_changes)} Aenderungen)

"""

    for entry in wiki_changes[-10:]:
        report += f"- {entry.get('file')}: {entry.get('description', '')}\n"

    report += f"""
---
Generiert: {datetime.now().isoformat()}
"""

    # Report speichern
    report_file = LOGS_DIR / f"{month}_docs_report.md"
    report_file.write_text(report, encoding='utf-8')
    print(f"[DOCS] Report gespeichert: {report_file}")

    return report


# ============ INTEGRATION ============

def log_wiki_article(article_path: str, title: str, action: str = "created"):
    """Convenience-Funktion fuer Wiki-Artikel."""
    log_change(
        file_path=article_path,
        action=action,
        description=f"Wiki-Artikel: {title}",
        author="wiki-author"
    )


def log_help_update(help_name: str, changes: str):
    """Convenience-Funktion fuer Help-Updates."""
    log_change(
        file_path=f"docs/help/{help_name}.txt",
        action="updated",
        description=changes,
        author="system"
    )


# ============ CLI ============

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python docs_changelog.py log FILE ACTION DESCRIPTION")
        print("  python docs_changelog.py show [COUNT]")
        print("  python docs_changelog.py report")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "log" and len(sys.argv) >= 5:
        log_change(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd == "show":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        show_recent(count)

    elif cmd == "report":
        report = generate_report()
        print(report)

    else:
        print("Unbekannter Befehl")
        sys.exit(1)
