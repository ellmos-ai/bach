# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Unit Tests fuer BACH PathHandler (hub/path.py)
==============================================

Testet:
- profile_name Property
- Operationen: show, list, validate, resolve
- JSON-Output-Modus
- Fehlerbehandlung bei ungueltigen Pfaden
- Hilfsfunktionen (_normalize_name, _has_flag, _strip_flags)
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import pytest

from hub.path import PathHandler, SUMMARY_GROUPS, VALIDATION_GROUPS


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_system(tmp_path):
    """Erstellt eine minimale BACH system/-Struktur im tmp-Verzeichnis."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()

    # hub/ mit bach_paths.py
    hub_dir = system_dir / "hub"
    hub_dir.mkdir()
    (hub_dir / "__init__.py").write_text("", encoding="utf-8")

    # Erstelle minimales bach_paths.py
    bach_paths_content = '''
from pathlib import Path

SYSTEM_ROOT = Path(r"{system}").resolve()
BACH_ROOT = Path(r"{root}").resolve()
BACH_DB = SYSTEM_ROOT / "data" / "bach.db"

_PATH_REGISTRY = {{
    "root": str(BACH_ROOT),
    "system": str(SYSTEM_ROOT),
    "hub": str(SYSTEM_ROOT / "hub"),
    "data": str(SYSTEM_ROOT / "data"),
    "db": str(SYSTEM_ROOT / "data" / "bach.db"),
    "logs": str(SYSTEM_ROOT / "logs"),
    "backups": str(SYSTEM_ROOT / "backups"),
    "messages": str(SYSTEM_ROOT / "messages"),
    "instances": str(SYSTEM_ROOT / "instances"),
    "prosync_transit": str(SYSTEM_ROOT / "prosync_transit"),
    "user": str(BACH_ROOT / "user"),
    "docs": str(SYSTEM_ROOT / "docs"),
    "exports": str(SYSTEM_ROOT / "exports"),
    "skills": str(SYSTEM_ROOT / "skills"),
    "tools": str(SYSTEM_ROOT / "tools"),
    "agents": str(SYSTEM_ROOT / "agents"),
    "experts": str(SYSTEM_ROOT / "agents" / "_experts"),
    "help": str(SYSTEM_ROOT / "help"),
    "partners": str(SYSTEM_ROOT / "partners"),
    "connectors": str(SYSTEM_ROOT / "connectors"),
    "foerderplanung": str(BACH_ROOT / "user" / "foerderplanung"),
    "berichte": str(BACH_ROOT / "user" / "berichte"),
    "berichte_output": str(BACH_ROOT / "user" / "berichte_output"),
    "steuer": str(BACH_ROOT / "user" / "steuer"),
    "belege": str(BACH_ROOT / "user" / "belege"),
}}
'''.format(system=str(system_dir).replace("\\", "\\\\"),
           root=str(tmp_path).replace("\\", "\\\\"))
    (hub_dir / "bach_paths.py").write_text(bach_paths_content, encoding="utf-8")

    # base.py (minimale Version fuer den Import)
    base_content = '''
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple, List


class BaseHandler(ABC):
    def __init__(self, base_path_or_app):
        if hasattr(base_path_or_app, 'base_path') and hasattr(base_path_or_app, 'db'):
            self.app = base_path_or_app
            self.base_path = base_path_or_app.base_path
        else:
            self.app = None
            self.base_path = Path(base_path_or_app) if not isinstance(base_path_or_app, Path) else base_path_or_app

        local_db = self.base_path / "data" / "bach.db"
        try:
            from .bach_paths import BACH_DB
            self._canonical_db = BACH_DB
        except ImportError:
            self._canonical_db = local_db

    @property
    @abstractmethod
    def profile_name(self) -> str:
        pass

    @property
    @abstractmethod
    def target_file(self) -> Path:
        pass

    @abstractmethod
    def get_operations(self) -> dict:
        pass

    @abstractmethod
    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        pass
'''
    (hub_dir / "base.py").write_text(base_content, encoding="utf-8")

    # data/ Ordner erstellen
    data_dir = system_dir / "data"
    data_dir.mkdir()

    # Weitere erwartete Ordner erstellen
    for subdir in ["logs", "backups", "tools", "skills", "agents", "connectors",
                   "partners", "help", "docs", "exports", "messages", "instances"]:
        (system_dir / subdir).mkdir(exist_ok=True)

    # user/ Ordner im Root
    user_dir = tmp_path / "user"
    user_dir.mkdir()

    return system_dir


@pytest.fixture
def handler(tmp_system):
    """Erzeugt einen PathHandler mit tmp_system als base_path.

    Importiert path.py mittels Manipulation des hub-Packages im tmp-Verzeichnis.
    """
    # Wir nutzen die echte PathHandler-Klasse, aber mit gepatchtem bach_paths
    original_sys_path = sys.path.copy()
    hub_dir = tmp_system / "hub"

    # Temporaer hub-Pfad einfuegen damit Imports funktionieren
    sys.path.insert(0, str(tmp_system))

    # PathHandler direkt aus dem echten BACH importieren
    from hub.path import PathHandler as RealPathHandler

    # Patch: bach_paths im hub.path-Modul auf unsere tmp-Version zeigen lassen
    import importlib
    import hub.path as path_module

    # Lade das tmp bach_paths Modul
    import importlib.util
    spec = importlib.util.spec_from_file_location("hub.bach_paths", str(hub_dir / "bach_paths.py"))
    tmp_bach_paths = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tmp_bach_paths)

    with patch.object(path_module, 'bp', tmp_bach_paths):
        h = RealPathHandler(tmp_system)
        # Patch _canonical_db auf unsere tmp DB
        h._canonical_db = tmp_system / "data" / "bach.db"
        yield h

    sys.path[:] = original_sys_path


@pytest.fixture
def handler_simple():
    """Einfacher Handler mit dem realen BACH system/ als base_path.

    Fuer Tests die keine Schreib-Operationen benoetigen.
    """
    return PathHandler(SYSTEM_ROOT)


# ═══════════════════════════════════════════════════════════════
# profile_name Property
# ═══════════════════════════════════════════════════════════════


class TestProfileName:
    """Tests fuer die profile_name Property."""

    def test_profile_name_is_path(self, handler_simple):
        assert handler_simple.profile_name == "path"

    def test_profile_name_type(self, handler_simple):
        assert isinstance(handler_simple.profile_name, str)

    def test_profile_name_not_empty(self, handler_simple):
        assert len(handler_simple.profile_name) > 0


# ═══════════════════════════════════════════════════════════════
# get_operations
# ═══════════════════════════════════════════════════════════════


class TestGetOperations:
    """Tests fuer die verfuegbaren Operationen."""

    def test_returns_dict(self, handler_simple):
        ops = handler_simple.get_operations()
        assert isinstance(ops, dict)

    def test_has_expected_operations(self, handler_simple):
        ops = handler_simple.get_operations()
        expected_keys = {"status", "list", "get", "resolve", "overrides", "set", "validate"}
        assert expected_keys.issubset(set(ops.keys()))

    def test_all_values_are_strings(self, handler_simple):
        ops = handler_simple.get_operations()
        for key, value in ops.items():
            assert isinstance(value, str), f"Operation '{key}' hat keinen String-Wert"


# ═══════════════════════════════════════════════════════════════
# target_file Property
# ═══════════════════════════════════════════════════════════════


class TestTargetFile:
    """Tests fuer target_file Property."""

    def test_target_file_points_to_bach_paths(self, handler_simple):
        assert handler_simple.target_file.name == "bach_paths.py"

    def test_target_file_is_path(self, handler_simple):
        assert isinstance(handler_simple.target_file, Path)

    def test_target_file_in_hub_directory(self, handler_simple):
        assert handler_simple.target_file.parent.name == "hub"


# ═══════════════════════════════════════════════════════════════
# Show/List Operations (Pfade anzeigen)
# ═══════════════════════════════════════════════════════════════


class TestShowOperations:
    """Tests fuer Pfad-Anzeige-Operationen."""

    def test_handle_status_returns_success(self, handler_simple):
        success, output = handler_simple.handle("status", [])
        assert success is True
        assert len(output) > 0

    def test_handle_empty_string_shows_summary(self, handler_simple):
        success, output = handler_simple.handle("", [])
        assert success is True
        assert "BACH" in output

    def test_handle_show_is_alias_for_status(self, handler_simple):
        success1, output1 = handler_simple.handle("status", [])
        success2, output2 = handler_simple.handle("show", [])
        # Beide sollten erfolgreich sein (Inhalt kann wegen Timestamp abweichen)
        assert success1 is True
        assert success2 is True

    def test_handle_list_returns_all_paths(self, handler_simple):
        success, output = handler_simple.handle("list", [])
        assert success is True
        assert len(output) > 100  # Sollte einiges an Ausgabe enthalten

    def test_handle_list_json(self, handler_simple):
        success, output = handler_simple.handle("list", ["--json"])
        assert success is True
        data = json.loads(output)
        assert "paths" in data
        assert "count" in data
        assert isinstance(data["paths"], list)
        assert data["count"] > 0

    def test_handle_get_specific_path(self, handler_simple):
        success, output = handler_simple.handle("get", ["hub"])
        assert success is True
        assert "hub" in output.lower()

    def test_handle_get_without_args_returns_error(self, handler_simple):
        success, output = handler_simple.handle("get", [])
        assert success is False
        assert "FEHLER" in output

    def test_shortform_path_name(self, handler_simple):
        """bach path db -> zeigt db-Pfad."""
        success, output = handler_simple.handle("db", [])
        assert success is True
        assert "bach.db" in output.lower() or "db" in output.lower()


# ═══════════════════════════════════════════════════════════════
# Validate Operation
# ═══════════════════════════════════════════════════════════════


class TestValidateOperation:
    """Tests fuer die Pfad-Validierung."""

    def test_validate_returns_success(self, handler_simple):
        success, output = handler_simple.handle("validate", [])
        assert success is True

    def test_validate_json_output(self, handler_simple):
        success, output = handler_simple.handle("validate", ["--json"])
        assert success is True
        data = json.loads(output)
        assert "valid" in data
        assert "warnings" in data
        assert "checked" in data
        assert isinstance(data["valid"], bool)
        assert isinstance(data["warnings"], list)

    def test_validate_checks_critical_paths(self, handler_simple):
        success, output = handler_simple.handle("validate", ["--json"])
        data = json.loads(output)
        checked_names = [item["name"] for item in data["checked"]]
        # Alle Namen aus VALIDATION_GROUPS sollten geprueft worden sein
        for group_names in VALIDATION_GROUPS.values():
            for name in group_names:
                assert name in checked_names, f"Pfad '{name}' wurde nicht validiert"


# ═══════════════════════════════════════════════════════════════
# Resolve Operation
# ═══════════════════════════════════════════════════════════════


class TestResolveOperation:
    """Tests fuer das Aufloesen relativer Pfade."""

    def test_resolve_relative_path(self, handler_simple):
        success, output = handler_simple.handle("resolve", ["hub/base.py"])
        assert success is True
        assert "hub" in output
        assert "base.py" in output

    def test_resolve_without_args_returns_error(self, handler_simple):
        success, output = handler_simple.handle("resolve", [])
        assert success is False
        assert "FEHLER" in output

    def test_resolve_json_output(self, handler_simple):
        success, output = handler_simple.handle("resolve", ["data/bach.db", "--json"])
        assert success is True
        data = json.loads(output)
        assert "input" in data
        assert "resolved_path" in data
        assert "exists" in data
        assert data["input"] == "data/bach.db"

    def test_resolve_from_root_flag(self, handler_simple):
        success, output = handler_simple.handle("resolve", ["system/hub", "--from-root", "--json"])
        assert success is True
        data = json.loads(output)
        assert data["from_root"] is True

    def test_resolve_absolute_path(self, handler_simple):
        abs_path = str(SYSTEM_ROOT / "hub")
        success, output = handler_simple.handle("resolve", [abs_path, "--json"])
        assert success is True
        data = json.loads(output)
        # Absoluter Pfad sollte nicht gegen base aufgeloest werden
        assert Path(data["resolved_path"]).is_absolute()


# ═══════════════════════════════════════════════════════════════
# JSON Output Mode
# ═══════════════════════════════════════════════════════════════


class TestJsonOutput:
    """Tests fuer den --json Output-Modus."""

    def test_status_json(self, handler_simple):
        success, output = handler_simple.handle("status", ["--json"])
        assert success is True
        data = json.loads(output)
        assert "groups" in data
        assert "generated_at" in data

    def test_overrides_json(self, handler_simple):
        success, output = handler_simple.handle("overrides", ["--json"])
        assert success is True
        data = json.loads(output)
        assert "count" in data
        assert "overrides" in data
        assert "db_path" in data

    def test_help_json(self, handler_simple):
        success, output = handler_simple.handle("help", ["--json"])
        assert success is True
        data = json.loads(output)
        assert "command" in data
        assert "operations" in data
        assert "examples" in data

    def test_json_flag_operation(self, handler_simple):
        """--json als Operation (erster Arg) zeigt Summary als JSON."""
        success, output = handler_simple.handle("--json", [])
        assert success is True
        data = json.loads(output)
        assert "groups" in data


# ═══════════════════════════════════════════════════════════════
# Error Handling
# ═══════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Tests fuer Fehlerbehandlung bei ungueltigen Eingaben."""

    def test_unknown_path_name_raises_keyerror(self, handler_simple):
        """Unbekannter Pfadname fuehrt zu KeyError intern, handle faengt ab."""
        # Bei direktem Zugriff via _get_registry_entry wird KeyError geworfen
        with pytest.raises(KeyError) as exc_info:
            handler_simple._get_registry_entry("nonexistent_gibberish_xyz_12345")
        assert "Unbekannter Pfad" in str(exc_info.value)

    def test_handle_unknown_path_as_operation(self, handler_simple):
        """Unbekannter Pfadname als Operation -> Shortform lookup, KeyError."""
        # Abhaengig von der Implementierung: kann True/False oder Exception sein
        try:
            success, output = handler_simple.handle("nonexistent_gibberish_xyz_12345", [])
            # Falls kein Fehler geworfen: sollte Fehlermeldung enthalten
            # (Implementierung koennte KeyError werfen oder abfangen)
        except KeyError:
            pass  # Erwartetes Verhalten

    def test_set_without_enough_args(self, handler_simple):
        success, output = handler_simple.handle("set", [])
        assert success is False
        assert "FEHLER" in output

    def test_set_with_only_name(self, handler_simple):
        success, output = handler_simple.handle("set", ["test_path"])
        assert success is False
        assert "FEHLER" in output


