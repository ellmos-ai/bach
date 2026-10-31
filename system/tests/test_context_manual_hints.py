"""Hermetische Chat-Hinweise: vorhandene Ziele, CLI-Parität und Auswahlregeln."""
import importlib.util
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(SYSTEM / 'tools'))
import injectors  # noqa: E402
from hub import memory_hook_provider as mhp  # noqa: E402
from hub.context_hints import CLI_PATTERN, ChatTriggerBackend, neutral_manual_hint  # noqa: E402

MANUAL_HINTS = {
    'steuer': 'Steuer-Tools: bach steuer status/beleg/posten/export | Steuer-Workflow',
    'medikament': 'Medikamente: bach gesundheit medikamente | bach.db health_medications',
    'versicherung': 'Versicherungs-Verwaltung: bach versicherung status | bach versicherung list/check/fristen',
    'abo': 'Abo-Verwaltung: bach abo list/check/export',
    'fixkosten': 'Fixkosten: bach haushalt fixkosten | bach.db fin_contracts',
    'fehler': 'Bekannte Fehler? --help lessons',
    'memory': 'Memory-Fragen? --help memory',
    'backup': 'Backup: bach backup create [--to-nas] | bach backup list | python system/tools/backup_manager.py restore backup latest',
    'pfad': 'Pfad-Fragen? --help dirs',
    'json': 'JSON-Probleme? bach c_json_repair <datei>',
    'arzt': 'Gesundheit: bach gesundheit termine --upcoming | diagnosen',
}


@pytest.mark.parametrize('phrase', [
    'steuer', 'medikament', 'versicherung', 'abo', 'fixkosten',
    'fehler', 'memory', 'backup', 'pfad', 'json',
])
def test_manual_cli_becomes_existing_document(phrase):
    original = MANUAL_HINTS[phrase]
    rendered = neutral_manual_hint(original, SYSTEM)
    assert rendered != original
    assert not CLI_PATTERN.search(rendered)
    targets = rendered.split('Dokumentation: ')[1].split(' | ')
    assert all((SYSTEM / target).is_file() for target in targets)
    assert MANUAL_HINTS[phrase] == original


@pytest.mark.parametrize('hint', [
    'Eigene Anleitung: bach unknown_private_command run',
    'Fehlende Datei: python absent.py',
    'Pfad verlassen: python ../outside.py',
    'Gemischte Ziele: bach steuer status | bach unknown_private_command run',
    'Kuratierter Pfad: skills/workflows/example',
])
def test_unknown_or_noncli_hint_unchanged(hint):
    assert neutral_manual_hint(hint, SYSTEM) == hint


