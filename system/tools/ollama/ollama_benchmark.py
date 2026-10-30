#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline benchmark helper for the num_ctx setting of the local Ollama client.

Runs the configured Ollama server with several num_ctx levels on a fixed,
deterministic prompt and reports the median generation throughput per level.
The final recommendation is the largest level that still completes without
errors and without a throughput collapse (median tok/s below half of the
best previous level). With --save the recommendation is stored through
OllamaHandler.set_num_ctx(num_ctx_recommended=...); nothing else is written
and no environment variables are touched.

Every report states why a level was recommended and, when the run stopped
early, why. It also prints the handoff budget derived from the chosen window:
60-80 % of num_ctx (BUDGET_LOW_RATIO/BUDGET_HIGH_RATIO) are considered safely
usable, converted to characters with CHARS_PER_TOKEN=4, i.e. num_ctx=8192
means roughly 4915-6553 usable tokens or 19660-26212 characters of handoff
prompt. With --advice the model itself is asked for a short note on the
recommendation (off by default; failures are warnings and never change the
exit code).

All work happens in main(): importing this module has no network or config
side effects.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ollama.ollama_client import DEFAULT_NUM_CTX, OllamaClient  # noqa: E402

try:  # handler import is optional, only --save needs it
    from hub.ollama import OllamaHandler  # noqa: E402
    _HAVE_HANDLER = True
except ImportError:  # pragma: no cover - depends on installation layout
    OllamaHandler = None  # type: ignore[assignment]
    _HAVE_HANDLER = False

DEFAULT_LEVELS = "2048,4096,8192,16384,32768"
DEFAULT_RUNS = 2
DEFAULT_PROMPT_CHARS = 2000

# Handoff budget: a prompt should only use a part of the context window, the
# rest is needed for the model's own output and for safety margin.
BUDGET_LOW_RATIO = 0.60
BUDGET_HIGH_RATIO = 0.80
CHARS_PER_TOKEN = 4

_PROMPT_SEED = (
    "Explain in a few bullet points how to tune a database for heavy read "
    "traffic: indexing strategy, query planning, caching layers and the "
    "sizing of working memory and disks. "
)


def _build_prompt(prompt_chars: int) -> str:
    """Return a deterministic prompt of (about) prompt_chars characters."""
    if prompt_chars <= 0:
        return _PROMPT_SEED.strip()
    if prompt_chars <= len(_PROMPT_SEED):
        return _PROMPT_SEED[:prompt_chars]
    parts = [_PROMPT_SEED]
    written = len(_PROMPT_SEED)
    while written < prompt_chars:
        parts.append(_PROMPT_SEED)
        written += len(_PROMPT_SEED)
    return "".join(parts)[:prompt_chars]


def _run_level(client: OllamaClient, model: str, prompt: str, num_ctx: int,
               runs: int) -> Dict[str, Any]:
    """Generate with one num_ctx level and collect per-run measurements."""
    ok = 0
    times: List[float] = []
    tokens: List[int] = []
    throughputs: List[float] = []
    first_error = ""
    for _ in range(max(1, runs)):
        start = time.perf_counter()
        resp = client.generate(prompt, model=model, num_ctx=num_ctx)
        elapsed = max(time.perf_counter() - start, 1e-9)
        if getattr(resp, "success", False):
            ok += 1
            times.append(elapsed)
            tokens_r = int(getattr(resp, "completion_tokens", 0) or 0)
            tokens.append(tokens_r)
            throughputs.append(tokens_r / elapsed if tokens_r > 0 else 0.0)
        elif not first_error:
            first_error = str(getattr(resp, "error", "") or "unknown error")
    return {
        "num_ctx": num_ctx,
        "ok": ok,
        "runs": max(1, runs),
        "median_time": float(statistics.median(times)) if times else None,
        "median_tokens": int(statistics.median(tokens)) if tokens else None,
        "median_tp": float(statistics.median(throughputs)) if throughputs else None,
        "first_error": first_error,
    }


def _benchmark(client: OllamaClient, model: str, prompt: str,
               levels: List[int], runs: int) -> Tuple[
        List[Dict[str, Any]], Optional[int], float, str]:
    """Measure all levels until a failure or a throughput collapse."""
    rows: List[Dict[str, Any]] = []
    best_median = 0.0
    recommended: Optional[int] = None
    stop_reason = ""
    for level in levels:
        row = _run_level(client, model, prompt, level, runs)
        rows.append(row)
        if row["median_tp"] is None:
            stop_reason = "no successful generation"
            if row["first_error"]:
                stop_reason += " (error: %s)" % row["first_error"]
            break
        if best_median > 0.0 and row["median_tp"] < 0.5 * best_median:
            stop_reason = (
                "throughput collapse at num_ctx=%d (median %.2f tok/s, "
                "best %.2f tok/s)" % (level, row["median_tp"], best_median)
            )
            break
        if row["median_tp"] > best_median:
            best_median = row["median_tp"]
        recommended = level
    return rows, recommended, best_median, stop_reason


