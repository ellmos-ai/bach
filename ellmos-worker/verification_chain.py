# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
ellmos-worker.verification_chain – Fail-closed Verifizierungskette
===================================================================

5 sequentielle Stufen (Quarantäne → Scope → Content-Guard → Erlaubnis →
Ausführung).  Jede Stufe darf nur ALLOW (oder DRY_RUN in Stufe 5)
zurückgeben, damit die nächste Stufe erreicht wird.  Jeder Verstoß
führt zu DENY oder ERROR und bricht die Kette sofort ab (fail-closed).

Die Kette erzeugt pro Stufe einen Ledger-Eintrag (JSON-serialisierbar),
der in eine aufrufenseitige Liste geschrieben wird.

Task: 2505
Version: 1.0.0
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

# ── Sandbox (best-effort Import) ────────────────────────────────────
try:
    from core.sandbox import SandboxLimits, run_isolated  # type: ignore
    _HAS_SANDBOX = True
except Exception:  # pragma: no cover
    SandboxLimits = None  # type: ignore[assignment]
    run_isolated = None   # type: ignore[assignment]
    _HAS_SANDBOX = False

# ── Controlcenter Permission (best-effort Import) ───────────────────
try:
    # Externes Repo: ellmos-controlcenter-mcp
    from ellmos_controlcenter_mcp.controlcenter import (  # type: ignore
        evaluate_permission as controlcenter_evaluate_permission,
    )
    _HAS_CONTROLCENTER = True
except Exception:
    try:
        # Alternative: lokales Modul
        import controlcenter_evaluate_permission as _ccmod  # type: ignore
        controlcenter_evaluate_permission = _ccmod.evaluate_permission
        _HAS_CONTROLCENTER = True
    except Exception:
        controlcenter_evaluate_permission = None  # type: ignore[assignment]
        _HAS_CONTROLCENTER = False


# ── Verdict ─────────────────────────────────────────────────────────

class Verdict(Enum):
    """Mögliche Stufen-Ergebnisse."""
    ALLOW   = "allow"
    DENY    = "deny"
    ERROR   = "error"
    DRY_RUN = "dry_run"


# ── Ledger-Eintrag ──────────────────────────────────────────────────

@dataclass
class LedgerEntry:
    """Einzelner Ledger-Eintrag pro Stufe.

    Felder:
        timestamp  – ISO-8601-String (optional, beim Serialisieren
                     gefüllt)
        stage      – Name der Stufe
        verdict    – Verdict-String
        detail     – Freitext-Explanation
        tool_name  – Name des Tools
        tool_args  – Argumente des Tools
        dry_run    – ob im Dry-Run-Modus
        metadata   – zusätzliche frei formbare Daten
    """
    stage: str
    verdict: str
    detail: str
    tool_name: str
    tool_args: List[str] = field(default_factory=list)
    dry_run: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def to_json(entries: List["LedgerEntry"]) -> str:
        return json.dumps([e.to_dict() for e in entries], ensure_ascii=False)


# ── StageResult ─────────────────────────────────────────────────────

@dataclass
class StageResult:
    """Ergebnis einer einzelnen Stufe (bzw. der gesamten Kette)."""
    stage: str
    verdict: Verdict
    detail: str
    ledger_entry: LedgerEntry

    @property
    def blocked(self) -> bool:
        return self.verdict in (Verdict.DENY, Verdict.ERROR)


# ── Stufenklassen ───────────────────────────────────────────────────

class _Stage:
    """Basis für alle Stufen.  Subklassen überschreiben `evaluate`."""

    name: str = ""

    def evaluate(
        self,
        tool_name: str,
        tool_args: List[str],
        ctx: Dict[str, Any],
    ) -> StageResult:
        raise NotImplementedError


