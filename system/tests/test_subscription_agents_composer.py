import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from core.app import App
from core.registry import HandlerRegistry
from hub import subscription_agents
from hub._services import blueprint_service, policy_registry_adapter
from hub._services.chat import slots_config
from hub._services.subscription_agents_composer import (
    MAX_PROMPT_CHARS,
    PREVIEW_SCHEMA,
    REQUEST_SCHEMA,
    SubscriptionAgentsComposer,
)


def _make_skill(root: Path, skill_id="task-notes", text="Prüfe den Auftrag sorgfältig.\n"):
    path = root / "arbeitsweise" / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nname: Task Notes\nversion: 1.4.2\ndescription: Geprüfte Arbeitsweise\n---\n"
        + text,
        encoding="utf-8",
    )
    return path


def _request(**changes):
    request = {
        "schema": REQUEST_SCHEMA,
        "target_client": {"client_id": "codex-cli", "host": "ASUS-GEI", "name": "Codex CLI"},
        "blueprint": {"id": 7, "version": 3},
        "selected_skill_ids": ["task-notes"],
        "user_task": "Fasse die Belege mit echten Umlauten zusammen.",
        "task_refs": [42],
        "task_selection_rule": "",
        "governance": {"scope": "BACH", "policy_query": "onboarding", "decision_query": ""},
    }
    request.update(changes)
    return request


def _saved_blueprint(**changes):
    blueprint = {
        "id": 7,
        "name": "research_helper",
        "title": "Recherchehilfe",
        "version": 3,
        "kind": "agent",
        "persona_role": "recherche",
        "persona_prompt": "Prüfe Quellen sorgfältig und benenne Unsicherheiten.",
        "skills_json": "[]",
        "contractus_json": '{"turns":12,"cooldown_seconds":20}',
        "governance_json": '{"profile":"fail_closed_standard","tool_whitelist":["read_file"]}',
        "modus": "casualis",
        "animus_type": "subscription",
    }
    blueprint.update(changes)
    return blueprint


def _blueprint_reader(blueprint=None):
    saved = dict(blueprint or _saved_blueprint())

    def read(blueprint_id, expected_version):
        return dict(saved)

    return read


