# SPDX-License-Identifier: MIT
"""
schwarm.runner -- Claude CLI Wrapper mit Kosten-Tracking
=========================================================
Zentraler Baustein: Startet Claude-Prozesse mit konfigurierbaren Parametern.
Handhabt Environment, Fallback, Timeout, Output-Capture.
Erweitert um Token-Zaehlung und DB-Logging (schwarm_runs).

Ref: BACH v3.8.0-SUGAR
"""
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# --- Dynamische Worker-Berechnung ---


def calculate_dynamic_workers(num_chunks: int, max_workers: int = 0) -> int:
    """Berechnet die optimale Worker-Anzahl basierend auf Task-Groesse.

    Heuristik:
      - < 4 Chunks  -> 2 Workers
      - 4-10 Chunks -> 4 Workers
      - > 10 Chunks -> min(chunks // 2, max_workers)

    Args:
        num_chunks: Anzahl der zu verarbeitenden Chunks/Tasks.
        max_workers: Obere Schranke. 0 = auto (min(CPU-Kerne, 8)).

    Returns:
        Optimale Worker-Anzahl (mindestens 2).
    """
    if max_workers <= 0:
        try:
            cpu_count = os.cpu_count() or 4
        except Exception:
            cpu_count = 4
        max_workers = min(cpu_count, 8)

    if num_chunks < 4:
        workers = 2
    elif num_chunks <= 10:
        workers = 4
    else:
        workers = num_chunks // 2

    # Clamp: min 2, max max_workers, nie mehr als chunks selbst
    workers = max(2, min(workers, max_workers, num_chunks))
    return workers


# --- Kosten pro Modell (USD / 1M Tokens) ---
MODEL_COSTS = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}

try:
    from hub.bach_paths import BACH_DB as DB_PATH
except ImportError:
    DB_PATH = Path(__file__).parent.parent.parent / "data" / "bach.db"


