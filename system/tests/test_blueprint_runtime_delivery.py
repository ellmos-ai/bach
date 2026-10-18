"""Blueprint persistence and controller contracts; all state is isolated."""
import json
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hub._services import blueprint_service as service
from hub._services.chat import slots_config as slots
from hub._services.chat.bach_tools import BachToolProvider
from gui.api import worker_status_adapter as adapter


@pytest.fixture
def state(tmp_path, monkeypatch):
    from hub._services import skill_source_service

    path = str(tmp_path / 'slots.json')
    slots.initialize_slots_config(path)
    resolved_target = Path(path).resolve()

    def fixture_lock_guard(target):
        if Path(target).resolve() != resolved_target:
            raise PermissionError("test lock guard denies paths outside the isolated config")

    # Only the fixture's exact temporary config is treated as known-unlocked.
    monkeypatch.setattr(skill_source_service, 'check_write_locks', fixture_lock_guard)
    monkeypatch.setattr(slots, 'DEFAULT_SLOTS_FILE', path)
    conn = sqlite3.connect(tmp_path / 'blueprints.db')
    conn.row_factory = sqlite3.Row
    service.ensure_blueprint_schema(conn)
    yield conn
    conn.close()


def save(conn, **changes):
    return service.save_blueprint(conn, {'name': 'my_expert', 'title': 'Meine Expertin',
        'persona_role': 'recherche', 'persona_prompt': 'Prüfe den zugewiesenen Auftrag.',
        'kind': 'agent', 'skills': [], 'contractus': {'turns': 8},
        'governance': {'tool_whitelist': ['read_file', 'task_manage']}, **changes})


def materialize(conn, bp, **changes):
    return service.materialize_blueprint(conn, bp['id'], expected_version=bp['version'],
        execution={'backend': 'ollama', 'model': 'test-local', 'mode': 'safe'},
        configuration_version=slots.core_system_agents_snapshot()['configuration_version'], **changes)


def test_update_requires_the_displayed_revision(state):
    first = save(state)
    for revision in (None, 0, 99, True):
        with pytest.raises(RuntimeError, match='blueprint_version_conflict'):
            save(state, expected_version=revision, persona_prompt='Veralteter Editor')
    second = save(state, expected_version=first['version'], persona_prompt='Aktuelle Revision')
    assert second['version'] == 2
    assert state.execute('SELECT persona_prompt FROM agent_blueprints').fetchone()[0] == 'Aktuelle Revision'


def test_blueprint_revisions_are_immutable_and_bound_to_the_displayed_version(state):
    first = save(state)
    old_ref = first['definition_ref']
    old_json = state.execute(
        'SELECT definition_json FROM agent_blueprint_revisions WHERE blueprint_id=? AND version=1',
        (first['id'],)).fetchone()[0]
    second = save(state, expected_version=first['version'], persona_prompt='Neue Fassung')
    assert second['definition_ref']['version'] == 2
    assert second['definition_ref']['sha256'] != old_ref['sha256']
    assert json.loads(old_json)['persona_prompt'] == 'Prüfe den zugewiesenen Auftrag.'
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        state.execute('UPDATE agent_blueprint_revisions SET definition_json=? WHERE blueprint_id=? AND version=1',
                      ('{}', first['id']))


@pytest.mark.parametrize('execution', [None, {'avatar': 'https://bad'}, {'symbol': 'unknown'}])
def test_blueprint_rejects_invalid_images_before_opening_write_transaction(state, execution):
    with pytest.raises(ValueError):
        save(state, contractus={'execution': execution})
    assert not state.in_transaction
    assert state.execute('SELECT count(*) FROM agent_blueprints').fetchone()[0] == 0


def test_blueprint_portrait_and_symbol_are_copied_into_the_real_slot(state):
    execution = {'backend': 'ollama', 'model': 'test-local', 'avatar': 'preset:researcher', 'symbol': 'topics_research'}
    bp = save(state, contractus={'turns': 8, 'execution': execution})
    saved = service._execution_blueprint(state, bp['id'], bp['version'])
    copied = service.blueprint_slot_changes(saved, execution)
    assert copied['avatar'] == 'preset:researcher' and copied['symbol'] == 'topics_research'
    result = service.materialize_blueprint(state, bp['id'], expected_version=bp['version'], execution=execution,
        configuration_version=slots.core_system_agents_snapshot()['configuration_version'])
    assert slots.get_system_slot(result['slot_id'])['avatar'] == 'preset:researcher'


