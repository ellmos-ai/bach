# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionen für side-effect-freie beobachtende CLI-Aufrufe."""

import atexit
import sys
import time
import types
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import bach as bach_cli


class _DummyHandler:
    def __init__(self, calls):
        self.calls = calls

    def handle(self, operation, args, dry_run=False):
        self.calls.append((operation, list(args), dry_run))
        return True, "[DRY-RUN] ok"


class _DummyRegistry:
    names = ["dummy"]

    @staticmethod
    def suggest(_command):
        return []


class _DummyApp:
    def __init__(self, calls):
        self.calls = calls
        self.registry = _DummyRegistry()

    def get_handler(self, name):
        return _DummyHandler(self.calls) if name == "dummy" else None


@pytest.fixture
def observer_boundary(tmp_path, monkeypatch):
    """Installiert sichtbare Sentinels an allen globalen Startnebenwirkungen."""
    effects = tmp_path / "effects"
    effects.mkdir()
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "config" / "db_sync_enabled").touch()

    def mark(name):
        (effects / name).write_text("called", encoding="utf-8")

    class FakeSyncManager:
        def __init__(self):
            mark("prosync-init")

        def sync_on_start(self):
            mark("prosync-start")
            return True, "ok"

        def sync_on_exit(self):
            mark("prosync-exit")
            return True, "ok"

    class FakeTracker:
        def __init__(self, *_args, **_kwargs):
            mark("activity-init")

        def check_eod_and_finalize(self, *_args, **_kwargs):
            mark("activity-eod")

        def check_idle_and_finalize(self, *_args, **_kwargs):
            mark("activity-idle")

        def tick(self, *_args, **_kwargs):
            mark("activity-tick")

    sync_module = types.ModuleType("hub.db_sync")
    sync_module.DBSyncManager = FakeSyncManager
    activity_module = types.ModuleType("tools.activity_tracker")
    activity_module.ActivityTracker = FakeTracker

    monkeypatch.setattr(bach_cli, "DATA_DIR", data_dir)
    monkeypatch.setattr(bach_cli, "DB_PATH", tmp_path / "bach.db")
    monkeypatch.setattr(bach_cli, "get_logger", lambda *_args, **_kwargs: mark("autolog"))
    monkeypatch.setattr(
        bach_cli,
        "_run_prosync_startup",
        lambda: (mark("prosync-start") or True, "ok"),
    )
    monkeypatch.setattr(bach_cli, "cmd", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bach_cli, "_run_injectors", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "hub.db_sync", sync_module)
    monkeypatch.setitem(sys.modules, "tools.activity_tracker", activity_module)
    monkeypatch.setattr(atexit, "register", lambda *_args, **_kwargs: mark("atexit-register"))
    monkeypatch.setattr(bach_cli, "_exit_sync_registered", False)

    return effects


def test_version_bypasses_all_global_start_side_effects(
    observer_boundary, monkeypatch, capsys
):
    """Ein fehlender früher Version-Exit darf keine globale Startarbeit reaktivieren."""
    app_calls = []
    monkeypatch.setattr(bach_cli, "_get_app", lambda: _DummyApp(app_calls))
    monkeypatch.setattr(sys, "argv", ["bach.py", "--version"])

    rc = bach_cli.main()

    assert rc == 0
    assert capsys.readouterr().out.strip() == "BACH v3.13.0-bluesky"
    assert list(observer_boundary.iterdir()) == []
    assert app_calls == []


def test_top_level_help_bypasses_all_global_start_side_effects(
    observer_boundary, monkeypatch, capsys
):
    """Ein Rückfall hinter Logger, ProSync oder Registry macht Help wieder blockierbar."""
    app_calls = []
    monkeypatch.setattr(bach_cli, "_get_app", lambda: _DummyApp(app_calls))
    monkeypatch.setattr(sys, "argv", ["bach.py", "--help"])

    rc = bach_cli.main()

    assert rc == 0
    output = capsys.readouterr().out
    assert "BACH v3.13.0-bluesky" in output
    assert "USAGE:" in output
    assert list(observer_boundary.iterdir()) == []
    assert app_calls == []


def test_subcommand_help_bypasses_global_start_side_effects(
    observer_boundary, monkeypatch, capsys
):
    """Auch `command --help` muss vor Logger, ProSync und Activity abzweigen."""
    calls = []

    class HelpHandler:
        def handle(self, operation, args, dry_run=False):
            calls.append((operation, list(args), dry_run))
            return True, "dummy help"

    class HelpApp:
        def get_handler(self, name):
            return HelpHandler() if name == "help" else None

    monkeypatch.setattr(bach_cli, "_get_app", lambda: HelpApp())
    monkeypatch.setattr(sys, "argv", ["bach.py", "dummy", "--help"])

    rc = bach_cli.main()

    assert rc == 0
    assert capsys.readouterr().out.strip() == "dummy help"
    assert list(observer_boundary.iterdir()) == []
    assert calls == [("dummy", [], False)]


