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
    d.mkdir(parents=True)
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
    assert "Muster" not in seg and "Max" not in seg


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_opener(monkeypatch, answer, calls):
    class Opener:
        def open(self, req, timeout=None):
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


@pytest.mark.parametrize("host", ["http://192.168.1.5:11434", "https://ollama.com", "example.org:11434"])
def test_ollama_refuses_non_loopback_host(pipe, monkeypatch, host):
    monkeypatch.setenv("OLLAMA_HOST", host)
    with pytest.raises(PipelineError, match="localhost"):
        pipe._call_llm("p", "ollama", "qwen3:4b")


@pytest.mark.parametrize("model", ["glm-5.2:cloud", "gpt-oss:120b-cloud", "claude-sonnet-4-6"])
def test_ollama_refuses_cloud_models(pipe, model):
    with pytest.raises(PipelineError, match="kein lokales Modell"):
        pipe._call_llm("p", "ollama", model)


def test_ollama_detects_truncated_context_and_errors(pipe, monkeypatch):
    monkeypatch.setenv("FOERDERBERICHT_NUM_CTX", "8192")
    calls = []
    _fake_opener(monkeypatch, {"message": {"content": "x"}, "done_reason": "stop",
                               "prompt_eval_count": 8000, "eval_count": 400}, calls)
    with pytest.raises(PipelineError, match="Kontext erschoepft"):
        pipe._call_llm("p", "ollama", "qwen3:4b")
    _fake_opener(monkeypatch, {"error": "model not found"}, calls)
    with pytest.raises(PipelineError, match="model not found"):
        pipe._call_llm("p", "ollama", "qwen3:4b")
