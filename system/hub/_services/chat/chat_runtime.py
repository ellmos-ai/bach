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
from contextvars import ContextVar
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

#: Exakte Erfolgsantwort von ``task_manage(action='decompose')`` in bach_tools.
_DECOMPOSE_RECEIPT_RE = re.compile(
    r"Task #(\d+) in (\d+) Teilaufgaben zerlegt: IDs (\[[\d, ]*\])"
)

#: Nutzerregel (Task #1697): Ein Hintergrundworker, der eine Aufgabe nicht
#: fertigstellen kann, zerlegt sie selbst und stellt die Teilaufgaben ein.
#: Das Zerlegen ist ein Erfolg, kein Abbruch.
SELF_DECOMPOSE_INSTRUCTION = (
    "Kannst du die Aufgabe in diesem Lauf nicht vollständig erledigen (zu groß, Werkzeugrunden "
    "werden knapp, Teilschritte fehlen), dann zerlege sie selbst in kleinere, einzeln erledigbare "
    "Teilaufgaben: task_manage(action='decompose', task_id=<ID>, subtasks=[{\"title\": \"...\", "
    "\"description\": \"Datei, Stelle, was genau zu tun ist\"}, ...], sequential=true, close_parent=false). "
    "Die bestätigte Teilaufgabenanlage ist ein Fortschritt; sie erledigt den Eltern-Task nicht. "
    "Gib anschließend mit task_manage(action='submit_result', task_id=<ID>, result='<Zerlegungsplan, "
    "bestätigte Kind-IDs, offene Arbeit>') den Plan zur getrennten Abnahme ab. Ohne bestätigten Werkzeugbeleg "
    "keinen Taskabschluss behaupten."
)


def tool_round_counter(round_num: int, max_rounds: int) -> str:
    """Rundenzähler für das Modell, z. B. ``[Werkzeugrunde 3/25 · noch 22]``."""
    if max_rounds > 0:
        return f"[Werkzeugrunde {round_num}/{max_rounds} · noch {max(0, max_rounds - round_num)}]"
    return f"[Werkzeugrunde {round_num} · ohne Limit]"