def test_seeding_populated_db_is_additive_and_does_not_overwrite(state):
    bp = save(state)
    service.seed_default_blueprints(state)
    count = state.execute('SELECT count(*) FROM agent_blueprints').fetchone()[0]
    assert state.execute("SELECT id FROM agent_blueprints WHERE name='my_expert'").fetchone()[0] == bp['id']
    names = {row[0] for row in state.execute('SELECT name FROM agent_blueprints')}
    assert {'template_boss_routing', 'template_entwickler', 'template_recherche', 'template_personal_assistant'} <= names
    service.seed_default_blueprints(state)
    assert state.execute('SELECT count(*) FROM agent_blueprints').fetchone()[0] == count


def test_template_flag_cannot_bypass_template_protection(state):
    service.seed_default_blueprints(state)
    with pytest.raises(PermissionError):
        save(state, name='buddha', is_template=1)


def test_materialization_creates_a_real_slot_without_process_or_presence(state):
    bp = save(state)
    result = materialize(state, bp)
    slot = slots.get_system_slot(result['slot_id'])
    assert result['status'] == 'configured' and result['worker_started'] is False
    assert result['definition_ref'] == bp['definition_ref']
    assert slot['blueprint_id'] == bp['id'] and slot['blueprint_version'] == 1
    assert slot['model'] == 'test-local' and slot['require_assigned_slot'] is True
    assert slot['allowed_tools'] == ['read_file', 'task_manage']
    assert 'Prüfe den zugewiesenen Auftrag.' in slots.compose_worker_prompt(slot)
    assert state.execute('SELECT count(*) FROM partner_presence').fetchone()[0] == 0
    with pytest.raises(RuntimeError, match='terminal_state_required'):
        materialize(state, bp)
    repeated = materialize(state, bp, terminal_verified=True)
    assert repeated['slot_id'] == result['slot_id']
    assert len(slots.core_system_agents_snapshot()['agents']) == 7


def test_materialization_stale_revision_and_stale_config_do_not_create_instances(state):
    bp = save(state)
    with pytest.raises(RuntimeError, match='version_conflict'):
        service.materialize_blueprint(state, bp['id'], expected_version=99,
            execution={'backend': 'ollama', 'model': 'test-local'}, configuration_version='a'*64)
    with pytest.raises(RuntimeError, match='configuration_version_conflict'):
        service.materialize_blueprint(state, bp['id'], expected_version=1,
            execution={'backend': 'ollama', 'model': 'test-local'}, configuration_version='a'*64)
    assert len(slots.core_system_agents_snapshot()['agents']) == 6


def test_no_dispatcher_cannot_fabricate_a_running_agent(state):
    bp = save(state)
    with pytest.raises(RuntimeError, match='worker_dispatcher_required'):
        service.start_blueprint_worker(state, bp['id'])
    assert state.execute('SELECT count(*) FROM partner_presence').fetchone()[0] == 0


def test_start_returns_the_actual_dispatcher_receipt_and_stale_instances_refuse(state):
    bp = save(state)
    configured = materialize(state, bp)
    execution = {'schema': 'bach.worker-execution.v1', 'worker_id': configured['slot_id'],
        'worker_thread_started': True, 'terminal': True, 'state': 'terminal'}
    dispatcher = Mock(return_value=execution)
    result = service.start_blueprint_worker(state, bp['id'], expected_version=1,
        configuration_version=configured['configuration_version'], dispatcher=dispatcher)
    assert result['job_receipt'] == execution and result['is_running'] is False
    assert result['heartbeat_receipt'] is None
    assert result['start_cause'] == 'manual'
    assert result['definition_ref'] == bp['definition_ref']
    assert result['configuration_version'] == configured['configuration_version']
    save(state, expected_version=1)
    with pytest.raises(RuntimeError, match='instance_not_current'):
        service.start_blueprint_worker(state, bp['id'], expected_version=2, dispatcher=dispatcher)
    assert dispatcher.call_count == 1


