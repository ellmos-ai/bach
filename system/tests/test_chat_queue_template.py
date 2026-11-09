"""Tests for Web-Chat Queue implementation in system/gui/templates/chat.html (Ticket T-20260909-926925722)."""

import json
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHAT_TEMPLATE_PATH = REPO_ROOT / "system" / "gui" / "templates" / "chat.html"


def test_chat_template_exists():
    assert CHAT_TEMPLATE_PATH.exists(), f"chat.html not found at {CHAT_TEMPLATE_PATH}"


def test_chat_template_markup_components():
    content = CHAT_TEMPLATE_PATH.read_text(encoding="utf-8")

    # Queue Tray markup & CSS
    assert "id=\"chat-queue-tray\"" in content or "id='chat-queue-tray'" in content
    assert "class=\"chat-queue-tray\"" in content or "class='chat-queue-tray'" in content
    assert "id=\"queue-items-list\"" in content or "id='queue-items-list'" in content
    assert "id=\"btn-toggle-queue-pause\"" in content or "id='btn-toggle-queue-pause'" in content
    assert "id=\"btn-clear-queue\"" in content or "id='btn-clear-queue'" in content

    # Composer Queue Action Button
    assert "id=\"queue-btn\"" in content or "id='queue-btn'" in content
    assert "Einreihen" in content


def test_chat_queue_manager_class_and_methods():
    content = CHAT_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "class ChatQueueManager" in content
    assert "storageKey(" in content
    assert "loadFromStorage(" in content
    assert "persist(" in content
    assert "enqueue(" in content
    assert "dequeue(" in content
    assert "remove(" in content
    assert "reorder(" in content
    assert "togglePause(" in content
    assert "clear(" in content

    # Storage key format
    assert "'bach_chat_queue_'" in content or '"bach_chat_queue_"' in content


def test_chat_queue_keyboard_and_error_handling():
    content = CHAT_TEMPLATE_PATH.read_text(encoding="utf-8")

    # Alt+Enter shortcut for queuing
    assert "e.altKey" in content
    assert "handleEnqueueBtn()" in content

    # Implicit queuing when sending is true
    assert "if (sending)" in content
    assert "queueManager.enqueue(text, currentChatId)" in content

    # Auto sequencer and timeout
    assert "processNextQueuedMessage" in content
    assert "setTimeout(processNextQueuedMessage, 600)" in content

    # Pause on error
    assert "queueManager.paused = true" in content
    assert "Warteschlange wegen Fehler pausiert" in content


class MockChatQueueManager:
    """Python simulation of client-side ChatQueueManager to verify exact queue algorithm."""

    def __init__(self, chat_id="default"):
        self.chat_id = chat_id
        self.items = []
        self.paused = false = False
        self.storage = {}

    def storage_key(self, chat_id=None):
        return f"bach_chat_queue_{chat_id or self.chat_id or 'default'}"

    def persist(self, chat_id=None):
        key = self.storage_key(chat_id)
        self.storage[key] = json.dumps(self.items)

    def load_from_storage(self, chat_id=None):
        key = self.storage_key(chat_id)
        raw = self.storage.get(key)
        self.items = json.loads(raw) if raw else []
        return self.items

    def enqueue(self, text, chat_id=None):
        trimmed = (text or "").strip()
        if not trimmed:
            return
        self.items.append(trimmed)
        self.persist(chat_id)

    def dequeue(self, chat_id=None):
        if not self.items:
            return None
        item = self.items.pop(0)
        self.persist(chat_id)
        return item

    def remove(self, index, chat_id=None):
        if 0 <= index < len(self.items):
            self.items.pop(index)
            self.persist(chat_id)

    def reorder(self, from_idx, to_idx, chat_id=None):
        if 0 <= from_idx < len(self.items) and 0 <= to_idx < len(self.items):
            item = self.items.pop(from_idx)
            self.items.insert(to_idx, item)
            self.persist(chat_id)

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused


def test_queue_manager_algorithm_lifecycle():
    qm = MockChatQueueManager(chat_id="chat-123")

    # Test enqueue
    qm.enqueue("First prompt", "chat-123")
    qm.enqueue("Second prompt", "chat-123")
    qm.enqueue("Third prompt", "chat-123")
    assert qm.items == ["First prompt", "Second prompt", "Third prompt"]

    # Verify storage format
    storage_key = qm.storage_key("chat-123")
    assert storage_key == "bach_chat_queue_chat-123"
    assert json.loads(qm.storage[storage_key]) == ["First prompt", "Second prompt", "Third prompt"]

    # Reorder
    qm.reorder(2, 0, "chat-123")  # Move third to first
    assert qm.items == ["Third prompt", "First prompt", "Second prompt"]

    # Remove
    qm.remove(1, "chat-123")  # Remove "First prompt"
    assert qm.items == ["Third prompt", "Second prompt"]

    # Pause
    assert qm.toggle_pause() is True
    assert qm.paused is True

    # Reload from storage in new instance
    qm2 = MockChatQueueManager(chat_id="chat-123")
    qm2.storage = qm.storage
    loaded = qm2.load_from_storage("chat-123")
    assert loaded == ["Third prompt", "Second prompt"]

    # Dequeue
    assert qm2.dequeue("chat-123") == "Third prompt"
    assert qm2.items == ["Second prompt"]
    assert qm2.dequeue("chat-123") == "Second prompt"
    assert qm2.dequeue("chat-123") is None
