# SPDX-License-Identifier: MIT
"""Empirischer Kurztest für verify_run mit None/[] binding und leerer allowed_tools."""
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("BACH_WORKTREE", "/Users/lukas/services/bach-worktrees/task-2245")

from hub._services import governance_binding as gb


def main():
    tmp = Path(tempfile.mkdtemp())
    global_file = tmp / "governance_global.json"
    global_file.write_text(json.dumps({
        "schema": "bach.governance-global.v1",
        "policy_refs": [],
        "forbidden_tools": ["web_fetch"],
    }), encoding="utf-8")
    os.environ["BACH_GOVERNANCE_GLOBAL_FILE"] = str(global_file)

    contract = gb.global_contract()
    print("global contract forbidden_tools:", contract["forbidden_tools"])

    # binding=None, allowed_tools=[] -> legacy early-return None
    result = gb.verify_run(None, [])
    print("verify_run(None, []) ->", result)
    assert result is None

    # binding=None, allowed_tools=None -> legacy early-return None
    result = gb.verify_run(None, None)
    print("verify_run(None, None) ->", result)
    assert result is None

    # binding=None, allowed_tools mit verbotenem Werkzeug -> violation
    try:
        gb.verify_run(None, ["web_fetch"])
        raise AssertionError("expected governance_global_violation")
    except gb.GovernanceRejected as exc:
        print("verify_run(None, ['web_fetch']) -> GovernanceRejected:", str(exc))
        assert str(exc) == "governance_global_violation"

    # valide Bindung, leere allowed_tools -> muss Bindung zurückgeben
    binding = {
        "schema": "bach.governance-binding.v1",
        "refs": [],
        "inherits": [],
        "global": contract,
        "profile": None,
        "tool_whitelist": None,
        "legacy": False,
    }
    binding["effective_sha256"] = gb._effective(binding)
    result = gb.verify_run(binding, [])
    print("verify_run(binding, []) ->", "ok" if result == binding else "mismatch")
    assert result == binding

    result = gb.verify_run(binding, None)
    print("verify_run(binding, None) ->", "ok" if result == binding else "mismatch")
    assert result == binding

    # allowed_tools mit Verbot -> violation auch bei gültiger Bindung
    try:
        gb.verify_run(binding, ["web_fetch"])
        raise AssertionError("expected governance_global_violation")
    except gb.GovernanceRejected as exc:
        print("verify_run(binding, ['web_fetch']) -> GovernanceRejected:", str(exc))
        assert str(exc) == "governance_global_violation"

    # Hash-Manipulation der gespeicherten Bindung -> governance_binding_invalid
    tampered = dict(binding)
    tampered["effective_sha256"] = "0" * 64
    try:
        gb.verify_run(tampered, [])
        raise AssertionError("expected governance_binding_invalid")
    except gb.GovernanceRejected as exc:
        print("verify_run(tampered, []) -> GovernanceRejected:", str(exc))
        assert str(exc) == "governance_binding_invalid"

    # Vertragsänderung seit Materialisierung -> governance_global_changed
    changed_contract = dict(contract)
    changed_contract["forbidden_tools"] = list(contract["forbidden_tools"]) + ["another_tool"]
    try:
        gb.verify_run(binding, [], contract=changed_contract)
        raise AssertionError("expected governance_global_changed")
    except gb.GovernanceRejected as exc:
        print("verify_run(binding, [], contract=changed) -> GovernanceRejected:", str(exc))
        assert str(exc) == "governance_global_changed"

    print("ALL EMPIRICAL CHECKS PASSED")


def test_empirical_verify_run():
    main()


if __name__ == "__main__":
    main()
