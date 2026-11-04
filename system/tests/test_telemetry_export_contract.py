"""Native core/consumer/export parity on explicitly prepared synthetic stores."""
import importlib.util
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from core import telemetry as core
from hub import bach_paths
from hub._services import ocean_stack_bridge as bridge
from hub.telemetry import TelemetryHandler


@pytest.fixture
def exported(monkeypatch):
    path = Path(__file__).resolve().parents[2] / '.MODULES/telemetry/src/telemetry.py'
    spec = importlib.util.spec_from_file_location('synthetic_telemetry_export', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv('BACH_DB', raising=False)
    monkeypatch.delenv('BACH_TELEMETRY_DISABLED', raising=False)
    monkeypatch.delenv('TELEMETRY_DISABLED', raising=False)
    return module


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'synthetic telemetry ü.db'
    assert core.ensure_schema(path)
    return path


def rows(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            'SELECT counter, labels, day, value FROM telemetry_counters '
            'ORDER BY counter, labels, day'
        ).fetchall()


def test_real_bridge_consumer_reports_and_resets_core_store(database, tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, '_MODULE_CACHE', {})
    monkeypatch.setattr(bach_paths, 'BACH_DB', database)
    monkeypatch.delenv('BACH_DB', raising=False)
    expected = Path(__file__).resolve().parents[2] / '.MODULES/telemetry/src/telemetry.py'
    assert Path(bridge.load_telemetry_module().__file__).resolve() == expected.resolve()
    assert core.increment('tool_calls', tool='real-consumer', db_path=database)
    handler = TelemetryHandler(tmp_path)
    success, text = handler.handle('report', ['7'])
    assert success and 'real-consumer' in text
    assert handler.handle('status', [])[0] is True
    assert handler.handle('reset', ['--confirm'])[0] is True
    assert rows(database) == []


@pytest.mark.parametrize('environment', ['absent', 'different'])
def test_consumer_reads_and_resets_core_canonical_store(
    exported, database, tmp_path, monkeypatch, environment
):
    monkeypatch.setattr(bach_paths, 'BACH_DB', database)
    decoy = tmp_path / 'decoy.db'
    assert core.ensure_schema(decoy)
    assert core.increment('tool_calls', tool='canonical-tool', db_path=database)
    assert core.increment('model_calls', model='decoy-model', db_path=decoy)
    if environment == 'different':
        monkeypatch.setenv('BACH_DB', str(decoy))
    memory_key = ('model_calls', '{"model": "memory-only", "outcome": "ok"}',
                  datetime.now(timezone.utc).date().isoformat())
    exported._MEM_COUNTERS[memory_key] = 99
    monkeypatch.setattr(bridge, 'load_telemetry_module', lambda: exported)
    handler = TelemetryHandler(tmp_path)
    success, text = handler.handle('report', ['7'])
    assert success and 'canonical-tool' in text
    assert 'decoy-model' not in text and 'memory-only' not in text
    success, text = handler.handle('status', [])
    assert success and 'Ereignisse gesamt: 1' in text
    before, other = rows(database), rows(decoy)
    assert handler.handle('reset', [])[0] is False
    assert rows(database) == before
    assert handler.handle('reset', ['--confirm'], dry_run=True)[0] is True
    assert rows(database) == before
    assert handler.handle('reset', ['--confirm'])[0] is True
    assert rows(database) == [] and rows(decoy) == other
    assert exported._MEM_COUNTERS[memory_key] == 99


@pytest.mark.parametrize('labels', [dict(tool='task'), {}, dict(tool='BAD LABEL'),
                                    dict(tool=123), dict(tool='TASK', ignored='private')])
@pytest.mark.parametrize('outcome', ['ok', 'WEIRD OUTCOME'])
def test_export_uses_existing_core_label_key(exported, database, labels, outcome):
    assert core.increment('tool_calls', outcome=outcome, db_path=database, **labels)
    assert exported.increment('tool_calls', outcome=outcome, db_path=database, **labels)
    saved = rows(database)
    assert len(saved) == 1 and saved[0][3] == 2
    assert 'private' not in saved[0][1]


@pytest.mark.parametrize('storage', ['sqlite', 'memory'])
@pytest.mark.parametrize('days', [2, 0, -1])
def test_days_cutoff_and_daily_aggregation(exported, database, storage, days):
    effective = 7 if days <= 0 else days
    today = datetime.now(timezone.utc).date()
    label = '{"outcome": "ok", "tool": "sum-tool"}'
    old_label = '{"outcome": "ok", "tool": "too-old"}'
    entries = [(label, today.isoformat(), 3),
               (label, (today - timedelta(days=effective)).isoformat(), 4),
               (old_label, (today - timedelta(days=effective + 1)).isoformat(), 100)]
    if storage == 'sqlite':
        with closing(sqlite3.connect(database)) as connection:
            connection.executemany(
                'INSERT INTO telemetry_counters(counter,labels,day,value) VALUES (?,?,?,?)',
                [('tool_calls', labels, day, value) for labels, day, value in entries],
            )
            connection.commit()
        arguments = {'db_path': database}
        native_success, native_text = core.report(days=days, db_path=database)
        assert native_success and '-> 7' in ' '.join(native_text.split())
        assert 'too-old' not in native_text
    else:
        exported._MEM_COUNTERS.update({
            ('tool_calls', labels, day): value for labels, day, value in entries
        })
        arguments = {}
    success, text = exported.report(days=days, **arguments)
    assert success and text.count('sum-tool') == 1 and ': 7' in text
    assert 'too-old' not in text
    assert f'Letzte {effective} Tage' in text


@pytest.mark.parametrize('storage', ['sqlite', 'memory'])
def test_series_cap_matches_core_and_preserves_existing_series(
    exported, database, storage, monkeypatch
):
    arguments = {'db_path': database} if storage == 'sqlite' else {}
    for index in range(core.MAX_SERIES_PER_DAY):
        assert exported.increment('tool_calls', tool=f'tool-{index:03d}', **arguments)
    assert exported.increment('tool_calls', tool='tool-000', **arguments)
    for label in ('overflow-a', 'overflow-b'):
        assert exported.increment('tool_calls', tool=label, **arguments)
    assert exported.increment('tool_calls', tool='overflow-error', outcome='error', **arguments)
    assert exported.increment('model_calls', model='fresh-counter', **arguments)
    if storage == 'sqlite':
        saved = {(counter, labels, day): value for counter, labels, day, value in rows(database)}
        assert core.increment('tool_calls', tool='core-overflow', db_path=database)
        assert len(rows(database)) == len(saved)
    else:
        saved = exported._MEM_COUNTERS
    tool_rows = {labels: value for (counter, labels, _), value in saved.items()
                 if counter == 'tool_calls'}
    assert len(tool_rows) == core.MAX_SERIES_PER_DAY + 2
    assert tool_rows['{"outcome": "ok", "tool": "tool-000"}'] == 2
    assert tool_rows['{"overflow":"true","outcome":"ok"}'] == 2
    assert tool_rows['{"overflow":"true","outcome":"error"}'] == 1
    assert any(c == 'model_calls' for c, _, _ in saved)

    class Tomorrow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=1)

    monkeypatch.setattr(exported, 'datetime', Tomorrow)
    assert exported.increment('tool_calls', tool='fresh-day', **arguments)
    current = rows(database) if storage == 'sqlite' else [
        (counter, labels, day, value)
        for (counter, labels, day), value in exported._MEM_COUNTERS.items()
    ]
    assert any('fresh-day' in label for _, label, _, _ in current)


