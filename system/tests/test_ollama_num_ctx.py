# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer die num_ctx-Konfiguration je Ollama-Modell.

Deckt ab:
- ``OllamaClient``: Default, ENV-Override, Fallback und Validierung von num_ctx
- ``hub.ollama``: Persistenz der num_ctx-Konfiguration und CLI-Pfad
- ``local_resource_reserve``: externer Kontext-Faktor und Budget-Konflikt
"""

import asyncio
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import pytest

from tools.ollama.ollama_client import DEFAULT_NUM_CTX, OllamaClient

from hub._services.chat import local_resource_reserve as lrr
from hub.ollama import OllamaHandler


@pytest.fixture(autouse=True)
def _clean_num_ctx_env(monkeypatch):
    """Entfernt num_ctx-Umgebungsvariablen fuer deterministische Tests."""
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)


# ---------------------------------------------------------------------------
# OllamaClient: num_ctx-Aufloesung
# ---------------------------------------------------------------------------


def test_default_num_ctx_ohne_umgebung():
    """Ohne ENV und ohne Argument gilt DEFAULT_NUM_CTX."""
    assert DEFAULT_NUM_CTX == 4096
    client = OllamaClient()
    assert client.num_ctx == DEFAULT_NUM_CTX


def test_num_ctx_override_ueber_env(monkeypatch):
    """OLLAMA_NUM_CTX hat Vorrang vor dem Default."""
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    client = OllamaClient()
    assert client.num_ctx == 8192


def test_num_ctx_fallback_ueber_cfg_env(monkeypatch):
    """OLLAMA_NUM_CFG dient als Fallback, wenn OLLAMA_NUM_CTX fehlt."""
    monkeypatch.setenv("OLLAMA_NUM_CFG", "2048")
    client = OllamaClient()
    assert client.num_ctx == 2048


def test_num_ctx_argument_hat_vorrang_vor_env(monkeypatch):
    """Ein explizites Argument schlaegt jede Umgebungsvariable."""
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    client = OllamaClient(num_ctx=16384)
    assert client.num_ctx == 16384


@pytest.mark.parametrize("wert", ["keine-zahl", "12.5", ""])
def test_num_ctx_nicht_ganzzahlig_wirft_value_error(monkeypatch, wert):
    """Nicht-ganzzahlige Werte werden mit klarer Meldung abgewiesen."""
    monkeypatch.setenv("OLLAMA_NUM_CTX", wert)
    with pytest.raises(ValueError, match="ganze Zahl"):
        OllamaClient()


@pytest.mark.parametrize("wert", [0, 511, 262145, 1_000_000])
def test_num_ctx_ausserhalb_bereich_wirft_value_error(wert):
    """Werte ausserhalb 512..262144 werden abgewiesen."""
    with pytest.raises(ValueError, match="512 und 262144"):
        OllamaClient(num_ctx=wert)


@pytest.mark.parametrize("wert", [512, 4096, 262144])
def test_num_ctx_grenzwerte_sind_erlaubt(wert):
    """Die Bereichsgrenzen selbst sind gueltig."""
    client = OllamaClient(num_ctx=wert)
    assert client.num_ctx == wert


# ---------------------------------------------------------------------------
# OllamaHandler: Persistenz je Modell
# ---------------------------------------------------------------------------


@pytest.fixture()
def handler(tmp_path):
    """Frischer OllamaHandler ohne Seiteneffekte (BaseHandler legt nichts an)."""
    return OllamaHandler(tmp_path)


def test_load_num_ctx_config_ohne_datei(handler):
    """Fehlende Konfigurationsdatei ergibt eine leere Konfiguration."""
    assert not handler.target_file.exists()
    assert handler._load_num_ctx_config() == {}


def test_load_num_ctx_config_mit_kaputtem_json(handler):
    """Unlesbares JSON wird als leere Konfiguration behandelt."""
    handler.target_file.parent.mkdir(parents=True, exist_ok=True)
    handler.target_file.write_text("{", encoding="utf-8")
    assert handler._load_num_ctx_config() == {}


def test_load_num_ctx_config_mit_nicht_dict_json(handler):
    """Gueltiges JSON ohne Objekt-Struktur wird verworfen."""
    handler.target_file.parent.mkdir(parents=True, exist_ok=True)
    handler.target_file.write_text("[]", encoding="utf-8")
    assert handler._load_num_ctx_config() == {}


def test_load_num_ctx_config_liest_bestand(handler):
    """Eine vorhandene Konfiguration wird unveraendert gelesen."""
    handler.target_file.parent.mkdir(parents=True, exist_ok=True)
    bestand = {"models": {"m": {"num_ctx": 2048}}}
    handler.target_file.write_text(json.dumps(bestand), encoding="utf-8")
    assert handler._load_num_ctx_config() == bestand


def test_set_num_ctx_persistiert_je_modell(handler):
    """set_num_ctx schreibt den Wert unter models/<modell>/num_ctx."""
    ok, text = handler.set_num_ctx("m", num_ctx=8192)
    assert ok is True
    assert text == "Ollama num_ctx fuer 'm' gespeichert: num_ctx=8192"
    gespeichert = json.loads(handler.target_file.read_text(encoding="utf-8"))
    assert gespeichert == {"models": {"m": {"num_ctx": 8192}}}


def test_set_num_ctx_legt_data_ordner_an(tmp_path):
    """Fehlendes data/-Verzeichnis wird beim Schreiben erzeugt."""
    handler = OllamaHandler(tmp_path)
    data_dir = tmp_path / "data"
    assert not data_dir.exists()
    ok, _ = handler.set_num_ctx("m", num_ctx=4096)
    assert ok is True
    assert data_dir.is_dir()


def test_set_num_ctx_schreibt_beide_werte(handler):
    """num_ctx und num_ctx_recommended werden gemeinsam gemeldet und behalten."""
    ok, text = handler.set_num_ctx("m", num_ctx=8192, num_ctx_recommended=16384)
    assert ok is True
    assert text == (
        "Ollama num_ctx fuer 'm' gespeichert: "
        "num_ctx=8192, num_ctx_recommended=16384"
    )
    gespeichert = json.loads(handler.target_file.read_text(encoding="utf-8"))
    assert gespeichert["models"]["m"] == {
        "num_ctx": 8192,
        "num_ctx_recommended": 16384,
    }


def test_set_num_ctx_erhaelt_andere_modelle(handler):
    """Ein weiteres Modell ueberschreibt bestehende Eintraege nicht."""
    handler.set_num_ctx("a", num_ctx=2048)
    handler.set_num_ctx("b", num_ctx=8192)
    gespeichert = json.loads(handler.target_file.read_text(encoding="utf-8"))
    assert gespeichert["models"]["a"] == {"num_ctx": 2048}
    assert gespeichert["models"]["b"] == {"num_ctx": 8192}


def test_set_num_ctx_ohne_modell(handler):
    """Ein leeres Modell wird abgewiesen und schreibt nichts."""
    ok, text = handler.set_num_ctx("")
    assert ok is False
    assert text == "Fehler: Ollama set_num_ctx benoetigt ein Modell"
    assert not handler.target_file.exists()


# ---------------------------------------------------------------------------
# OllamaHandler: CLI-Pfad _set_num_ctx
# ---------------------------------------------------------------------------


def test_cli_ohne_argumente(handler):
    """Ohne Argumente nennt die Meldung Modell und Usage."""
    ok, text = handler._set_num_ctx([])
    assert ok is False
    assert text.startswith(
        "Fehler: Ollama set_num_ctx benoetigt ein Modell\n"
        "Usage: ollama set_num_ctx <modell> "
    )


def test_cli_ohne_flags(handler):
    """Mit Modell, aber ohne Flags, wird die Flag-Usage gemeldet."""
    ok, text = handler._set_num_ctx(["m"])
    assert ok is False
    assert text.startswith(
        "Fehler: Ollama set_num_ctx benoetigt --num-ctx oder --num-ctx-recommended\n"
    )


def test_cli_num_ctx_keine_zahl(handler):
    """Nicht-ganzzahliges --num-ctx wird abgewiesen."""
    ok, text = handler._set_num_ctx(["m", "--num-ctx=abc"])
    assert ok is False
    assert text == "Fehler: Ollama num_ctx muss eine ganze Zahl sein"


def test_cli_num_ctx_recommended_keine_zahl(handler):
    """Nicht-ganzzahliges --num-ctx-recommended wird abgewiesen."""
    ok, text = handler._set_num_ctx(["m", "--num-ctx-recommended=abc"])
    assert ok is False
    assert text == "Fehler: Ollama num_ctx_recommended muss eine ganze Zahl sein"


@pytest.mark.parametrize(
    "flag", ["--num-ctx=100", "--num-ctx-recommended=100"]
)
def test_cli_bereich_wird_geprueft(handler, flag):
    """Werte unterhalb 512 werden fuer beide Flags abgewiesen."""
    ok, text = handler._set_num_ctx(["m", flag])
    assert ok is False
    assert text == "Fehler: Ollama num_ctx muss zwischen 512 und 262144 liegen"
    assert not handler.target_file.exists()


def test_cli_dry_run_schreibt_nicht(handler):
    """dry_run meldet die Absicht und laesst die Datei unberuehrt."""
    ok, text = handler._set_num_ctx(["m", "--num-ctx=8192"], dry_run=True)
    assert ok is True
    assert text == "[DRY-RUN] Wuerde Ollama num_ctx fuer 'm' setzen: num_ctx=8192"
    assert not handler.target_file.exists()


def test_cli_ohne_dry_run_persistiert(handler):
    """Ohne dry_run delegiert die CLI an set_num_ctx und persisteirt."""
    ok, text = handler._set_num_ctx(["m", "--num-ctx=8192"])
    assert ok is True
    assert text == "Ollama num_ctx fuer 'm' gespeichert: num_ctx=8192"
    gespeichert = json.loads(handler.target_file.read_text(encoding="utf-8"))
    assert gespeichert == {"models": {"m": {"num_ctx": 8192}}}


# ---------------------------------------------------------------------------
# local_resource_reserve: externer Kontext-Faktor und Budget-Konflikt
# ---------------------------------------------------------------------------


def _policy(**overrides):
    """Minimale, strukturell gueltige Reserve-Policy fuer probe()."""
    policy = {
        "schema": lrr.SCHEMA,
        "enabled": True,
        "wait_seconds": 30,
        "poll_seconds": 2,
        "memory_reserve_bytes": 1024**3,
        "models": {
            "m": {
                "digest": "a" * 64,
                "weight_budget_bytes": 4 * 1024**3,
                "kv_headroom_bytes": 512 * 1024**2,
                "overhead_bytes": 256 * 1024**2,
                "num_ctx": 8192,
            }
        },
    }
    policy.update(overrides)
    return policy


def _observed(**overrides):
    """Beobachtung eines lokalen Modells, passend zu _policy()."""
    observed = {
        "external": False,
        "digest": "a" * 64,
        "weight_floor_bytes": 1024**3,
        "resident_context": None,
    }
    observed.update(overrides)
    return observed


def _patch_ollama_backend(monkeypatch):
    """Erzwingt backend_identifier() == 'ollama' fuer beliebige Backends."""
    from hub._services.llm import model_backend

    monkeypatch.setattr(model_backend, "backend_identifier", lambda backend: "ollama")


def _patch_observation(monkeypatch, observed):
    async def _fake_observe(backend, model):
        return observed

    monkeypatch.setattr(lrr, "observe_ollama", _fake_observe)


def test_external_context_factor_ist_0_8():
    """Der externe Handoff-Threshold nutzt 80 Prozent des num_ctx."""
    assert lrr.EXTERNAL_CONTEXT_FACTOR == 0.8


def test_decision_hat_feste_huelle():
    """_decision liefert die stabile Empfangshuelle inklusive Zeitstempel."""
    receipt = lrr._decision("ready", admitted=True, enforced=False, extra_feld=7)
    assert receipt["schema"] == lrr.SCHEMA
    assert receipt["state"] == "ready"
    assert receipt["admitted"] is True
    assert receipt["enforced"] is False
    assert receipt["retryable"] is False
    assert receipt["extra_feld"] == 7
    assert datetime.fromisoformat(receipt["checked_at"]) is not None


def test_probe_ohne_policy_ist_nicht_konfiguriert(monkeypatch):
    """Ohne Reserve-Policy wird der Aufruf zugelassen, aber nicht erzwungen."""
    monkeypatch.setattr(lrr, "read_policy", lambda: (None, None))
    receipt = asyncio.run(lrr.probe(types.SimpleNamespace(num_ctx=8192), "m"))
    assert receipt["state"] == "not_configured"
    assert receipt["admitted"] is True
    assert receipt["enforced"] is False


def test_probe_mit_kaputter_policy_ist_invalid(monkeypatch):
    """Ein Lesefehler der Policy wird als invalid_policy gemeldet."""
    def _raise():
        raise OSError("policy weg")

    monkeypatch.setattr(lrr, "read_policy", _raise)
    receipt = asyncio.run(lrr.probe(types.SimpleNamespace(num_ctx=8192), "m"))
    assert receipt["state"] == "invalid_policy"
    assert receipt["admitted"] is False


def test_probe_externes_ziel_leitet_schwelle_aus_num_ctx_ab(monkeypatch):
    """Bei externem Backend gilt int(num_ctx * 0.8) als Handoff-Schwelle."""
    monkeypatch.setattr(lrr, "read_policy", lambda: (_policy(), "b" * 64))
    _patch_ollama_backend(monkeypatch)
    _patch_observation(monkeypatch, _observed(external=True))
    receipt = asyncio.run(lrr.probe(types.SimpleNamespace(num_ctx=8192), "m"))
    assert receipt["state"] == "external_target"
    assert receipt["admitted"] is True
    assert receipt["enforced"] is False
    assert receipt["handoff_context_threshold"] == int(8192 * 0.8) == 6553
    assert receipt["policy_version"] == "b" * 64


def test_probe_externes_ziel_ohne_num_ctx_hat_keine_schwelle(monkeypatch):
    """Ohne bekanntes num_ctx bleibt der Handoff-Threshold offen."""
    monkeypatch.setattr(lrr, "read_policy", lambda: (_policy(), "b" * 64))
    _patch_ollama_backend(monkeypatch)
    _patch_observation(monkeypatch, _observed(external=True))
    receipt = asyncio.run(lrr.probe(types.SimpleNamespace(), "m"))
    assert receipt["state"] == "external_target"
    assert receipt["handoff_context_threshold"] is None


def test_probe_budget_konflikt_bei_abweichendem_num_ctx(monkeypatch):
    """Ein anderes num_ctx als im Budget beobachtet wird zum Konflikt."""
    monkeypatch.setattr(lrr, "read_policy", lambda: (_policy(), "b" * 64))
    _patch_ollama_backend(monkeypatch)
    _patch_observation(monkeypatch, _observed())
    receipt = asyncio.run(lrr.probe(types.SimpleNamespace(num_ctx=4096), "m"))
    assert receipt["state"] == "model_budget_conflict"
    assert receipt["admitted"] is False
    assert receipt["model"] == "m"


def test_probe_budget_konflikt_bei_abweichendem_digest(monkeypatch):
    """Ein abweichender Modell-Digest wird ebenfalls zum Konflikt."""
    monkeypatch.setattr(lrr, "read_policy", lambda: (_policy(), "b" * 64))
    _patch_ollama_backend(monkeypatch)
    _patch_observation(monkeypatch, _observed(digest="c" * 64))
    receipt = asyncio.run(lrr.probe(types.SimpleNamespace(num_ctx=8192), "m"))
    assert receipt["state"] == "model_budget_conflict"


def test_probe_unbekanntes_modell(monkeypatch):
    """Ein Modell ohne Budget wird als missing_model_budget gemeldet."""
    monkeypatch.setattr(lrr, "read_policy", lambda: (_policy(), "b" * 64))
    _patch_ollama_backend(monkeypatch)
    _patch_observation(monkeypatch, _observed())
    receipt = asyncio.run(lrr.probe(types.SimpleNamespace(num_ctx=8192), "unbekannt"))
    assert receipt["state"] == "missing_model_budget"
    assert receipt["admitted"] is False
