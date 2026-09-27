# -*- coding: utf-8 -*-
"""Befund C: _owner_check() war fail-open (leere OWNER_ID -> jeder darf).
Diese Tests decken den Fix ab: fail-closed bei leerer OWNER_ID, und ALLE
in main() registrierten Handler laufen durch _require_owner()."""
import ast
import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("telegram", reason="braucht python-telegram-bot")

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import hub._services.chat.telegram_chat as tg


def _fake_update(chat_id):
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id))


class TestOwnerCheckFailClosed:
    def test_empty_owner_id_rejects_everyone(self, monkeypatch):
        monkeypatch.setattr(tg, "OWNER_ID", "")
        assert tg._owner_check(_fake_update(123456)) is False
        assert tg._owner_check(_fake_update(0)) is False

    def test_matching_chat_id_allowed(self, monkeypatch):
        monkeypatch.setattr(tg, "OWNER_ID", "42")
        assert tg._owner_check(_fake_update(42)) is True

    def test_non_matching_chat_id_rejected(self, monkeypatch):
        monkeypatch.setattr(tg, "OWNER_ID", "42")
        assert tg._owner_check(_fake_update(999)) is False


class TestRequireOwnerWrapsCallback:
    def test_blocks_when_not_owner(self, monkeypatch):
        asyncio.run(self._test_blocks_when_not_owner(monkeypatch))

    async def _test_blocks_when_not_owner(self, monkeypatch):
        monkeypatch.setattr(tg, "OWNER_ID", "42")
        called = {"inner": False}

        async def inner(update, ctx):
            called["inner"] = True

        replies = []

        class FakeMessage:
            async def reply_text(self, text):
                replies.append(text)

        update = SimpleNamespace(effective_chat=SimpleNamespace(id=999), effective_message=FakeMessage())
        await tg._require_owner(inner)(update, None)
        assert called["inner"] is False
        assert replies == ["Zugriff nur für den Owner."]

    def test_calls_through_when_owner(self, monkeypatch):
        asyncio.run(self._test_calls_through_when_owner(monkeypatch))

    async def _test_calls_through_when_owner(self, monkeypatch):
        monkeypatch.setattr(tg, "OWNER_ID", "42")
        called = {"inner": False}

        async def inner(update, ctx):
            called["inner"] = True

        update = SimpleNamespace(effective_chat=SimpleNamespace(id=42), effective_message=None)
        await tg._require_owner(inner)(update, None)
        assert called["inner"] is True


class TestEveryRegisteredHandlerIsWrapped:
    """Root-cause-Coverage: parst main()'s Quelltext und verlangt, dass
    JEDER add_handler(...)-Aufruf sein Callback in _require_owner(...)
    wrappt. Verhindert, dass Handler Nr. 20 den Guard wieder vergisst
    (Befund C: 14 von 19 Handlern hatten frueher gar keinen Check)."""

    def test_all_add_handler_calls_wrap_with_require_owner(self):
        src = inspect.getsource(tg.register_handlers)
        tree = ast.parse(src)
        add_handler_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_handler"
        ]
        assert len(add_handler_calls) >= 19, "weniger Handler gefunden als erwartet - main() umgebaut?"

        def _uses_require_owner(handler_ctor_call: ast.Call) -> bool:
            # handler_ctor_call ist z.B. CommandHandler("start", <callback>)
            # oder MessageHandler(<filter>, <callback>) - Callback ist immer
            # das letzte Positionsargument.
            if not handler_ctor_call.args:
                return False
            callback_arg = handler_ctor_call.args[-1]
            return (
                isinstance(callback_arg, ast.Call)
                and isinstance(callback_arg.func, ast.Name)
                and callback_arg.func.id == "_require_owner"
            )

        unwrapped = []
        for call in add_handler_calls:
            handler_ctor = call.args[0] if call.args else None
            if not isinstance(handler_ctor, ast.Call):
                unwrapped.append(ast.dump(call)[:80])
                continue
            if not _uses_require_owner(handler_ctor):
                unwrapped.append(ast.dump(handler_ctor)[:120])
        assert not unwrapped, f"add_handler ohne _require_owner(): {unwrapped}"


class TestRealRegisteredHandlersRejectForeignChat:
    """Nicht die Handliste aus dem AST-Test, sondern die ECHTE Registrierung:
    register_handlers() auf eine echte Application anwenden und JEDEN
    eingesammelten Callback mit einem fremden Chat aufrufen. Nur Bestehen
    beweist, dass der Owner-Check tatsaechlich vor der Auslieferung sitzt,
    nicht nur strukturell im Quelltext."""

    def test_every_registered_handler_rejects_foreign_chat(self, monkeypatch):
        asyncio.run(self._test_every_registered_handler_rejects_foreign_chat(monkeypatch))

    async def _test_every_registered_handler_rejects_foreign_chat(self, monkeypatch):
        from telegram.ext import Application

        monkeypatch.setattr(tg, "OWNER_ID", "42")
        monkeypatch.setattr(tg, "HAS_BACH", True)

        app = Application.builder().token("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA").build()
        tg.register_handlers(app)

        replies = []

        class FakeMessage:
            async def reply_text(self, text):
                replies.append(text)

        foreign_update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=999999),
            effective_message=FakeMessage(),
            message=FakeMessage(),
        )

        handlers = [h for group in app.handlers.values() for h in group]
        assert len(handlers) >= 19, "weniger echte Handler registriert als erwartet"

        for h in handlers:
            await h.callback(foreign_update, None)

        assert len(replies) == len(handlers)
        assert all(r == "Zugriff nur für den Owner." for r in replies)
