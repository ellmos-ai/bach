"""Actual host inventories, current source history and authenticated boards."""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gui import server
from hub._services import capability_inventory_service as inventory
from hub._services import skill_source_service as sources


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_plugins_are_actual_files_without_default_seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / ".claude/plugins"
    write_json(root / "installed_plugins.json", {"plugins": {"real@test": [
        {"installPath": str(root / "cache/real/1")},
        {"installPath": str(root / "cache/real/2")}]}})
    for version in ("1", "2"):
        write_json(root / "cache/real" / version / ".claude-plugin/plugin.json", {"name":"Real", "version":version})
    write_json(tmp_path / ".claude/settings.json", {"enabledPlugins":{"real@test":False}})
    result = inventory.plugin_inventory([root])
    assert result["count"] == 2
    assert len({item["id"] for item in result["items"]}) == 2
    assert {item["version"] for item in result["items"]} == {"1", "2"}
    assert all(item["code_present"] is True and item["enabled_in_client"] is False and item["runtime_active"] is None for item in result["items"])
    assert inventory.plugin_inventory([tmp_path / "missing"])["count"] == 0


def test_mcp_projection_excludes_credentials_and_process_claims(tmp_path):
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text('[mcp_servers.safe]\ncommand="/opt/bin/node"\nargs=["--token","FAKE_ARG_SECRET"]\nenabled=false\n[mcp_servers.safe.env]\nTOKEN="FAKE_ENV_SECRET"\n[mcp_servers.remote]\nurl="https://fakeuser:FAKE_URL_SECRET@example.org/path?token=FAKE_QUERY_SECRET"\n[mcp_servers.unsafe]\ncommand="node --token FAKE_COMMAND_SECRET"\n[mcp_servers.slash]\ncommand="node --token=/private/FAKE_COMMAND_SECRET"\n', encoding="utf-8")
    result = inventory.mcp_inventory([config])
    rows = {item["name"]:item for item in result["items"]}
    assert rows["safe"]["command_name"] == "node"
    assert rows["safe"]["enabled_in_client"] is False
    assert rows["remote"]["hostname"] == "example.org"
    assert rows["unsafe"]["command_name"] is None
    assert rows["slash"]["command_name"] is None
    assert result["active_connection_count"] is None
    assert all(row["runtime_connected"] is None for row in rows.values())
    text = json.dumps(result)
    for forbidden in ("FAKE_ARG_SECRET", "FAKE_ENV_SECRET", "FAKE_URL_SECRET", "FAKE_QUERY_SECRET", "FAKE_COMMAND_SECRET", "fakeuser"):
        assert forbidden not in text


def test_codex_version_caches_are_discovered_without_runtime_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / ".codex/plugins"
    for version in ("1.0", "2.0"):
        write_json(root / "cache/marketplace/example" / version / ".codex-plugin/plugin.json", {"name":"Example", "version":version})
    (tmp_path / ".codex/config.toml").write_text('[plugins."example@marketplace"]\nenabled=false\n', encoding="utf-8")
    result = inventory.plugin_inventory([root])
    assert result["count"] == 2
    assert all(row["consumer"] == "Codex" and row["runtime_active"] is None and row["enabled_in_client"] is False for row in result["items"])
    assert {row["version"] for row in result["items"]} == {"1.0", "2.0"}
    assert all(row["evidence"] == "cached_plugin_manifest" for row in result["items"])


def test_mcp_project_scopes_are_distinct(tmp_path):
    config = tmp_path / ".claude.json"
    write_json(config, {"mcpServers":{"same":{"command":"node"}}, "projects":{"/workspace":{"mcpServers":{"same":{"command":"python"}}}}})
    result = inventory.mcp_inventory([config])
    assert result["count"] == 2
    assert len({item["id"] for item in result["items"]}) == 2
    assert {item["scope"] for item in result["items"]} == {"global", "/workspace"}


