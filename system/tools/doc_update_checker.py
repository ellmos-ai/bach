#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: doc_update_checker
Version: 1.1.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-05-15
Anthropic-Compatible: True

Description:
    Prüft BACH-Dokumentation dateibasiert auf Alter, veraltete Pfade
    und grobe Strukturprobleme und kann sichere Pfadkorrekturen anwenden.

Usage:
    python doc_update_checker.py [check|report|auto-update|schedule]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__version__ = "1.1.0"
__author__ = "BACH Team"


def _configure_windows_stdio() -> None:
    """Aktiviert UTF-8 nur für echte CLI-Läufe, nicht beim Import in Tests."""
    if sys.platform != "win32":
        return
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass


SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parent
DATA_DIR = BACH_ROOT / "data"
DB_FILE = DATA_DIR / "bach.db"
REPORTS_DIR = BACH_ROOT / "logs"

OUTDATED_DAYS = 60
WARNING_DAYS = 30
CRITICAL_DAYS = 90

STATIC_PATH_MIGRATIONS: List[Tuple[str, str]] = [
    ("scripts/", "tools/"),
    ("scripts\\", "tools\\"),
    ("skills/_connectors/", "connectors/"),
    ("skills\\_connectors\\", "connectors\\"),
    ("skills/_agents/ati/", "agents/ati/"),
    ("skills\\_agents\\ati\\", "agents\\ati\\"),
    ("skills/_agents/", "agents/"),
    ("skills\\_agents\\", "agents\\"),
    ("skills/_experts/", "agents/_experts/"),
    ("skills\\_experts\\", "agents\\_experts\\"),
    ("skills/_workflows/", "skills/workflows/"),
    ("skills\\_workflows\\", "skills\\workflows\\"),
    ("skills/_partners/", "partners/"),
    ("skills\\_partners\\", "partners\\"),
    ("system/help/wiki/", "system/wiki/"),
    ("system\\help\\wiki\\", "system\\wiki\\"),
]

DOC_SCAN_SPECS: List[Tuple[str, Tuple[str, ...]]] = [
    ("docs", ("*.md", "*.txt")),
    ("agents", ("*.md", "*.txt")),
    ("hub/_services", ("*.md", "*.txt")),
    ("skills/_services", ("*.md", "*.txt")),
    ("skills/workflows", ("*.md", "*.txt")),
    ("wiki", ("*.md", "*.txt")),
]

ROOT_DOCS = ("SKILL.md", "README.md", "README.de.md", "ROADMAP.md", "CHANGELOG.md", "BUGLOG.md")
VERSION_PATTERN = re.compile(r"[vV]?(\d+\.\d+\.\d+)")


