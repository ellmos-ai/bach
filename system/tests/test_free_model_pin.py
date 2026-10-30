"""Tests fuer das Per-Lauf-Pinning eines tool-faehigen freien OpenRouter-Modells.

Geprueft wird ausschliesslich die Entscheidungslogik von
``hub._services.llm.free_model_pin``: Determinismus pro Lauf, Rotation zwischen
Laeufen, Ausschluss des Provider-Routers aus dem Rotationspool und der
Rueckfall auf ``openrouter/free``.  Kataloge werden als reine dicts uebergeben,
es findet kein Netzzugriff statt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm import free_model_pin as pin  # noqa: E402
from hub._services.llm.openrouter_catalog import FREE_ROUTER_ID  # noqa: E402


def _catalog(*model_ids: str, stale: bool = False, failure_code=None) -> dict:
    """Baut einen Katalog-Snapshot im Format von get_openrouter_catalog()."""
    models = [
        {"id": model_id, "name": model_id, "free": True, "kind": "model"}
        for model_id in model_ids
    ]
    catalog = {
        "models": models,
        "source": "openrouter_models_api",
        "stale": stale,
        "observed_at": "2026-10-30T00:00:00+00:00",
    }
    if failure_code is not None:
        catalog["failure_code"] = failure_code
    return catalog


ROUTER_RECORD = {
    "id": FREE_ROUTER_ID,
    "name": "Auto Router",
    "free": True,
    "kind": "provider_router",
}


def test_fallback_id_is_openrouter_free():
    assert FREE_ROUTER_ID == "openrouter/free"
    assert pin.FALLBACK_REASONS == (
        "run_id_missing",
        "catalog_stale",
        "no_free_candidates",
    )


def test_same_run_id_pins_same_model():
    catalog = _catalog("gamma:free", "alpha:free", "beta:free")
    first = pin.pick_free_model("run-42", catalog=catalog)
    second = pin.pick_free_model("run-42", catalog=catalog)
    assert first["model"] == second["model"]
    assert first["rotation_index"] == second["rotation_index"]
    assert first["pinned"] is True
    assert first["fallback"] is False
    assert first["reason"] is None


def test_pinned_model_is_member_of_candidates():
    catalog = _catalog("gamma:free", "alpha:free", "beta:free")
    result = pin.pick_free_model("run-42", catalog=catalog)
    assert result["model"] in result["candidates"]
    assert len(result["candidates"]) == 3


def test_candidates_are_sorted_deterministically():
    catalog = _catalog("Gamma:free", "alpha:free", "beta:free", "Beta:free")
    candidates = pin.free_candidates(catalog)
    assert candidates == sorted(candidates, key=lambda item: (item.casefold(), item))
    assert candidates[0] == "alpha:free"


def test_runs_rotate_over_candidate_pool():
    catalog = _catalog("alpha:free", "beta:free", "gamma:free")
    chosen = {
        pin.pinned_model(f"run-{index}", catalog=catalog) for index in range(12)
    }
    assert len(chosen) > 1
    assert chosen <= set(pin.free_candidates(catalog))


def test_router_is_never_a_rotation_member():
    catalog = _catalog("alpha:free", "beta:free", "gamma:free")
    catalog["models"].append(dict(ROUTER_RECORD))
    candidates = pin.free_candidates(catalog)
    assert FREE_ROUTER_ID not in candidates
    assert len(candidates) == 3
    for index in range(12):
        assert pin.pinned_model(f"run-{index}", catalog=catalog) != FREE_ROUTER_ID


def test_stale_catalog_falls_back_to_router_with_failure_code():
    catalog = _catalog(
        "alpha:free", "beta:free", stale=True, failure_code="catalog_timeout"
    )
    result = pin.pick_free_model("run-7", catalog=catalog)
    assert result["model"] == "openrouter/free"
    assert result["fallback"] is True
    assert result["pinned"] is False
    assert result["reason"] == "catalog_timeout"
    assert result["stale"] is True
    assert result["rotation_index"] is None


def test_stale_catalog_without_failure_code_uses_catalog_stale():
    catalog = _catalog("alpha:free", stale=True)
    result = pin.pick_free_model("run-7", catalog=catalog)
    assert result["model"] == "openrouter/free"
    assert result["reason"] == "catalog_stale"


def test_empty_pool_falls_back_to_router():
    result = pin.pick_free_model("run-9", catalog=_catalog())
    assert result["model"] == "openrouter/free"
    assert result["fallback"] is True
    assert result["reason"] == "no_free_candidates"
    assert result["candidates"] == []


def test_router_only_catalog_falls_back_to_router():
    catalog = {"models": [dict(ROUTER_RECORD)], "source": "cache", "stale": False}
    result = pin.pick_free_model("run-9", catalog=catalog)
    assert result["model"] == "openrouter/free"
    assert result["reason"] == "no_free_candidates"


@pytest.mark.parametrize("run_id", [None, "", "   "])
def test_missing_run_id_falls_back_to_router(run_id):
    catalog = _catalog("alpha:free", "beta:free", "gamma:free")
    result = pin.pick_free_model(run_id, catalog=catalog)
    assert result["model"] == "openrouter/free"
    assert result["fallback"] is True
    assert result["pinned"] is False
    assert result["reason"] == "run_id_missing"


def test_tool_capable_only_false_keeps_free_models_without_kind():
    catalog = {
        "models": [
            {"id": "alpha:free", "name": "alpha", "free": True, "kind": "model"},
            {"id": "delta:free", "name": "delta", "free": False},
            dict(ROUTER_RECORD),
        ],
        "source": "cache",
        "stale": False,
    }
    strict = pin.free_candidates(catalog, tool_capable_only=True)
    loose = pin.free_candidates(catalog, tool_capable_only=False)
    assert strict == ["alpha:free"]
    assert loose == ["alpha:free", "delta:free"]


def test_rotation_index_is_bounded_and_salted():
    size = 5
    for run_id in ("run-1", "run-2", "run-3"):
        index = pin.rotation_index(run_id, size)
        assert isinstance(index, int)
        assert 0 <= index < size
    assert pin.rotation_index("run-1", size) == pin.rotation_index("run-1", size)
    assert pin.rotation_index("run-1", size) != size


def test_rotation_index_rejects_empty_pool():
    with pytest.raises(ValueError):
        pin.rotation_index("run-1", 0)


def test_pick_uses_cached_catalog_when_none_given(monkeypatch):
    catalog = _catalog("alpha:free", "beta:free", "gamma:free")
    calls = []

    def fake_get_openrouter_catalog(**kwargs):
        calls.append(kwargs)
        return catalog

    monkeypatch.setattr(pin, "get_openrouter_catalog", fake_get_openrouter_catalog)
    result = pin.pick_free_model("run-11")
    assert calls == [{}]
    assert result["pinned"] is True
    assert result["model"] in pin.free_candidates(catalog)


def test_pick_tolerates_non_mapping_catalog(monkeypatch):
    monkeypatch.setattr(pin, "get_openrouter_catalog", lambda **kwargs: "kaputt")
    result = pin.pick_free_model("run-12")
    assert result["model"] == "openrouter/free"
    assert result["reason"] == "no_free_candidates"


# ---------------------------------------------------------------------------
# Integration: OpenRouterBackend pinnt ein freies Modell pro Lauf
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

from hub._services.llm import model_backend as mb  # noqa: E402
from hub._services.llm.model_backend import (  # noqa: E402
    HermesBackend,
    OpenRouterBackend,
    backend_identifier,
    create_backend,
)


def _selection_catalog(*model_ids: str, stale: bool = False, failure_code=None) -> dict:
    catalog = _catalog(*model_ids, stale=stale, failure_code=failure_code)
    catalog["selection"] = {"allowed": True, "reason": "model_free"}
    return catalog


def _install_catalog(monkeypatch, catalog):
    def fake_get_openrouter_catalog(**kwargs):
        return catalog

    monkeypatch.setattr(pin, "get_openrouter_catalog", fake_get_openrouter_catalog)
    monkeypatch.setattr(
        "hub._services.llm.openrouter_catalog.get_openrouter_catalog",
        fake_get_openrouter_catalog,
    )


def _install_super_chat(monkeypatch, captured):
    async def fake_chat(self, messages, tools=None, think=True, model=None, *, retry_transient=True):
        captured.append(model)
        return {"content": "ok", "tool_calls": None}

    monkeypatch.setattr(mb.HermesBackend, "chat", fake_chat)


def _chat_once(backend, model=None):
    return asyncio.run(
        backend.chat([{"role": "user", "content": "hi"}], model=model)
    )


def test_backend_pins_same_model_across_calls_in_one_run(monkeypatch):
    catalog = _selection_catalog("alpha:free", "beta:free", "gamma:free")
    _install_catalog(monkeypatch, catalog)
    captured = []
    _install_super_chat(monkeypatch, captured)

    backend = OpenRouterBackend(api_key="testkey", run_id="run-42")
    assert _chat_once(backend) == {"content": "ok", "tool_calls": None}
    _chat_once(backend)

    assert len(captured) == 2
    assert captured[0] == captured[1]
    assert captured[0] in pin.free_candidates(catalog)
    assert captured[0] != FREE_ROUTER_ID
    assert backend.last_free_pin_decision["pinned"] is True
    assert backend.last_resolved_model == captured[0]


def test_backend_rotates_model_between_runs(monkeypatch):
    catalog = _selection_catalog("alpha:free", "beta:free", "gamma:free")
    _install_catalog(monkeypatch, catalog)

    chosen = set()
    expected = set()
    for index in range(8):
        captured = []
        _install_super_chat(monkeypatch, captured)
        backend = OpenRouterBackend(api_key="testkey", run_id=f"run-{index}")
        _chat_once(backend)
        chosen.add(captured[0])
        expected.add(pin.pinned_model(f"run-{index}", catalog=catalog))

    assert chosen == expected
    assert len(chosen) > 1
    assert chosen <= set(pin.free_candidates(catalog))


def test_backend_without_run_id_keeps_router_id(monkeypatch):
    catalog = _selection_catalog("alpha:free", "beta:free")
    _install_catalog(monkeypatch, catalog)
    captured = []
    _install_super_chat(monkeypatch, captured)

    backend = OpenRouterBackend(api_key="testkey")
    _chat_once(backend)

    assert captured == [FREE_ROUTER_ID]
    assert backend.last_free_pin_decision["pinned"] is False
    assert backend.last_free_pin_decision["reason"] == "run_id_missing"
    assert backend.last_resolved_model == FREE_ROUTER_ID


def test_backend_with_stale_catalog_falls_back_to_router(monkeypatch):
    catalog = _selection_catalog("alpha:free", stale=True, failure_code="catalog_timeout")
    _install_catalog(monkeypatch, catalog)
    captured = []
    _install_super_chat(monkeypatch, captured)

    backend = OpenRouterBackend(api_key="testkey", run_id="run-7")
    _chat_once(backend)

    assert captured == [FREE_ROUTER_ID]
    assert backend.last_free_pin_decision["reason"] == "catalog_timeout"


def test_backend_with_empty_pool_falls_back_to_router(monkeypatch):
    catalog = _selection_catalog(stale=False)
    _install_catalog(monkeypatch, catalog)
    captured = []
    _install_super_chat(monkeypatch, captured)

    backend = OpenRouterBackend(api_key="testkey", run_id="run-9")
    _chat_once(backend)

    assert captured == [FREE_ROUTER_ID]
    assert backend.last_free_pin_decision["reason"] == "no_free_candidates"


def test_backend_pinned_model_passes_catalog_selection(monkeypatch):
    catalog = _selection_catalog("alpha:free", "beta:free")
    calls = []

    def fake_get(**kwargs):
        calls.append(kwargs)
        return catalog

    monkeypatch.setattr(pin, "get_openrouter_catalog", fake_get)
    monkeypatch.setattr(
        "hub._services.llm.openrouter_catalog.get_openrouter_catalog", fake_get
    )
    captured = []
    _install_super_chat(monkeypatch, captured)

    backend = OpenRouterBackend(api_key="testkey", run_id="run-5")
    _chat_once(backend)

    assert any(kwargs.get("model_id") for kwargs in calls)
    assert captured[0] in pin.free_candidates(catalog)


def test_create_backend_openrouter_free_passes_run_id():
    config = {
        "type": "openrouter",
        "free_only": True,
        "api_key": "testkey",
        "run_id": "run-77",
    }
    backend = create_backend(config)
    assert isinstance(backend, OpenRouterBackend)
    assert backend.run_id == "run-77"
    assert backend_identifier(backend) == "openrouter"


def test_create_backend_openrouter_without_run_id_defaults_empty():
    config = {"type": "openrouter", "free_only": True, "api_key": "testkey"}
    backend = create_backend(config)
    assert isinstance(backend, OpenRouterBackend)
    assert backend.run_id == ""


def test_create_backend_legacy_hermes_alias_unaffected():
    config = {"type": "openrouter", "api_key": "testkey", "default_model": "x/y"}
    backend = create_backend(config)
    assert isinstance(backend, HermesBackend)
    assert not isinstance(backend, OpenRouterBackend)
