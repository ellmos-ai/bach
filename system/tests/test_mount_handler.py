# -*- coding: utf-8 -*-
"""Tests for MountHandler (hub/mount.py)."""

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from hub.mount import MountHandler


@pytest.fixture
def mount_env(tmp_path):
    """Erstellt MountHandler mit temp-DB und Verzeichnisstruktur."""
    base = tmp_path / "bach"
    (base / "data").mkdir(parents=True)
    (base / "user").mkdir()

    db_path = base / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            name TEXT PRIMARY KEY,
            type TEXT,
            category TEXT,
            endpoint TEXT,
            is_active INTEGER DEFAULT 1,
            help_text TEXT
        )
    """)
    conn.commit()
    conn.close()

    h = MountHandler(base)
    return h, base, db_path


class TestInit:
    def test_profile_name(self, mount_env):
        h, _, _ = mount_env
        assert h.profile_name == "mount"

    def test_target_file(self, mount_env):
        h, base, _ = mount_env
        assert h.target_file == base / "user"

    def test_operations(self, mount_env):
        h, _, _ = mount_env
        ops = h.get_operations()
        assert "add" in ops
        assert "remove" in ops
        assert "list" in ops
        assert "restore" in ops


class TestHandleDispatch:
    def test_list_on_empty_op(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h.handle("", [], dry_run=False)
        assert ok is True

    def test_list_explicit(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h.handle("list", [])
        assert ok is True

    def test_unknown_op(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h.handle("nonsense", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_add_dispatches(self, mount_env):
        h, base, _ = mount_env
        source = base / "extern"
        source.mkdir()
        with patch.object(h, "_create_link"):
            ok, msg = h.handle("add", [str(source), "myalias"])
            assert ok is True


class TestListMounts:
    def test_empty(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h._list_mounts()
        assert ok is True
        assert "Keine Mounts" in msg

    def test_with_entries(self, mount_env):
        h, base, db_path = mount_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('docs', 'mount', 'storage', ?, 1)",
            (str(base / "extern"),)
        )
        conn.commit()
        conn.close()

        ok, msg = h._list_mounts()
        assert ok is True
        assert "docs" in msg
        assert "[FEHLT]" in msg

    def test_existing_target_shows_existiert(self, mount_env):
        h, base, db_path = mount_env
        (base / "user" / "docs").mkdir()
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('docs', 'mount', 'storage', ?, 1)",
            (str(base / "extern"),)
        )
        conn.commit()
        conn.close()

        ok, msg = h._list_mounts()
        assert "[EXISTIERT]" in msg

    def test_inactive_shows_marker(self, mount_env):
        h, _, db_path = mount_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('old', 'mount', 'storage', '/tmp/old', 0)"
        )
        conn.commit()
        conn.close()

        ok, msg = h._list_mounts()
        assert "[--]" in msg


class TestCreateLink:
    def test_windows_uses_mklink(self, mount_env):
        h, base, _ = mount_env
        source = base / "src"
        target = base / "dst"
        source.mkdir()

        with patch("hub.mount.os.name", "nt"), \
             patch("hub.mount.subprocess.run") as mock_run:
            h._create_link(source, target)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "mklink" in cmd
            assert "/J" in cmd

    def test_unix_uses_symlink(self, mount_env):
        h, base, _ = mount_env
        source = base / "src"
        target = base / "dst"
        source.mkdir()

        with patch("hub.mount.os.name", "posix"), \
             patch("hub.mount.os.symlink") as mock_sym:
            h._create_link(source, target)
            mock_sym.assert_called_once_with(source, target)


class TestRemoveLink:
    def test_windows_existing_target(self, mount_env):
        h, base, _ = mount_env
        target = base / "user" / "linked"
        target.mkdir()

        with patch("hub.mount.os.name", "nt"), \
             patch("hub.mount.os.rmdir") as mock_rm:
            result = h._remove_link(target)
            assert result is True
            mock_rm.assert_called_once_with(target)

    def test_windows_nonexistent_returns_false(self, mount_env):
        h, base, _ = mount_env
        target = base / "user" / "gone"

        with patch("hub.mount.os.name", "nt"):
            result = h._remove_link(target)
            assert result is False

    def test_unix_symlink(self, mount_env):
        h, base, _ = mount_env
        target = base / "user" / "linked"

        with patch("hub.mount.os.name", "posix"), \
             patch.object(Path, "is_symlink", return_value=True), \
             patch("hub.mount.os.unlink") as mock_unlink:
            result = h._remove_link(target)
            assert result is True
            mock_unlink.assert_called_once_with(target)

    def test_unix_dangling_symlink(self, mount_env):
        h, base, _ = mount_env
        target = base / "user" / "dangling"

        with patch("hub.mount.os.name", "posix"), \
             patch.object(Path, "is_symlink", return_value=True), \
             patch.object(Path, "exists", return_value=False), \
             patch("hub.mount.os.unlink") as mock_unlink:
            result = h._remove_link(target)
            assert result is True
            mock_unlink.assert_called_once()

    def test_unix_no_link_returns_false(self, mount_env):
        h, base, _ = mount_env
        target = base / "user" / "nothing"

        with patch("hub.mount.os.name", "posix"), \
             patch.object(Path, "is_symlink", return_value=False), \
             patch.object(Path, "exists", return_value=False):
            result = h._remove_link(target)
            assert result is False


class TestAddMount:
    def test_missing_args(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h._add_mount([], dry_run=False)
        assert ok is False
        assert "Verwendung" in msg

    def test_source_not_exists(self, mount_env):
        h, base, _ = mount_env
        ok, msg = h._add_mount([str(base / "missing"), "alias"], dry_run=False)
        assert ok is False
        assert "existiert nicht" in msg

    def test_dry_run(self, mount_env):
        h, base, _ = mount_env
        source = base / "extern"
        source.mkdir()
        ok, msg = h._add_mount([str(source), "test"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_creates_link_and_db_entry(self, mount_env):
        h, base, db_path = mount_env
        source = base / "extern"
        source.mkdir()

        with patch.object(h, "_create_link") as mock_link:
            ok, msg = h._add_mount([str(source), "mydata"], dry_run=False)
            assert ok is True
            mock_link.assert_called_once()

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT * FROM connections WHERE name='mydata'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_skips_link_if_target_exists(self, mount_env):
        h, base, _ = mount_env
        source = base / "extern"
        source.mkdir()
        (base / "user" / "mydata").mkdir()

        with patch.object(h, "_create_link") as mock_link:
            ok, msg = h._add_mount([str(source), "mydata"], dry_run=False)
            assert ok is True
            mock_link.assert_not_called()


class TestMountSourceContainment:
    def test_rejects_existing_directory_outside_allowed_root(self, mount_env, tmp_path):
        _, base, _ = mount_env
        outside = tmp_path / "outside"
        outside.mkdir()
        h = MountHandler(base, allowed_source_roots=[base])

        with pytest.raises(ValueError, match="außerhalb erlaubter Wurzeln"):
            h._resolve_mount_source(str(outside))

    def test_accepts_existing_directory_inside_allowed_root(self, mount_env):
        _, base, _ = mount_env
        source = base / "extern"
        source.mkdir()
        h = MountHandler(base, allowed_source_roots=[base])

        assert h._resolve_mount_source(str(source)) == source.resolve()

    def test_normalizes_user_path_before_creating_path_object(self, mount_env):
        _, base, _ = mount_env
        source = base / "extern"
        source.mkdir()
        h = MountHandler(base, allowed_source_roots=[base])

        # Die Sicherheitsgrenze muss den String vollständig normalisieren und
        # eindämmen, bevor daraus ein Pfad für Dateisystemzugriffe entsteht.
        with patch("hub.mount.Path.resolve", side_effect=AssertionError("late resolve")):
            assert h._resolve_mount_source(str(source)) == Path(os.path.realpath(source))

    def test_rejects_parent_traversal_outside_allowed_root(self, mount_env, tmp_path):
        _, base, _ = mount_env
        outside = tmp_path / "outside"
        outside.mkdir()
        traversing = base / "user" / ".." / ".." / outside.name
        h = MountHandler(base, allowed_source_roots=[base])

        with pytest.raises(ValueError, match="außerhalb erlaubter Wurzeln"):
            h._resolve_mount_source(str(traversing))

    def test_configured_additional_root_remains_supported(self, mount_env, tmp_path):
        _, base, _ = mount_env
        external_root = tmp_path / "nas"
        source = external_root / "documents"
        source.mkdir(parents=True)
        h = MountHandler(base, allowed_source_roots=[base, external_root])

        assert h._resolve_mount_source(str(source)) == source.resolve()

    def test_add_rejects_outside_source_before_link_or_db_write(self, mount_env, tmp_path):
        _, base, db_path = mount_env
        outside = tmp_path / "outside"
        outside.mkdir()
        h = MountHandler(base, allowed_source_roots=[base])

        with patch.object(h, "_create_link") as mock_link:
            ok, msg = h._add_mount([str(outside), "blocked"], dry_run=False)

        assert ok is False
        assert "außerhalb erlaubter Wurzeln" in msg
        mock_link.assert_not_called()
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT * FROM connections WHERE name='blocked'"
        ).fetchone()
        conn.close()
        assert row is None


class TestRemoveMount:
    def test_missing_args(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h._remove_mount([], dry_run=False)
        assert ok is False

    def test_dry_run(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h._remove_mount(["test"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_removes_link_and_db_entry(self, mount_env):
        h, base, db_path = mount_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('docs', 'mount', 'storage', '/some/path', 1)"
        )
        conn.commit()
        conn.close()

        with patch.object(h, "_remove_link", return_value=True):
            ok, msg = h._remove_mount(["docs"], dry_run=False)
            assert ok is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT * FROM connections WHERE name='docs'"
        ).fetchone()
        conn.close()
        assert row is None


class TestRestoreMounts:
    def test_empty_db(self, mount_env):
        h, _, _ = mount_env
        ok, msg = h._restore_mounts(dry_run=False)
        assert ok is True
        assert "Wiederhergestellt: 0" in msg

    def test_restores_missing_link(self, mount_env):
        h, base, db_path = mount_env
        source = base / "extern"
        source.mkdir()

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('docs', 'mount', 'storage', ?, 1)",
            (str(source),)
        )
        conn.commit()
        conn.close()

        with patch.object(h, "_create_link") as mock_link:
            ok, msg = h._restore_mounts(dry_run=False)
            assert ok is True
            assert "Wiederhergestellt: 1" in msg
            mock_link.assert_called_once()

    def test_skips_existing_target(self, mount_env):
        h, base, db_path = mount_env
        source = base / "extern"
        source.mkdir()
        (base / "user" / "docs").mkdir()

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('docs', 'mount', 'storage', ?, 1)",
            (str(source),)
        )
        conn.commit()
        conn.close()

        with patch.object(h, "_create_link") as mock_link:
            ok, msg = h._restore_mounts(dry_run=False)
            assert ok is True
            assert "Wiederhergestellt: 0" in msg
            mock_link.assert_not_called()

    def test_source_missing_adds_error(self, mount_env):
        h, base, db_path = mount_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('gone', 'mount', 'storage', ?, 1)",
            (str(base / "missing"),),
        )
        conn.commit()
        conn.close()

        ok, msg = h._restore_mounts(dry_run=False)
        assert ok is True
        assert "Fehler: 1" in msg
        assert "Quelle fehlt" in msg

    def test_dry_run_lists_without_creating(self, mount_env):
        h, base, db_path = mount_env
        source = base / "extern"
        source.mkdir()

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('docs', 'mount', 'storage', ?, 1)",
            (str(source),)
        )
        conn.commit()
        conn.close()

        with patch.object(h, "_create_link") as mock_link:
            ok, msg = h._restore_mounts(dry_run=True)
            assert ok is True
            assert "Wiederhergestellt: 1" in msg
            mock_link.assert_not_called()

    def test_link_error_captured(self, mount_env):
        h, base, db_path = mount_env
        source = base / "extern"
        source.mkdir()

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) "
            "VALUES ('docs', 'mount', 'storage', ?, 1)",
            (str(source),)
        )
        conn.commit()
        conn.close()

        with patch.object(h, "_create_link", side_effect=OSError("permission denied")):
            ok, msg = h._restore_mounts(dry_run=False)
            assert ok is True
            assert "Fehler: 1" in msg
