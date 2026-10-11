# SPDX-License-Identifier: MIT
"""P05 3a/3e: package-supplied system templates and their capability status; isolated state only."""
import asyncio
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hub._services import blueprint_service as service
from hub._services import template_provider_service as tps
from hub._services.chat import slots_config as slots

PROVIDER = {"id": "githubbot-core", "command": ["githubbot-core", "--json", "system-agent"]}
SYSTEM = Path(__file__).resolve().parents[1]
V020_CONTENT_SHA256 = "2e72c000d1aaf00c8643082bd7efe3d80a028817c050f20b588938cad19646c8"


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    monkeypatch.setattr(tps, "_PROBES", {})
    conn = sqlite3.connect(tmp_path / "blueprints.db")
    conn.row_factory = sqlite3.Row
    service.ensure_blueprint_schema(conn)
    yield conn
    conn.close()


def descriptor(version="0.2.0", sha256=None, **changes):
    data = {"schema": "githubbot-core.system-agent/v1", "id": "githubbot", "version": version,
            "capability": {"package": "githubbot-core", "version": version, "spi_version": 1},
            "blueprint": {"name": "githubbot", "title": "GitHub Maintenance Agent", "kind": "agent",
                          "description": "Issue triage and read-only reports.", "persona_role": "github-maintainer",
                          "persona_prompt": "You are the GitHub maintenance agent.", "skills": [],
                          "animus_type": "cli", "modus": "casualis", "contractus": {"turns": 15},
                          "governance": {"profile": "read_only_research",
                                         "tool_whitelist": ["read_files", "search_content"]}},
            "permissions": {"ceiling": ["issue.comment"], "enabled": []}}
    data.update(changes)
    data["sha256"] = sha256 or tps.template_sha256(data)
    return data


def envelope(data, **changes):
    return {"schema": "githubbot-core.result/v1", "command": "system-agent", "ok": True, "mode": "read",
            "data": data, "errors": [], **changes}


def runner_for(payload, returncode=0):
    def run(command, **kwargs):
        run.calls.append((command, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload).encode("utf-8"))
    run.calls = []
    return run


def raising(exc):
    def run(command, **kwargs):
        raise exc
    return run


def sync(state, payload=None, *, runner=None):
    runner = runner or runner_for(envelope(payload or descriptor()))
    return tps.sync_providers(state, [PROVIDER], runner=runner)["providers"][0]


def rows(state):
    return [dict(row) for row in state.execute(
        "SELECT * FROM agent_blueprints WHERE provider IS NOT NULL ORDER BY id")]


def materialize(state, row, **changes):
    return service.materialize_blueprint(state, row["id"], expected_version=row["version"],
        execution={"backend": "ollama", "model": "test-local", "mode": "safe"},
        configuration_version=slots.core_system_agents_snapshot()["configuration_version"], **changes)


def test_registers_validated_template_once_per_provider_id_and_version(state, monkeypatch):
    monkeypatch.setenv("BACH_R7_SERVER_SECRET", "not-for-providers")
    runner = runner_for(envelope(descriptor()))
    first = tps.sync_providers(state, [PROVIDER], runner=runner)["providers"][0]
    command, kwargs = runner.calls[0]
    assert command == PROVIDER["command"] and kwargs["shell"] is False and kwargs["timeout"] == tps.TIMEOUT_SECONDS
    assert "BACH_R7_SERVER_SECRET" not in kwargs["env"] and kwargs["cwd"]
    assert first["action"] == "registered" and first["available"] is True
    [row] = rows(state)
    assert row["name"] == "githubbot-core.githubbot.v0.2.0" and row["is_template"] == 1
    assert (row["provider"], row["provider_template_id"], row["provider_version"]) == ("githubbot-core", "githubbot", "0.2.0")
    assert row["template_sha256"] == descriptor()["sha256"] and row["template_status"] == "available"
    assert json.loads(row["governance_json"])["profile"] == "read_only_research"
    assert "permissions" not in json.dumps(row) and "issue.comment" not in json.dumps(row)
    assert sync(state)["action"] == "confirmed" and len(rows(state)) == 1


