"""Isolated checks for verified profile chats without provider or production DB access."""

import asyncio
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from gui import server
from hub._services.chat import agent_profile_context as profiles
from hub._services.chat.chat_runtime import ChatRuntime, ComputeLocked, FailedAnswer
from hub._services.chat.session_store import ChatSessionStoreError, SQLiteChatSessionStore


class FakeBackend:
    manages_own_tools = True

    def __init__(self):
        self.calls = []

    def get_default_model(self):
        return "fixture-model"

    def get_context_limit(self):
        return 32768

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return {"content": "Fixture-Antwort"}


class ProfileChatBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "fixture.db"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE bach_agents (id INTEGER PRIMARY KEY, name TEXT, version TEXT, "
                     "is_active INTEGER, priority INTEGER, display_name TEXT, dashboard TEXT)")
        conn.execute("INSERT INTO bach_agents VALUES "
                     "(1, 'persoenlicher-assistent', '1.2.0', 1, 1, 'Persönlicher Assistent', NULL)")
        conn.execute("INSERT INTO bach_agents VALUES "
                     "(2, 'unverified', '1.0.0', 1, 1, 'Unverified', NULL)")
        conn.execute("CREATE TABLE bach_experts "
                     "(id INTEGER PRIMARY KEY, name TEXT, agent_id INTEGER, is_active INTEGER)")
        conn.execute("CREATE TABLE session_snapshots (id INTEGER PRIMARY KEY, session_id TEXT, "
                     "snapshot_type TEXT, name TEXT, snapshot_data TEXT, created_at TEXT)")
        conn.commit()
        conn.close()
        db_patch = patch.object(profiles, "BACH_DB", self.db)
        db_patch.start()
        self.addCleanup(db_patch.stop)

    def test_mock_provider_and_budget_stop(self):
        binding = profiles.resolve_profile(1)
        backend = FakeBackend()
        runtime = ChatRuntime(backend, session_store=SQLiteChatSessionStore(self.db))
        runtime.max_tool_rounds = 0
        chat_id = "agent:1:" + "a" * 32
        answer = asyncio.run(runtime.process("Hallo", chat_id, agent_context=binding))
        self.assertEqual(answer, "Fixture-Antwort")
        self.assertEqual(len(backend.calls), 1)
        self.assertIn("AUSGEWÄHLTES AGENTENPROFIL", backend.calls[0][0][0]["content"])
        state = runtime.session_store.load_state(chat_id)
        self.assertEqual(state["binding"]["agent_id"], 1)
        self.assertEqual(len(state["messages"]), 2)

        missing = asyncio.run(runtime.process("Hallo", "agent:1:" + "c" * 32))
        self.assertIsInstance(missing, FailedAnswer)
        self.assertEqual(len(backend.calls), 1)
        runtime.compute_gate = lambda _backend: True
        with self.assertRaises(ComputeLocked):
            asyncio.run(runtime.process("Hallo", "agent:1:" + "b" * 32,
                                        agent_context=binding))
        self.assertEqual(len(backend.calls), 1)

    def test_profile_binding_cannot_absorb_global_transcript(self):
        store = SQLiteChatSessionStore(self.db)
        chat_id = "agent:1:" + "d" * 32
        store.save(chat_id, [{"role": "user", "content": "Alter Verlauf"}])
        binding, _text = profiles.resolve_profile(1)
        with self.assertRaises(ChatSessionStoreError):
            store.save(chat_id, [], binding=binding)

    def test_profile_requires_exact_name_and_hash(self):
        with self.assertRaises(profiles.ProfileUnavailable):
            profiles.resolve_profile(2)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE bach_agents SET version = '1.0.0' WHERE id = 1")
        conn.commit()
        conn.close()
        with self.assertRaises(profiles.ProfileUnavailable):
            profiles.resolve_profile(1)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE bach_agents SET version = '1.2.0' WHERE id = 1")
        conn.commit()
        conn.close()
        altered = dict(profiles._PROFILES)
        slug, version, _hash = altered["persoenlicher-assistent"]
        altered["persoenlicher-assistent"] = (slug, version, "0" * 64)
        with patch.object(profiles, "_PROFILES", altered):
            with self.assertRaises(profiles.ProfileUnavailable):
                profiles.resolve_profile(1)

    def test_gui_marks_only_verified_profiles(self):
        def connection():
            conn = sqlite3.connect(self.db)
            conn.row_factory = sqlite3.Row
            return conn

        with patch.object(server, "get_bach_db", connection), patch.object(
            server, "validate_token", lambda token: {"id": 1} if token == "profile-fixture" else None
        ):
            response = TestClient(server.app, headers={"Authorization": "Bearer profile-fixture"}).get("/api/agents")
        self.assertEqual(response.status_code, 200)
        agents = {agent["id"]: agent for agent in response.json()["agents"]}
        self.assertIs(agents[1]["profile_chat_ready"], True)
        self.assertIs(agents[2]["profile_chat_ready"], False)

    def test_runtime_status_requires_device_and_owned_pid(self):
        from hub.agent_launcher import AgentLauncherHandler
        from hub import agent_process_provider

        base = Path(self.temp.name) / "system"
        skill_dir = base / "agents" / "persoenlicher-assistent"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("fixture", encoding="utf-8")
        pid_dir = base / "data" / "agent_pids"
        pid_dir.mkdir(parents=True)

        def connection():
            conn = sqlite3.connect(self.db)
            conn.row_factory = sqlite3.Row
            return conn

        with patch.object(server, "BACH_DIR", base), patch.object(server, "get_bach_db", connection), patch.object(
            server, "has_active_devices", lambda: False
        ), patch.object(server, "validate_token", lambda token: {"id": 1} if token == "fixture" else None):
            client = TestClient(server.app)
            self.assertEqual(client.get("/api/agents/runtime").status_code, 401)
            headers = {"Authorization": "Bearer fixture"}
            response = client.get("/api/agents/runtime", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["agents"], [
                {"agent_id": 1, "process_state": "not_started", "running": False}
            ])
            (pid_dir / "persoenlicher-assistent.pid").write_text(
                '{"name":"persoenlicher-assistent","pid":321,"process_create_time":1.0}',
                encoding="utf-8")
            with patch.object(agent_process_provider, "inspect_process_identity", return_value=("owned", object())), patch.object(
                AgentLauncherHandler, "_is_agent_running", side_effect=AssertionError("externe Registry darf nicht starten")
            ), patch.dict("os.environ", {"BACH_USE_EXTERNAL_AGENT_REGISTRY": "0"}):
                response = client.get("/api/agents/runtime", headers=headers)
            self.assertEqual(response.json()["agents"][0]["process_state"], "running")
            with patch.object(agent_process_provider, "inspect_process_identity", return_value=("owned", object())), patch.object(
                AgentLauncherHandler, "_is_agent_running", side_effect=AssertionError("externe Registry darf nicht starten")
            ), patch.dict("os.environ", {"BACH_USE_EXTERNAL_AGENT_REGISTRY": "1"}):
                response = client.get("/api/agents/runtime", headers=headers)
            self.assertEqual(response.json()["agents"][0]["process_state"], "unavailable")
            self.assertEqual(response.json()["agents"][0]["reason"], "external_registry_not_probed")

    def test_profile_snapshot_requires_id_and_control_token(self):
        from hub._services.chat import telegram_chat as control

        runtime = ChatRuntime(FakeBackend(), session_store=SQLiteChatSessionStore(self.db))
        chat_id = "agent:1:" + "e" * 32
        binding, _text = profiles.resolve_profile(1)
        runtime.session_store.save(chat_id, [{"role": "user", "content": "Privat"}], binding=binding)
        runtime.session_store.save("gui-web", [{"role": "user", "content": "Global privat"}])
        snapshot = next(s for s in runtime.session_store.list_snapshots() if s["agent_id"] == 1)
        server = control.QuietHTTPServer(("127.0.0.1", 0), control.ControlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        with patch.object(control, "runtime", runtime), patch.object(
            control, "is_control_api_authorized", lambda headers: headers.get("Authorization") == "Bearer fixture"
        ):
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/api/session?id={snapshot['id']}"
                self.assertEqual(httpx.get(url, timeout=3).status_code, 401)
                self.assertEqual(httpx.get(url + "&agent_id=1", timeout=3).status_code, 401)
                headers = {"Authorization": "Bearer fixture"}
                self.assertEqual(httpx.get(url, headers=headers, timeout=3).status_code, 409)
                response = httpx.get(url + "&agent_id=1", headers=headers, timeout=3)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["session"]["messages"][0]["content"], "Privat")
                history_url = f"http://127.0.0.1:{server.server_port}/api/history?chat_id={chat_id}"
                sessions_url = f"http://127.0.0.1:{server.server_port}/api/sessions"
                for private_url in (history_url, sessions_url):
                    self.assertEqual(httpx.get(private_url, timeout=3).status_code, 401)
                    self.assertEqual(httpx.get(private_url,
                                                headers={"Authorization": "Bearer fake"}, timeout=3).status_code, 401)
                self.assertEqual(httpx.get(history_url, headers=headers, timeout=3).status_code, 409)
                self.assertEqual(httpx.get(sessions_url, headers=headers, timeout=3).status_code, 200)
                global_url = f"http://127.0.0.1:{server.server_port}/api/history?chat_id=gui-web"
                self.assertEqual(httpx.get(global_url, timeout=3).status_code, 401)
                self.assertEqual(httpx.get(global_url,
                                            headers={"Authorization": "Bearer fake"}, timeout=3).status_code, 401)
                self.assertEqual(httpx.get(global_url, headers=headers, timeout=3).json()["messages"][0]["content"],
                                 "Global privat")
                self.assertEqual(httpx.get(history_url + "&agent_id=2", headers=headers, timeout=3).status_code, 409)
                self.assertEqual(httpx.get(history_url + "&agent_id=1", headers=headers, timeout=3).json()["messages"][0]["content"], "Privat")
                clear_url = f"http://127.0.0.1:{server.server_port}/api/clear"
                self.assertEqual(httpx.post(clear_url, json={"chat_id": chat_id},
                                            headers=headers, timeout=3).status_code, 409)
                self.assertEqual(httpx.post(clear_url, json={"chat_id": chat_id, "agent_id": 2},
                                            headers=headers, timeout=3).status_code, 409)
                self.assertEqual(runtime.session_store.load_state(chat_id)["messages"][0]["content"], "Privat")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
