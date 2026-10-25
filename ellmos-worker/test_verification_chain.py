# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests für ellmos-worker.verification_chain (Task 2505).

Ausführung:
    python -m pytest ellmos-worker/test_verification_chain.py -v
"""
import sys
import pytest
from pathlib import Path

# Worktree-Pfad an sys.path hängen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ellmos_worker.verification_chain import (
    VerificationChain,
    Verdict,
    StageResult,
    QuarantineStage,
    ScopeStage,
    ContentGuardStage,
    PermissionStage,
    ExecutionStage,
    LedgerEntry,
)


# ── QuarantineStage ─────────────────────────────────────────────────

class TestQuarantineStage:
    def test_pass(self):
        s = QuarantineStage()
        r = s.evaluate("db_check", [], {})
        assert r.verdict == Verdict.ALLOW
        assert r.stage == "quarantine"

    def test_blacklist_deny(self):
        s = QuarantineStage()
        ctx = {"quarantine_blacklist": {"danger_tool"}}
        r = s.evaluate("danger_tool", [], ctx)
        assert r.verdict == Verdict.DENY
        assert r.blocked

    def test_whitelist_deny(self):
        s = QuarantineStage()
        ctx = {"quarantine_whitelist": {"allowed_tool"}}
        r = s.evaluate("other_tool", [], ctx)
        assert r.verdict == Verdict.DENY


# ── ScopeStage ──────────────────────────────────────────────────────

class TestScopeStage:
    def test_no_paths_pass(self):
        s = ScopeStage()
        r = s.evaluate("tool", ["/some/arg"], {})
        assert r.verdict == Verdict.ALLOW

    def test_out_of_scope_deny(self):
        s = ScopeStage()
        ctx = {"scope_allowed_paths": [Path("/allowed/dir")]}
        r = s.evaluate("tool", ["/etc/passwd"], ctx)
        assert r.verdict == Verdict.DENY
        assert r.blocked


# ── ContentGuardStage ───────────────────────────────────────────────

class TestContentGuardStage:
    def test_clean_pass(self):
        s = ContentGuardStage()
        r = s.evaluate("tool", ["--verbose", "file.txt"], {})
        assert r.verdict == Verdict.ALLOW

    def test_dangerous_pattern_deny(self):
        s = ContentGuardStage()
        r = s.evaluate("tool", ["rm -rf /"], {})
        assert r.verdict == Verdict.DENY
        assert r.blocked

    def test_shell_injection_deny(self):
        s = ContentGuardStage()
        r = s.evaluate("tool", ["echo $(whoami)"], {})
        assert r.verdict == Verdict.DENY


# ── PermissionStage ─────────────────────────────────────────────────

class TestPermissionStage:
    def test_no_controlcenter_deny(self):
        """Ohne controlcenter_evaluate_permission → fail-closed DENY."""
        s = PermissionStage()
        r = s.evaluate("tool", [], {})
        # In der Testumgebung ist das Modul nicht importierbar
        assert r.verdict == Verdict.DENY
        assert "fail-closed" in r.detail.lower()

    def test_ledger_entry_present(self):
        s = PermissionStage()
        r = s.evaluate("tool", [], {})
        assert isinstance(r.ledger_entry, LedgerEntry)
        assert r.ledger_entry.stage == "permission"


# ── ExecutionStage ──────────────────────────────────────────────────

class TestExecutionStage:
    def test_missing_tool_file(self):
        s = ExecutionStage()
        r = s.evaluate("ghost", [], {"tool_file": "/nonexistent/ghost.py"})
        assert r.verdict == Verdict.ERROR
        assert r.blocked

    def test_ledger_entry(self):
        s = ExecutionStage()
        r = s.evaluate("ghost", [], {})
        assert r.stage == "execution"
        assert isinstance(r.ledger_entry, LedgerEntry)


# ── VerificationChain End-to-End ────────────────────────────────────

class TestVerificationChain:
    def test_dry_run_skips_execution(self):
        chain = VerificationChain()
        # Quarantäne, Scope, ContentGuard sollten ALLOW,
        # Permission fehlt → DENY (fail-closed), Execution nicht erreicht
        result = chain.run("some_tool", ["arg1"], dry_run=True)
        # Da PermissionStage fail-closed DENY liefert (kein Controlcenter),
        # bricht die Kette an Stufe 4 ab – Execution nie erreicht.
        assert result.verdict == Verdict.DENY
        assert result.stage == "permission"

    def test_ledger_written(self):
        chain = VerificationChain()
        chain.run("some_tool", ["arg1"], dry_run=True)
        ledger = chain.ledger
        assert len(ledger) >= 3  # Quarantäne + Scope + ContentGuard + Permission
        assert all(isinstance(e, LedgerEntry) for e in ledger)

    def test_ledger_json(self):
        chain = VerificationChain()
        chain.run("some_tool", [], dry_run=True)
        js = chain.ledger_json
        assert isinstance(js, str)
        # gültiges JSON
        import json
        data = json.loads(js)
        assert isinstance(data, list)

    def test_fail_closed_blocks_execution(self):
        """Wenn irgendeine Stufe DENY/ERROR, bricht die Kette ab."""
        chain = VerificationChain(
            quarantine_blacklist={"blocked_tool"},
        )
        result = chain.run("blocked_tool", [], dry_run=True)
        assert result.verdict == Verdict.DENY
        assert result.stage == "quarantine"
        # Execution sollte nie im Ledger auftauchen
        stages_seen = [e.stage for e in chain.ledger]
        assert "execution" not in stages_seen

    def test_five_stages_defined(self):
        chain = VerificationChain()
        assert len(chain._STAGES) == 5
        names = [s.name for s in chain._STAGES]
        assert names == ["quarantine", "scope", "content_guard",
                         "permission", "execution"]

    def test_stages_are_immutable_tuple(self):
        chain = VerificationChain()
        with pytest.raises((AttributeError, TypeError)):
            chain._STAGES = []  # type: ignore


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