class DocUpdateChecker:
    """Dateibasierte Dokumentationsprüfung für BACH."""

    VERSION = "1.1.0"

    def __init__(self, db_path: Optional[Path] = None, base_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else DB_FILE
        self.root = Path(base_path) if base_path is not None else BACH_ROOT
        self.reports_dir = self.root / "logs"

    def check_all(self) -> Dict:
        """Führt die vollständige Prüfung durch."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "total_docs": 0,
            "outdated": [],
            "invalid_paths": [],
            "version_mismatch": [],
            "missing_sections": [],
            "suggestions": [],
        }

        docs = self._get_all_docs()
        results["total_docs"] = len(docs)

        for doc in docs:
            age_issue = self._check_age(doc)
            if age_issue:
                results["outdated"].append(age_issue)

            results["invalid_paths"].extend(self._check_paths_in_doc(doc))

            if doc.get("doc_type") == "skill":
                version_issue = self._check_version(doc)
                if version_issue:
                    results["version_mismatch"].append(version_issue)

            results["missing_sections"].extend(self._check_required_sections(doc))

        results["suggestions"] = self._generate_suggestions(results)
        return results

    def _get_all_docs(self) -> List[Dict]:
        """Sammelt relevante Doku-Dateien aus dem aktuellen BACH-Layout."""
        docs: List[Dict] = []
        seen_paths = set()

        for subdir, patterns in DOC_SCAN_SPECS:
            search_path = self.root / subdir
            if not search_path.exists():
                continue

            for pattern in patterns:
                for doc_file in search_path.rglob(pattern):
                    if self._should_skip(doc_file):
                        continue

                    rel_path = doc_file.relative_to(self.root)
                    rel_key = rel_path.as_posix()
                    if rel_key in seen_paths:
                        continue
                    seen_paths.add(rel_key)

                    docs.append(
                        {
                            "path": rel_key,
                            "absolute_path": str(doc_file),
                            "doc_type": self._classify_doc(doc_file, rel_path),
                            "name": doc_file.stem,
                        }
                    )

        for root_doc in ROOT_DOCS:
            root_file = self.root / root_doc
            if not root_file.exists():
                continue
            docs.append(
                {
                    "path": root_doc,
                    "absolute_path": str(root_file),
                    "doc_type": self._classify_doc(root_file, Path(root_doc)),
                    "name": root_file.stem,
                }
            )

        return docs

    def _should_skip(self, path: Path) -> bool:
        path_str = str(path)
        return "_archive" in path_str or "__pycache__" in path_str

    def _classify_doc(self, absolute_path: Path, rel_path: Path) -> str:
        rel_parts = rel_path.parts
        if len(rel_parts) >= 2 and rel_parts[0] == "docs" and rel_parts[1] == "help":
            return "help"
        if absolute_path.name.upper() == "SKILL.MD":
            return "skill"
        if absolute_path.name.upper().startswith("README"):
            return "readme"
        if absolute_path.suffix.lower() == ".txt":
            return "help"
        return "guide"

    def _check_age(self, doc: Dict) -> Optional[Dict]:
        if not doc.get("path"):
            return None

        full_path = self.root / doc["path"]
        if not full_path.exists():
            return None

        try:
            mtime = datetime.fromtimestamp(full_path.stat().st_mtime)
            age_days = (datetime.now() - mtime).days
        except OSError:
            return None

        if age_days > CRITICAL_DAYS:
            severity = "critical"
        elif age_days > OUTDATED_DAYS:
            severity = "warning"
        else:
            return None

        return {
            "path": doc["path"],
            "doc_type": doc.get("doc_type"),
            "age_days": age_days,
            "last_modified": mtime.isoformat(),
            "severity": severity,
        }

    def _check_paths_in_doc(self, doc: Dict) -> List[Dict]:
        issues: List[Dict] = []

        if not doc.get("path"):
            return issues

        full_path = self.root / doc["path"]
        if not full_path.exists():
            return issues

        try:
            content = full_path.read_text(encoding="utf-8")
        except OSError:
            return issues

        for invalid_path, correct_path in self._collect_fixable_paths(content):
            issues.append(
                {
                    "doc_path": doc["path"],
                    "invalid_path": invalid_path,
                    "correct_path": correct_path,
                    "auto_fixable": True,
                }
            )

        win_paths = re.findall(r'C:\[^"\s\n]+', content)
        for win_path in win_paths:
            clean_path = win_path.rstrip(r"\.,;:")
            if "BACH" in clean_path and not Path(clean_path).exists():
                issues.append(
                    {
                        "doc_path": doc["path"],
                        "invalid_path": clean_path,
                        "correct_path": None,
                        "auto_fixable": False,
                        "note": "Pfad existiert nicht mehr",
                    }
                )

        return issues

    def _collect_fixable_paths(self, content: str) -> List[Tuple[str, str]]:
        """Sammelt konkrete, sicher ersetzbare Altpfade."""
        fixes: List[Tuple[str, str]] = []
        seen = set()

        def add(old_path: str, new_path: str) -> None:
            if old_path not in content:
                return
            key = (old_path, new_path)
            if key in seen:
                return
            seen.add(key)
            fixes.append(key)

        for old_path, new_path in STATIC_PATH_MIGRATIONS:
            add(old_path, new_path)

        hub_services_dir = self.root / "hub" / "_services"
        if hub_services_dir.exists():
            for service_dir in hub_services_dir.iterdir():
                if not service_dir.is_dir():
                    continue
                service_name = service_dir.name
                add(
                    f"skills/_services/{service_name}/",
                    f"hub/_services/{service_name}/",
                )
                add(
                    f"skills\\_services\\{service_name}\\",
                    f"hub\\_services\\{service_name}\\",
                )

        for match in re.finditer(r"(?:hub/)?handlers/([A-Za-z0-9_-]+)\.py", content):
            handler_name = match.group(1)
            if (self.root / "hub" / f"{handler_name}.py").exists():
                add(match.group(0), f"hub/{handler_name}.py")

        for match in re.finditer(r"(?:hub\\)?handlers\\([A-Za-z0-9_-]+)\.py", content):
            handler_name = match.group(1)
            if (self.root / "hub" / f"{handler_name}.py").exists():
                add(match.group(0), f"hub\\{handler_name}.py")

        fixes.sort(key=lambda item: len(item[0]), reverse=True)
        return fixes

    def _check_version(self, doc: Dict) -> Optional[Dict]:
        if not doc.get("path"):
            return None

        full_path = self.root / doc["path"]
        if not full_path.exists():
            return None

        try:
            content = full_path.read_text(encoding="utf-8")
        except OSError:
            return None

        if VERSION_PATTERN.search(content[:500]):
            return None
        return None

    def _check_required_sections(self, doc: Dict) -> List[Dict]:
        issues: List[Dict] = []

        if not doc.get("path"):
            return issues

        full_path = self.root / doc["path"]
        if not full_path.exists():
            return issues

        required_sections = {
            "skill": ["## Übersicht", "## CLI-Befehle", "## Dateien"],
            "readme": ["## Installation", "## Usage"],
            "guide": ["## Einleitung", "## Schritte"],
        }

        doc_type = doc.get("doc_type", "")
        if doc_type not in required_sections:
            return issues

        try:
            content = full_path.read_text(encoding="utf-8")
        except OSError:
            return issues

        for section in required_sections[doc_type]:
            pattern = section.replace("## ", "").lower()
            if pattern not in content.lower():
                issues.append(
                    {
                        "doc_path": doc["path"],
                        "doc_type": doc_type,
                        "missing_section": section,
                        "auto_fixable": False,
                    }
                )

        return issues

    def _generate_suggestions(self, results: Dict) -> List[Dict]:
        suggestions = []

        for doc in results["outdated"]:
            if doc["severity"] == "critical":
                suggestions.append(
                    {
                        "priority": "high",
                        "action": "review_and_update",
                        "target": doc["path"],
                        "reason": f"Dokument seit {doc['age_days']} Tagen nicht aktualisiert",
                        "suggestion": "Inhalt prüfen und aktualisieren oder als veraltet markieren",
                    }
                )
            else:
                suggestions.append(
                    {
                        "priority": "medium",
                        "action": "check",
                        "target": doc["path"],
                        "reason": f"Dokument seit {doc['age_days']} Tagen nicht aktualisiert",
                        "suggestion": "Bei nächster Gelegenheit prüfen",
                    }
                )

        auto_fixable = [path_info for path_info in results["invalid_paths"] if path_info.get("auto_fixable")]
        if auto_fixable:
            suggestions.append(
                {
                    "priority": "high",
                    "action": "auto_fix_paths",
                    "targets": [path_info["doc_path"] for path_info in auto_fixable],
                    "count": len(auto_fixable),
                    "suggestion": f"{len(auto_fixable)} Pfade können automatisch korrigiert werden",
                }
            )

        return suggestions

    def auto_fix_paths(self, dry_run: bool = True) -> List[Dict]:
        fixed = []

        for doc in self._get_all_docs():
            if not doc.get("path"):
                continue

            full_path = self.root / doc["path"]
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"[WARN] Fehler bei {doc['path']}: {exc}")
                continue

            original = content
            replacements = self._collect_fixable_paths(content)
            for old_path, new_path in replacements:
                if old_path in content:
                    content = content.replace(old_path, new_path)

            if content == original:
                continue

            if not dry_run:
                full_path.write_text(content, encoding="utf-8")

            fixed.append(
                {
                    "path": doc["path"],
                    "changes": sum(original.count(old_path) for old_path, _new_path in replacements),
                    "applied": not dry_run,
                }
            )

        return fixed

    def update_timestamps(self) -> int:
        print("[INFO] update_timestamps() ist jetzt no-op (dateibasierte Prüfung)")
        return 0

    def generate_report(self, results: Optional[Dict] = None) -> Path:
        if results is None:
            results = self.check_all()

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        report_path = self.reports_dir / f"Doc_Update_Report_{timestamp}.md"

        lines = [
            "# Dokumentations-Update Report",
            f"\n**Erstellt:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Geprüfte Dokumente:** {results['total_docs']}",
            "",
            "---",
            "",
            "## Zusammenfassung",
            "",
            "| Kategorie | Anzahl |",
            "|-----------|--------|",
            f"| Veraltet (>{OUTDATED_DAYS} Tage) | {len(results['outdated'])} |",
            f"| Ungültige Pfade | {len(results['invalid_paths'])} |",
            f"| Fehlende Sektionen | {len(results['missing_sections'])} |",
            f"| Vorschläge | {len(results['suggestions'])} |",
            "",
        ]

        if results["outdated"]:
            lines.extend(["## Veraltete Dokumente", ""])

            critical = [doc for doc in results["outdated"] if doc["severity"] == "critical"]
            warning = [doc for doc in results["outdated"] if doc["severity"] == "warning"]

            if critical:
                lines.extend(["### Kritisch (>90 Tage)", ""])
                for doc in critical:
                    lines.append(f"- **{doc['path']}** ({doc['age_days']} Tage)")
                lines.append("")

            if warning:
                lines.extend(["### Warnung (>60 Tage)", ""])
                for doc in warning:
                    lines.append(f"- {doc['path']} ({doc['age_days']} Tage)")
                lines.append("")

        if results["invalid_paths"]:
            lines.extend(["## Ungültige Pfade in Dokumenten", ""])

            auto_fix = [path_info for path_info in results["invalid_paths"] if path_info.get("auto_fixable")]
            manual = [path_info for path_info in results["invalid_paths"] if not path_info.get("auto_fixable")]

            if auto_fix:
                lines.extend(["### Automatisch korrigierbar", ""])
                for path_info in auto_fix:
                    lines.append(f"- `{path_info['doc_path']}`")
                    lines.append(f"  - `{path_info['invalid_path']}` → `{path_info['correct_path']}`")
                lines.append("")

            if manual:
                lines.extend(["### Manuelle Prüfung erforderlich", ""])
                for path_info in manual:
                    lines.append(f"- `{path_info['doc_path']}`: `{path_info['invalid_path']}`")
                lines.append("")

        if results["suggestions"]:
            lines.extend(["## Empfohlene Aktionen", ""])
            for index, suggestion in enumerate(results["suggestions"], 1):
                priority_emoji = "🔴" if suggestion["priority"] == "high" else "🟡"
                lines.append(f"{index}. {priority_emoji} **{suggestion['action']}**")
                lines.append(f"   - {suggestion['suggestion']}")
                if suggestion.get("target"):
                    lines.append(f"   - Ziel: `{suggestion['target']}`")
                lines.append("")

        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    def schedule_output(self) -> Dict:
        results = self.check_all()
        output = {"has_issues": False, "summary": "", "actions": []}

        total_issues = (
            len(results["outdated"])
            + len(results["invalid_paths"])
            + len(results["missing_sections"])
        )

        if total_issues <= 0:
            return output

        output["has_issues"] = True
        parts = []

        if results["outdated"]:
            critical = len([doc for doc in results["outdated"] if doc["severity"] == "critical"])
            if critical:
                parts.append(f"{critical} kritisch veraltet")
            else:
                parts.append(f"{len(results['outdated'])} veraltet")

        if results["invalid_paths"]:
            parts.append(f"{len(results['invalid_paths'])} ungültige Pfade")

        output["summary"] = f"📄 Dokumentation: {', '.join(parts)}"

        auto_fixable = [path_info for path_info in results["invalid_paths"] if path_info.get("auto_fixable")]
        if auto_fixable:
            output["actions"].append(
                {
                    "type": "auto_fix",
                    "command": "python doc_update_checker.py auto-update",
                    "description": f"{len(auto_fixable)} Pfade automatisch korrigieren",
                }
            )

        return output


def main() -> None:
    _configure_windows_stdio()
    parser = argparse.ArgumentParser(description="Documentation Update Checker")
    parser.add_argument("command", nargs="?", default="check", help="Befehl: check, report, auto-update, schedule")
    parser.add_argument("--dry-run", action="store_true", help="Nur simulieren")
    parser.add_argument("--json", action="store_true", help="JSON-Ausgabe")

    args = parser.parse_args()
    cmd = args.command.lower()
    checker = DocUpdateChecker()

    if cmd == "check":
        results = checker.check_all()

        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
            return

        print(f"\n{'=' * 60}")
        print("  DOKUMENTATIONSPRÜFUNG")
        print(f"{'=' * 60}")
        print(f"  Dokumente geprüft:   {results['total_docs']}")
        print(f"  Veraltet:            {len(results['outdated'])}")
        print(f"  Ungültige Pfade:     {len(results['invalid_paths'])}")
        print(f"  Fehlende Sektionen:  {len(results['missing_sections'])}")
        print(f"  Vorschläge:          {len(results['suggestions'])}")

        if results["outdated"]:
            print("\n  ⚠️ VERALTETE DOKUMENTE:")
            for doc in results["outdated"][:5]:
                emoji = "🔴" if doc["severity"] == "critical" else "🟡"
                print(f"    {emoji} {doc['path']} ({doc['age_days']}d)")
            if len(results["outdated"]) > 5:
                print(f"    ... und {len(results['outdated']) - 5} weitere")

        if results["suggestions"]:
            print("\n  💡 EMPFEHLUNGEN:")
            for suggestion in results["suggestions"][:3]:
                print(f"    - {suggestion['suggestion']}")

    elif cmd == "report":
        report_path = checker.generate_report()
        print(f"\n✅ Report erstellt: {report_path}")

    elif cmd in ["auto-update", "auto-fix"]:
        dry_run = args.dry_run
        print(f"\n[AUTO-UPDATE] {'[DRY-RUN]' if dry_run else '[LIVE]'}")

        fixed = checker.auto_fix_paths(dry_run=dry_run)
        print(f"  Pfad-Korrekturen: {len(fixed)}")

        for item in fixed[:5]:
            status = "würde" if dry_run else "wurde"
            print(f"    - {item['path']} ({item['changes']} Änderungen {status} angewendet)")

        if not dry_run:
            updated = checker.update_timestamps()
            print(f"  DB-Einträge aktualisiert: {updated}")

        print(f"\n✅ Auto-Update {'simuliert' if dry_run else 'abgeschlossen'}")

    elif cmd == "schedule":
        output = checker.schedule_output()
        if args.json:
            print(json.dumps(output, ensure_ascii=False))
        elif output["has_issues"]:
            print(output["summary"])
            for action in output["actions"]:
                print(f"  → {action['description']}")
        else:
            print("✅ Dokumentation aktuell")

    elif cmd in ["help", "-h", "--help"]:
        print(
            """
Documentation Update Checker - Befehle:

  check                 Prüft alle Dokumentationen
  check --json          Prüfung mit JSON-Ausgabe

  report                Erstellt Markdown-Report

  auto-update           Korrigiert automatisch (Pfade)
  auto-update --dry-run Nur simulieren

  schedule              Ausgabe für Micro-Routines
  schedule --json       JSON für automatische Verarbeitung
            """.strip()
        )
    else:
        print(f"[ERR] Unbekannter Befehl: {cmd}")


if __name__ == "__main__":
    main()