def test_dry_run_dispatch_skips_global_start_side_effects(
    observer_boundary, monkeypatch, capsys
):
    """Ein Dry-run darf nicht vor dem Handler Logger, Sync oder Activity schreiben."""
    app_calls = []
    monkeypatch.setattr(bach_cli, "_get_app", lambda: _DummyApp(app_calls))
    monkeypatch.setattr(sys, "argv", ["bach.py", "dummy", "run", "--dry-run"])

    rc = bach_cli.main()

    assert rc == 0
    assert "[DRY-RUN] ok" in capsys.readouterr().out
    assert list(observer_boundary.iterdir()) == []
    assert app_calls == [("run", ["--dry-run"], True)]


def test_bounded_worker_terminates_a_slow_real_process():
    """Ohne harten Prozessabbruch kann ein Cloud-Hänger das Budget überziehen."""
    run_bounded = getattr(bach_cli, "_run_bounded_command", None)
    assert run_bounded is not None, "Der begrenzte Prozess-Runner fehlt"

    started = time.monotonic()
    completed, timed_out = run_bounded(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout_seconds=0.2,
    )
    elapsed = time.monotonic() - started

    assert completed is None
    assert timed_out is True
    assert elapsed < 2.0


def test_prosync_timeout_is_reported_before_dispatch_and_disables_exit_push(
    observer_boundary, monkeypatch, capsys
):
    """Ein abgebrochener Pull darf weder still bleiben noch einen Exit-Push planen."""
    app_calls = []
    observed = {}

    def fake_startup_sync():
        observed["output_before_sync"] = capsys.readouterr().out
        return False, "Startzeitbudget von 0.2 s überschritten"

    monkeypatch.setattr(
        bach_cli, "_run_prosync_startup", fake_startup_sync, raising=False
    )
    monkeypatch.setattr(bach_cli, "_get_app", lambda: _DummyApp(app_calls))
    monkeypatch.setattr(sys, "argv", ["bach.py", "dummy", "run"])

    rc = bach_cli.main()
    output = capsys.readouterr().out

    assert rc == 0
    assert "[ProSync] Starte Pull" in observed.get("output_before_sync", "")
    assert "Startzeitbudget von 0.2 s überschritten" in output
    assert not (observer_boundary / "atexit-register").exists()
    assert app_calls == [("run", [], False)]


def test_unknown_command_does_not_write_activity(
    observer_boundary, monkeypatch, capsys
):
    """Ein unbekannter Befehl ist nicht angenommen und darf keinen Tick schreiben."""
    monkeypatch.setattr(bach_cli, "_get_app", lambda: _DummyApp([]))
    monkeypatch.setattr(sys, "argv", ["bach.py", "definitely-unknown-command"])

    rc = bach_cli.main()

    assert rc == 1
    assert "Unbekannter Befehl" in capsys.readouterr().out
    assert not any(p.name.startswith("activity-") for p in observer_boundary.iterdir())


def test_activity_ticks_only_after_handler_acceptance(monkeypatch, tmp_path, capsys):
    """CLI-Dispatch darf weder vor Annahme noch per Idle/EOD versteckt finalisieren."""
    events = []

    class OrderedTracker:
        def __init__(self, *_args, **_kwargs):
            events.append("activity-init")

        def check_eod_and_finalize(self, *_args, **_kwargs):
            events.append("activity-eod")

        def check_idle_and_finalize(self, *_args, **_kwargs):
            events.append("activity-idle")

        def tick(self, *_args, **_kwargs):
            events.append("activity-tick")

    class OrderedHandler:
        def handle(self, operation, args, dry_run=False):
            events.append("handled")
            return True, "ok"

    class OrderedRegistry:
        @staticmethod
        def suggest(_command):
            return []

    class OrderedApp:
        registry = OrderedRegistry()

        def get_handler(self, name):
            events.append("accepted")
            return OrderedHandler() if name == "dummy" else None

    activity_module = types.ModuleType("tools.activity_tracker")
    activity_module.ActivityTracker = OrderedTracker
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(bach_cli, "DATA_DIR", data_dir)
    monkeypatch.setattr(bach_cli, "DB_PATH", tmp_path / "bach.db")
    monkeypatch.setattr(bach_cli, "get_logger", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bach_cli, "_get_app", lambda: OrderedApp())
    monkeypatch.setattr(bach_cli, "cmd", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bach_cli, "_run_injectors", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "tools.activity_tracker", activity_module)
    monkeypatch.setattr(sys, "argv", ["bach.py", "dummy", "run"])

    rc = bach_cli.main()

    assert rc == 0
    assert capsys.readouterr().out.strip() == "ok"
    assert events == [
        "accepted",
        "activity-init",
        "activity-tick",
        "handled",
    ]