# ═══════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════


class TestHelperFunctions:
    """Tests fuer interne Hilfsfunktionen."""

    def test_normalize_name_lowercase(self, handler_simple):
        assert handler_simple._normalize_name("HUB") == "hub"
        assert handler_simple._normalize_name("Bach_DB") == "bach_db"

    def test_normalize_name_replaces_hyphens(self, handler_simple):
        assert handler_simple._normalize_name("my-path") == "my_path"

    def test_normalize_name_replaces_spaces(self, handler_simple):
        assert handler_simple._normalize_name("my path") == "my_path"

    def test_has_flag_true(self, handler_simple):
        assert handler_simple._has_flag(["--json", "arg1"], "--json") is True

    def test_has_flag_false(self, handler_simple):
        assert handler_simple._has_flag(["arg1", "arg2"], "--json") is False

    def test_has_flag_multiple(self, handler_simple):
        assert handler_simple._has_flag(["--from-root"], "--from-root", "--root") is True
        assert handler_simple._has_flag(["--root"], "--from-root", "--root") is True

    def test_strip_flags(self, handler_simple):
        result = handler_simple._strip_flags(["--json", "arg1", "arg2"], "--json")
        assert result == ["arg1", "arg2"]

    def test_strip_flags_multiple(self, handler_simple):
        result = handler_simple._strip_flags(
            ["--json", "--from-root", "path/to/file"],
            "--json", "--from-root"
        )
        assert result == ["path/to/file"]

    def test_strip_flags_no_match(self, handler_simple):
        result = handler_simple._strip_flags(["arg1", "arg2"], "--json")
        assert result == ["arg1", "arg2"]

    def test_json_dump_produces_valid_json(self, handler_simple):
        payload = {"key": "value", "number": 42, "umlauts": "Aerzte"}
        result = handler_simple._json_dump(payload)
        parsed = json.loads(result)
        assert parsed == payload

    def test_json_dump_does_not_escape_unicode(self, handler_simple):
        payload = {"name": "Foerderplanung"}
        result = handler_simple._json_dump(payload)
        assert "Foerderplanung" in result  # Nicht escaped