def _handoff_budget(num_ctx: int) -> Dict[str, int]:
    """Return the handoff character/token budget derived from num_ctx.

    A prompt handed over to a local model should never fill the whole
    context window: the model needs room for its own answer and some safety
    margin. So the budget is expressed as a range from BUDGET_LOW_RATIO to
    BUDGET_HIGH_RATIO of the window.
    """
    if num_ctx <= 0:
        return {"low_tokens": 0, "high_tokens": 0, "low_chars": 0,
                "high_chars": 0}
    low_tokens = int(num_ctx * BUDGET_LOW_RATIO)
    high_tokens = int(num_ctx * BUDGET_HIGH_RATIO)
    return {
        "low_tokens": low_tokens,
        "high_tokens": high_tokens,
        "low_chars": low_tokens * CHARS_PER_TOKEN,
        "high_chars": high_tokens * CHARS_PER_TOKEN,
    }


def _format_handoff_budget(num_ctx: int, label: str) -> str:
    """Return the one-line handoff budget message for a num_ctx value."""
    budget = _handoff_budget(num_ctx)
    return ("Handoff budget: ~%d-%d tokens (~%d-%d chars) at %s=%d "
            "(%.0f%%-%.0f%% of the window)"
            % (budget["low_tokens"], budget["high_tokens"],
               budget["low_chars"], budget["high_chars"], label, num_ctx,
               BUDGET_LOW_RATIO * 100, BUDGET_HIGH_RATIO * 100))


def _print_report(model: str, prompt_chars: int, runs: int,
                  rows: List[Dict[str, Any]], recommended: Optional[int],
                  best_median: float, stop_reason: str,
                  default_num_ctx: int) -> None:
    """Print the measurement table and the final recommendation."""
    print("Ollama num_ctx benchmark: model=%s, runs per level=%d, "
          "prompt~%d chars" % (model, runs, prompt_chars))
    print("client default num_ctx: %s (DEFAULT_NUM_CTX from ollama_client)"
          % default_num_ctx)
    print("")
    header = "num_ctx | ok/runs | median time (s) | median tokens | median tok/s | note"
    print(header)
    print("-" * len(header))
    for row in rows:
        m_time = "-" if row["median_time"] is None else "%.2f" % row["median_time"]
        m_tokens = "-" if row["median_tokens"] is None else str(row["median_tokens"])
        m_tp = "-" if row["median_tp"] is None else "%.2f" % row["median_tp"]
        note = row["first_error"]
        if recommended is not None and row["num_ctx"] == recommended:
            note = (note + " " if note else "") + "<= recommended"
        print("%7d | %7d/%d | %15s | %13s | %12s | %s"
              % (row["num_ctx"], row["ok"], row["runs"], m_time, m_tokens,
                 m_tp, note))
    print("")
    if recommended is not None:
        print("Recommended num_ctx: %d (best median throughput: %.2f tok/s)"
              % (recommended, best_median))
        print("Why: it is the largest level that still finished all runs "
              "without errors and without a throughput collapse, and it has "
              "the best median throughput (%.2f tok/s) of all measured "
              "levels." % best_median)
    else:
        print("No num_ctx level could be recommended.")
        print("Why: every measured level failed (no successful generation or "
              "a throughput collapse); see the note column and the stop "
              "reason below.")
    if stop_reason:
        print("Stopped early: %s" % stop_reason)
        print("Reason: the benchmark stops at the first level that produces "
              "no successful generation or whose median throughput drops "
              "below half of the best previous level, because larger windows "
              "only add cost from that point on.")
    budget_ctx = recommended if recommended is not None else default_num_ctx
    if budget_ctx:
        label = "num_ctx" if recommended is not None else "default num_ctx"
        print(_format_handoff_budget(budget_ctx, label))
    else:
        print("Handoff budget: unknown (no num_ctx available).")


def _format_rows_summary(rows: List[Dict[str, Any]]) -> str:
    """Return a compact one-line summary of the measured levels."""
    parts = []
    for row in rows:
        tp = "-" if row["median_tp"] is None else "%.2f" % row["median_tp"]
        parts.append("num_ctx=%d: %d/%d ok, %s tok/s"
                     % (row["num_ctx"], row["ok"], row["runs"], tp))
    return "; ".join(parts)


