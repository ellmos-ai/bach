# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests: Betriebsmodi der Foerderbericht-Pipeline (cloud = anonymisiert, lokal = ohne Anonymisierung)."""

import io
import json
import re
import sys
import types
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import foerderbericht_pipeline as fp
from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline, PipelineError


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    return FoerderberichtPipeline(base_path=tmp_path)


def _akte(base):
    d = base / "data_roh" / "Muster, Max"
    d.mkdir(parents=True, exist_ok=True)
    (d / "Aktendeckblatt.txt").write_text(
        "Name: Max Muster\nGeboren am 15.03.2016\nEltern: Erika Muster, Hans Muster\n"
        "Einzeltherapeutin: Frau Hoffmann\n", encoding="utf-8")
    (d / "Protokoll_1.txt").write_text(
        "Max kam ruhig in die Gruppe. Frau Hoffmann begruesste ihn.\n", encoding="utf-8")


def test_unknown_modus_fails_closed(pipe):
    r = pipe.run_full_pipeline(modus="egal")
    assert not r.success and "Modus" in r.error


def test_modus_lokal_rejects_cloud_backend(pipe):
    r = pipe.run_full_pipeline(modus="lokal", llm_backend="claude_code")
    assert not r.success and "lokale Backends" in r.error


def test_prepare_without_anonymization_keeps_cleartext_and_identity_mapping(pipe):
    _akte(pipe.base_path)
    r = pipe.prepare_prompt(anonymize=False)
    assert r.success, r.error
    prompt = (pipe.base_path / "data_bundled" / "prompt.txt").read_text(encoding="utf-8")
    assert "Max Muster" in prompt and "Hoffmann" in prompt
    assert not re.search(r"Person\d{3}", prompt)
    info = json.loads((pipe.base_path / "data_bundled" / "session_info.json").read_text(encoding="utf-8"))
    assert info["mappings"] == {} and info["modus"] == "lokal"


def test_run_full_pipeline_lokal_uses_ollama_with_cleartext_prompt(pipe, monkeypatch):
    _akte(pipe.base_path)
    seen = {}

    def fake_llm(self, prompt, backend, model):
        seen.update(prompt=prompt, backend=backend, model=model)
        return "{}"

    monkeypatch.setattr(FoerderberichtPipeline, "_call_llm", fake_llm)
    monkeypatch.setattr(FoerderberichtPipeline, "finish_report",
                        lambda self, **kw: kw.get("_result") or fp.PipelineResult(success=True))
    pipe.run_full_pipeline(modus="lokal")
    assert seen["backend"] == "ollama" and seen["model"] == fp.DEFAULT_LOCAL_MODEL
    assert "Max Muster" in seen["prompt"]


def test_run_full_pipeline_cloud_still_anonymizes(pipe, monkeypatch):
    _akte(pipe.base_path)
    seen = {}

    def fake_llm(self, prompt, backend, model):
        seen.update(prompt=prompt, backend=backend)
        return "{}"

    monkeypatch.setattr(FoerderberichtPipeline, "_call_llm", fake_llm)
    monkeypatch.setattr(FoerderberichtPipeline, "finish_report",
                        lambda self, **kw: kw.get("_result") or fp.PipelineResult(success=True))
    pipe.run_full_pipeline()  # Default: cloud
    assert seen["backend"] == "claude_code"
    seg = seen["prompt"][seen["prompt"].index("=== DOKUMENTEN-BUNDLE"):seen["prompt"].index("=== AUFGABE")]
    import re as _re
    assert "Muster" not in seg and _re.search(r"\bMax\b", seg) is None


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_opener(monkeypatch, answer, calls, ps_models=None):
    class Opener:
        def open(self, req, timeout=None):
            if req.full_url.endswith("/api/ps"):
                return _FakeResp(json.dumps({"models": ps_models or []}).encode("utf-8"))
            calls.append((req.full_url, json.loads(req.data.decode("utf-8"))))
            return _FakeResp(json.dumps(answer).encode("utf-8"))

    monkeypatch.setattr(fp.urllib.request, "build_opener", lambda *handlers: Opener())


