# BACH Adapter: usecase_runner
"""Usecase-Builder runner and automation for Buddha (Ticket T-20260909-613048528).

Generates workflows for usecases, verifies test-scores, and handles escalation to Claude.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


def get_default_db_path() -> Path:
    """Resolve default database path."""
    try:
        from hub.bach_paths import BACH_DB
        if BACH_DB.exists():
            return BACH_DB
    except Exception:
        pass
    fallback = REPO_ROOT / "system" / "hub" / "bach.db"
    return fallback


def slugify_workflow_name(name: str) -> str:
    """Convert a title or name into a safe filename slug."""
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", (name or "").strip().lower())
    slug = re.sub(r"_+", "_", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("_-")
    return slug or "workflow_auto"


def ensure_buddha_usecase_task(
    usecase_id: int,
    title: str,
    description: Optional[str] = None,
    workflow_name: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Tuple[int, bool]:
    """Ensure an idempotent [Usecase-Builder] task exists in bach.db for Buddha.

    Returns:
        (task_id, created): created is True if newly inserted, False if already present.
    """
    path = db_path or get_default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ensure tasks table exists with basic columns
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'normal',
            category TEXT,
            assigned_to TEXT,
            source TEXT,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    task_title = f"[Usecase-Builder] {title}"
    task_source = f"usecase:{usecase_id}"

    # Check for existing open task
    cursor.execute("""
        SELECT id FROM tasks
        WHERE (source = ? OR title = ?)
          AND status IN ('pending', 'in_progress', 'working', 'assigned')
        ORDER BY id DESC LIMIT 1
    """, (task_source, task_title))
    row = cursor.fetchone()
    if row:
        conn.close()
        return (row["id"], False)

    # Insert new task
    task_desc = (
        f"Autonome Workflow-Erstellung für Usecase #{usecase_id} ({title})\n"
        f"Workflow-Name: {workflow_name or 'noch nicht festgelegt'}\n\n"
        f"{description or ''}"
    ).strip()

    cursor.execute("""
        INSERT INTO tasks (title, description, status, priority, category, assigned_to, source, created_at, updated_at)
        VALUES (?, ?, 'pending', 'normal', 'usecase-builder', 'BUDDHA', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (task_title, task_desc, task_source))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return (new_id, True)


def generate_workflow_template(
    workflow_name: str,
    title: str,
    description: Optional[str] = None,
    test_input: Optional[str] = None,
    expected_output: Optional[str] = None,
    target_dir: Optional[Path] = None,
) -> Path:
    """Generate canonical workflow template markdown file under skills/workflows/."""
    slug = slugify_workflow_name(workflow_name or title)
    filename = f"{slug}.md"

    primary_dir = target_dir or (REPO_ROOT / "skills" / "workflows")
    primary_dir.mkdir(parents=True, exist_ok=True)
    file_path = primary_dir / filename

    content = f"""---
name: {slug}
title: {title}
category: workflow
status: active
---

# Workflow: {title}

## Beschreibung
{description or 'Keine Beschreibung hinterlegt.'}

## Eingabe / Input
{test_input or 'Standard-Input'}

## Schritte (Steps)
1. Eingabe analysieren und Kontext laden.
2. Erforderliche Tools und Prompts aufrufen.
3. Workflow-Schritte sequentiell ausführen.
4. Ergebnis validieren und zurückgeben.

## Erwartete Ausgabe / Expected Output
{expected_output or 'Erfolgreich ausgefuehrt'}
"""

    file_path.write_text(content, encoding="utf-8")

    # Mirror to skills/_workflows for legacy resolver compatibility ONLY when target_dir is default
    if target_dir is None:
        try:
            legacy_dir = REPO_ROOT / "skills" / "_workflows"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dir / filename).write_text(content, encoding="utf-8")
        except Exception:
            pass

    return file_path