def _estimate_tokens(text: str) -> int:
    """Grobe Token-Schaetzung: ~4 Zeichen pro Token."""
    return max(1, len(text) // 4)


def _get_model_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Berechnet geschaetzte Kosten in USD."""
    costs = MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
    return (tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000


def ensure_schwarm_table(db_path: Path = DB_PATH):
    """Erstellt die schwarm_runs Tabelle falls nicht vorhanden."""
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schwarm_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            task TEXT,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            workers INTEGER DEFAULT 1,
            duration_ms INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            result_summary TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def log_schwarm_run(pattern: str, task: str, tokens_in: int, tokens_out: int,
                    cost_usd: float, workers: int, duration_ms: int,
                    status: str = "completed", result_summary: str = "",
                    db_path: Path = DB_PATH):
    """Loggt einen Schwarm-Run in die DB."""
    if not db_path.exists():
        return None
    ensure_schwarm_table(db_path)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        INSERT INTO schwarm_runs
            (pattern, task, tokens_in, tokens_out, cost_usd, workers,
             duration_ms, status, result_summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pattern, task[:500] if task else "", tokens_in, tokens_out,
          cost_usd, workers, duration_ms, status, result_summary[:1000],
          datetime.now().isoformat()))
    conn.commit()
    run_id = cursor.lastrowid
    conn.close()
    return run_id


class ClaudeRunner:
    """Wrapper um die Claude CLI fuer automatisierte Aufrufe."""

    def __init__(self, model="claude-sonnet-4-6", fallback_model=None,
                 permission_mode="dontAsk", allowed_tools=None, timeout=1800,
                 cwd=None):
        self.model = model
        self.fallback_model = fallback_model
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools or ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]
        self.timeout = timeout
        self.cwd = cwd
        # Kosten-Tracking pro Session
        self.session_tokens_in = 0
        self.session_tokens_out = 0
        self.session_cost_usd = 0.0

    def _build_env(self):
        """Environment vorbereiten: CLAUDECODE entfernen, Encoding setzen."""
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _build_cmd(self, prompt, **overrides):
        """Claude CLI Kommando zusammenbauen."""
        model = overrides.get("model", self.model)
        continue_conv = overrides.get("continue_conversation", False)

        cmd = ["claude"]
        if continue_conv:
            cmd.append("--continue")
        cmd.extend([
            "--model", model,
            "-p", prompt,
            "--permission-mode", self.permission_mode,
            "--allowedTools", ",".join(self.allowed_tools),
        ])
        fallback = overrides.get("fallback_model", self.fallback_model)
        if fallback:
            cmd.extend(["--fallback-model", fallback])
        return cmd

    def run(self, prompt, **overrides):
        """
        Fuehrt einen Claude-Aufruf aus.

        Returns:
            dict mit keys: success, output, stderr, returncode, duration_s,
                           model, tokens_in, tokens_out, cost_usd
        """
        cmd = self._build_cmd(prompt, **overrides)
        env = self._build_env()
        cwd = overrides.get("cwd", self.cwd)
        timeout = overrides.get("timeout", self.timeout)
        model = overrides.get("model", self.model)

        start = datetime.now()
        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(cwd) if cwd else None
            )
            duration = (datetime.now() - start).total_seconds()

            # Token-Schaetzung
            tokens_in = _estimate_tokens(prompt)
            tokens_out = _estimate_tokens(result.stdout) if result.stdout else 0
            cost = _get_model_cost(model, tokens_in, tokens_out)

            # Session-Tracking
            self.session_tokens_in += tokens_in
            self.session_tokens_out += tokens_out
            self.session_cost_usd += cost

            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "stderr": result.stderr.strip() if result.stderr else "",
                "returncode": result.returncode,
                "duration_s": duration,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost,
            }

        except subprocess.TimeoutExpired:
            duration = (datetime.now() - start).total_seconds()
            return {
                "success": False,
                "output": "",
                "stderr": f"TIMEOUT nach {timeout}s",
                "returncode": -1,
                "duration_s": duration,
                "model": model,
                "tokens_in": _estimate_tokens(prompt),
                "tokens_out": 0,
                "cost_usd": 0.0,
            }

        except FileNotFoundError:
            return {
                "success": False,
                "output": "",
                "stderr": "claude CLI nicht gefunden. Ist Claude Code installiert?",
                "returncode": -2,
                "duration_s": 0,
                "model": model,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
            }

        except Exception as e:
            duration = (datetime.now() - start).total_seconds()
            return {
                "success": False,
                "output": "",
                "stderr": str(e),
                "returncode": -3,
                "duration_s": duration,
                "model": model,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
            }

    def run_parallel(self, prompts, max_workers=3, **overrides):
        """Fuehrt mehrere Claude-Aufrufe parallel aus.

        Args:
            prompts: Liste von Prompt-Strings oder Liste von Dicts mit {prompt, **overrides}
            max_workers: Maximale Anzahl paralleler Worker
            **overrides: Default-Overrides fuer alle Aufrufe

        Returns:
            Liste von Result-Dicts (gleiche Struktur wie run())
        """
        tasks = []
        for item in prompts:
            if isinstance(item, dict):
                item_copy = dict(item)
                prompt = item_copy.pop("prompt")
                merged = {**overrides, **item_copy}
                tasks.append((prompt, merged))
            else:
                tasks.append((item, overrides))

        results = [None] * len(tasks)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {}
            for idx, (prompt, ovr) in enumerate(tasks):
                future = executor.submit(self.run, prompt, **ovr)
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = {
                        "success": False, "output": "", "stderr": str(e),
                        "returncode": -4, "duration_s": 0,
                        "model": overrides.get("model", self.model),
                        "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                    }

        return results

    def pipe(self, prompt, **overrides):
        """Kurzform: Prompt rein, Text raus. Wirft Exception bei Fehler."""
        result = self.run(prompt, **overrides)
        if not result["success"]:
            raise RuntimeError(f"Claude Fehler (rc={result['returncode']}): {result['stderr']}")
        return result["output"]

    def get_session_stats(self) -> dict:
        """Gibt Session-Statistiken zurueck."""
        return {
            "tokens_in": self.session_tokens_in,
            "tokens_out": self.session_tokens_out,
            "cost_usd": self.session_cost_usd,
        }