@pytest.mark.parametrize("variable,runner", [("BACH_PLUGIN_ROOTS",inventory.plugin_inventory), ("BACH_MCP_CONFIGS",inventory.mcp_inventory), ("BACH_SOFTWARE_ROOTS",inventory.software_inventory)])
def test_explicit_inventory_configuration_is_authoritative(monkeypatch, variable, runner):
    monkeypatch.setenv(variable, "[]")
    assert runner()["count"] == 0
    for value in ("", '["relative/path"]', '"wrong"'):
        monkeypatch.setenv(variable, value)
        with pytest.raises(ValueError): runner()


def test_software_files_do_not_claim_installed_runtime(tmp_path):
    root = tmp_path / "repos"
    write_json(root / "actual/package.json", {"name":"Actual", "version":"2.1.0"})
    (root / "empty").mkdir()
    result = inventory.software_inventory([root])
    assert result["count"] == 1
    item = result["items"][0]
    assert item["version"] == "2.1.0"
    assert item["installed"] is None and item["runtime_active"] is None


def test_inventory_symlinks_and_invalid_sources_are_not_followed(tmp_path):
    write_json(tmp_path / "outside/package.json", {"name":"Outside"})
    root = tmp_path / "repos"; root.mkdir()
    (root / "escape").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert inventory.software_inventory([root])["count"] == 0
    bad = tmp_path / "bad.json"; bad.write_text("not json", encoding="utf-8")
    assert inventory.mcp_inventory([bad])["errors"]


def test_current_skill_library_and_immutable_history(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("BACH_USER_SKILLS_ROOT", str(local))
    monkeypatch.setenv("BACH_SKILLS_ROOTS", "[]")
    monkeypatch.setattr(sources, "check_write_locks", lambda _:None)
    first = "---\nname: Beispiel\ndescription: Aktuelle Anleitung\nversion: 1.0.0\n---\n\n# Grüße\n"
    second = first.replace("1.0.0", "1.1.0")
    saved = sources.save_skill("example", first, "0")
    sources.save_skill("example", second, saved["source_version"])
    library = sources.skill_library()
    assert library["count"] == 1 and library["skills"][0]["version"] == "1.1.0"
    assert library["skills"][0]["description"] == "Aktuelle Anleitung"
    history = sources.list_skill_history("example")
    revision = hashlib.sha256(first.encode()).hexdigest()
    assert history["versions"][0]["source_version"] == revision
    assert sources.read_skill_history("example", revision)["content"] == first
    assert sources.read_skill("example")["content"] == second
    (local / ".history/example" / (revision + ".md")).write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError): sources.read_skill_history("example", revision)
    with pytest.raises(ValueError): sources.list_skill_history("../escape")


def test_board_shells_and_host_inventory_perimeter(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    (tmp_path / "skills").mkdir()
    for name in ("plugins", "mcp", "software"):
        (tmp_path / "skills" / (name + ".html")).write_text('<h1>Board</h1>', encoding="utf-8")
    client = TestClient(server.app)
    for name in ("plugins", "mcp", "software"):
        assert client.get("/skills/" + name).status_code == 200
    for path in ("/api/capabilities/skills/library", "/api/capabilities/plugins/inventory", "/api/capabilities/mcp/connections", "/api/capabilities/software", "/api/capabilities/skills/example/history"):
        assert client.get(path).status_code == 401
    monkeypatch.setattr(server, "validate_token", lambda token:{"id":1} if token == "board-test" else None)
    monkeypatch.setenv("BACH_MCP_CONFIGS", "[]")
    observed = client.get("/api/capabilities/mcp/connections", headers={"Authorization":"Bearer board-test"})
    assert observed.status_code == 200 and observed.json()["count"] == 0
    monkeypatch.setenv("BACH_MCP_CONFIGS", "bad")
    assert client.get("/api/capabilities/mcp/connections", headers={"Authorization":"Bearer board-test"}).status_code == 503
