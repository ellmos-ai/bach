"""Hermetische Chat-Hinweise: vorhandene Ziele, CLI-Parität und Auswahlregeln."""
import importlib.util
import sqlite3
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(SYSTEM / 'tools'))
import injectors
from hub.context_hints import CLI_PATTERN, ChatTriggerBackend, neutral_manual_hint


@pytest.mark.parametrize('phrase', [
    'steuer', 'medikament', 'versicherung', 'abo', 'fixkosten', 'arzt',
    'fehler', 'memory', 'backup', 'pfad', 'json',
])
def test_manual_cli_becomes_existing_document(phrase):
    original = injectors.ContextInjector.CONTEXT_TRIGGERS[phrase]
    rendered = neutral_manual_hint(original, SYSTEM)
    assert rendered != original
    assert not CLI_PATTERN.search(rendered)
    targets = rendered.split('Dokumentation: ')[1].split(' | ')
    assert all((SYSTEM / target).is_file() for target in targets)
    assert injectors.ContextInjector.CONTEXT_TRIGGERS[phrase] == original


@pytest.mark.parametrize('hint', [
    'Eigene Anleitung: bach unknown_private_command run',
    'Fehlende Datei: python absent.py',
    'Pfad verlassen: python ../outside.py',
    'Gemischte Ziele: bach steuer status | bach unknown_private_command run',
    'Kuratierter Pfad: skills/workflows/example',
])
def test_unknown_or_noncli_hint_unchanged(hint):
    assert neutral_manual_hint(hint, SYSTEM) == hint


@pytest.mark.parametrize('hint', ['python tools/absent.py', 'python "absent.py"',
                                 'python3 absent.py', 'python ../outside.py'])
def test_unknown_python_paths_remain_filtered(hint):
    import bach_api
    proxy = bach_api._InjectorProxy()
    proxy.set_mode('api')
    assert proxy._filter_cli(['[KONTEXT] ' + hint]) == []


def test_legacy_selects_visible_hint_before_usage(monkeypatch):
    ci = injectors.ContextInjector
    monkeypatch.setattr(ci, '_last_load', datetime.now())  # noqa: DTZ005 -- lokale Zeit des Altpfads
    monkeypatch.setattr(ci, '_cache', {
        'steuer': {'id': 1, 'source': 'manual', 'pattern': ci._compile_trigger('steuer'),
                   'hint': 'Privat: bach unknown_private_command run'},
        'steuer|beleg': {'id': 2, 'source': 'manual', 'pattern': ci._compile_trigger('steuer|beleg'),
                        'hint': ci.CONTEXT_TRIGGERS['steuer']},
    })
    used = []
    monkeypatch.setattr(ci, '_mark_usage', classmethod(lambda cls, rule_id: used.append(rule_id)))
    assert ci.check('steuer', cli_hints=False) == '[KONTEXT] ' + neutral_manual_hint(
        ci.CONTEXT_TRIGGERS['steuer'], SYSTEM)
    assert used == [2]
    assert ci.check('steuer') == '[KONTEXT] Privat: bach unknown_private_command run'
    assert used == [2, 1]


def test_api_passes_mode_before_context_selection(monkeypatch):
    import bach_api
    seen = []

    class System:
        def process(self, text, context, *, skip, cli_hints):
            seen.append((text, skip, cli_hints))
            return []

    proxy = bach_api._InjectorProxy()
    proxy._system = System()
    proxy.set_mode('api')
    assert proxy.process('steuer', skip={'strategy'}) == []
    proxy.set_mode('cli')
    assert proxy.process('steuer') == []
    assert seen == [('steuer', {'strategy'}, False), ('steuer', (), True)]