def test_provider_env_keeps_posix_tmpdir_but_no_server_secrets(monkeypatch):
    # macOS/Linux temp dir lives in TMPDIR; without it the provider falls back to /tmp (R12).
    monkeypatch.setenv("TMPDIR", "/private/var/folders/xy/T/")
    monkeypatch.setenv("BACH_R7_SERVER_SECRET", "not-for-providers")
    env = tps._child_env()
    assert env["TMPDIR"] == "/private/var/folders/xy/T/" and "BACH_R7_SERVER_SECRET" not in env


def test_missing_provider_marks_template_unavailable_and_keeps_existing_agent(state):
    sync(state)
    [row] = rows(state)
    configured = materialize(state, row)
    slot_before = slots.get_system_slot(configured["slot_id"])
    result = sync(state, runner=raising(FileNotFoundError("githubbot-core")))
    assert result == {**result, "action": "marked_unavailable", "available": False, "reason": "provider_missing"}
    [row] = rows(state)
    assert (row["template_status"], row["template_status_reason"]) == ("unavailable", "provider_missing")
    with pytest.raises(RuntimeError, match="template_unavailable"):
        materialize(state, row, terminal_verified=True)
    assert slots.get_system_slot(configured["slot_id"]) == slot_before
    execution = {"schema": "bach.worker-execution.v1", "worker_id": configured["slot_id"],
                 "worker_thread_started": True, "terminal": False, "state": "running"}
    started = service.start_blueprint_worker(state, row["id"], expected_version=row["version"],
        configuration_version=configured["configuration_version"], dispatcher=Mock(return_value=execution))
    assert started["is_running"] is True
    assert sync(state)["action"] == "confirmed" and rows(state)[0]["template_status"] == "available"


@pytest.mark.parametrize("runner, reason", [
    (runner_for(envelope(descriptor()), returncode=2), "provider_exit_nonzero"),
    (raising(subprocess.TimeoutExpired(["githubbot-core"], 20)), "provider_timeout"),
    (raising(PermissionError("denied")), "provider_not_executable"),
    (runner_for({"schema": "githubbot-core.result/v1", "ok": False, "data": None, "errors": ["x"]}),
     "provider_result_not_ok"),
    (runner_for(descriptor(schema="other.system-agent/v1")), "schema_mismatch"),
    (runner_for(envelope(descriptor(schema="githubbot-core.system-agent/v2"))), "schema_mismatch"),
    (runner_for(envelope(descriptor(sha256="0" * 64))), "hash_mismatch"),
    (runner_for(envelope(descriptor(version="latest"))), "version_invalid"),
    (runner_for(envelope(descriptor(capability={"package": "other", "version": "0.2.0"}))), "version_invalid"),
    (runner_for(envelope(descriptor(extra=True))), "unknown_fields"),
    (runner_for(envelope(descriptor(capability={"package": "githubbot-core", "version": "0.2.0", "x": 1}))),
     "unknown_fields"),
    (runner_for(envelope({**descriptor(), "blueprint": {**descriptor()["blueprint"], "is_template": 1}})),
     "unknown_fields"),
    (runner_for(envelope(descriptor(), trace="x")), "provider_result_not_ok"),
    (runner_for(envelope(descriptor(blueprint={**descriptor()["blueprint"], "modus": "chaos"}))), "blueprint_invalid"),
    (runner_for(envelope(descriptor(blueprint={**descriptor()["blueprint"], "persona_prompt": " "}))),
     "blueprint_invalid"),
    (runner_for(envelope(descriptor(blueprint={**descriptor()["blueprint"],
                                               "contractus": {"execution": {"symbol": "unknown"}}}))),
     "blueprint_invalid"),
])
def test_failing_or_invalid_provider_output_registers_nothing(state, runner, reason):
    result = sync(state, runner=runner)
    assert result["available"] is False and result["reason"] == reason and rows(state) == []


