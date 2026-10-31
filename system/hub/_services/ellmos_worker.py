# MODUL-ZUORDNUNG: Inhaltsschutz vor Werkzeugaufrufen
# SPDX-License-Identifier: MIT
# Herkunft: SentinelFleet (AGPL-3.0, commit e7f9c748); durch alleinigen
# Rechteinhaber Lukas unter MIT neu lizenziert; siehe NOTICE im Modulordner.
"""Adapter für das Shared Module ellmos-worker (Prüfkette vor Werkzeugaufrufen).

Lädt verification_chain.py des Shared Modules .MODULES/.CONTROL/ellmos-worker
als Modul bach_ellmos_worker_core und re-exportiert die Kern-API 1:1. Der
Pfad kann über die Umgebungsvariable BACH_ELLMOS_WORKER_MODULE überschrieben
werden. bach.py bindet diesen Adapter lazy über _ellmos_worker_module() ein.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_MODULE_NAME = "bach_ellmos_worker_core"
_MODULE_NAME_ENV = "BACH_ELLMOS_WORKER_MODULE"
_DEFAULT_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / ".MODULES"
    / ".CONTROL"
    / "ellmos-worker"
    / "verification_chain.py"
)


def _load():
    module_path = Path(os.environ.get(_MODULE_NAME_ENV) or _DEFAULT_MODULE_PATH)
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(_MODULE_NAME, None)
        raise
    return module


_mod = _load()

GENESIS = _mod.GENESIS
hash_line = _mod.hash_line
Stage = _mod.Stage
VerificationChain = _mod.VerificationChain
Ledger = _mod.Ledger
Checker = _mod.Checker
CheckOutcome = _mod.CheckOutcome
QuarantineChecker = _mod.QuarantineChecker
ScopeChecker = _mod.ScopeChecker
ContentGuardChecker = _mod.ContentGuardChecker
PermissionAdapter = _mod.PermissionAdapter

__all__ = [
    "GENESIS",
    "hash_line",
    "Stage",
    "VerificationChain",
    "Ledger",
    "Checker",
    "CheckOutcome",
    "QuarantineChecker",
    "ScopeChecker",
    "ContentGuardChecker",
    "PermissionAdapter",
]