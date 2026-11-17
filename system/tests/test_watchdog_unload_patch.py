"""Behavioral acceptance for the prepared watchdog-to-native-guard handoff."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PATCH_TOOL = Path(__file__).resolve().parents[1] / "tools/maintenance/watchdog_unload_patch.py"
PREFIX = b"#!/bin/bash\n# independent watchdog configuration\n"
SUFFIX = b"\nundo_ollama_unload_all() {\n    return 0\n}\n# independent recovery code\n"
OLD_FUNCTION = b'do_ollama_unload_all() {\n    # entlaedt alle aktiven Modelle via API keep_alive=0\n    local models=$(curl -s --max-time 5 http://localhost:11434/api/ps 2>/dev/null | /usr/bin/python3 -c "\nimport json, sys\ntry:\n    d = json.load(sys.stdin)\n    for m in d.get(\'models\', []):\n        print(m.get(\'name\', \'\'))\nexcept Exception:\n    pass\n")\n    if [ -z "$models" ]; then\n        log "  ollama: kein Modell geladen, nichts zu tun"\n        return 1  # nichts effektiv passiert, eskalation soll weitergehen\n    fi\n    local n=0\n    while IFS= read -r m; do\n        [ -z "$m" ] && continue\n        curl -s --max-time 5 -X POST http://localhost:11434/api/generate \\\n            -d "{\\"model\\":\\"$m\\",\\"keep_alive\\":0}" > /dev/null 2>&1\n        log "  ollama: stop model $m (keep_alive=0)"\n        n=$((n + 1))\n    done <<< "$models"\n    [ "$n" -gt 0 ] && return 0 || return 1\n}\n'


def patcher():
    assert PATCH_TOOL.is_file(), "Guarded watchdog patch preparation is not implemented"
    spec = importlib.util.spec_from_file_location("watchdog_patch_acceptance", PATCH_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source():
    return PREFIX + OLD_FUNCTION + SUFFIX


def prepare(data=None, **paths):
    data = source() if data is None else data
    return patcher().prepare_patch(
        data, expected_sha256=hashlib.sha256(data).hexdigest(),
        python_path=paths.get("python_path", "/usr/bin/python3"),
        helper_path=paths.get("helper_path", "/srv/bach/memory_pressure_unload_guard.py"),
    )


def test_patch_preserves_unrelated_watchdog_and_recovery_bytes():
    result = prepare()
    assert result.startswith(PREFIX)
    assert result.endswith(SUFFIX)
    assert result != source()


def test_stale_source_hash_denies_patch():
    with pytest.raises(ValueError, match="source_changed"):
        patcher().prepare_patch(source(), expected_sha256="0" * 64,
            python_path="/usr/bin/python3", helper_path="/srv/bach/guard.py")


@pytest.mark.parametrize("data", [
    PREFIX + OLD_FUNCTION + OLD_FUNCTION + SUFFIX,
    PREFIX + SUFFIX,
    PREFIX + OLD_FUNCTION.replace(b"local n=0", b"local n=1") + SUFFIX,
], ids=["duplicate", "missing", "changed"])
def test_missing_duplicate_or_changed_unload_function_is_not_guessed(data):
    with pytest.raises(ValueError):
        prepare(data)


@pytest.mark.parametrize("value", ["relative/python", "/tmp/../python", "/tmp/python\nother", "/tmp/python\x00other"])
def test_ambiguous_operator_path_denies_patch(value):
    with pytest.raises(ValueError):
        prepare(python_path=value)


@pytest.mark.parametrize("returncode", [0, 1, 73])
@pytest.mark.parametrize("override_threshold", [False, True])
def test_shell_preserves_guard_argv_result_and_quoting(tmp_path, returncode, override_threshold):
    helper = tmp_path / "guard 'quoted' $(touch injected).py"
    capture = tmp_path / "argv.json"
    helper.write_text(
        "import json,os,sys\n"
        "open(os.environ['CAPTURE_PATH'],'w').write(json.dumps(sys.argv[1:]))\n"
        f"raise SystemExit({returncode})\n", encoding="utf-8")
    result = prepare(python_path=sys.executable, helper_path=str(helper))
    runtime = Path(os.environ.get("BACH_RUNTIME_DIR", str(tmp_path / "runtime with spaces")))
    env = dict(os.environ, HOME=str(tmp_path / "isolated-home"),
        BACH_RUNTIME_DIR=str(runtime),
        LOG=str(tmp_path / "watchdog.log"), SESSION_FLAG=str(tmp_path / "session flag.json"),
        METRIC_MODE="pressure", PRESSURE_WARN_LEVEL="4",
        FREE_EMERGENCY_PAGES="0", FREE_PAGES_MIN="65536", CAPTURE_PATH=str(capture))
    env.pop("free_threshold", None)
    if override_threshold:
        env["free_threshold"] = "98304"
    run = subprocess.run(["/bin/bash", "-c", result.decode("utf-8") + "\ndo_ollama_unload_all\n"],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert run.returncode == returncode
    assert json.loads(capture.read_text()) == [
        "--inference-root", str(runtime / "local-inference"),
        "--session-flag", str(tmp_path / "session flag.json"),
        "--metric-mode", "pressure", "--warn-level", "4",
        "--emergency-pages", "0", "--free-threshold", "98304" if override_threshold else "65536",
    ]
    assert not (tmp_path / "injected").exists()


def test_missing_guard_is_failure_and_has_no_direct_unload_fallback(tmp_path):
    result = prepare(python_path=sys.executable, helper_path=str(tmp_path / "missing.py"))
    env = dict(os.environ, HOME=str(tmp_path), LOG=str(tmp_path / "watchdog.log"),
        SESSION_FLAG=str(tmp_path / "session.json"), METRIC_MODE="pressure",
        PRESSURE_WARN_LEVEL="4", FREE_EMERGENCY_PAGES="0", FREE_PAGES_MIN="65536")
    env.pop("BACH_RUNTIME_DIR", None)
    run = subprocess.run(["/bin/bash", "-c", result.decode() + "\ndo_ollama_unload_all\n"],
        env=env, cwd=tmp_path, capture_output=True, timeout=10)
    assert run.returncode != 0
    assert not (tmp_path / ".bach").exists()


def test_cli_only_prepares_new_artifact_and_refuses_overwrite(tmp_path):
    patcher()
    original = tmp_path / "watchdog.sh"
    output = tmp_path / "prepared.sh"
    original.write_bytes(source())
    command = [sys.executable, str(PATCH_TOOL), "--source", str(original),
        "--expected-sha256", hashlib.sha256(source()).hexdigest(),
        "--python", sys.executable, "--helper", "/srv/bach/guard.py", "--output", str(output)]
    first = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert first.returncode == 0, first.stderr
    assert original.read_bytes() == source()
    prepared = output.read_bytes()
    assert prepared.startswith(PREFIX) and prepared.endswith(SUFFIX)
    receipt = json.loads(first.stdout)
    assert receipt["source_sha256"] == hashlib.sha256(source()).hexdigest()
    assert receipt["prepared_sha256"] == hashlib.sha256(prepared).hexdigest()
    second = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert second.returncode != 0
    assert output.read_bytes() == prepared
