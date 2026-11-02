from __future__ import annotations

from system.hub._services.chat.chat_tray import BACHTray


def test_bach_tray_exposes_buddha_talk_radio_slot():
    tray = BACHTray(remote=True)
    tray.state["connected"] = True
    tray.slots = {
        "buddha_chat": {"model": "qwen3.8:27b-mlx", "backend": "ollama"},
        "buddha_always_on": {"model": "qwen3.8:27b-mlx", "backend": "ollama", "enabled": True},
        "buddha_connector": {"model": "qwen3.8:27b-mlx", "backend": "ollama"},
    }
    menu = tray._build_menu()
    labels = [str(item.text) for item in menu.items if getattr(item, "text", None)]
    assert any("📻 Buddha Talk" in lbl for lbl in labels), f"Missing Buddha Talk slot in {labels}"
    assert any("🎙️ ELLMOS Talk" in lbl for lbl in labels)


def test_talk_config_and_summon_endpoints(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from gui import server

    monkeypatch.setattr(server, "_TALK_CONFIG_FILE", tmp_path / "talk_config.json")
    server._TALK_SESSION_SINGLETON = None

    client = TestClient(server.app)
    r_get = client.get("/api/talk/config")
    assert r_get.status_code == 200
    data = r_get.json()
    assert data["schema"] == "ellmos.talk.config.v1"
    assert "tauri" in data["supported_runtimes"]
    assert data["required_models"]["fast_relay_default"] == "smollm2:360m"

    r_post = client.post(
        "/api/talk/config",
        json={
            "persona": "claude",
            "primary_model": "claude-sonnet-4-6",
            "fast_relay_model": "gemma4-e2b",
            "operating_mode": "ptt",
            "summon_policy": "knock",
            "input_device_id": "usb-mic-1",
            "output_device_id": "speakers-2",
            "camera_device_id": "cam-front",
            "client_runtime": "tauri",
        },
    )
    assert r_post.status_code == 200
    cfg = r_post.json()["config"]
    assert cfg["persona"] == "claude"
    assert cfg["primary_model"] == "claude-sonnet-4-6"
    assert cfg["fast_relay_model"] == "gemma4-e2b"
    assert cfg["input_device_id"] == "usb-mic-1"
    assert cfg["output_device_id"] == "speakers-2"
    assert cfg["camera_device_id"] == "cam-front"
    assert cfg["client_runtime"] == "tauri"

    r_sum = client.post(
        "/api/talk/summon",
        json={"caller": "claude", "message": "Test-Funkspruch bereit."},
    )
    assert r_sum.status_code == 200
    assert r_sum.json()["accepted"] is True

    r_ack = client.post("/api/talk/summon/ack", json={"start_listening": True})
    assert r_ack.status_code == 200
    assert r_ack.json()["visual_state"]["pending_summon"] is None

