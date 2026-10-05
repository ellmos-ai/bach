# SPDX-License-Identifier: MIT
"""Working-Memory Subsystem: failure trails & negative memory (Ocean shadow).

Dieses Paket ist als deklarativer Shadow mit ``runtime_authority=false``
gedacht: Es protokolliert fehlgeschlagene Werkzeugaufrufe und gibt Hinweise
auf Blockade/Backoff, ohne selbst Scheduler-Entscheidungen zu erzwingen.
"""
from __future__ import annotations

from .failure_trails import FailureTrailStore, TrailEntry

__all__ = ["FailureTrailStore", "TrailEntry"]
