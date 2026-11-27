# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone permissions module."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from permissions import PermissionPolicy, merge_settings_permissions, normalize_rules


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "permissions"
    assert data["selfcontained"] is True


def test_policy_deny_precedence_and_wildcards():
    policy = PermissionPolicy(
        allow_rules=["Bash(git *)", "Read(*)"],
        deny_rules=["Bash(git push*)"],
    )
    assert policy.evaluate("Bash(git status)").allowed is True
    push = policy.evaluate("Bash(git push origin main)")
    assert push.allowed is False
    assert push.reason == "explicit_deny"
    danger = policy.evaluate("Bash(rm -rf /)")
    assert danger.allowed is False
    assert danger.reason == "dangerous_builtin_block"


def test_merge_settings_permissions(tmp_path: Path):
    cfg = tmp_path / ".claude" / "settings.local.json"
    out = merge_settings_permissions(
        cfg,
        allow_add=["Read(*)", "Bash(python *)"],
        deny_add=["Bash(rm -rf *)"],
    )
    assert out["permissions"]["allow"] == ["Read(*)", "Bash(python *)"]
    assert normalize_rules(["a", " ", "a", "b"]) == ["a", "b"]
    assert cfg.is_file()
