from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hub._services.document import report_host_loader as loader


def config(**changes):
    return {"enabled": True, "provider_name": "fixture-provider", "agent_id": "fixture-agent", **changes}


class Entry:
    def __init__(self, name, factory):
        self.name, self.factory, self.loads = name, factory, 0

    def load(self):
        self.loads += 1
        return self.factory


@pytest.mark.parametrize("value", [
    None, {}, [], config(enabled=False), config(enabled=1),
    config(provider_name=""), config(provider_name="../private"),
    config(provider_name="a" * 81), config(agent_id=""),
    config(agent_id="a/b"), config(agent_id="a" * 81),
    config(agent_id=123), config(provider_name=123),
    config(secret="must-not-be-consumed"),
    {"enabled": True, "provider_name": "fixture-provider"},
])
def test_invalid_or_disabled_never_discovers(monkeypatch, value):
    def forbidden(**kwargs):
        pytest.fail("disabled/invalid configuration discovered installed plugins")

    monkeypatch.setattr(loader.metadata, "entry_points", forbidden)
    assert loader.load_report_host_dependencies(value) is None


def test_only_named_factory_loaded_without_arguments(monkeypatch):
    ports = {"document_reader": object(), "operator_confirmation": object()}
    calls = []
    chosen = Entry("fixture-provider", lambda: (calls.append(()) or ports))
    other = Entry("other-provider", lambda: pytest.fail("fallback was loaded"))
    seen = []
    def discover(**kwargs):
        seen.append(kwargs)
        return [other, chosen]
    monkeypatch.setattr(loader.metadata, "entry_points", discover)
    assert loader.load_report_host_dependencies(config()) is ports
    assert calls == [()]
    assert seen == [{"group": loader.HOST_DEPENDENCIES_GROUP}]
    assert chosen.loads == 1 and other.loads == 0


@pytest.mark.parametrize("names", [[], ["other-provider"], ["fixture-provider", "fixture-provider"]])
def test_missing_or_ambiguous_has_no_fallback(monkeypatch, names):
    entries = [Entry(name, lambda: pytest.fail("ambiguous factory invoked")) for name in names]
    monkeypatch.setattr(loader.metadata, "entry_points", lambda **kwargs: entries)
    assert loader.load_report_host_dependencies(config()) is None
    assert not any(entry.loads for entry in entries)


@pytest.mark.parametrize("factory", [
    None, lambda: None, lambda: [], lambda: {"local_model": object()},
    lambda: {"secret": "private-path-fixture"},
])
def test_invalid_factory_or_dependency_keys_are_unavailable(monkeypatch, factory):
    monkeypatch.setattr(loader.metadata, "entry_points",
                        lambda **kwargs: [Entry("fixture-provider", factory)])
    assert loader.load_report_host_dependencies(config()) is None


@pytest.mark.parametrize("phase", ["discovery", "load", "factory"])
def test_exception_never_logs_private_content(monkeypatch, capsys, caplog, phase):
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_PLUGIN_SECRET_FIXTURE")
    entry = Entry("fixture-provider", fail if phase == "factory" else lambda: {})
    if phase == "load":
        entry.load = fail
    monkeypatch.setattr(loader.metadata, "entry_points",
                        fail if phase == "discovery" else lambda **kwargs: [entry])
    assert loader.load_report_host_dependencies(config()) is None
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
    assert "PRIVATE_PLUGIN_SECRET_FIXTURE" not in caplog.text


def test_control_main_passes_configured_dependencies_without_starting_other_work():
    # Execute the actual main function alone; avoid importing the Telegram runtime.
    source = Path(__file__).resolve().parents[1] / "hub/_services/chat/telegram_chat.py"
    tree = ast.parse(source.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = []
    dependencies = {"document_reader": object()}
    import hub._services.document.report_host_loader as imported
    original = imported.load_report_host_dependencies
    imported.load_report_host_dependencies = lambda value: (calls.append(value) or dependencies)
    try:
        namespace = {
            "CONFIG": {"reports": config()},
            "start_control_api": lambda **kwargs: (calls.append(kwargs) or None),
        }
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), "exec"), namespace)
        assert namespace["main"]() == 1
        assert calls == [config(), {"report_host_dependencies": dependencies}]
    finally:
        imported.load_report_host_dependencies = original
