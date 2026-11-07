# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit test for standalone prompt module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import prompt


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "prompt"
    assert data["selfcontained"] is True


def test_prompt_tags_serialization():
    tags = prompt.serialize_prompt_tags(["alpha", "beta"])
    assert tags == '["alpha", "beta"]'
    assert prompt.prompt_tags_text(tags) == "alpha, beta"
    assert prompt.serialize_prompt_tags("x, y") == '["x", "y"]'


def test_prompt_core_crud_and_sync(tmp_path):
    db_file = tmp_path / "test_prompts.db"
    core = prompt.PromptCore(db_file)
    p_id = core.add("TestA", "Text A", category="Dev", tags=["qa"])
    assert p_id > 0
    p = core.get("TestA")
    assert p["name"] == "TestA"
    assert p["category"] == "Dev"

    # Test sync with external library
    lib_file = tmp_path / "library.json"
    lib_file.write_text(json.dumps({
        "items": [
            {"id": "ext1", "item_type": "PROMPT", "name": "ExtPrompt", "content": "External Text"}
        ]
    }), encoding="utf-8")

    res = core.sync_promptboard(lib_file, dry_run=False)
    assert res["ok"] is True
    assert res["imported"] == 1
    assert res["exported"] == 1
    assert res["total_bach"] == 2
    assert res["total_promptboard"] == 2
