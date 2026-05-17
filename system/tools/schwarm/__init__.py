# SPDX-License-Identifier: MIT
"""
schwarm - LLM Swarm Execution Patterns
==================================================
Patterns: parallel-chunks, consensus, hierarchy, stigmergy, specialist.

Ref: BACH v3.8.0-SUGAR / renamed v3.11.1
"""

from .runner import ClaudeRunner, calculate_dynamic_workers
from .consensus import ConsensusPattern
from .hierarchy import HierarchyPattern
from .stigmergy_pattern import StigmergyPattern
from .specialist import SpecialistPattern

__all__ = [
    "ClaudeRunner",
    "calculate_dynamic_workers",
    "ConsensusPattern",
    "HierarchyPattern",
    "StigmergyPattern",
    "SpecialistPattern",
]
