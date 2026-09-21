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

Git-Fallback (v1.1):
  Wenn das manuelle Log leer ist, leiten show/report Aenderungen
  automatisch aus der Git-Historie ab (letzte 30 Tage, docs/help + wiki).
  Manuelles Loggen via "log" hat weiterhin Vorrang.
"""

import json
import re
import subprocess
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


# ============ GIT-FALLBACK (v1.1) ============

GIT_FALLBACK_DAYS = 30

GIT_ACTION_MAP = {
    "A": "created",
    "C": "created",
    "M": "updated",
    "D": "deleted",
    "R": "moved",
    "T": "updated",
}


def _git_repo_prefix() -> Optional[str]:
    """
    Relativer Pfad vom Git-Repo-Root zu BACH_DIR ('' wenn identisch).

    Returns:
        '' wenn BACH_DIR == Repo-Root, sonst Praefix wie 'system',
        oder None wenn BACH_DIR ausserhalb eines Git-Repos liegt.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(BACH_DIR), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        repo_root = Path(result.stdout.strip()).resolve()
        bach = BACH_DIR.resolve()
        if bach == repo_root:
            return ""
        if repo_root in bach.parents:
            return str(bach.relative_to(repo_root))
    except (ValueError, OSError):
        pass
    return None


def git_fallback_entries(days: int = GIT_FALLBACK_DAYS) -> List[Dict]:
    """
    Leitet Changelog-Eintraege aus der Git-Historie ab (Fallback-Quelle).

    Additiv: Wird nur genutzt, wenn das manuelle Log leer ist.
    Liest git log --since=<days> -- docs/help wiki im BACH_DIR.

    Args:
        days: Zeitfenster in Tagen (Standard 30)

    Returns:
        Liste von Entries im gleichen Format wie das manuelle Log
        (chronologisch, aelteste zuerst), bei Fehlern eine leere Liste.
    """
    if _git_repo_prefix() is None:
        return []

    try:
        result = subprocess.run(
            ["git", "-C", str(BACH_DIR), "log",
             f"--since={days} days ago",
             "--name-status",
             "--pretty=format:%h|%ad|%an|%s",
             "--date=short",
             "--", "docs/help", "wiki"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    prefix = _git_repo_prefix() or ""
    header_re = re.compile(r"^[0-9a-f]{7,40}\|")
    status_re = re.compile(r"^([A-Z]\d*)\t(.+)$")

    entries: List[Dict] = []
    commit = None  # (timestamp, author, subject)

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        if header_re.match(line):
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commit = (parts[1], parts[2], parts[3])
            continue
        match = status_re.match(line)
        if match and commit:
            status, rest = match.group(1), match.group(2)
            action = GIT_ACTION_MAP.get(status[0], "updated")
            # Rename (R100\told\tnew): neue Datei dokumentieren
            file_path = rest.split("\t")[-1] if status[0] == "R" else rest
            if prefix and file_path.startswith(prefix + "/"):
                file_path = file_path[len(prefix) + 1:]
            entries.append({
                "timestamp": f"{commit[0]}T00:00:00",
                "file": file_path,
                "action": action,
                "description": commit[2],
                "author": commit[1],
                "source": "git",
            })

    # Chronologisch wie das manuelle Log: aelteste zuerst
    entries.reverse()
    return entries


# ============ REPORTS ============

def show_recent(count: int = 10) -> List[Dict]:
    """Zeigt die letzten N Aenderungen (git-Fallback, wenn Log leer)."""
    log_data = load_log()
    entries = log_data.get("entries", [])
    source = "Log"

    if not entries:
        entries = git_fallback_entries()
        source = f"git-Fallback (letzte {GIT_FALLBACK_DAYS} Tage)"

    recent = entries[-count:] if entries else []
    recent.reverse()  # Neueste zuerst

    print(f"[DOCS] Letzte {len(recent)} Aenderungen ({source}):")
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
    """Generiert einen Monatsbericht (git-Fallback, wenn Log leer)."""
    log_data = load_log()
    entries = log_data.get("entries", [])
    source_label = "Manuelles Log"

    if not entries:
        entries = git_fallback_entries()
        source_label = f"Git-Fallback (letzte {GIT_FALLBACK_DAYS} Tage)"

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

- Quelle: {source_label}
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
