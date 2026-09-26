"""Befunde aus dem Idle-Worker-Lauf T-20260920-970553854 (2026-09-26)."""

import hub.memory_hook_provider as mhp
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.worker import ist_fertig


class _ProxyLikeBachApiMemory:
    """Wie bach_api._MemoryProxy: jeder Attributname liefert eine Funktion."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def test_memory_hook_gets_no_function_as_db_path(monkeypatch):
    seen = {}

    def fake_hook(db_path=None):
        seen["db_path"] = db_path

    monkeypatch.setattr(mhp, "get_shared_memory_hook", fake_hook)
    runtime = ChatRuntime(backend=None, memory_fn=_ProxyLikeBachApiMemory())
    assert runtime._get_memory_hook_context("hallo", "chat-1") == ""
    assert seen == {"db_path": None}


def test_memory_hook_keeps_a_real_db_path(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(mhp, "get_shared_memory_hook", lambda db_path=None: seen.setdefault("p", db_path))

    class _Memory:
        db_path = tmp_path / "bach.db"

    ChatRuntime(backend=None, memory_fn=_Memory())._get_memory_hook_context("x", "c")
    assert seen["p"] == tmp_path / "bach.db"


def test_fertig_is_found_at_the_end_of_a_long_answer():
    bericht = "Ich habe den Collector gebaut und getestet. " * 40 + "\nFERTIG"
    assert ist_fertig(bericht)
    assert ist_fertig("FERTIG. Erledigt.")
    assert not ist_fertig("Backend-Fehler: RuntimeError: Kontext-Übergabe bleibt zu groß")
    assert not ist_fertig(None)