def _write_blueprint_db(path: Path, blueprint=None):
    row = _saved_blueprint(**(blueprint or {}))
    conn = sqlite3.connect(path)
    try:
        conn.execute("""
            CREATE TABLE agent_blueprints (
                id INTEGER PRIMARY KEY, name TEXT, title TEXT, persona_role TEXT,
                persona_prompt TEXT, skills_json TEXT, contractus_json TEXT,
                animus_type TEXT, modus TEXT, governance_json TEXT,
                kind TEXT, version INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO agent_blueprints (
                id, name, title, persona_role, persona_prompt, skills_json,
                contractus_json, animus_type, modus, governance_json, kind, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["id"], row["name"], row["title"], row["persona_role"],
            row["persona_prompt"], row["skills_json"], row["contractus_json"],
            row["animus_type"], row["modus"], row["governance_json"],
            row["kind"], row["version"],
        ))
        conn.commit()
    finally:
        conn.close()


def _policy_observer(*, scope, consumer, query, kind):
    assert scope == "BACH"
    assert consumer == "codex-cli"
    return {
        "schema": "bach.policy-registry.v1",
        "availability": "available",
        "registry_version": "a" * 64,
        "entries": [{
            "id": f"onboarding.{kind}", "kind": kind, "scope": scope, "version": "1.2",
            "status": "active", "source_state": "ok", "source_sha256": "b" * 64,
            "title": "Dieser Titel wird nicht in die Vorschau übernommen",
            "policy_text": "Dieser Volltext wird nicht gelesen oder eingebettet.",
        }],
    }


def test_compose_uses_versioned_sources_and_task_snapshot_without_claiming(tmp_path):
    skill_path = _make_skill(tmp_path)
    observed = []

    def read_task(task_id):
        observed.append(task_id)
        return {
            "id": 42, "task_version": "c" * 64, "title": "Quellenprüfung",
            "status": "pending", "priority": "P1",
            "description": "MUST_NOT_EMBED", "claim_id": "MUST_NOT_RETURN",
        }

    composer = SubscriptionAgentsComposer(
        skill_roots=[tmp_path], task_snapshot_reader=read_task,
        blueprint_snapshot_reader=_blueprint_reader(),
        policy_observer=_policy_observer, host="ASUS-GEI",
    )
    result = composer.compose(_request())

    assert result["schema"] == PREVIEW_SCHEMA
    assert result["status"] == "ready_for_review"
    assert "Prüfe den Auftrag sorgfältig." in result["prompt"]
    assert "Fasse die Belege mit echten Umlauten zusammen." in result["prompt"]
    assert "Quellenprüfung" in result["prompt"]
    assert "MUST_NOT_EMBED" not in result["prompt"]
    assert "MUST_NOT_RETURN" not in repr(result)
    assert "Dieser Volltext" not in result["prompt"]
    assert "onboarding.policy" in result["prompt"]
    assert observed == [42]
    assert result["actions"] == {
        "agent_started": False, "task_claimed": False,
        "queue_scanned": False, "clipboard_written": False,
    }
    skill = next(item for item in result["sources"] if item["id"] == "skill:task-notes")
    assert skill["path"] == str(skill_path)
    assert skill["version"] == "1.4.2"
    assert len(skill["sha256"]) == 64
    assert skill["source_bytes"] == skill_path.stat().st_size
    assert result["prompt_bytes"] == len(result["prompt"].encode("utf-8"))
    assert result["prompt_chars"] == len(result["prompt"]) <= MAX_PROMPT_CHARS
    assert all(item.get("enforcement_verified") is False
               for item in result["sources"] if item["kind"] in {"policy", "decision"})


def test_missing_skill_and_governance_are_explicit_and_fail_closed(tmp_path):
    def unavailable(**_):
        raise policy_registry_adapter.PolicyProviderUnavailable("provider not configured")

    result = SubscriptionAgentsComposer(
        skill_roots=[tmp_path], policy_observer=unavailable,
        blueprint_snapshot_reader=_blueprint_reader(),
        task_snapshot_reader=lambda _: (_ for _ in ()).throw(AssertionError("no refs")),
    ).compose(_request(task_refs=[], selected_skill_ids=["missing-skill"]))

    assert result["status"] == "needs_sources"
    assert {item["reason"] for item in result["missing"]} == {"source_missing", "provider_unavailable"}
    assert "missing-skill" not in result["prompt"]
    assert "Fehlende Governance-Quellen nicht durch Annahmen ersetzen" in result["prompt"]
    assert all(item["state"] == "unavailable" for item in result["sources"]
               if item["kind"] in {"policy", "decision"})


def test_credential_like_user_content_is_rejected_without_echoing_value():
    secret = "never-expose-this-value-123"
    with pytest.raises(ValueError) as error:
        SubscriptionAgentsComposer(
            policy_observer=_policy_observer, blueprint_snapshot_reader=_blueprint_reader(),
            task_snapshot_reader=lambda _: {},
        ).compose(_request(user_task=f"API_KEY={secret}", task_refs=[]))
    assert secret not in str(error.value)
    assert "Credential" in str(error.value)


@pytest.mark.parametrize("version", [True, 0, -1, "3"])
def test_blueprint_version_must_be_a_positive_integer(version):
    blueprint = dict(_request()["blueprint"], version=version)
    with pytest.raises(ValueError, match="Blueprint-Version"):
        SubscriptionAgentsComposer(policy_observer=_policy_observer,
                                   blueprint_snapshot_reader=_blueprint_reader()).compose(
            _request(blueprint=blueprint, task_refs=[]))


def test_role_and_skill_limits_fail_without_truncation(tmp_path):
    blueprint = _saved_blueprint(persona_prompt="x" * 20_001)
    with pytest.raises(ValueError, match="persona_prompt"):
        SubscriptionAgentsComposer(
            skill_roots=[tmp_path], policy_observer=_policy_observer,
            blueprint_snapshot_reader=_blueprint_reader(blueprint),
        ).compose(_request(task_refs=[]))

    _make_skill(tmp_path, text="x" * 80_001)
    with pytest.raises(ValueError, match="Promptbudget"):
        SubscriptionAgentsComposer(
            skill_roots=[tmp_path], policy_observer=_policy_observer,
            blueprint_snapshot_reader=_blueprint_reader(),
        ).compose(
            _request(task_refs=[]))


def test_persisted_blueprint_reader_binds_id_and_exact_revision_read_only(tmp_path):
    db_path = tmp_path / "bach.db"
    _write_blueprint_db(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    composer = SubscriptionAgentsComposer(task_db_path=db_path, policy_observer=_policy_observer)

    result = composer.compose(_request(task_refs=[], selected_skill_ids=[]))

    assert result["blueprint"]["id"] == "7"
    assert result["blueprint"]["name"] == "research_helper"
    assert result["blueprint"]["version"] == 3
    assert len(result["blueprint"]["sha256"]) == 64
    source = next(item for item in result["sources"] if item["kind"] == "blueprint")
    assert source["snapshot_source"] == "blueprint_service._execution_blueprint"
    assert source["projection_only"] is True
    assert len(source["sha256"]) == 64
    assert result["prompt"].count("Prüfe Quellen sorgfältig") == 1
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before

    with pytest.raises(ValueError, match="Revision"):
        composer.compose(_request(blueprint={"id": 7, "version": 2}, task_refs=[]))
    with pytest.raises(ValueError, match="nicht gefunden"):
        composer.compose(_request(blueprint={"id": 99, "version": 3}, task_refs=[]))


def test_blueprint_request_cannot_supply_persona_or_other_saved_fields():
    calls = []

    def reader(blueprint_id, version):
        calls.append((blueprint_id, version))
        return _saved_blueprint()

    composer = SubscriptionAgentsComposer(
        blueprint_snapshot_reader=reader, policy_observer=_policy_observer,
    )
    with pytest.raises(ValueError, match="Nicht unterstützte Felder"):
        composer.compose(_request(blueprint={
            "id": 7, "version": 3, "persona_prompt": "Vom Client eingeschleust",
        }, task_refs=[]))
    assert calls == []


def test_blueprint_reference_requires_an_explicit_displayed_revision():
    composer = SubscriptionAgentsComposer(
        blueprint_snapshot_reader=_blueprint_reader(), policy_observer=_policy_observer,
    )
    with pytest.raises(ValueError, match="Blueprint-Version"):
        composer.compose(_request(blueprint={"id": 7}, task_refs=[]))


def test_handler_is_discoverable_and_reads_request_file_without_logging_payload(tmp_path, monkeypatch):
    hub_dir = Path(__file__).parents[1] / "hub"
    registry = HandlerRegistry()
    count = registry._load_handlers_from_file(hub_dir / "subscription_agents.py", hub_dir)
    assert count == 1
    assert "subscription_agents" in registry._handlers

    request_path = tmp_path / "preview.json"
    request_path.write_text(json.dumps(_request(task_refs=[], selected_skill_ids=[])), encoding="utf-8")
    calls = []

    class ComposerStub:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def compose(self, request):
            calls.append(("compose", request["schema"]))
            return {"schema": PREVIEW_SCHEMA, "prompt": "Vorschau"}

    monkeypatch.setattr(subscription_agents, "SubscriptionAgentsComposer", ComposerStub)
    app = App(hub_dir.parent)
    app._registry = registry
    hook_events = []
    monkeypatch.setattr(app.hooks, "emit", lambda name, payload: hook_events.append((name, payload)))
    import bach_api
    monkeypatch.setattr(bach_api, "_app", app)
    success, output = bach_api.get_app().execute(
        "subscription_agents", "compose", [str(request_path)],
    )

    assert success is True
    assert json.loads(output) == {"schema": PREVIEW_SCHEMA, "prompt": "Vorschau"}
    assert calls[-1] == ("compose", REQUEST_SCHEMA)
    assert hook_events[0][1]["args"] == [str(request_path)]
    assert "Vorschau" not in repr(hook_events)



@pytest.mark.parametrize("workspace", ["/tmp/Arbeitsfläche", r"C:\Users\Example\Projekt"])
def test_target_workspace_is_bounded_metadata_not_a_filesystem_grant(tmp_path, workspace):
    _make_skill(tmp_path)
    composer = SubscriptionAgentsComposer(
        skill_roots=[tmp_path], blueprint_snapshot_reader=_blueprint_reader(),
        policy_observer=_policy_observer, host="test-host",
    )
    target = {**_request()["target_client"], "workspace": workspace}
    result = composer.compose(_request(target_client=target, task_refs=[]))
    assert result["target_client"]["workspace"] == workspace
    assert workspace in result["prompt"]
    assert "Zugriff nicht geprüft" in result["prompt"]
    assert all(value is False for value in result["actions"].values())
    assert not any(item["path"] == workspace for item in result["sources"])
    assert not (tmp_path / "Arbeitsfläche").exists()


@pytest.mark.parametrize("workspace", [12, "x" * 1025, "line1\nline2", "tab\tpath", "\x00", "api_key=sk_" + "X" * 20])
def test_target_workspace_rejects_invalid_or_secret_like_metadata(workspace):
    with pytest.raises(ValueError):
        SubscriptionAgentsComposer._target({**_request()["target_client"], "workspace": workspace})


def test_legacy_target_without_workspace_preserves_its_shape():
    target = _request()["target_client"]
    assert SubscriptionAgentsComposer._target(target) == target



def _compose_contractus(tmp_path, contractus, *, modus="casualis",
                        animus_type="subscription", description=""):
    saved = _saved_blueprint(
        contractus_json=json.dumps(contractus), modus=modus,
        animus_type=animus_type, description=description,
    )
    composer = SubscriptionAgentsComposer(
        skill_roots=[tmp_path],
        task_snapshot_reader=lambda _task_id: (_ for _ in ()).throw(
            AssertionError("request has no task references")
        ),
        blueprint_snapshot_reader=_blueprint_reader(saved),
        policy_observer=_policy_observer,
        host="ASUS-GEI",
    )
    return composer.compose(_request(
        task_refs=[], selected_skill_ids=[], user_task="Prüfe die Vorlage."
    ))


@pytest.mark.parametrize(
    ("contractus", "modus", "animus_type", "expected"),
    [
        (
            {
                "turns": 15, "cooldown_seconds": 30, "task_type": "allround",
                "modus": "casualis", "wake_behavior": "idle_wake",
                "animus_type": "subscription",
            },
            "casualis", "subscription",
            ["- Aufgabentyp: allround", "- Weckverhalten: idle_wake"],
        ),
        (
            {"max_turns": 30, "cooldown_seconds": 0,
             "task_types": ["chat", "routing", "triage"]},
            "casualis", "subscription",
            ["- Aufgabentypen: chat, routing, triage"],
        ),
        (
            {"turns": 10, "cooldown": 120, "task_type": "audit",
             "modus": "impetus_temporal", "wake": "manual"},
            "impetus_temporal", "cli",
            ["- Aufgabentyp: audit", "- Weckverhalten: manual"],
        ),
        (
            {"turns": 20, "cooldown_seconds": 30},
            "casualis", "api",
            ["- Maximale Turns: 20", "- Cooldown-Sekunden: 30"],
        ),
    ],
)
def test_native_contractus_preset_and_seed_shapes_are_projected_declaratively(
    tmp_path, contractus, modus, animus_type, expected
):
    result = _compose_contractus(
        tmp_path, contractus, modus=modus, animus_type=animus_type,
    )
    assert result["schema"] == PREVIEW_SCHEMA
    assert result["status"] == "ready_for_review"
    assert "## [Contractus: deklarative Metadaten]" in result["prompt"]
    assert all(value in result["prompt"] for value in expected)
    assert "- Diese Angaben sind deklarative Metadaten" in result["prompt"]
    assert result["actions"]["agent_started"] is False
    blueprint_record = next(item for item in result["sources"] if item["kind"] == "blueprint")
    assert blueprint_record["projection_only"] is True
    assert blueprint_record["snapshot_source"] == "blueprint_service._execution_blueprint"


def test_absent_contractus_fields_keep_documented_defaults():
    normalized, modus, animus_type, metadata = blueprint_service.project_contractus({})
    assert normalized == {}
    assert modus == "casualis"
    assert animus_type == "subscription"
    assert metadata == {}


def test_contractus_task_type_and_task_types_remain_separate():
    normalized, _, _, metadata = blueprint_service.project_contractus({
        "task_type": "allround", "task_types": ["chat", "triage"],
    })
    assert normalized == {
        "task_type": "allround", "task_types": ["chat", "triage"],
    }
    assert metadata == {}


def test_equal_contractus_aliases_normalize_without_changing_meaning():
    normalized, _, _, metadata = blueprint_service.project_contractus({
        "turns": 8, "max_turns": 8, "cooldown": 10,
        "cooldown_seconds": 10, "wake": "manual", "wake_behavior": "manual",
    })
    assert normalized == {
        "turns": 8, "cooldown_seconds": 10, "wake_behavior": "manual",
    }
    assert metadata == {}


@pytest.mark.parametrize(
    ("contractus", "modus", "animus_type", "message"),
    [
        ({"turns": 8, "max_turns": 9}, "casualis", "subscription",
         "contractus_alias_conflict"),
        ({"cooldown": 5, "cooldown_seconds": 6}, "casualis", "subscription",
         "contractus_alias_conflict"),
        ({"wake": "manual", "wake_behavior": "idle_wake"}, "casualis", "subscription",
         "contractus_alias_conflict"),
        ({"modus": "usus"}, "casualis", "subscription",
         "contractus_alias_conflict"),
        ({"animus_type": "cli"}, "casualis", "subscription",
         "contractus_alias_conflict"),
        ({"unsupported_field": "value"}, "casualis", "subscription",
         "Nicht unterstützte Contractus-Felder"),
        ({"execution": {"backend": "ollama"}}, "casualis", "subscription",
         "contractus_execution_not_projected"),
        ({"turns": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"max_turns": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"turns": None, "max_turns": None}, "casualis", "subscription",
         "contractus_null_not_allowed"),
        ({"cooldown": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"cooldown_seconds": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"cooldown": None, "cooldown_seconds": None}, "casualis", "subscription",
         "contractus_null_not_allowed"),
        ({"wake": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"wake_behavior": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"wake": None, "wake_behavior": None}, "casualis", "subscription",
         "contractus_null_not_allowed"),
        ({"modus": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"animus_type": None}, "casualis", "subscription", "contractus_null_not_allowed"),
        ({"turns": True}, "casualis", "subscription",
         "Contractus-turns"),
        ({"task_types": ["chat", "chat"]}, "casualis", "subscription",
         "Contractus-Aufgabentyp-Liste"),
        ({"task_type": "unknown"}, "casualis", "subscription",
         "Contractus-Aufgabentyp"),
        ({}, "", "subscription", "Blueprint-Arbeitsmodus"),
        ({}, "casualis", "", "Blueprint-Animus-Typ"),
        ({"task_types": ["chat"] * 33}, "casualis", "subscription",
         "Contractus-Aufgabentyp-Liste"),
        ({"task_types": ["chat"], "nested": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}}},
         "casualis", "subscription", "contractus_depth_limit"),
        ({"task_type": "x" * 33_000}, "casualis", "subscription",
         "Größenlimit"),
    ],
)
def test_contractus_rejects_conflicts_unknowns_execution_and_invalid_bounds(
    tmp_path, contractus, modus, animus_type, message
):
    with pytest.raises(ValueError, match=message):
        _compose_contractus(
            tmp_path, contractus, modus=modus, animus_type=animus_type,
        )


def test_contractus_projection_hash_binds_description_without_prompting_it(tmp_path):
    left = _compose_contractus(
        tmp_path, {"turns": 12, "cooldown_seconds": 20},
        description="Description revision one",
    )
    right = _compose_contractus(
        tmp_path, {"turns": 12, "cooldown_seconds": 20},
        description="Description revision two",
    )
    assert left["blueprint"]["sha256"] != right["blueprint"]["sha256"]
    assert "Description revision one" not in left["prompt"]
    assert "Description revision two" not in right["prompt"]
    source = SubscriptionAgentsComposer._normalize_blueprint({
        "id": 7, "name": "research_helper", "title": "Recherchehilfe",
        "description": "Description revision one", "version": 3, "kind": "agent",
        "persona_role": "recherche", "persona_prompt": "Prüfe Quellen sorgfältig.",
        "skills": [], "contractus": {"max_turns": 12, "cooldown_seconds": 20},
        "governance": {}, "modus": "casualis", "animus_type": "subscription",
    })[1]
    assert source["contractus_projection_version"] == "bach.contractus-projection.v1"
    assert source["contractus"] == {"turns": 12, "cooldown_seconds": 20}



def test_contractus_projection_rejects_credential_like_metadata(tmp_path):
    with pytest.raises(ValueError, match="Credential-ähnlicher Inhalt"):
        _compose_contractus(
            tmp_path, {"turns": 8},
            description="password=NeverExposeThisValue123",
        )



def test_contractus_projector_applies_its_own_utf8_size_limit():
    with pytest.raises(ValueError, match="contractus_size_limit"):
        blueprint_service.project_contractus({"task_types": ["x" * 33_000]})



def test_all_native_contractus_presets_and_seed_rows_are_supported():
    for preset in blueprint_service.CONTRACTUS_PRESETS:
        contractus = {
            key: preset[key] for key in blueprint_service.CONTRACTUS_FIELDS
            if key in preset
        }
        normalized, modus, animus_type, metadata = blueprint_service.project_contractus(
            preset, modus=preset["modus"], animus_type=preset["animus_type"],
        )
        assert modus == preset["modus"]
        assert animus_type == preset["animus_type"]
        assert (("turns" in normalized) or ("max_turns" in contractus))
        assert "execution" not in normalized
        assert metadata == {
            "id": preset["id"], "title": preset["title"],
            "description": preset["description"],
        }

    connection = sqlite3.connect(":memory:")
    try:
        blueprint_service.ensure_blueprint_schema(connection)
        blueprint_service.seed_default_blueprints(connection)
        rows = connection.execute(
            "SELECT contractus_json, modus, animus_type FROM agent_blueprints"
        ).fetchall()
        assert rows
        for raw_contractus, modus, animus_type in rows:
            projected, normalized_modus, normalized_animus, metadata = blueprint_service.project_contractus(
                json.loads(raw_contractus), modus=modus, animus_type=animus_type,
            )
            assert normalized_modus == modus
            assert normalized_animus == animus_type
            assert "execution" not in projected
            assert metadata == {}
    finally:
        connection.close()



def test_full_preset_metadata_is_bound_but_not_added_to_prompt(tmp_path):
    preset = dict(blueprint_service.CONTRACTUS_PRESETS[0])
    result = _compose_contractus(
        tmp_path, preset, modus=preset["modus"], animus_type=preset["animus_type"],
    )
    assert preset["title"] not in result["prompt"]
    assert preset["description"] not in result["prompt"]
    normalized, source, _ = SubscriptionAgentsComposer._normalize_blueprint({
        "id": 7, "name": "research_helper", "title": "Recherchehilfe",
        "version": 3, "kind": "agent", "persona_role": "recherche",
        "persona_prompt": "Prüfe Quellen sorgfältig.", "skills": [],
        "contractus": preset, "governance": {}, "modus": preset["modus"],
        "animus_type": preset["animus_type"],
    })
    assert source["contractus_preset"] == {
        "id": preset["id"], "title": preset["title"],
        "description": preset["description"],
    }
    assert normalized["contractus"]["task_type"] == preset["task_type"]



def test_contractus_preset_metadata_rejects_control_characters():
    for description in ("contains" + chr(0) + "nul", "line1" + chr(10) + "line2"):
        with pytest.raises(ValueError, match="Contractus-Preset-description"):
            blueprint_service.project_contractus({"description": description})


def test_shared_start_prompt_preserves_legacy_contractus_and_materialization(tmp_path, monkeypatch):
    slots_path = tmp_path / "slots.json"
    slots_config.initialize_slots_config(str(slots_path))
    monkeypatch.setattr(slots_config, "DEFAULT_SLOTS_FILE", str(slots_path))
    conn = sqlite3.connect(tmp_path / "blueprints.db")
    conn.row_factory = sqlite3.Row
    try:
        blueprint_service.ensure_blueprint_schema(conn)
        execution = {"backend": "ollama", "model": "test-local", "mode": "safe"}
        contractus = {
            "turns": 8, "cooldown": 7, "execution": execution,
            "legacy_seed": {"schedule_hint": "manual"},
        }
        saved = blueprint_service.save_blueprint(conn, {
            "name": "legacy_contractus", "title": "Altvertrag",
            "persona_role": "recherche", "persona_prompt": "Prüfe Quellen sorgfältig.",
            "kind": "agent", "skills": [], "modus": "usus", "animus_type": "cli",
            "contractus": contractus,
            "governance": {"tool_whitelist": ["read_files"]},
        })
        assert "Max. 8 Turns, 7s Cooldown" in saved["start_prompt"]
        assert "Animus-Typ: cli" in saved["start_prompt"]
        assert "Contractus: deklarative Metadaten" not in saved["start_prompt"]

        stored = blueprint_service._execution_blueprint(conn, saved["id"], saved["version"])
        assert json.loads(stored["contractus_json"]) == contractus
        changes = blueprint_service.blueprint_slot_changes(stored, execution)
        assert changes["max_tool_rounds"] == 8
        assert changes["worker_type"] == "continuous"

        materialized = blueprint_service.materialize_blueprint(
            conn, saved["id"], expected_version=saved["version"], execution=execution,
            configuration_version=slots_config.core_system_agents_snapshot()["configuration_version"],
            slots_path=str(slots_path),
        )
        slot = slots_config.get_system_slot(materialized["slot_id"], str(slots_path))
        assert materialized["worker_started"] is False
        assert slot["max_tool_rounds"] == 8
        assert json.loads(conn.execute(
            "SELECT contractus_json FROM agent_blueprints WHERE id = ?", (saved["id"],)
        ).fetchone()[0]) == contractus
    finally:
        conn.close()


def test_composer_uses_nested_modus_animus_without_injected_defaults(tmp_path):
    saved = _saved_blueprint(
        contractus_json=json.dumps({"turns": 7, "modus": "usus", "animus_type": "cli"}),
        modus=None, animus_type=None,
    )
    composer = SubscriptionAgentsComposer(
        skill_roots=[tmp_path], blueprint_snapshot_reader=_blueprint_reader(saved),
        policy_observer=_policy_observer, host="ASUS-GEI",
    )

    result = composer.compose(_request(task_refs=[], selected_skill_ids=[]))

    assert result["status"] == "ready_for_review"
    assert "Arbeitsmodus: usus" in result["prompt"]
    assert "Animus-Typ: cli" in result["prompt"]
    assert "- Maximale Turns: 7" in result["prompt"]
    assert "- Diese Angaben sind deklarative Metadaten" in result["prompt"]
