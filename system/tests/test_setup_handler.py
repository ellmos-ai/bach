# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the BACH Setup Handler — validation, config loading, USER.md, ProSync."""

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import hub.setup as setup_handler_module
from hub.setup import SetupHandler


@pytest.fixture(autouse=True)
def isolate_translation_runtime(monkeypatch):
    """Keep setup language tests from leaking process-global translation state."""

    import hub.lang as lang_module

    monkeypatch.setattr(lang_module, "_t_cache", dict(lang_module._t_cache))
    monkeypatch.setattr(lang_module, "_t_lang_cache", lang_module._t_lang_cache)


@pytest.fixture(autouse=True)
def stub_os_keyring(monkeypatch):
    """SetupHandler._check() fragt sonst den ECHTEN OS-Schluesselbund ab.

    Auf Windows geht das an den Credential Manager; faellt der Aufruf aus oder
    liefert er eine Backend-Prioritaet 0, kippt `_check()` auf False und der
    Test schlaegt scheinbar grundlos fehl (beobachtet: derselbe Lauf 2x/1x/0x
    rot). Kein Test in dieser Datei prueft die Schluesselbund-Zeile, deshalb
    wird sie hier hermetisch gestellt.
    """
    import keyring

    monkeypatch.setattr(
        keyring,
        "get_keyring",
        lambda: SimpleNamespace(priority=1),
    )