def test_provider_contract_hash_rule_is_canonical_utf8():
    material = {"schema": "s", "id": "ü", "blueprint": {"b": 1, "a": [1, 2]}, "version": "9.9.9", "capability": {}}
    canonical = '{"blueprint":{"a":[1,2],"b":1},"id":"ü","schema":"s"}'.encode("utf-8")
    assert tps.template_sha256(material) == hashlib.sha256(canonical).hexdigest()


def test_provider_contract_githubbot_core_0_2_0(state):
    # Exact `githubbot-core --json system-agent` output of v0.2.0 (fixture, measured 2026-10-11).
    output = json.loads((SYSTEM / "tests" / "fixtures" / "githubbot_core_0_2_0_system_agent.json")
                        .read_text(encoding="utf-8"))
    data = output["data"]
    # v0.2.0 declares the hash of its whole package file including _meta.description,
    # which the output omits: not recomputable from the delivered bytes.
    assert data["sha256"] == "39615b1644dc0de923d0f2b32fdff726b5e6941d2ce69ccb1a7a1a4dacde51d9"
    assert tps.template_sha256(data) == V020_CONTENT_SHA256
    rejected = sync(state, runner=runner_for(output))
    assert (rejected["available"], rejected["reason"]) == (False, "hash_mismatch") and rows(state) == []
    fixed = {**output, "data": {**data, "sha256": V020_CONTENT_SHA256}}
    accepted = sync(state, runner=runner_for(fixed))
    assert (accepted["action"], accepted["sha256"]) == ("registered", V020_CONTENT_SHA256)
    [row] = rows(state)
    assert (row["name"], row["provider_version"], row["template_sha256"]) == (
        "githubbot-core.githubbot.v0.2.0", "0.2.0", V020_CONTENT_SHA256)


def test_invalid_json_and_oversized_output_fail_closed(state):
    def text(stdout):
        return lambda command, **kwargs: SimpleNamespace(returncode=0, stdout=stdout)
    assert sync(state, runner=text(b"not json"))["reason"] == "provider_output_invalid_json"
    assert sync(state, runner=text(b"[" * 200000 + b"]" * 200000))["reason"] == "provider_output_invalid_json"
    assert sync(state, runner=text(b" " * (tps.MAX_OUTPUT_BYTES + 1)))["reason"] == "provider_output_too_large"


def test_real_process_without_shell_and_timeout(state, tmp_path):
    payload = tmp_path / "out.json"
    payload.write_text(json.dumps(envelope(descriptor())), encoding="utf-8")
    real = {"id": "githubbot-core", "command": [sys.executable, "-c",
            "import sys; sys.stdout.write(open(sys.argv[1], encoding='utf-8').read())", str(payload)]}
    assert tps.sync_providers(state, [real])["providers"][0]["action"] == "registered"
    slow = {"id": "githubbot-core", "command": [sys.executable, "-c", "import time; time.sleep(10)"]}
    assert tps.probe(slow, timeout=0.5)["reason"] == "provider_timeout"
    missing = {"id": "githubbot-core", "command": [str(tmp_path / "does-not-exist.exe")]}
    assert tps.probe(missing)["reason"] == "provider_missing"


def _child(code):
    return {"id": "githubbot-core", "command": [sys.executable, "-c", code]}


def _probe_child(code, **kwargs):
    started = time.monotonic()
    return tps.probe(_child(code), **kwargs), time.monotonic() - started


def test_bounded_run_limit_boundary_stdout():
    limit = tps.MAX_OUTPUT_BYTES
    ok = tps._bounded_run([sys.executable, "-c", f"import sys; sys.stdout.write('x' * {limit})"], timeout=20)
    assert ok.returncode == 0 and len(ok.stdout) == limit
    with pytest.raises(tps._OutputTooLarge):
        tps._bounded_run([sys.executable, "-c", f"import sys; sys.stdout.write('x' * {limit + 1})"], timeout=20)


