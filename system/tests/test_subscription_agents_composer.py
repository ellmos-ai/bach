import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from core.app import App
from core.registry import HandlerRegistry
from hub._services.subscription_agents_composer import (
    MAX_PROMPT_CHARS,
    PREVIEW_SCHEMA,
    REQUEST_SCHEMA,
    SubscriptionAgentsComposer,
)
from hub._services import policy_registry_adapter
from hub import subscription_agents


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