def tool_round_warning_threshold(max_rounds: int) -> int:
    """Ab wie vielen Restrunden gewarnt wird: mindestens 2, sonst ein Fünftel."""
    return max(2, -(-max_rounds // 5)) if max_rounds > 0 else 0


def _resume_handoff_context(original, summary, *, background_task, has_tools,
                            round_num, max_rounds):
    """Bewahrt die Rolle und setzt genau die aktuellen Laufhinweise ein."""
    history = [
        message for message in summary
        if message.get("role") != "system"
        and message.get("content") != SELF_DECOMPOSE_INSTRUCTION
        and not re.fullmatch(
            r"\[Werkzeugrunde \d+(?:/\d+ · noch \d+| · ohne Limit)\]",
            str(message.get("content", "")),
        )
    ]
    messages = [message for message in original if message.get("role") == "system"] + history
    if background_task and has_tools:
        messages.append({"role": "user", "content": SELF_DECOMPOSE_INSTRUCTION})
    messages.append({"role": "user", "content": tool_round_counter(round_num, max_rounds)})
    return messages, history

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


def _tool_dispatch_kwargs(session, agent_operations):
    """Build dispatcher context only from trusted runtime session state."""
    binding = getattr(session, "worker_task_binding", None)
    require_binding = getattr(session, "require_task_binding", False)
    grants = getattr(session, "allowed_tools", None)
    kwargs = {}
    if agent_operations is not None:
        # Preserve the existing managed-agent contract.
        kwargs = {"agent_operations": agent_operations, "allowed_tools": grants}
    if binding is not None or require_binding:
        kwargs.update({
            "worker_task_binding": binding,
            "require_task_binding": require_binding,
        })
        # Bound workers need the runtime's grant even when the managed-agent
        # controller is absent. Never infer it from the model's tool arguments.
        if binding is not None and agent_operations is None:
            kwargs["allowed_tools"] = grants
    return kwargs


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



_SAFE_FAILURE_REASON_CODES = frozenset({
    "local_reserve_invalid_policy",
    "local_reserve_unknown_model",
    "local_reserve_unsupported_provider",
    "local_reserve_missing_model_budget",
    "local_reserve_model_budget_conflict",
    "local_reserve_budget_exceeds_host",
    "local_reserve_resource_policy_changed",
    "local_reserve_reserve_wait_expired",
    "local_reserve_reserve_wait_lease_return_required",
})


def _local_reserve_failure(exc: BaseException) -> tuple[str | None, str]:
    """Project only the reserve service's finite public decision vocabulary."""
    from hub._services.chat.local_resource_reserve import LocalReserveError
    if not isinstance(exc, LocalReserveError):
        return None, ""
    prefix = "Lokale Ressourcenfreigabe: "
    message = str(exc)
    decision = message[len(prefix):] if message.startswith(prefix) else ""
    code = f"local_reserve_{decision}" if decision else ""
    if code not in _SAFE_FAILURE_REASON_CODES:
        return None, "Lokale Ressourcenfreigabe fehlgeschlagen"
    safe_messages = {
        "local_reserve_reserve_wait_expired": "Lokale Ressourcenreserve wurde nicht rechtzeitig frei",
        "local_reserve_reserve_wait_lease_return_required": "Task-Lease wird vor der lokalen Kapazitätswarte zurückgegeben",
        "local_reserve_budget_exceeds_host": "Lokales Modell überschreitet das verfügbare Hostbudget",
        "local_reserve_resource_policy_changed": "Ressourcenrichtlinie änderte sich während der Prüfung",
        "local_reserve_invalid_policy": "Ressourcenrichtlinie ist nicht verifizierbar",
        "local_reserve_unknown_model": "Lokales Modell ist nicht verifizierbar",
        "local_reserve_unsupported_provider": "Lokaler Anbieter wird nicht unterstützt",
        "local_reserve_missing_model_budget": "Modellbudget fehlt",
        "local_reserve_model_budget_conflict": "Modellbudget stimmt nicht mit dem beobachteten Ziel überein",
    }
    return code, safe_messages[code]


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

    def __new__(cls, value, *, backend_error=None, reason_code=None):
        from hub._services.llm.backend_errors import normalize_backend_error
        answer = super().__new__(cls, value)
        answer.backend_error = normalize_backend_error(backend_error)
        answer.reason_code = (
            reason_code if isinstance(reason_code, str) and reason_code in _SAFE_FAILURE_REASON_CODES else None
        )
        return answer

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
        """Convert a caught failure, redacting reserve details to a finite code."""
        reason_code, safe_message = _local_reserve_failure(exc)
        if reason_code is not None:
            return cls(f"{cls.PREFIX}{safe_message}", reason_code=reason_code)
        from hub._services.chat.local_resource_reserve import LocalReserveError
        if isinstance(exc, LocalReserveError):
            return cls(f"{cls.PREFIX}{safe_message}")
        return cls(f"{cls.PREFIX}{type(exc).__name__}: {exc}".rstrip(": "))


class SuccessfulAnswer(str):
    """Successful text with explicit status or task completion metadata.

    BACH's older order-worker seams are text-only and call ``startswith`` on
    the callback result. This narrow ``str`` subtype keeps the visible answer
    unchanged while making that legacy probe agree with the explicit success
    status. Tool-confirmed task IDs can also travel on this immutable answer
    instance, rather than a mutable per-chat buffer. Other answers stay strings.
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
            ),
            backend_error=result.get("backend_error"),
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
        self._trusted_memory_hook_opt_in: bool = False
        self.custom_system_prompt: str = ""
        self.profile_binding: dict | None = None
        self.profile_context_text: str = ""
        self.chat_id: str = ""
        self.operator_control: Any = None
        self.worker_handoff: Any = None
        self.resolved_model: str = ""
        self.worker_task_actions: Any = None
        self.worker_task_binding: Any = None
        self.require_task_binding: bool = False
        self._persistent_core_model_call_control: Any = None
        self._worker_model_dispatch_binding: Any = None
        self._local_reserve_failure_binding: Any = None
        self._local_reserve_failure_control: Any = None
        self._local_reserve_failure_reason_code: str | None = None

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
                 session_store=None, agent_operations=None):
        self.backend = backend
        self.base_system = system_prompt
        self.bach_app = bach_app
        self.memory = memory_fn
        self.injector = injector
        self.session_store = session_store
        self.agent_operations = agent_operations
        self.compute_gate = None
        self._sessions = {}
        self._session_locks = {}
        self._chat_turn_gates: dict[str, _ChatTurnGate] = {}
        self._chat_turn_gates_lock = threading.Lock()
        self._compute_turn_gate = _ComputeTurnGate()
        self._local_resource_waiters: dict[str, dict] = {}
        self._local_resource_waiters_lock = threading.Lock()
        self._compute_turn_context = ContextVar(
            f"bach_compute_turn_context_{id(self)}", default=None
        )
        self._task_completion_receipts: dict[str, list[int]] = {}
        self._task_completion_receipts_lock = threading.Lock()
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
            registry=BachToolProvider(bach_app, backend.get_default_model if hasattr(backend, "get_default_model") else None,
                                      agent_operations=agent_operations),
            memory_fn=memory_fn,
            injector=injector,
        )

    @staticmethod
    def _refresh_worker_tools(session: ChatSession) -> FailedAnswer | None:
        # This value is session-local and refreshed only from a native slot
        # reader. Prompt/request text never supplies MemoryHook authority.
        session._trusted_memory_hook_opt_in = False
        system_memory_hook_opt_in = False
        has_system_slot = False
        system_reader = getattr(session, "system_slot_reader", None)
        if system_reader is not None:
            try:
                system_slot = system_reader()
                if (not system_slot or system_slot.get("id") != session.system_slot_id
                        or system_slot.get("enabled", True) is not True):
                    raise RuntimeError("Systemsteckplatz ist ausgeschaltet oder nicht verfügbar")
                expected = getattr(session, "system_slot_configuration", {})
                if any(system_slot.get(key) != value for key, value in expected.items()):
                    raise RuntimeError("Steckplatzkonfiguration hat sich während des Turns geändert")
                system_memory_hook_opt_in = system_slot.get("memory_hook_opt_in", False)
                if type(system_memory_hook_opt_in) is not bool:
                    raise RuntimeError("Steckplatz MemoryHook-Opt-in ist nicht verifizierbar")
                has_system_slot = True
                session.allow_tools = system_slot.get("allow_tools", True) is True
                session.allowed_tools = system_slot.get("allowed_tools")
                from hub._services.skill_source_service import load_skill_instructions
                load_skill_instructions(system_slot.get("skill_refs", []))
            except Exception as exc:
                session.allow_tools = False
                session._trusted_memory_hook_opt_in = False
                return FailedAnswer.from_exception(exc)
        reader = getattr(session, "worker_slot_reader", None)
        if reader is None:
            session._trusted_memory_hook_opt_in = system_memory_hook_opt_in if has_system_slot else False
            return None
        try:
            slot = reader()
            if not isinstance(slot, dict) or slot.get("id") != getattr(session, "chat_id", ""):
                raise RuntimeError("Worker-Slot fehlt oder stimmt nicht überein")
            if slot.get("enabled", True) is not True:
                raise RuntimeError("Worker ist deaktiviert")
            worker_memory_hook_opt_in = slot.get("memory_hook_opt_in", False)
            if type(worker_memory_hook_opt_in) is not bool:
                raise RuntimeError("Worker MemoryHook-Opt-in ist nicht verifizierbar")
            # A worker reader is the more specific authority when a session
            # carries both a system caller and a dynamic worker binding.
            session._trusted_memory_hook_opt_in = worker_memory_hook_opt_in
            session.allow_tools = slot.get("allow_tools", True) is True
            session.allowed_tools = slot.get("allowed_tools")
            from hub._services.skill_source_service import load_skill_instructions
            load_skill_instructions(slot.get("skill_refs", []))
            return None
        except Exception as exc:
            session.allow_tools = False
            session._trusted_memory_hook_opt_in = False
            return FailedAnswer.from_exception(exc)

    @staticmethod
    def _native_model_fallback_route(session: ChatSession, backend: Any, model: Any):
        """Resolve a target only from the session's trusted native profile reader."""
        reader = getattr(session, "worker_slot_reader", None)
        expected_id = getattr(session, "chat_id", "")
        if reader is None:
            reader = getattr(session, "system_slot_reader", None)
            expected_id = getattr(session, "system_slot_id", None)
        if reader is None:
            return None
        if not callable(reader):
            # Keep ValueError so callers retain the established redacted invalid-profile result.
            raise ValueError("Native Profilquelle ist nicht aufrufbar")  # noqa: TRY004
        profile = reader()
        if (not isinstance(profile, dict) or profile.get("id") != expected_id
                or profile.get("enabled", True) is not True):
            raise ValueError("Native Profilquelle stimmt nicht überein")
        from hub._services.chat.model_sockets import (
            model_fallbacks_for_profile,
            profile_backend_matches,
        )
        chain = model_fallbacks_for_profile(profile)
        if not chain:
            return None
        primary_backend, primary_model = profile.get("backend"), profile.get("model")
        if (not isinstance(primary_backend, str) or not isinstance(primary_model, str)
                or not isinstance(model, str)):
            # Keep ValueError for malformed native profile data; callers redact it as a failed route.
            raise ValueError("Fallbackprofil hat kein eindeutiges Primärziel")  # noqa: TRY004
        targets = [{"backend": primary_backend, "model": primary_model}, *chain]
        matched = [
            index for index, target in enumerate(targets)
            if target["model"] == model
            and profile_backend_matches(target["backend"], backend, model)
        ]
        if len(matched) != 1:
            raise ValueError("Modellziel ist nicht in der nativen Fallbackkette")
        return {"profile": profile, "targets": targets, "index": matched[0]}

    @staticmethod
    def _safe_preanswer_fallback_failure(*, result=None, error=None) -> bool:
        """Allow only typed failures that prove no answer or tool call escaped."""
        if error is not None:
            from hub._services.chat.local_resource_reserve import LocalReserveError
            if isinstance(error, LocalReserveError):
                return str(error) in {
                    "Lokale Ressourcenfreigabe: budget_exceeds_host",
                    "Lokale Ressourcenfreigabe: reserve_wait_expired",
                }
            try:
                import httpx
            except ImportError:
                return False
            if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                return True
            if isinstance(error, httpx.HTTPStatusError):
                # A bare status cannot distinguish rate limiting from provider quota.
                return False
            return False

        if not isinstance(result, dict) or not result.get("error"):
            return False
        if result.get("content") or result.get("thinking") or result.get("tool_calls"):
            return False
        raw_message = result.get("raw_message")
        if raw_message:
            if not isinstance(raw_message, dict):
                return False
            if any(raw_message.get(key) for key in ("content", "thinking", "tool_calls")):
                return False
        from hub._services.llm.backend_errors import normalize_backend_error
        detail = normalize_backend_error(result.get("backend_error"))
        return bool(
            detail
            and not detail.get("quota_exceeded")
            and detail.get("kind") in {"rate_limited", "http_error"}
            and detail.get("status_code") in {429, 502, 503, 504, 529}
        )

    async def _chat_with_configured_fallbacks(self, session, backend, model, *args, **kwargs):
        """Advance one explicit native chain only after a typed pre-answer failure."""
        try:
            route = self._native_model_fallback_route(session, backend, model)
        except Exception:  # noqa: BLE001 - redact native profile reader details at the runtime boundary.
            raise RuntimeError("Native Modellfallbackkette ist nicht verifizierbar") from None
        if route is None:
            result = await self._chat_with_compute_turn(
                backend, *args, **{**kwargs, "model": model}
            )
            return result, backend, model

        targets = route["targets"]
        last_exception = None
        from hub._services.chat.model_sockets import resolve_fallback_backend
        for index in range(route["index"], len(targets)):
            target = targets[index]
            if index == route["index"]:
                active_backend = backend
            else:
                try:
                    active_backend = resolve_fallback_backend(target)
                except Exception:  # noqa: BLE001 - redact resolver details; report only the configured target.
                    raise RuntimeError(
                        f"Konfiguriertes Fallbackziel ist nicht verfügbar: {target['backend']}"
                    ) from None
                problem = self._worker_backend_gate(session, active_backend, target["model"])
                if problem is not None:
                    raise RuntimeError(str(problem))

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = target["model"]
            try:
                result = await self._chat_with_compute_turn(
                    active_backend, *args, **call_kwargs
                )
            except Exception as exc:
                # The persistent core is explicitly pinned to its selected local
                # model; reserve exhaustion must not silently downgrade or route elsewhere.
                from hub._services.chat.local_resource_reserve import LocalReserveError
                if (getattr(session, "chat_id", None) == "buddha_always_on"
                        and isinstance(exc, LocalReserveError)):
                    raise
                # A self-managed CLI can finish tool effects before an exception.
                # Without a typed no-tool receipt, the failure cannot authorize retry.
                if (getattr(active_backend, "manages_own_tools", False)
                        or not self._safe_preanswer_fallback_failure(error=exc)):
                    raise
                last_exception = exc
                if index + 1 < len(targets):
                    log.info("Konfiguriertes Modellfallback nach sicherem Vorabfehler: %s", target["backend"])
                    continue
                break
            if (not getattr(active_backend, "manages_own_tools", False)
                    and self._safe_preanswer_fallback_failure(result=result)
                    and index + 1 < len(targets)):
                log.info("Konfiguriertes Modellfallback nach sicherem Vorabfehler: %s", target["backend"])
                continue
            return result, active_backend, target["model"]

        if last_exception is not None:
            raise RuntimeError("Konfigurierte Modellfallbackkette ausgeschöpft") from None
        return {"error": "Konfigurierte Modellfallbackkette ausgeschöpft"}, backend, model

    @classmethod
    def _worker_backend_gate(cls, session: ChatSession, backend: Any, model: Any = None) -> FailedAnswer | None:
        capability_error = cls._refresh_worker_tools(session)
        if capability_error is not None:
            return capability_error
        try:
            cls._native_model_fallback_route(session, backend, model)
        except Exception:  # noqa: BLE001 - fail closed without exposing native profile details.
            return FailedAnswer("Native Modellfallbackkette ist nicht verifizierbar")
        binding = getattr(session, "worker_task_binding", None)
        if binding is None and getattr(session, "require_task_binding", False):
            return FailedAnswer("Taskbindung fehlt; Workerlauf nicht verifizierbar")
        if binding is not None:
            try:
                binding.assert_active()
            except Exception:
                return FailedAnswer("Taskbindung oder Workerlauf ist nicht mehr aktiv")
            actions = getattr(session, "worker_task_actions", None)
            if actions is not None:
                try:
                    actions.validate(binding)
                except Exception:
                    return FailedAnswer("Angeforderte Taskaktion oder Inhaltsversion ist nicht mehr aktuell")
            from .slots_config import task_matches_slot_binding
            if not task_matches_slot_binding(binding.task_snapshot(), {
                    "id": getattr(session, "chat_id", ""), "model": model}):
                return FailedAnswer("Task passt nicht zur aktuellen Slot- oder Modellauswahl")
            if getattr(backend, "manages_own_tools", False):
                from hub._services.llm.model_backend import CLIBackend
                if not isinstance(backend, CLIBackend) or backend.cli_name != "claude":
                    return FailedAnswer("Lease-Anbindung für die eigenen Backend-Werkzeuge fehlt")
                handoff = getattr(session, "worker_handoff", None)
                pending = [control.snapshot() for control in (actions, handoff) if control is not None]
                if any(receipt and receipt.get("state") in {"pending", "running"} for receipt in pending):
                    return FailedAnswer("Angeforderte Blockaktion ist für dieses CLI-Backend nicht verfügbar")
        if (getattr(session, "allowed_tools", None) is not None and binding is None
                and getattr(backend, "manages_own_tools", False)):
            return FailedAnswer("Toolfreigaben für dieses CLI benötigen einen gebundenen Task")
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
                    item["content"] = FailedAnswer(
                        content, backend_error=item.get("backend_error"),
                        reason_code=item.get("reason_code"),
                    )
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
              if key not in (FailedAnswer.STATUS_KEY, "completed_task_ids", "backend_error", "reason_code")}
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
                elif status == FailedAnswer.STATUS_SUCCESS or getattr(content, "answer_status", None) == FailedAnswer.STATUS_SUCCESS:
                    status = FailedAnswer.STATUS_SUCCESS
                else:
                    status = (
                        FailedAnswer.STATUS_FAILED
                        if FailedAnswer.legacy_looks_like(content)
                        else FailedAnswer.STATUS_SUCCESS
                    )
                item[FailedAnswer.STATUS_KEY] = status
                from hub._services.llm.backend_errors import normalize_backend_error
                detail = normalize_backend_error(getattr(content, "backend_error", None) or item.get("backend_error"))
                item.pop("backend_error", None)
                if detail is not None and status == FailedAnswer.STATUS_FAILED:
                    item["backend_error"] = detail
                reason_code = getattr(content, "reason_code", None) or item.get("reason_code")
                item.pop("reason_code", None)
                if (status == FailedAnswer.STATUS_FAILED and isinstance(reason_code, str)
                        and reason_code in _SAFE_FAILURE_REASON_CODES):
                    item["reason_code"] = reason_code
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
        if not hasattr(session, "_trusted_memory_hook_opt_in"):
            session._trusted_memory_hook_opt_in = False
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
    async def _enter_compute_turn(gate: _ComputeTurnGate, chat_id: str, priority: str, *, check_ready=None) -> None:
        waiting_foreground = priority == "foreground"
        registered_waiter = False
        try:
            if waiting_foreground:
                with gate.condition:
                    gate.foreground_waiters += 1
                    registered_waiter = True
            while True:
                if check_ready is not None:
                    check_ready()
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

    def _model_binding_for_session(self, chat_id, backend, model, session):
        from hub._services.chat.model_sockets import model_binding_for_call
        from hub._services.llm.model_backend import backend_identifier

        agent_id = getattr(session, "system_slot_id", None) if session is not None else None
        if agent_id is None and session is not None and getattr(session, "worker_slot_reader", None):
            agent_id = session.worker_slot_reader().get("id")
        target_backend = backend_identifier(backend) or getattr(backend, "backend_id", "")
        return model_binding_for_call(
            chat_id, target_backend, str(model), agent_id=agent_id,
            require_config=getattr(self, "require_model_socket_config", False),
        )

    async def prepare_inference_call(self, backend, model, *, chat_id=None):
        """Probe the actual target and binding without taking a compute owner.

        Resource waits are receipts, not admission to inference. Callers must
        recheck after waiting; external aliases never need a local binding.
        """
        from hub._services.chat.local_resource_reserve import (
            LocalReserveError,
            probe,
            read_policy,
            require_retryable,
        )
        from hub._services.chat.local_model_admission import compose_admission_receipt

        session = (self.sessions.get(str(chat_id)) or self.get_session(chat_id)) if chat_id is not None else None
        if session is not None and (getattr(session, "worker_task_binding", None) is not None
                or getattr(session, "worker_slot_reader", None) is not None
                or getattr(session, "require_task_binding", False)):
            # Keep only the most recent internal capacity receipt for the
            # caller's terminal, pre-tool reserve recovery decision.
            session._local_reserve_failure_receipt = None
            session._local_reserve_failure_binding = None
            session._local_reserve_failure_control = None
            session._local_reserve_failure_reason_code = None

        def check_caller():
            if session is not None and (
                getattr(session, "worker_task_binding", None) is not None
                or getattr(session, "require_task_binding", False)
                or getattr(session, "system_slot_reader", None) is not None
                or getattr(session, "worker_slot_reader", None) is not None
            ):
                problem = self._worker_backend_gate(session, backend, model)
                if problem is not None:
                    raise RuntimeError(str(problem))

        check_caller()
        if not self._uses_local_compute(backend) or str(model).lower().endswith(":cloud"):
            return None, None
        receipt = await probe(backend, model)
        try:
            _, version = read_policy()
        except (OSError, ValueError, TypeError, UnicodeError):
            raise LocalReserveError("Lokale Ressourcenfreigabe: invalid_policy") from None
        if receipt.get("policy_version") != version:
            raise LocalReserveError("Lokale Ressourcenfreigabe: resource_policy_changed")
        check_caller()
        if receipt["state"] == "external_target":
            return receipt, None
        require_socket = bool(getattr(self, "require_model_socket_config", False))
        binding = None
        if receipt["admitted"] or receipt["state"] in {"waiting_memory_reserve", "waiting_disk_reserve"}:
            binding = self._model_binding_for_session(chat_id or "runtime", backend, model, session)
        receipt = compose_admission_receipt(
            receipt, binding=binding, require_model_socket=require_socket)
        require_retryable(receipt)
        return receipt, binding

    def _persistent_core_pre_effect_reserve_receipt(
        self, *, session, binding, backend, model, priority, receipt,
    ):
        """Return a sanitized wait receipt only for this controller's first, tool-free call."""
        waiting = {"waiting_memory_reserve", "waiting_disk_reserve"}
        if (priority != "background" or not isinstance(receipt, dict)
                or receipt.get("state") not in waiting or receipt.get("admitted") is not False
                or receipt.get("enforced") is not True or receipt.get("retryable") is not True
                or not self._uses_local_compute(backend)
                or not isinstance(model, str) or model.lower().endswith(":cloud")):
            return None
        control = getattr(session, "_persistent_core_model_call_control", None)
        if (session is None or control is None or binding is None
                or getattr(session, "worker_task_binding", None) is not binding
                or getattr(session, "require_task_binding", False) is not True
                or getattr(control, "worker_id", None) != "buddha_always_on"
                or getattr(control, "task_binding", None) is not binding
                or getattr(session, "_worker_model_dispatch_binding", None) is binding
                or type(getattr(binding, "tool_dispatch_count", None)) is not int
                or binding.tool_dispatch_count != 0
                or getattr(binding, "closed", True) is not False
                or getattr(control, "persistent_core_startup_cancelled", True) is not False):
            return None
        stop_event = getattr(control, "stop_event", None)
        startup_confirmed = getattr(control, "persistent_core_startup_confirmed", None)
        if (stop_event is None or not callable(getattr(stop_event, "is_set", None))
                or stop_event.is_set() or startup_confirmed is None
                or not callable(getattr(startup_confirmed, "is_set", None))
                or not startup_confirmed.is_set()):
            return None
        intent_id = getattr(control, "persistent_core_intent_id", None)
        profile_version = getattr(control, "persistent_core_profile_version", None)
        checkpoint = getattr(control, "persistent_core_checkpoint", None)
        recovery_state = getattr(control, "persistent_core_recovery_state", None)
        if (not isinstance(intent_id, str) or re.fullmatch(r"[0-9a-f]{32}", intent_id) is None
                or not isinstance(profile_version, str)
                or re.fullmatch(r"[0-9a-f]{64}", profile_version) is None
                or not isinstance(checkpoint, dict) or checkpoint.get("phase") != "admitted"
                or not isinstance(recovery_state, dict) or recovery_state.get("phase") != "active"):
            return None
        try:
            binding.assert_active()
            from hub._services.chat import slots_config
            snapshot = slots_config.persistent_core_startup_snapshot()
            worker = snapshot.get("slot") if isinstance(snapshot, dict) else None
            if (not isinstance(worker, dict)
                    or snapshot.get("state") != "prior_generation_unsettled"
                    or snapshot.get("worker_id") != "buddha_always_on"
                    or snapshot.get("intent_id") != intent_id
                    or snapshot.get("profile_version") != profile_version
                    or snapshot.get("checkpoint") != checkpoint
                    or snapshot.get("recovery_state") != recovery_state
                    or worker.get("id") != "buddha_always_on"
                    or worker.get("backend") != "ollama"
                    or worker.get("model") != model
                    or worker.get("persistent_opt_in") is not True
                    or worker.get("persistent_opt_in_id") != intent_id
                    or worker.get("persistent_opt_in_profile_version") != profile_version
                    or worker.get("status") != "running"
                    or slots_config._persistent_core_profile_version(worker) != profile_version
                    or not slots_config._valid_persistent_worker_controller_checkpoint(checkpoint)
                    or not slots_config._valid_persistent_core_recovery_state(
                        recovery_state, worker=worker, checkpoint=checkpoint)):
                return None
        except Exception:  # noqa: BLE001 -- malformed persisted proof fails closed
            return None

        capacity_fields = {
            "schema", "state", "admitted", "enforced", "retryable", "checked_at",
            "policy_version", "model", "wait_seconds", "poll_seconds",
            "memory_total_bytes", "memory_available_bytes", "memory_required_bytes",
            "disk_free_bytes", "disk_reserve_bytes", "weight_request_bytes",
            "resident_weight_credit",
        }
        if set(receipt) != capacity_fields | {"local_admission"}:
            return None
        admission = receipt.get("local_admission")
        if (not isinstance(admission, dict)
                or set(admission) != {"schema", "decision", "reserve", "model_socket", "capacity"}
                or admission.get("schema") != "bach.local-model-admission.v1"
                or admission.get("decision") != receipt.get("state")):
            return None
        reserve = admission.get("reserve")
        if (not isinstance(reserve, dict)
                or set(reserve) != {"schema", "state", "configured", "enforced", "policy_version"}
                or reserve.get("schema") != receipt.get("schema")
                or reserve.get("state") != receipt.get("state")
                or reserve.get("configured") is not True
                or reserve.get("enforced") is not True
                or reserve.get("policy_version") != receipt.get("policy_version")):
            return None
        model_socket = admission.get("model_socket")
        if (not isinstance(model_socket, dict)
                or model_socket.get("status") not in {"bound", "not_required"}):
            return None
        if model_socket.get("status") == "bound" and model_socket.get("model") != model:
            return None
        if admission.get("capacity") != {"status": "unknown", "certification": "not_provided"}:
            return None
        capacity_receipt = {key: receipt[key] for key in capacity_fields}
        try:
            observation = slots_config._persistent_core_capacity_observation(
                capacity_receipt, worker=worker, expected_state=receipt["state"],
            )
        except Exception:  # noqa: BLE001 -- unavailable capacity policy is not a reauthorization proof
            return None
        if observation is None or observation.get("state") not in waiting:
            return None
        return capacity_receipt

    async def _chat_with_compute_turn(self, backend, *args, **kwargs):
        """Hold the local-compute gate for one model call, then yield to waiters."""
        turn_context = self._compute_turn_context.get()
        def check_binding():
            if turn_context:
                session = self.get_session(turn_context[0])
                if (getattr(session, "worker_task_binding", None) is not None
                        or getattr(session, "require_task_binding", False)
                        or getattr(session, "system_slot_reader", None) is not None
                        or getattr(session, "worker_slot_reader", None) is not None):
                    problem = self._worker_backend_gate(session, backend, kwargs.get("model"))
                    if problem is not None:
                        raise RuntimeError(str(problem))
        check_binding()
        session = self.get_session(turn_context[0]) if turn_context else None
        binding = getattr(session, "worker_task_binding", None)
        def mark_model_dispatch():
            current_binding = getattr(session, "worker_task_binding", None) if session is not None else None
            if current_binding is not None:
                # Keep the exact binding object alive; token/id surrogates can be reused.
                session._worker_model_dispatch_binding = current_binding

        if binding is not None and getattr(backend, "manages_own_tools", False):
            agent_kwargs = {"agent_operations": self.agent_operations} if self.agent_operations is not None else {}
            mark_model_dispatch()
            return await backend.chat_bound(
                *args, **kwargs, binding=binding, mode=session.mode,
                guard=check_binding, bach_app=self.bach_app,
                allowed_tools=getattr(session, "allowed_tools", None),
                **agent_kwargs,
            )
        if not self._uses_local_compute(backend):
            mark_model_dispatch()
            return await backend.chat(*args, **kwargs)
        selected_model = kwargs.get("model") or backend.get_default_model()

        chat_id, priority = turn_context or ("runtime", "foreground")
        from hub._services.chat.host_inference_gate import HostInferenceGate

        session = self.get_session(chat_id) if turn_context else None
        guard = ({"check_ready": check_binding} if session is not None and (
            getattr(session, "worker_task_binding", None) is not None
            or getattr(session, "require_task_binding", False)
            or getattr(session, "system_slot_reader", None) is not None
            or getattr(session, "worker_slot_reader", None) is not None) else {})
        from hub._services.chat.local_resource_reserve import (
            LocalReserveError,
            read_policy,
            require_retryable,
        )

        def check_model_binding():
            return self._model_binding_for_session(chat_id, backend, selected_model, session)

        def check_local_ready():
            check_binding()
            check_model_binding()

        guard = {"check_ready": check_local_ready}
        deadline = None
        policy_bound = False
        policy_version = None

        def check_reserve_policy(receipt):
            # A metadata request or gate wait can yield after the probe read
            # its policy. Bind the file currently on disk before dispatch too.
            try:
                _, current_version = read_policy()
            except (OSError, ValueError, TypeError, UnicodeError):
                raise LocalReserveError("Lokale Ressourcenfreigabe: invalid_policy") from None
            if (receipt.get("policy_version") != policy_version
                    or current_version != policy_version):
                raise LocalReserveError("Lokale Ressourcenfreigabe: resource_policy_changed")

        try:
            while True:
                check_binding()
                receipt, _ = await self.prepare_inference_call(
                    backend, selected_model, chat_id=chat_id if turn_context else None)
                if receipt is None:
                    mark_model_dispatch()
                    return await backend.chat(*args, **kwargs)
                if not policy_bound:
                    policy_version = receipt.get("policy_version")
                    policy_bound = True
                check_reserve_policy(receipt)
                check_binding()
                if receipt["state"] == "external_target":
                    with self._local_resource_waiters_lock:
                        self._local_resource_waiters.pop(chat_id, None)
                    mark_model_dispatch()
                    return await backend.chat(*args, **kwargs)
                require_retryable(receipt)
                binding = getattr(session, "worker_task_binding", None) if session is not None else None
                pre_effect_receipt = self._persistent_core_pre_effect_reserve_receipt(
                    session=session, binding=binding, backend=backend, model=selected_model,
                    priority=priority, receipt=receipt,
                )
                if pre_effect_receipt is not None:
                    control = getattr(session, "_persistent_core_model_call_control", None)
                    session._local_reserve_failure_receipt = pre_effect_receipt
                    session._local_reserve_failure_binding = binding
                    session._local_reserve_failure_control = control
                    session._local_reserve_failure_reason_code = (
                        "local_reserve_reserve_wait_lease_return_required"
                    )
                    raise LocalReserveError(
                        "Lokale Ressourcenfreigabe: reserve_wait_lease_return_required"
                    )
                if receipt["admitted"]:
                    model_binding = check_model_binding()
                    target = ({key: model_binding[key] for key in
                              ("socket_id", "binding_id", "agent_id", "backend", "model")}
                              if model_binding is not None else None)
                    async with HostInferenceGate().turn(chat_id, priority, model_target=target, **guard):
                        # Resource availability can change while we waited for
                        # the existing host owner. Recheck under that owner.
                        receipt, _ = await self.prepare_inference_call(
                            backend, selected_model, chat_id=chat_id if turn_context else None)
                        if receipt is None:
                            raise RuntimeError("model_socket_target_changed")
                        check_reserve_policy(receipt)
                        check_binding()
                        require_retryable(receipt)
                        if receipt["admitted"] and receipt["state"] != "external_target":
                            current_binding = check_model_binding()
                            if current_binding != model_binding:
                                raise RuntimeError("model_socket_binding_changed")
                            await self._enter_compute_turn(self._compute_turn_gate, chat_id, priority, **guard)
                            try:
                                check_binding()
                                if check_model_binding() != model_binding:
                                    raise RuntimeError("model_socket_binding_changed")
                                check_reserve_policy(receipt)
                                with self._local_resource_waiters_lock:
                                    self._local_resource_waiters.pop(chat_id, None)
                                mark_model_dispatch()
                                return await backend.chat(*args, **kwargs)
                            finally:
                                self._leave_compute_turn(self._compute_turn_gate)
                    if receipt["state"] == "external_target":
                        # An alias may have changed while waiting. External
                        # inference runs only after returning the host owner.
                        check_binding()
                        check_reserve_policy(receipt)
                        with self._local_resource_waiters_lock:
                            self._local_resource_waiters.pop(chat_id, None)
                        mark_model_dispatch()
                        return await backend.chat(*args, **kwargs)
                # The host owner has been returned before reserve polling.
                # We stay at this model-call boundary: previous tools and the
                # task/session context are not replayed or reset.
                with self._local_resource_waiters_lock:
                    self._local_resource_waiters[chat_id] = dict(receipt)
                if deadline is None:
                    deadline = time.monotonic() + receipt["wait_seconds"]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if session is not None and (getattr(session, "worker_task_binding", None) is not None
                            or getattr(session, "worker_slot_reader", None) is not None):
                        fields = (
                            "schema", "state", "admitted", "enforced", "retryable", "checked_at",
                            "policy_version", "model", "memory_total_bytes", "memory_available_bytes",
                            "memory_required_bytes", "disk_free_bytes", "disk_reserve_bytes",
                            "weight_request_bytes", "resident_weight_credit",
                        )
                        session._local_reserve_failure_receipt = {
                            key: receipt[key] for key in fields if key in receipt
                        }
                    raise LocalReserveError("Lokale Ressourcenfreigabe: reserve_wait_expired")
                # Check cancellation, policy downgrades and native lease loss
                # frequently even if the resource probe interval is longer.
                poll_deadline = time.monotonic() + min(remaining, receipt["poll_seconds"])
                while time.monotonic() < poll_deadline:
                    check_binding()
                    await asyncio.sleep(min(.1, max(0, poll_deadline - time.monotonic())))
        finally:
            with self._local_resource_waiters_lock:
                self._local_resource_waiters.pop(chat_id, None)

    def _reset_task_completion_receipts(self, chat_id: str) -> None:
        with self._task_completion_receipts_lock:
            self._task_completion_receipts[str(chat_id)] = []

    def _record_task_completion_receipt(
        self, chat_id: str, tool_name: str, tool_args: Any, tool_result: str
    ) -> bool:
        """Record a successful `task_manage(done)` or self-decomposition receipt.

        Nutzerregel (Task #1697): Kann der Hintergrundworker eine Aufgabe nicht
        fertigstellen, zerlegt er sie selbst in kleinere Teilaufgaben und stellt
        sie ein. Diese Zerlegung ist ein Erfolg. Sie zählt nur, wenn das Werkzeug
        mindestens eine Teilaufgabe angelegt und den Eltern-Task geschlossen hat.
        """
        turn_context = self._compute_turn_context.get()
        if (
            turn_context is None
            or turn_context[0] != str(chat_id)
            or turn_context[1] != "background"
        ):
            return False
        if tool_name != "task_manage" or not isinstance(tool_args, dict):
            return False
        action = tool_args.get("action")
        if action not in ("done", "decompose"):
            return False
        try:
            task_id = int(tool_args.get("task_id"))
        except (TypeError, ValueError):
            return False
        if task_id <= 0:
            return False
        result_text = str(tool_result).strip()
        if action == "done":
            if result_text != f"Task #{task_id} erledigt.":
                return False
        else:
            if not tool_args.get("close_parent", True):
                return False
            match = _DECOMPOSE_RECEIPT_RE.fullmatch(result_text)
            if not match or int(match.group(1)) != task_id or int(match.group(2)) < 1:
                return False
            try:
                child_ids = json.loads(match.group(3))
            except ValueError:
                return False
            if (
                len(child_ids) != int(match.group(2))
                or any(type(child_id) is not int or child_id <= 0 or child_id == task_id
                       for child_id in child_ids)
                or len(set(child_ids)) != len(child_ids)
            ):
                return False
        with self._task_completion_receipts_lock:
            receipts = self._task_completion_receipts.setdefault(str(chat_id), [])
            if task_id in receipts:
                return False
            receipts.append(task_id)
        return True

    def get_last_task_completion_receipts(self, chat_id: str) -> tuple[int, ...]:
        """Return task IDs confirmed by successful task-management tool calls."""
        with self._task_completion_receipts_lock:
            return tuple(self._task_completion_receipts.get(str(chat_id), ()))

    def consume_task_completion_receipts(self, chat_id: str) -> tuple[int, ...]:
        """Return and discard receipts after a worker block has consumed them."""
        with self._task_completion_receipts_lock:
            return tuple(self._task_completion_receipts.pop(str(chat_id), ()))

    def compute_turn_status(self) -> dict[str, Any]:
        """Return live evidence about which BACH run currently owns local inference."""
        from hub._services.chat.host_inference_gate import HostInferenceGate

        result = HostInferenceGate().status()
        with self._local_resource_waiters_lock:
            if self._local_resource_waiters:
                result["resource_waiters"] = [
                    {"chat_id": chat_id, **receipt}
                    for chat_id, receipt in list(self._local_resource_waiters.items())[:64]
                ]
                result["resource_waiter_count"] = len(self._local_resource_waiters)
        return result

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
             "ok": not FailedAnswer.message_is_failed(m),
             **({"completed_task_ids": list(m["completed_task_ids"])}
                if m.get("completed_task_ids") else {})}
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
- 2. ZERLEGEN: Wenn umfangreich aber verstanden, mit task_manage(action='decompose', task_id=<ID>, subtasks=[{"title": "...", "description": "Datei, Stelle, nächste Schritte"}], sequential=true) in konkrete Einzelschritte zerlegen. Erst die Werkzeugbestätigung belegt einen Abschluss.
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
        if agent_context is not None:
            await self._enter_profile_turn(gate)
        else:
            await self._enter_chat_turn(gate)
        compute_context_token = self._compute_turn_context.set((
            str(chat_id), self._process_priority(chat_id, work_priority)
        ))
        try:
            if self._process_priority(chat_id, work_priority) == "background":
                self._reset_task_completion_receipts(chat_id)
                # A previous task's resolved model is not evidence for this run.
                # Do not create a chat session before local compute admission.
                cached_session = self.sessions.get(chat_id)
                if cached_session is not None:
                    cached_session.resolved_model = None
            if agent_context is not None:
                self.bind_profile_session(chat_id, agent_context)
            return await self._process_turn(
                text, chat_id, backend=backend, model=model,
                skip_compute_gate=skip_compute_gate, **kwargs,
            )
        finally:
            self._compute_turn_context.reset(compute_context_token)
            self._leave_chat_turn(gate)

    async def _process_turn(self, text: str, chat_id: str, *, backend=None, model=None,
                            skip_compute_gate: bool = False, **kwargs) -> str:
        """Verarbeitet eine User-Nachricht und gibt die Antwort zurück."""
        # Jeder lokale Modellaufruf nutzt _chat_with_compute_turn. Das Gate
        # wird nach jeder Inferenz freigegeben, damit ein wartender Vordergrund-
        # Chat vor der nächsten Hintergrund-Toolrunde rechnen kann.
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
            actual_local = True
            if self._uses_local_compute(selected_backend):
                candidate_model = model or getattr(known_session, "model", "") or selected_backend.get_default_model()
                receipt, _ = await self.prepare_inference_call(
                    selected_backend, candidate_model, chat_id=chat_id if known_session is not None else None)
                # A localhost Ollama cloud proxy does not compete for this
                # host's compute. Do not bypass using a stale caller receipt.
                actual_local = receipt is not None and receipt["state"] != "external_target"
            if actual_local:
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
            from .slots_config import (system_slot_chat_id, get_system_slot,
                compose_worker_prompt, CORE_EDITABLE_FIELDS)
            system_id = system_slot_chat_id(chat_id)
            if system_id:
                from hub._services.llm.model_backend import backend_identifier
                slot = get_system_slot(system_id)
                if not slot or slot.get("enabled", True) is not True:
                    raise ValueError("Systemsteckplatz ist ausgeschaltet")
                expected_backend = "ollama" if slot["backend"] == "ollama-cloud" else slot["backend"]
                if selected_model != slot["model"] or backend_identifier(selected_backend) != expected_backend:
                    raise ValueError("Steckplatz-Anbieter oder Modell wurde inzwischen geändert")
                session.mode = slot["mode"]
                session.think = slot["think"]
                session.allow_tools = slot.get("allow_tools", True) is True
                session.max_tool_rounds = slot["max_tool_rounds"]
                session.system_slot_id = system_id
                session.system_slot_reader = lambda: get_system_slot(system_id)
                session.system_slot_configuration = {key: slot.get(key) for key in CORE_EDITABLE_FIELDS if key != "enabled"}
                session.custom_system_prompt = compose_worker_prompt({
                    **slot, "custom_role_prompt": session.profile_context_text})
            else:
                session.custom_system_prompt = self.build_system_prompt(
                    session, profile_context=session.profile_context_text)
        capability_error = self._worker_backend_gate(session, selected_backend, selected_model)
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
            capability_error = self._worker_backend_gate(session, selected_backend, selected_model)
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
        sys_prompt = getattr(session, "custom_system_prompt", "") or self.build_system_prompt(session)
        if bach_ctx and not getattr(session, "custom_system_prompt", ""):
            sys_prompt += f"\n\n--- BACH ---\n{bach_ctx}"
        custom_prompt = getattr(session, "custom_system_prompt", "")
        legacy_memory_hook = session.profile_binding is None and not custom_prompt
        configured_memory_hook = getattr(session, "_trusted_memory_hook_opt_in", False) is True
        if legacy_memory_hook or configured_memory_hook:
            # Assemble the persona first, then evaluate the existing hook once.
            # Only a native slot reader can opt profile/custom-prompt sessions in.
            hook_ctx = self._get_memory_hook_context(text, chat_id)
            if hook_ctx:
                sys_prompt += f"\n\n--- MEMORY-HOOK ---\n{hook_ctx}"
        if session.allow_tools is False:
            sys_prompt += "\n\n[CAPABILITY-GATE: Keine Werkzeuge verfügbar. Antworte ohne Tool-Aufrufe.]"

        msgs = [{"role": "system", "content": sys_prompt}] + self._messages_for_backend(
            session.messages
        )

        if getattr(selected_backend, "manages_own_tools", False):
            if session.allow_tools is True and self._compute_turn_context.get() == (str(chat_id), "background"):
                msgs[0]["content"] += "\n\n" + SELF_DECOMPOSE_INSTRUCTION
            capability_error = self._worker_backend_gate(session, selected_backend, selected_model)
            if capability_error is not None:
                session.messages.append({"role": "assistant", "content": capability_error})
                self._persist_session(chat_id, session)
                return capability_error
            try:
                result = await self._chat_with_compute_turn(
                    selected_backend,
                    msgs, think=session.think, model=selected_model
                )
                answer = _managed_backend_answer(result)
                resolved = result.get("model") if isinstance(result, dict) else None
                if (not FailedAnswer.looks_like(answer) and isinstance(resolved, str) and resolved.strip()):
                    session.resolved_model = resolved
                    if chat_id:
                        try:
                            from hub._services.chat.slots_config import update_slot
                            update_slot(str(chat_id), {"resolved_model": resolved})
                        except Exception:
                            pass
            except Exception as e:
                answer = FailedAnswer.from_exception(e)
        else:
            tools = tools_for_mode(session.mode, bound_worker=session.worker_task_binding is not None) if (self.max_tool_rounds > 0 and session.allow_tools is True) else []
            grants = getattr(session, "allowed_tools", None)
            if grants is not None:
                tools = [tool for tool in tools if tool["function"]["name"] in grants]
            answer = await self._tool_loop(
                msgs,
                session,
                tools,
                backend=selected_backend,
                model=selected_model,
                context_limit=context_limit,
            )
        answer = _classify_successful_answer(answer)
        completed_task_ids = ()
        if self._compute_turn_context.get() == (str(chat_id), "background") and not isinstance(answer, FailedAnswer):
            completed_task_ids = self.get_last_task_completion_receipts(chat_id)
        if completed_task_ids:
            answer = SuccessfulAnswer(answer)
            answer.completed_task_ids = completed_task_ids
        session.messages.append({
            "role": "assistant",
            "content": answer,
            FailedAnswer.STATUS_KEY: (
                FailedAnswer.STATUS_FAILED
                if isinstance(answer, FailedAnswer)
                else FailedAnswer.STATUS_SUCCESS
            ),
            **({"completed_task_ids": list(completed_task_ids)} if completed_task_ids else {}),
        })
        self._persist_session(chat_id, session)
        return answer

    async def _tool_loop(self, msgs: list, session: ChatSession,
                         tools: list, *, backend=None, model: str = "",
                         context_limit: int | None = None) -> str:
        actions = getattr(session, "worker_task_actions", None)
        try:
            return await self._tool_loop_impl(msgs, session, tools, backend=backend, model=model,
                                              context_limit=context_limit)
        finally:
            if actions is not None:
                actions.end_block()

    async def _tool_loop_impl(self, msgs: list, session: ChatSession,
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
        turn_context = self._compute_turn_context.get()
        background_task = turn_context is not None and turn_context[1] == "background"
        msgs.append({"role": "user", "content": tool_round_counter(0, max_rounds)})
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

            actions = getattr(session, "worker_task_actions", None)
            if actions is not None:
                try:
                    actions.consume(getattr(session, "worker_task_binding", None),
                                    backend=getattr(selected_backend, "name", type(selected_backend).__name__),
                                    model=selected_model)
                    if actions.instruction() is not None and (not tools or session.allow_tools is not True):
                        raise ValueError("Zerlegung benötigt verfügbare Task-Werkzeuge")
                except Exception as exc:
                    return FailedAnswer.from_exception(exc)

            handoff_control = getattr(session, "worker_handoff", None)
            if handoff_control is not None and handoff_control.closed:
                return FailedAnswer.from_exception(RuntimeError("Workerlauf beendet"))
            request_id = handoff_control.consume() if handoff_control is not None else None
            if request_id is not None:
                try:
                    summary = await self._handoff(
                        msgs, session, backend=selected_backend, model=selected_model, strict=True,
                    )
                    resumed, history = _resume_handoff_context(
                        msgs, summary, background_task=background_task,
                        has_tools=session.allow_tools is True and bool(offered_tools),
                        round_num=round_num, max_rounds=max_rounds,
                    )
                    if not handoff_control.finish(request_id, succeeded=True):
                        return FailedAnswer.from_exception(RuntimeError("Workerlauf während Übergabe beendet"))
                    msgs = resumed
                    session.messages = history
                    capability_error = self._refresh_worker_tools(session)
                    if capability_error is not None:
                        return capability_error
                    tools = offered_tools if session.allow_tools is True else []
                except Exception as exc:
                    handoff_control.finish(request_id, succeeded=False)
                    return FailedAnswer.from_exception(exc)

            if actions is not None:
                instruction = actions.instruction()
                if instruction is not None and (not tools or session.allow_tools is not True):
                    return FailedAnswer("Zerlegung benötigt verfügbare Task-Werkzeuge")
                if instruction is not None and not any(
                        message.get("role") == "user" and message.get("content") == instruction for message in msgs):
                    msgs.append({"role": "user", "content": instruction})

            try:
                previous_backend = selected_backend
                previous_model = selected_model
                result, selected_backend, selected_model = await self._chat_with_configured_fallbacks(
                    session, selected_backend, selected_model,
                    msgs, tools=tools, think=session.think,
                )
                if selected_backend is not previous_backend or selected_model != previous_model:
                    context_limit = self._context_limit_for_backend(selected_backend, selected_model)
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
                    + (f"\n[Teilantwort vor dem Abbruch]\n{teil}" if teil else ""),
                    backend_error=result.get("backend_error"),
                )

            resolved_model = result.get("model") if isinstance(result, dict) else None
            if isinstance(resolved_model, str) and resolved_model.strip():
                session.resolved_model = resolved_model
                cid = getattr(session, "chat_id", "")
                if cid:
                    try:
                        from hub._services.chat.slots_config import update_slot
                        update_slot(cid, {"resolved_model": resolved_model})
                    except Exception:
                        pass

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
                    summary = await self._handoff(
                        msgs,
                        session,
                        backend=selected_backend,
                        model=selected_model,
                        strict=selected_model == "glm-5.3:cloud",
                    )
                    msgs, session.messages = _resume_handoff_context(
                        msgs, summary, background_task=background_task,
                        has_tools=session.allow_tools is True and bool(offered_tools),
                        round_num=round_num, max_rounds=max_rounds,
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
                capability_error = self._worker_backend_gate(session, selected_backend, selected_model)
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
                log.info("Tool [%d] dispatch", round_num)
                cid = getattr(session, "chat_id", "")
                if cid:
                    try:
                        from hub._services.chat.slots_config import update_slot
                        slot_updates = {"current_activity": f"Tool [{round_num}]: {t_name}"}
                        if getattr(session, "resolved_model", None):
                            slot_updates["resolved_model"] = session.resolved_model
                        update_slot(cid, slot_updates)
                    except Exception:
                        pass
                # Updating activity may race with (or itself trigger) a
                # downgrade. Re-read immediately before dispatcher entry.
                capability_error = self._worker_backend_gate(session, selected_backend, selected_model)
                if capability_error is not None:
                    session.current_tool = ""
                    return capability_error
                if session.allow_tools is False:
                    session.current_tool = ""
                    return FailedAnswer(
                        f"{FailedAnswer.PREFIX}Tool-Aufruf im tool-freien Lauf blockiert"
                    )
                binding = getattr(session, "worker_task_binding", None)
                grants = getattr(session, "allowed_tools", None)
                if grants is not None and t_name not in grants:
                    return FailedAnswer("Werkzeug ist für diesen Agenten nicht freigegeben")
                tool_kwargs = _tool_dispatch_kwargs(session, self.agent_operations)
                traced_outcome = None
                if binding is not None:
                    from hub._services.chat.worker_tool_dispatch_trace import (
                        abandon_normal_tool_result,
                        acknowledge_normal_tool_result,
                        execute_normal_tool,
                    )
                    traced_outcome = execute_normal_tool(
                        binding, t_name, t_args,
                        lambda name, arguments: exec_tool(
                            name, arguments, session.mode,
                            bach_app=self.bach_app,
                            default_model=selected_model,
                            **tool_kwargs,
                        ),
                    )
                    if traced_outcome.status != "returned":
                        binding.invalidate()
                        session.current_tool = ""
                        return FailedAnswer(
                            "Worker-Werkzeugnachweis fehlt oder Werkzeugwirkung ist ungeklärt"
                        )
                    t_result = traced_outcome.result
                else:
                    t_result = exec_tool(
                        t_name, t_args, session.mode,
                        bach_app=self.bach_app,
                        default_model=selected_model,
                        **tool_kwargs,
                    )
                tool_call_id = ""
                if hasattr(selected_backend, "_last_tool_call_ids"):
                    ids = selected_backend._last_tool_call_ids
                    if i < len(ids):
                        tool_call_id = ids[i]
                try:
                    msgs.append(
                        selected_backend.tool_response_message(str(t_result), tool_call_id)
                    )
                except Exception:  # noqa: BLE001 - Never replay an unconsumed tool effect.
                    if traced_outcome is not None:
                        abandon_normal_tool_result(binding, traced_outcome)
                    elif binding is not None:
                        binding.invalidate()
                    session.current_tool = ""
                    raise RuntimeError("Werkzeugantwort konnte nicht konsumiert werden") from None
                if traced_outcome is not None:
                    # This confirms consumption, never semantic task acceptance.
                    if not acknowledge_normal_tool_result(binding, traced_outcome):
                        binding.invalidate()
                        session.current_tool = ""
                        return FailedAnswer("Konsum der Werkzeugantwort ist nicht bestätigt")
                if binding is not None:
                    actions = getattr(session, "worker_task_actions", None)
                    if actions is not None and t_name == "task_manage":
                        actions.confirm(binding)
                    completed = binding.completed_task_ids
                    with self._task_completion_receipts_lock:
                        receipts = self._task_completion_receipts.setdefault(str(session.chat_id), [])
                        for task_id in completed:
                            if task_id not in receipts:
                                receipts.append(task_id)
                    if binding.closed:
                        # The task is already released at the authority. Return
                        # its ACK receipt without further inference or mutations.
                        session.current_tool = ""
                        return str(t_result)
                else:
                    self._record_task_completion_receipt(
                        getattr(session, "chat_id", ""), t_name, t_args, str(t_result)
                    )

            # Ein Zähler pro Werkzeugrunde, nach allen Antworten der Runde.
            # Keine Tool-Ergebnisse verändern: deren exakter Text ist ein Receipt.
            msgs.append({"role": "user", "content": tool_round_counter(round_num, max_rounds)})

            if background_task and ("openrouter" in getattr(selected_backend, "base_url", "").lower() or "openrouter" in str(selected_model).lower()):
                await asyncio.sleep(1.0)

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
                    final_res, selected_backend, selected_model = await self._chat_with_configured_fallbacks(
                        session, selected_backend, selected_model,
                        msgs, tools=None, think=final_think,
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

            if max_rounds > 0 and max_rounds - round_num <= tool_round_warning_threshold(max_rounds):
                rest = max_rounds - round_num
                nudge = (
                    f"[SYSTEM-HINWEIS: Werkzeugrunde {round_num}/{max_rounds} - Noch {rest} Runde(n) verbleibend!]\n"
                    "Deine Werkzeugrunden sind fast aufgebraucht! "
                    "Wenn du die Ursache kennst: Gehe JETZT direkt zur Code-Änderung (edit_file / write_file) über. "
                    "Wenn du die Aufgabe in dieser Session nicht mehr fertigstellen kannst: "
                    + SELF_DECOMPOSE_INSTRUCTION
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
            res, selected_backend, selected_model = await self._chat_with_configured_fallbacks(
                session, selected_backend, selected_model,
                frage, tools=None,
                think=session.think if selected_model == "glm-5.3:cloud" else False,
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
            result, selected_backend, selected_model = await self._chat_with_configured_fallbacks(
                session, selected_backend, selected_model,
                prompt,
                think=session.think if selected_model == "glm-5.3:cloud" else False,
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
