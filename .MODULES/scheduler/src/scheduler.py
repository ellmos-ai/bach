# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: scheduler
===============================
Self-contained periodic job scheduling engine, execution tracking, error containment, and execution receipts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ScheduledJob:
    job_id: str
    name: str
    interval_seconds: float
    func: Callable[..., Any]
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_run_at: Optional[float] = None
    next_run_at: float = field(default_factory=time.time)
    run_count: int = 0
    last_error: Optional[str] = None
    last_result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "run_count": self.run_count,
            "last_error": self.last_error,
            "last_result": self.last_result,
        }


class JobScheduler:
    """Manages recurring tasks, interval tracking, and execution containment."""

    def __init__(self):
        self._jobs: Dict[str, ScheduledJob] = {}
        self._execution_history: List[Dict[str, Any]] = []

    def add_job(
        self,
        name: str,
        interval_seconds: float,
        func: Callable[..., Any],
        job_id: Optional[str] = None,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
    ) -> ScheduledJob:
        """Registers a recurring job."""
        jid = job_id or f"job_{uuid.uuid4().hex[:8]}"
        now = time.time()
        job = ScheduledJob(
            job_id=jid,
            name=name,
            interval_seconds=max(0.1, float(interval_seconds)),
            func=func,
            args=list(args or []),
            kwargs=dict(kwargs or {}),
            enabled=enabled,
            created_at=now,
            next_run_at=now + interval_seconds,
        )
        self._jobs[jid] = job
        return job

    def remove_job(self, job_id: str) -> bool:
        """Removes a job by ID."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        return False

    def pause_job(self, job_id: str) -> bool:
        """Pauses a job."""
        if job_id in self._jobs:
            self._jobs[job_id].enabled = False
            return True
        return False

    def resume_job(self, job_id: str) -> bool:
        """Resumes a paused job and updates next_run_at."""
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.enabled = True
            job.next_run_at = time.time() + job.interval_seconds
            return True
        return False

    def run_job(self, job_id: str) -> Dict[str, Any]:
        """Force executes a specific job immediately."""
        if job_id not in self._jobs:
            return {"job_id": job_id, "ok": False, "error": f"Job not found: {job_id}"}

        job = self._jobs[job_id]
        now = time.time()
        start = time.perf_counter()
        ok = False
        res_str = None
        err_str = None

        try:
            res = job.func(*job.args, **job.kwargs)
            res_str = str(res)
            ok = True
        except Exception as exc:
            err_str = f"{type(exc).__name__}: {exc}"

        dur = time.perf_counter() - start
        job.last_run_at = now
        job.next_run_at = now + job.interval_seconds
        job.run_count += 1
        job.last_result = res_str
        job.last_error = err_str

        record = {
            "job_id": job.job_id,
            "name": job.name,
            "run_at": now,
            "duration_seconds": round(dur, 4),
            "ok": ok,
            "result": res_str,
            "error": err_str,
        }
        self._execution_history.append(record)
        if len(self._execution_history) > 200:
            self._execution_history = self._execution_history[-200:]
        return record

    def run_pending(self) -> List[Dict[str, Any]]:
        """Executes all enabled jobs that are due."""
        now = time.time()
        receipts: List[Dict[str, Any]] = []
        for job in list(self._jobs.values()):
            if job.enabled and now >= job.next_run_at:
                receipt = self.run_job(job.job_id)
                receipts.append(receipt)
        return receipts

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Returns details of all registered jobs."""
        return [job.to_dict() for job in self._jobs.values()]

    def get_status(self) -> Dict[str, Any]:
        """Returns summary status of the scheduler."""
        jobs = list(self._jobs.values())
        enabled_count = sum(1 for j in jobs if j.enabled)
        return {
            "total_jobs": len(jobs),
            "enabled_jobs": enabled_count,
            "paused_jobs": len(jobs) - enabled_count,
            "total_executions": len(self._execution_history),
        }