def test_actual_legacy_api_does_not_consume_cooldown_for_unknown_hint(tmp_path, monkeypatch):
    import bach_api
    ci = injectors.ContextInjector
    system = injectors.InjectorSystem(tmp_path)
    monkeypatch.setattr(ci, 'base_path', tmp_path)
    monkeypatch.setattr(ci, '_last_load', datetime.now())  # noqa: DTZ005 -- lokale Zeit des Altpfads
    monkeypatch.setattr(ci, '_cache', {
        'privat': {'id': 1, 'source': 'manual', 'hint': 'Privat: bach unknown_private_command run'},
        'steuer': {'id': 2, 'source': 'manual', 'hint': ci.CONTEXT_TRIGGERS['steuer']},
    })
    used = []
    monkeypatch.setattr(ci, '_mark_usage', classmethod(lambda cls, rule_id: used.append(rule_id)))
    monkeypatch.setattr(injectors.ToolInjector, 'check_before_create', lambda text: None)
    monkeypatch.setattr(system.config, 'is_enabled', lambda name: name == 'context_injector')
    proxy = bach_api._InjectorProxy()
    proxy._system = system
    proxy.set_mode('api')
    assert proxy.process('privat') == []
    assert not system.cooldown.is_on_cooldown('context')
    assert proxy.process('steuer') == ['[KONTEXT] ' + neutral_manual_hint(ci.CONTEXT_TRIGGERS['steuer'], SYSTEM)]
    assert system.cooldown.is_on_cooldown('context')
    assert used == [2]


def _database(path):
    spec = importlib.util.spec_from_file_location(
        'manual_hint_union', SYSTEM / 'data/schema/memory_union/memory_union.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = sqlite3.connect(path)
    module.create_union_schema(conn)
    rows = [
        ('steuer', 'Privat: bach unknown_private_command run', 'manual', 1, 'approved'),
        ('steuer|beleg', injectors.ContextInjector.CONTEXT_TRIGGERS['steuer'], 'manual', 1, 'approved'),
        ('gesperrt', injectors.ContextInjector.CONTEXT_TRIGGERS['steuer'], 'manual', 1, 'blocked'),
        ('ausgeschaltet', injectors.ContextInjector.CONTEXT_TRIGGERS['steuer'], 'manual', 0, 'approved'),
        ('toolprobe', injectors.ContextInjector.CONTEXT_TRIGGERS['steuer'], 'tool', 1, 'approved'),
    ]
    conn.executemany('INSERT INTO context_triggers '
                     '(trigger_phrase,hint_text,source,is_active,status) VALUES (?,?,?,?,?)', rows)
    conn.commit()
    conn.close()


def test_external_chat_preserves_flags_rules_and_counts_only_shown(tmp_path, monkeypatch):
    pytest.importorskip('memoryhooker.triggers')
    from hub import memory_hook_provider as mhp
    db = tmp_path / 'memory.db'
    _database(db)
    monkeypatch.setenv(mhp.CONTEXT_TRIGGERS_DB_ENV, '1')
    monkeypatch.delenv(mhp.LEGACY_INJECTORS_ENV, raising=False)
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    hook = mhp.ExternalMemoryHook(db_path=db, config_path=tmp_path / 'missing.toml')
    assert hook._groups_supported
    hook._config = replace(hook._config, triggers=replace(
        hook._config.triggers, sources=['context'], cooldowns={'context': 60}))
    original = hook.backend.triggers(['manual'])
    adapted = ChatTriggerBackend(hook.backend, SYSTEM).triggers(['manual'])
    assert adapted[1].rule_id == original[1].rule_id
    assert adapted[1].hint != original[1].hint
    assert hook.backend.triggers(['manual']) == original
    visible = hook.hook_context('steuer', 'chat', cli_hints=False)
    assert '[KONTEXT] ' + neutral_manual_hint(original[1].hint, SYSTEM) in visible
    assert '[KONTEXT]' not in (hook.hook_context('steuer', 'chat', cli_hints=False) or '')
    for prompt in ('gesperrt', 'ausgeschaltet', 'toolprobe'):
        assert '[KONTEXT]' not in (hook.hook_context(prompt, prompt, cli_hints=False) or '')
    assert original[0].hint in hook.hook_context('steuer', 'cli', cli_hints=True)
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute('SELECT hint_text,is_active,status,usage_count FROM context_triggers ORDER BY id').fetchall()
    finally:
        conn.close()
    assert [r[3] for r in rows] == [1, 1, 0, 0, 0]
    assert rows[2][1:3] == (1, 'blocked')
    assert rows[3][1:3] == (0, 'approved')
    assert rows[1][0] == original[1].hint
