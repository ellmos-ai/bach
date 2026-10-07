"""Foerderbericht-Pipeline: Modi lokal, cloud, hybrid und Ordnerwaechter."""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from hub._services.document import foerderbericht_modi as modi
from hub._services.document.foerderbericht_watch import (
    WatchState,
    pruefe_eingang,
    watch,
)

ANTWORT = json.dumps({
    "name": "Max Mustermann",
    "geburtsdatum": "15.03.2016",
    "zusammenfassung": "Max zeigt Fortschritte in der Kommunikation.",
    "ziele": [{"ziel": "Kommunikation", "icf": "d350"}],
}, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# Konfiguration
# ─────────────────────────────────────────────────────────────

def test_modus_default_is_cloud(monkeypatch):
    monkeypatch.delenv("BACH_FOERDERBERICHT_MODUS", raising=False)
    assert modi.resolve_modus() == "cloud"


def test_modus_from_env_and_aliases(monkeypatch):
    monkeypatch.setenv("BACH_FOERDERBERICHT_MODUS", "Lokal")
    assert modi.resolve_modus() == "lokal"
    assert modi.resolve_modus("local") == "lokal"
    assert modi.resolve_modus("hybrid") == "hybrid"


def test_unknown_modus_rejected():
    with pytest.raises(modi.ModusFehler, match="Unbekannter Modus"):
        modi.resolve_modus("irgendwas")


def test_context_is_rounded_and_capped(monkeypatch):
    monkeypatch.setenv("BACH_FOERDERBERICHT_MAX_CTX", "16384")
    # Kleinster Wert: Antwortreserve (8192) plus Prompt, auf 4096 gerundet
    assert modi.benoetigter_kontext("") == 8192
    assert modi.benoetigter_kontext("x" * 100) == 12288
    assert modi.benoetigter_kontext("x" * 20000) % 4096 == 0
    with pytest.raises(modi.ModusFehler, match="zu gross"):
        modi.benoetigter_kontext("x" * 60000)


# ─────────────────────────────────────────────────────────────
# Lokales Modell
# ─────────────────────────────────────────────────────────────

class _FakeBackend:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def chat(self, messages, tools=None, think=True, model=None):
        self.calls.append({"messages": messages, "think": think, "model": model})
        return self.result


def test_call_local_llm_returns_content_without_thinking():
    backend = _FakeBackend({"content": " {\"a\": 1} "})
    assert modi.call_local_llm("Prompt", "qwen-test", backend=backend) == '{"a": 1}'
    assert backend.calls[0]["think"] is False
    assert backend.calls[0]["model"] == "qwen-test"


def test_call_local_llm_surfaces_errors_and_empty_answers():
    with pytest.raises(modi.ModusFehler, match="Timeout"):
        modi.call_local_llm("P", "m", backend=_FakeBackend({"content": "", "error": "Timeout"}))
    with pytest.raises(modi.ModusFehler, match="leere Antwort"):
        modi.call_local_llm("P", "m", backend=_FakeBackend({"content": "  "}))


def test_call_local_llm_works_inside_running_event_loop():
    backend = _FakeBackend({"content": "ok"})

    async def inside():
        return modi.call_local_llm("P", "m", backend=backend)

    assert asyncio.run(inside()) == "ok"


# ─────────────────────────────────────────────────────────────
# Hybrid: Strukturdaten und Datenschutz-Sperre
# ─────────────────────────────────────────────────────────────

def test_structure_overview_has_no_filenames():
    from datetime import datetime, timezone
    docs = [
        SimpleNamespace(category=SimpleNamespace(value="core"), doc_type="protokoll",
                        date_hint=datetime(2025, 3, 10, tzinfo=timezone.utc), text_length=1200, size_bytes=0,
                        filename="Protokoll Max Mustermann.docx"),
        SimpleNamespace(category=SimpleNamespace(value="skip"), doc_type="sonstiges",
                        date_hint=None, text_length=0, size_bytes=5, filename="x"),
    ]
    data = modi.struktur_uebersicht(docs, "2025")
    assert data["dokumente"] == [
        {"kategorie": "core", "typ": "protokoll", "monat": "2025-03", "zeichen": 1200}
    ]
    assert "Mustermann" not in json.dumps(data)


def test_draft_metadata_contains_no_values():
    meta = modi.entwurf_metadaten(json.loads(ANTWORT) | {"Max Mustermann": "x"})
    dump = json.dumps(meta, ensure_ascii=False)
    assert "Mustermann" not in dump
    assert "Fortschritte" not in dump
    assert meta["felder"]["zusammenfassung"]["zeichen"] > 0
    assert meta["felder"]["ziele"] == {"typ": "liste", "eintraege": 1}
    assert meta["icf_codes"] == ["d350"]
    assert "<feld>" in meta["felder"]


def test_leak_guard_uses_whole_words():
    begriffe = modi.sensible_begriffe("Ben Mustermann", "15.03.2016")
    modi.pruefe_cloud_nutzlast("Das Kind benötigt Struktur.", begriffe)
    for text in ("Bericht fuer Ben.", "MUSTERMANN", "geb. 15.03.2016"):
        with pytest.raises(modi.ModusFehler, match="Datenschutz-Sperre"):
            modi.pruefe_cloud_nutzlast(text, begriffe)


def _run_hybrid(cloud_answers, local_answers, uebersicht=None):
    cloud_prompts, local_prompts = [], []

    def cloud(prompt):
        cloud_prompts.append(prompt)
        return cloud_answers.pop(0)

    def lokal(prompt):
        local_prompts.append(prompt)
        return local_answers.pop(0)

    result = modi.run_hybrid(
        "AUFTRAG mit Akte von Max Mustermann",
        uebersicht or {"berichtszeitraum": "2025", "dokumente": [{"typ": "hilfeplan"}]},
        modi.sensible_begriffe("Max Mustermann", "15.03.2016"),
        cloud=cloud, lokal=lokal,
    )
    return result, cloud_prompts, local_prompts


def test_hybrid_cloud_plans_and_approves_without_seeing_content():
    result, cloud_prompts, local_prompts = _run_hybrid(
        ["Plan: Hilfeplan fuer Ziele.", "OK"], [ANTWORT]
    )
    assert result == ANTWORT
    assert len(cloud_prompts) == 2 and len(local_prompts) == 1
    assert "Plan: Hilfeplan fuer Ziele." in local_prompts[0]
    assert "AUFTRAG mit Akte" in local_prompts[0]
    for prompt in cloud_prompts:
        assert "Mustermann" not in prompt
        assert "Fortschritte" not in prompt
        assert "AUFTRAG" not in prompt


def test_hybrid_revision_round_uses_cloud_feedback():
    revised = ANTWORT.replace("Fortschritte", "deutliche Fortschritte")
    result, _cloud_prompts, local_prompts = _run_hybrid(
        ["Plan", "1. Zusammenfassung ausbauen."], [ANTWORT, revised]
    )
    assert result == revised
    assert "1. Zusammenfassung ausbauen." in local_prompts[1]


def test_hybrid_keeps_draft_when_revision_is_not_json():
    result, _, _ = _run_hybrid(["Plan", "1. mehr"], [ANTWORT, "kein json"])
    assert result == ANTWORT


def test_hybrid_aborts_before_cloud_call_on_leak():
    with pytest.raises(modi.ModusFehler, match="Datenschutz-Sperre"):
        _run_hybrid(["Plan"], [ANTWORT], uebersicht={"notiz": "Max Mustermann"})


# ─────────────────────────────────────────────────────────────
# Pipeline (echte Dienste, Modelle gefaelscht)
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def berichte(tmp_path):
    akte = tmp_path / "Berichte" / "data_roh" / "Mustermann, Max"
    akte.mkdir(parents=True)
    (akte / "Aktendeckblatt.txt").write_text(
        "Aktendeckblatt\nName: Max Mustermann\nGeburtsdatum: 15.03.2016\n", encoding="utf-8")
    (akte / "Protokoll_2025-03-10.txt").write_text(
        "Protokoll\nMax Mustermann arbeitete konzentriert an seinen Zielen.\n" * 10,
        encoding="utf-8")
    (akte / "Hilfeplan_2025.txt").write_text(
        "Hilfeplan\nZiel: soziale Interaktion in Kleingruppen.\n", encoding="utf-8")
    return tmp_path / "Berichte"


def _pipeline(base):
    from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline
    return FoerderberichtPipeline(base_path=base)


def test_prepare_lokal_keeps_real_names_out_of_cloud_prompt_file(berichte):
    result = _pipeline(berichte).prepare_prompt(modus="lokal")
    assert result.success, result.error
    assert result.modus == "lokal"
    assert result.output_path.name == "prompt_lokal.txt"
    prompt = result.output_path.read_text(encoding="utf-8")
    assert "Mustermann" in prompt
    assert "anonymisiert" not in prompt.lower()
    bundled = berichte / "data_bundled"
    assert not (bundled / "prompt.txt").exists()
    assert not any((berichte / "data_ano").iterdir())
    info = json.loads((bundled / "session_info.json").read_text(encoding="utf-8"))
    assert info["modus"] == "lokal" and info["mappings"] == {}


def test_prepare_cloud_still_anonymizes(berichte):
    result = _pipeline(berichte).prepare_prompt(modus="cloud")
    assert result.success, result.error
    assert result.output_path.name == "prompt.txt"
    assert "Mustermann" not in result.output_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("modus", ["lokal", "hybrid"])
def test_full_run_local_modes_never_send_names_to_cloud(berichte, modus):
    from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline

    cloud_prompts, local_prompts = [], []

    def fake_cloud(self, prompt, backend, model):
        cloud_prompts.append(prompt)
        return "OK" if "Metadaten" in prompt else "Plan: Hilfeplan fuer Ziele."

    def fake_local(prompt, model=None, system=None, backend=None):
        local_prompts.append(prompt)
        return "```json\n" + ANTWORT + "\n```"

    with patch.object(FoerderberichtPipeline, "_call_llm", fake_cloud), \
         patch.object(modi, "call_local_llm", fake_local):
        result = _pipeline(berichte).run_full_pipeline(modus=modus)

    assert result.success, result.error
    assert result.modus == modus
    assert any(berichte.joinpath("output_berichte").iterdir())
    assert local_prompts and "Mustermann" in local_prompts[0]
    if modus == "lokal":
        assert cloud_prompts == []
    else:
        assert len(cloud_prompts) == 2
    for prompt in cloud_prompts:
        assert "Mustermann" not in prompt
        assert "15.03.2016" not in prompt
    assert not (berichte / ".pipeline_lock").exists()


def test_full_run_cloud_mode_uses_cloud_model_only(berichte):
    from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline

    cloud_prompts = []

    def fake_cloud(self, prompt, backend, model):
        cloud_prompts.append(prompt)
        return ANTWORT

    def no_local(*_a, **_k):
        raise AssertionError("cloud-Modus darf das lokale Modell nicht rufen")

    with patch.object(FoerderberichtPipeline, "_call_llm", fake_cloud), \
         patch.object(modi, "call_local_llm", no_local):
        result = _pipeline(berichte).run_full_pipeline(modus="cloud")

    assert result.success, result.error
    assert len(cloud_prompts) == 1
    assert "Mustermann" not in cloud_prompts[0]


# ─────────────────────────────────────────────────────────────
# Ordnerwaechter
# ─────────────────────────────────────────────────────────────

def test_watch_waits_until_case_file_is_quiet(berichte):
    state = WatchState()
    starten, grund = pruefe_eingang(berichte, state, ruhe_s=3600)
    assert not starten and grund == "Akte wird noch kopiert"
    starten, grund = pruefe_eingang(berichte, state, ruhe_s=0)
    assert starten, grund


def test_watch_refuses_multiple_client_folders_and_lock(berichte):
    (berichte / "data_roh" / "Zweiter, Klient").mkdir()
    starten, grund = pruefe_eingang(berichte, WatchState(), ruhe_s=0)
    assert not starten and "2 Klienten-Ordner" in grund
    shutil.rmtree(berichte / "data_roh" / "Zweiter, Klient")
    (berichte / ".pipeline_lock").write_text("x")
    assert pruefe_eingang(berichte, WatchState(), ruhe_s=0) == (False, "Pipeline laeuft bereits")


def test_watch_detects_change_between_checks(berichte):
    state = WatchState()
    pruefe_eingang(berichte, state, ruhe_s=3600)
    (berichte / "data_roh" / "Mustermann, Max" / "Neu.txt").write_text("neu", encoding="utf-8")
    starten, grund = pruefe_eingang(berichte, state, ruhe_s=0)
    assert not starten and "veraendert" in grund


class _FakePipeline:
    runs = []

    def __init__(self, base, success=True):
        self.base_path = base
        self.success = success

    def run_full_pipeline(self, **kwargs):
        _FakePipeline.runs.append(kwargs)
        if self.success:
            shutil.rmtree(self.base_path / "data_roh")
            (self.base_path / "data_roh").mkdir()
        return SimpleNamespace(success=self.success, error="kaputt",
                               output_path=self.base_path / "Foerderbericht_Max Mustermann.docx")


def test_watch_once_runs_pipeline_and_hides_filename(berichte):
    _FakePipeline.runs = []
    meldungen = []
    erstellt = watch(lambda: _FakePipeline(berichte), modus="lokal", ruhe_s=0,
                     once=True, melden=meldungen.append,
                     pipeline_kwargs={"berichtszeitraum": "2026"})
    assert erstellt == 1
    assert _FakePipeline.runs == [{"modus": "lokal", "berichtszeitraum": "2026"}]
    assert not any("Mustermann" in m for m in meldungen)


def test_watch_does_not_retry_unchanged_failed_case_file(berichte):
    _FakePipeline.runs = []
    erstellt = watch(lambda: _FakePipeline(berichte, success=False), modus="lokal",
                     ruhe_s=0, melden=lambda _m: None, sleep=lambda _s: None,
                     max_laeufe=1)
    assert erstellt == 0
    # Zweiter Waechter-Durchlauf mit demselben Zustand: kein neuer Versuch
    state = WatchState()
    from hub._services.document.foerderbericht_watch import fingerabdruck
    state.fehlgeschlagen.add(fingerabdruck(berichte / "data_roh"))
    starten, grund = pruefe_eingang(berichte, state, ruhe_s=0)
    assert not starten and "fehlgeschlagenem Lauf" in grund


# ─────────────────────────────────────────────────────────────
# Chat-Werkzeug und CLI
# ─────────────────────────────────────────────────────────────

class _RecordingPipeline:
    calls = []

    def __init__(self, base_path=None):
        self.base_path = base_path or Path("/nirgendwo")

    def _result(self, modus):
        return SimpleNamespace(
            success=True, modus=modus, duration_s=1.0, tarnname="Tarn",
            steps_completed=["bericht: erstellt"], error="",
            output_path=Path("/geheim/Foerderbericht_Max Mustermann.docx"),
        )

    def run_full_pipeline(self, **kwargs):
        _RecordingPipeline.calls.append(("run", kwargs))
        return self._result(kwargs.get("modus") or "cloud")

    def prepare_prompt(self, **kwargs):
        _RecordingPipeline.calls.append(("prepare", kwargs))
        return self._result(kwargs.get("modus"))

    def finish_report(self, **kwargs):
        _RecordingPipeline.calls.append(("finish", kwargs))
        return self._result("cloud")


def _with_recording_pipeline():
    import sys
    _RecordingPipeline.calls = []
    module = SimpleNamespace(FoerderberichtPipeline=_RecordingPipeline)
    return patch.dict(sys.modules, {"hub._services.document.foerderbericht_pipeline": module})


def test_chat_tool_run_passes_modus_and_hides_filename():
    from hub._services.chat.bach_tools import exec_tool
    with _with_recording_pipeline():
        out = exec_tool("foerderbericht", {"action": "run", "modus": "hybrid"}, "safe")
    assert _RecordingPipeline.calls[0][0] == "run"
    assert _RecordingPipeline.calls[0][1]["modus"] == "hybrid"
    assert "Modus hybrid" in out
    assert "Mustermann" not in out and "/geheim" not in out


def test_chat_tool_prepare_is_always_anonymized(monkeypatch):
    from hub._services.chat.bach_tools import exec_tool
    monkeypatch.setenv("BACH_FOERDERBERICHT_MODUS", "lokal")
    with _with_recording_pipeline():
        exec_tool("foerderbericht", {"action": "prepare"}, "safe")
    assert _RecordingPipeline.calls[0] == ("prepare", _RecordingPipeline.calls[0][1])
    assert _RecordingPipeline.calls[0][1]["modus"] == "cloud"


def test_chat_tool_finish_hides_filename():
    from hub._services.chat.bach_tools import exec_tool
    with _with_recording_pipeline():
        out = exec_tool("foerderbericht", {"action": "finish"}, "safe")
    assert _RecordingPipeline.calls[0][0] == "finish"
    assert "Bericht erstellt in output_berichte/" in out
    assert "Mustermann" not in out


def test_cli_pipeline_passes_modus_and_local_model(tmp_path):
    from hub.bericht import BerichtHandler
    with _with_recording_pipeline():
        ok, msg = BerichtHandler(tmp_path).handle(
            "pipeline", ["--modus", "lokal", "--lokal-modell", "llama-test"])
    assert ok, msg
    kwargs = _RecordingPipeline.calls[0][1]
    assert kwargs["modus"] == "lokal" and kwargs["lokal_modell"] == "llama-test"
    assert "Modus: lokal" in msg
    assert "Tarnname" not in msg and "Mustermann" not in msg


def test_cli_watch_once_forwards_options(tmp_path, monkeypatch):
    from hub.bericht import BerichtHandler
    seen = {}

    def fake_watch(factory, **kwargs):
        seen.update(kwargs)
        return 1

    import hub._services.document.foerderbericht_watch as watch_mod
    monkeypatch.setattr(watch_mod, "watch", fake_watch)
    with _with_recording_pipeline():
        ok, msg = BerichtHandler(tmp_path).handle(
            "watch", ["--once", "--modus", "hybrid", "--ruhe", "5",
                      "--zeitraum", "01.01.2026 - 31.12.2026"])
    assert ok, msg
    assert seen["once"] is True and seen["modus"] == "hybrid" and seen["ruhe_s"] == 5.0
    assert seen["pipeline_kwargs"] == {"berichtszeitraum": "01.01.2026 - 31.12.2026"}
    assert "Berichte erstellt: 1" in msg
