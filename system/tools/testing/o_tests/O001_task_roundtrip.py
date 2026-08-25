#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""O001 - Task-Roundtrip.

Für BACH wird der produktive Task-API-Lebenszyklus gegen eine temporäre, über
``BACH_DB`` gesetzte Datenbank geprüft. Andere Systeme behalten den bisherigen
dateibasierten Infrastruktur-Fallback.
"""

import gc
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def _base_result(root: Path) -> dict:
    return {
        "system_path": str(root),
        "test_date": datetime.now().isoformat(),
        "test_id": "O001",
        "test_name": "Task-Roundtrip",
        "checks": [],
        "status": "UNKNOWN",
        "score": 0.0,
    }


def _finish_result(result: dict, checks_passed: int, total_checks: int, summary: str) -> dict:
    result["score"] = round(checks_passed / max(total_checks, 1) * 5, 2)
    result["status"] = "PASS" if checks_passed == total_checks else "PARTIAL" if checks_passed >= total_checks * 0.5 else "FAIL"
    result["summary"] = summary
    result["score_explanation"] = (
        "Der Score bewertet nur die hier dokumentierten Prüfungen. "
        "Eine Teilbewertung benennt fehlende oder fehlgeschlagene Schritte und ist keine globale Systemnote."
    )
    return result


def _is_bach_system(root: Path) -> bool:
    return (root / "bach.py").is_file() and (root / "hub" / "task.py").is_file()


def _create_isolated_task_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'P3',
                category TEXT DEFAULT 'general',
                description TEXT DEFAULT '',
                assigned_to TEXT,
                delegated_to TEXT,
                depends_on TEXT,
                created_at TEXT,
                completed_at TEXT,
                updated_at TEXT
            )
        """)


def _run_bach_task_roundtrip(root: Path) -> dict:
    """Prüft BACHs produktive Task-API gegen eine temporäre kanonische DB."""
    result = _base_result(root)
    result["mode"] = "bach_task_api_isolated_db"
    checks_passed = 0
    total_checks = 0

    with tempfile.TemporaryDirectory(prefix="bach-o001-") as temp_dir:
        db_path = Path(temp_dir) / "o001_tasks.sqlite3"
        _create_isolated_task_db(db_path)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from hub import bach_paths
        from hub.task import TaskHandler

        previous_db = bach_paths.BACH_DB
        bach_paths.BACH_DB = db_path
        handler = TaskHandler(root)

        def run_api(name: str, operation: str, args: list[str], expected_text: str = ""):
            nonlocal checks_passed, total_checks
            total_checks += 1
            success, output = handler.handle(operation, args)
            output = str(output).strip()
            passed = bool(success) and (not expected_text or expected_text in output)
            result["checks"].append({
                "name": name,
                "passed": passed,
                "details": output[-500:] if output else "Keine Ausgabe",
            })
            if passed:
                checks_passed += 1
            return passed, output

        created, output = run_api(
            "task_create_via_api",
            "add",
            ["O001 isolierter Task", "--priority", "P2", "--category", "qa"],
            "erstellt",
        )
        match = re.search(r"\bTask\s+(\d+)\s+erstellt\b", output)
        if not created or not match:
            if result["checks"]:
                result["checks"][-1]["passed"] = False
                if created:
                    checks_passed -= 1
                result["checks"][-1]["details"] = f"Task-ID nicht lesbar: {output[-500:]}"
            bach_paths.BACH_DB = previous_db
            return _finish_result(result, checks_passed, total_checks, "Task-Erstellung über die BACH-Task-API fehlgeschlagen")

        task_id = match.group(1)
        run_api("task_read_via_api", "show", [task_id], "O001 isolierter Task")
        run_api("task_edit_via_api", "edit", [task_id, "--title", "O001 bearbeitet"], "bearbeitet")

        completed, _ = run_api("task_complete_via_api", "done", [task_id], "erledigt")
        if completed:
            conn = sqlite3.connect(db_path)
            try:
                status = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            finally:
                conn.close()
            if status != ("done",):
                result["checks"][-1]["passed"] = False
                checks_passed -= 1

        deleted, _ = run_api("task_delete_via_api", "delete", [task_id], "geloescht")
        if deleted:
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            finally:
                conn.close()
            if row is not None:
                result["checks"][-1]["passed"] = False
                checks_passed -= 1

        total_checks += 1
        isolated = handler.db_path == db_path and db_path.exists()
        result["checks"].append({
            "name": "canonical_database_isolated",
            "passed": isolated,
            "details": "BACH_DB zeigte für alle Task-API-Aufrufe auf eine temporäre Testdatenbank.",
        })
        if isolated:
            checks_passed += 1
        bach_paths.BACH_DB = previous_db
        # sqlite3's context manager commits but does not close connections. The
        # handler uses short-lived connections, so collect them before Windows
        # removes the temporary database directory.
        gc.collect()

    return _finish_result(result, checks_passed, total_checks, f"{checks_passed}/{total_checks} BACH-Task-API- und Datenbankprüfungen bestanden")


