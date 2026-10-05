#!/usr/bin/env python3
"""BACH Chat Runtime -- compatibility seam over the neutral ``ellmos-chat`` module.

Since wave 2 of the BACH-GUI module cut (decision D-20260830-002) the session
management, tool-use loop and context compression live in ``ellmos_chat``.
This file keeps BACH's import path and its public surface unchanged:

    from hub._services.chat.chat_runtime import ChatRuntime, RUNTIME_BACH_DB

BACH keeps what is BACH's and injects it:

* **Tools** -- ``bach_tools.BachToolProvider`` (``bach_command`` into the 110+
  CHIAH handlers, plus the lazy ``hub._services.*`` imports for recurring
  tasks, the Foerderbericht pipeline and the weather service).
* **Transcripts** -- ``session_store.SQLiteChatSessionStore``, i.e.
  ``session_snapshots``/``chat-transcript.v1`` in the canonical ``bach.db``.
  ``_SnapshotStoreAdapter`` below presents it as the module's ``ChatStore``
  protocol. There is no second chat database.
* **System prompt** -- BACH's hand-written capability text, not the module's
  generated one.

Only telegram_chat.py imports this module directly; the tray and the GUI
``/chat`` page reach the same runtime through the Control API on :8081.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, FrozenSet, Optional

try:
    from ellmos_chat import (
        ChatRuntime as _ModuleChatRuntime,
        ChatSession as _ModuleChatSession,
        Mode,
        as_mode,
        RunResult,
        RunStatus,
    )
except ImportError:
    from enum import Enum

    class Mode(str, Enum):
        SAFE = "safe"
        FULL = "full"

    def as_mode(v):
        return Mode(str(getattr(v, "value", v)).strip().lower())

    class RunResult:
        pass

    class RunStatus:
        pass

    class _ModuleChatSession:
        def __init__(self):
            self.messages: list[dict] = []
            self.think: bool = True
            self._mode: Mode = Mode.SAFE
            self.model: str = ""
            self.current_tool: str = ""
            self.tool_round: int = 0
            self.last_tools: list[str] = []
            self.last_active: float = 0.0

        @property
        def mode(self) -> Mode:
            return self._mode

        @mode.setter
        def mode(self, value) -> None:
            self._mode = as_mode(value)

    class _ModuleChatRuntime:
        def __init__(
            self,
            backend,
            system_prompt: str = "",
            store: Any = None,
            registry: Any = None,
            policy: Any = None,
            memory_fn: Any = None,
            injector: Any = None,
            max_tool_rounds: int = 12,
            max_sessions: int = 1024,
            auto_continue: int = 0,
            goal: str = "",
        ):
            self.backend = backend
            self.base_system = system_prompt
            self.system_prompt = system_prompt
            self.store = store
            self.registry = registry
            self.memory = memory_fn
            self.injector = injector
            self.max_tool_rounds = max(0, int(max_tool_rounds))
            self.max_sessions = max(1, int(max_sessions))
            self.auto_continue = max(0, int(auto_continue))
            self.goal = str(goal or "")
            self._sessions: dict[str, Any] = {}
            self._session_locks: dict[str, Any] = {}

from hub import safe_exec
from hub._services.limits import limit
from hub._services.chat import hooks
from hub._services.chat.bach_tools import (
    RUNTIME_BACH_DB,
    apply_task_field_changes,
    GateReopenBlocked,
    BachToolProvider,
    _tool,
    TOOLS_SAFE,
    TOOLS_FULL,
    TOOLS_PLAN,
    tools_for_mode,
    exec_tool,
    is_blocked,
    is_safe_command,
    is_safe_write_path,
    run_shell,
    run_shell_restricted,
    run_argv,
    BLOCKED_PATTERNS,
    SAFE_BASES,
    CMD_TIMEOUT,
    BACH_SYSTEM_DIR,
    AUTO_NUDGE,
    HANDOFF_PROMPT,
    GOAL_CHECK,
    _ALLOWED_FS_ROOTS,
    _fs_root_allowed,
    _resolve,
    _is_under,
    _norm,
    _secret_locations,
    _is_secret_path,
    _contains_secret_location,
    ist_fertig,
    check_safe_shell_args,
    BACH_COMMAND_HANDLERS,
)

log = logging.getLogger("bach.chat")


class _SnapshotStoreAdapter:
    """The module's ``ChatStore`` protocol on BACH's snapshot session store.

    The module appends message by message; BACH's store holds one snapshot of
    the whole transcript per chat. Each append therefore writes the runtime's
    current in-memory transcript -- the same thing BACH persisted before the
    cut, just twice per turn instead of once. Reading first would risk wiping a
    good snapshot after a transient read error.
    """

    def __init__(self, runtime: "ChatRuntime"):
        self._runtime = runtime

    def load(self, chat_id: str) -> list[dict]:
        return self._runtime._load_messages(chat_id)

    def append(self, chat_id: str, role: str, content: str) -> None:
        session = self._runtime._sessions.get(chat_id)
        messages = (
            session.messages if session is not None
            else [{"role": role, "content": content}]
        )
        self._runtime._persist(chat_id, messages)

    def replace(self, chat_id: str, messages: list[dict]) -> None:
        self._runtime._persist(chat_id, messages)

    def clear(self, chat_id: str) -> None:
        store = self._runtime.session_store
        if store is None:
            return
        try:
            store.delete(chat_id)
        except Exception as exc:  # already reported by clear_session
            log.warning("Chat-Persistenz konnte nicht geloescht werden: %s", exc)



class FailedAnswer(str):
    """Antworttext, der aus einer gefangenen Backend-Ausnahme stammt.

    ``process`` faengt Backend-Ausnahmen ab und gibt ihren Text als Antwort
    zurueck -- fuer Chat und Auftragsnachrichten ist das richtig, der Nutzer
    soll den Fehler sehen. Automatische Konsumenten konnten einen Fehlschlag
    danach aber nicht mehr von einer echten Antwort unterscheiden und haben
    ihn als Erfolg verbucht (T-20260906-743610852).

    Als ``str``-Unterklasse bleibt jeder bestehende Aufrufer unveraendert --
    persistieren, als Reply ablegen, an Telegram senden -- waehrend Aufrufer,
    die den Unterschied brauchen, ihn per ``isinstance`` erfragen koennen.

    Der sichtbare Text bleibt fuer bestehende Aufrufer unveraendert. Der
    Session-Store legt daneben ``answer_status=failed`` ab; dadurch bleibt der
    Status auch nach einem Neustart erhalten, ohne den Text zu duplizieren.
    ``looks_like`` akzeptiert einen expliziten Status; sein statusloser
    Legacy-Zweig bleibt fuer alte textbasierte Konsumenten erhalten. Die
    Nachrichtenbewertung verwendet dagegen ``answer_status`` zuerst. Alte
    Snapshots ohne Status koennen dort nur ueber ``legacy_looks_like`` bewertet
    werden.
    """

    PREFIX = "Backend-Fehler: "
    STATUS_KEY = "answer_status"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    @classmethod
    def looks_like(cls, text, *, status: str | None = None) -> bool:
        """Return whether ``text`` is a typed failure in the live runtime.

        New callers should pass the explicit status. The statusless path keeps
        the old text probe alive for T-306 and other external consumers, but a
        ``SuccessfulAnswer`` is an explicit in-memory success and wins over
        that legacy prefix probe.
        """
        if status == cls.STATUS_FAILED:
            return True
        if status == cls.STATUS_SUCCESS:
            return False
        if getattr(text, "answer_status", None) == cls.STATUS_SUCCESS:
            return False
        return isinstance(text, cls) or cls.legacy_looks_like(text)

    @classmethod
    def legacy_looks_like(cls, text) -> bool:
        """Recognise the pre-status transcript format, conservatively.

        This is intentionally separate from :meth:`looks_like`: the old
        ``role``/``content``-only format has no provenance bit, so its exact
        prefix is the only evidence available. New messages always carry an
        explicit status and never take this ambiguous path.
        """
        return isinstance(text, str) and text.startswith(cls.PREFIX)

    @classmethod
    def message_is_failed(cls, message: dict) -> bool:
        """Classify one transcript entry without guessing over new metadata."""
        if message.get("role") != "assistant":
            return False
        content = message.get("content", "")
        if isinstance(content, cls):
            return True
        status = message.get(cls.STATUS_KEY)
        if status == cls.STATUS_FAILED:
            return True
        if status == cls.STATUS_SUCCESS:
            return False
        return cls.legacy_looks_like(content)

    @classmethod
    def from_exception(cls, exc: BaseException) -> "FailedAnswer":
        """Gefangene Ausnahme als Fehlschlag-Antwort, mit ihrem Typnamen.

        Der Typ steht immer davor, nicht nur wenn ``str(exc)`` leer ist:
        ``httpx.ReadTimeout`` und Verwandte haben keinen Text, und auch bei
        vorhandener Meldung sagt der Typ, ob die Leitung stand, das Modell
        schwieg oder der Aufruf falsch war.
        """
        return cls(f"{cls.PREFIX}{type(exc).__name__}: {exc}".rstrip(": "))


class SuccessfulAnswer(str):
    """A successful text answer that happens to use the legacy error prefix.

    BACH's older order-worker seams are text-only and call ``startswith`` on
    the callback result. This narrow ``str`` subtype keeps the visible answer
    unchanged while making that legacy probe agree with the explicit success
    status. It is only created for colliding successful text; ordinary answers
    remain ordinary strings.
    """

    answer_status = FailedAnswer.STATUS_SUCCESS

    @staticmethod
    def _contains_legacy_failure_prefix(prefix) -> bool:
        prefixes = prefix if isinstance(prefix, tuple) else (prefix,)
        return any(
            candidate in (FailedAnswer.PREFIX, FailedAnswer.PREFIX.rstrip())
            for candidate in prefixes
            if isinstance(candidate, str)
        )

    def startswith(self, prefix, *args) -> bool:
        if self._contains_legacy_failure_prefix(prefix):
            other_prefixes = tuple(
                candidate
                for candidate in (prefix if isinstance(prefix, tuple) else (prefix,))
                if candidate not in (FailedAnswer.PREFIX, FailedAnswer.PREFIX.rstrip())
            )
            if not other_prefixes:
                return False
            prefix = other_prefixes[0] if len(other_prefixes) == 1 else other_prefixes
        return super().startswith(prefix, *args)


def _classify_successful_answer(answer: Any) -> str:
    """Attach an explicit success type only where old text probes collide."""
    if isinstance(answer, (FailedAnswer, SuccessfulAnswer)):
        return answer
    if isinstance(answer, str) and answer.strip().startswith(FailedAnswer.PREFIX):
        return SuccessfulAnswer(answer)
    return answer


def _managed_backend_answer(result: Any) -> str:
    """Validate a backend-owned-tools result before it enters chat history."""
    # Older/current CLI seams can wrap the structured provider result in the
    # outer ``content`` field.  Unwrap that additive shape here so the status
    # contract does not depend on the provider adapter version.
    if isinstance(result, dict) and isinstance(result.get("content"), dict):
        nested = result["content"]
        if "error" in nested or "content" in nested:
            result = nested
    if not isinstance(result, dict):
        return FailedAnswer(f"{FailedAnswer.PREFIX}Backend-Antwort ist ungültig")

    if result.get("error"):
        partial = result.get("content")
        partial_text = partial if isinstance(partial, str) else ""
        return FailedAnswer(
            f"{FailedAnswer.PREFIX}{result['error']}"
            + (
                f"\n[Teilantwort vor dem Abbruch]\n{partial_text}"
                if partial_text
                else ""
            )
        )

    content = result.get("content")
    if not isinstance(content, str) or not content.strip():
        return FailedAnswer(f"{FailedAnswer.PREFIX}Backend-Antwort ist leer oder ungültig")
    return content


def _session_name(chat_id: str, session: Optional["ChatSession"] = None) -> str:
    cid = str(chat_id)
    if cid == "gui-web" or cid.startswith("web"):
        if session and session.messages:
            first_user = next((m.get("content", "") for m in session.messages if m.get("role") == "user"), "")
            if first_user:
                clean = " ".join(first_user.split())
                if len(clean) > 42:
                    clean = clean[:42] + "…"
                return f"Web: {clean}"
        return "Web Chat"
    if cid.isdigit():
        return f"Telegram ({cid})"
    if "idle" in cid:
        return f"Idle Worker ({cid})"
    if "tray" in cid:
        return f"Tray ({cid})"
    return f"Chat ({cid})"



class ChatSession(_ModuleChatSession):
    """Laufzeit-State für eine einzelne Chat-Session."""

    def __init__(self):
        super().__init__()
        self._bach_mode: str = "safe"
        self.voice_output: bool = False
        self.backend: Any = None
        self.max_tool_rounds: Optional[int] = None
        self.allow_tools: bool = True
        self.worker_slot_reader: Any = None
        self.custom_system_prompt: str = ""
        self.profile_binding: dict | None = None
        self.profile_context_text: str = ""
        self.chat_id: str = ""
        self.operator_control: Any = None

    @property
    def mode(self) -> str:
        return getattr(self, "_bach_mode", "safe")

    @mode.setter
    def mode(self, value) -> None:
        val = str(value.value if hasattr(value, "value") else value).strip().lower() if value is not None else "safe"
        self._bach_mode = val
        if val in ("safe", "full"):
            self._mode = as_mode(val)
        else:
            self._mode = Mode.SAFE


class ComputeLocked(RuntimeError):
    """Ein Modell-Load wurde unterbunden, weil Rechenjobs laufen.

    Ausnahme statt Antworttext: es gibt nichts zu persistieren, keinen Turn im
    Transkript und keine "Antwort", die ein Worker als Ergebnis verbuchen
    koennte. Der Auftrags-Worker fasst sie ohnehin richtig auf -- er loggt und
    versucht es beim naechsten Poll erneut (T-20260907-440775748).
    """


class _ChatTurnGate:
    def __init__(self):
        self.condition = threading.Condition()
        self.active_turns = 0
        self.clearing = False


class _ComputeTurnGate:
    """Serialize local inference runs and let foreground chats pass first."""

    def __init__(self):
        self.condition = threading.Condition()
        self.active = False
        self.foreground_waiters = 0
        self.chat_id = ""
        self.priority = ""
        self.started_at: float | None = None


class ChatRuntime(_ModuleChatRuntime):
    _sessions: dict[str, Any] = {}

    @property
    def sessions(self) -> dict:
        if not hasattr(self, "_sessions"):
            self._sessions = {}
        return self._sessions

    @sessions.setter
    def sessions(self, value: dict) -> None:
        self._sessions = value

    """Backend-unabhängige Chat-Runtime mit Tool-Use-Loop."""

    MAX_CONTEXT_CHARS = limit("BACH_MAX_CONTEXT_CHARS")
    SUMMARIZE_THRESHOLD = limit("BACH_SUMMARIZE_THRESHOLD")
    MAX_MESSAGES = limit("BACH_MAX_MESSAGES")
    SESSION_IDLE_TTL = float(os.environ.get("BACH_CHAT_SESSION_TTL", "86400"))
    CLEAR_WAIT_TIMEOUT = 5.0

    def __init__(self, backend, system_prompt: str = "",
                 bach_app=None, memory_fn=None, injector=None,
                 session_store=None):
        self.backend = backend
        self.base_system = system_prompt
        self.bach_app = bach_app
        self.memory = memory_fn
        self.injector = injector
        self.session_store = session_store
        self.compute_gate = None
        self._sessions = {}
        self._session_locks = {}
        self._chat_turn_gates: dict[str, _ChatTurnGate] = {}
        self._chat_turn_gates_lock = threading.Lock()
        self._compute_turn_gate = _ComputeTurnGate()
        self.max_tool_rounds: int = limit("BACH_MAX_TOOL_ROUNDS")
        self._persistence_error: str | None = None
        self.auto_continue: int = limit("BACH_AUTO_CONTINUE")
        self.goal: str = ""
        self.context_limit: int = limit("BACH_CONTEXT_LIMIT")
        self.handoff_percent: int = limit("BACH_HANDOFF_PERCENT")
        self.last_handoff: str = ""
        self.hook_every: int = limit("BACH_HOOK_EVERY")
        super().__init__(
            backend,
            system_prompt=system_prompt,
            store=_SnapshotStoreAdapter(self),
            registry=BachToolProvider(bach_app, backend.get_default_model if hasattr(backend, "get_default_model") else None),
            memory_fn=memory_fn,
            injector=injector,
        )

    @staticmethod
    def _refresh_worker_tools(session: ChatSession) -> FailedAnswer | None:
        reader = getattr(session, "worker_slot_reader", None)
        if reader is None:
            return None
        try:
            slot = reader()
            if not isinstance(slot, dict) or slot.get("id") != getattr(session, "chat_id", ""):
                raise RuntimeError("Worker-Slot fehlt oder stimmt nicht überein")
            session.allow_tools = slot.get("allow_tools", True) is True
            return None
        except Exception as exc:
            session.allow_tools = False
            return FailedAnswer.from_exception(exc)

    @classmethod
    def _worker_backend_gate(cls, session: ChatSession, backend: Any) -> FailedAnswer | None:
        capability_error = cls._refresh_worker_tools(session)
        if capability_error is not None:
            return capability_error
        if session.allow_tools is False and getattr(backend, "manages_own_tools", False):
            # Self-managed backends can dispatch tools outside BACH's tool
            # loop, so a worker downgrade must stop every backend boundary.
            return FailedAnswer(
                f"{FailedAnswer.PREFIX}Backend mit eigenen Tools ist für "
                "einen tool-freien Lauf nicht verifizierbar"
            )
        return None

    def _load_messages(self, chat_id: str) -> list[dict]:
        if self.session_store is None:
            return []
        if str(chat_id).startswith("agent:"):
            state = self.session_store.load_state(chat_id)
            if state["binding"] is None:
                raise ValueError("Der Profilkontext fehlt vor dem Restore")
            return self._restore_message_status(state["messages"])
        try:
            messages = self.session_store.load(chat_id)
            self._persistence_error = None
            return self._restore_message_status(messages)
        except Exception as exc:
            self._persistence_error = str(exc)
            log.warning("Chat-Persistenz konnte nicht gelesen werden: %s", exc)
            return []

    @staticmethod
    def _restore_message_status(messages: list[dict]) -> list[dict]:
        """Restore typed answers while keeping transcript JSON additive.

        ``answer_status`` was added without changing the snapshot version. A
        missing key therefore means a legacy snapshot and keeps its old
        prefix-based, fail-closed fallback. Explicit success is authoritative
        for a new answer, including a legitimate text that starts with the old
        marker.
        """
        restored: list[dict] = []
        for message in messages:
            if not isinstance(message, dict):
                restored.append(message)
                continue
            item = dict(message)
            if item.get("role") == "assistant":
                content = item.get("content", "")
                status = item.get(FailedAnswer.STATUS_KEY)
                if isinstance(content, FailedAnswer):
                    item[FailedAnswer.STATUS_KEY] = FailedAnswer.STATUS_FAILED
                elif status == FailedAnswer.STATUS_FAILED and isinstance(content, str):
                    item["content"] = FailedAnswer(content)
                elif status == FailedAnswer.STATUS_SUCCESS:
                    if isinstance(content, str) and content.strip().startswith(FailedAnswer.PREFIX):
                        item["content"] = SuccessfulAnswer(content)
                elif FailedAnswer.legacy_looks_like(content):
                    # Pre-status entries have no way to prove intent. Keep the
                    # old failure detection so a real historical backend error
                    # cannot become a successful result after a restart.
                    item["content"] = FailedAnswer(content)
                    item[FailedAnswer.STATUS_KEY] = FailedAnswer.STATUS_FAILED
            restored.append(item)
        return restored

    @staticmethod
    def _messages_for_backend(messages: list[dict]) -> list[dict]:
        """Remove runtime-only status metadata before a provider call."""
        return [
            {key: value for key, value in message.items()
             if key != FailedAnswer.STATUS_KEY}
            for message in messages
        ]

    @staticmethod
    def _messages_for_store(messages: list[dict]) -> list[dict]:
        """Persist explicit answer status without changing visible content."""
        stored: list[dict] = []
        for message in messages:
            item = dict(message)
            if item.get("role") == "assistant":
                content = item.get("content", "")
                status = item.get(FailedAnswer.STATUS_KEY)
                if isinstance(content, FailedAnswer) or status == FailedAnswer.STATUS_FAILED:
                    status = FailedAnswer.STATUS_FAILED
                elif status == FailedAnswer.STATUS_SUCCESS:
                    status = FailedAnswer.STATUS_SUCCESS
                elif getattr(content, "answer_status", None) == FailedAnswer.STATUS_SUCCESS:
                    status = FailedAnswer.STATUS_SUCCESS
                else:
                    status = (
                        FailedAnswer.STATUS_FAILED
                        if FailedAnswer.legacy_looks_like(content)
                        else FailedAnswer.STATUS_SUCCESS
                    )
                item[FailedAnswer.STATUS_KEY] = status
            stored.append(item)
        return stored

    def _persist(self, chat_id: str, messages: list[dict]) -> None:
        if self.session_store is None:
            return
        try:
            session = self._sessions.get(chat_id)
            name = _session_name(chat_id, session) if session else ""
            self.session_store.save(
                chat_id,
                self._messages_for_store(messages),
                name=name, binding=getattr(session, "profile_binding", None),
            )
            self._persistence_error = None
        except Exception as exc:
            self._persistence_error = str(exc)
            if getattr(session, "profile_binding", None) is not None:
                self.sessions.pop(chat_id, None)
                raise RuntimeError("Profiltranskript konnte nicht dauerhaft gespeichert werden") from exc
            log.warning("Chat-Persistenz konnte nicht geschrieben werden: %s", exc)

    def _persist_session(self, chat_id: str, session: ChatSession) -> None:
        if self.session_store is None:
            return
        try:
            name = _session_name(chat_id, session)
            self.session_store.save(
                chat_id,
                self._messages_for_store(session.messages),
                name=name, binding=getattr(session, "profile_binding", None),
            )
            self._persistence_error = None
        except Exception as exc:
            self._persistence_error = str(exc)
            if getattr(session, "profile_binding", None) is not None:
                self.sessions.pop(chat_id, None)
                raise RuntimeError("Profiltranskript konnte nicht dauerhaft gespeichert werden") from exc
            log.warning("Chat-Persistenz konnte nicht geschrieben werden: %s", exc)

    def persistence_status(self) -> dict:
        """Non-sensitive health readback for the Control API."""
        return {
            "enabled": self.session_store is not None,
            "ok": self.session_store is not None and self._persistence_error is None,
            "error": self._persistence_error or "",
        }

    def bind_profile_session(self, chat_id: str, agent_context: tuple[dict, str]) -> None:
        from .agent_profile_context import binding_metadata, profile_chat_id_agent, require_current_binding
        binding, profile_text = agent_context
        binding = binding_metadata(binding)
        current_binding, current_text = require_current_binding(binding)
        if current_binding != binding or current_text != profile_text:
            raise ValueError("Profilquelle hat sich vor dem Turn geändert")
        if (profile_chat_id_agent(chat_id) != binding["agent_id"] or not profile_text
                or self.session_store is None):
            raise ValueError("Profil-Chat-ID, Kontext oder dauerhafter Store fehlt")
        state = self.session_store.load_state(chat_id)
        prior = state["binding"]
        ram = self.sessions.get(chat_id)
        if prior is None:
            if state["messages"] or (ram is not None and ram.messages):
                raise ValueError("Bestehender globaler Verlauf darf kein Profil übernehmen")
            self.session_store.save(chat_id, [], binding=binding)
            self.sessions.pop(chat_id, None)
        elif prior != binding or (ram is not None and getattr(ram, "profile_binding", None) != binding):
            raise ValueError("Profilbindung darf nicht gewechselt werden")
        session = self.get_session(chat_id)
        if session.worker_slot_reader is not None or (session.custom_system_prompt and not session.profile_context_text):
            raise ValueError("Slot- und Profilprompt sind nicht kombinierbar")
        session.profile_binding = binding
        session.profile_context_text = profile_text

    def get_session(self, chat_id: str) -> ChatSession:
        if str(chat_id).startswith("agent:"):
            if self.session_store is None:
                raise ValueError("Profilstore fehlt")
            state = self.session_store.load_state(chat_id)
            if state["binding"] is None:
                raise ValueError("Profilbindung fehlt")
            cached = self.sessions.get(chat_id)
            if cached is not None:
                if getattr(cached, "profile_binding", None) != state["binding"]:
                    raise ValueError("RAM-Profilbindung stimmt nicht mit dem Store überein")
                return cached
            session = ChatSession()
            session.chat_id = chat_id
            session.model = self.backend.get_default_model() if hasattr(self.backend, "get_default_model") else ""
            session.messages = self._restore_message_status(state["messages"])
            session.profile_binding = state["binding"]
            session.last_active = time.time()
            self.sessions[chat_id] = session
            return session
        now = time.time()
        if chat_id in self._sessions:
            s = self._sessions[chat_id]
            s.chat_id = chat_id
            if getattr(s, "last_active", 0.0) > 0 and (now - s.last_active) > self.SESSION_IDLE_TTL:
                log.info("Session %s wegen Inaktivität (>24h) archiviert und zurückgesetzt", chat_id)
                self.archive_and_reset(chat_id, reason="24h Inaktivität (RAM)")
                s_new = self._sessions[chat_id]
                s_new.chat_id = chat_id
                self._ensure_session_attrs(s_new)
                return s_new
            self._ensure_session_attrs(s)
            return s

        if self.session_store is not None:
            last_ts = self.session_store.get_last_updated(chat_id)
            if last_ts and (now - last_ts) > self.SESSION_IDLE_TTL:
                log.info("Persistierte Session %s älter als 24h -> Auto-Reset", chat_id)
                try:
                    self.session_store.archive_current(chat_id, f"Archiv [24h Auto-Reset] {_session_name(chat_id)}")
                    self.session_store.delete(chat_id)
                except Exception as exc:
                    log.warning("Auto-Reset Archivierung fehlgeschlagen: %s", exc)
                s = ChatSession()
                s.chat_id = chat_id
                s.model = self.backend.get_default_model() if hasattr(self.backend, "get_default_model") else ""
                s.last_active = now
                self._ensure_session_attrs(s)
                self._sessions[chat_id] = s
                return s

        s = ChatSession()
        s.chat_id = chat_id
        s.model = self.backend.get_default_model() if hasattr(self.backend, "get_default_model") else ""
        s.messages = self._load_messages(chat_id)
        s.last_active = now if s.messages else 0.0
        self._ensure_session_attrs(s)
        self._sessions[chat_id] = s
        return s

    @staticmethod
    def _ensure_session_attrs(session: ChatSession) -> None:
        if not hasattr(session, "voice_output"):
            session.voice_output = False
        if not hasattr(session, "allow_tools"):
            session.allow_tools = True
        if not hasattr(session, "worker_slot_reader"):
            session.worker_slot_reader = None
        if not hasattr(session, "operator_control"):
            session.operator_control = None
        if not hasattr(session, "custom_system_prompt"):
            session.custom_system_prompt = ""
        if not hasattr(session, "profile_binding"):
            session.profile_binding = None
        if not hasattr(session, "profile_context_text"):
            session.profile_context_text = ""
        if not hasattr(session, "backend"):
            session.backend = None
        if not hasattr(session, "max_tool_rounds"):
            session.max_tool_rounds = None
        if not hasattr(session, "current_tool"):
            session.current_tool = ""
        if not hasattr(session, "tool_round"):
            session.tool_round = 0
        if not hasattr(session, "last_tools"):
            session.last_tools = []

    def _context_limit_for_backend(self, backend, model: str = "") -> int:
        """Freeze the effective context limit for the backend selected for a turn."""
        getter = getattr(backend, "get_context_limit", None)
        value = getter() if callable(getter) else getattr(backend, "num_ctx", None)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return self.get_model_context_limit(model, backend)
        return value if value > 0 else self.get_model_context_limit(model, backend)

    def archive_and_reset(
        self, chat_id: str, reason: str = "Manuell", *,
        keep_empty_session: bool = True, strict_persistence: bool = False,
    ) -> int | None:
        """Archive and reset; explicit clears can require durable success."""
        archived_id = None
        session = self.sessions.get(chat_id)
        has_messages = bool(session and session.messages)
        if not has_messages and self.session_store is not None:
            stored = self._load_messages(chat_id)
            has_messages = bool(stored)

        if strict_persistence and self.session_store is not None:
            prefix = f"Archiv [{reason}] {_session_name(chat_id)}"
            try:
                archived_id = self.session_store.archive_and_delete(
                    chat_id, session.messages if session else None, prefix,
                    binding=(getattr(session, "profile_binding", None) if session else
                        self.session_store.load_state(chat_id)["binding"] if str(chat_id).startswith("agent:") else None)
                )
                self._persistence_error = None
            except Exception as exc:
                self._persistence_error = str(exc)
                log.error("Chat-Persistenz konnte nicht gelöscht werden: %s", exc)
                raise RuntimeError("Chat-Persistenz konnte nicht gelöscht werden") from exc
            self.sessions.pop(chat_id, None)
            return archived_id

        if has_messages and self.session_store is not None:
            prefix = f"Archiv [{reason}] {_session_name(chat_id)}"
            try:
                archived_id = self.session_store.archive_current(chat_id, prefix)
            except Exception as exc:
                self._persistence_error = str(exc)
                log.warning("Konnte Session vor Reset nicht archivieren: %s", exc)
                if strict_persistence:
                    raise RuntimeError(
                        "Chat-Persistenz konnte nicht gelöscht werden: "
                        "Archivierung fehlgeschlagen"
                    ) from exc

        if self.session_store is not None:
            try:
                self.session_store.delete(chat_id)
                self._persistence_error = None
            except Exception as exc:
                self._persistence_error = str(exc)
                log.error("Chat-Persistenz konnte nicht gelöscht werden: %s", exc)
                if strict_persistence:
                    raise RuntimeError("Chat-Persistenz konnte nicht gelöscht werden") from exc

        self.sessions.pop(chat_id, None)
        if keep_empty_session:
            new_session = ChatSession()
            new_session.model = self.backend.get_default_model()
            new_session.last_active = time.time()
            self.sessions[chat_id] = new_session
        return archived_id

    def clear_session(self, chat_id: str, archive_reason: str = "Clear") -> int | None:
        gate = self._chat_turn_gate(chat_id)
        deadline = time.monotonic() + self.CLEAR_WAIT_TIMEOUT
        with gate.condition:
            while gate.clearing:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Chat-Clear wartet zu lange auf einen anderen Clear")
                gate.condition.wait(remaining)
            gate.clearing = True
        try:
            with gate.condition:
                while gate.active_turns:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError("Chat-Clear blockiert: laufender Chat-Turn")
                    gate.condition.wait(remaining)
            return self.archive_and_reset(
                chat_id, reason=archive_reason,
                keep_empty_session=False, strict_persistence=True,
            )
        finally:
            with gate.condition:
                gate.clearing = False
                gate.condition.notify_all()

    def _chat_turn_gate(self, chat_id: str) -> _ChatTurnGate:
        key = str(chat_id)
        with self._chat_turn_gates_lock:
            return self._chat_turn_gates.setdefault(key, _ChatTurnGate())

    @staticmethod
    def _uses_local_compute(backend) -> bool:
        """Only local Ollama/LM Studio inference competes for this host's torch."""
        try:
            from hub._services.llm.model_backend import backend_identifier

            backend_id = backend_identifier(backend)
        except Exception:
            backend_id = str(getattr(backend, "backend_id", "") or "").lower()
        if backend_id not in {"lmstudio", "ollama"}:
            return False

        base_url = getattr(backend, "base_url", None)
        if not base_url:
            return True
        try:
            hostname = urllib.parse.urlsplit(str(base_url)).hostname
        except ValueError:
            return False
        return hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

    @staticmethod
    def _process_priority(chat_id: str, requested: str | None) -> str:
        if requested in {"foreground", "background"}:
            return requested
        if str(chat_id).startswith(("idle-", "worker-", "tray-worker-")):
            return "background"
        return "foreground"

    @staticmethod
    async def _enter_compute_turn(gate: _ComputeTurnGate, chat_id: str, priority: str) -> None:
        waiting_foreground = priority == "foreground"
        registered_waiter = False
        try:
            if waiting_foreground:
                with gate.condition:
                    gate.foreground_waiters += 1
                    registered_waiter = True
            while True:
                with gate.condition:
                    if not gate.active and (priority != "background" or gate.foreground_waiters == 0):
                        gate.active = True
                        gate.chat_id = str(chat_id)
                        gate.priority = priority
                        gate.started_at = time.time()
                        if registered_waiter:
                            gate.foreground_waiters -= 1
                            registered_waiter = False
                        return
                await asyncio.sleep(0.025)
        finally:
            if registered_waiter:
                with gate.condition:
                    gate.foreground_waiters = max(0, gate.foreground_waiters - 1)
                    gate.condition.notify_all()

    @staticmethod
    def _leave_compute_turn(gate: _ComputeTurnGate) -> None:
        with gate.condition:
            gate.active = False
            gate.chat_id = ""
            gate.priority = ""
            gate.started_at = None
            gate.condition.notify_all()

    def compute_turn_status(self) -> dict[str, Any]:
        """Return live evidence about which BACH run currently owns local inference."""
        with self._compute_turn_gate.condition:
            gate = self._compute_turn_gate
            return {
                "active": gate.active,
                "holder": "BACH" if gate.active else None,
                "chat_id": gate.chat_id or None,
                "priority": gate.priority or None,
                "started_at": gate.started_at,
                "foreground_waiters": gate.foreground_waiters,
            }

    @staticmethod
    async def _enter_chat_turn(gate: _ChatTurnGate) -> None:
        while True:
            with gate.condition:
                if not gate.clearing:
                    gate.active_turns += 1
                    return
            # Polling avoids a background lock-acquisition thread surviving
            # cancellation of this coroutine and leaking active_turns.
            await asyncio.sleep(0.025)

    @staticmethod
    async def _enter_profile_turn(gate: _ChatTurnGate) -> None:
        while True:
            with gate.condition:
                if not gate.clearing and gate.active_turns == 0:
                    gate.active_turns = 1
                    return
            await asyncio.sleep(0.025)

    @staticmethod
    def _leave_chat_turn(gate: _ChatTurnGate) -> None:
        with gate.condition:
            gate.active_turns -= 1
            gate.condition.notify_all()

    def fork_session(self, target_chat_id: str, snapshot_id: int, *, agent_context=None) -> int:
        """Klont den Verlauf aus einem Snapshot in die Ziel-Session."""
        if not self.session_store:
            raise RuntimeError("Kein SessionStore verfügbar")
        snap = self.session_store.get_snapshot_by_id(snapshot_id)
        if not snap:
            raise ValueError(f"Snapshot ID {snapshot_id} nicht gefunden")
        messages = self._restore_message_status(snap.get("messages", []))
        source_binding = snap.get("binding")
        if agent_context is not None:
            from .agent_profile_context import profile_chat_id_agent
            binding, text = agent_context
            if profile_chat_id_agent(target_chat_id) != binding["agent_id"] or source_binding != binding:
                raise ValueError("Fork darf Profil oder Kontextklasse nicht wechseln")
            target = self.session_store.load_state(target_chat_id)
            if target["binding"] is not None or target["messages"] or target_chat_id in self.sessions:
                raise ValueError("Profil-Fork benötigt eine neue leere Ziel-Session")
            s = ChatSession()
            s.chat_id = target_chat_id
            s.model = self.backend.get_default_model()
            s.messages = list(messages)
            s.profile_binding = binding
            s.profile_context_text = text
            s.last_active = time.time()
            self._persist_session(target_chat_id, s)
            self.sessions[target_chat_id] = s
            return len(messages)
        if source_binding is not None or str(target_chat_id).startswith("agent:"):
            raise ValueError("Ein Profil-Snapshot darf keinen globalen Fork erzeugen")

        # Aktuelle Ziel-Session vor dem Fork sichern
        curr = self.sessions.get(target_chat_id)
        if curr and curr.messages and self.session_store:
            try:
                self.session_store.archive_current(
                    target_chat_id,
                    f"Archiv [Vor Fork #{snapshot_id}] {_session_name(target_chat_id)}"
                )
            except Exception:
                pass

        s = ChatSession()
        s.model = self.backend.get_default_model()
        s.messages = list(messages)
        s.last_active = time.time()
        self.sessions[target_chat_id] = s
        self._persist_session(target_chat_id, s)
        return len(messages)

    def history(self, chat_id: str) -> list[dict]:
        """Read-only transcript of a session: the visible user/assistant turns in order.

        Does not create a session (unknown chat_id -> []). Internal entries -- the
        summarised-context system message, tool traffic -- stay hidden. The GUI
        restores exactly this list when the chat page is reopened, so leaving the
        page no longer loses the conversation (plan item 1.1.7 / 1.2.4 within the
        runtime's lifetime; the session store itself is unchanged).
        """
        session = self.sessions.get(chat_id)
        messages = session.messages if session is not None else self._load_messages(chat_id)
        return [
            {"role": m["role"], "content": m.get("content", ""),
             "ok": not FailedAnswer.message_is_failed(m)}
            for m in messages
            if m.get("role") in ("user", "assistant")
        ]

    def build_system_prompt(self, session: ChatSession, *, profile_context: str = "") -> str:
        capabilities = """
Du hast Zugriff auf Werkzeuge (Tools), die du bei Bedarf aufrufen kannst.

SAFE-MODUS (Standard):
- list_directory, read_file, search_text — Dateisystem lesen
- edit_file — Text in Dateien ersetzen (suchen/ersetzen)
- move_file — Dateien/Ordner verschieben oder umbenennen
- copy_file — Dateien/Ordner kopieren
- file_info — Detaillierte Datei-/Ordner-Informationen
- recycle — In Papierkorb verschieben (wiederherstellbar, statt Löschen)
- create_directory — Neuen Ordner erstellen
- safe_shell — Lesende Shell-Befehle (ls, cat, grep, git, docker, ps, etc.)
- system_status — Systeminfos (CPU, RAM, Disk)
- ollama_info — Modelle und Status
- bach_command — BACH Memory, Tasks, Suche, Status
- get_datetime — Datum/Uhrzeit
- web_search — Im Internet suchen (DuckDuckGo)
- web_fetch — Inhalt einer URL abrufen (Webseite, API, JSON)
- weather — Aktuelles Wetter abfragen
- task_manage — Tasks anlegen, auflisten, erledigen
- maintain — Systemwartung: fällige Tasks (check), Wartung (run), BACH-Status (health), Service-Check (services)
- foerderbericht — Förderbericht-Pipeline: Anonymisierung (prepare), Status (status), Aufräumen (cleanup)
- delegate — Aufgabe an Claude Code oder Codex CLI delegieren

FULL-MODUS (nur nach /mode full bestätigt):
- execute_command — Beliebige Shell-Befehle
- write_file — Dateien schreiben

BACH-HANDLER (alle via bach_command nutzbar):
- denkarium write/read/search/brainstorm/promote/stats — Gedanken-Sammler/Logbuch (persönliches Notizbuch des Users — NICHT als Agenten-Notizbuch; dafür mem/bach memory)
- calendar list/add/today/week — Termine und Kalender
- contact list/search/show — Kontaktverwaltung
- routine list/add/complete — Routinen und Gewohnheiten
- countdown list — Countdowns und Timer
- mem write/read/fact/facts/search/context — Memory-System
- lesson add/list — Lessons Learned
- mediplaner export/import/help — JSON-Austausch zwischen BACH-Gesundheitsdaten und MediPlaner
- help <thema> — Dokumentation zu jedem Thema (260+ Help-Dateien)

WICHTIGSTE REGEL — SUCHE ALS FALLBACK:
Wenn der User einen Service, ein Tool oder eine Funktion anfragt die du nicht kennst:
1. ZUERST: bach_command mit "help <thema>" nutzen — findet die passende Dokumentation
2. DANN: bach_command mit "search <begriff>" — durchsucht Handler, Tools und Skills
3. NIEMALS sagen "das kann ich nicht" ohne vorher gesucht zu haben
BACH hat 110+ Handler — du kennst hier nur die wichtigsten. Die Suche findet den Rest.

REGELN:
- Nutze Tools aktiv, wenn der User nach Informationen fragt
- Nutze web_search, wenn du aktuelle Informationen brauchst oder der User fragt
- Nutze task_manage, wenn der User Tasks verwalten will
- Nutze maintain, wenn der User nach Systemstatus, Wartung oder Health fragt
- Nutze delegate, wenn eine Aufgabe besser von Claude (Coding, Analyse) oder Codex (schnelle Code-Generierung) erledigt wird
- Nutze edit_file zum Bearbeiten von Dateien (suchen/ersetzen)
- Nutze recycle zum Löschen — verschiebt in den Papierkorb statt endgültig zu löschen
- Nutze weather für Wetterabfragen
- Nutze denkarium, wenn der User Gedanken notieren, im Logbuch schreiben oder brainstormen will (das ist SEIN persönliches Notizbuch — nutze es NICHT als dein eigenes Notizbuch; für Agenten-Erinnerungen: mem/bach memory)
- Nutze calendar, wenn der User nach Terminen fragt oder welche anlegen will
- Nutze contact, wenn der User Kontakte sucht oder anzeigen will
- Nutze routine, wenn der User nach Routinen oder Gewohnheiten fragt
- Führe Befehle aus, wenn der User es wünscht
- Antworte immer auf Deutsch
- Sei präzise, hilfreich, und zeige Tool-Ergebnisse klar an
- Du KANNST Befehle ausführen — sag nicht, dass du das nicht kannst

TURN-BUDGET, MEHRDEUTIGKEIT & DELEGATION (4-STUFEN-PRIORITÄT):
- Du hast pro Bearbeitungssitzung ein begrenztes Werkzeug-Rundenbudget. Große oder unklare Aufgaben NICHT endlos durchsuchen!
- 1. DIREKT LÖSEN: Wenn das Problem klar und überschaubar ist, direkt umsetzen und testen.
- 2. ZERLEGEN: Wenn umfangreich aber verstanden, mit task_manage(action='add', title='Edit: ...') in konkrete Einzelschritte zerlegen.
- 3. MEHRDEUTIGKEIT: Bei knappen/mehrdeutigen Aufgaben zuerst Code-Präzedenzfälle suchen und immer die minimal-invasive, risikoärmste Option wählen. Bei anhaltender Unsicherheit nach 3-5 Runden: Rückfrage mit task_manage(category='TO-DECIDE') anlegen.
- 4. DELEGIEREN & ABLEHNEN (Ultima Ratio): Erst delegieren (via delegate an Claude/Codex), wenn Modellgrenzen oder Werkzeuge nachweislich überschritten sind. Niemals voreilig ablehnen oder Aufgaben abwälzen!

WARTUNGSROLLE:
Du bist auch für Systemwartung zuständig. Wenn der User danach fragt:
- maintain(check) zeigt fällige wiederkehrende Tasks
- maintain(run, operation) führt Wartung aus (registry, skills, docs, backup, clean, memory, recurring)
- maintain(health) zeigt den Gesamtstatus
"""
        base = self.base_system
        if profile_context:
            base += ("\n\nDu bist das ausdrücklich ausgewählte BACH-Agentenprofil. Antworte auf Deutsch. "
                     "Die globalen Modus- und Werkzeuggrenzen gelten unverändert.")
        s = base + "\n\n" + capabilities
        if profile_context:
            s += "\n\n--- AUSGEWÄHLTES AGENTENPROFIL ---\n" + profile_context
        s += f"\n[Modus={session.mode}, Denken={'AN' if session.think else 'AUS'}, Modell={session.model}]"
        return s

    def _get_extra_context(self, text: str) -> str:
        if not self.injector and not self.memory:
            return ""
        parts = []
        if self.injector:
            try:
                hook = self._memory_hook()
                skip = hook.handled_injectors() if hook is not None else frozenset()
                inj = self.injector.process(text, skip=skip) if skip else self.injector.process(text)
                if inj:
                    parts.append("Kontext:\n" + "\n".join(str(i) for i in inj[:3]))
            except Exception:
                pass
        if self.memory:
            try:
                ctx = self.memory("context")
                if ctx and isinstance(ctx, str) and len(ctx) > 10:
                    parts.append(ctx[:2000])
            except Exception:
                pass
        return "\n\n".join(parts)

    def _get_bach_context(self, text: str) -> str:
        """BACH's name for the module's injector/memory context hook."""
        return self._get_extra_context(text)

    def _get_memory_hook_context(self, text: str, chat_id: str) -> str:
        """Memoryhooker-Kontext (Stufe 6) -- fail-soft, liefert nie einen Abbruch.

        Der Seam haengt in process() VOR dem Prompt-Aufbau: session_start_message
        (einmalig) + evaluate_prompt (Modus remember+search, Session-Cap,
        Cooldown) gegen BachMemoryBackend (read-only gegen die BACH-DB).
        Rollback: BACH_USE_EXTERNAL_MEMORYHOOKS=0. Fehlt das Modul oder
        klemmt der Hook, ist das Ergebnis "" -- der Chat laeuft weiter.
        """
        try:
            hook = self._memory_hook()
            if hook is None:
                return ""
            # api-Modus (Telegram): CLI-Hinweise zeigt der Chat nicht.
            cli_hints = getattr(self.injector, "_mode", "cli") != "api"
            return hook.hook_context(text, chat_id, cli_hints=cli_hints,
                                     disabled=self._injectors_off()) or ""
        except Exception:
            return ""

    def _injectors_off(self) -> frozenset:
        """In BACH abgeschaltete Injektoren (bach inject toggle), fail-soft."""
        try:
            from hub.memory_hook_provider import INJECTOR_SWITCHES
            config = self.injector._get_system().config
            return frozenset(key for key, switch in INJECTOR_SWITCHES.items()
                             if not config.is_enabled(switch))
        except Exception:
            return frozenset()

    def _memory_hook(self):
        """Geteilter memoryhooker-Adapter oder None (fail-soft)."""
        try:
            from hub.memory_hook_provider import get_shared_memory_hook
            db_path = getattr(getattr(self, "memory", None), "db_path", None)
            # bach_api.memory ist ein Proxy, dessen __getattr__ fuer JEDEN Namen
            # eine Funktion liefert; nur echte Pfade weitergeben, sonst Default-DB.
            if not isinstance(db_path, (str, os.PathLike)):
                db_path = None
            return get_shared_memory_hook(db_path=db_path)
        except Exception:
            return None

    async def process(self, text: str, chat_id: str, *, backend=None, model=None,
                      skip_compute_gate: bool = False, agent_context=None,
                      work_priority: str | None = None, **kwargs) -> str:
        from .agent_profile_context import profile_chat_id_agent
        profile_id = profile_chat_id_agent(chat_id)
        if str(chat_id).startswith("agent:") and profile_id is None:
            return FailedAnswer("Profil-Chat-ID ist ungültig")
        if profile_id is not None and agent_context is None:
            return FailedAnswer("Profilbindung fehlt")
        if agent_context is not None and profile_id is None:
            return FailedAnswer("Profilkontext benötigt eine Profil-Chat-ID")
        gate = self._chat_turn_gate(chat_id)
        compute_backend = (
            backend
            or getattr(self.sessions.get(chat_id), "backend", None)
            or self.backend
        )
        uses_local_compute = self._uses_local_compute(compute_backend)
        compute_acquired = False
        if agent_context is not None:
            await self._enter_profile_turn(gate)
        else:
            await self._enter_chat_turn(gate)
        try:
            if uses_local_compute:
                await self._enter_compute_turn(
                    self._compute_turn_gate,
                    chat_id,
                    self._process_priority(chat_id, work_priority),
                )
                compute_acquired = True
            if agent_context is not None:
                self.bind_profile_session(chat_id, agent_context)
            return await self._process_turn(
                text, chat_id, backend=backend, model=model,
                skip_compute_gate=skip_compute_gate, **kwargs,
            )
        finally:
            if compute_acquired:
                self._leave_compute_turn(self._compute_turn_gate)
            self._leave_chat_turn(gate)

    async def _process_turn(self, text: str, chat_id: str, *, backend=None, model=None,
                            skip_compute_gate: bool = False, **kwargs) -> str:
        """Verarbeitet eine User-Nachricht und gibt die Antwort zurück."""
        # Der eine Punkt, an dem jeder Modell-Load vorbeikommt: Telegram,
        # /api/chat (Idle-Worker) und der Auftrags-Worker rufen alle hier an.
        # Das Gate deshalb hier statt je Aufrufer (T-20260907-440775748).
        known_session = self.sessions.get(chat_id)
        selected_backend = (
            backend
            or getattr(known_session, "backend", None)
            or self.backend
        )
        if (
            not skip_compute_gate
            and self.compute_gate is not None
            and self.compute_gate(selected_backend)
        ):
            raise ComputeLocked(
                "Compute-Lock aktiv -- kein Modell-Load, damit laufende "
                "Rechenjobs nicht in den Swap gedraengt werden."
            )
        session = self.get_session(chat_id)
        selected_model = model or session.model or selected_backend.get_default_model()
        if str(chat_id).startswith("agent:"):
            if not session.profile_binding or not session.profile_context_text:
                raise ValueError("Profilkontext fehlt vor Inferenz")
            session.model = selected_model
            session.custom_system_prompt = self.build_system_prompt(
                session, profile_context=session.profile_context_text)
        capability_error = self._worker_backend_gate(session, selected_backend)
        if capability_error is not None:
            session.messages.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": capability_error},
            ])
            self._persist_session(chat_id, session)
            return capability_error
        context_limit = self._context_limit_for_backend(selected_backend, selected_model)
        session.last_active = time.time()
        session.messages.append({"role": "user", "content": text})

        active_limit = context_limit
        summarize_thresh = self.SUMMARIZE_THRESHOLD if active_limit <= 32768 else self.SUMMARIZE_THRESHOLD * 4
        max_msgs = self.MAX_MESSAGES if active_limit <= 32768 else self.MAX_MESSAGES * 2

        total = sum(len(m.get("content", "")) for m in session.messages)
        if total > summarize_thresh or len(session.messages) > max_msgs:
            capability_error = self._worker_backend_gate(session, selected_backend)
            if capability_error is not None:
                session.messages.append({"role": "assistant", "content": capability_error})
                self._persist_session(chat_id, session)
                return capability_error
            await self._summarize(
                session,
                backend=selected_backend,
                model=selected_model,
            )

        bach_ctx = "" if session.profile_binding else self._get_bach_context(text)
        # memoryhooker-Seam (MODULRUECKTRANSFER Stufe 6): dynamisch injizierter
        # Memory-Kontext mit Session-Cap/Cooldown und Audit-Trail. Fail-soft,
        # Rollback via BACH_USE_EXTERNAL_MEMORYHOOKS=0.
        hook_ctx = "" if session.profile_binding else self._get_memory_hook_context(text, chat_id)

        sys_prompt = getattr(session, "custom_system_prompt", "") or self.build_system_prompt(session)
        if bach_ctx and not getattr(session, "custom_system_prompt", ""):
            sys_prompt += f"\n\n--- BACH ---\n{bach_ctx}"
        if hook_ctx and not getattr(session, "custom_system_prompt", ""):
            sys_prompt += f"\n\n--- MEMORY-HOOK ---\n{hook_ctx}"
        if session.allow_tools is False:
            sys_prompt += "\n\n[CAPABILITY-GATE: Keine Werkzeuge verfügbar. Antworte ohne Tool-Aufrufe.]"

        msgs = [{"role": "system", "content": sys_prompt}] + self._messages_for_backend(
            session.messages
        )

        if getattr(selected_backend, "manages_own_tools", False):
            capability_error = self._worker_backend_gate(session, selected_backend)
            if capability_error is not None:
                session.messages.append({"role": "assistant", "content": capability_error})
                self._persist_session(chat_id, session)
                return capability_error
            try:
                result = await selected_backend.chat(
                    msgs, think=session.think, model=selected_model
                )
                answer = _managed_backend_answer(result)
            except Exception as e:
                answer = FailedAnswer.from_exception(e)
        else:
            tools = tools_for_mode(session.mode) if (self.max_tool_rounds > 0 and session.allow_tools is True) else []
            answer = await self._tool_loop(
                msgs,
                session,
                tools,
                backend=selected_backend,
                model=selected_model,
                context_limit=context_limit,
            )
        answer = _classify_successful_answer(answer)
        session.messages.append({
            "role": "assistant",
            "content": answer,
            FailedAnswer.STATUS_KEY: (
                FailedAnswer.STATUS_FAILED
                if isinstance(answer, FailedAnswer)
                else FailedAnswer.STATUS_SUCCESS
            ),
        })
        self._persist_session(chat_id, session)
        return answer

    async def _tool_loop(self, msgs: list, session: ChatSession,
                         tools: list, *, backend=None, model: str = "",
                         context_limit: int | None = None) -> str:
        selected_backend = backend or getattr(session, "backend", None) or self.backend
        selected_model = model or session.model or selected_backend.get_default_model()
        max_rounds = session.max_tool_rounds if getattr(session, "max_tool_rounds", None) is not None else self.max_tool_rounds
        round_num = 0
        auto_used = 0
        goal_checked = False
        handoffs = 0
        seit_hook = 0
        session.tool_round = 0
        session.last_tools = []
        result = {}
        offered_tools = tools
        while True:
            capability_error = self._refresh_worker_tools(session)
            if capability_error is not None:
                session.current_tool = ""
                return capability_error
            tools = offered_tools if session.allow_tools is True else []
            if max_rounds > 0 and round_num > max_rounds:
                session.current_tool = ""
                return result.get("content", "") or "(Max Tool-Runden erreicht)"

            # OPS-RUN-001: Operator-Steuerung an der Modell-Grenze konsumieren.
            # Nur aktiv, wenn die Session ein Control-Verzeichnis traegt
            # (Agent-Laeufe); Telegram-Chat etc. bleiben unveraendert.
            ctrl = getattr(session, "operator_control", None)
            if ctrl is not None:
                try:
                    pause_info = await ctrl.wait_if_paused()
                    if pause_info.get("timed_out"):
                        msgs.append({"role": "user", "content":
                            "[SYSTEM-HINWEIS: Eine Operator-Pause wurde nicht "
                            "aufgehoben; der Lauf wurde nach Ablauf der "
                            "Wartegrenze fortgesetzt.]"})
                    for note in ctrl.drain_notes():
                        log.info("Operator-Hinweis injiziert (Runde %d)", round_num)
                        msgs.append({"role": "user", "content":
                            f"[OPERATOR-HINWEIS vom {note.get('requested_at', '?')}]\n"
                            f"{note.get('message', '')}"})
                    cpt = ctrl.consume_new_checkpoint()
                    if cpt:
                        log.info("Operator-Checkpoint bestaetigt (Runde %d)", round_num)
                        msgs.append({"role": "user", "content":
                            f"[OPERATOR-CHECKPOINT vom {cpt.get('acknowledged_at', '?')}]\n"
                            f"{cpt.get('message', 'Sicherer Checkpoint erreicht.')}"})
                except Exception as e:
                    # Steuerung darf den Lauf nie gefährden.
                    log.warning("Operator-Steuerung fehlgeschlagen (ignoriert): %s", e)

            try:
                result = await selected_backend.chat(
                    msgs, tools=tools, think=session.think, model=selected_model
                )
            except Exception as e:
                session.current_tool = ""
                return FailedAnswer.from_exception(e)

            if result.get("error"):
                # Ein abgebrochener Lauf ist genauso wenig eine Antwort wie eine
                # gefangene Ausnahme: derselbe Typ, damit der Idle-Worker ihn
                # nicht als Erfolg verbucht (T-20260906-743610852).
                session.current_tool = ""
                teil = result.get("content") or ""
                return FailedAnswer(
                    f"{FailedAnswer.PREFIX}{result['error']}"
                    + (f"\n[Teilantwort vor dem Abbruch]\n{teil}" if teil else "")
                )

            if self._context_voll(
                result, session, context_limit=context_limit
            ):
                if handoffs >= 2:
                    session.current_tool = ""
                    return FailedAnswer.from_exception(RuntimeError(
                        "Kontext-Übergabe bleibt nach zwei Versuchen zu groß"
                    ))
                handoffs += 1
                log.info("Kontext-Uebergabe [%d] bei %s Token",
                         handoffs, result.get("prompt_tokens"))
                try:
                    msgs = await self._handoff(
                        msgs,
                        session,
                        backend=selected_backend,
                        model=selected_model,
                        strict=selected_model == "glm-5.3:cloud",
                    )
                except Exception as e:
                    session.current_tool = ""
                    return FailedAnswer.from_exception(e)
                continue

            # Only a measured positive token count below the threshold proves
            # relief. Missing/invalid counts must not bypass the retry cap.
            if type(result.get("prompt_tokens")) is int and result["prompt_tokens"] > 0:
                handoffs = 0
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                content = result.get("content", "") or "(keine Antwort)"
                nxt, goal_checked = self._auto_next(content, auto_used, goal_checked)
                if nxt is not None:
                    auto_used += 1
                    log.info(f"Auto-Continue [{auto_used}/{self.auto_continue}]")
                    msgs.append({"role": "user", "content": nxt})
                    continue
                session.current_tool = ""
                return content

            capability_error = self._refresh_worker_tools(session)
            if capability_error is not None:
                session.current_tool = ""
                return capability_error
            if session.allow_tools is False:
                session.current_tool = ""
                return FailedAnswer(
                    f"{FailedAnswer.PREFIX}Tool-Aufruf im tool-freien Lauf blockiert"
                )

            raw_msg = result.get("raw_message", {})
            if raw_msg:
                msgs.append(raw_msg)

            round_num += 1
            session.tool_round = round_num
            for i, tc in enumerate(tool_calls):
                capability_error = self._refresh_worker_tools(session)
                if capability_error is not None:
                    session.current_tool = ""
                    return capability_error
                if session.allow_tools is False:
                    session.current_tool = ""
                    return FailedAnswer(
                        f"{FailedAnswer.PREFIX}Tool-Aufruf im tool-freien Lauf blockiert"
                    )
                fn = tc.get("function", {})
                t_name = fn.get("name", "")
                t_args = fn.get("arguments", {})
                session.current_tool = t_name
                if t_name and t_name not in session.last_tools:
                    session.last_tools = (session.last_tools + [t_name])[-5:]
                log.info(f"Tool [{round_num}]: {t_name}({json.dumps(t_args, ensure_ascii=False)[:200]})")
                cid = getattr(session, "chat_id", "")
                if cid:
                    try:
                        from hub._services.chat.slots_config import update_slot
                        update_slot(cid, {"current_activity": f"Tool [{round_num}]: {t_name}"})
                    except Exception:
                        pass
                # Updating activity may race with (or itself trigger) a
                # downgrade. Re-read immediately before dispatcher entry.
                capability_error = self._refresh_worker_tools(session)
                if capability_error is not None:
                    session.current_tool = ""
                    return capability_error
                if session.allow_tools is False:
                    session.current_tool = ""
                    return FailedAnswer(
                        f"{FailedAnswer.PREFIX}Tool-Aufruf im tool-freien Lauf blockiert"
                    )
                t_result = exec_tool(
                    t_name, t_args, session.mode,
                    bach_app=self.bach_app,
                    default_model=selected_model,
                )
                tool_call_id = ""
                if hasattr(selected_backend, "_last_tool_call_ids"):
                    ids = selected_backend._last_tool_call_ids
                    if i < len(ids):
                        tool_call_id = ids[i]
                msgs.append(
                    selected_backend.tool_response_message(str(t_result), tool_call_id)
                )

            # Hook-Punkt: die Hooker bringen eigene Cooldowns mit, deshalb darf
            # hier oft gefragt werden - sie schweigen selbst, wenn nichts ansteht.
            seit_hook += 1
            if seit_hook >= self.hook_every and hooks.enabled("PostToolUse"):
                seit_hook = 0
                zusatz = hooks.fire("PostToolUse", getattr(session, "chat_id", "") or "bach-chat",
                                    prompt=str(session.last_tools))
                if zusatz:
                    log.info("Hook PostToolUse: %d Zeichen Kontext", len(zusatz))
                    msgs.append({"role": "user", "content": zusatz})

            # Turn-Awareness & Rundenlimit-Verwaltung:
            if max_rounds > 0 and round_num >= max_rounds:
                session.current_tool = ""
                final_prompt = (
                    f"[SYSTEM-HINWEIS: Werkzeugrunden aufgebraucht ({round_num}/{max_rounds})]\n"
                    "Die maximale Anzahl an Werkzeugrunden für diese Sitzung ist erreicht. "
                    "Fasse bitte präzise zusammen:\n"
                    "1. Was hast du bisher analysiert und herausgefunden (Dateipfade, Zeilennummern, Befunde)?\n"
                    "2. Was wurde im Code bereits geändert oder behoben?\n"
                    "3. Falls die Aufgabe noch nicht komplett gelöst ist: Welcher konkrete Folge-Task (z. B. 'Edit: ...') "
                    "wurde angelegt oder welche Schritte muss der nächste Lauf ausführen?"
                )
                msgs.append({"role": "user", "content": final_prompt})
                try:
                    # GLM Cloud requires think=true to keep reasoning in the
                    # separate thinking field. The final summary is still a
                    # model call and must obey the same output contract.
                    final_think = (
                        session.think if selected_model == "glm-5.3:cloud"
                        else False
                    )
                    final_res = await selected_backend.chat(
                        msgs, tools=None, think=final_think, model=selected_model
                    )
                    if final_res.get("error"):
                        return FailedAnswer(
                            f"{FailedAnswer.PREFIX}{final_res['error']}"
                        )
                    content = (final_res.get("content") or "").strip()
                    if content:
                        return content
                    return FailedAnswer(
                        f"{FailedAnswer.PREFIX}Abschluss-Zusammenfassung ist leer"
                    )
                except Exception as e:
                    log.warning("Abschluss-Zusammenfassung fehlgeschlagen: %s", e)
                    return FailedAnswer.from_exception(e)

            if max_rounds > 0 and round_num >= max_rounds - 2:
                rest = max_rounds - round_num
                nudge = (
                    f"[SYSTEM-HINWEIS: Werkzeugrunde {round_num}/{max_rounds} - Noch {rest} Runde(n) verbleibend!]\n"
                    "Deine Werkzeugrunden sind fast aufgebraucht! "
                    "Wenn du die Ursache kennst: Gehe JETZT direkt zur Code-Änderung (edit_file / write_file) über. "
                    "Wenn du den Code in dieser Session nicht mehr fertigstellen kannst: "
                    "Rufe sofort `task_manage(action='add', title='Edit: ...', description='Exakte Datei: ..., Zeilen: ..., Was zu tun ist: ...', category='...')` auf, "
                    "um einen konkreten Editier-Task anzulegen, und schließe diesen Analyse-Task mit deinen Erkenntnissen ab."
                )
                msgs.append({"role": "user", "content": nudge})

    def get_model_context_limit(self, model: str | None = None, backend: Any = None) -> int:
        """Dynamische Bestimmung des Kontextlimits je nach Modell und Backend."""
        m = (model or "").lower()
        # Cloud / Ultra-High Context Models
        if ":cloud" in m or "kimi" in m or "glm" in m:
            return 131072
        if "claude" in m or "sonnet" in m or "opus" in m:
            return 200000
        if "gpt-4" in m or "o3" in m or "o4" in m or "codex" in m:
            return 128000
        if "hermes" in m:
            return 131072

        # Backend-Typen pruefen
        b_name = type(backend).__name__.lower() if backend else ""
        if "anthropic" in b_name:
            return 200000
        if "openai" in b_name or "hermes" in b_name:
            return 128000

        # Lokales Modell -> Default aus self.context_limit (meist 32768)
        return self.context_limit

    def _context_voll(
        self,
        result: dict,
        session: ChatSession | None = None,
        *,
        context_limit: int | None = None,
    ) -> bool:
        """Ist das Kontextfenster so voll, dass eine Uebergabe faellig ist?

        Ohne Token-Zahl vom Backend wird nicht geraten - dann bleibt alles
        beim Alten. Prozent 0 schaltet die Uebergabe ab.
        """
        if self.handoff_percent <= 0:
            return False
        active_limit = context_limit if context_limit is not None else self.context_limit
        if context_limit is None and session is not None:
            active_limit = self.get_model_context_limit(
                session.model, getattr(session, "backend", None) or self.backend
            )
        if active_limit <= 0:
            return False
        used = result.get("prompt_tokens")
        if not isinstance(used, int) or used <= 0:
            return False
        return used >= active_limit * self.handoff_percent / 100

    async def _handoff(self, msgs: list, session: ChatSession, *, backend=None,
                       model: str = "", strict: bool = False) -> list:
        """Laesst das Modell sich selbst uebergeben und leert den Kontext.

        Anders als _summarize (Gespraechsprosa aus fremder Sicht) schreibt hier
        das arbeitende Modell selbst - es kennt seinen Stand. Das Ergebnis wird
        der Anfang des neuen, leeren Verlaufs.
        """
        frage = msgs + [{"role": "user", "content": HANDOFF_PROMPT}]
        selected_backend = backend or getattr(session, "backend", None) or self.backend
        selected_model = model or session.model or selected_backend.get_default_model()
        handoff_error = None
        try:
            res = await selected_backend.chat(
                frage, tools=None,
                think=session.think if selected_model == "glm-5.3:cloud" else False,
                model=selected_model,
            )
            if res.get("error"):
                raise RuntimeError(str(res["error"]))
            uebergabe = (res.get("content") or "").strip()
        except Exception as e:
            log.warning("Uebergabe fehlgeschlagen: %s", e)
            handoff_error = e
            uebergabe = ""

        if not uebergabe:
            if strict:
                if handoff_error is not None:
                    raise RuntimeError(f"Kontext-Übergabe fehlgeschlagen: {handoff_error}") from handoff_error
                raise RuntimeError("Kontext-Übergabe ist leer")
            # Lieber die letzten Schritte behalten als blind alles wegwerfen.
            return msgs[:1] + msgs[-4:]

        self.last_handoff = uebergabe
        if self.memory:
            try:
                self.memory("write", f"Uebergabe: {uebergabe[:400]}")
            except Exception:
                pass

        return [{"role": "user",
                 "content": "Du setzt eine begonnene Arbeit fort. Das ist dein "
                            "eigener Uebergabezettel:\n\n" + uebergabe +
                            "\n\nArbeite ab RESUME weiter. Frage nicht nach."}]

    def _auto_next(self, content: str, used: int, goal_checked: bool):
        """Naechste Nachricht im Loop-Mode, oder None wenn Schluss ist.

        Gibt (nachricht, goal_checked) zurueck. Ohne /auto (auto_continue=0)
        immer (None, goal_checked) - dann verhaelt sich der Tool-Loop exakt
        wie vorher. Der Zustand wird durchgereicht statt am Objekt gehalten:
        mehrere Chats teilen sich eine Runtime-Instanz.
        """
        if self.auto_continue <= 0 or used >= self.auto_continue:
            return None, goal_checked
        fertig = ist_fertig(content, fenster=200)
        if fertig:
            # Einmal streng gegen das Ziel gegenpruefen, dann ist Schluss.
            if goal_checked or not self.goal:
                return None, goal_checked
            return GOAL_CHECK.format(goal=self.goal), True
        return AUTO_NUDGE, goal_checked

    async def _summarize(self, session: ChatSession, *, backend=None,
                         model: str = ""):
        selected_backend = backend or getattr(session, "backend", None) or self.backend
        selected_model = model or session.model or selected_backend.get_default_model()
        if len(session.messages) < 6:
            return
        old = session.messages[:-4]
        recent = session.messages[-4:]

        old_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistent'}: {m.get('content', '')[:300]}"
            for m in old if m.get("role") in ("user", "assistant")
        )

        prompt = [
            {"role": "system", "content": "Fasse den Gesprächsverlauf in 2-3 Sätzen zusammen."},
            {"role": "user", "content": old_text[:6000]},
        ]

        try:
            result = await selected_backend.chat(
                prompt,
                think=session.think if selected_model == "glm-5.3:cloud" else False,
                model=selected_model,
            )
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
            summary = result.get("content", "")[:500]

            if self.memory:
                try:
                    self.memory("write", f"Chat: {summary[:300]}")
                except Exception:
                    pass

            session.messages = [
                {"role": "system", "content": f"Bisheriger Kontext: {summary}"}
            ] + recent
        except Exception:
            if selected_model != "glm-5.3:cloud":
                session.messages = recent
