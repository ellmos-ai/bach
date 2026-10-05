#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: ocean.k9_boundary
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version ocean.k9_boundary

Description:
    Ocean K9-BOUNDARY Modul: Dateisystem-Schicht (open-ocean) mit
    reversiblem 2-Phasen Action Journal.  Bietet transaktionale Datei-
    operationen über Preflight, Prepare, Execute und automatischen
    Rollback mit SHA-256 Integritätsprüfung.

Usage:
    from tools.ocean.k9_boundary import ActionJournal
    tx = ActionJournal(Path("/tmp/workspace"))
    tx.add_copy(src, dst)
    tx.prepare()
    tx.execute()
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

from .action_journal import ActionJournal, FileOp, JournalState

__all__ = ["ActionJournal", "FileOp", "JournalState"]