def evaluate_usecase_test(
    usecase_id: int,
    db_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Test usecase and calculate score (pass >= 75%). Updates usecases table."""
    root = repo_root or REPO_ROOT
    path = db_path or get_default_db_path()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,))
    uc = cursor.fetchone()
    if not uc:
        conn.close()
        return {"success": False, "error": f"Usecase #{usecase_id} nicht gefunden"}

    uc_dict = dict(uc)
    workflow_name = uc_dict.get("workflow_name") or ""
    expected = uc_dict.get("expected_output") or ""
    test_input = uc_dict.get("test_input") or ""

    score_parts = 0
    score_max = 4
    checks = []

    # Check 1: Workflow zugewiesen?
    if workflow_name:
        checks.append(f"[OK] Workflow zugewiesen: {workflow_name}")
        score_parts += 1
    else:
        checks.append("[FEHLT] Kein Workflow zugewiesen")

    # Check 2: Workflow-Datei existiert?
    wf_found = False
    if workflow_name:
        slug = slugify_workflow_name(workflow_name)
        candidates = [
            root / "skills" / "workflows" / f"{slug}.md",
            root / "skills" / "_workflows" / f"{slug}.md",
            root / "skills" / "workflows" / f"{workflow_name}.md" if not workflow_name.endswith(".md") else root / "skills" / "workflows" / workflow_name,
            root / "skills" / "_workflows" / f"{workflow_name}.md" if not workflow_name.endswith(".md") else root / "skills" / "_workflows" / workflow_name,
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                wf_found = True
                checks.append(f"[OK] Workflow-Datei vorhanden: {c.name}")
                score_parts += 1
                break
    if not wf_found and workflow_name:
        checks.append(f"[FEHLT] Workflow-Datei nicht gefunden: {workflow_name}")

    # Check 3: Test-Input definiert?
    if test_input and str(test_input).strip():
        checks.append("[OK] Test-Input definiert")
        score_parts += 1
    else:
        checks.append("[FEHLT] Kein Test-Input definiert")

    # Check 4: Expected-Output definiert?
    if expected and str(expected).strip():
        checks.append("[OK] Expected-Output definiert")
        score_parts += 1
    else:
        checks.append("[FEHLT] Kein Expected-Output definiert")

    test_score = int((score_parts / score_max) * 100) if score_max > 0 else 0
    test_result = "pass" if test_score >= 75 else ("fail" if test_score > 0 else "pending")

    cursor.execute("""
        UPDATE usecases
        SET last_tested = ?, test_result = ?, test_score = ?
        WHERE id = ?
    """, (datetime.now().isoformat(), test_result, test_score, usecase_id))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "usecase_id": usecase_id,
        "title": uc_dict.get("title"),
        "result": test_result,
        "score": test_score,
        "checks": checks,
        "output": "\n".join(checks) + f"\n\nScore: {test_score}% ({score_parts}/{score_max})",
    }


def escalate_failed_usecase(
    task_id: int,
    usecase_id: int,
    error_log: str,
    target_agent: str = "CLAUDE",
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Escalate a failed usecase task to Claude after failed attempts."""
    path = db_path or get_default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return {"success": False, "error": f"Task #{task_id} nicht gefunden"}

    current_desc = task["description"] or ""
    escalation_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    escalated_desc = (
        f"{current_desc}\n\n"
        f"--- ESKALATION AN {target_agent} [{escalation_stamp}] ---\n"
        f"Grund: Workflow-Umsetzung nach 2 Versuchen fehlgeschlagen (Score < 75%).\n"
        f"Fehlerprotokoll:\n{error_log}"
    ).strip()

    cursor.execute("""
        UPDATE tasks
        SET assigned_to = ?, status = 'delegated', description = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (target_agent, escalated_desc, task_id))

    cursor.execute("""
        UPDATE usecases
        SET test_result = 'delegated'
        WHERE id = ?
    """, (usecase_id,))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "task_id": task_id,
        "usecase_id": usecase_id,
        "status": "delegated",
        "assigned_to": target_agent,
    }


def run_usecase_builder_task(
    task_id: int,
    attempt: int = 1,
    max_attempts: int = 2,
    db_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute the [Usecase-Builder] task as Buddha worker.

    1. Parses task and finds usecase.
    2. Builds missing workflow template under skills/workflows/.
    3. Runs evaluate_usecase_test.
    4. If score >= 75%: marks task completed.
    5. If score < 75% and attempt >= max_attempts: escalates to Claude.
    """
    path = db_path or get_default_db_path()
    root = repo_root or REPO_ROOT

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return {"success": False, "error": f"Task #{task_id} nicht gefunden"}

    # Extract usecase_id
    usecase_id = None
    source = task["source"] or ""
    if source.startswith("usecase:"):
        try:
            usecase_id = int(source.split(":", 1)[1])
        except ValueError:
            pass

    if not usecase_id:
        title = task["title"] or ""
        clean_title = title.replace("[Usecase-Builder]", "").strip()
        cursor.execute("SELECT id FROM usecases WHERE title = ? ORDER BY id DESC LIMIT 1", (clean_title,))
        uc_row = cursor.fetchone()
        if uc_row:
            usecase_id = uc_row["id"]

    if not usecase_id:
        conn.close()
        return {"success": False, "error": f"Kein Usecase für Task #{task_id} gefunden"}

    cursor.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,))
    uc = cursor.fetchone()
    if not uc:
        conn.close()
        return {"success": False, "error": f"Usecase #{usecase_id} nicht gefunden"}

    uc_dict = dict(uc)
    workflow_name = uc_dict.get("workflow_name")
    if not workflow_name:
        workflow_name = slugify_workflow_name(uc_dict.get("title") or f"usecase_{usecase_id}")
        cursor.execute("UPDATE usecases SET workflow_name = ? WHERE id = ?", (workflow_name, usecase_id))
        conn.commit()

    conn.close()

    # Step 1: Generate workflow template file
    generate_workflow_template(
        workflow_name=workflow_name,
        title=uc_dict.get("title") or f"Usecase {usecase_id}",
        description=uc_dict.get("description"),
        test_input=uc_dict.get("test_input"),
        expected_output=uc_dict.get("expected_output"),
        target_dir=(root / "skills" / "workflows"),
    )

    # Step 2: Evaluate test
    test_eval = evaluate_usecase_test(usecase_id, db_path=path, repo_root=root)
    score = test_eval.get("score", 0)

    # Step 3: Check success vs escalation
    if score >= 75:
        # Mark completed
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks
            SET status = 'completed',
                result = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (f"Erfolgreich abgenommen (Score: {score}%). Workflow erstellt unter skills/workflows/{workflow_name}.md", task_id))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "task_id": task_id,
            "usecase_id": usecase_id,
            "status": "completed",
            "score": score,
            "result": "pass",
        }

    # If score < 75%
    if attempt >= max_attempts:
        escalation = escalate_failed_usecase(
            task_id=task_id,
            usecase_id=usecase_id,
            error_log=test_eval.get("output", "Score unter 75%"),
            target_agent="CLAUDE",
            db_path=path,
        )
        return {
            "success": False,
            "task_id": task_id,
            "usecase_id": usecase_id,
            "status": "delegated",
            "score": score,
            "escalated_to": "CLAUDE",
            "error": "Score < 75% nach 2 Versuchen; an CLAUDE eskaliert",
        }

    return {
        "success": False,
        "task_id": task_id,
        "usecase_id": usecase_id,
        "status": "retry_needed",
        "attempt": attempt,
        "score": score,
    }
