"""Tests für den num_ctx-Benchmark (tools.ollama.ollama_benchmark).

Alle Tests laufen ohne Netzwerkzugriff: client.generate wird durch einen
Stub ersetzt, der vorbestimmte OllamaResponse-Objekte liefert. Geprüft
werden Prompt-Aufbau, Messung pro Stufe, die Stop-Regeln von _benchmark,
das Übergabebudget, der Beratungsprompt und die advice-Ausgabepfade.
"""

import pytest

from tools.ollama.ollama_benchmark import (
    BUDGET_HIGH_RATIO,
    BUDGET_LOW_RATIO,
    CHARS_PER_TOKEN,
    DEFAULT_LEVELS,
    DEFAULT_PROMPT_CHARS,
    DEFAULT_RUNS,
    _benchmark,
    _build_advice_prompt,
    _build_prompt,
    _handoff_budget,
    _print_advice,
    _run_level,
)
from tools.ollama.ollama_client import OllamaResponse


class StubClient:
    """Ersatz für OllamaClient: kein Netzwerk, vorbestimmte Antworten.

    Enthält `responses` noch Einträge, werden diese der Reihe nach
    zurückgegeben (Exceptions werden ausgelöst); danach liefert der Stub
    erfolgreich Antworten mit completion_tokens=10.
    """

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def generate(self, prompt, model=None, num_ctx=None, **kwargs):
        self.calls.append({"prompt": prompt, "model": model, "num_ctx": num_ctx})
        if self.responses:
            response = self.responses.pop(0)
        else:
            response = OllamaResponse(success=True, completion_tokens=10)
        if isinstance(response, Exception):
            raise response
        return response


def _successful_run():
    """Benchmark mit zwei erfolgreichen Stufen als Testdaten-Lieferant."""
    client = StubClient()
    rows, recommended, best_median, stop_reason = _benchmark(
        client, "llama3.2", "prompt", [2048, 8192], runs=1
    )
    assert stop_reason == ""
    assert recommended == 8192
    assert best_median > 0.0
    return rows, recommended, best_median


# --- Konstanten ---


def test_documented_constants():
    assert DEFAULT_LEVELS == "2048,4096,8192,16384,32768"
    assert DEFAULT_RUNS == 2
    assert DEFAULT_PROMPT_CHARS == 2000
    assert BUDGET_LOW_RATIO == 0.60
    assert BUDGET_HIGH_RATIO == 0.80
    assert CHARS_PER_TOKEN == 4


# --- _build_prompt ---


def test_build_prompt_deterministic_and_exact_length():
    for chars in (1, 100, 500, DEFAULT_PROMPT_CHARS, 5000):
        first = _build_prompt(chars)
        second = _build_prompt(chars)
        assert len(first) == chars
        assert first == second


def test_build_prompt_nonpositive_returns_seed():
    zero = _build_prompt(0)
    assert zero == _build_prompt(-7)


# --- _run_level ---


def test_run_level_all_success():
    client = StubClient()
    row = _run_level(client, "llama3.2", "prompt", 4096, runs=2)
    assert row["num_ctx"] == 4096
    assert row["ok"] == 2
    assert row["runs"] == 2
    assert row["median_tokens"] == 10
    assert row["median_time"] > 0.0
    assert row["median_tp"] > 0.0
    assert row["first_error"] == ""
    assert len(client.calls) == 2
    assert all(call["num_ctx"] == 4096 for call in client.calls)
    assert all(call["model"] == "llama3.2" for call in client.calls)
    assert all(call["prompt"] == "prompt" for call in client.calls)


def test_run_level_all_failed():
    client = StubClient([OllamaResponse(success=False, error="boom")] * 2)
    row = _run_level(client, "llama3.2", "prompt", 4096, runs=2)
    assert row["num_ctx"] == 4096
    assert row["ok"] == 0
    assert row["runs"] == 2
    assert row["median_time"] is None
    assert row["median_tokens"] is None
    assert row["median_tp"] is None
    assert row["first_error"] == "boom"


def test_run_level_mixed_keeps_first_error():
    client = StubClient(
        [
            OllamaResponse(success=False, error="boom"),
            OllamaResponse(success=True, completion_tokens=10),
        ]
    )
    row = _run_level(client, "llama3.2", "prompt", 4096, runs=2)
    assert row["ok"] == 1
    assert row["median_tokens"] == 10
    assert row["median_tp"] > 0.0
    assert row["first_error"] == "boom"


def test_run_level_zero_runs_normalized():
    client = StubClient()
    row = _run_level(client, "llama3.2", "prompt", 4096, runs=0)
    assert row["num_ctx"] == 4096
    assert row["runs"] == 1


# --- _benchmark ---


