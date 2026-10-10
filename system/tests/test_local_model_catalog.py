"""Native metadata/catalog and CLI boundaries without network or live models."""
import asyncio
import copy
import json
import sys
from pathlib import Path

import httpx
import pytest
from gui.api import model_sockets as api
from hub._services.chat import local_model_catalog as catalog
from hub._services.chat import local_provider_config as providers
from hub._services.chat import model_sockets as sockets
from hub._services.chat import slots_config as slots
from hub.model_sockets import ModelSocketsHandler


@pytest.fixture(autouse=True)
def clean_provider_environment(monkeypatch):
    for key in ("OLLAMA_URL", "OLLAMA_MODEL", "LM_STUDIO_URL", "LM_STUDIO_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_provider_uses_explicit_chat_config_and_environment_without_secrets(monkeypatch):
    config = {"backend": {"type": "ollama", "base_url": "http://127.0.0.1:19111",
                           "default_model": "configured:1b"}, "bot_token": "private"}
    assert providers.local_backend_configs(config)["ollama"]["base_url"].endswith(":19111")
    assert "private" not in json.dumps(providers.local_backend_configs(config))
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:19112")
    monkeypatch.setenv("OLLAMA_MODEL", "override:2b")
    for value in (providers.effective_chat_backend(config), providers.local_backend_configs(config)["ollama"]):
        assert value["base_url"].endswith(":19112")
        assert value["default_model"] == "override:2b"


def test_implicit_ollama_type_keeps_configured_address_and_model():
    config = {"backend": {"base_url": "http://127.0.0.1:19991", "default_model": "implicit:4b"}}
    assert providers.local_backend_configs(config)["ollama"]["base_url"].endswith(":19991")
    assert providers.local_backend_configs(config)["ollama"]["default_model"] == "implicit:4b"


def test_local_config_reader_has_no_runtime_initialization(tmp_path, monkeypatch):
    monkeypatch.setattr(providers.Path, "home", lambda: tmp_path)
    path = tmp_path / ".config/bach/telegram_chat.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"backend": {"type": "lmstudio", "base_url": "http://localhost:19444/v1",
                                           "api_key": "private-lm-key"}}))
    config = providers.local_backend_configs()
    assert config["lmstudio"]["base_url"].endswith(":19444/v1")
    assert config["lmstudio"]["api_key"] == "private-lm-key"
    assert not (tmp_path / ".bach").exists()


@pytest.mark.parametrize("kind", ["lmstudio", "lm-studio", "openai"])
def test_ollama_environment_never_retargets_another_provider(monkeypatch, kind):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:19111")
    monkeypatch.setenv("OLLAMA_MODEL", "local:1b")
    config = {"backend": {"type": kind, "base_url": "http://localhost:19555/v1", "default_model": "original"}}
    assert providers.effective_chat_backend(config) == config["backend"]
    if kind != "openai":
        assert providers.local_backend_configs(config)["lmstudio"]["base_url"].endswith(":19555/v1")