class QuarantineStage(_Stage):
    """Stufe 1 – Quarantäne: Tool muss in einer vertrauenswürdigen
    Liste (bzw. unter TOOLS_DIR) liegen."""

    name = "quarantine"

    def evaluate(
        self,
        tool_name: str,
        tool_args: List[str],
        ctx: Dict[str, Any],
    ) -> StageResult:
        allowed = ctx.get("quarantine_whitelist")
        # Wenn keine Whitelist gesetzt ist, wird nur geprüft, ob der
        # Name nicht in einer Blacklist steht.
        blacklist: set = ctx.get("quarantine_blacklist", set())
        if tool_name.lower() in blacklist:
            return self._fail(
                Verdict.DENY,
                f"Tool '{tool_name}' ist auf der Quarantaene-Blacklist.",
            )
        if allowed is not None and tool_name not in allowed:
            return self._fail(
                Verdict.DENY,
                f"Tool '{tool_name}' ist nicht in der Quarantaene-Whitelist.",
            )
        return self._ok("Tool durch Quarantae-Pruefung.")

    def _fail(self, v: Verdict, d: str) -> StageResult:
        le = LedgerEntry(self.name, v.value, d, "", [], False,
                         {"reason": "quarantine"})
        return StageResult(self.name, v, d, le)

    def _ok(self, d: str) -> StageResult:
        le = LedgerEntry(self.name, Verdict.ALLOW.value, d, "", [], False,
                         {"reason": "quarantine_pass"})
        return StageResult(self.name, Verdict.ALLOW, d, le)


class ScopeStage(_Stage):
    """Stufe 2 – Scope: Prüft, dass die Argumente dem erlaubten
    Scope entsprechen (Pfade, Flags)."""

    name = "scope"

    def evaluate(
        self,
        tool_name: str,
        tool_args: List[str],
        ctx: Dict[str, Any],
    ) -> StageResult:
        allowed_paths: List[Path] = ctx.get("scope_allowed_paths", [])
        if not allowed_paths:
            return self._ok("Keine Scope-Beschraenkung konfiguriert.")
        for arg in tool_args:
            p = Path(arg)
            if p.is_absolute() and not any(
                p.is_relative_to(ap) for ap in allowed_paths
            ):
                return self._fail(
                    Verdict.DENY,
                    f"Argument '{arg}' liegt auerhalb der erlaubten Scope-Pfade.",
                )
        return self._ok(f"Alle Argumente innerhalb von {len(allowed_paths)} Scope-Pfad(en).")

    def _fail(self, v: Verdict, d: str) -> StageResult:
        le = LedgerEntry(self.name, v.value, d, "", [], False,
                         {"reason": "scope_violation"})
        return StageResult(self.name, v, d, le)

    def _ok(self, d: str) -> StageResult:
        le = LedgerEntry(self.name, Verdict.ALLOW.value, d, "", [], False,
                         {"reason": "scope_pass"})
        return StageResult(self.name, Verdict.ALLOW, d, le)


class ContentGuardStage(_Stage):
    """Stufe 3 – Content-Guard: Prüf auf gefährliche Patterns in den
    Argumenten (rm -rf, base64-encoded payloads, Shell-Inject)."""

    name = "content_guard"

    _FORBIDDEN_PATTERNS = (
        "rm -rf /",
        "rm -rf ~",
        "dd if=",
        "mkfs",
        "; rm",
        "| rm",
        "$(",
        "`",
        "&& rm",
        "base64 -d",
    )

    def evaluate(
        self,
        tool_name: str,
        tool_args: List[str],
        ctx: Dict[str, Any],
    ) -> StageResult:
        for arg in tool_args:
            lower = arg.lower()
            for pat in self._FORBIDDEN_PATTERNS:
                if pat in lower:
                    return self._fail(
                        Verdict.DENY,
                        f"Gefaehrliches Pattern '{pat}' in Argument erkannt.",
                    )
        return self._ok("Kein gefaehrliches Content-Muster erkannt.")

    def _fail(self, v: Verdict, d: str) -> StageResult:
        le = LedgerEntry(self.name, v.value, d, "", [], False,
                         {"reason": "content_guard_hit"})
        return StageResult(self.name, v, d, le)

    def _ok(self, d: str) -> StageResult:
        le = LedgerEntry(self.name, Verdict.ALLOW.value, d, "", [], False,
                         {"reason": "content_guard_pass"})
        return StageResult(self.name, Verdict.ALLOW, d, le)