@pytest.fixture
def handler(tmp_path):
    """SetupHandler with a temporary base_path (system/ inside tmp_path)."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    data_dir = system_dir / "data"
    data_dir.mkdir()
    (system_dir / "hooks").mkdir()
    # Minimal bach.db so _canonical_db resolves locally, not to ~/.bach/bach.db
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS languages_config (
            default_language TEXT, updated_at TEXT
        );
        INSERT INTO languages_config (default_language, updated_at)
            VALUES ('en', '2026-01-01');
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)
    conn.commit()
    conn.close()
    return SetupHandler(system_dir)


@pytest.fixture
def handler_with_db(tmp_path):
    """SetupHandler with a bach.db containing assistant_user_profile."""
    tmp_path = tmp_path / "system"
    tmp_path.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (tmp_path / "hooks").mkdir()

    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE assistant_user_profile (
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            confidence TEXT DEFAULT 'mittel',
            learned_from TEXT DEFAULT 'unknown',
            created_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (category, key)
        );
        CREATE TABLE system_config (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)
    conn.commit()
    conn.close()

    h = SetupHandler(tmp_path)
    return h, db_path


# ═══════════════════════════════════════════════════════════════
# MCP VALIDATION
# ═══════════════════════════════════════════════════════════════


class TestMcpValidation:
    def test_valid_core_packages_pass(self, handler):
        ok, errors = handler._validate_mcp_install_plan(
            ["ellmos-codecommander-mcp", "ellmos-filecommander-mcp"],
            handler.CORE_MCP_SERVER_CONFIGS,
        )
        assert ok
        assert errors == []

    def test_empty_packages_fail(self, handler):
        ok, errors = handler._validate_mcp_install_plan([], {})
        assert not ok
        assert any("Keine MCP-Pakete" in e for e in errors)

    def test_invalid_package_name_fails(self, handler):
        ok, errors = handler._validate_mcp_install_plan(
            ["../evil-package"], {}
        )
        assert not ok
        assert any("Ungueltiger MCP-Paketname" in e for e in errors)

    def test_package_not_in_allowlist_fails(self, handler):
        ok, errors = handler._validate_mcp_install_plan(
            ["some-random-package"], {}
        )
        assert not ok
        assert any("nicht in Allowlist" in e for e in errors)

    def test_non_npx_command_fails(self, handler):
        ok, errors = handler._validate_mcp_install_plan(
            ["ellmos-codecommander-mcp"],
            {"test-server": {"command": "node", "args": ["ellmos-codecommander-mcp"]}},
        )
        assert not ok
        assert any("npx" in e for e in errors)

    def test_mismatched_config_package_fails(self, handler):
        ok, errors = handler._validate_mcp_install_plan(
            ["ellmos-codecommander-mcp"],
            {"test-server": {"command": "npx", "args": ["ellmos-filecommander-mcp"]}},
        )
        assert not ok
        assert any("nicht im Installationsplan" in e for e in errors)


# ═══════════════════════════════════════════════════════════════
# JSON CONFIG LOADING
# ═══════════════════════════════════════════════════════════════


class TestLoadJsonObjectConfig:
    def test_missing_file_with_allow_missing(self, handler, tmp_path):
        ok, data, error = handler._load_json_object_config(
            tmp_path / "nonexistent.json", "test", allow_missing=True
        )
        assert ok
        assert data == {}

    def test_missing_file_without_allow_missing(self, handler, tmp_path):
        ok, data, error = handler._load_json_object_config(
            tmp_path / "nonexistent.json", "test", allow_missing=False
        )
        assert not ok
        assert "nicht gefunden" in error

    def test_valid_json_object(self, handler, tmp_path):
        f = tmp_path / "config.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        ok, data, error = handler._load_json_object_config(f, "test")
        assert ok
        assert data == {"key": "value"}

    def test_invalid_json_fails(self, handler, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{not valid json}', encoding="utf-8")
        ok, data, error = handler._load_json_object_config(f, "test")
        assert not ok
        assert "ungueltig" in error

    def test_json_array_fails(self, handler, tmp_path):
        f = tmp_path / "array.json"
        f.write_text('[1, 2, 3]', encoding="utf-8")
        ok, data, error = handler._load_json_object_config(f, "test")
        assert not ok
        assert "Objekt" in error

    def test_empty_file_returns_empty_dict(self, handler, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("  \n  ", encoding="utf-8")
        ok, data, error = handler._load_json_object_config(f, "test")
        assert ok
        assert data == {}

    def test_directory_path_fails(self, handler, tmp_path):
        ok, data, error = handler._load_json_object_config(tmp_path, "test")
        assert not ok
        assert "Verzeichnis" in error


# ═══════════════════════════════════════════════════════════════
# PROSYNC SETUP
# ═══════════════════════════════════════════════════════════════


class TestProSyncSetup:
    def test_enable_multi_system(self, handler):
        ok, msg = handler._setup_prosync(["--multi-system"])
        assert ok
        flag_file = handler.base_path / "data" / "config" / "db_sync_enabled"
        assert flag_file.exists()

    def test_disable_single_system(self, handler):
        flag_dir = handler.base_path / "data" / "config"
        flag_dir.mkdir(parents=True, exist_ok=True)
        (flag_dir / "db_sync_enabled").write_text("enabled", encoding="utf-8")

        ok, msg = handler._setup_prosync(["--single-system"])
        assert ok
        assert not (flag_dir / "db_sync_enabled").exists()

    def test_status_when_disabled(self, handler):
        ok, msg = handler._setup_prosync([])
        assert ok
        assert "nicht aktiv" in msg

    def test_status_when_enabled(self, handler):
        flag_dir = handler.base_path / "data" / "config"
        flag_dir.mkdir(parents=True, exist_ok=True)
        (flag_dir / "db_sync_enabled").write_text("enabled", encoding="utf-8")

        ok, msg = handler._setup_prosync([])
        assert ok
        assert "aktiv" in msg

    def test_config_dict_multi_system(self, handler):
        ok, msg = handler._setup_prosync([], config={"multi_system": True})
        assert ok
        flag_file = handler.base_path / "data" / "config" / "db_sync_enabled"
        assert flag_file.exists()


# ═══════════════════════════════════════════════════════════════
# USER.MD PARSING & PERSONALIZATION
# ═══════════════════════════════════════════════════════════════


USER_MD_TEMPLATE = """# User Profile
> **Type:** TEMPLATE (dist_type=1) -- customize after installation.
<!-- BACH-INTERNAL-MARKER: dist_type=1 TEMPLATE -->

## Basic Information
**Name:** User
**Role:** Developer
**Language:** en
**Timezone:** UTC
**Operating System:** Unknown

## Communication
**Communication Style:** direct
**Detail Preference:** balanced
**Technical Depth:** advanced

## Your Core Values

- Efficiency
- Simplicity

### Short-term
- Learn BACH

### Long-term
- Build great tools

