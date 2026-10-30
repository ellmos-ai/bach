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
