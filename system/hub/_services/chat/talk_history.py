"""Persist ELLMOS Talk turns in the canonical chat snapshot store (PB-2, #3986).

Talk used to keep its history in process memory only; a restart erased it and it never
showed up in the history list. One transcript per persona, chat id ``talk-<persona>``.
"""
from __future__ import annotations

import logging
import re

from .session_store import SQLiteChatSessionStore

log = logging.getLogger(__name__)


def talk_chat_id(persona: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(persona or "buddha").strip().lower()).strip("-")[:60]
    return "talk-" + (slug or "buddha")


def _default_store() -> SQLiteChatSessionStore:
    from hub.bach_paths import BACH_DB
    return SQLiteChatSessionStore(BACH_DB)


def record_talk_turn(persona: str, prompt: str, reply: str, *, store: SQLiteChatSessionStore | None = None) -> None:
    """Append one spoken turn; a store failure is logged, never raised (the radio keeps talking)."""
    try:
        store = store or _default_store()
        chat_id = talk_chat_id(persona)
        messages = store.load(chat_id) + [{"role": "user", "content": prompt},
                                          {"role": "assistant", "content": reply}]
        store.save(chat_id, messages, name=f"Talk ({chat_id.removeprefix('talk-')})")
    except Exception as exc:  # noqa: BLE001 - persistence must not break a live turn
        log.warning("Talk-Verlauf konnte nicht gespeichert werden: %s", exc)