def test_cli_is_discovered_through_native_handler_registry(native_config, tmp_path, monkeypatch):
    from core.registry import HandlerRegistry
    isolated = tmp_path / "hub"
    isolated.mkdir()
    isolated.joinpath("model_sockets.py").write_text(
        Path(__file__).parents[1].joinpath("hub/model_sockets.py").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.delitem(sys.modules, "hub.model_sockets", raising=False)
    registry = HandlerRegistry()
    assert registry.discover(isolated) == 1
    handler = registry.get("model-sockets", base_path=tmp_path)
    assert handler and handler.get_operations()["migrate"]


def test_cli_production_app_path_does_not_open_or_initialize_task_db(tmp_path, monkeypatch):
    from core.registry import HandlerRegistry
    class AppWithoutDatabase:
        base_path = tmp_path
        @property
        def db(self):
            raise AssertionError("Katalog darf App.db nicht öffnen")
    registry = HandlerRegistry()
    registry.register("model-sockets", ModelSocketsHandler)
    handler = registry.get("model-sockets", app=AppWithoutDatabase())
    monkeypatch.setattr(catalog, "local_model_catalog", lambda: {"models": [], "runtime_verified": False})
    assert run(handler, "catalog", "--json")["models"] == []


def metadata(capabilities=None):
    return {"details": {"format": "mlx", "quantization_level": "nvfp4"},
            "model_info": {"general.parameter_count": 27_800_000_000},
            "capabilities": ["completion", "tools"] if capabilities is None else capabilities}


@pytest.fixture
def transport(monkeypatch):
    requests = []
    state = {"tags": {"models": [{"name": "qwen:27b", "size": 18_000}, {"name": "nomic:latest", "size": 100},
                                  {"name": "glm:cloud"}, {"name": "qwen:27b"}]},
             "show": {"qwen:27b": metadata(), "nomic:latest": metadata(["embedding"])},
             "tag_status": 200}
    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(state["tag_status"], json=state["tags"], headers={"location": "https://external.invalid"})
        name = json.loads(request.content)["model"]
        return httpx.Response(200, json=state["show"][name])
    original = httpx.Client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(catalog.httpx, "Client", client)
    return state, requests


def read(base="http://127.0.0.1:19111"):
    return catalog.local_model_catalog(configs={"ollama": {"base_url": base}}, host_id="test-host")


def test_catalog_filters_cloud_deduplicates_and_distinguishes_embedding(transport):
    _, requests = transport
    result = read()
    models = {item["model"]: item for item in result["models"]}
    assert set(models) == {"qwen:27b", "nomic:latest"}
    assert models["qwen:27b"]["chat_eligible"] and models["qwen:27b"]["native_tools_capable"]
    assert not models["nomic:latest"]["chat_eligible"]
    assert models["qwen:27b"]["socket_id"] == sockets.socket_id("ollama", "qwen:27b", "test-host")
    assert all(item["weight_bytes"] is None and item["residency"] == "unknown" for item in models.values())
    assert not result["runtime_verified"]
    assert [r.method for r in requests] == ["GET", "POST", "POST"]
    assert all(r.url.host == "127.0.0.1" and r.url.port == 19111 for r in requests)
    assert not any("glm:cloud" in r.content.decode() for r in requests)
    assert all(r.url.path in {"/api/tags", "/api/show"} for r in requests)


@pytest.mark.parametrize("change", [
    {"remote_host": "cloud.invalid"}, {"remote_model": "cloud-model"}, {"model_info": {}},
    {"model_info": {"general.parameter_count": True}}, {"capabilities": []}, {"capabilities": "tools"},
    {"details": {"format": "unverified"}},
])
def test_unverified_local_capability_is_excluded(transport, change):
    state, _ = transport
    state["show"]["qwen:27b"].update(change)
    result = read()
    assert "qwen:27b" not in [item["model"] for item in result["models"]]
    assert result["providers"][0]["partial"]


@pytest.mark.parametrize("base", ["https://cloud.invalid", "http://127.0.0.1?token=secret",
                                  "http://user:secret@localhost", "file:///local"])
def test_nonlocal_or_credential_url_never_queried_or_disclosed(transport, base):
    _, requests = transport
    result = read(base)
    assert requests == [] and result["providers"][0]["reason"] == "provider_not_local"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("status", [302, 403, 500])
def test_unavailable_or_redirect_is_unknown(transport, status):
    state, requests = transport
    state["tag_status"] = status
    result = read()
    assert result["providers"][0]["status"] == "unknown" and result["models"] == []
    assert len(requests) == 1


def test_response_size_and_time_budget_are_fail_closed(transport, monkeypatch):
    _, requests = transport
    monkeypatch.setattr(catalog, "_MAX_BYTES", 16)
    assert read()["providers"][0]["status"] == "unknown"
    requests.clear()
    calls = iter([0, 11])
    monkeypatch.setattr(catalog.time, "monotonic", lambda: next(calls))
    assert read()["providers"][0]["status"] == "unknown" and not requests


def test_catalog_truncation_is_explicit(transport, monkeypatch):
    monkeypatch.setattr(catalog, "_MAX_MODELS", 1)
    result = read()
    assert result["providers"][0]["partial"]
    assert len(result["models"]) == 1


def test_catalog_api_uses_shared_reader_without_write(monkeypatch):
    expected = {"models": [], "runtime_verified": False}
    monkeypatch.setattr(catalog, "local_model_catalog", lambda: copy.deepcopy(expected))
    assert asyncio.run(api.local_model_catalog()) == expected
    assert any(route.path.endswith("/catalog") and "GET" in route.methods for route in api.router.routes)


@pytest.fixture
def native_config(tmp_path, monkeypatch):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(sockets.platform, "node", lambda: "test-host")
    from hub._services import skill_source_service
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda path: None)
    return path, ModelSocketsHandler(tmp_path)


def run(handler, operation, *args):
    ok, text = handler.handle(operation, list(args))
    assert ok, text
    return json.loads(text)


def test_cli_cas_migration_configure_bind_unbind_roundtrip(native_config):
    path, handler = native_config
    assert handler.profile_name == "model-sockets" and handler.target_file == Path(path)
    before = Path(path).read_bytes()
    view = run(handler, "list", "--json")
    assert before == Path(path).read_bytes()
    migrated = run(handler, "migrate", "--version", view["configuration_version"])
    configured = run(handler, "configure", "--version", migrated["configuration_version"],
                     "--backend", "ollama", "--model", "new:4b", "--max-active-slots", "2")
    target = sockets.socket_id("ollama", "new:4b", "test-host")
    bound = run(handler, "bind", "--version", configured["configuration_version"], "--agent", "buddha_chat",
                "--socket", target, "--priority", "foreground", "--context-tokens", "4096")
    selected = next(item for item in bound["sockets"] if item["id"] == target)
    assert selected["slots"][0]["context_tokens"] == 4096
    old_data = Path(path).read_bytes()
    assert not handler.handle("unbind", ["--version", configured["configuration_version"],
                                       "--binding", selected["slots"][0]["id"]])[0]
    assert Path(path).read_bytes() == old_data
    removed = run(handler, "unbind", "--version", bound["configuration_version"],
                  "--binding", selected["slots"][0]["id"])
    assert not next(item for item in removed["sockets"] if item["id"] == target)["slots"]
    assert not removed["ack"]["worker_started"]


def test_cli_rejects_missing_version_and_cloud_config_without_write(native_config):
    path, handler = native_config
    before = Path(path).read_bytes()
    assert not handler.handle("migrate", [])[0]
    version = sockets.model_sockets_snapshot()["configuration_version"]
    migrated = run(handler, "migrate", "--version", version)
    before = Path(path).read_bytes()
    assert not handler.handle("configure", ["--version", migrated["configuration_version"], "--backend", "ollama",
                                            "--model", "glm:cloud"])[0]
    assert Path(path).read_bytes() == before
    assert handler.handle("migrate", ["--version", version], dry_run=True)[0]
    assert Path(path).read_bytes() == before