def _build_advice_prompt(model: str, prompt_chars: int, rows: List[Dict[str, Any]],
                         recommended: int, best_median: float) -> str:
    """Return the prompt used for the optional --advice note."""
    budget = _handoff_budget(recommended)
    return (
        "You are advising on the context window (num_ctx) of the local "
        "Ollama model %s.\n"
        "Benchmark results: %s.\n"
        "Recommended num_ctx=%d, median throughput %.2f tok/s.\n"
        "Planned handoff prompts have about %d characters; the safe budget "
        "at this window is roughly %d-%d tokens (%d-%d characters).\n"
        "Answer with at most 4 short bullet points: does the window fit that "
        "prompt size, and what must stay below the handoff budget? Be "
        "concrete and do not just repeat the numbers."
        % (model, _format_rows_summary(rows), recommended, best_median,
           prompt_chars, budget["low_tokens"], budget["high_tokens"],
           budget["low_chars"], budget["high_chars"]))


def _print_advice(client: OllamaClient, model: str, prompt_chars: int,
                  rows: List[Dict[str, Any]], recommended: int,
                  best_median: float) -> None:
    """Print an optional LLM note; every failure is a warning only."""
    prompt = _build_advice_prompt(model, prompt_chars, rows, recommended,
                                  best_median)
    try:
        resp = client.generate(prompt, model=model, num_ctx=recommended)
    except Exception as exc:  # advice must never break the benchmark run
        print("--advice warning: request failed: %s" % exc, file=sys.stderr)
        return
    if not getattr(resp, "success", False):
        print("--advice warning: model returned an error: %s"
              % (getattr(resp, "error", "") or "unknown error"),
              file=sys.stderr)
        return
    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        print("--advice warning: model returned an empty answer.",
              file=sys.stderr)
        return
    print("")
    print("Advisor note from %s (optional, verify before acting):" % model)
    print(text)


def _save_recommendation(model: str, recommended: int) -> int:
    """Store only num_ctx_recommended via OllamaHandler; returns exit code."""
    if OllamaHandler is None:
        print("--save skipped: hub.ollama.OllamaHandler is not importable "
              "here.", file=sys.stderr)
        return 1
    try:
        saved, msg = OllamaHandler().set_num_ctx(
            model, num_ctx_recommended=recommended)
    except Exception as exc:  # keep the benchmark usable even if saving fails
        print("Saving recommendation failed for model %r: %s"
              % (model, exc), file=sys.stderr)
        return 1
    if saved:
        print("Saved num_ctx_recommended=%d for model %r: %s"
              % (recommended, model, msg))
        return 0
    print("Saving recommendation refused for model %r: %s"
          % (model, msg), file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark num_ctx levels of a local Ollama model and "
                    "recommend one.")
    parser.add_argument("--model", default=OllamaClient.DEFAULT_MODEL,
                        help="Ollama model name (default: %(default)s)")
    parser.add_argument("--levels", default=DEFAULT_LEVELS,
                        help="Comma separated num_ctx levels "
                             "(default: %(default)s)")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                        help="Measured runs per level (default: %(default)s)")
    parser.add_argument("--prompt-chars", dest="prompt_chars", type=int,
                        default=DEFAULT_PROMPT_CHARS,
                        help="Approximate prompt length in characters "
                             "(default: %(default)s)")
    parser.add_argument("--save", action="store_true",
                        help="Persist the recommendation via "
                             "OllamaHandler.set_num_ctx(num_ctx_recommended=...)")
    parser.add_argument("--advice", action="store_true",
                        help="Optional: ask the model itself for a short note "
                             "on the recommended level (off by default)")
    args = parser.parse_args(argv)

    levels: List[int] = []
    for raw in str(args.levels).split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            levels.append(int(raw))
        except ValueError:
            print("Ignoring invalid num_ctx level: %r" % raw, file=sys.stderr)
    if not levels:
        print("No valid num_ctx levels supplied.", file=sys.stderr)
        return 2
    if args.runs < 1:
        print("--runs must be at least 1.", file=sys.stderr)
        return 2
    if args.prompt_chars < 1:
        print("--prompt-chars must be at least 1.", file=sys.stderr)
        return 2

    prompt = _build_prompt(args.prompt_chars)
    client = OllamaClient()
    rows, recommended, best_median, stop_reason = _benchmark(
        client, args.model, prompt, levels, args.runs)
    _print_report(args.model, args.prompt_chars, args.runs, rows,
                  recommended, best_median, stop_reason,
                  OllamaClient.DEFAULT_NUM_CTX)

    if args.advice:
        if recommended is None:
            print("--advice skipped: no level passed the checks.",
                  file=sys.stderr)
        else:
            _print_advice(client, args.model, args.prompt_chars, rows,
                          recommended, best_median)

    if args.save:
        if recommended is None:
            print("--save skipped: no level passed the checks, nothing "
                  "stored.")
            return 1
        return _save_recommendation(args.model, recommended)
    return 0 if recommended is not None else 1


if __name__ == "__main__":
    sys.exit(main())