def test_endless_stdout_is_killed_long_before_timeout():
    code = "import sys\nwhile True: sys.stdout.write('x' * 65536); sys.stdout.flush()"
    result, seconds = _probe_child(code, timeout=15)
    assert result["reason"] == "provider_output_too_large" and seconds < 10


def test_stderr_flood_is_bounded_and_killed():
    code = "import sys\nwhile True: sys.stderr.write('e' * 65536); sys.stderr.flush()"
    result, seconds = _probe_child(code, timeout=15)
    assert result["reason"] == "provider_output_too_large" and seconds < 10


def test_overflowing_child_is_reaped(monkeypatch):
    started = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        started.append(proc)
        return proc
    monkeypatch.setattr(subprocess, "Popen", spy)
    result, _ = _probe_child("import sys\nwhile True: sys.stdout.write('x' * 65536); sys.stdout.flush()", timeout=15)
    assert result["reason"] == "provider_output_too_large"
    assert started and all(proc.poll() is not None for proc in started)


def test_silent_child_still_times_out_and_is_reaped(monkeypatch):
    started = []
    real_popen = subprocess.Popen
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(real_popen(*a, **k)) or started[-1])
    result, seconds = _probe_child("import time; time.sleep(30)", timeout=0.5)
    assert result["reason"] == "provider_timeout" and seconds < 10
    assert all(proc.poll() is not None for proc in started)


def test_grandchild_holding_the_pipes_dies_with_the_provider(tmp_path):
    # Enkel erbt stdout/stderr (wie hinter cmd.exe-Shims oder eigenen Kindern des Providers) und schreibt Herzschläge.
    beat = tmp_path / "beat"
    grand = f"import time\nfor _ in range(400):\n    open({str(beat)!r}, 'a').write('.'); time.sleep(0.05)"
    code = (f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {grand!r}], "
            "stdout=sys.stdout, stderr=sys.stderr)\ntime.sleep(60)")
    result, seconds = _probe_child(code, timeout=3)
    assert result["reason"] == "provider_timeout" and seconds < 10
    time.sleep(0.3)
    size = beat.stat().st_size
    time.sleep(0.5)
    assert size > 0 and beat.stat().st_size == size


def test_bounded_run_returns_normal_output_and_exit_code():
    done = tps._bounded_run([sys.executable, "-c", "import sys; print('hi'); sys.stderr.write('warn'); sys.exit(3)"],
                            timeout=20)
    assert (done.returncode, done.stdout.strip(), done.stderr) == (3, b"hi", b"warn")


def test_version_change_requires_explicit_migration(state):
    sync(state)
    [old] = rows(state)
    configured = materialize(state, old)
    newer = descriptor("0.3.0", blueprint={**descriptor()["blueprint"], "persona_prompt": "Newer prompt."})
    result = sync(state, newer)
    assert result["action"] == "migration_required" and result["current_version"] == "0.2.0"
    [row] = rows(state)
    assert row["provider_version"] == "0.2.0" and row["persona_prompt"] == old["persona_prompt"]
    assert row["template_status"] == "migration_required"
    runner = runner_for(envelope(newer))
    with pytest.raises(tps.TemplateProviderError, match="offer_changed"):
        tps.migrate_template(state, "githubbot-core", "githubbot", to_version="0.3.0",
                             expected_sha256=old["template_sha256"], providers=[PROVIDER], runner=runner)
    assert len(rows(state)) == 1
    migrated = tps.migrate_template(state, "githubbot-core", "githubbot", to_version="0.3.0",
                                    expected_sha256=newer["sha256"], providers=[PROVIDER], runner=runner)
    assert migrated["from_version"] == "0.2.0" and migrated["superseded_blueprint_id"] == old["id"]
    old_row, new_row = rows(state)
    assert (old_row["template_status"], old_row["version"]) == ("superseded", old["version"])
    assert (new_row["provider_version"], new_row["template_status"]) == ("0.3.0", "available")
    assert new_row["persona_prompt"] == "Newer prompt."
    assert slots.get_system_slot(configured["slot_id"])["blueprint_version"] == old["version"]
    with pytest.raises(tps.TemplateProviderError, match="already_current"):
        tps.migrate_template(state, "githubbot-core", "githubbot", to_version="0.3.0",
                             expected_sha256=newer["sha256"], providers=[PROVIDER], runner=runner)
    assert sync(state, newer)["action"] == "confirmed"


