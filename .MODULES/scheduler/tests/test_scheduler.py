# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone scheduler module."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from scheduler import JobScheduler


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "scheduler"
    assert data["selfcontained"] is True


def test_scheduler_lifecycle():
    scheduler = JobScheduler()
    counter = 0

    def task(amount: int):
        nonlocal counter
        counter += amount
        return counter

    job = scheduler.add_job("increment", interval_seconds=0.05, func=task, args=[2])
    assert job.name == "increment"
    assert scheduler.get_status()["total_jobs"] == 1

    # Run force
    receipt = scheduler.run_job(job.job_id)
    assert receipt["ok"] is True
    assert counter == 2
    assert job.run_count == 1

    # Run pending after interval
    time.sleep(0.1)
    pending = scheduler.run_pending()
    assert len(pending) == 1
    assert counter == 4

    # Pause and verify it doesn't run
    scheduler.pause_job(job.job_id)
    time.sleep(0.1)
    assert len(scheduler.run_pending()) == 0
    assert counter == 4

    # Resume and run
    scheduler.resume_job(job.job_id)
    scheduler.run_job(job.job_id)
    assert counter == 6


def test_scheduler_error_capture():
    scheduler = JobScheduler()

    def bad_task():
        raise ValueError("Simulated fault")

    job = scheduler.add_job("bad", interval_seconds=10, func=bad_task)
    receipt = scheduler.run_job(job.job_id)
    assert receipt["ok"] is False
    assert "ValueError" in receipt["error"]
    assert job.last_error is not None
