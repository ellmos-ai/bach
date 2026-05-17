# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Self-Test: LLM-Selbsterfahrungsprotokoll (E-Tests)

Generiert Testprompts fuer LLM-basierte QA von BACH.
Ein frischer Agent fuehrt die Tests durch und bewertet das System.

Usage:
    python -m tools.self_test [--profile standard|quick|full]
    bach self-test [standard|quick|full]

Portiert aus: .TESTS/system_diff_tests/testing/e_tests/
"""

from pathlib import Path

SELF_TEST_DIR = Path(__file__).parent