def test_generic_worker_start_cannot_bypass_blueprint_revision_binding():
    with pytest.raises(adapter.WorkerActionRejected, match='versionierten Blueprint-Start'):
        adapter.start_worker('system-blueprint-17', device_token='test-device')
    from hub._services.chat import telegram_chat as control
    response, status = control.start_worker_execution('system-blueprint-17')
    assert status == 409
    assert response['error_code'] == 'blueprint_versioned_start_required'
    response, status = control.start_worker_execution('system-blueprint-17',
        start_request_id='a'*32, expected_service_instance='b'*32,
        expected_configuration_version='c'*64)
    assert status == 409
    assert response['error_code'] == 'blueprint_versioned_start_required'


def test_generic_control_slot_edits_cannot_toggle_a_blueprint():
    from hub._services.chat.telegram_chat import _generic_blueprint_slot_update_denial
    slot = {'id': 'system-blueprint-17', 'blueprint_id': 17, 'blueprint_version': 2}
    assert _generic_blueprint_slot_update_denial(slot, {'enabled': False})['error_code'] == 'blueprint_generic_toggle_forbidden'
    assert _generic_blueprint_slot_update_denial(slot, {'status': 'idle'})['error_code'] == 'blueprint_generic_toggle_forbidden'
    assert _generic_blueprint_slot_update_denial(slot, {'model': 'other'}) is None
    assert _generic_blueprint_slot_update_denial({'id': 'normal-worker'}, {'enabled': False}) is None


@pytest.mark.parametrize(('path', 'body'), [
    ('/api/workers/toggle', {'id': 'system-blueprint-17', 'status': 'paused'}),
    ('/api/slots', {'slot_id': 'system-blueprint-17', 'updates': {'enabled': False}}),
])
def test_generic_control_toggle_routes_reject_blueprints_before_mutation(monkeypatch, path, body):
    from hub._services.chat import telegram_chat as control
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = path
    replies = []
    monkeypatch.setattr(handler, '_allow_json_post', lambda: True)
    monkeypatch.setattr(handler, '_read_body', lambda: body)
    monkeypatch.setattr(handler, '_json', lambda payload, status=200: replies.append((payload, status)))
    monkeypatch.setattr(control, '_execution_worker_slot', lambda _slot_id: {
        'id': 'system-blueprint-17', 'blueprint_id': 17, 'blueprint_version': 2,
        'persistent_opt_in': False, 'status': 'running'})
    revoke = Mock()
    update = Mock()
    monkeypatch.setattr(control, '_request_worker_revocation', revoke)
    monkeypatch.setattr(control, 'update_slot', update)
    handler.do_POST()
    assert replies and replies[-1][1] == 409
    assert replies[-1][0]['error_code'] == 'blueprint_generic_toggle_forbidden'
    revoke.assert_not_called()
    update.assert_not_called()


@pytest.mark.parametrize('enabled', [True, False])
def test_blueprint_toggle_rejects_before_configuration_mutation(monkeypatch, enabled):
    import asyncio
    from fastapi import HTTPException
    from gui.api import core_system_agents as api
    change = Mock()
    monkeypatch.setattr(api, 'get_system_slot', lambda _slot: {'blueprint_id': 17})
    monkeypatch.setattr(api, 'change_core_system_agent', change)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.toggle_core_system_agent('system-blueprint-17', None,
            {'configuration_version': 'a' * 64, 'enabled': enabled}))
    assert error.value.status_code == 409
    change.assert_not_called()


