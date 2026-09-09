# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Machine-readable examples must stay invariant across translated Help files."""

import json
import re
from pathlib import Path

import pytest


HELP_DIR = Path(__file__).parent.parent / "docs" / "help"
LANGUAGES = {
    "de": "",
    "en": "_en",
    "es": "_es",
    "ja": "_ja",
    "ru": "_ru",
    "zh": "_zh",
}
API_PAYLOADS = {
    "backend": {"name": "claude", "model": "opus"},
    "mode": {"mode": "safe"},
    "model": {"model": "qwen3.5:35b-a3b"},
    "think": {"think": True},
    "max_tool_rounds": {"rounds": 10},
    "chat": {"prompt": "...", "chat_id": "..."},
}
CONFIG_PAYLOAD = {
    "bot_token": "...",
    "owner_id": "...",
    "backend": {
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "default_model": "qwen3.5:35b-a3b",
    },
}
REQUIRED_TOKENS = (
    "python start/startspine.py start --tray",
    "python start/startspine.py start --tray --host bach-server.local",
    "hub/_services/chat/telegram_chat.py",
    "hub/_services/chat/chat_runtime.py",
    "hub/_services/llm/model_backend.py",
    "hub/_services/chat/chat_tray.py",
    "~/.config/bach/telegram_chat.json",
    "~/.credentials/telegram_bot_token",
    "~/.credentials/telegram_owner_id",
    "data/system_prompt_buddha.txt",
    "BACH_HOST",
    "BACH_NO_BROWSER",
)


def _json_object_after_config_path(text: str) -> dict:
    marker = "~/.config/bach/telegram_chat.json"
    offset = 0
    while True:
        marker_pos = text.find(marker, offset)
        if marker_pos < 0:
            raise AssertionError("Konfigurationsbeispiel fehlt")
        start = text.find("{", marker_pos, marker_pos + 180)
        if start >= 0:
            break
        offset = marker_pos + len(marker)

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:index + 1])
    raise AssertionError("Konfigurationsbeispiel ist nicht abgeschlossen")


@pytest.mark.parametrize("language,suffix", LANGUAGES.items())
def test_bach_chat_machine_examples_are_language_invariant(language, suffix):
    text = (HELP_DIR / f"bach_chat{suffix}.txt").read_text(encoding="utf-8")

    for endpoint, expected in API_PAYLOADS.items():
        match = re.search(
            rf"POST\s+/api/{re.escape(endpoint)}\b[^\n]*?(\{{[^\n]+\}})",
            text,
        )
        assert match, f"{language}: API-Beispiel für {endpoint} fehlt"
        assert json.loads(match.group(1)) == expected

    assert _json_object_after_config_path(text) == CONFIG_PAYLOAD
    for token in REQUIRED_TOKENS:
        assert token in text, f"{language}: unveränderliches Beispiel fehlt: {token}"


@pytest.mark.parametrize("suffix", LANGUAGES.values())
def test_install_startspine_examples_are_language_invariant(suffix):
    text = (HELP_DIR / f"install{suffix}.txt").read_text(encoding="utf-8")
    assert "python start/startspine.py start --chat --gui" in text
    assert "python start/startspine.py status --json" in text
    assert "0.0.0.0" in text