def test_same_version_with_changed_content_is_not_overwritten(state):
    sync(state)
    changed = descriptor(blueprint={**descriptor()["blueprint"], "persona_prompt": "Changed silently."})
    assert sync(state, changed)["action"] == "marked_unavailable"
    [row] = rows(state)
    assert row["persona_prompt"] == "You are the GitHub maintenance agent."
    assert row["template_status_reason"] == "template_changed_without_version"


def test_user_saves_cannot_create_or_overwrite_system_templates(state):
    base = {"name": "mine", "persona_role": "recherche", "persona_prompt": "x", "kind": "agent"}
    with pytest.raises(PermissionError):
        service.save_blueprint(state, {**base, "is_template": 1})
    saved = service.save_blueprint(state, {**base, "provider": "githubbot-core", "provider_version": "9.9.9",
                                           "template_sha256": "a" * 64, "template_status": "available"})
    row = state.execute("SELECT * FROM agent_blueprints WHERE id = ?", (saved["id"],)).fetchone()
    assert row["is_template"] == 0 and row["provider"] is None and row["template_sha256"] is None
    sync(state)
    with pytest.raises(PermissionError):
        service.save_blueprint(state, {**base, "name": "githubbot-core.githubbot.v0.2.0"})


def test_user_row_with_the_template_name_is_never_taken_over(state):
    service.save_blueprint(state, {"name": "githubbot-core.githubbot.v0.2.0", "persona_role": "recherche",
                                   "persona_prompt": "user owned", "kind": "agent"})
    assert sync(state)["action"] == "name_conflict"
    assert rows(state) == []
    assert tuple(state.execute("SELECT persona_prompt, is_template FROM agent_blueprints").fetchone()) == ("user owned", 0)


def test_unconfigured_provider_templates_become_unavailable(state):
    sync(state)
    result = tps.sync_providers(state, [])
    assert result["unconfigured"] == ["githubbot-core"]
    assert rows(state)[0]["template_status_reason"] == "provider_not_configured"


@pytest.mark.parametrize("content", [
    "{", "[]", json.dumps({"providers": [{"id": "x"}]}), json.dumps({"providers": [{"id": "x", "command": []}]}),
    json.dumps({"providers": [{"id": "x", "command": "x --json"}]}),
    json.dumps({"providers": [PROVIDER, PROVIDER]}), json.dumps({"providers": [], "extra": 1}),
    json.dumps({"providers": [{**PROVIDER, "shell": True}]}),
])
def test_invalid_provider_config_fails_closed(tmp_path, monkeypatch, content):
    path = tmp_path / "providers.json"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("BACH_TEMPLATE_PROVIDERS_FILE", str(path))
    with pytest.raises(tps.TemplateProviderError, match="provider_config_invalid"):
        tps.load_providers()
    modules, sources = tps.capability_status()
    assert modules["template-providers"]["adapter_registered"] is False and sources == []


def test_capability_status_reports_last_real_probe_without_commands(state, tmp_path, monkeypatch):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": [PROVIDER]}), encoding="utf-8")
    monkeypatch.setenv("BACH_TEMPLATE_PROVIDERS_FILE", str(path))
    modules, sources = tps.capability_status()
    module = modules["template-provider:githubbot-core"]
    assert module["available"] is None and module["reason_code"] == "provider_not_probed"
    tps.sync_providers(state, runner=runner_for(envelope(descriptor())))
    modules, sources = tps.capability_status()
    module = modules["template-provider:githubbot-core"]
    assert module == {**module, "adapter_registered": True, "available": True, "runtime_verified": False,
                      "reason_code": "provider_probe_ok", "version": "0.2.0"}
    assert sources[0]["verified"] is False and sources[0]["descriptor_verified"] is True
    assert sources[0]["template"] == {"id": "githubbot", "version": "0.2.0", "sha256": descriptor()["sha256"]}
    assert sources[0]["source_commit"] is None
    assert "--json" not in json.dumps([modules, sources])
    tps.sync_providers(state, runner=runner_for(envelope(descriptor()), returncode=1))
    module = tps.capability_status()[0]["template-provider:githubbot-core"]
    assert module["available"] is False and module["reason_code"] == "provider_exit_nonzero"