def test_core_snapshot_shares_the_verified_run_id_and_definition_pin(state, monkeypatch):
    from gui.api import core_system_agents as core
    import gui.api.unified_api as unified
    bp = save(state)
    service.ensure_blueprint_schema(state)
    config_sha = 'd' * 64
    execution = {'schema': 'bach.worker-execution.v1', 'worker_id': f"system-blueprint-{bp['id']}",
        'start_request_id': 'a' * 32, 'generation': 'b' * 32,
        'worker_thread_started': True, 'terminal': False, 'state': 'running',
        'configuration_ref': {'sha256': config_sha}}
    monkeypatch.setattr(core, 'core_system_agents_snapshot', lambda: {'configuration_version': config_sha,
        'agents': [{'id': f"system-blueprint-{bp['id']}", 'blueprint_id': bp['id'],
            'blueprint_version': bp['version'], 'name': bp['title'], 'icon': '', 'deletable': False,
            'model': 'test-local', 'mode': 'safe', 'status': 'running'}]})
    monkeypatch.setattr(adapter, '_request_control_api', lambda *_args, **_kwargs: {
        'configuration_version': config_sha,
        'agents': [{'id': f"system-blueprint-{bp['id']}", 'execution': execution}]})
    monkeypatch.setattr(unified, '_get_agent_studio_ro_conn', lambda: state)
    monkeypatch.setattr('hub._services.worker_policy_settings.attach_active_task_leases', lambda agents: agents)
    snapshot = core._snapshot()
    agent = snapshot['agents'][0]
    assert agent['run_id'] == 'b' * 32
    assert agent['definition_ref'] == bp['definition_ref']
    assert agent['configuration_ref'] == {'sha256': config_sha}
    assert agent['actual_start_cause'] == 'manual'


def test_legacy_execution_without_configuration_pin_stays_unbound(state, monkeypatch):
    from gui.api import core_system_agents as core
    import gui.api.unified_api as unified
    bp = save(state)
    config_sha = 'd' * 64
    execution = {'schema': 'bach.worker-execution.v1', 'worker_id': f"system-blueprint-{bp['id']}",
        'start_request_id': 'a' * 32, 'generation': 'b' * 32,
        'worker_thread_started': True, 'terminal': False, 'state': 'running'}
    monkeypatch.setattr(core, 'core_system_agents_snapshot', lambda: {'configuration_version': config_sha,
        'agents': [{'id': f"system-blueprint-{bp['id']}", 'blueprint_id': bp['id'],
            'blueprint_version': bp['version'], 'name': bp['title'], 'icon': '', 'deletable': False,
            'model': 'test-local', 'mode': 'safe', 'status': 'running'}]})
    monkeypatch.setattr(adapter, '_request_control_api', lambda *_args, **_kwargs: {
        'configuration_version': config_sha,
        'agents': [{'id': f"system-blueprint-{bp['id']}", 'execution': execution}]})
    monkeypatch.setattr(unified, '_get_agent_studio_ro_conn', lambda: state)
    monkeypatch.setattr('hub._services.worker_policy_settings.attach_active_task_leases', lambda agents: agents)
    agent = core._snapshot()['agents'][0]
    assert agent['configuration_ref'] is None
    assert 'run_id' not in agent
    assert 'actual_start_cause' not in agent


def test_controller_receipt_pins_only_the_configuration_hash_admitted_by_cas():
    from hub._services.chat.telegram_chat import _admitted_configuration_ref
    version = 'e' * 64
    assert _admitted_configuration_ref(version) == {'configuration_ref': {'sha256': version}}
    for invalid in (None, '', 'x' * 64, 'A' * 64):
        assert _admitted_configuration_ref(invalid) == {}


