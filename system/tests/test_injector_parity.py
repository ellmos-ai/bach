"""Adapter-Tests v2.0.0 für system/tools/injectors.py.

injectors.py ist ein dünner Adapter auf hub.memory_hook_provider
(get_shared_memory_hook) und ersetzt die Legacy-Injektoren. Diese Suite testet
das Adapterverhalten direkt — OHNE Abhängigkeit von memoryhooker. Die frühere
Legacy-Parity-Suite (alt==neu gegen memoryhooker) crashte am entfernten
StrategyInjector.STRATEGIES und wurde hier komplett ersetzt.

Abgedeckt:
- InjectorConfig: Defaults, Datei-Laden, defektes JSON, toggle-Persistenz
- TimeInjector: ohne base_path, mit Fake-Modul tools.time_system,
  Fehlerfall set_interval-AttributeError -> manager None
- InjectorSystem: ohne/mit Shared-Hook, process-Weiterleitung mit exakten
  kwargs (chat_id="adapter"), check_between, Fassadenmethoden,
  Legacy-classmethods, Constructor-Wiring.

Wichtig: InjectorSystem mit base_path nur mit Fakezeit-Modul instantiieren
(auf Base-Path importiert injectors sonst den echten TimeManager).
"""
import json
import sys
import types
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parents[1]
for _p in (str(SYSTEM_DIR / "tools"), str(SYSTEM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import injectors  # noqa: E402


class FakeHook:
    """Minimaler Doppelgänger für get_shared_memory_hook."""

    def __init__(self, ctx_result=None, cli_result=(None, []), ctx_raises=None,
                 cli_raises=None):
        self.ctx_result = ctx_result
        self.cli_result = cli_result
        self.ctx_raises = ctx_raises
        self.cli_raises = cli_raises
        self.ctx_calls = []
        self.cli_calls = []

    def hook_context(self, **kwargs):
        self.ctx_calls.append(kwargs)
        if self.ctx_raises is not None:
            raise self.ctx_raises
        return self.ctx_result

    def cli_injections(self, **kwargs):
        self.cli_calls.append(kwargs)
        if self.cli_raises is not None:
            raise self.cli_raises
        return self.cli_result


class RecordingFakeTimeManager:
    """Ersatz für tools.time_system.TimeManager; set_interval zeichnet auf."""

    def __init__(self, base_path=None):
        self.base_path = base_path
        self.interval = None
        self.set_interval_calls = []

    def set_interval(self, i):
        self.interval = i
        self.set_interval_calls.append(i)

    def timebeat(self):
        return "beat"


class NoSetIntervalTimeManager:
    """Variante ohne set_interval -> AttributeError im Injector-try-Block."""

    def __init__(self, base_path=None):
        self.base_path = base_path

    def timebeat(self):
        return "beat"


def install_fake_time_module(monkeypatch, manager_cls=RecordingFakeTimeManager):
    mod_tools = types.ModuleType("tools")
    mod_ts = types.ModuleType("tools.time_system")
    mod_ts.TimeManager = manager_cls
    mod_tools.time_system = mod_ts
    monkeypatch.setitem(sys.modules, "tools", mod_tools)
    monkeypatch.setitem(sys.modules, "tools.time_system", mod_ts)
    return mod_ts


def make_system(tmp_path, monkeypatch, hook=None):
    """InjectorSystem mit Fakezeit-Modul und gestrecktem Shared-Hook bauen."""
    install_fake_time_module(monkeypatch)
    monkeypatch.setattr(injectors, "get_shared_memory_hook", lambda *a, **k: hook)
    return injectors.InjectorSystem(tmp_path)


# --- InjectorConfig -------------------------------------------------------

def test_injector_config_defaults(tmp_path):
    cfg = injectors.InjectorConfig(tmp_path / "config.json")
    assert cfg.config == {
        "strategy_injector": True,
        "context_injector": True,
        "time_injector": True,
        "between_injector": True,
        "timebeat_interval": 60,
    }
    assert cfg.is_enabled("unbekannt") is False


def test_injector_config_loads_existing_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"injectors": {"strategy_injector": False}}), encoding="utf-8"
    )
    cfg = injectors.InjectorConfig(path)
    assert cfg.is_enabled("strategy_injector") is False
    assert cfg.is_enabled("context_injector") is True
    assert cfg.is_enabled("time_injector") is True