def _test_generic_task_infrastructure(root: Path) -> dict:
    """Bewahrt den bisherigen dateibasierten Fallback für fremde Systeme."""
    result = _base_result(root)
    result["mode"] = "generic_task_infrastructure"
    checks_passed = 0
    total_checks = 0

    total_checks += 1
    task_patterns = ["AUFGABEN.txt", "TASKS.txt", "TODO.txt", "tasks.json", "AUFGABEN.md"]
    task_files = []
    for pattern in task_patterns:
        task_files.extend(root.rglob(pattern))
    if task_files:
        checks_passed += 1
        result["checks"].append({"name": "task_file_exists", "passed": True, "details": f"Gefunden: {[str(f.relative_to(root)) for f in task_files[:3]]}"})
    else:
        result["checks"].append({"name": "task_file_exists", "passed": False, "details": "Keine Task-Datei gefunden"})

    total_checks += 1
    if task_files:
        task_file = task_files[0]
        try:
            content = task_file.read_text(encoding="utf-8")
            has_open = bool(re.search(r"(?i)(OPEN|TODO|OFFEN|PENDING)", content))
            has_done = bool(re.search(r"(?i)(DONE|ERLEDIGT|COMPLETED)", content))
            has_checkboxes = bool(re.search(r"\[\s*[xX ]?\s*\]", content))
            passed = has_open or has_done or has_checkboxes
            if passed:
                checks_passed += 1
            result["checks"].append({"name": "task_structure", "passed": passed, "details": f"OPEN: {has_open}, DONE: {has_done}, Checkboxes: {has_checkboxes}"})
        except OSError as exc:
            result["checks"].append({"name": "task_structure", "passed": False, "details": f"Lesefehler: {exc}"})
    else:
        result["checks"].append({"name": "task_structure", "passed": False, "details": "Keine Task-Datei zum Prüfen"})

    total_checks += 1
    writable = bool(task_files and os.access(task_files[0], os.W_OK))
    if writable:
        checks_passed += 1
    result["checks"].append({"name": "task_writable", "passed": writable, "details": "Schreibzugriff möglich" if writable else "Kein Schreibzugriff oder keine Task-Datei"})

    total_checks += 1
    archive_patterns = ["ARCHIV", "archive", "DONE", "history", "completed"]
    has_archive = any((root / pattern).exists() or list(root.rglob(pattern)) for pattern in archive_patterns)
    if has_archive:
        checks_passed += 1
    result["checks"].append({"name": "task_archive", "passed": has_archive, "details": "Archiv/History-Struktur gefunden" if has_archive else "Kein Archiv gefunden"})

    return _finish_result(result, checks_passed, total_checks, f"{checks_passed}/{total_checks} Infrastrukturprüfungen bestanden")


def test_task_roundtrip(root_path: str) -> dict:
    """Testet BACH per CLI, andere Systeme über deren sichtbare Infrastruktur."""
    root = Path(root_path)
    if not root.exists():
        return {"error": f"Pfad existiert nicht: {root_path}"}
    if _is_bach_system(root):
        return _run_bach_task_roundtrip(root)
    return _test_generic_task_infrastructure(root)


def main():
    if len(sys.argv) < 2:
        print("Usage: python O001_task_roundtrip.py <system_path> [output_json]")
        sys.exit(1)
    result = test_task_roundtrip(sys.argv[1])
    output = sys.argv[2] if len(sys.argv) > 2 else None
    if output:
        Path(output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Ergebnis gespeichert: {output}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
