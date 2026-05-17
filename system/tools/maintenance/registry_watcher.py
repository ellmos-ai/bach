#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Registry Watcher v1.1.3

Registry-Checks fuer das aktuelle BACH-Layout.

Features:
- Rekursive Dateisystem-Scans fuer `tools/` und `skills/`
- Trennung zwischen aktuellen Problemen und historischen/stalen DB-Eintraegen
- Reports fuer Wartung und Startup-Selbstcheck

Usage:
  python registry_watcher.py check              # Alle Registries pruefen
  python registry_watcher.py check --db         # Nur DB-Tabellen pruefen
  python registry_watcher.py report             # Health-Report speichern
  python registry_watcher.py tools              # Nur Tools pruefen
  python registry_watcher.py skills             # Nur Skills pruefen
  python registry_watcher.py agents             # Nur Agents pruefen
  python registry_watcher.py partners           # Nur Partner pruefen
  python registry_watcher.py check --json       # JSON-Ausgabe
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# Windows Console UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# Pfade - BACH v1.1
SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parent.parent  # tools/maintenance -> tools -> system
DATA_DIR = BACH_ROOT / "data"
DB_FILE = DATA_DIR / "bach.db"
REPORTS_DIR = BACH_ROOT / "logs"

TOOLS_DIR = BACH_ROOT / "tools"
SKILLS_DIR = BACH_ROOT / "skills"
AGENTS_DIR = BACH_ROOT / "agents"

IGNORED_DIR_NAMES = {"__pycache__", "node_modules", ".git", ".pytest_cache"}