class PermissionStage(_Stage):
    """Stufe 4 – Erlaubnis via `controlcenter_evaluate_permission`.
    Bei fehlendem Modul → fail-closed DENY."""

    name = "permission"

    def evaluate(
        self,
        tool_name: str,
        tool_args: List[str],
        ctx: Dict[str, Any],
    ) -> StageResult:
        if not _HAS_CONTROLCENTER or controlcenter_evaluate_permission is None:
            # fail-closed: Modul fehlt → verweigern
            return self._fail(
                Verdict.DENY,
                "controlcenter_evaluate_permission nicht verfuegbar – "
                "fail-closed DENY.",
            )
        try:
            result = controlcenter_evaluate_permission(
                tool_name, tool_args, ctx.get("session_id", ""),
            )
            if getattr(result, "allowed", False) or result is True:
                return self._ok(
                    f"Erlaubnis erteilt: {getattr(result, 'detail', '')}"
                )
            return self._fail(
                Verdict.DENY,
                f"Erlaubnis verweigert: {getattr(result, 'detail', '')}",
            )
        except Exception as exc:
            return self._fail(
                Verdict.ERROR,
                f"Ausnahme bei Erlaubnispruefung: {exc!r}",
            )

    def _fail(self, v: Verdict, d: str) -> StageResult:
        le = LedgerEntry(self.name, v.value, d, "", [], False,
                         {"reason": "permission"})
        return StageResult(self.name, v, d, le)

    def _ok(self, d: str) -> StageResult:
        le = LedgerEntry(self.name, Verdict.ALLOW.value, d, "", [], False,
                         {"reason": "permission_granted"})
        return StageResult(self.name, Verdict.ALLOW, d, le)


class ExecutionStage(_Stage):
    """Stufe 5 – Ausführung: `subprocess.run` oder `run_isolated`
    mit Sandbox-Limits."""

    name = "execution"

    def evaluate(
        self,
        tool_name: str,
        tool_args: List[str],
        ctx: Dict[str, Any],
    ) -> StageResult:
        tool_file: Optional[Path] = ctx.get("tool_file")
        if tool_file is None or not Path(tool_file).exists():
            return self._fail(
                Verdict.ERROR,
                "Tool-Datei nicht gefunden oder nicht uebergeben.",
            )
        import subprocess
        limits: Any = ctx.get("sandbox_limits")
        cmd: List[str] = [sys.executable, str(tool_file)] + tool_args
        cwd = str(ctx.get("cwd", Path.cwd()))
        try:
            if _HAS_SANDBOX and limits is not None:
                result = run_isolated(cmd, limits=limits)
                rc = result.returncode
                timed_out = getattr(result, "timed_out", False)
                mem_exceeded = getattr(result, "memory_exceeded", False)
            else:
                result = subprocess.run(cmd, cwd=cwd, capture_output=True,
                                       text=True)
                rc = result.returncode
                timed_out = False
                mem_exceeded = False
        except Exception as exc:
            return self._fail(Verdict.ERROR, f"Ausfuehrungsfehler: {exc!r}")

        if timed_out or mem_exceeded:
            return self._fail(
                Verdict.DENY,
                f"Sandbox-Grenzen ueberschritten "
                f"(timeout={timed_out}, memory={mem_exceeded}).",
            )
        if rc != 0:
            return StageResult(
                self.name,
                Verdict.DENY,
                f"Tool lieferte Returncode {rc}.",
                LedgerEntry(self.name, Verdict.DENY.value,
                            f"rc={rc}", tool_name, tool_args, False,
                            {"returncode": rc, "timed_out": timed_out,
                             "memory_exceeded": mem_exceeded}),
            )
        return StageResult(
            self.name,
            Verdict.ALLOW,
            f"Tool erfolgreich (rc={rc}).",
            LedgerEntry(self.name, Verdict.ALLOW.value,
                        f"rc={rc}", tool_name, tool_args, False,
                        {"returncode": rc, "timed_out": timed_out,
                         "memory_exceeded": mem_exceeded}),
        )

    def _fail(self, v: Verdict, d: str) -> StageResult:
        le = LedgerEntry(self.name, v.value, d, "", [], False,
                         {"reason": "execution"})
        return StageResult(self.name, v, d, le)