def test_injector_config_bad_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{kein json", encoding="utf-8")
    cfg = injectors.InjectorConfig(path)
    assert cfg.config["strategy_injector"] is True
    assert cfg.config["timebeat_interval"] == 60


def test_toggle_persists_to_file(tmp_path):
    path = tmp_path / "config.json"
    cfg = injectors.InjectorConfig(path)
    assert cfg.toggle("strategy_injector") is False
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["injectors"]["strategy_injector"] is False
    assert cfg.is_enabled("strategy_injector") is False
    assert cfg.toggle("strategy_injector") is True
    assert cfg.is_enabled("strategy_injector") is True
    assert cfg.toggle("bogus") is False
    assert "bogus" not in cfg.config
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "bogus" not in data["injectors"]


# --- TimeInjector ---------------------------------------------------------

class _StubManager:
    def timebeat(self):
        return "beat"


def test_time_injector_without_base_path(tmp_path):
    ti = injectors.TimeInjector()
    assert ti.manager is None
    assert ti.check() is None


def test_time_injector_check_uses_manager_timebeat(tmp_path):
    ti = injectors.TimeInjector()
    ti.manager = _StubManager()
    assert ti.check() == "beat"


def test_time_injector_with_base_path_uses_fake_manager(tmp_path, monkeypatch):
    install_fake_time_module(monkeypatch)
    ti = injectors.TimeInjector(30, tmp_path)
    assert isinstance(ti.manager, RecordingFakeTimeManager)
    assert ti.manager.set_interval_calls == [30]
    assert ti.check() == "beat"


def test_time_injector_set_interval_attribute_error_is_swallowed(
    tmp_path, monkeypatch
):
    # AttributeError beim set_interval wird geschluckt; der Manager bleibt
    # instanziiert und check() laeuft auf timebeat() weiter.
    install_fake_time_module(monkeypatch, manager_cls=NoSetIntervalTimeManager)
    ti = injectors.TimeInjector(30, tmp_path)
    assert isinstance(ti.manager, NoSetIntervalTimeManager)
    assert not hasattr(ti.manager, "set_interval")
    assert ti.check() == "beat"


# --- InjectorSystem: Shared-Hook-Adapterverhalten --------------------------

def test_system_without_shared_hook_returns_neutral(tmp_path, monkeypatch):
    inj = make_system(tmp_path, monkeypatch, hook=None)
    assert inj.process("irgendein text") == []
    assert inj.check_between("ls -la") is None


def test_process_forwards_exact_kwargs(tmp_path, monkeypatch):
    hook = FakeHook(ctx_result={"text": "INJEZIERT"})
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    assert inj.process("t") == [{"text": "INJEZIERT"}]
    assert hook.ctx_calls == [
        {"text": "t", "chat_id": "adapter", "cli_hints": True, "disabled": frozenset()}
    ]


def test_process_passes_cli_hints_false_and_ignores_context(tmp_path, monkeypatch):
    hook = FakeHook(ctx_result={"text": "INJEZIERT"})
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    out = inj.process("t", cli_hints=False, context={"a": 1}, skip=("s",))
    assert out == [{"text": "INJEZIERT"}]
    assert hook.ctx_calls[0]["cli_hints"] is False
    assert "context" not in hook.ctx_calls[0]
    assert "skip" not in hook.ctx_calls[0]


def test_process_none_or_empty_injection_returns_empty_list(tmp_path, monkeypatch):
    for res in (None, {}):
        hook = FakeHook(ctx_result=res)
        inj = make_system(tmp_path, monkeypatch, hook=hook)
        assert inj.process("t") == []


def test_process_hook_exception_returns_empty_list(tmp_path, monkeypatch):
    hook = FakeHook(ctx_result=None, ctx_raises=RuntimeError("boom"))
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    assert inj.process("t") == []


def test_check_between_returns_first_entry(tmp_path, monkeypatch):
    hook = FakeHook(cli_result=(None, ["A", "B"]))
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    assert inj.check_between("ls -la") == "A"
    assert hook.cli_calls == [
        {"output": "", "last_command": "ls -la", "disabled": frozenset()}
    ]


def test_check_between_empty_list_returns_none(tmp_path, monkeypatch):
    hook = FakeHook(cli_result=(None, []))
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    assert inj.check_between("ls") is None


def test_check_between_survives_hook_exception(tmp_path, monkeypatch):
    hook = FakeHook(cli_raises=RuntimeError("boom"))
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    assert inj.check_between("ls") is None


def test_check_between_session_ending_not_forwarded(tmp_path, monkeypatch):
    hook = FakeHook(cli_result=(None, ["A", "B"]))
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    assert inj.check_between("ls", session_ending=True) == "A"
    assert hook.cli_calls[0] == {
        "output": "",
        "last_command": "ls",
        "disabled": frozenset(),
    }


# --- InjectorSystem: Fassade und Legacy-Oberfläche -------------------------

def test_system_facade_toggle_is_enabled_status_persist(tmp_path, monkeypatch):
    inj = make_system(tmp_path, monkeypatch, hook=None)
    assert inj.toggle("time_injector") is False
    assert inj.is_enabled("time_injector") is False
    assert inj.is_enabled("context_injector") is True

    status = inj.status()
    assert status == inj.config.config
    assert "timebeat_interval" in status
    status["timebeat_interval"] = 1
    assert inj.status()["timebeat_interval"] == 60  # status() liefert Kopie

    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert data["injectors"]["time_injector"] is False


def test_neutral_facade_methods(tmp_path, monkeypatch):
    inj = make_system(tmp_path, monkeypatch, hook=None)
    assert inj.check_before_create("irgendein text") is None
    assert inj.get_tool_reminder() is None
    assert inj.get_cooldown_state("strategy_injector") == {
        "remaining": 0,
        "last_shown": None,
    }
    inj.mark_shown("strategy_injector")
    assert inj.is_on_cooldown("strategy_injector") is False


def test_legacy_class_methods_return_none(tmp_path):
    assert injectors.StrategyInjector.check("text", context=None) is None
    assert injectors.ContextInjector.check("text", cli_hints=True) is None
    assert injectors.ToolInjector.check_before_create("text") is None
    assert injectors.ToolInjector.get_startup_reminder(tmp_path) is None
    assert injectors.BetweenInjector.check_task_done("ls -la") is None


def test_constructor_wires_shared_hook(tmp_path, monkeypatch):
    hook = FakeHook()
    inj = make_system(tmp_path, monkeypatch, hook=hook)
    assert inj._shared_hook is hook
