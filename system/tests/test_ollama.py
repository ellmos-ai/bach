# SPDX-License-Identifier: MIT
"""Tests fuer hub/ollama.py — OllamaHandler (Standalone, kein Server/Ollama noetig)."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.ollama import OllamaHandler


@pytest.fixture
def ollama_env(tmp_path):
    """Erstellt OllamaHandler mit tmp_path, _client bleibt None (lazy)."""
    h = OllamaHandler(tmp_path)
    return h


@pytest.fixture
def mock_client():
    """Mock fuer OllamaClient mit typischen Methoden."""
    client = MagicMock()
    client.base_url = "http://localhost:11434"
    client.get_status.return_value = {"online": True, "version": "0.5.1", "error": None}
    client.list_models.return_value = [
        SimpleNamespace(name="llama3.2", size_gb=4.1),
        SimpleNamespace(name="qwen3", size_gb=2.0),
    ]
    client.generate.return_value = SimpleNamespace(
        success=True,
        text="Antwort vom Modell",
        duration_seconds=1.5,
        total_tokens=42,
        prompt_tokens=10,
        completion_tokens=32,
        error=None,
    )
    client.embed.return_value = (True, [0.1, 0.2, 0.3, 0.4, 0.5])
    return client


# ── Properties ──────────────────────────────────────────────

class TestProperties:
    def test_profile_name(self, ollama_env):
        assert ollama_env.profile_name == "ollama"

    def test_target_file(self, ollama_env):
        h = ollama_env
        assert h.target_file == h.base_path / "data" / "ollama_config.json"

    def test_default_model(self, ollama_env):
        assert ollama_env.DEFAULT_MODEL == "llama3.2"

    def test_get_operations_keys(self, ollama_env):
        ops = ollama_env.get_operations()
        expected = {"status", "ask", "models", "embed"}
        assert set(ops.keys()) == expected


# ── Client Lazy Loading ─────────────────────────────────────

class TestClientLazy:
    def test_client_is_none_initially(self, ollama_env):
        assert ollama_env._client is None

    def test_client_property_raises_without_ollama_client(self, ollama_env):
        """Wenn OllamaClient is None (import fehlgeschlagen), soll ImportError kommen."""
        with patch("hub.ollama.OllamaClient", None):
            ollama_env._client = None
            with pytest.raises(ImportError, match="nicht verfuegbar"):
                _ = ollama_env.client


# ── Handle: status ───────────────────────────────────────────

class TestHandleStatus:
    def test_status_online(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("status", [])
        assert ok is True
        assert "ONLINE" in text
        assert "0.5.1" in text

    def test_status_offline(self, ollama_env, mock_client):
        mock_client.get_status.return_value = {"online": False, "version": None, "error": "Connection refused"}
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("status", [])
        assert ok is True
        assert "OFFLINE" in text

    def test_status_import_error(self, ollama_env):
        """Wenn client-Property ImportError wirft, wird das sauber abgefangen."""
        with patch.object(type(ollama_env), "client", new_callable=PropertyMock, side_effect=ImportError("OllamaClient nicht verfuegbar")):
            ok, text = ollama_env.handle("status", [])
        assert ok is True
        assert "nicht verfuegbar" in text

    def test_status_exception(self, ollama_env, mock_client):
        mock_client.get_status.side_effect = ConnectionError("timeout")
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("status", [])
        assert ok is True
        assert "NICHT ERREICHBAR" in text

    def test_unknown_operation_falls_to_status(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("nonexistent", [])
        assert ok is True
        assert "OLLAMA" in text

    def test_empty_operation_falls_to_status(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("", [])
        assert ok is True
        assert "OLLAMA" in text


# ── Handle: models ───────────────────────────────────────────

class TestHandleModels:
    def test_models_listed(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("models", [])
        assert ok is True
        assert "llama3.2" in text
        assert "qwen3" in text
        assert "4.1 GB" in text

    def test_models_empty(self, ollama_env, mock_client):
        mock_client.list_models.return_value = []
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("models", [])
        assert ok is True
        assert "Keine Modelle" in text

    def test_models_import_error(self, ollama_env):
        with patch.object(type(ollama_env), "client", new_callable=PropertyMock, side_effect=ImportError("OllamaClient nicht verfuegbar")):
            ok, text = ollama_env.handle("models", [])
        assert ok is True
        assert "nicht verfuegbar" in text

    def test_models_exception(self, ollama_env, mock_client):
        mock_client.list_models.side_effect = Exception("Netzwerkfehler")
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("models", [])
        assert ok is True
        assert "Fehler" in text


# ── Handle: ask ──────────────────────────────────────────────

class TestHandleAsk:
    def test_ask_basic(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("ask", ["Was ist Python?"])
        assert ok is True
        assert "Antwort vom Modell" in text

    def test_ask_with_model(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("ask", ["Hallo", "--model=qwen3"])
        assert ok is True
        mock_client.generate.assert_called_once_with("Hallo", model="qwen3")

    def test_ask_no_prompt(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("ask", [])
        assert ok is False
        assert "Kein Prompt" in text

    def test_ask_only_flags_no_prompt(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("ask", ["--model=qwen3"])
        assert ok is False
        assert "Kein Prompt" in text

    def test_ask_dry_run(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("ask", ["Test"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text
        mock_client.generate.assert_not_called()

    def test_ask_failed_response(self, ollama_env, mock_client):
        mock_client.generate.return_value = SimpleNamespace(
            success=False,
            text="",
            error="Model not found",
            duration_seconds=0,
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0,
        )
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("ask", ["Hallo"])
        assert ok is True
        assert "Model not found" in text

    def test_ask_import_error(self, ollama_env):
        with patch.object(type(ollama_env), "client", new_callable=PropertyMock, side_effect=ImportError("OllamaClient nicht verfuegbar")):
            ok, text = ollama_env.handle("ask", ["Hallo"])
        assert ok is True
        assert "nicht verfuegbar" in text


# ── Handle: embed ────────────────────────────────────────────

class TestHandleEmbed:
    def test_embed_basic(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("embed", ["Test-Text"])
        assert ok is True
        assert "Dimensionen: 5" in text

    def test_embed_no_text(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("embed", [])
        assert ok is False
        assert "Kein Text" in text

    def test_embed_dry_run(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("embed", ["Embedding"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text

    def test_embed_failure(self, ollama_env, mock_client):
        mock_client.embed.return_value = (False, None)
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("embed", ["Test"])
        assert ok is True
        assert "Fehler" in text

    def test_embed_import_error(self, ollama_env):
        with patch.object(type(ollama_env), "client", new_callable=PropertyMock, side_effect=ImportError("OllamaClient nicht verfuegbar")):
            ok, text = ollama_env.handle("embed", ["Hallo"])
        assert ok is True
        assert "nicht verfuegbar" in text

    def test_embed_only_flags_no_text(self, ollama_env, mock_client):
        ollama_env._client = mock_client
        ok, text = ollama_env.handle("embed", ["--model=xyz"])
        assert ok is False
        assert "Kein Text" in text