def test_ollama_posts_to_loopback_without_think_and_with_context(pipe, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    calls = []
    _fake_opener(monkeypatch, {"message": {"content": ' {"a": 1} '}, "done_reason": "stop",
                               "prompt_eval_count": 100, "eval_count": 50}, calls)
    assert pipe._call_llm("p", "ollama", "qwen3:4b") == '{"a": 1}'
    url, payload = calls[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert payload["think"] is False and payload["stream"] is False and payload["options"]["num_ctx"] >= 8192


@pytest.mark.parametrize("host", ["http://192.168.1.5:11434", "https://ollama.com", "example.org:11434",
                                  "http://8.8.8.8:11434", "http://100.128.0.1:11434"])
def test_ollama_refuses_hosts_that_are_not_own_devices(pipe, monkeypatch, host):
    monkeypatch.setenv("OLLAMA_HOST", host)
    with pytest.raises(PipelineError, match="FOERDERBERICHT_ALLOWED_HOSTS"):
        pipe._call_llm("p", "ollama", "qwen3:4b")


@pytest.mark.parametrize("host", ["http://127.0.0.1:11434", "localhost:11434", "http://100.119.69.90:11434",
                                  "http://mac-studio.tail1234.ts.net:11434"])
def test_ollama_accepts_loopback_and_tailscale_hosts(pipe, monkeypatch, host):
    monkeypatch.setenv(
        "FOERDERBERICHT_ALLOWED_HOSTS",
        "localhost,127.0.0.1,100.119.69.90,mac-studio.tail1234.ts.net",
    )
    monkeypatch.setenv("OLLAMA_HOST", host)
    calls = []
    _fake_opener(monkeypatch, {"message": {"content": "{}"}, "done_reason": "stop",
                               "prompt_eval_count": 10, "eval_count": 5}, calls)
    assert pipe._call_llm("p", "ollama", "qwen3:4b") == "{}"


def test_ollama_reuses_context_of_already_loaded_model(pipe, monkeypatch):
    """Ein Dauer-Worker (Buddha) haelt das Modell mit 16384 Kontext. Ein anderer num_ctx wuerde es
    neu laden und verdraengen; deshalb wird der geladene Kontext uebernommen."""
    monkeypatch.delenv("FOERDERBERICHT_NUM_CTX", raising=False)
    calls = []
    _fake_opener(monkeypatch, {"message": {"content": "{}"}, "done_reason": "stop",
                               "prompt_eval_count": 10, "eval_count": 5}, calls,
                 ps_models=[{"name": "qwen3.8:27b-mlx", "model": "qwen3.8:27b-mlx", "context_length": 16384}])
    pipe._call_llm("p", "ollama", "qwen3.8:27b-mlx")
    payload = calls[0][1]
    assert payload["options"]["num_ctx"] == 16384 and payload["keep_alive"] == "30m"


@pytest.mark.parametrize("model", ["glm-5.2:cloud", "gpt-oss:120b-cloud", "claude-sonnet-4-6"])
def test_ollama_refuses_cloud_models(pipe, model):
    with pytest.raises(PipelineError, match="kein lokales Modell"):
        pipe._call_llm("p", "ollama", model)


def test_ollama_detects_truncated_context_and_errors(pipe, monkeypatch):
    monkeypatch.setenv("FOERDERBERICHT_NUM_CTX", "8192")
    calls = []
    _fake_opener(monkeypatch, {"message": {"content": "x"}, "done_reason": "stop",
                               "prompt_eval_count": 8000, "eval_count": 400}, calls)
    with pytest.raises(PipelineError, match="Kontextfenster voll"):
        pipe._call_llm("p", "ollama", "qwen3:4b")
    _fake_opener(monkeypatch, {"error": "model not found"}, calls)
    with pytest.raises(PipelineError, match="model not found"):
        pipe._call_llm("p", "ollama", "qwen3:4b")

# --- SSH-Tunnel (automatisch im Modus lokal, wenn OLLAMA_HOST fehlt und ein Ziel konfiguriert ist) ---

class _FakeProc:
    def __init__(self, exit_code=None, stderr=b"", hang_on_terminate=False):
        self.exit_code = exit_code
        self.stderr = io.BytesIO(stderr)
        self.terminated = False
        self.killed = False
        self.hang = hang_on_terminate
        self._handle = 0

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        if not self.hang:
            self.exit_code = 0

    def kill(self):
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout=None):
        if self.exit_code is None:
            raise fp.subprocess.TimeoutExpired("ssh", timeout)
        return self.exit_code


@pytest.fixture
def tunnel_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("FOERDERBERICHT_SSH_TUNNEL", "tester@100.64.0.9")
    monkeypatch.setenv("FOERDERBERICHT_ALLOWED_HOSTS", "100.64.0.9")
    monkeypatch.setenv("FOERDERBERICHT_ALLOWED_HOSTS", "localhost,127.0.0.1,100.64.0.9")
    monkeypatch.delenv("FOERDERBERICHT_SSH_KEY", raising=False)
    monkeypatch.setattr(fp, "_free_port", lambda: 54321)
    monkeypatch.setattr(fp, "_tunnel_ready", lambda port, proc, timeout_s=45.0: None)
    started = []

    def fake_popen(cmd, **kwargs):
        proc = _FakeProc()
        started.append((cmd, kwargs, proc))
        return proc

    monkeypatch.setattr(fp.subprocess, "Popen", fake_popen)
    return started


_OK_ANSWER = {"message": {"content": "{}"}, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5}


def test_tunnel_is_opened_used_and_closed(pipe, monkeypatch, tunnel_env):
    calls = []
    _fake_opener(monkeypatch, _OK_ANSWER, calls)
    assert pipe._call_llm("p", "ollama", "qwen3.8:27b-mlx") == "{}"
    cmd, _kw, proc = tunnel_env[0]
    assert cmd[0] == "ssh" and "-N" in cmd and "BatchMode=yes" in cmd
    assert cmd[cmd.index("-L") + 1] == "127.0.0.1:54321:127.0.0.1:11434"
    assert cmd[-2:] == ["--", "tester@100.64.0.9"], "Ziel hinter '--' (keine Optionsinjektion)"
    assert calls[0][0] == "http://127.0.0.1:54321/api/chat"
    assert proc.terminated, "Tunnel muss nach dem Aufruf geschlossen sein"


def test_tunnel_uses_key_and_remote_port_from_env(pipe, monkeypatch, tunnel_env):
    monkeypatch.setenv("FOERDERBERICHT_SSH_KEY", "/tmp/k")
    monkeypatch.setenv("FOERDERBERICHT_SSH_REMOTE_PORT", "12345")
    _fake_opener(monkeypatch, _OK_ANSWER, [])
    pipe._call_llm("p", "ollama", "m")
    cmd = tunnel_env[0][0]
    assert cmd[cmd.index("-i") + 1] == "/tmp/k"
    assert cmd[cmd.index("-L") + 1].endswith(":12345")


def test_tunnel_is_closed_when_model_call_fails(pipe, monkeypatch, tunnel_env):
    _fake_opener(monkeypatch, {"error": "model not found"}, [])
    with pytest.raises(PipelineError, match="model not found"):
        pipe._call_llm("p", "ollama", "m")
    assert tunnel_env[0][2].terminated


def test_tunnel_is_closed_on_keyboard_interrupt(pipe, monkeypatch, tunnel_env):
    class Boom:
        def open(self, req, timeout=None):
            if req.full_url.endswith("/api/ps"):
                return _FakeResp(b'{"models": []}')
            raise KeyboardInterrupt

    monkeypatch.setattr(fp.urllib.request, "build_opener", lambda *h: Boom())
    with pytest.raises(KeyboardInterrupt):
        pipe._call_llm("p", "ollama", "m")
    assert tunnel_env[0][2].terminated


def test_tunnel_is_killed_when_terminate_does_not_help(pipe, monkeypatch, tunnel_env):
    stubborn = _FakeProc(hang_on_terminate=True)
    monkeypatch.setattr(fp.subprocess, "Popen", lambda cmd, **kw: stubborn)
    _fake_opener(monkeypatch, _OK_ANSWER, [])
    pipe._call_llm("p", "ollama", "m")
    assert stubborn.terminated and stubborn.killed


def test_no_tunnel_when_ollama_host_is_set_or_no_target(pipe, monkeypatch, tunnel_env):
    _fake_opener(monkeypatch, _OK_ANSWER, [])
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    pipe._call_llm("p", "ollama", "m")
    assert tunnel_env == []
    monkeypatch.delenv("OLLAMA_HOST")
    monkeypatch.delenv("FOERDERBERICHT_SSH_TUNNEL")
    pipe._call_llm("p", "ollama", "m")
    assert tunnel_env == []


def test_tunnel_start_failure_reports_ssh_error(pipe, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("FOERDERBERICHT_SSH_TUNNEL", "tester@100.64.0.9")
    monkeypatch.setenv("FOERDERBERICHT_ALLOWED_HOSTS", "100.64.0.9")
    monkeypatch.setattr(fp, "_free_port", lambda: 54321)
    monkeypatch.setattr(fp.subprocess, "Popen", lambda cmd, **kw: _FakeProc(exit_code=255, stderr=b"Permission denied"))
    with pytest.raises(PipelineError, match="Permission denied"):
        pipe._call_llm("p", "ollama", "m")


def test_tunnel_not_ready_times_out(monkeypatch):
    proc = _FakeProc()  # laeuft, antwortet aber nie
    monkeypatch.setattr(fp.time, "sleep", lambda s: None)
    t = iter(range(0, 1000, 20))
    monkeypatch.setattr(fp.time, "time", lambda: next(t))

    class NoAnswer:
        def open(self, *a, **k):
            raise OSError("refused")

    monkeypatch.setattr(fp.urllib.request, "build_opener", lambda *h: NoAnswer())
    with pytest.raises(PipelineError, match="nicht bereit"):
        fp._tunnel_ready(54321, proc, timeout_s=45)


@pytest.mark.parametrize("target", ["", "-oProxyCommand=evil", "a b@host", "user@8.8.8.8", "user@host;rm -rf",
                                    "http://x", "user@evil.example.com", "@host", "user@"])
def test_invalid_tunnel_targets_are_rejected(pipe, monkeypatch, target):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("FOERDERBERICHT_SSH_TUNNEL", target or "   ")
    started = []
    monkeypatch.setattr(fp.subprocess, "Popen", lambda *a, **k: started.append(1))
    _fake_opener(monkeypatch, _OK_ANSWER, [])
    if not target:
        # leeres Ziel = kein Tunnel (heutiges Verhalten), kein Fehler
        assert pipe._call_llm("p", "ollama", "m") == "{}" and started == []
        return
    with pytest.raises(PipelineError, match="Tunnelziel"):
        pipe._call_llm("p", "ollama", "m")
    assert started == [], "bei ungueltigem Ziel darf kein Prozess starten"


@pytest.mark.parametrize("target", ["tester@100.119.69.90", "mac-studio", "u@mac.tail1234.ts.net", "u@127.0.0.1", "u@localhost"])
def test_valid_tunnel_targets_are_accepted(target, monkeypatch):
    monkeypatch.setenv(
        "FOERDERBERICHT_ALLOWED_HOSTS",
        "localhost,127.0.0.1,100.119.69.90,mac.tail1234.ts.net",
    )
    assert fp._validate_tunnel_target(target) == target


# --- P2-Belege Zweitpruefung PR #553 ---


@pytest.mark.parametrize(
    "host",
    [
        "http://100.128.0.1:11434",
        "http://100.64.0.9:11434",
        "http://100.119.69.91:11434",
        "http://other.tail1234.ts.net:11434",
    ],
)
def test_ollama_rejects_unlisted_tailscale_neighbors_when_own_devices_allowed(
    pipe, monkeypatch, host
):
    monkeypatch.setenv(
        "FOERDERBERICHT_ALLOWED_HOSTS",
        "localhost,127.0.0.1,100.119.69.90,mac-studio.tail1234.ts.net",
    )
    monkeypatch.setenv("OLLAMA_HOST", host)
    with pytest.raises(PipelineError, match="FOERDERBERICHT_ALLOWED_HOSTS"):
        pipe._call_llm("p", "ollama", "qwen3:4b")


def test_prepare_prompt_accepts_flat_data_roh_without_client_folder(pipe):
    data_roh = pipe.base_path / "data_roh"
    data_roh.mkdir(parents=True, exist_ok=True)
    (data_roh / "Aktendeckblatt.txt").write_text(
        "Name: Max Muster\n"
        "Geboren am 15.03.2016\n"
        "Eltern: Erika Muster, Hans Muster\n"
        "Einzeltherapeutin: Frau Hoffmann\n",
        encoding="utf-8",
    )
    result = pipe.prepare_prompt(anonymize=False, client_name="Max Muster")
    assert result.success, result.error
    prompt = (pipe.base_path / "data_bundled" / "prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "Max Muster" in prompt


def test_prepare_prompt_errors_when_data_roh_is_empty(pipe):
    (pipe.base_path / "data_roh").mkdir(parents=True, exist_ok=True)
    try:
        result = pipe.prepare_prompt(anonymize=False)
    except PipelineError as exc:
        assert "data_roh enthaelt" in str(exc)
    else:
        assert not result.success
        assert "data_roh enthaelt" in (result.error or "")


def test_prepare_prompt_requires_client_name_when_data_roh_is_flat(pipe):
    data_roh = pipe.base_path / "data_roh"
    data_roh.mkdir(parents=True, exist_ok=True)
    (data_roh / "Aktendeckblatt.txt").write_text(
        "Name: Max Muster\nGeboren am 15.03.2016\n", encoding="utf-8",
    )
    result = pipe.prepare_prompt(anonymize=False)
    assert not result.success
    assert "Klienten-Ordner" in (result.error or "")


def test_ollama_detects_num_predict_truncation(pipe, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("FOERDERBERICHT_SSH_TUNNEL", raising=False)
    monkeypatch.delenv("FOERDERBERICHT_NUM_CTX", raising=False)
    calls = []
    _fake_opener(
        monkeypatch,
        {
            "message": {"content": '{"a": 1}'},
            "done_reason": "length",
            "prompt_eval_count": 100,
            "eval_count": 6000,
        },
        calls,
    )
    with pytest.raises(PipelineError, match="abgeschnitten"):
        pipe._call_llm("p", "ollama", "qwen3:4b")
    assert calls[0][1]["options"]["num_predict"] == 6000


def test_ollama_returns_answer_when_done_reason_is_stop(pipe, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("FOERDERBERICHT_SSH_TUNNEL", raising=False)
    monkeypatch.delenv("FOERDERBERICHT_NUM_CTX", raising=False)
    calls = []
    _fake_opener(
        monkeypatch,
        {
            "message": {"content": '{"a": 1}'},
            "done_reason": "stop",
            "prompt_eval_count": 100,
            "eval_count": 50,
        },
        calls,
    )
    assert pipe._call_llm("p", "ollama", "qwen3:4b") == '{"a": 1}'
    assert calls[0][1]["options"]["num_predict"] == 6000