def _setup_adapter_db(tmp_path, rows):
    (tmp_path / 'data').mkdir(exist_ok=True)
    (tmp_path / 'config.json').write_text(
        '{"injectors": {"strategy_injector": false, "time_injector": false, "context_injector": true}}',
        encoding='utf-8',
    )
    db = tmp_path / 'data' / 'bach.db'
    spec = importlib.util.spec_from_file_location(
        'manual_hint_union', SYSTEM / 'data/schema/memory_union/memory_union.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = sqlite3.connect(db)
    module.create_union_schema(conn)
    conn.executemany(
        'INSERT INTO context_triggers (trigger_phrase,hint_text,source,is_active,status) VALUES (?,?,?,?,?)',
        rows,
    )
    conn.commit()
    conn.close()
    return db


def test_stale_arzt_option_is_preserved_and_filtered(tmp_path, monkeypatch):
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    original = MANUAL_HINTS['arzt']
    assert '--upcoming' in original
    assert '--upcoming' not in (SYSTEM / 'docs/help/gesundheit.txt').read_text(encoding='utf-8')
    assert '--upcoming' not in (SYSTEM / 'hub/gesundheit.py').read_text(encoding='utf-8')
    assert neutral_manual_hint(original, SYSTEM) == original
    db = _setup_adapter_db(tmp_path, [('arzt', original, 'manual', 1, 'approved')])
    system = injectors.InjectorSystem(tmp_path)
    assert system.process('arzt', cli_hints=False) == []
    conn = sqlite3.connect(db)
    assert conn.execute('SELECT usage_count FROM context_triggers WHERE id=1').fetchone()[0] == 0
    conn.close()
    assert system.process('arzt', cli_hints=True) == ['[KONTEXT] ' + original]
    conn = sqlite3.connect(db)
    assert conn.execute('SELECT usage_count FROM context_triggers WHERE id=1').fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize('hint', [
    'Bekannt: bach gesundheit appointments --all',
    'Bekannt: bach backup create --to-nas',
    'Bekannt: python tools/backup_manager.py',
    'Bekannt: python3 system/tools/backup_manager.py',
    'Bekannt: python3 "system/tools/backup_manager.py"',
    "Bekannt: python 'system/tools/backup_manager.py'",
])
def test_supported_options_and_quoted_python_targets_stay_visible(hint):
    rendered = neutral_manual_hint(hint, SYSTEM)
    assert rendered != hint
    assert not CLI_PATTERN.search(rendered)
    assert all((SYSTEM / target).is_file() for target in rendered.split('Dokumentation: ')[1].split(' | '))


@pytest.mark.parametrize('tail', [
    '--unknown-danger', '--unknown-danger=1', '--format-unknown',
    '| --format', '| python -u absent.py', '| python3 "missing file.py"',
])
def test_unknown_attached_or_unowned_cli_marker_preserves_original(tail):
    hint = 'Gemischt: bach steuer status ' + tail
    assert neutral_manual_hint(hint, SYSTEM) == hint


@pytest.mark.parametrize('target', [
    '"tools/backup_manager.py".bak', "'tools/backup_manager.py'/absent",
    '"tools/backup_manager.py?absent"', 'tools/backup_manager.py\x00',
])
def test_quoted_or_invalid_complete_python_argument_is_preserved(target):
    hint = 'Gemischt: bach steuer status | python ' + target
    assert neutral_manual_hint(hint, SYSTEM) == hint


@pytest.mark.parametrize('hint', ['python tools/absent.py', 'python "absent.py"',
                                 'python3 absent.py', 'python ../outside.py'])
def test_unknown_python_paths_remain_filtered(hint):
    from system import bach_api
    proxy = bach_api._InjectorProxy()
    proxy.set_mode('api')
    assert proxy._filter_cli(['[KONTEXT] ' + hint]) == []


def test_adapter_selects_visible_hint_before_usage(tmp_path, monkeypatch):
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    db = _setup_adapter_db(tmp_path, [
        ('steuer', 'Privat: bach unknown_private_command run', 'manual', 1, 'approved'),
        ('steuer|beleg', MANUAL_HINTS['steuer'], 'manual', 1, 'approved'),
    ])
    system = injectors.InjectorSystem(tmp_path)
    hook, _ = system._get_seam()
    hook._config = replace(hook._config, triggers=replace(hook._config.triggers, cooldowns={'context': 0}))
    assert system.process('steuer', cli_hints=False) == [
        '[KONTEXT] ' + neutral_manual_hint(MANUAL_HINTS['steuer'], SYSTEM)
    ]
    conn = sqlite3.connect(db)
    assert [r[0] for r in conn.execute('SELECT usage_count FROM context_triggers ORDER BY id').fetchall()] == [0, 1]
    conn.close()
    assert system.process('steuer', cli_hints=True) == ['[KONTEXT] Privat: bach unknown_private_command run']
    conn = sqlite3.connect(db)
    assert [r[0] for r in conn.execute('SELECT usage_count FROM context_triggers ORDER BY id').fetchall()] == [1, 1]
    conn.close()


def test_api_passes_mode_before_context_selection():
    from system import bach_api
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


def test_actual_adapter_api_does_not_consume_cooldown_for_unknown_hint(tmp_path, monkeypatch):
    from system import bach_api
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    db = _setup_adapter_db(tmp_path, [
        ('privat', 'Privat: bach unknown_private_command run', 'manual', 1, 'approved'),
        ('steuer', MANUAL_HINTS['steuer'], 'manual', 1, 'approved'),
    ])
    system = injectors.InjectorSystem(tmp_path)
    proxy = bach_api._InjectorProxy()
    proxy._system = system
    proxy.set_mode('api')
    assert proxy.process('privat') == []
    assert not system.is_on_cooldown('context')
    assert proxy.process('steuer') == ['[KONTEXT] ' + neutral_manual_hint(MANUAL_HINTS['steuer'], SYSTEM)]
    assert system.is_on_cooldown('context')
    conn = sqlite3.connect(db)
    assert [r[0] for r in conn.execute('SELECT usage_count FROM context_triggers ORDER BY id').fetchall()] == [0, 1]
    conn.close()


def _database(path):
    spec = importlib.util.spec_from_file_location(
        'manual_hint_union', SYSTEM / 'data/schema/memory_union/memory_union.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = sqlite3.connect(path)
    module.create_union_schema(conn)
    rows = [
        ('steuer', 'Privat: bach unknown_private_command run', 'manual', 1, 'approved'),
        ('steuer|beleg', MANUAL_HINTS['steuer'], 'manual', 1, 'approved'),
        ('gesperrt', MANUAL_HINTS['steuer'], 'manual', 1, 'blocked'),
        ('ausgeschaltet', MANUAL_HINTS['steuer'], 'manual', 0, 'approved'),
        ('toolprobe', MANUAL_HINTS['steuer'], 'tool', 1, 'approved'),
    ]
    conn.executemany('INSERT INTO context_triggers '
                     '(trigger_phrase,hint_text,source,is_active,status) VALUES (?,?,?,?,?)', rows)
    conn.commit()
    conn.close()


def test_external_chat_preserves_flags_rules_and_counts_only_shown(tmp_path, monkeypatch):
    pytest.importorskip('memoryhooker.triggers')
    db = tmp_path / 'memory.db'
    _database(db)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
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


MIXED_UNKNOWN = [
    'Gemischt: bach steuer status | python3 absent.py',
    'Gemischt: bach steuer status | python "absent.py"',
    'Gemischt: bach steuer status | --unknown-danger',
    'Gemischt: bach steuer status | python tools/backup_manager.py.bak',
    'Gemischt: bach steuer status | python tools/backup_manager.py/absent',
    'Gemischt: bach steuer status | python tools/backup_manager.py?absent',
]


@pytest.mark.parametrize('hint', MIXED_UNKNOWN)
def test_mixed_unknown_helper_preserves_complete_original(hint):
    assert neutral_manual_hint(hint, SYSTEM) == hint
    assert CLI_PATTERN.search(hint)


@pytest.mark.parametrize('hint', MIXED_UNKNOWN)
def test_mixed_unknown_adapter_filtered_before_usage_selection_and_cooldown(tmp_path, monkeypatch, hint):
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    db = _setup_adapter_db(tmp_path, [
        ('steuer', hint, 'manual', 1, 'approved'),
    ])
    system = injectors.InjectorSystem(tmp_path)
    assert system.process('steuer', cli_hints=False) == []
    assert not system.is_on_cooldown('context')
    conn = sqlite3.connect(db)
    assert conn.execute('SELECT usage_count FROM context_triggers WHERE id=1').fetchone()[0] == 0
    valid = MANUAL_HINTS['steuer']
    conn.execute(
        "INSERT INTO context_triggers (trigger_phrase,hint_text,source,is_active,status) VALUES (?,?,?,?,?)",
        ('steuer|beleg', valid, 'manual', 1, 'approved'),
    )
    conn.commit()
    conn.close()
    assert system.process('steuer', cli_hints=False) == ['[KONTEXT] ' + neutral_manual_hint(valid, SYSTEM)]
    assert system.is_on_cooldown('context')
    conn = sqlite3.connect(db)
    assert [r[0] for r in conn.execute('SELECT usage_count FROM context_triggers ORDER BY id').fetchall()] == [0, 1]
    conn.close()


@pytest.mark.parametrize('hint', MIXED_UNKNOWN)
def test_mixed_unknown_external_filtered_before_usage_selection_and_cooldown(tmp_path, monkeypatch, hint):
    db = tmp_path / 'mixed.db'
    _database(db)
    conn = sqlite3.connect(db)
    conn.execute('UPDATE context_triggers SET hint_text=? WHERE id=1', (hint,))
    conn.execute("UPDATE context_triggers SET trigger_phrase='beleg' WHERE id=2")
    conn.commit()
    conn.close()
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    hook = mhp.ExternalMemoryHook(db_path=db, config_path=tmp_path / 'missing.toml')
    assert hook._groups_supported
    hook._config = replace(hook._config, triggers=replace(
        hook._config.triggers, sources=['context'], cooldowns={'context': 60}))
    assert '[KONTEXT]' not in (hook.hook_context('steuer', 'chat', cli_hints=False) or '')
    valid = MANUAL_HINTS['steuer']
    assert '[KONTEXT] ' + neutral_manual_hint(valid, SYSTEM) in hook.hook_context('steuer beleg', 'chat', cli_hints=False)
    assert hint in hook.hook_context('steuer', 'cli', cli_hints=True)
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute('SELECT hint_text,usage_count FROM context_triggers ORDER BY id').fetchall()
    finally:
        conn.close()
    assert rows[0] == (hint, 1)  # Only the explicit CLI view counts this unchanged rule.
    assert rows[1] == (valid, 1)