# ── VerificationChain ───────────────────────────────────────────────

class VerificationChain:
    """Feste 5-Stufen-Kette (fail-closed).

    Nutze:
        chain = VerificationChain()
        result = chain.run("db_check", ["--dry-run"], dry_run=True)
        if result.blocked:
            ...
    """

    # Feste Reihenfolge – keine Konfiguration, keine Ueberschreibung
    _STAGES: tuple = (
        QuarantineStage(),
        ScopeStage(),
        ContentGuardStage(),
        PermissionStage(),
        ExecutionStage(),
    )

    def __init__(
        self,
        quarantine_blacklist: Optional[set] = None,
        quarantine_whitelist: Optional[set] = None,
        scope_allowed_paths: Optional[Sequence[Path]] = None,
        sandbox_limits: Any = None,
        session_id: str = "",
    ) -> None:
        self.ctx: Dict[str, Any] = {
            "quarantine_blacklist": quarantine_blacklist or set(),
            "quarantine_whitelist": quarantine_whitelist,
            "scope_allowed_paths": list(scope_allowed_paths or []),
            "sandbox_limits": sandbox_limits,
            "session_id": session_id,
        }
        self._ledger: List[LedgerEntry] = []

    def __setattr__(self, name: str, value: Any) -> None:
        """Fail-closed: Stufen-Konfiguration ist fix."""
        if name == "_STAGES":
            raise AttributeError(
                "_STAGES ist unveraenderlich (fail-closed): "
                "Neuzuweisung nicht erlaubt."
            )
        super().__setattr__(name, value)

    # ── Public API ──────────────────────────────────────────────────

    def run(
        self,
        tool_name: str,
        tool_args: Sequence[str],
        dry_run: bool = False,
        **ctx_extra: Any,
    ) -> StageResult:
        """Führt alle 5 Stufen aus.

        Bei dry_run=True wird Stufe 5 (ExecutionStage) übersprungen;
        ein DRY_RUN-Ledger-Eintrag wird stattdessen geschrieben.
        Bei DENY/ERROR bricht die Kette sofort ab (fail-closed).
        """
        ctx = {**self.ctx, **ctx_extra}
        args = list(tool_args)

        for i, stage in enumerate(self._STAGES, 1):
            # Dry-Run: Stufe 5 überspringen
            if dry_run and stage.name == "execution":
                le = LedgerEntry(
                    stage.name, Verdict.DRY_RUN.value,
                    "Dry-Run: Stufe uebersprungen.",
                    tool_name, args, True,
                    {"reason": "dry_run_skip"},
                )
                self._ledger.append(le)
                return StageResult(stage.name, Verdict.DRY_RUN,
                                   "Dry-Run: Ausführung übersprungen.", le)

            result = stage.evaluate(tool_name, args, ctx)
            self._ledger.append(result.ledger_entry)
            if result.blocked:
                return result  # fail-closed

        # Alle Stufen ALLOW
        return StageResult("complete", Verdict.ALLOW,
                           "Alle Stufen bestanden.",
                           self._ledger[-1])

    @property
    def ledger(self) -> List[LedgerEntry]:
        return list(self._ledger)

    @property
    def ledger_json(self) -> str:
        return LedgerEntry.to_json(self._ledger)
