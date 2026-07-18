# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for UpgradeHandler — version listing, status, help, category routing."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.upgrade import UpgradeHandler

SCHEMA = """
CREATE TABLE dist_file_versions (
    file_path TEXT NOT NULL,
    version TEXT NOT NULL,
    file_hash TEXT,
    dist_type INTEGER DEFAULT 2,
    created_at TEXT,
    PRIMARY KEY (file_path, version)
);
CREATE TABLE distribution_releases (
    version TEXT PRIMARY KEY,
    release_date TEXT,
    status TEXT DEFAULT 'released',
    is_stable INTEGER DEFAULT 1,
    description TEXT
);
CREATE TABLE distribution_manifest (
    path TEXT PRIMARY KEY,
    file_path TEXT,
    dist_type INTEGER DEFAULT 2,
    template_hash TEXT,
    description TEXT,
    created_at TEXT,
    updated_at TEXT,
    current_version TEXT,
    file_hash TEXT
);
CREATE TABLE dist_type_defaults (
    path TEXT PRIMARY KEY,
    dist_type INTEGER DEFAULT 2,
    is_file INTEGER DEFAULT 0
);
"""


@pytest.fixture
def handler(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    data_dir = system_dir / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return UpgradeHandler(system_dir)


def _seed_versions(handler, file_path="hub/backup.py", count=3):
    conn = sqlite3.connect(str(handler.db_path))
    for i in range(1, count + 1):
        conn.execute("""
            INSERT INTO dist_file_versions (file_path, version, file_hash, dist_type, created_at)
            VALUES (?, ?, ?, 2, ?)
        """, (file_path, f"1.{i}.0", f"abc{i}def0", f"2026-01-0{i} 12:00:00"))
    conn.commit()
    conn.close()


def _seed_releases(handler):
    conn = sqlite3.connect(str(handler.db_path))
    conn.execute("""
        INSERT INTO distribution_releases (version, release_date, status, is_stable)
        VALUES ('3.3.0', '2026-03-01', 'released', 1)
    """)
    conn.execute("""
        INSERT INTO distribution_releases (version, release_date, status, is_stable)
        VALUES ('3.4.0-beta', '2026-04-01', 'beta', 0)
    """)
    conn.commit()
    conn.close()


def _write_system_file(handler, relative_path: str, content: str) -> str:
    target = handler.base_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _insert_version(handler, file_path: str, version: str, file_hash: str, created_at: str):
    conn = sqlite3.connect(str(handler.db_path))
    conn.execute(
        """
        INSERT INTO dist_file_versions (file_path, version, file_hash, dist_type, created_at)
        VALUES (?, ?, ?, 2, ?)
        """,
        (file_path, version, file_hash, created_at),
    )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# INIT & INTERFACE
# ═══════════════════════════════════════════════════════════════


class TestInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "upgrade"

    def test_operations_contain_core_categories(self, handler):
        ops = handler.get_operations()
        for cat in ("core", "templates", "skills", "hub", "tools", "gui"):
            assert cat in ops

    def test_handle_unknown_as_file(self, handler):
        ok, msg = handler.handle("nonexistent-file.py", [])
        assert not ok


# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════


class TestHelp:
    def test_help_returns_success(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok
        assert "UPGRADE" in msg
        assert "BEFEHLE" in msg

    def test_empty_operation_shows_help(self, handler):
        ok, msg = handler.handle("", [])
        assert ok


# ═══════════════════════════════════════════════════════════════
# LIST VERSIONS
# ═══════════════════════════════════════════════════════════════


class TestListVersions:
    def test_list_missing_arg(self, handler):
        ok, msg = handler.handle("list", [])
        assert not ok
        assert "Datei fehlt" in msg

    def test_list_missing_arg_json(self, handler):
        ok, msg = handler.handle("list", ["--json"])
        assert not ok
        data = json.loads(msg)
        assert data["ok"] is False
        assert data["error_code"] == "missing_file"
        assert data["file_path"] is None
        assert data["versions"] == []

    def test_list_nonexistent_file(self, handler):
        ok, msg = handler.handle("list", ["ghost.py"])
        assert not ok
        assert "Keine Versionen" in msg

    def test_list_nonexistent_file_json(self, handler):
        ok, msg = handler.handle("list", ["ghost.py", "--json"])
        assert not ok
        data = json.loads(msg)
        assert data["ok"] is False
        assert data["error_code"] == "no_versions_found"
        assert data["file_path"] == "ghost.py"
        assert data["versions"] == []

    def test_list_with_versions(self, handler):
        _seed_versions(handler, "hub/backup.py", 3)
        ok, msg = handler.handle("list", ["hub/backup.py"])
        assert ok
        assert "hub/backup.py" in msg
        assert "1.3.0" in msg
        assert "aktuell" in msg
        assert "CORE" in msg

    def test_list_shows_previous_marker(self, handler):
        _seed_versions(handler, "hub/backup.py", 3)
        ok, msg = handler.handle("list", ["hub/backup.py"])
        assert ok
        assert "Vorherige" in msg

    def test_list_json_structure(self, handler):
        _seed_versions(handler, "hub/backup.py", 3)
        ok, msg = handler.handle("list", ["hub/backup.py", "--json"])
        assert ok
        data = json.loads(msg)
        assert data["file_path"] == "hub/backup.py"
        assert data["current_version"] == "1.3.0"
        assert len(data["versions"]) == 3
        assert data["versions"][0]["is_current"] is True
        assert data["versions"][1]["is_previous"] is True


# ═══════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_empty_db(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok
        assert "Nachverfolgte Dateien: 0" in msg
        assert "Gesamt-Versionen:      0" in msg
        assert "Release-Eintraege:     0" in msg

    def test_status_with_tracked_files(self, handler):
        _seed_versions(handler, "hub/backup.py", 2)
        _seed_versions(handler, "tools/converter.py", 1)
        ok, msg = handler.handle("status", [])
        assert ok
        assert "Nachverfolgte Dateien: 2" in msg
        assert "Gesamt-Versionen:      3" in msg

    def test_status_shows_releases(self, handler):
        _seed_releases(handler)
        ok, msg = handler.handle("status", [])
        assert ok
        assert "3.3.0" in msg
        assert "stable" in msg
        assert "beta" in msg

    def test_status_json(self, handler):
        _seed_versions(handler, "hub/backup.py", 2)
        _seed_releases(handler)
        ok, msg = handler.handle("status", ["--json"])
        assert ok
        data = json.loads(msg)
        assert data["tracked_files"] == 1
        assert data["total_versions"] == 2
        assert data["manifest_entries"] == 0
        assert data["release_entries"] == 2
        assert data["repair_recommended"] is False
        assert len(data["releases"]) == 2
        assert data["releases"][0]["channel"] == "beta"


# ═══════════════════════════════════════════════════════════════
# CHECK UPDATES
# ═══════════════════════════════════════════════════════════════


class TestCheckUpdates:
    def test_check_empty_db_reports_no_versioned_files(self, handler):
        ok, msg = handler.handle("check", [])
        assert ok
        assert "Keine versionierten Dateien" in msg

    def test_check_empty_db_json_reports_zero_summary(self, handler):
        ok, msg = handler.handle("check", ["--json"])
        assert ok
        data = json.loads(msg)
        assert data["no_tracked_versions"] is True
        assert data["manifest_entries"] == 0
        assert data["release_entries"] == 0
        assert data["repair_recommended"] is True
        assert data["summary"]["checked_files"] == 0
        assert data["upgrade_candidates"] == []

    def test_check_reports_upgrade_candidates_drift_and_missing(self, handler):
        _seed_releases(handler)

        old_hash = _write_system_file(handler, "hub/backup.py", "print('old')\n")
        _insert_version(handler, "hub/backup.py", "1.0.0", old_hash, "2026-01-01 12:00:00")
        _insert_version(
            handler,
            "hub/backup.py",
            "1.1.0",
            hashlib.sha256("print('new')\n".encode("utf-8")).hexdigest(),
            "2026-02-01 12:00:00",
        )

        _write_system_file(handler, "tools/converter.py", "print('local drift')\n")
        _insert_version(
            handler,
            "tools/converter.py",
            "2.0.0",
            hashlib.sha256("print('expected')\n".encode("utf-8")).hexdigest(),
            "2026-03-01 12:00:00",
        )

        _insert_version(
            handler,
            "agents/demo/SKILL.md",
            "1.0.0",
            hashlib.sha256("# Demo\n".encode("utf-8")).hexdigest(),
            "2026-03-02 12:00:00",
        )

        current_hash = _write_system_file(handler, "core/app.py", "print('current')\n")
        _insert_version(handler, "core/app.py", "3.0.0", current_hash, "2026-03-03 12:00:00")

        ok, msg = handler.handle("check", [])

        assert ok
        assert "Stabile Linie:        3.3.0 (2026-03-01)" in msg
        assert "Neueste bekannte:     3.4.0-beta (2026-04-01) [beta]" in msg
        assert "Gepruefte Dateien:    4" in msg
        assert "Aktuell:              1" in msg
        assert "Upgrade-Kandidaten:   1" in msg
        assert "Lokale Abweichungen:  1" in msg
        assert "Fehlende Dateien:     1" in msg
        assert "hub/backup.py  1.0.0 -> 1.1.0" in msg
        assert "tools/converter.py  erwartet 2.0.0" in msg
        assert "agents/demo/SKILL.md  erwartet 1.0.0" in msg

    def test_check_json_reports_upgrade_candidates_drift_and_missing(self, handler):
        _seed_releases(handler)

        old_hash = _write_system_file(handler, "hub/backup.py", "print('old')\n")
        _insert_version(handler, "hub/backup.py", "1.0.0", old_hash, "2026-01-01 12:00:00")
        _insert_version(
            handler,
            "hub/backup.py",
            "1.1.0",
            hashlib.sha256("print('new')\n".encode("utf-8")).hexdigest(),
            "2026-02-01 12:00:00",
        )

        _write_system_file(handler, "tools/converter.py", "print('local drift')\n")
        _insert_version(
            handler,
            "tools/converter.py",
            "2.0.0",
            hashlib.sha256("print('expected')\n".encode("utf-8")).hexdigest(),
            "2026-03-01 12:00:00",
        )

        _insert_version(
            handler,
            "agents/demo/SKILL.md",
            "1.0.0",
            hashlib.sha256("# Demo\n".encode("utf-8")).hexdigest(),
            "2026-03-02 12:00:00",
        )

        current_hash = _write_system_file(handler, "core/app.py", "print('current')\n")
        _insert_version(handler, "core/app.py", "3.0.0", current_hash, "2026-03-03 12:00:00")

        ok, msg = handler.handle("check", ["--json"])

        assert ok
        data = json.loads(msg)
        assert data["no_tracked_versions"] is False
        assert data["manifest_entries"] == 0
        assert data["release_entries"] == 2
        assert data["repair_recommended"] is False
        assert data["summary"]["checked_files"] == 4
        assert data["summary"]["up_to_date"] == 1
        assert data["summary"]["upgrade_candidates"] == 1
        assert data["summary"]["local_modifications"] == 1
        assert data["summary"]["missing_files"] == 1
        assert data["release_status"]["stable"]["version"] == "3.3.0"
        assert data["release_status"]["latest"]["version"] == "3.4.0-beta"

    def test_check_uses_metadata_fast_path_for_unchanged_latest_files(self, handler, monkeypatch):
        file_hash = _write_system_file(handler, "core/app.py", "print('current')\n")
        _insert_version(handler, "core/app.py", "3.0.0", file_hash, "2999-01-01T00:00:00")

        def fail_hash(_path):
            raise AssertionError("hashing should not be needed for unchanged latest files")

        monkeypatch.setattr(handler, "_hash_file", fail_hash)

        ok, msg = handler.handle("check", ["--json"])

        assert ok
        data = json.loads(msg)
        assert data["manifest_entries"] == 0
        assert data["release_entries"] == 0
        assert data["repair_recommended"] is True
        assert data["summary"]["checked_files"] == 1
        assert data["summary"]["up_to_date"] == 1
        assert data["summary"]["upgrade_candidates"] == 0
        assert data["summary"]["local_modifications"] == 0

    def test_check_falls_back_to_hash_when_file_is_newer_than_metadata(self, handler, monkeypatch):
        file_hash = _write_system_file(handler, "core/app.py", "print('current')\n")
        _insert_version(handler, "core/app.py", "3.0.0", file_hash, "2000-01-01T00:00:00")

        calls = {"count": 0}

        def count_hash(path):
            calls["count"] += 1
            return hashlib.sha256(path.read_bytes()).hexdigest()

        monkeypatch.setattr(handler, "_hash_file", count_hash)

        ok, msg = handler.handle("check", ["--json"])

        assert ok
        data = json.loads(msg)
        assert data["manifest_entries"] == 0
        assert data["release_entries"] == 0
        assert data["repair_recommended"] is True
        assert calls["count"] == 1
        assert data["summary"]["checked_files"] == 1
        assert data["summary"]["up_to_date"] == 1


class TestRepairMetadata:
    def test_detect_release_date_reads_next_release_previous_release_line(self, handler):
        bach_root = handler.base_path.parent
        (bach_root / ".dev").mkdir()
        (bach_root / ".dev" / "NEXT_RELEASE.md").write_text(
            "# Demo\n\n**Vorheriger Release:** v9.9.9 (2026-04-03) -- Demo\n",
            encoding="utf-8",
        )

        assert handler._detect_release_date("v9.9.9") == "2026-04-03"

    def test_repair_dry_run_reports_pending_manifest_and_versions(self, handler):
        bach_root = handler.base_path.parent
        (bach_root / "README.md").write_text("**Version:** v9.9.9\n", encoding="utf-8")
        (bach_root / "CHANGELOG.md").write_text(
            "# Demo\n\n## [9.9.9] - 2026-02-02\n\n### Added\n\n- Test.\n",
            encoding="utf-8",
        )
        _write_system_file(handler, "hub/demo.py", "print('demo')\n")

        conn = sqlite3.connect(str(handler.db_path))
        conn.execute(
            "INSERT INTO dist_type_defaults (path, dist_type, is_file) VALUES (?, ?, ?)",
            ("README.md", 2, 1),
        )
        conn.execute(
            "INSERT INTO dist_type_defaults (path, dist_type, is_file) VALUES (?, ?, ?)",
            ("system/hub/", 2, 0),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("repair", ["--version", "v9.9.9", "--json"], dry_run=True)

        assert ok
        data = json.loads(msg)
        assert data["dry_run"] is True
        assert data["version"] == "v9.9.9"
        assert data["summary"]["candidate_files"] == 2
        assert data["summary"]["manifest_inserted"] == 2
        assert data["summary"]["version_entries_inserted"] == 2
        assert data["db"]["release_entries_before"] == 0
        assert data["db"]["release_entries_after"] == 0
        assert data["release"]["inserted"] == 1
        assert data["release"]["bootstrapped"] is True
        assert data["release"]["release_date"] == "2026-02-02"
        assert data["release"]["status"] == "final"
        assert data["release_catalog_populated"] is False

        conn = sqlite3.connect(str(handler.db_path))
        assert conn.execute("SELECT COUNT(*) FROM distribution_manifest").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM dist_file_versions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM distribution_releases").fetchone()[0] == 0
        conn.close()

    def test_repair_dry_run_flag_in_args_is_honored(self, handler):
        bach_root = handler.base_path.parent
        (bach_root / "README.md").write_text("**Version:** v9.9.9\n", encoding="utf-8")
        _write_system_file(handler, "hub/demo.py", "print('demo')\n")

        conn = sqlite3.connect(str(handler.db_path))
        conn.execute(
            "INSERT INTO dist_type_defaults (path, dist_type, is_file) VALUES (?, ?, ?)",
            ("system/hub/", 2, 0),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle(
            "repair",
            ["--version", "v9.9.9", "--dry-run", "--json"],
        )

        assert ok
        data = json.loads(msg)
        assert data["dry_run"] is True
        assert data["summary"]["candidate_files"] == 1
        assert data["summary"]["version_entries_inserted"] == 1

        conn = sqlite3.connect(str(handler.db_path))
        assert conn.execute("SELECT COUNT(*) FROM distribution_manifest").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM dist_file_versions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM distribution_releases").fetchone()[0] == 0
        conn.close()

    def test_repair_populates_manifest_and_current_version_rows(self, handler):
        bach_root = handler.base_path.parent
        (bach_root / "README.md").write_text("**Version:** v9.9.9\n", encoding="utf-8")
        (bach_root / "CHANGELOG.md").write_text(
            "# Demo\n\n## [9.9.9] - 2026-02-02\n\n### Added\n\n- Test.\n",
            encoding="utf-8",
        )
        _write_system_file(handler, "hub/demo.py", "print('demo')\n")

        conn = sqlite3.connect(str(handler.db_path))
        conn.execute(
            "INSERT INTO dist_type_defaults (path, dist_type, is_file) VALUES (?, ?, ?)",
            ("README.md", 2, 1),
        )
        conn.execute(
            "INSERT INTO dist_type_defaults (path, dist_type, is_file) VALUES (?, ?, ?)",
            ("system/hub/", 2, 0),
        )
        conn.commit()
        conn.close()

        ok, _ = handler.handle("repair", ["--version", "v9.9.9"])

        assert ok

        conn = sqlite3.connect(str(handler.db_path))
        manifest_paths = {
            row[0]
            for row in conn.execute("SELECT path FROM distribution_manifest ORDER BY path").fetchall()
        }
        version_rows = conn.execute(
            "SELECT file_path, version FROM dist_file_versions ORDER BY file_path"
        ).fetchall()
        release_rows = conn.execute(
            "SELECT version, release_date, status, is_stable FROM distribution_releases ORDER BY version"
        ).fetchall()
        conn.close()

        assert manifest_paths == {"README.md", "system/hub/demo.py"}
        assert version_rows == [
            ("README.md", "v9.9.9"),
            ("system/hub/demo.py", "v9.9.9"),
        ]
        assert release_rows == [("v9.9.9", "2026-02-02", "final", 1)]

    def test_repair_bootstraps_release_catalog_only_when_missing(self, handler):
        bach_root = handler.base_path.parent
        (bach_root / "README.md").write_text("**Version:** v9.9.9\n", encoding="utf-8")
        (bach_root / "CHANGELOG.md").write_text(
            "# Demo\n\n## [9.9.9] - 2026-02-02\n\n### Added\n\n- Test.\n",
            encoding="utf-8",
        )
        _write_system_file(handler, "hub/demo.py", "print('demo')\n")

        conn = sqlite3.connect(str(handler.db_path))
        conn.execute(
            "INSERT INTO dist_type_defaults (path, dist_type, is_file) VALUES (?, ?, ?)",
            ("system/hub/", 2, 0),
        )
        conn.execute(
            "INSERT INTO distribution_releases (version, release_date, status, is_stable) VALUES (?, ?, ?, ?)",
            ("v9.9.9", "2026-02-02", "final", 1),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("repair", ["--version", "v9.9.9", "--json"])

        assert ok
        data = json.loads(msg)
        assert data["release"]["inserted"] == 0
        assert data["release"]["skipped_reason"] == "already_present"
        assert data["db"]["release_entries_before"] == 1
        assert data["db"]["release_entries_after"] == 1
        assert data["release_catalog_populated"] is True


# ═══════════════════════════════════════════════════════════════
# CATEGORY ROUTING
# ═══════════════════════════════════════════════════════════════


class TestCategoryRouting:
    @pytest.mark.parametrize("category", [
        "core", "templates", "agents", "skills", "hub",
        "tools", "connectors", "partners", "docs", "gui",
    ])
    def test_category_dispatches_without_crash(self, handler, category):
        ok, msg = handler.handle(category, [], dry_run=True)
        assert isinstance(ok, bool)
        assert isinstance(msg, str)


# ═══════════════════════════════════════════════════════════════
# DB CONNECTION SAFETY
# ═══════════════════════════════════════════════════════════════


class TestDbSafety:
    def test_list_closes_connection_on_success(self, handler):
        _seed_versions(handler)
        handler.handle("list", ["hub/backup.py"])
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_list_closes_connection_on_error(self, handler):
        handler.handle("list", ["nonexistent.py"])
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_status_closes_connection(self, handler):
        handler.handle("status", [])
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()
