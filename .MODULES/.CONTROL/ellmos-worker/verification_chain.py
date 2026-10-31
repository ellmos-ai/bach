# MODUL-ZUORDNUNG: Inhaltsschutz vor Werkzeugaufrufen
# SPDX-License-Identifier: MIT
# Herkunft: SentinelFleet (AGPL-3.0, commit e7f9c748); durch alleinigen
# Rechteinhaber Lukas unter MIT neu lizenziert; siehe NOTICE im Modulordner.

"""Ellmos-Worker-Kernmodul (Entry-Point): Prüfkette je Werkzeugaufruf.

Kette: Quarantäne → Scope → content-guard → Erlaubnis → Ausführung. Jede
Stufe schreibt einen Hash-Ledger-Eintrag; die Ausführung erfolgt nur nach
vier bestandenen Prüfungen (fail-closed). Die Geschwister-Module ledger und
checkers werden unter kanonischen Namen geladen (sys.modules-Eintrag vor
exec, damit Cache und isinstance-Prüfungen stabil bleiben) und 1:1
re-exportiert.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from enum import Enum
from hashlib import sha256
from pathlib import Path


def _import_sibling(name):
    canonical = "ellmos_worker.%s" % name
    if canonical in sys.modules:
        return sys.modules[canonical]
    module_path = Path(__file__).resolve().parent / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location(canonical, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[canonical] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(canonical, None)
        raise
    return module


_ledger = _import_sibling("ledger")
_checkers = _import_sibling("checkers")

# 1:1-Re-Exporte der Geschwister-Module
GENESIS = _ledger.GENESIS
hash_line = _ledger.hash_line
Ledger = _ledger.Ledger
Checker = _checkers.Checker
CheckOutcome = _checkers.CheckOutcome
QuarantineChecker = _checkers.QuarantineChecker
ScopeChecker = _checkers.ScopeChecker
ContentGuardChecker = _checkers.ContentGuardChecker
PermissionAdapter = _checkers.PermissionAdapter

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


def canonical_json(value):
    """Deterministisches JSON (sortierte Schlüssel, kompakte Trennzeichen)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def normalize_args(args):
    """Normalisiert Aufrufargumente für deterministische Hashes."""
    if args is None:
        return []
    if isinstance(args, str):
        return [args]
    if isinstance(args, (list, tuple)):
        return list(args)
    if isinstance(args, dict):
        return dict(args)
    return [args]


def hash_args(args):
    """SHA-256 über das kanonische JSON der normalisierten Argumente."""
    return sha256(canonical_json(normalize_args(args)).encode("utf-8")).hexdigest()


class Stage(str, Enum):
    """Prüfstufen der Kette; Werte wandern 1:1 ins Ledger."""

    QUARANTINE = "quarantine"
    SCOPE = "scope"
    CONTENT_GUARD = "content_guard"
    PERMISSION = "permission"
    EXECUTION = "execution"


class VerificationChain:
    """Prüfkette je Werkzeugaufruf mit Hash-Ledger-Eintrag je Stufe."""

    def __init__(self, ledger, quarantine, scope, content_guard, permission, executor=None):
        self.ledger = ledger
        self.quarantine = quarantine
        self.scope = scope
        self.content_guard = content_guard
        self.permission = permission
        self.executor = executor
        self._check_stages = [
            (Stage.QUARANTINE, quarantine),
            (Stage.SCOPE, scope),
            (Stage.CONTENT_GUARD, content_guard),
            (Stage.PERMISSION, permission),
        ]

    def execute(self, tool_name, args=None, dry_run=False):
        """Führt die Prüfkette aus; Rückgabe ist der Tool-Returncode."""
        normalized = normalize_args(args)
        args_hash = hash_args(normalized)
        nachweis_id = str(uuid.uuid4())
        for stage, checker in self._check_stages:
            try:
                ok, grund = checker.check(tool_name, normalized)
            except Exception as exc:
                ok, grund = False, "%s: Checker-Ausnahme: %r" % (stage.value, exc)
            if ok:
                self.ledger.append(stage.value, tool_name, args_hash, "pass", nachweis_id)
            else:
                self.ledger.append(stage.value, tool_name, args_hash, "deny", nachweis_id, detail=grund)
                return 1
        if dry_run:
            self.ledger.append(
                Stage.EXECUTION.value, tool_name, args_hash, "dry_run", nachweis_id,
                detail="[DRY-RUN] Ausführung übersprungen",
            )
            return 0
        if self.executor is None:
            self.ledger.append(
                Stage.EXECUTION.value, tool_name, args_hash, "error", nachweis_id,
                detail="kein Executor konfiguriert (fail-closed)",
            )
            return 1
        try:
            rc = int(self.executor(tool_name, normalized))
        except Exception as exc:
            self.ledger.append(
                Stage.EXECUTION.value, tool_name, args_hash, "error", nachweis_id,
                detail="execution: Executor-Ausnahme: %r" % exc,
            )
            return 1
        self.ledger.append(
            Stage.EXECUTION.value, tool_name, args_hash, "executed", nachweis_id,
            detail="returncode=%d" % rc,
        )
        return rc