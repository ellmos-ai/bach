"""Regression tests for the opt-in Claude Code agent exporter."""

from __future__ import annotations

import sqlite3
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.agents_export import AgentsExporter


def _fixture_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "bach"
    skill = root / "system" / "skills" / "alpha"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: alpha\nversion: 1.0.0\ntype: skill\ndescription: Alpha\n---\nAlpha\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "fixture.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE bach_agents (
            id INTEGER, name TEXT, display_name TEXT, type TEXT,
            category TEXT, description TEXT, skill_path TEXT,
            is_active INTEGER, version TEXT, language TEXT, persona TEXT
        );
        CREATE TABLE bach_experts (
            id INTEGER, name TEXT, display_name TEXT, domain TEXT,
            description TEXT, skill_path TEXT, is_active INTEGER,
            version TEXT, language TEXT, persona TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO bach_agents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "über-agent",
            "Über",
            "boss",
            "test",
            "Unicode-Beschreibung",
            "skills/alpha",
            1,
            "1.0.0",
            "de",
            "Ruhig und präzise",
        ),
    )
    conn.execute(
        "INSERT INTO bach_experts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            2,
            "expert",
            "Expert",
            "testing",
            "Expert description",
            "skills/alpha",
            1,
            "1.0.0",
            "de",
            "Expert persona",
        ),
    )
    conn.execute(
        "INSERT INTO bach_agents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (3, "inactive", "Inactive", "boss", "test", "Skip", "skills/alpha", 0, "1", "de", "Skip"),
    )
    conn.commit()
    conn.close()

    persona_dir = root / "system" / "agents" / "personas"
    persona_dir.mkdir(parents=True)
    (persona_dir / "UBER.md").write_text(
        """---
name: über-agent
version: 1.0.0
type: persona
persona:
  display_name: "Über"
skills:
  - alpha
runtime:
  model: sonnet
  max_turns: 5
  tools:
    - Read
    - Grep
description: >
  Unicode persona.
---
# Über
""",
        encoding="utf-8",
    )
    return root, db_path


def test_agent_export_is_deterministic_and_validated(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    output = tmp_path / "claude" / "agents"
    exporter = AgentsExporter(root, db_path=db_path)

    success, message = exporter.generate(format="agent", output_dir=output)
    assert success
    assert "Erzeugt und gelesen" in message
    files = sorted(output.glob("*.md"))
    assert [path.name for path in files] == ["expert.md", "uber-agent.md"]

    first = {path.name: path.read_text(encoding="utf-8") for path in files}
    assert "name: uber-agent" in first["uber-agent.md"]
    assert "model: \"sonnet\"" in first["uber-agent.md"]
    assert "maxTurns: 5" in first["uber-agent.md"]
    assert "skills: [\"alpha\"]" in first["uber-agent.md"]
    assert "Unicode-Beschreibung" in first["uber-agent.md"]
    assert "system/skills/alpha" in first["uber-agent.md"]
    assert exporter.validate_agent_document(first["uber-agent.md"]) == []

    success, message = exporter.generate(format="agent", output_dir=output)
    assert success
    assert "Unverändert vorhanden" in message
    second = {path.name: path.read_text(encoding="utf-8") for path in files}
    assert first == second


def test_legacy_export_remains_the_default_format(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    output = tmp_path / "AGENTS.md"
    exporter = AgentsExporter(root, db_path=db_path, output_path=output)

    success, message = exporter.generate()
    assert success
    assert "AGENTS.md generiert" in message
    content = output.read_text(encoding="utf-8")
    assert content.startswith("# BACH Agents & Experts\n")
    assert "## Boss-Agenten (Orchestrierer)" in content
    assert "## Experten (Spezialisierte Ausführer)" in content


def test_local_fixture_db_is_used_when_it_contains_agent_tables(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    local_db = root / "system" / "data" / "bach.db"
    local_db.parent.mkdir(parents=True)
    shutil.copyfile(db_path, local_db)

    exporter = AgentsExporter(root)
    assert exporter.db_path == local_db


def test_agent_export_dry_run_does_not_create_files(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    output = tmp_path / "not-created"
    success, message = AgentsExporter(root, db_path=db_path).generate(
        format="agent", output_dir=output, dry_run=True
    )
    assert success
    assert "DRY-RUN" in message
    assert not output.exists()


def test_agent_export_cli_accepts_format_and_dry_run(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    output = tmp_path / "cli-output"
    script = Path(__file__).parents[1] / "tools" / "agents_export.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--format",
            "agent",
            "--db",
            str(db_path),
            "--root",
            str(root),
            "--output",
            str(output),
            "--dry-run",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "DRY-RUN" in result.stdout
    assert not output.exists()


def test_agent_export_reports_conflicting_foreign_file_without_overwrite(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    output = tmp_path / "claude" / "agents"
    output.mkdir(parents=True)
    foreign = output / "expert.md"
    foreign.write_text("foreign\n", encoding="utf-8")

    success, message = AgentsExporter(root, db_path=db_path).generate(
        format="agent", output_dir=output
    )
    assert not success
    assert "wird nicht überschrieben" in message
    assert foreign.read_text(encoding="utf-8") == "foreign\n"
    assert (output / "uber-agent.md").exists()


def test_agent_export_reports_missing_skill_and_inactive_rows(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE bach_agents SET skill_path = ? WHERE name = ?", ("missing", "über-agent"))
    conn.commit()
    conn.close()
    output = tmp_path / "claude" / "agents"

    success, message = AgentsExporter(root, db_path=db_path).generate(
        format="agent", output_dir=output, dry_run=True
    )
    assert not success
    assert "Skill-Pfad fehlt" in message
    assert "inaktiv" in message
    assert list(output.glob("*.md")) == []


def test_agent_export_reports_persona_file_name_conflict(tmp_path: Path) -> None:
    root, db_path = _fixture_root(tmp_path)
    persona = root / "system" / "agents" / "personas" / "UBER.md"
    persona.write_text(
        persona.read_text(encoding="utf-8").replace("name: über-agent", "name: wrong-agent"),
        encoding="utf-8",
    )
    success, message = AgentsExporter(root, db_path=db_path).generate(
        format="agent", output_dir=tmp_path / "output", dry_run=True
    )
    assert not success
    assert "Persona-Datei" in message
    assert "DB nennt" in message
