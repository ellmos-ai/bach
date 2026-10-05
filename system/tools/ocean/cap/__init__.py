#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: ocean.cap
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version ocean.cap

Description:
    Ocean CAP-Module (Compliance & Automation Pipeline).
    Aktuell enthalten:
    - doc_handler: §14 Abs. 4 UStG Rechnungsprüfung & Bestreitungsbrief-Generator.
    - compliance: Compliance-Schema-Registry und Checklisten-Adapter.

Usage:
    from tools.ocean.cap import doc_handler, compliance
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

from . import compliance
from . import doc_handler

__all__ = ["compliance", "doc_handler"]