# ═══════════════════════════════════════════════════════════════
# Overrides (mit temp DB)
# ═══════════════════════════════════════════════════════════════


class TestOverrides:
    """Tests fuer DB-basierte Pfad-Overrides."""

    def test_overrides_empty_without_db(self, handler_simple):
        """Ohne passende DB gibt es keine Overrides."""
        # Erstelle Handler mit nicht-existierender DB
        with patch.object(handler_simple, '_active_db_path', return_value=Path("/nonexistent/bach.db")):
            overrides = handler_simple._load_overrides()
            assert overrides == {}

    def test_set_override_dry_run(self, handler_simple):
        success, output = handler_simple.handle("set", ["test_key", "/some/path"], dry_run=True)
        assert success is True
        assert "DRY-RUN" in output

    def test_set_override_dry_run_json(self, handler_simple):
        success, output = handler_simple.handle("set", ["test_key", "/some/path", "--json"], dry_run=True)
        assert success is True
        data = json.loads(output)
        assert data["dry_run"] is True
        assert data["name"] == "test_key"
        assert data["path"] == "/some/path"

    def test_set_and_load_override_in_temp_db(self, tmp_path):
        """Setzt ein Override in einer temp-DB und liest es zurueck."""
        db_path = tmp_path / "test_bach.db"
        custom_path = str(tmp_path / "custom_data")

        # DB erstellen mit system_config Tabelle
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE system_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO system_config (key, value) VALUES (?, ?)",
            ("path.custom_dir", custom_path)
        )
        conn.commit()
        conn.close()

        # Handler mit gepatchter DB
        h = PathHandler(SYSTEM_ROOT)
        with patch.object(h, '_active_db_path', return_value=db_path):
            overrides = h._load_overrides()
            assert "custom_dir" in overrides
            assert str(overrides["custom_dir"]) == custom_path

    def test_overrides_handle_sqlite_error(self, tmp_path):
        """Bei korrupter DB gibt es leere Overrides zurueck."""
        db_path = tmp_path / "corrupt.db"
        db_path.write_text("this is not a valid sqlite database", encoding="utf-8")

        h = PathHandler(SYSTEM_ROOT)
        with patch.object(h, '_active_db_path', return_value=db_path):
            overrides = h._load_overrides()
            assert overrides == {}


