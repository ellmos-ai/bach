#!/usr/bin/env python3
"""Periodischer Monitor für Task #1564 Übersetzungspipeline.

Liest /Users/lukas/.bach/backups/task_1316/translation_results.json,
zeigt Fortschritt und ETA an und protokolliert in logs/monitor_1564.log.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = Path("/Users/lukas/.bach/backups/task_1316/translation_results.json")
LOG_PATH = ROOT / "logs" / "monitor_1564.log"
INTERVAL_SECONDS = 30
ETA_WINDOW_JOBS = 10


def _fmt_eta(seconds: float) -> str:
    if seconds < 0 or not seconds:
        return "n/a"
    td = timedelta(seconds=int(seconds))
    return str(td)


def _last_processed_job(results: list[dict]) -> dict | None:
    if not results:
        return None
    # results are appended in processing order; take the last one
    return results[-1]


def monitor() -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    log_fh = LOG_PATH.open("a", encoding="utf-8")

    def log(msg: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line)
        log_fh.write(line + "\n")
        log_fh.flush()

    log(f"Monitor gestartet (Interval={INTERVAL_SECONDS}s, Ziel={RESULTS_PATH})")

    last_success = -1
    last_time = None

    while True:
        try:
            data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"Warnung: Ergebnisdatei konnte nicht gelesen werden: {exc}")
            time.sleep(INTERVAL_SECONDS)
            continue

        total = data.get("jobs_total", 212)
        stats = data.get("stats", {})
        success = stats.get("success", 0)
        fail = stats.get("fail", 0)
        done = success + fail
        remaining = max(0, total - done)
        pct = (done / total * 100) if total else 0.0

        results = data.get("results", [])
        last = _last_processed_job(results)
        last_info = "kein Job verarbeitet"
        if last:
            last_info = (
                f"Job {last.get('job_id')} "
                f"{last.get('namespace', '-')}.{last.get('key', '-')} -> "
                f"{last.get('target_language', '-')} "
                f"({'OK' if last.get('success') else 'FAIL'}, "
                f"{last.get('model_used', '-')}, "
                f"{last.get('duration_seconds', 0):.1f}s)"
            )

        # ETA aus den Dauern der letzten ETA_WINDOW_JOBS Erfolge
        durations = [
            r.get("duration_seconds", 0)
            for r in results[-ETA_WINDOW_JOBS:]
            if r.get("success") and r.get("duration_seconds")
        ]
        if durations:
            avg = sum(durations) / len(durations)
            eta_seconds = avg * remaining
            eta = _fmt_eta(eta_seconds)
        else:
            avg = 0.0
            eta = "n/a"

        # Durchschnittsrate seit Monitorstart (nur bei Fortschritt)
        now = datetime.now()
        rate_info = ""
        if last_success >= 0 and success > last_success and last_time:
            delta_jobs = success - last_success
            delta_seconds = (now - last_time).total_seconds()
            if delta_seconds > 0:
                rate = delta_seconds / delta_jobs
                rate_info = f", seit Start ~{rate:.0f}s/Job"
        if success > last_success:
            last_success = success
            last_time = now

        log(
            f"Fortschritt: {done}/{total} ({pct:.1f}%) | "
            f"success={success}, fail={fail}, remaining={remaining} | "
            f"avg/job={avg:.1f}s | ETA={eta}{rate_info} | Letzter: {last_info}"
        )

        if done >= total:
            log("Pipeline abgeschlossen. Monitor beendet.")
            log_fh.close()
            return

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        print("\nMonitor beendet (KeyboardInterrupt).", file=sys.stderr)
        sys.exit(0)
