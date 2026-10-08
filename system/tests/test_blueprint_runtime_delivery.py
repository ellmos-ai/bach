"""Blueprint persistence and controller contracts; all state is isolated."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hub._services import blueprint_service as service
from hub._services.chat import slots_config as slots
from hub._services.chat.bach_tools import BachToolProvider
from gui.api import worker_status_adapter as adapter


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = str(tmp_path / 'slots.json')
    slots.initialize_slots_config(path)
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
    save(state, expected_version=1)
    with pytest.raises(RuntimeError, match='instance_not_current'):
        service.start_blueprint_worker(state, bp['id'], expected_version=2, dispatcher=dispatcher)
    assert dispatcher.call_count == 1


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


@pytest.mark.parametrize('wrong', ['worker', 'request', 'service', 'generation', 'physical'], ids=['worker','request','service','generation','physical'])
def test_dispatcher_rejects_uncorrelated_or_invalid_controller_receipts(monkeypatch, wrong):
    worker_id = 'system-blueprint-17'; version='a'*64; request='b'*32; instance='c'*32
    receipt={'schema':'bach.worker-execution.v1','worker_id':worker_id,'start_request_id':request,
        'service_instance':instance,'generation':'d'*32,'state':'running','terminal':False,'worker_thread_started':True}
    key={'worker':'worker_id','request':'start_request_id','service':'service_instance','generation':'generation','physical':'worker_thread_started'}[wrong]
    receipt[key]='wrong'
    responses=iter([{'configuration_version':version,'service_instance':instance,
        'agents':[{'id':worker_id,'enabled':True,'execution_kind':'worker'}]}, {'available':True},
        {'ok':True}, {'ok':True,'execution':receipt}])
    call=Mock(side_effect=lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(adapter, '_request_control_api', call)
    with pytest.raises(adapter.WorkerStatusUnavailable):
        adapter.dispatch_blueprint_worker(worker_id,version,device_token='test-device',start_request_id=request)
    body=call.call_args_list[2].kwargs['body']
    assert body['configuration_version']==version and body['expected_service_instance']==instance


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