def test_benchmark_all_levels_ok_recommends_last():
    client = StubClient()
    rows, recommended, best_median, stop_reason = _benchmark(
        client, "llama3.2", "prompt", [2048, 4096, 8192], runs=2
    )
    assert [row["num_ctx"] for row in rows] == [2048, 4096, 8192]
    assert all(row["ok"] == 2 for row in rows)
    assert recommended == 8192
    assert best_median > 0.0
    assert stop_reason == ""
    assert len(client.calls) == 6


def test_benchmark_stops_on_no_success():
    client = StubClient([OllamaResponse(success=False, error="boom")] * 2)
    rows, recommended, best_median, stop_reason = _benchmark(
        client, "llama3.2", "prompt", [2048, 4096, 8192], runs=2
    )
    assert len(rows) == 1
    assert recommended is None
    assert best_median == 0.0
    assert stop_reason == "no successful generation (error: boom)"


def test_benchmark_stops_on_throughput_collapse():
    client = StubClient(
        [OllamaResponse(success=True, completion_tokens=100)] * 2
        + [OllamaResponse(success=True, completion_tokens=0)] * 2
    )
    rows, recommended, best_median, stop_reason = _benchmark(
        client, "llama3.2", "prompt", [2048, 4096], runs=2
    )
    assert len(rows) == 2
    assert recommended == 2048
    assert best_median > 0.0
    expected = "throughput collapse at num_ctx=4096 (median 0.00 tok/s, best %.2f tok/s)" % best_median
    assert stop_reason == expected
    assert len(client.calls) == 4


# --- _handoff_budget ---


def test_handoff_budget_uses_ratios():
    budget = _handoff_budget(8192)
    expected_low_tokens = int(8192 * BUDGET_LOW_RATIO)
    expected_high_tokens = int(8192 * BUDGET_HIGH_RATIO)
    assert budget["low_tokens"] == expected_low_tokens
    assert budget["high_tokens"] == expected_high_tokens
    assert budget["low_chars"] == expected_low_tokens * CHARS_PER_TOKEN
    assert budget["high_chars"] == expected_high_tokens * CHARS_PER_TOKEN
    assert (budget["low_tokens"], budget["high_tokens"]) == (4915, 6553)


def test_handoff_budget_non_positive_is_zero():
    for value in (0, -100):
        assert _handoff_budget(value) == {
            "low_tokens": 0,
            "high_tokens": 0,
            "low_chars": 0,
            "high_chars": 0,
        }


# --- _build_advice_prompt ---


def test_build_advice_prompt_contents():
    rows, recommended, best_median = _successful_run()
    prompt = _build_advice_prompt(
        "llama3.2", DEFAULT_PROMPT_CHARS, rows, recommended, best_median
    )
    assert "llama3.2" in prompt
    assert "Recommended num_ctx=%d, median throughput %.2f tok/s." % (
        recommended,
        best_median,
    ) in prompt
    budget = _handoff_budget(recommended)
    assert "roughly %d-%d tokens (%d-%d characters)" % (
        budget["low_tokens"],
        budget["high_tokens"],
        budget["low_chars"],
        budget["high_chars"],
    ) in prompt


# --- _print_advice ---


def test_print_advice_success(capsys):
    rows, recommended, best_median = _successful_run()
    client = StubClient([OllamaResponse(success=True, text="Nimm 8192 als Kontextfenster.")])
    _print_advice(client, "llama3.2", DEFAULT_PROMPT_CHARS, rows, recommended, best_median)
    captured = capsys.readouterr()
    assert "Advisor note from llama3.2 (optional, verify before acting):" in captured.out
    assert "Nimm 8192 als Kontextfenster." in captured.out
    assert client.calls and client.calls[0]["num_ctx"] == recommended


def test_print_advice_request_failed(capsys):
    rows, recommended, best_median = _successful_run()
    client = StubClient([RuntimeError("Verbindung fehlgeschlagen")])
    _print_advice(client, "llama3.2", DEFAULT_PROMPT_CHARS, rows, recommended, best_median)
    captured = capsys.readouterr()
    assert "--advice warning: request failed: Verbindung fehlgeschlagen" in captured.err


def test_print_advice_model_error(capsys):
    rows, recommended, best_median = _successful_run()
    client = StubClient([OllamaResponse(success=False, error="boom")])
    _print_advice(client, "llama3.2", DEFAULT_PROMPT_CHARS, rows, recommended, best_median)
    captured = capsys.readouterr()
    assert "--advice warning: model returned an error: boom" in captured.err


def test_print_advice_empty_answer(capsys):
    rows, recommended, best_median = _successful_run()
    client = StubClient([OllamaResponse(success=True, text="")])
    _print_advice(client, "llama3.2", DEFAULT_PROMPT_CHARS, rows, recommended, best_median)
    captured = capsys.readouterr()
    assert "--advice warning: model returned an empty answer." in captured.err