"""Blueprint persistence and controller contracts; all state is isolated."""
import json
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


# Task #2010: isolated optional colors, inheritance and explicit CAS overrides.
@pytest.fixture
def color_state(tmp_path):
    conn = sqlite3.connect(tmp_path / "blueprints.db")
    conn.row_factory = sqlite3.Row
    service.ensure_blueprint_schema(conn)
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    yield conn, path
    conn.close()


def save_color_blueprint(conn, **changes):
    return service.save_blueprint(conn, {
        "name": "color-agent", "title": "Farbprüfung", "persona_role": "recherche",
        "persona_prompt": "Prüfe den Auftrag.", "skills": [],
        "contractus": {"turns": 3}, "governance": {"tool_whitelist": ["read_file"]},
        **changes,
    })


def public_slot(path, sid):
    return next(agent for agent in slots.core_system_agents_snapshot(path)["agents"]
                if agent["id"] == sid)


def materialize_color_blueprint(conn, path, bp, **changes):
    return service.materialize_blueprint(conn, bp["id"], expected_version=bp["version"],
        execution={"backend": "ollama", "model": "fixture-only", "mode": "safe"},
        configuration_version=slots.core_system_agents_snapshot(path)["configuration_version"],
        slots_path=path, **changes)


def test_agent_color_blueprint_color_reload_omission_clear_and_stale_revision(color_state):
    conn, _ = color_state
    first = save_color_blueprint(conn, color="#A1B2C3")
    assert first["color"] == "#a1b2c3"
    assert service._execution_blueprint(conn, first["id"], 1)["color"] == "#a1b2c3"
    second = save_color_blueprint(conn, expected_version=1)
    assert second["color"] == "#a1b2c3"
    before = [tuple(row) for row in conn.execute("SELECT * FROM agent_blueprints")]
    with pytest.raises(RuntimeError, match="version_conflict"):
        save_color_blueprint(conn, expected_version=1, color="#112233")
    assert [tuple(row) for row in conn.execute("SELECT * FROM agent_blueprints")] == before
    assert save_color_blueprint(conn, expected_version=second["version"], color=None)["color"] is None


@pytest.mark.parametrize("value", [True, 12, [], {}, "red", "#abc", "#12345678", " #123456", "#123456;display:none"])
def test_agent_color_invalid_color_preserves_blueprint_and_slot_bytes(color_state, value):
    conn, path = color_state
    save_color_blueprint(conn, color="#123456")
    before = [tuple(row) for row in conn.execute("SELECT * FROM agent_blueprints")]
    raw = Path(path).read_bytes()
    with pytest.raises(ValueError, match="Farbe"):
        save_color_blueprint(conn, expected_version=1, color=value)
    with pytest.raises(ValueError, match="Farbe"):
        slots._validated_core_edits({"color_override": value})
    assert [tuple(row) for row in conn.execute("SELECT * FROM agent_blueprints")] == before
    assert Path(path).read_bytes() == raw


def _exercise_color_override_lifecycle(color_state):
    conn, path = color_state
    first = save_color_blueprint(conn, color="#AABBCC")
    configured = materialize_color_blueprint(conn, path, first)
    sid = configured["slot_id"]
    assert configured["worker_started"] is False
    inherited = public_slot(path, sid)
    assert {key: inherited[key] for key in ("color", "color_source", "color_override", "blueprint_color")} == {
        "color": "#aabbcc", "color_source": "blueprint", "color_override": None, "blueprint_color": "#aabbcc"}
    version = configured["configuration_version"]
    override = slots.change_core_system_agent(sid, version, {"color_override": "#1122AA"}, path=path)
    assert public_slot(path, sid)["color"] == "#1122aa"
    assert public_slot(path, sid)["color_source"] == "instance"
    raw = Path(path).read_bytes()
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_core_system_agent(sid, version, {"color_override": None}, path=path)
    assert Path(path).read_bytes() == raw
    second = save_color_blueprint(conn, expected_version=1, color="#DDCCBB")
    materialize_color_blueprint(conn, path, second, terminal_verified=True)
    current = public_slot(path, sid)
    assert current["blueprint_color"] == "#ddccbb" and current["color"] == "#1122aa"
    current_version = slots.core_system_agents_snapshot(path)["configuration_version"]
    slots.change_core_system_agent(sid, current_version, {"color_override": None}, path=path)
    assert public_slot(path, sid)["color"] == "#ddccbb"
    assert public_slot(path, sid)["color_source"] == "blueprint"
    assert override["configuration_version"] != version


def test_agent_color_legacy_snapshot_is_read_only_and_color_fields_are_not_capabilities(color_state):
    conn, path = color_state
    from pathlib import Path
    raw = Path(path).read_bytes()
    snapshot = slots.core_system_agents_snapshot(path)
    assert all(agent["color"] is None and agent["color_source"] == "default" for agent in snapshot["agents"])
    assert Path(path).read_bytes() == raw
    assert "blueprint_color" not in slots.CORE_EDITABLE_FIELDS
    for field in ("blueprint_color", "color", "color_source"):
        with pytest.raises(ValueError):
            slots._validated_core_edits({field: "#123456"})
        with pytest.raises(ValueError):
            slots.update_slot("buddha_chat", {field: "#123456"}, path)
    assert Path(path).read_bytes() == raw
    blueprint = save_color_blueprint(conn)
    assert service._execution_blueprint(conn, blueprint["id"], 1)["color"] is None


