"""Unit tests for Buddha Usecase-Builder automation (Ticket T-20260909-613048528)."""

from pathlib import Path
import sqlite3
import pytest

from hub._services.chat.usecase_runner import (
    ensure_buddha_usecase_task,
    generate_workflow_template,
    evaluate_usecase_test,
    run_usecase_builder_task,
    escalate_failed_usecase,
    slugify_workflow_name,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def test_env(tmp_path):
    """Set up temporary database and skills directory for isolated testing."""
    db_path = tmp_path / "test_bach.db"
    skills_dir = tmp_path / "skills" / "workflows"
    skills_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE usecases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            workflow_name TEXT,
            test_input TEXT,
            expected_output TEXT,
            test_result TEXT DEFAULT 'pending',
            test_score INTEGER DEFAULT 0,
            last_tested TIMESTAMP,
            created_by TEXT DEFAULT 'test',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE tasks (
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
    conn.commit()
    conn.close()

    return {"db_path": db_path, "skills_dir": skills_dir, "repo_root": tmp_path}


def test_slugify_workflow_name():
    assert slugify_workflow_name("Einfache Notiz erfassen!") == "einfache_notiz_erfassen"
    assert slugify_workflow_name("Workflow--123_test") == "workflow-123_test"
    assert slugify_workflow_name("") == "workflow_auto"


def test_ensure_buddha_usecase_task_idempotency(test_env):
    db_path = test_env["db_path"]

    # First call: should create new task
    task_id1, created1 = ensure_buddha_usecase_task(
        usecase_id=42,
        title="Dokumente scannen",
        description="Scanne PDF und extrahiere Text",
        workflow_name="doc_scanner",
        db_path=db_path,
    )
    assert created1 is True
    assert task_id1 > 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id1,)).fetchone()
    conn.close()

    assert task["title"] == "[Usecase-Builder] Dokumente scannen"
    assert task["assigned_to"] == "BUDDHA"
    assert task["status"] == "pending"
    assert task["category"] == "usecase-builder"
    assert task["source"] == "usecase:42"

    # Second call: must be idempotent and return same task without duplicate
    task_id2, created2 = ensure_buddha_usecase_task(
        usecase_id=42,
        title="Dokumente scannen",
        description="Scanne PDF und extrahiere Text",
        workflow_name="doc_scanner",
        db_path=db_path,
    )
    assert created2 is False
    assert task_id2 == task_id1

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    assert count == 1


def test_generate_workflow_template(test_env):
    target_dir = test_env["skills_dir"]

    file_path = generate_workflow_template(
        workflow_name="smart_invoice_parser",
        title="Rechnungen automatisch parsen",
        description="Liest PDF-Rechnungen und parst Beträge.",
        test_input="Rechnung_123.pdf",
        expected_output="Total: 150.00 EUR",
        target_dir=target_dir,
    )

    assert file_path.exists()
    content = file_path.read_text(encoding="utf-8")
    assert "# Workflow: Rechnungen automatisch parsen" in content
    assert "Rechnung_123.pdf" in content
    assert "Total: 150.00 EUR" in content
    assert "name: smart_invoice_parser" in content


def test_run_usecase_builder_task_success(test_env):
    db_path = test_env["db_path"]
    repo_root = test_env["repo_root"]

    # Insert usecase with full input/output
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO usecases (title, description, workflow_name, test_input, expected_output)
        VALUES (?, ?, ?, ?, ?)
    """, (
        "Reisekostenabrechnung",
        "Rechne Spesen ab",
        "reisekosten",
        "Beleg_Hotel.pdf",
        "Abrechnung OK",
    ))
    usecase_id = cur.lastrowid
    conn.commit()
    conn.close()

    task_id, _ = ensure_buddha_usecase_task(
        usecase_id=usecase_id,
        title="Reisekostenabrechnung",
        workflow_name="reisekosten",
        db_path=db_path,
    )

    # Run runner
    res = run_usecase_builder_task(
        task_id=task_id,
        attempt=1,
        max_attempts=2,
        db_path=db_path,
        repo_root=repo_root,
    )

    assert res["success"] is True
    assert res["status"] == "completed"
    assert res["score"] >= 75

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    u = conn.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,)).fetchone()
    conn.close()

    assert t["status"] == "completed"
    assert "Erfolgreich abgenommen" in t["result"]
    assert u["test_result"] == "pass"
    assert u["test_score"] >= 75


def test_run_usecase_builder_task_escalation(test_env):
    db_path = test_env["db_path"]
    repo_root = test_env["repo_root"]

    # Insert usecase without test_input or expected_output to force low score (< 75%)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO usecases (title, description, workflow_name, test_input, expected_output)
        VALUES (?, ?, ?, NULL, NULL)
    """, ("Unvollstaendiger Usecase", "Keine Inputs vorhanden", "unvollstaendig"))
    usecase_id = cur.lastrowid
    conn.commit()
    conn.close()

    task_id, _ = ensure_buddha_usecase_task(
        usecase_id=usecase_id,
        title="Unvollstaendiger Usecase",
        workflow_name="unvollstaendig",
        db_path=db_path,
    )

    # First attempt: retry needed
    res1 = run_usecase_builder_task(
        task_id=task_id,
        attempt=1,
        max_attempts=2,
        db_path=db_path,
        repo_root=repo_root,
    )
    assert res1["success"] is False
    assert res1["status"] == "retry_needed"

    # Second attempt: escalates to CLAUDE
    res2 = run_usecase_builder_task(
        task_id=task_id,
        attempt=2,
        max_attempts=2,
        db_path=db_path,
        repo_root=repo_root,
    )
    assert res2["success"] is False
    assert res2["status"] == "delegated"
    assert res2["escalated_to"] == "CLAUDE"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    u = conn.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,)).fetchone()
    conn.close()

    assert t["assigned_to"] == "CLAUDE"
    assert t["status"] == "delegated"
    assert "ESKALATION AN CLAUDE" in t["description"]
    assert u["test_result"] == "delegated"


def test_usecases_html_template_elements():
    html_path = REPO_ROOT / "system" / "gui" / "templates" / "usecases.html"
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Delegate button and function
    assert "An Buddha zur Umsetzung übergeben" in content or "An Buddha zur Umsetzung" in content
    assert "delegateToBuddha(" in content
    assert "delegateCurrentToBuddha(" in content
    assert "/api/usecases" in content