def test_gui_capabilities_route_includes_provider_modules(tmp_path, monkeypatch):
    from gui import server
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": [PROVIDER]}), encoding="utf-8")
    monkeypatch.setenv("BACH_TEMPLATE_PROVIDERS_FILE", str(path))
    monkeypatch.setattr(tps, "_PROBES", {})
    result = asyncio.run(server.get_gui_capabilities())
    assert result["modules"]["template-provider:githubbot-core"]["reason_code"] == "provider_not_probed"
    assert result["module_sources"][0]["id"] == "policy-registry"
    assert result["module_sources"][1]["id"] == "githubbot-core"
    assert "template-provider:githubbot-core" not in result["missing_adapters"]
    # Under pytest, gui.server cannot include unified_api (pre-existing import order); declare its router directly.
    from gui.api import unified_api
    from gui.api.gui_capabilities import declaration
    endpoints = {(e["method"], e["path"]): e for e in declaration(unified_api.router.routes, {}, {}, {})["endpoints"]}
    for path in ("/api/agent-studio/template-providers/sync", "/api/agent-studio/template-providers/migrate"):
        assert endpoints[("POST", path)]["auth"] == "device-token"


def test_sync_route_runs_the_configured_real_provider(tmp_path, monkeypatch):
    from gui.api import unified_api
    payload = tmp_path / "out.json"
    payload.write_text(json.dumps(envelope(descriptor())), encoding="utf-8")
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({"providers": [{"id": "githubbot-core", "command": [sys.executable, "-c",
        "import sys; sys.stdout.write(open(sys.argv[1], encoding='utf-8').read())", str(payload)]}]}),
        encoding="utf-8")
    monkeypatch.setenv("BACH_TEMPLATE_PROVIDERS_FILE", str(config))
    monkeypatch.setattr(tps, "_PROBES", {})
    db = tmp_path / "bach.db"
    monkeypatch.setattr(unified_api, "_get_conn", lambda timeout=30.0: sqlite3.connect(db))
    result = asyncio.run(unified_api.sync_template_providers())
    assert result["providers"][0]["action"] == "registered"
    with pytest.raises(unified_api.HTTPException) as denied:
        asyncio.run(unified_api.migrate_system_template({"provider": "githubbot-core", "template_id": "githubbot",
            "to_version": "0.2.0", "expected_sha256": descriptor()["sha256"]}))
    assert denied.value.status_code == 409 and denied.value.detail == "already_current"
    with pytest.raises(unified_api.HTTPException) as bad:
        asyncio.run(unified_api.migrate_system_template({"provider": "githubbot-core"}))
    assert bad.value.status_code == 400


def test_migration_052_is_additive_and_idempotent(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "m052", SYSTEM / "data" / "schema" / "migrations" / "052_blueprint_template_provider.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute("CREATE TABLE agent_blueprints (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,"
                 " title TEXT, is_template INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO agent_blueprints (name, title, is_template) VALUES ('legacy', 'Alt', 1)")
    conn.commit()
    module.run_migration(conn)
    module.run_migration(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_blueprints)")}
    assert {"provider", "provider_template_id", "provider_version", "template_sha256",
            "template_status", "template_status_reason"} <= columns
    assert conn.execute("SELECT name, title, is_template, provider FROM agent_blueprints").fetchall() == [
        ("legacy", "Alt", 1, None)]
    conn.close()