def test_agent_color_rematerialization_stale_cas_does_not_change_color(color_state):
    conn, path = color_state
    bp = save_color_blueprint(conn, color="#123456")
    materialize_color_blueprint(conn, path, bp)
    from pathlib import Path
    raw = Path(path).read_bytes()
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        service.materialize_blueprint(conn, bp["id"], expected_version=bp["version"],
            execution={"backend": "ollama", "model": "fixture-only"},
            configuration_version="stale", terminal_verified=True, slots_path=path)
    assert Path(path).read_bytes() == raw


def test_agent_color_existing_override_survives_blueprint_refresh_and_legacy_schema(color_state):
    conn, path = color_state
    conn.execute("ALTER TABLE agent_blueprints DROP COLUMN color")
    conn.commit()
    service.ensure_blueprint_schema(conn)
    first = save_color_blueprint(conn, color="#112233")
    configured = materialize_color_blueprint(conn, path, first)
    sid = configured["slot_id"]
    # A preexisting explicit instance choice is fixture state, not an edit-path bypass.
    config = json.loads(Path(path).read_text())
    config["slots"][sid]["color_override"] = "#445566"
    Path(path).write_text(json.dumps(config))
    second = save_color_blueprint(conn, expected_version=1, color="#778899")
    materialize_color_blueprint(conn, path, second, terminal_verified=True)
    actual = public_slot(path, sid)
    assert actual["blueprint_color"] == "#778899"
    assert actual["color_override"] == actual["color"] == "#445566"
    assert actual["color_source"] == "instance"
    assert slots.agent_color_fields({"blueprint_color": "#778899", "color_override": None}) == {
        "blueprint_color": "#778899", "color_override": None,
        "color": "#778899", "color_source": "blueprint"}
    snapshot = slots.core_system_agents_snapshot(path)
    assert snapshot["color_contract"] == "bach.agent-colors.v1"
    slot = next(item for item in snapshot["agents"] if item["id"] == sid)
    assert slot["color"] == "#445566"


def test_agent_color_existing_readonly_api_projects_contract_and_instance(color_state, monkeypatch):
    import asyncio
    from gui.api import unified_api, core_system_agents
    conn, path = color_state
    saved = save_color_blueprint(conn, color="#ABCDEF")
    materialize_color_blueprint(conn, path, saved)
    # The production reader needs Row objects; this local read source never contacts Control.
    def reader():
        view = sqlite3.connect(conn.execute("PRAGMA database_list").fetchone()[2])
        view.row_factory = sqlite3.Row
        view.execute("PRAGMA query_only=ON")
        return view
    monkeypatch.setattr(unified_api, "_get_agent_studio_ro_conn", reader)
    monkeypatch.setattr(core_system_agents, "_snapshot", lambda: slots.core_system_agents_snapshot(path))
    answer = asyncio.run(unified_api.list_agent_blueprints())
    assert answer["color_contract"] == "bach.agent-colors.v1"
    item = next(item for item in answer["blueprints"] if item["id"] == saved["id"])
    assert item["color"] == "#abcdef"
    assert item["instance"]["color"] == "#abcdef"
    assert item["instance"]["color_source"] == "blueprint"


@pytest.mark.parametrize("locked", [False, True])
def test_agent_color_isolated_color_cas_with_exact_temporary_guard_evidence(color_state, monkeypatch, locked):
    """Functional CAS only; synthetic scope evidence is not native lock acceptance."""
    from hub._services import skill_source_service
    _, path = color_state
    target = Path(path).resolve()
    calls = []
    def guard(candidate):
        resolved = Path(candidate).resolve()
        if resolved != target:
            raise PermissionError("Außerhalb der isolierten Fixture")
        calls.append({"target": resolved, "locked": locked})
        if locked:
            raise PermissionError("Synthetischer Sperrbeleg")
    monkeypatch.setattr(skill_source_service, "check_write_locks", guard)
    if locked:
        before = Path(path).read_bytes()
        version = slots.core_system_agents_snapshot(path)["configuration_version"]
        with pytest.raises(PermissionError, match="Sperrbeleg"):
            slots.change_core_system_agent("buddha_chat", version, {"color_override": "#112233"}, path=path)
        assert Path(path).read_bytes() == before
    else:
        _exercise_color_override_lifecycle(color_state)
        version = slots.core_system_agents_snapshot(path)["configuration_version"]
        sid = "system-blueprint-1"
        slots.change_core_system_agent(sid, version, {"color_override": "#456789"}, path=path)
        version = slots.core_system_agents_snapshot(path)["configuration_version"]
        slots.change_core_system_agent(sid, version, reset=True, path=path)
        assert public_slot(path, sid)["color_override"] is None
        assert public_slot(path, sid)["color"] == "#ddccbb"
    assert calls and all(call["target"] == target for call in calls)
    with pytest.raises(PermissionError, match="Außerhalb"):
        guard(target.parent / "foreign.json")
