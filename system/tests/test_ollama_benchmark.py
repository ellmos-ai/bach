"""Smoke-Tests fuer die num_ctx-Messroutine (ollama_benchmark).

Abgedeckt: Handoff-Budget-Berechnung relativ zum Kontextfenster,
Textform der Budget-Zeile, Prompt-Bau fuer den optionalen LLM-Rat und
der fehlertolerante --advice-Pfad.

Kein Ollama-Server noetig: alle Tests arbeiten mit reinen Daten bzw.
Fake-Clients.
"""

import io
import contextlib

import pytest

from tools.ollama.ollama_benchmark import (
    BUDGET_LOW_RATIO,
    BUDGET_HIGH_RATIO,
    CHARS_PER_TOKEN,
    _build_advice_prompt,
    _format_handoff_budget,
    _format_rows_summary,
    _handoff_budget,
    _print_advice,
)


def _row(num_ctx, ok=3, runs=3, median_time=1.0, median_tokens=100,
         median_tp=100.0, first_error=""):
    return {
        "num_ctx": num_ctx,
        "ok": ok,
        "runs": runs,
        "median_time": median_time,
        "median_tokens": median_tokens,
        "median_tp": median_tp,
        "first_error": first_error,
    }


# --- _handoff_budget -------------------------------------------------------

def test_handoff_budget_uses_configured_ratios():
    budget = _handoff_budget(4096)
    assert budget["low_tokens"] == int(4096 * BUDGET_LOW_RATIO)
    assert budget["high_tokens"] == int(4096 * BUDGET_HIGH_RATIO)
    assert budget["low_chars"] == budget["low_tokens"] * CHARS_PER_TOKEN
    assert budget["high_chars"] == budget["high_tokens"] * CHARS_PER_TOKEN


def test_handoff_budget_stays_below_window():
    for num_ctx in (512, 4096, 8192, 32768, 262144):
        budget = _handoff_budget(num_ctx)
        assert 0 < budget["low_tokens"] < budget["high_tokens"] < num_ctx


def test_handoff_budget_is_monotonic():
    small = _handoff_budget(2048)
    large = _handoff_budget(8192)
    assert small["high_tokens"] < large["low_tokens"]


@pytest.mark.parametrize("num_ctx", [0, -1, -4096])
def test_handoff_budget_degenerate_window_returns_zero(num_ctx):
    budget = _handoff_budget(num_ctx)
    assert budget == {"low_tokens": 0, "high_tokens": 0,
                      "low_chars": 0, "high_chars": 0}


# --- _format_handoff_budget ------------------------------------------------

def test_format_handoff_budget_contains_numbers_and_label():
    text = _format_handoff_budget(4096, "num_ctx")
    budget = _handoff_budget(4096)
    assert text.startswith("Handoff budget:")
    assert "%d-%d tokens" % (budget["low_tokens"], budget["high_tokens"]) in text
    assert "%d-%d chars" % (budget["low_chars"], budget["high_chars"]) in text
    assert "num_ctx=4096" in text
    assert "60%-80%" in text


def test_format_handoff_budget_supports_alternative_label():
    assert "default num_ctx=8192" in _format_handoff_budget(8192, "default num_ctx")


# --- _format_rows_summary -------------------------------------------------

def test_format_rows_summary_lists_all_levels():
    rows = [_row(2048, median_tp=50.0), _row(4096, median_tp=80.0)]
    text = _format_rows_summary(rows)
    assert "num_ctx=2048: 3/3 ok, 50.00 tok/s" in text
    assert "num_ctx=4096: 3/3 ok, 80.00 tok/s" in text
    assert "; " in text


def test_format_rows_summary_handles_missing_throughput():
    rows = [_row(2048, ok=0, median_time=None, median_tokens=None, median_tp=None,
                 first_error="timeout")]
    text = _format_rows_summary(rows)
    assert "num_ctx=2048: 0/3 ok, - tok/s" in text


# --- _build_advice_prompt -------------------------------------------------

def test_build_advice_prompt_mentions_model_and_budget():
    rows = [_row(2048, median_tp=50.0), _row(4096, median_tp=80.0)]
    prompt = _build_advice_prompt("qwen2.5:7b", 12000, rows, 4096, 80.0)
    budget = _handoff_budget(4096)
    assert "qwen2.5:7b" in prompt
    assert "Recommended num_ctx=4096" in prompt
    assert "80.00 tok/s" in prompt
    assert str(12000) in prompt
    assert str(budget["low_tokens"]) in prompt
    assert str(budget["high_chars"]) in prompt
    assert "num_ctx=2048: 3/3 ok" in prompt


# --- _print_advice --------------------------------------------------------

class _BoomClient:
    def generate(self, *args, **kwargs):
        raise RuntimeError("ollama not reachable")


class _FailingClient:
    def generate(self, *args, **kwargs):
        return type("Resp", (), {"success": False, "error": "model not found",
                                 "text": ""})()


class _OkClient:
    def __init__(self):
        self.called = {}

    def generate(self, prompt, model=None, num_ctx=None):
        self.called = {"prompt": prompt, "model": model, "num_ctx": num_ctx}
        return type("Resp", (), {"success": True, "error": "",
                                 "text": "  Fenster passt.  "})()


def _run_print_advice(client):
    err = io.StringIO()
    rows = [_row(4096)]
    with contextlib.redirect_stderr(err):
        _print_advice(client, "qwen2.5:7b", 12000, rows, 4096, 80.0)
    return err.getvalue()


def test_print_advice_swallows_exceptions():
    err = _run_print_advice(_BoomClient())
    assert "--advice warning" in err
    assert "ollama not reachable" in err


def test_print_advice_reports_model_error_without_raising():
    err = _run_print_advice(_FailingClient())
    assert "--advice warning" in err
    assert "model not found" in err


def test_print_advice_uses_recommended_window():
    client = _OkClient()
    _run_print_advice(client)
    assert client.called["model"] == "qwen2.5:7b"
    assert client.called["num_ctx"] == 4096
    assert "Handoff" in client.called["prompt"] or "budget" in client.called["prompt"]
