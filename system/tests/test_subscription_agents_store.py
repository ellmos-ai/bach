"""Basis-Tests fuer hub/_services/subscription_agents_store.py.

Deckt Schema-Idempotenz sowie create/list/get/delete und die
Prompt-Kopplung ab. Laeuft auf einer temporaeren SQLite-Datei.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services import subscription_agents_store as store  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "agents.db"
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    store.ensure_subscription_agent_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_schema_is_idempotent(conn):
    store.ensure_subscription_agent_schema(conn)
    store.ensure_subscription_agent_schema(conn)
    agent_cols = {
        row[1] for row in conn.execute(f"PRAGMA table_info({store.AGENT_TABLE})")
    }
    prompt_cols = {
        row[1] for row in conn.execute(f"PRAGMA table_info({store.PROMPT_TABLE})")
    }
    assert {"id", "name", "prompt_id", "status", "expires_at"} <= agent_cols
    assert {"prompt_id", "agent_id", "prompt_text"} <= prompt_cols


def test_create_list_get_delete_agent(conn):
    created = store.create_subscription_agent(
        conn,
        {
            "name": "test-agent",
            "title": "Testtitel",
            "description": "Beschreibung",
            "prompt_text": "Du bist ein Testagent.",
        },
    )
    assert created["id"] > 0
    assert created["name"] == "test-agent"
    assert created["status"] == store.STATUS_IDLE
    assert created["prompt_text"] == "Du bist ein Testagent."
    assert created["prompt_id"]

    listed = store.list_subscription_agents(conn)
    assert [agent["id"] for agent in listed] == [created["id"]]

    fetched = store.get_subscription_agent(conn, created["id"])
    assert fetched is not None
    assert fetched["name"] == "test-agent"

    assert store.delete_subscription_agent(conn, created["id"]) is True
    assert store.get_subscription_agent(conn, created["id"]) is None
    assert store.list_subscription_agents(conn) == []
    assert store.list_subscription_prompts(conn) == []


def test_duplicate_name_rejected(conn):
    store.create_subscription_agent(conn, {"name": "dupe"})
    with pytest.raises(ValueError):
        store.create_subscription_agent(conn, {"name": "dupe"})


def test_prompt_delete_cascades_to_agent(conn):
    created = store.create_subscription_agent(
        conn, {"name": "kopplung", "prompt_text": "Text"}
    )
    prompt_id = created["prompt_id"]
    assert store.get_subscription_prompt(conn, prompt_id) is not None
    store.delete_subscription_prompt(conn, prompt_id)
    assert store.get_subscription_prompt(conn, prompt_id) is None
    agent = store.get_subscription_agent(conn, created["id"])
    assert agent is not None
    assert agent.get("prompt_id") in ("", None)


def test_cloud_model_blocked_on_create(conn):
    for blocked in ("gpt:cloud", "ollama-cloud:llama3", "openrouter:meta-llama", "internal-foo"):
        with pytest.raises(ValueError) as info:
            store.create_subscription_agent(
                conn, {"name": "sperre-" + blocked.replace(":", "-").replace(".", "-"), "model": blocked}
            )
        assert store.MODEL_BLOCKED_MESSAGE in str(info.value)
    assert store.list_subscription_agents(conn) == []


def test_local_model_allowed_on_create(conn):
    created = store.create_subscription_agent(
        conn, {"name": "lokal", "model": "gpt-oss:20b"}
    )
    assert created["model"] == "gpt-oss:20b"
    fetched = store.get_subscription_agent(conn, created["id"])
    assert fetched is not None
    assert fetched["model"] == "gpt-oss:20b"


def test_cloud_model_blocked_on_update(conn):
    created = store.create_subscription_agent(
        conn, {"name": "update-sperre", "model": "gpt-oss:20b"}
    )
    with pytest.raises(ValueError) as info:
        store.update_subscription_agent(conn, created["id"], {"model": "x:cloud"})
    assert store.MODEL_BLOCKED_MESSAGE in str(info.value)
    with pytest.raises(ValueError):
        store.update_subscription_agent(conn, created["id"], {"model": "openai:gpt-4o"})
    unchanged = store.get_subscription_agent(conn, created["id"])
    assert unchanged is not None
    assert unchanged["model"] == "gpt-oss:20b"


# --------------------------------------------------------------------------
# Blueprint-Vererbung, Kaskaden, Lifecycle
# --------------------------------------------------------------------------
def _create_blueprint_table(conn, **overrides):
    conn.execute(
        "CREATE TABLE agent_blueprints ("
        "id INTEGER PRIMARY KEY, name TEXT, title TEXT, description TEXT, "
        "avatar TEXT, skills_json TEXT, persona_prompt TEXT, start_prompt TEXT)"
    )
    row = {
        "name": "Vorlagenname",
        "title": "Titelvorlage",
        "description": "Beschreibung aus Vorlage",
        "avatar": "V",
        "skills_json": '["skill.alpha"]',
        "persona_prompt": "Du bist die Vorlage.",
        "start_prompt": "Starte jetzt.",
    }
    row.update(overrides)
    conn.execute(
        "INSERT INTO agent_blueprints (id, name, title, description, avatar, "
        "skills_json, persona_prompt, start_prompt) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["name"],
            row["title"],
            row["description"],
            row["avatar"],
            row["skills_json"],
            row["persona_prompt"],
            row["start_prompt"],
        ),
    )
    conn.commit()


def test_blueprint_defaults_are_inherited(conn):
    _create_blueprint_table(conn)
    agent = store.create_subscription_agent(
        conn, {"name": "vorlagen-kind", "blueprint_id": 1}
    )
    assert agent["title"] == "Titelvorlage"
    assert agent["description"] == "Beschreibung aus Vorlage"
    assert agent["avatar"] == "V"
    assert "skill.alpha" in str(agent.get("skills"))
    prompts = store.list_subscription_prompts(conn)
    assert len(prompts) == 1
    assert prompts[0]["prompt_text"] == "Du bist die Vorlage."


def test_unknown_blueprint_is_rejected(conn):
    _create_blueprint_table(conn)
    with pytest.raises(ValueError):
        store.create_subscription_agent(
            conn, {"name": "ohne-vorlage", "blueprint_id": 99}
        )
    assert store.list_subscription_agents(conn) == []


def test_delete_agent_removes_linked_prompt(conn):
    agent = store.create_subscription_agent(conn, {"name": "loesch-agent"})
    prompt = store.create_subscription_prompt(
        conn, {"agent_id": agent["id"], "prompt_text": "Gekoppelt"}
    )
    assert store.delete_subscription_agent(conn, agent["id"]) is True
    assert store.get_subscription_agent(conn, agent["id"]) is None
    assert store.list_subscription_prompts(conn) == []
    assert store.get_subscription_prompt(conn, prompt["id"]) is None


def test_delete_prompt_removes_linked_agent(conn):
    agent = store.create_subscription_agent(conn, {"name": "loesch-prompt"})
    prompt = store.create_subscription_prompt(
        conn, {"agent_id": agent["id"], "prompt_text": "Gekoppelt"}
    )
    assert store.delete_subscription_prompt(conn, prompt["id"]) is True
    assert store.get_subscription_prompt(conn, prompt["id"]) is None
    assert store.get_subscription_agent(conn, agent["id"]) is None


def test_prompt_double_link_is_rejected(conn):
    agent = store.create_subscription_agent(conn, {"name": "doppel-prompt"})
    store.create_subscription_prompt(
        conn, {"agent_id": agent["id"], "prompt_text": "Erster"}
    )
    with pytest.raises(ValueError) as info:
        store.create_subscription_prompt(
            conn, {"agent_id": agent["id"], "prompt_text": "Zweiter"}
        )
    assert "bereits einen Prompt" in str(info.value)
    assert len(store.list_subscription_prompts(conn)) == 1


def test_heartbeat_marks_running_and_sets_expiry(conn):
    agent = store.create_subscription_agent(conn, {"name": "herzschlag"})
    started = store.record_subscription_agent_heartbeat(
        conn, agent["id"], ttl_seconds=120
    )
    assert started["status"] == store.STATUS_RUNNING
    assert started["expires_at"] is not None
    assert started["last_heartbeat_at"] is not None


def test_stop_clears_expiry(conn):
    agent = store.create_subscription_agent(conn, {"name": "stoppen"})
    store.record_subscription_agent_heartbeat(conn, agent["id"], ttl_seconds=120)
    stopped = store.stop_subscription_agent(conn, agent["id"])
    assert stopped["status"] == store.STATUS_STOPPED
    assert stopped["expires_at"] is None
    assert stopped["last_heartbeat_at"] is not None


def test_duplicate_uses_copy_suffix(conn):
    source = store.create_subscription_agent(
        conn, {"name": "quelle", "model": "gpt-oss:20b"}
    )
    copied = store.duplicate_subscription_agent(conn, source["id"])
    assert copied["id"] != source["id"]
    assert copied["name"]
    assert copied["name"] != source["name"]
    assert "copy" in copied["name"]
    assert copied["model"] == "gpt-oss:20b"
    assert len(store.list_subscription_agents(conn)) == 2


def test_clean_name_rejects_spaces():
    with pytest.raises(ValueError):
        store._clean_name("bad name")


# ---------------------------------------------------------------------------
# Transport-Tests: FastAPI-Router /api/agent-studio/subscription-agents
#
# Eigener Client, eigene tmp-DB und gepatchte Geraete-Autorisierung, damit die
# Tests ohne echte devices-Tabelle und ohne laufenden Server arbeiten.
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from gui import server  # noqa: E402
from gui.api import subscription_agents_transport as transport  # noqa: E402

API_PREFIX = "/api/agent-studio/subscription-agents"
# Original sichern, bevor Fixtures das Modulglobal umbiegen.
ORIGINAL_AUTHORIZE = transport._authorize_active_device


@pytest.fixture()
def transport_client(tmp_path, monkeypatch):
    """TestClient mit gepatchtem Modulglobal-DB-Pfad und erlaubter Auth."""
    db_path = tmp_path / "transport.db"

    async def _allow(request):  # Signatur wie _authorize_active_device(request)
        return None

    monkeypatch.setattr(transport, "BACH_DB", db_path)
    monkeypatch.setattr(transport, "_SCHEMA_READY", False)
    monkeypatch.setattr(transport, "_authorize_active_device", _allow)
    monkeypatch.setattr(
        server,
        "validate_token",
        lambda token: {"id": 1} if token == "gui-fixture" else None,
    )
    client = TestClient(
        server.app,
        raise_server_exceptions=False,
        headers={"Authorization": "Bearer gui-fixture"},
    )
    try:
        yield client
    finally:
        client.close()


def test_transport_list_returns_agents_and_count(transport_client):
    response = transport_client.get(f"{API_PREFIX}/list")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"agents", "count"}
    assert payload["agents"] == []
    assert payload["count"] == 0


def test_transport_prompts_returns_prompts_and_count(transport_client):
    response = transport_client.get(f"{API_PREFIX}/prompts")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"prompts", "count"}
    assert payload["prompts"] == []
    assert payload["count"] == 0


def test_transport_prompt_post_rejects_non_json(transport_client):
    response = transport_client.post(
        f"{API_PREFIX}/prompts",
        content=b"{}",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "json_required"


def test_transport_requires_device_auth(transport_client, monkeypatch):
    """Ohne Auth-Stub muss die echte Pruefung mit 401 abweisen."""
    monkeypatch.setattr(transport, "_authorize_active_device", ORIGINAL_AUTHORIZE)
    anonymous = TestClient(server.app, raise_server_exceptions=False)
    try:
        response = anonymous.get(f"{API_PREFIX}/list")
    finally:
        anonymous.close()
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "device_auth_required"


def test_transport_prompt_crud_roundtrip(transport_client):
    """POST legt einen Prompt an, PUT aendert ihn, DELETE entfernt ihn."""
    created = transport_client.post(
        f"{API_PREFIX}/prompts", json={"prompt_text": "Hallo"}
    )
    assert created.status_code == 200
    prompt = created.json()["prompt"]
    prompt_id = prompt["prompt_id"]
    assert prompt_id
    assert prompt["prompt_text"] == "Hallo"

    updated = transport_client.put(
        f"{API_PREFIX}/prompts/{prompt_id}", json={"prompt_text": "Neu"}
    )
    assert updated.status_code == 200
    assert updated.json()["prompt"]["prompt_text"] == "Neu"

    removed = transport_client.delete(f"{API_PREFIX}/prompts/{prompt_id}")
    assert removed.status_code == 200
    body = removed.json()
    assert body["deleted"] is True
    assert body["prompt_id"] == prompt_id

    again = transport_client.delete(f"{API_PREFIX}/prompts/{prompt_id}")
    assert again.status_code == 404
    assert again.json()["detail"]["code"] == "prompt_not_found"


def test_transport_prompt_put_unknown_returns_prompt_rejected(transport_client):
    """Unbekannte Prompt-ID beim PUT wird als 422 prompt_rejected gemeldet."""
    response = transport_client.put(
        f"{API_PREFIX}/prompts/gibt-es-nicht", json={"prompt_text": "Neu"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "prompt_rejected"


def test_transport_create_rejects_cloud_model(transport_client):
    """Cloud-Modelle sind in der Ablage gesperrt und enden als 422 agent_rejected."""
    response = transport_client.post(
        f"{API_PREFIX}/create",
        json={"name": "x", "model": "gpt-oss:20b:cloud"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_rejected"


def test_transport_duplicate_rejects_non_string_name(transport_client):
    """Der Name muss ein String sein, sonst 422 agent_rejected."""
    response = transport_client.post(
        f"{API_PREFIX}/1/duplicate", json={"name": 123}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_rejected"


def test_transport_duplicate_unknown_agent_returns_agent_rejected(transport_client):
    """Unbekannte Agent-ID im Duplicate-Pfad ist ein ValueError, also 422 (nicht 404)."""
    response = transport_client.post(
        f"{API_PREFIX}/999999/duplicate", json={"name": "Kopie"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_rejected"


def test_transport_heartbeat_rejects_non_int_ttl(transport_client):
    """ttl_seconds muss eine ganze Zahl sein."""
    response = transport_client.post(
        f"{API_PREFIX}/999999/heartbeat", json={"ttl_seconds": "abc"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_rejected"


def test_transport_stop_unknown_agent_returns_not_found(transport_client):
    """Stop auf unbekannte Agent-ID meldet 404 agent_not_found."""
    response = transport_client.post(f"{API_PREFIX}/999999/stop", json={})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent_not_found"


def test_transport_agent_delete_unknown_returns_not_found(transport_client):
    """DELETE auf unbekannte Agent-ID meldet 404 agent_not_found."""
    response = transport_client.delete(f"{API_PREFIX}/999999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent_not_found"