**Last Updated:** 2026-01-01
**Sync Source:** none
"""


class TestParseUserMd:
    def test_parses_basic_information(self, handler):
        parsed = handler._parse_user_md(USER_MD_TEMPLATE)
        assert parsed["stats"]["role"] == "Developer"
        assert parsed["stats"]["timezone"] == "UTC"
        assert parsed["stats"]["os"] == "Unknown"

    def test_parses_communication_traits(self, handler):
        parsed = handler._parse_user_md(USER_MD_TEMPLATE)
        assert parsed["traits"]["communication_style"] == "direct"
        assert parsed["traits"]["detail_preference"] == "balanced"

    def test_parses_core_values(self, handler):
        parsed = handler._parse_user_md(USER_MD_TEMPLATE)
        assert "Efficiency" in parsed["values"]
        assert "Simplicity" in parsed["values"]

    def test_parses_goals(self, handler):
        parsed = handler._parse_user_md(USER_MD_TEMPLATE)
        assert "Learn BACH" in parsed["goals_short"]
        assert "Build great tools" in parsed["goals_long"]

    def test_skips_default_username(self, handler):
        parsed = handler._parse_user_md(USER_MD_TEMPLATE)
        assert "name" not in parsed["stats"]


class TestPersonalizeUserMd:
    def test_replaces_name_and_role(self, handler):
        db_data = {
            "stats": {"name": "Lukas", "role": "Researcher"},
            "traits": {}, "values": [], "goals": {},
        }
        result = handler._personalize_user_md(USER_MD_TEMPLATE, db_data)
        assert "**Name:** Lukas" in result
        assert "**Role:** Researcher" in result

    def test_removes_template_marker(self, handler):
        db_data = {"stats": {}, "traits": {}, "values": [], "goals": {}}
        result = handler._personalize_user_md(USER_MD_TEMPLATE, db_data)
        assert "TEMPLATE" not in result
        assert "PERSONALIZED" in result

    def test_replaces_values(self, handler):
        db_data = {
            "stats": {}, "traits": {},
            "values": ["Innovation", "Open Source"],
            "goals": {},
        }
        result = handler._personalize_user_md(USER_MD_TEMPLATE, db_data)
        assert "- Innovation" in result
        assert "- Open Source" in result

    def test_replaces_goals(self, handler):
        db_data = {
            "stats": {}, "traits": {}, "values": [],
            "goals": {
                "short_term_0": "Ship v4",
                "long_term_0": "World domination",
            },
        }
        result = handler._personalize_user_md(USER_MD_TEMPLATE, db_data)
        assert "- Ship v4" in result
        assert "- World domination" in result


# ═══════════════════════════════════════════════════════════════
# USER PROFILE DB SYNC
# ═══════════════════════════════════════════════════════════════


class TestUserProfileDbSync:
    def test_load_from_empty_db(self, handler_with_db):
        handler, db_path = handler_with_db
        data = handler._load_user_profile_from_db(db_path)
        assert data["stats"] == {}
        assert data["values"] == []

    def test_load_from_populated_db(self, handler_with_db):
        handler, db_path = handler_with_db
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO assistant_user_profile (category, key, value) VALUES ('stat', 'name', 'Lukas')"
        )
        conn.execute(
            "INSERT INTO assistant_user_profile (category, key, value) VALUES ('trait', 'communication_style', 'direct')"
        )
        conn.execute(
            "INSERT INTO assistant_user_profile (category, key, value) VALUES ('value', 'v0', 'Innovation')"
        )
        conn.commit()
        conn.close()

        data = handler._load_user_profile_from_db(db_path)
        assert data["stats"]["name"] == "Lukas"
        assert data["traits"]["communication_style"] == "direct"
        assert "Innovation" in data["values"]

    def test_sync_to_db(self, handler_with_db):
        handler, db_path = handler_with_db
        parsed = {
            "stats": {"name": "Lukas", "role": "Researcher"},
            "traits": {"communication_style": "direct"},
            "values": ["Innovation"],
            "goals_short": ["Ship v4"],
            "goals_long": ["World domination"],
        }
        synced = handler._sync_user_md_to_db(parsed, db_path)
        assert synced == 6

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT value FROM assistant_user_profile WHERE category='stat' AND key='name'"
        ).fetchone()
        assert row[0] == "Lukas"
        conn.close()

    def test_sync_preserves_manually_learned(self, handler_with_db):
        handler, db_path = handler_with_db
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO assistant_user_profile (category, key, value, learned_from) "
            "VALUES ('stat', 'name', 'Manual', 'conversation')"
        )
        conn.commit()
        conn.close()

        parsed = {"stats": {"name": "Override"}, "traits": {}, "values": [], "goals_short": [], "goals_long": []}
        synced = handler._sync_user_md_to_db(parsed, db_path)
        assert synced == 0

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT value FROM assistant_user_profile WHERE category='stat' AND key='name'"
        ).fetchone()
        assert row[0] == "Manual"
        conn.close()


# ═══════════════════════════════════════════════════════════════
# TEMPLATE INIT & CLEANUP
# ═══════════════════════════════════════════════════════════════


class TestTemplateManagement:
    def test_init_creates_from_template(self, handler):
        root = handler.base_path.parent
        (root / "README.template.md").write_text("# Template", encoding="utf-8")
        assert not (root / "README.md").exists()

        created = handler._init_from_templates()
        assert len(created) == 1
        assert (root / "README.md").exists()

    def test_init_skips_existing(self, handler):
        root = handler.base_path.parent
        (root / "README.template.md").write_text("# Template", encoding="utf-8")
        (root / "README.md").write_text("# Real", encoding="utf-8")

        created = handler._init_from_templates()
        assert len(created) == 0
        assert (root / "README.md").read_text(encoding="utf-8") == "# Real"

    def test_cleanup_removes_template_when_real_exists(self, handler):
        root = handler.base_path.parent
        template = root / "README.template.md"
        real = root / "README.md"
        template.write_text("# Template", encoding="utf-8")
        real.write_text("# Real", encoding="utf-8")

        cleaned = handler._cleanup_templates()
        assert len(cleaned) == 1
        assert not template.exists()
        assert real.exists()

    def test_cleanup_keeps_template_when_no_real(self, handler):
        root = handler.base_path.parent
        template = root / "README.template.md"
        template.write_text("# Template", encoding="utf-8")

        cleaned = handler._cleanup_templates()
        assert len(cleaned) == 0
        assert template.exists()


# ═══════════════════════════════════════════════════════════════
# PREFLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════


class TestPreflight:
    def test_preflight_runs_without_error(self, handler):
        ok, msg = handler._preflight([])
        assert isinstance(ok, bool)
        assert "Python >= 3.10" in msg

    def test_preflight_checks_db_dir(self, handler):
        ok, msg = handler._preflight([])
        assert "data/ beschreibbar" in msg


class TestSetupCheck:
    def test_check_uses_resolved_npm_executable_on_windows(self, handler, tmp_path, monkeypatch):
        root = handler.base_path.parent
        (root / "USER.md").write_text("# User", encoding="utf-8")

        fake_home = tmp_path / "home"
        secrets_dir = fake_home / ".bach"
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "bach_secrets.json").write_text(
            json.dumps({"secrets": {"demo": "value"}}),
            encoding="utf-8",
        )

        commands = []
        global_modules = tmp_path / "npm-global"
        (global_modules / "ellmos-codecommander-mcp").mkdir(parents=True)
        (global_modules / "ellmos-filecommander-mcp").mkdir(parents=True)

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            if cmd[1:3] == ["root", "-g"]:
                return SimpleNamespace(returncode=0, stdout=str(global_modules), stderr="")
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(setup_handler_module.shutil, "which", lambda name: "C:\\Program Files\\nodejs\\npm.CMD")
        monkeypatch.setattr(setup_handler_module.subprocess, "run", fake_run)
        monkeypatch.setattr(setup_handler_module.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr(setup_handler_module.importlib.util, "find_spec", lambda name: object())
        monkeypatch.setattr(handler, "_is_npm_package_installed", lambda pkg: False)

        ok, msg = handler._check()

        assert ok, msg
        assert "[OK] ellmos-codecommander-mcp installiert" in msg
        assert "[OK] ellmos-filecommander-mcp installiert" in msg
        assert commands
        assert all(cmd[0].lower().endswith("npm.cmd") for cmd in commands)
        assert commands[0][1:3] == ["root", "-g"]

    def test_check_accepts_local_mcp_workspace_repos(self, handler, tmp_path, monkeypatch):
        root = handler.base_path.parent
        (root / "USER.md").write_text("# User", encoding="utf-8")

        fake_home = tmp_path / "home"
        secrets_dir = fake_home / ".bach"
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "bach_secrets.json").write_text(
            json.dumps({"secrets": {"demo": "value"}}),
            encoding="utf-8",
        )

        global_modules = tmp_path / "npm-global"
        global_modules.mkdir()
        local_mcp_root = tmp_path / ".MCP"
        for pkg in (
            "ellmos-codecommander-mcp",
            "ellmos-filecommander-mcp",
            "n8n-manager-mcp",
        ):
            pkg_dir = local_mcp_root / pkg
            (pkg_dir / "dist").mkdir(parents=True)
            (pkg_dir / "package.json").write_text(
                json.dumps({"name": pkg}),
                encoding="utf-8",
            )

        def fake_run(cmd, **kwargs):
            if cmd[1:3] == ["root", "-g"]:
                return SimpleNamespace(returncode=0, stdout=str(global_modules), stderr="")
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(setup_handler_module.shutil, "which", lambda name: "C:\\Program Files\\nodejs\\npm.CMD")
        monkeypatch.setattr(setup_handler_module.subprocess, "run", fake_run)
        monkeypatch.setattr(setup_handler_module.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr(setup_handler_module.importlib.util, "find_spec", lambda name: object())

        ok, msg = handler._check()

        assert ok, msg
        assert "[OK] ellmos-codecommander-mcp lokale Arbeitskopie erkannt" in msg
        assert "[OK] ellmos-filecommander-mcp lokale Arbeitskopie erkannt" in msg
        assert "[OK] n8n-manager-mcp lokale Arbeitskopie erkannt (optional)" in msg

    def test_local_mcp_roots_accept_env_override(self, handler, tmp_path, monkeypatch):
        env_root = tmp_path / "external-mcp-workspaces"
        env_root.mkdir()
        monkeypatch.setenv("BACH_LOCAL_MCP_ROOTS", str(env_root))

        roots = handler._candidate_local_mcp_roots()

        assert env_root in roots

    def test_check_fails_when_psutil_missing(self, handler, tmp_path, monkeypatch):
        root = handler.base_path.parent
        (root / "USER.md").write_text("# User", encoding="utf-8")

        fake_home = tmp_path / "home"
        secrets_dir = fake_home / ".bach"
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "bach_secrets.json").write_text(
            json.dumps({"secrets": {"demo": "value"}}),
            encoding="utf-8",
        )

        def fake_run(cmd, **kwargs):
            package = cmd[3]
            return SimpleNamespace(returncode=0, stdout=f"{package}@1.0.0", stderr="")

        monkeypatch.setattr(setup_handler_module.shutil, "which", lambda name: "C:\\Program Files\\nodejs\\npm.CMD")
        monkeypatch.setattr(setup_handler_module.subprocess, "run", fake_run)
        monkeypatch.setattr(setup_handler_module.Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr(setup_handler_module.importlib.util, "find_spec", lambda name: None if name == "psutil" else object())
        monkeypatch.setattr(handler, "_is_npm_package_installed", lambda pkg: False)

        ok, msg = handler._check()

        assert ok is False
        assert "psutil fehlt" in msg


# ═══════════════════════════════════════════════════════════════
# LANGUAGE SWAP
# ═══════════════════════════════════════════════════════════════


class TestLanguageSwap:
    def test_invalid_language_fails(self, handler):
        ok, msg = handler._swap_doc_language("fr")
        assert not ok
        assert "de|en|es|ja|ru|zh" in msg

    def test_none_language_fails(self, handler):
        ok, msg = handler._swap_doc_language(None)
        assert not ok

    def test_swap_to_de_with_existing_de_file(self, handler):
        root = handler.base_path.parent
        (root / "README.md").write_text("# English", encoding="utf-8")
        (root / "README.de.md").write_text("# Deutsch", encoding="utf-8")

        ok, msg = handler._swap_doc_language("de")
        assert ok
        assert (root / "README.md").read_text(encoding="utf-8") == "# Deutsch"
        assert (root / "README.en.md").exists()

    def test_swap_to_en_with_existing_en_file(self, handler):
        root = handler.base_path.parent
        (root / "README.md").write_text("# Deutsch", encoding="utf-8")
        (root / "README.en.md").write_text("# English", encoding="utf-8")

        ok, msg = handler._swap_doc_language("en")
        assert ok
        assert (root / "README.md").read_text(encoding="utf-8") == "# English"

    def test_swap_to_es_sets_system_language_without_doc_swap(self, handler):
        root = handler.base_path.parent
        (root / "README.md").write_text("# English", encoding="utf-8")

        ok, msg = handler._swap_doc_language("es")
        assert ok
        assert "Systemsprache" in msg
        assert (root / "README.md").read_text(encoding="utf-8") == "# English"

        conn = sqlite3.connect(str(handler._canonical_db))
        row = conn.execute("SELECT default_language FROM languages_config").fetchone()
        conn.close()
        assert row[0] == "es"