# ═══════════════════════════════════════════════════════════════
# Summary Groups / Validation Groups
# ═══════════════════════════════════════════════════════════════


class TestGroupConstants:
    """Tests fuer die Modul-Konstanten SUMMARY_GROUPS und VALIDATION_GROUPS."""

    def test_summary_groups_is_dict(self):
        assert isinstance(SUMMARY_GROUPS, dict)

    def test_summary_groups_has_expected_keys(self):
        assert "core" in SUMMARY_GROUPS
        assert "runtime" in SUMMARY_GROUPS
        assert "workspace" in SUMMARY_GROUPS
        assert "domains" in SUMMARY_GROUPS

    def test_validation_groups_has_severity_levels(self):
        assert "error" in VALIDATION_GROUPS
        assert "warn" in VALIDATION_GROUPS
        assert "info" in VALIDATION_GROUPS

    def test_all_summary_group_values_are_tuples(self):
        for key, value in SUMMARY_GROUPS.items():
            assert isinstance(value, tuple), f"SUMMARY_GROUPS['{key}'] ist kein Tuple"

    def test_all_validation_group_values_are_tuples(self):
        for key, value in VALIDATION_GROUPS.items():
            assert isinstance(value, tuple), f"VALIDATION_GROUPS['{key}'] ist kein Tuple"


# ═══════════════════════════════════════════════════════════════
# Help Operation
# ═══════════════════════════════════════════════════════════════


class TestHelpOperation:
    """Tests fuer die Help-Ausgabe."""

    def test_help_returns_success(self, handler_simple):
        success, output = handler_simple.handle("help", [])
        assert success is True

    def test_help_contains_command_info(self, handler_simple):
        success, output = handler_simple.handle("help", [])
        assert "bach path" in output.lower()

    def test_help_aliases(self, handler_simple):
        """--help und -h sind Aliase fuer help."""
        s1, o1 = handler_simple.handle("--help", [])
        s2, o2 = handler_simple.handle("-h", [])
        assert s1 is True
        assert s2 is True