def test_existing_database_revision_migration_backfills_immutable_definition(tmp_path):
    migration_path = Path(__file__).resolve().parents[1] / 'data' / 'schema' / 'migrations' / '054_agent_blueprint_revisions.py'
    spec = importlib.util.spec_from_file_location('test_migration_054', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    conn = sqlite3.connect(tmp_path / 'legacy.db')
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE agent_blueprints (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, title TEXT, description TEXT,
        persona_role TEXT, persona_prompt TEXT, skills_json TEXT, animus_type TEXT,
        contractus_json TEXT, modus TEXT, is_template INTEGER, is_materialized INTEGER,
        governance_json TEXT, kind TEXT, start_prompt TEXT, version INTEGER,
        created_at TEXT, updated_at TEXT
    )""")
    conn.execute("""INSERT INTO agent_blueprints VALUES
        (1, 'legacy', 'Legacy', 'Ältere Vorlage', 'research', 'Prompt', '[]', 'subscription',
         '{}', 'casualis', 1, 0, '{}', 'agent', '', 1, 'created', 'updated')""")
    conn.commit()
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_blueprint_revisions'").fetchone() is None
    migration.run_migration(conn)
    pin = service.blueprint_revision_reference(conn, 1, 1)
    assert pin and pin['version'] == 1 and len(pin['sha256']) == 64
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        conn.execute('DELETE FROM agent_blueprint_revisions WHERE blueprint_id=1 AND version=1')
    conn.close()


def test_revision_migration_conflict_rolls_back_new_schema_objects(state):
    bp = save(state)
    migration_path = Path(__file__).resolve().parents[1] / 'data' / 'schema' / 'migrations' / '054_agent_blueprint_revisions.py'
    spec = importlib.util.spec_from_file_location('test_migration_054_conflict', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    state.execute('DROP TRIGGER agent_blueprint_revisions_immutable_update')
    state.execute('DROP TRIGGER agent_blueprint_revisions_immutable_delete')
    state.execute("UPDATE agent_blueprint_revisions SET definition_sha256=?, definition_json='{}' WHERE blueprint_id=? AND version=1",
                  ('0' * 64, bp['id']))
    state.commit()
    with pytest.raises(RuntimeError, match='blueprint_revision_conflict'):
        migration.run_migration(state)
    names = {row[0] for row in state.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert 'agent_blueprint_revisions_immutable_update' not in names
    assert 'agent_blueprint_revisions_immutable_delete' not in names
    corrupted = state.execute(
        'SELECT definition_sha256, definition_json FROM agent_blueprint_revisions WHERE blueprint_id=? AND version=1',
        (bp['id'],)).fetchone()
    assert corrupted['definition_sha256'] == '0' * 64 and corrupted['definition_json'] == '{}'


def test_provider_template_import_captures_definition_revision(state):
    from hub._services import template_provider_service as provider
    fields = {
        'title': 'Imported template', 'description': 'A provider template',
        'persona_role': 'helper', 'persona_prompt': 'Help carefully.', 'skills': [],
        'animus_type': 'cli', 'contractus': {'turns': 5}, 'modus': 'casualis',
        'governance': {'tool_whitelist': ['read_file']}, 'kind': 'agent',
    }
    blueprint_id = provider._insert_template(state, 'test-provider',
        {'id': 'helper', 'version': '1.0.0', 'sha256': 'f' * 64, 'fields': fields})
    pin = service.blueprint_revision_reference(state, blueprint_id, 1)
    assert pin == {'blueprint_id': blueprint_id, 'version': 1, 'sha256': pin['sha256']}


def test_living_uses_the_materialized_slot_revision_not_newer_current_revision(state, monkeypatch):
    import asyncio
    import gui.api.unified_api as unified
    bp = save(state)
    current = save(state, expected_version=bp['version'], persona_prompt='New revision')
    config_sha = 'c' * 64
    old_slot = {
        'id': f"system-blueprint-{bp['id']}", 'blueprint_id': bp['id'], 'blueprint_version': bp['version'],
        'definition_ref': bp['definition_ref'], 'configuration_ref': {'sha256': config_sha},
        'run_id': 'b' * 32, 'actual_start_cause': 'manual', 'status': 'running',
        'runtime_verified': True, 'living': True, 'running': True, 'task_id': None,
        'execution': {'schema': 'bach.worker-execution.v1'},
    }
    monkeypatch.setattr(unified, '_get_agent_studio_ro_conn', lambda: state)
    monkeypatch.setattr('gui.api.core_system_agents._snapshot', lambda: {
        'configuration_version': 'd' * 64, 'agents': [old_slot]})
    monkeypatch.setattr('hub._services.worker_policy_settings.attach_active_task_leases', lambda agents: agents)
    result = asyncio.run(unified.get_living_agents())['living_agents'][0]
    assert current['version'] == 2
    assert result['blueprint_version'] == 1 and result['current_blueprint_version'] == 2
    assert result['definition_ref'] == bp['definition_ref']
    assert result['run_id'] == 'b' * 32 and result['actual_start_cause'] == 'manual'


def test_living_does_not_attribute_run_when_slot_revision_pin_is_missing(state, monkeypatch):
    import asyncio
    import gui.api.unified_api as unified
    bp = save(state)
    slot = {'id': f"system-blueprint-{bp['id']}", 'blueprint_id': bp['id'],
        'blueprint_version': 1, 'definition_ref': None, 'configuration_ref': {'sha256': 'c' * 64},
        'run_id': 'b' * 32, 'actual_start_cause': 'manual', 'status': 'running',
        'runtime_verified': True, 'living': True, 'running': True}
    monkeypatch.setattr(unified, '_get_agent_studio_ro_conn', lambda: state)
    monkeypatch.setattr('gui.api.core_system_agents._snapshot', lambda: {'agents': [slot]})
    monkeypatch.setattr('hub._services.worker_policy_settings.attach_active_task_leases', lambda agents: agents)
    result = asyncio.run(unified.get_living_agents())['living_agents'][0]
    assert result['run_id'] is None and result['actual_start_cause'] is None
    assert result['definition_ref'] is None


def test_provider_enforces_grants_for_schema_and_execution(state):
    provider = BachToolProvider(allowed_tools=['read_file'])
    assert [item['function']['name'] for item in provider.get_tools('full')] == ['read_file']
    assert provider.execute('write_file', {'path': 'never-created'}, 'full').startswith('BLOCKIERT:')


def test_system_worker_approval_reads_one_image_and_rejects_config_replacement(state):
    bp = save(state)
    configured = materialize(state, bp)
    slot = slots.system_worker_at_version(configured['slot_id'], configured['configuration_version'])
    assert slot['model'] == 'test-local'
    slots.change_core_system_agent(slot['id'], configured['configuration_version'], {'model': 'new-model'})
    with pytest.raises(RuntimeError, match='configuration_version_conflict'):
        slots.system_worker_at_version(slot['id'], configured['configuration_version'])


@pytest.mark.parametrize('wrong', ['worker', 'request', 'service', 'generation', 'physical', 'configuration'], ids=['worker','request','service','generation','physical','configuration'])
def test_dispatcher_rejects_uncorrelated_or_invalid_controller_receipts(monkeypatch, wrong):
    worker_id = 'system-blueprint-17'; version='a'*64; request='b'*32; instance='c'*32
    receipt={'schema':'bach.worker-execution.v1','worker_id':worker_id,'start_request_id':request,
        'service_instance':instance,'generation':'d'*32,'state':'running','terminal':False,'worker_thread_started':True,
        'configuration_ref': {'sha256':version}}
    if wrong == 'configuration':
        receipt['configuration_ref'] = {'sha256':'e'*64}
    else:
        key={'worker':'worker_id','request':'start_request_id','service':'service_instance','generation':'generation','physical':'worker_thread_started'}[wrong]
        receipt[key]='wrong'
    responses=iter([{'configuration_version':version,'service_instance':instance,
        'agents':[{'id':worker_id,'enabled':True,'execution_kind':'worker'}]}, {'available':True},
        {'ok':True}, {'ok':True,'execution':receipt}])
    call=Mock(side_effect=lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(adapter, '_request_control_api', call)
    with pytest.raises(adapter.WorkerStatusUnavailable):
        adapter.dispatch_blueprint_worker(worker_id,version,blueprint_id=17,blueprint_version=3,
            definition_sha256='f'*64,device_token='test-device',start_request_id=request)
    body=call.call_args_list[2].kwargs['body']
    assert body['configuration_version']==version and body['expected_service_instance']==instance


def test_dispatcher_returns_the_cas_bound_configuration_pin(monkeypatch):
    worker_id = 'system-blueprint-17'; version='a'*64; start_request_id='b'*32; instance='c'*32
    receipt={'schema':'bach.worker-execution.v1','worker_id':worker_id,'start_request_id':start_request_id,
        'service_instance':instance,'generation':'d'*32,'state':'running','terminal':False,
        'worker_thread_started':True,'configuration_ref':{'sha256':version}}
    responses=iter([{'configuration_version':version,'service_instance':instance,
        'agents':[{'id':worker_id,'enabled':True,'execution_kind':'worker'}]}, {'available':True},
        {'ok':True}, {'ok':True,'execution':receipt}])
    calls=[]
    def send_control_request(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)
    monkeypatch.setattr(adapter, '_request_control_api', send_control_request)
    result=adapter.dispatch_blueprint_worker(worker_id,version,blueprint_id=17,blueprint_version=3,
        definition_sha256='f'*64,device_token='test-device',start_request_id=start_request_id)
    assert result['configuration_ref'] == {'sha256': version}
    assert calls[2][0][1] == 'blueprints/start'
    assert calls[2][1]['body']['blueprint_version'] == 3
    assert calls[2][1]['body']['definition_sha256'] == 'f'*64


def test_changing_grants_revokes_an_admitted_blueprint_generation(state):
    from hub._services.chat import telegram_chat as control
    bp = save(state)
    created = materialize(state, bp)
    admitted = slots.get_system_slot(created["slot_id"])
    reader = control._execution_slot_reader(admitted)
    assert reader()["allowed_tools"] == admitted["allowed_tools"]
    snapshot = slots.core_system_agents_snapshot()
    slots.change_core_system_agent(created["slot_id"], snapshot["configuration_version"],
        {"allowed_tools": admitted["allowed_tools"] + ["edit_file"]})
    with pytest.raises(RuntimeError, match="neuer Start"):
        reader()


def test_native_tool_names_take_precedence_over_legacy_aliases(state):
    bp = save(state, governance={"tool_whitelist":["execute_command","task_manage"]})
    created = materialize(state, bp)
    assert slots.get_system_slot(created["slot_id"])["allowed_tools"] == ["execute_command","task_manage"]


@pytest.mark.parametrize('modus,worker_type', [('casualis','once'),('usus','continuous')])
def test_blueprint_work_mode_reaches_the_actual_controller(state, modus, worker_type):
    from hub._services.chat import telegram_chat as control
    bp = save(state, modus=modus)
    created = materialize(state, bp)
    assert slots.get_system_slot(created['slot_id'])['type'] == worker_type
    assert slots.system_worker_at_version(created['slot_id'], created['configuration_version'])['type'] == worker_type
    assert control._execution_worker_slot(created['slot_id'])['type'] == worker_type


@pytest.mark.parametrize('modus', ['impetus_temporal','impetus_causa'])
def test_unimplemented_trigger_modes_refuse_to_create_an_unbounded_worker(state, modus):
    bp = save(state, modus=modus)
    with pytest.raises(ValueError, match='noch nicht ausführbar'):
        materialize(state, bp)
    assert slots.get_system_slot(f"system-blueprint-{bp['id']}") == {}


def test_contract_presets_advertise_executable_modes_and_all_can_be_saved(state):
    import asyncio
    from gui.api import unified_api as api
    presets = asyncio.run(api.get_contractus_presets())['presets']
    for preset in presets:
        assert preset['title']
        assert preset['execution_supported'] is (preset['modus'] in {'casualis','usus'})
        save(state, name=preset['id'], modus=preset['modus'])


def test_blueprint_delete_serializes_slot_inspection_with_materialization(state, monkeypatch):
    import asyncio
    from gui.api import unified_api as api
    bp = save(state)
    db = state.execute('PRAGMA database_list').fetchone()[2]
    monkeypatch.setattr(api, '_get_conn', lambda: sqlite3.connect(db))
    observed = []
    def inspect(slot_id):
        competitor = sqlite3.connect(db, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                competitor.execute('BEGIN IMMEDIATE')
            observed.append(slot_id)
            return {}
        finally:
            competitor.close()
    monkeypatch.setattr(slots, 'get_system_slot', inspect)
    result = asyncio.run(api.delete_agent_blueprint(bp['id'], expected_version=bp['version']))
    assert result['success'] is True
    assert observed == [f"system-blueprint-{bp['id']}"]
    assert state.execute('SELECT count(*) FROM agent_blueprints WHERE id=?', (bp['id'],)).fetchone()[0] == 0


def test_completed_once_blueprint_releases_its_acquired_task_for_reuse():
    from hub._services.chat import telegram_chat as control
    slot = {'id':'system-blueprint-7','system':True,'blueprint_id':7,'task_id':42,'type':'once'}
    assert control._worker_once_completion_changes(slot, (42,))['task_id'] is None
    assert 'task_id' not in control._worker_once_completion_changes(slot, ())
    assert 'task_id' not in control._worker_once_completion_changes(slot, (99,))
    assert 'task_id' not in control._worker_once_completion_changes({**slot,'system':False}, (42,))