@pytest.mark.parametrize('storage', ['sqlite', 'memory'])
def test_optout_stops_recording_but_keeps_report_and_confirmed_reset(
    exported, database, monkeypatch, storage
):
    arguments = {'db_path': database} if storage == 'sqlite' else {}
    assert exported.increment('tool_calls', tool='existing', **arguments)
    monkeypatch.setenv('BACH_TELEMETRY_DISABLED', '1')
    assert exported.increment('tool_calls', tool='disabled', **arguments) is False
    success, text = exported.report(**arguments)
    assert success and 'existing' in text and 'disabled' not in text
    assert 'NEIN' in exported.status(**arguments)[1]
    assert exported.reset(**arguments)[0] is False
    assert exported.reset(confirm=True, **arguments)[0] is True
    assert 'existing' not in exported.report(**arguments)[1]


@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'schema'])
def test_selected_unavailable_store_never_falls_back_to_memory(exported, tmp_path, kind):
    assert exported.increment('tool_calls', tool='memory-only')
    before = dict(exported._MEM_COUNTERS)
    path = tmp_path / kind / 'absent.db'
    if kind != 'missing':
        path.parent.mkdir()
        path.write_bytes(b'not sqlite' if kind == 'corrupt' else b'')
    original = path.read_bytes() if path.exists() else None
    for result in (exported.report(db_path=path), exported.status(db_path=path),
                   exported.reset(confirm=True, db_path=path)):
        assert result[0] is False and 'nicht verfügbar' in result[1]
        assert 'memory-only' not in result[1]
    if kind != 'schema':
        assert exported.increment('tool_calls', tool='must-not-fallback', db_path=path) is False
    assert exported._MEM_COUNTERS == before
    assert (path.read_bytes() if path.exists() else None) == original
    if kind == 'missing':
        assert not path.parent.exists()


def test_unknown_counter_is_ignored_in_both_storage_modes(exported, database):
    assert exported.increment('unknown-counter', tool='synthetic') is False
    assert exported.increment('unknown-counter', db_path=database) is False
    assert rows(database) == [] and exported._MEM_COUNTERS == {}


def test_report_and_status_are_read_only_and_release_file_handles(exported, database):
    assert core.increment('tool_calls', tool='existing', db_path=database)
    before = database.read_bytes()
    assert exported.report(db_path=database)[0] is True
    assert exported.status(db_path=database)[0] is True
    assert database.read_bytes() == before
    renamed = database.with_name('renamed synthetic.db')
    database.replace(renamed)
    assert renamed.read_bytes() == before