class RegistryWatcher:
    """Layout-aware Registry-Konsistenzpruefung fuer BACH."""

    VERSION = "1.1.3"

    def __init__(self, db_path: Optional[Path] = None, base_path: Optional[Path] = None):
        candidate_db = Path(db_path) if db_path is not None else None
        if base_path is None and candidate_db is not None and candidate_db.is_dir():
            base_path = candidate_db
            candidate_db = None

        self.root = Path(base_path) if base_path is not None else BACH_ROOT
        fallback_db = self.root / "data" / "bach.db"
        self.db_path = (
            Path(candidate_db)
            if candidate_db is not None
            else self._resolve_canonical_db_path(fallback_db)
        )
        self.tools_dir = self.root / "tools"
        self.skills_dir = self.root / "skills"
        self.agents_dir = self.root / "agents"

    def _resolve_canonical_db_path(self, fallback_db: Path) -> Path:
        """Nutze fuer die echte BACH-Instanz denselben kanonischen DB-Pfad wie die Handler.

        Tests und isolierte Fixture-Roots bleiben bewusst bei ihrem lokalen
        `data/bach.db`, damit sie nicht aus Versehen auf die Live-DB zeigen.
        """
        try:
            if self.root.resolve() != BACH_ROOT.resolve():
                return fallback_db
        except OSError:
            return fallback_db

        inserted = False
        try:
            root_str = str(BACH_ROOT)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
                inserted = True
            from hub.bach_paths import BACH_DB

            return Path(BACH_DB)
        except Exception:
            return fallback_db
        finally:
            if inserted:
                try:
                    sys.path.remove(root_str)
                except ValueError:
                    pass

    def check_all(self) -> Dict:
        """Fuehrt die vollstaendige Registry-Pruefung aus."""
        checks = {
            "tools": self.check_tools(),
            "skills": self.check_skills(),
            "agents": self.check_agents(),
            "partners": self.check_partners(),
        }
        return {
            "timestamp": datetime.now().isoformat(),
            "version": self.VERSION,
            "checks": checks,
            "summary": self._build_summary(checks),
        }

    def check_database(self) -> Dict:
        """Prueft nur die fuer den Registry-Watcher relevanten DB-Tabellen."""
        required_tables = {
            "tools": "tools",
            "skills": "skills",
            "agents": "bach_agents",
            "partners": "partner_recognition",
        }

        result = {
            "timestamp": datetime.now().isoformat(),
            "version": self.VERSION,
            "mode": "db_only",
            "db_path": str(self.db_path),
            "tables": {},
            "summary": {
                "healthy": False,
                "tables_checked": len(required_tables),
                "tables_present": 0,
                "missing_tables": [],
                "recommendation": "",
            },
        }

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for label, table_name in required_tables.items():
                    cursor.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table' AND name = ?
                        """,
                        (table_name,),
                    )
                    exists = cursor.fetchone() is not None
                    rows = None
                    if exists:
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        rows = int(cursor.fetchone()[0])
                        result["summary"]["tables_present"] += 1
                    else:
                        result["summary"]["missing_tables"].append(table_name)

                    result["tables"][label] = {
                        "table": table_name,
                        "exists": exists,
                        "rows": rows,
                    }
        except Exception as exc:
            result["error"] = str(exc)
            result["summary"]["recommendation"] = "DB-Zugriff fehlgeschlagen"
            return result

        result["summary"]["healthy"] = not result["summary"]["missing_tables"]
        if result["summary"]["healthy"]:
            result["summary"]["recommendation"] = "Alle Registry-Tabellen vorhanden"
        else:
            missing = ", ".join(result["summary"]["missing_tables"])
            result["summary"]["recommendation"] = f"Fehlende Tabellen: {missing}"
        return result

    def check_tools(self) -> Dict:
        """Prueft die Tools-Registry gegen den rekursiven tools/-Baum."""
        result = self._base_result()

        try:
            rows = self._fetch_rows(
                """
                SELECT name, path, type, category, command, dist_type
                FROM tools
                WHERE is_available = 1
                """
            )
            fs_paths, fs_names = self._scan_tools()
            matched_paths = set()
            db_names = set()

            result["db_count"] = len(rows)
            result["fs_count"] = len(fs_paths)

            for row in rows:
                name = row["name"]
                db_names.add(name)
                rel_path = self._normalize_path(row["path"])

                if not rel_path:
                    result["external_entries"].append(self._entry(name, row["path"], reason="no_path"))
                    continue

                if self._is_absolute_outside_root(rel_path):
                    result["external_entries"].append(self._entry(name, rel_path, reason="absolute_external"))
                    continue

                if not rel_path.startswith("tools/"):
                    result["historical_entries"].append(self._entry(name, rel_path, reason="out_of_scope"))
                    continue

                result["managed_db_count"] += 1
                resolved = self._resolve_path(rel_path)
                if resolved.exists():
                    matched_paths.add(rel_path)
                    result["valid"].append(name)
                    continue

                candidates = fs_names.get(name, [])
                if candidates:
                    result["relocated_entries"].append(
                        self._entry(name, rel_path, reason="relocated", candidates=candidates)
                    )
                    matched_paths.update(candidates)
                else:
                    result["stale_db_entries"].append(self._entry(name, rel_path, reason="stale_db"))

            for rel_path, file_path in fs_paths.items():
                if rel_path in matched_paths:
                    continue
                if file_path.stem in db_names:
                    continue
                result["orphan_files"].append(rel_path)

        except Exception as exc:
            result["error"] = str(exc)

        return self._finalize_result(result)

    def check_skills(self) -> Dict:
        """Prueft die Skills-Registry gegen den aktuellen skills/-Sync-Scope."""
        result = self._base_result()

        try:
            rows = self._fetch_rows(
                """
                SELECT name, path, dist_type
                FROM skills
                WHERE path IS NOT NULL AND TRIM(path) != ''
                """
            )
            fs_paths, fs_names = self._scan_skills()
            matched_paths = set()
            db_names = set()

            result["db_count"] = len(rows)
            result["fs_count"] = len(fs_paths)

            for row in rows:
                name = row["name"]
                db_names.add(name)
                rel_path = self._normalize_path(row["path"])

                if not rel_path:
                    result["historical_entries"].append(self._entry(name, row["path"], reason="empty_path"))
                    continue

                if self._is_absolute_outside_root(rel_path):
                    result["external_entries"].append(self._entry(name, rel_path, reason="absolute_external"))
                    continue

                if not rel_path.startswith("skills/"):
                    result["historical_entries"].append(self._entry(name, rel_path, reason="outside_sync_scope"))
                    continue

                result["managed_db_count"] += 1
                resolved = self._resolve_path(rel_path)
                if resolved.exists():
                    matched_paths.add(rel_path)
                    result["valid"].append(name)
                    continue

                candidates = fs_names.get(Path(rel_path).stem, [])
                if candidates:
                    result["relocated_entries"].append(
                        self._entry(name, rel_path, reason="relocated", candidates=candidates)
                    )
                    matched_paths.update(candidates)
                else:
                    result["stale_db_entries"].append(self._entry(name, rel_path, reason="stale_db"))

            for rel_path, file_path in fs_paths.items():
                if rel_path in matched_paths:
                    continue
                if file_path.stem in db_names:
                    continue
                result["orphan_files"].append(rel_path)

        except Exception as exc:
            result["error"] = str(exc)

        return self._finalize_result(result)

    def check_agents(self) -> Dict:
        """Prueft die Agenten-Oberflaeche gegen die aktuelle bach_agents-Tabelle."""
        result = self._base_result()

        try:
            if self._table_exists("bach_agents"):
                rows = self._fetch_rows(
                    """
                    SELECT DISTINCT name, skill_path, is_active
                    FROM bach_agents
                    WHERE is_active = 1
                    """
                )
                table_name = "bach_agents+agents" if self._table_exists("agents") else "bach_agents"
                if self._table_exists("agents"):
                    legacy_rows = self._fetch_rows(
                        """
                        SELECT DISTINCT name, skill_path, is_active
                        FROM agents
                        WHERE is_active = 1
                        """
                    )
                    known_names = {row["name"] for row in rows}
                    rows.extend(row for row in legacy_rows if row["name"] not in known_names)
            else:
                table_name = "agents"
                rows = self._fetch_rows(
                    """
                    SELECT DISTINCT name, skill_path, is_active
                    FROM agents
                    WHERE is_active = 1
                    """
                )

            fs_paths, fs_names = self._scan_agents_surface()
            matched_paths = set()
            matched_names = set()

            result["table"] = table_name
            result["db_count"] = len(rows)
            result["fs_count"] = len(fs_paths)

            for row in rows:
                name = row["name"]
                rel_path = self._normalize_path(row["skill_path"])

                if rel_path and not self._is_absolute_outside_root(rel_path):
                    resolved = self._resolve_path(rel_path)
                    if resolved.exists():
                        matched_paths.add(rel_path)
                        matched_names.add(name)
                        result["managed_db_count"] += 1
                        result["valid"].append(name)
                        continue

                candidate_path = fs_names.get(name)
                if candidate_path:
                    matched_paths.add(candidate_path)
                    matched_names.add(name)
                    if rel_path:
                        result["relocated_entries"].append(
                            self._entry(name, rel_path, reason="relocated", candidates=[candidate_path])
                        )
                    else:
                        result["valid"].append(name)
                    continue

                if rel_path:
                    result["missing_files"].append(self._entry(name, rel_path, reason="missing_agent_path"))
                else:
                    result["historical_entries"].append(self._entry(name, None, reason="legacy_agent_without_path"))

            for rel_path in fs_paths:
                profile_name = Path(rel_path).stem if rel_path.endswith((".md", ".txt")) else Path(rel_path).name
                if rel_path in matched_paths or profile_name in matched_names:
                    continue
                result["historical_entries"].append(
                    self._entry(profile_name, rel_path, reason="unregistered_surface")
                )

        except Exception as exc:
            result["error"] = str(exc)

        return self._finalize_result(result)

    def check_partners(self) -> Dict:
        """Prueft die Partner-Registry auf Basiskonsistenz."""
        result = {
            "db_count": 0,
            "active_count": 0,
            "config_errors": [],
            "valid": [],
        }

        try:
            rows = self._fetch_rows(
                """
                SELECT partner_name, status, partner_type
                FROM partner_recognition
                """
            )
            result["db_count"] = len(rows)

            for row in rows:
                if row["status"] == "active":
                    result["active_count"] += 1
                    result["valid"].append(row["partner_name"])

        except Exception as exc:
            result["error"] = str(exc)

        return self._finalize_result(result)

    def generate_report(self, results: Optional[Dict] = None) -> str:
        """Generiert einen lesbaren Health-Report."""
        if results is None:
            results = self.check_all()

        lines = [
            "=" * 60,
            "BACH Registry Health Report",
            f"Zeitpunkt: {results['timestamp']}",
            f"Version: {results['version']}",
            "=" * 60,
            "",
        ]

        for category, check in results["checks"].items():
            lines.append(f"[{category.upper()}]")
            if "table" in check:
                lines.append(f"  Tabelle:      {check['table']}")
            lines.append(f"  DB-Eintraege: {check.get('db_count', 0)}")
            if "managed_db_count" in check:
                lines.append(f"  Managed:      {check.get('managed_db_count', 0)}")
            if "fs_count" in check:
                lines.append(f"  Dateisystem:  {check.get('fs_count', 0)}")
            if "active_count" in check:
                lines.append(f"  Aktiv:        {check.get('active_count', 0)}")

            actionable = self._actionable_count(check)
            stale = len(check.get("stale_db_entries", [])) + len(check.get("relocated_entries", []))
            ignored = len(check.get("historical_entries", [])) + len(check.get("external_entries", []))

            lines.append(f"  Actionable:   {actionable}")
            if stale:
                lines.append(f"  Stale/Move:   {stale}")
            if ignored:
                lines.append(f"  Historisch:   {ignored}")
            if check.get("valid"):
                lines.append(f"  OK:           {len(check['valid'])}")

            self._append_examples(lines, "missing_files", check, label="Missing")
            self._append_examples(lines, "orphan_files", check, label="Orphan FS")
            self._append_examples(lines, "stale_db_entries", check, label="Stale DB")
            self._append_examples(lines, "relocated_entries", check, label="Moved")
            self._append_examples(lines, "historical_entries", check, label="Historical")
            self._append_examples(lines, "external_entries", check, label="External")

            if check.get("error"):
                lines.append(f"  Error:        {check['error']}")

            lines.append("")

        summary = results.get("summary", {})
        lines.append("-" * 60)
        status = "HEALTHY" if summary.get("healthy") else "ISSUES FOUND"
        lines.append(f"Status: {status}")
        lines.append(f"Actionable Issues: {summary.get('actionable_issues', 0)}")
        lines.append(f"Stale Entries:     {summary.get('stale_entries', 0)}")
        lines.append(f"Ignored History:   {summary.get('ignored_entries', 0)}")
        lines.append("-" * 60)

        return "\n".join(lines)

    def save_report(self, filepath: Optional[Path] = None) -> Path:
        """Speichert Report als TXT + JSON."""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = REPORTS_DIR / f"registry_health_{timestamp}.txt"

        REPORTS_DIR.mkdir(exist_ok=True)

        results = self.check_all()
        filepath.write_text(self.generate_report(results), encoding="utf-8")
        filepath.with_suffix(".json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return filepath

    def generate_db_report(self, results: Dict) -> str:
        """Formatiert den DB-Only-Check fuer die CLI."""
        lines = [
            "[REGISTRY-DB] Datenbank-Check",
            f"  DB: {results.get('db_path')}",
        ]

        for label, info in results.get("tables", {}).items():
            status = "OK" if info.get("exists") else "FEHLT"
            row_info = ""
            if info.get("exists"):
                row_info = f" ({info.get('rows', 0)} Zeilen)"
            lines.append(f"  [{status}] {label}: {info.get('table')}{row_info}")

        if results.get("error"):
            lines.append(f"  [ERROR] {results['error']}")

        summary = results.get("summary", {})
        lines.append(
            "  Zusammenfassung: "
            f"{summary.get('tables_present', 0)}/{summary.get('tables_checked', 0)} Tabellen vorhanden"
        )
        lines.append(f"  Empfehlung: {summary.get('recommendation', '')}")
        return "\n".join(lines)

    def _build_summary(self, checks: Dict[str, Dict]) -> Dict:
        actionable = 0
        stale = 0
        ignored = 0
        has_errors = False

        for check in checks.values():
            actionable += self._actionable_count(check)
            stale += len(check.get("stale_db_entries", [])) + len(check.get("relocated_entries", []))
            ignored += len(check.get("historical_entries", [])) + len(check.get("external_entries", []))
            if check.get("error"):
                has_errors = True

        healthy = actionable == 0 and not has_errors
        if healthy and stale == 0 and ignored == 0:
            recommendation = "Alles OK"
        elif healthy:
            recommendation = (
                f"Keine aktuellen Probleme. {stale} stale und {ignored} historische Eintraege "
                "optional bereinigen."
            )
        else:
            recommendation = f"{actionable} aktuelle Probleme gefunden"

        return {
            "total_issues": actionable,
            "actionable_issues": actionable,
            "stale_entries": stale,
            "ignored_entries": ignored,
            "healthy": healthy,
            "recommendation": recommendation,
        }

    def _actionable_count(self, check: Dict) -> int:
        count = len(check.get("missing_files", []))
        count += len(check.get("orphan_files", []))
        count += len(check.get("config_errors", []))
        if check.get("error"):
            count += 1
        return count

    def _base_result(self) -> Dict:
        return {
            "db_count": 0,
            "managed_db_count": 0,
            "fs_count": 0,
            "missing_files": [],
            "orphan_files": [],
            "stale_db_entries": [],
            "relocated_entries": [],
            "historical_entries": [],
            "external_entries": [],
            "valid": [],
        }

    def _finalize_result(self, result: Dict) -> Dict:
        """Entfernt Mehrfacheintraege aus den Ergebnislisten, ohne die Reihenfolge zu verlieren."""
        result["valid"] = self._dedupe_strings(result.get("valid", []))
        result["orphan_files"] = self._dedupe_strings(result.get("orphan_files", []))
        result["config_errors"] = self._dedupe_strings(result.get("config_errors", []))

        entry_keys = (
            "missing_files",
            "stale_db_entries",
            "relocated_entries",
            "historical_entries",
            "external_entries",
        )
        for key in entry_keys:
            result[key] = self._dedupe_entries(result.get(key, []))

        return result

    def _dedupe_strings(self, values: Iterable[str]) -> List[str]:
        """Dedupe fuer einfache String-Listen."""
        seen = set()
        deduped: List[str] = []
        for value in values or []:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _dedupe_entries(self, entries: Iterable[Dict]) -> List[Dict]:
        """Dedupe fuer strukturierte Registry-Eintraege."""
        seen = set()
        deduped: List[Dict] = []

        for entry in entries or []:
            if isinstance(entry, str):
                key = ("__string__", entry)
                normalized_entry = entry
            else:
                normalized_entry = dict(entry)
                candidates = tuple(self._dedupe_strings(normalized_entry.get("candidates") or []))
                if candidates:
                    normalized_entry["candidates"] = list(candidates)
                else:
                    normalized_entry.pop("candidates", None)
                key = (
                    normalized_entry.get("name"),
                    normalized_entry.get("expected_path"),
                    normalized_entry.get("reason"),
                    candidates,
                )

            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized_entry)

        return deduped

    def _fetch_rows(self, query: str) -> List[sqlite3.Row]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query)
            return cursor.fetchall()

    def _table_exists(self, table_name: str) -> bool:
        rows = self._fetch_rows(
            f"""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = '{table_name}'
            """
        )
        return bool(rows)

    def _scan_tools(self) -> Tuple[Dict[str, Path], Dict[str, List[str]]]:
        return self._scan_tree(
            self.tools_dir,
            extensions={".py"},
            include_file=self._include_tool_file,
        )

    def _scan_skills(self) -> Tuple[Dict[str, Path], Dict[str, List[str]]]:
        return self._scan_tree(
            self.skills_dir,
            extensions={".md", ".txt", ".py"},
            include_file=self._include_skill_file,
        )

    def _scan_tree(
        self,
        root: Path,
        extensions: Iterable[str],
        include_file,
    ) -> Tuple[Dict[str, Path], Dict[str, List[str]]]:
        files_by_path: Dict[str, Path] = {}
        files_by_name: Dict[str, List[str]] = defaultdict(list)

        if not root.exists():
            return files_by_path, files_by_name

        normalized_extensions = {ext.lower() for ext in extensions}
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in IGNORED_DIR_NAMES for part in file_path.parts):
                continue
            if file_path.suffix.lower() not in normalized_extensions:
                continue
            if not include_file(file_path):
                continue

            rel_path = file_path.relative_to(self.root).as_posix()
            files_by_path[rel_path] = file_path
            files_by_name[file_path.stem].append(rel_path)

        return files_by_path, files_by_name

    def _scan_agents_surface(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        files_by_path: Dict[str, str] = {}
        files_by_name: Dict[str, str] = {}

        if not self.agents_dir.exists():
            return files_by_path, files_by_name

        for entry in self.agents_dir.iterdir():
            if entry.name.startswith((".", "_")) or entry.name == "personas":
                continue

            if entry.is_file() and entry.suffix.lower() in {".md", ".txt"}:
                if entry.stem == "README":
                    continue
                rel_path = entry.relative_to(self.root).as_posix()
                files_by_path[rel_path] = rel_path
                files_by_name[entry.stem] = rel_path
                continue

            if entry.is_dir():
                skill_file = entry / "SKILL.md"
                if skill_file.exists():
                    rel_path = skill_file.relative_to(self.root).as_posix()
                    files_by_path[rel_path] = rel_path
                    files_by_name[entry.name] = rel_path

        return files_by_path, files_by_name

    def _include_tool_file(self, file_path: Path) -> bool:
        return file_path.name != "__init__.py" and not file_path.name.startswith(("_", "."))

    def _include_skill_file(self, file_path: Path) -> bool:
        if file_path.name.startswith("."):
            return False
        if file_path.name == "__init__.py":
            return False
        if file_path.name.startswith("_") and file_path.suffix.lower() != ".py":
            return False
        return True

    def _normalize_path(self, raw_path: Optional[str]) -> Optional[str]:
        if raw_path is None:
            return None

        text = str(raw_path).strip()
        if not text:
            return None

        text = text.replace("\\", "/")
        if text.startswith("./"):
            text = text[2:]

        path_obj = Path(text)
        if path_obj.is_absolute():
            try:
                return path_obj.relative_to(self.root).as_posix()
            except ValueError:
                return path_obj.as_posix()

        return text

    def _resolve_path(self, rel_path: str) -> Path:
        path_obj = Path(rel_path)
        if path_obj.is_absolute():
            return path_obj
        return self.root / rel_path

    def _is_absolute_outside_root(self, rel_path: str) -> bool:
        path_obj = Path(rel_path)
        if not path_obj.is_absolute():
            return False
        try:
            path_obj.relative_to(self.root)
            return False
        except ValueError:
            return True

    def _entry(
        self,
        name: str,
        expected_path: Optional[str],
        *,
        reason: str,
        candidates: Optional[List[str]] = None,
    ) -> Dict:
        entry = {
            "name": name,
            "expected_path": expected_path,
            "reason": reason,
        }
        if candidates:
            entry["candidates"] = candidates
        return entry

    def _append_examples(self, lines: List[str], key: str, check: Dict, *, label: str) -> None:
        items = check.get(key) or []
        for item in items[:3]:
            if isinstance(item, str):
                lines.append(f"  {label}: {item}")
                continue

            name = item.get("name") or item.get("expected_path") or "?"
            expected = item.get("expected_path")
            if expected:
                lines.append(f"  {label}: {name} -> {expected}")
            else:
                lines.append(f"  {label}: {name}")

            candidates = item.get("candidates") or []
            if candidates:
                lines.append(f"    Kandidaten: {', '.join(candidates[:3])}")


def main() -> None:
    """CLI Entry Point."""
    parser = argparse.ArgumentParser(description="BACH Registry Watcher")
    parser.add_argument(
        "command",
        nargs="?",
        default="check",
        choices=["check", "report", "tools", "skills", "agents", "partners"],
        help="Befehl",
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help="Nur die Registry-relevanten DB-Tabellen pruefen",
    )
    parser.add_argument("--json", action="store_true", help="JSON-Ausgabe")
    args = parser.parse_args()

    if args.db and args.command != "check":
        parser.error("--db ist nur mit 'check' verfuegbar.")

    watcher = RegistryWatcher()

    if args.command == "check":
        if args.db:
            results = watcher.check_database()
            print(
                json.dumps(results, indent=2, ensure_ascii=False)
                if args.json
                else watcher.generate_db_report(results)
            )
            return
        results = watcher.check_all()
        print(json.dumps(results, indent=2, ensure_ascii=False) if args.json else watcher.generate_report(results))
        return

    if args.command == "report":
        filepath = watcher.save_report()
        print(f"[OK] Report gespeichert: {filepath}")
        return

    result = getattr(watcher, f"check_{args.command}")()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    actionable = watcher._actionable_count(result)
    stale = len(result.get("stale_db_entries", [])) + len(result.get("relocated_entries", []))
    ignored = len(result.get("historical_entries", [])) + len(result.get("external_entries", []))
    print(f"[{args.command.upper()}] DB: {result.get('db_count', 0)} | FS: {result.get('fs_count', 0)}")
    if "managed_db_count" in result:
        print(f"  Managed: {result.get('managed_db_count', 0)}")
    print(f"  Actionable: {actionable}")
    if stale:
        print(f"  Stale/Move: {stale}")
    if ignored:
        print(f"  Historisch/Extern: {ignored}")
    if result.get("error"):
        print(f"  Error: {result['error']}")


if __name__ == "__main__":
    main()
