#!/usr/bin/env python3
"""
BACH Telegram Chat Runtime
============================

Interaktiver Telegram-Bot mit pluggbarem LLM-Backend.
Nutzt BACH Chat-Runtime für Tool-Use, Sicherheit, Kontext.

Kann mit jedem Backend betrieben werden:
  - Ollama (lokal)
  - OpenAI / OpenAI-kompatibel
  - Anthropic Claude
  - Claude Code CLI / Codex CLI

Konfiguration:
  ~/.config/bach/telegram_chat.json oder Umgebungsvariablen.

Start:
  python -m hub._services.chat.telegram_chat
  # oder direkt:
  python telegram_chat.py
"""
import asyncio
import functools
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import json
import logging
import os
import socket
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("bach.telegram_chat")

# BACH system path: resolve from this file's location (system/hub/_services/chat/)
_here = Path(__file__).resolve()
_system_dir = str(_here.parents[3])
_root_dir = str(_here.parents[4])
for _p in (_system_dir, _root_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from telegram import Update
    from telegram.ext import (Application, CommandHandler, MessageHandler,
                              filters, ContextTypes)
except ImportError as exc:
    # T-20260927-232943082: ein Bibliotheksmodul darf den Prozess nicht per
    # sys.exit() beenden -- das riss frueher jeden Importeur mit (z.B.
    # pytest beim Sammeln von Testmodulen, INTERNALERROR statt Testfehler).
    raise ImportError(
        "python-telegram-bot nicht installiert: pip install python-telegram-bot"
    ) from exc

try:
    import httpx
except ImportError as exc:
    raise ImportError("httpx nicht installiert: pip install httpx") from exc

# BACH imports
from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
try:
    import bach_api
    _memory = bach_api.memory
    _injector = bach_api.injector
    _injector.set_mode("api")
    _bach_app = bach_api.get_app()
    HAS_BACH = True
    print("BACH API geladen")
except Exception as e:
    HAS_BACH = False
    _bach_app = None
    _memory = None
    _injector = None
    print(f"BACH API nicht verfügbar: {e}")

# Chat Runtime + Backend
from hub._services.llm.model_backend import (
    CLIBackend,
    OllamaBackend,
    backend_identifier,
    create_backend,
)
from hub._services.chat.chat_runtime import (
    ChatRuntime,
    ComputeLocked,
    FailedAnswer,
    SuccessfulAnswer,
)
from hub._services.chat.session_store import SQLiteChatSessionStore
from hub._services.chat.worker_handoff import WorkerHandoff
from hub._services.chat.worker_task_actions import WorkerTaskActions
from hub._services.chat.control_auth import (
    get_control_api_token,
    is_control_api_authorized,
)
from hub._services.agents_heart import (
    AssignmentDenied,
    begin_assignment,
    finish_assignment,
)
from hub._services.chat.slots_config import (
    bump_pause_counter,
    get_slot_pause_info,
    DEFAULT_CORE_SLOTS,
    add_worker,
    change_core_prompt,
    core_prompt_snapshot,
    get_activity_history,
    get_prompt_templates,
    get_slot,
    get_always_on_execution_slot,
    get_worker_slot,
    list_workers,
    load_slots_config,
    reconcile_workers,
    record_activity,
    remove_worker,
    reset_prompt_template,
    update_prompt_template,
    update_slot,
    worker_configuration_snapshot,
    change_worker_configuration,
    _worker_configuration,
)

# Compute Lock (optional — graceful if not available)
try:
    from hub.compute_lock import (
        DEFAULT_CHECK_SCRIPT, DEFAULT_LOCK_PATH,
        check_compute_active, pause_compute_jobs, resume_compute_jobs,
        start_resume_monitor, recover_paused_jobs, format_status_message,
        write_session_flag, delete_session_flag,
        set_inferenz_active, get_effective_keep_alive_seconds,
        get_fackel_preference, set_fackel_preference,
    )
    HAS_COMPUTE_LOCK = True
except ImportError:
    HAS_COMPUTE_LOCK = False
    DEFAULT_LOCK_PATH = "~/.memwatchdog/compute_active.lock"
    DEFAULT_CHECK_SCRIPT = ""
    def get_fackel_preference(path=None):
        return "compute"
    def set_fackel_preference(pref, path=None, quelle="unbekannt"):
        return pref

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("bach.telegram_chat")

_ACTIVE_WORKER_THREADS: Dict[str, threading.Thread] = {}

_WORKER_CONTROL_LOCK = threading.RLock()


class _WorkerAdmission:
    """Handle for the actual synchronous admission, before any worker launch."""
    def __init__(self):
        self.caller = threading.current_thread()
        self.finished = threading.Event()

    def is_alive(self):
        return not self.finished.is_set() and self.caller.is_alive()

    def join(self, timeout=None):
        self.finished.wait(timeout)


@dataclass
class _WorkerControl:
    """Generation-bound cooperative cancellation state for one worker run."""

    worker_id: str
    generation: str = field(default_factory=lambda: uuid.uuid4().hex)
    stop_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    thread: Any = None
    start_request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    admission_handle: Any = None
    admission_pending: bool = False
    launch_attempted: bool = False
    worker_thread_started: bool = False
    start_error: Optional[str] = None
    admitted_worker: Optional[Dict[str, Any]] = None
    slot_policy_reader: Any = None
    stop_status: Optional[str] = None
    stop_activity: str = "Manuell gestoppt"
    requested_at: Optional[str] = None
    receipt: Optional[Dict[str, Any]] = None
    task_binding: Any = None
    sequence_creator_authority: Any = None
    creator_delegation: Any = None
    deferred_task_versions: dict[int, str] = field(default_factory=dict)
    completed_task_ids: list[int] = field(default_factory=list)
    completed_task_results: dict[int, dict] = field(default_factory=dict)
    reviewed_task_ids: list[int] = field(default_factory=list)
    lease_supervisor: Any = None
    supports_step_actions: bool = False
    handoff: WorkerHandoff = field(init=False)
    task_actions: WorkerTaskActions = field(init=False)

    def __post_init__(self):
        self.handoff = WorkerHandoff(self.worker_id, self.generation)
        self.task_actions = WorkerTaskActions(self.worker_id, self.generation)


# A blocking runtime cannot be killed safely from a control/API thread. The
# endpoint waits only this long for cooperative completion and otherwise
# reports a pending revocation instead of claiming success.
_WORKER_STOP_WAIT_SECONDS = 2.0
_WORKER_CONTROLS: Dict[str, _WorkerControl] = {}
_WORKER_EXECUTIONS: Dict[str, _WorkerControl] = {}
_WORKER_SERVICE_INSTANCE = uuid.uuid4().hex


def worker_execution_receipt(worker_id: str, start_request_id: str | None = None) -> dict:
    """Observe this service's exact start without inferring completion from text."""
    with _WORKER_CONTROL_LOCK:
        control = _WORKER_EXECUTIONS.get(worker_id)
        if start_request_id is not None and (
                control is None or control.start_request_id != start_request_id):
            raise ValueError("Start-Request ist nicht bestätigt")
        if control is None:
            current, thread = _active_worker_control(worker_id)
            return {"schema": "bach.worker-execution.v1", "service_instance": _WORKER_SERVICE_INSTANCE,
                "worker_id": worker_id, "start_request_id": None, "generation": None,
                "state": "unconfirmed" if current is not None or _thread_is_alive(thread) else "idle",
                "terminal": False, "worker_thread_started": None,
                "worker_status": None, "completed_task_ids": [], "reviewed_task_ids": [], "error_code": None}
        return _control_execution_receipt(control)


def _control_execution_receipt(control: _WorkerControl) -> dict:
    """Observe this captured generation even after a later start replaced it."""
    with _WORKER_CONTROL_LOCK:
        worker_id = control.worker_id
        alive = _thread_is_alive(control.thread)
        terminal = control.done_event.is_set() and not alive
        if terminal:
            state = "terminal"
        elif control.done_event.is_set():
            state = "finishing"
        elif control.admission_pending:
            state = ("stopping" if control.stop_event.is_set() else "starting") if alive else "unconfirmed"
        elif not alive or not control.worker_thread_started:
            state = "unconfirmed"
        else:
            state = "stopping" if control.stop_event.is_set() else "running"
        try:
            status = (_execution_worker_slot(worker_id) or {}).get("status")
        except Exception:
            status = None
        binding = control.task_binding
        return {"schema": "bach.worker-execution.v1", "service_instance": _WORKER_SERVICE_INSTANCE,
            "worker_id": worker_id, "start_request_id": control.start_request_id,
            "generation": control.generation, "state": state, "terminal": terminal,
            "worker_thread_started": (None if control.launch_attempted and not control.worker_thread_started
                                      and not terminal else control.worker_thread_started),
            "worker_status": status, "error_code": control.start_error,
            "completed_task_ids": sorted(set(control.completed_task_ids) | (set(binding.completed_task_ids) if binding is not None else set())),
            "reviewed_task_ids": sorted(set(control.reviewed_task_ids) | (set(binding.reviewed_task_ids) if binding is not None else set()))}


def _retain_worker_task_receipts(control: _WorkerControl) -> None:
    """Keep canonical Release ACKs before replacing the current task binding."""
    binding = control.task_binding
    if binding is None:
        return
    completed = tuple(binding.completed_task_ids)
    reviewed = tuple(binding.reviewed_task_ids)
    result = getattr(binding, "completion_result", None)
    with _WORKER_CONTROL_LOCK:
        control.completed_task_ids = sorted(set(control.completed_task_ids) | set(completed))
        control.reviewed_task_ids = sorted(set(control.reviewed_task_ids) | set(reviewed))
        if (isinstance(result, dict) and result.get("generation") == control.generation
                and result.get("task_id") in completed):
            control.completed_task_results[result["task_id"]] = dict(result)


def worker_execution_result(worker_id, request_id, generation, task_id):
    """Private native-chain handoff after ACK and physical thread completion."""
    with _WORKER_CONTROL_LOCK:
        control = _WORKER_EXECUTIONS.get(worker_id)
        if (control is None or control.start_request_id != request_id
                or control.generation != generation or not control.done_event.is_set()
                or _thread_is_alive(control.thread)):
            raise ValueError("Physisches Laufende dieser Generation nicht bestätigt")
        result = control.completed_task_results.get(task_id)
        if task_id not in control.completed_task_ids or not isinstance(result, dict):
            raise ValueError("Bestätigter Taskabschluss mit fachlichem Ergebnis fehlt")
        return dict(result)


def _native_task_client():
    """Production workers require a declared canonical authority, not a projection."""
    from hub.rheingold import get_lead_config
    from hub._services.task_lease_client import TaskLeaseClient, LeaseProtocolError
    from hub._services.chat.bach_tools import _current_runtime_db
    config = get_lead_config()
    mode = config.get("mode")
    if mode not in {"worker", "lead"} and not (
            mode == "isolated" and os.environ.get("BACH_MODE") == "isolated"):
        raise LeaseProtocolError("Kanonische Task-Autorität ist für diesen Worker nicht konfiguriert")
    client = TaskLeaseClient(db_path=_current_runtime_db())
    if client.mode != ("remote" if mode == "worker" else "local"):
        raise LeaseProtocolError("Task-Autorität wurde während der Auswahl geändert")
    return client


def _execution_worker_slot(worker_id: str) -> dict:
    if worker_id == "buddha_always_on":
        return get_always_on_execution_slot()
    worker = get_worker_slot(worker_id)
    if worker:
        return worker
    # Dynamic IDs are already resolved by their strict canonical registry.
    # Only an actual system-slot ID needs a second system-slot lookup.
    if worker_id not in load_slots_config().get("slots", {}):
        return {}
    from hub._services.chat.slots_config import get_system_slot
    system_slot = get_system_slot(worker_id)
    if system_slot and system_slot.get("execution_kind") == "worker":
        worker_type = system_slot.get("type", "continuous")
        if worker_type not in {"once", "continuous"}:
            raise ValueError("System-Worker-Laufbegrenzung ist ungültig")
        return {**system_slot, "type": worker_type, "system": True}
    return {}


def _execution_worker_configuration(slot: dict):
    configuration = _worker_configuration(slot)
    if slot.get("id") == "buddha_always_on" or slot.get("system"):
        configuration = {**configuration, "execution": {key: slot.get(key) for key in
            ("enabled", "category", "pickup_filter", "workdir", "type", "require_assigned_slot",
             "custom_system_prompt", "custom_role_prompt", "role_id", "sub_mode",
              "allowed_tools", "skill_refs", "blueprint_id", "blueprint_version")}}
    return configuration


def _execution_slot_reader(slot: dict):
    worker_id = slot["id"]
    if worker_id != "buddha_always_on" and not slot.get("system"):
        return lambda: _execution_worker_slot(worker_id)

    def policy(current):
        # Task ID is owned controller metadata; actual mutations are fenced
        # by the separate private binding, not by this policy snapshot.
        return json.dumps(_execution_worker_configuration({**current, "task_id": None}),
                          sort_keys=True, ensure_ascii=False)

    admitted = policy(slot)
    def read():
        current = _execution_worker_slot(worker_id)
        if policy(current) != admitted:
            raise RuntimeError("Worker-Konfiguration wurde seit dem Start geändert; neuer Start erforderlich")
        from hub._services.skill_source_service import load_skill_instructions
        load_skill_instructions(current.get("skill_refs", []))
        return current
    return read


def _acquire_worker_task(control, slot, physical_worker_id):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    def is_current():
        # One identity read also works from the heartbeat thread. Taking the
        # controller lock here would invert lock order with stop/cleanup.
        return (_WORKER_CONTROLS.get(control.worker_id) is control
                and not control.done_event.is_set())
    host = socket.gethostname()
    client = _native_task_client()
    if control.sequence_creator_authority is not None:
        if client.mode != "local":
            raise RuntimeError("Private Sequenzzulassung benötigt den lokalen TaskDB-Lead")
        with _WORKER_CONTROL_LOCK:
            if not is_current() or control.stop_event.is_set():
                raise RuntimeError("Sequenz-Workerlauf nicht mehr aktuell")
            if control.creator_delegation is None:
                control.creator_delegation = control.sequence_creator_authority.bind(
                    task_id=slot.get("task_id"), slot_id=control.worker_id,
                    start_request_id=control.start_request_id, generation=control.generation,
                    worker_id=f"{physical_worker_id}@{host}", host=host)
    return WorkerLeaseBinding.acquire_next(
        client, slot, worker_id=f"{physical_worker_id}@{host}", host=host,
        generation=control.generation, is_current=is_current, stop_event=control.stop_event,
        policy_guard=_execution_slot_reader(slot) if slot.get("id") == "buddha_always_on" or slot.get("system") else None,
        _creator_delegation=control.creator_delegation,
        deferred_versions=control.deferred_task_versions,
    )


def _bound_worker_prompt(binding, prompt):
    snapshot = binding.task_snapshot()
    fields = ("id", "title", "description", "category", "priority", "depends_on",
              "assigned_to", "required_model", "assigned_slot", "task_version")
    content = {key: snapshot[key] for key in fields if key in snapshot}
    return (f"{prompt}\n\nAktuell übernommener Auftrag: Task #{binding.task_id}. "
            "Bearbeite ausschließlich diesen Auftrag. Ein Abschluss zählt erst nach der Werkzeugbestätigung.\n"
            + json.dumps(content, ensure_ascii=False))


def _request_worker_handoff(worker_id: str, generation: str) -> Dict[str, Any]:
    with _WORKER_CONTROL_LOCK:
        control = _WORKER_CONTROLS.get(worker_id)
        slot = _execution_worker_slot(worker_id)
        if (control is None or not _thread_is_alive(control.thread) or control.stop_event.is_set()
                or control.admission_pending
                or not slot or slot.get("enabled", True) is not True or slot.get("status") != "running"):
            raise ValueError("Worker ist nicht in einem aktiven Lauf")
        if slot.get("expires_at"):
            expiry = datetime.fromisoformat(slot["expires_at"])
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise ValueError("Worker-Lease ist abgelaufen")
        if not control.supports_step_actions:
            raise ValueError("Dieses Backend unterstützt keine verifizierte Kontextübergabe im laufenden Block")
        return control.handoff.request(generation)


def _request_worker_decomposition(worker_id, generation, task_id, task_version):
    with _WORKER_CONTROL_LOCK:
        control = _WORKER_CONTROLS.get(worker_id)
        slot = _execution_worker_slot(worker_id)
        if (control is None or not _thread_is_alive(control.thread) or control.stop_event.is_set()
                or control.admission_pending
                or not slot or slot.get("enabled", True) is not True or slot.get("status") != "running"):
            raise ValueError("Worker ist nicht in einem aktiven Lauf")
        if slot.get("allow_tools", True) is not True or slot.get("max_tool_rounds") == 0:
            raise ValueError("Zerlegung benötigt aktivierte Task-Werkzeuge")
        if slot.get("expires_at"):
            expiry = datetime.fromisoformat(slot["expires_at"])
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise ValueError("Worker-Lease ist abgelaufen")
        if not control.supports_step_actions:
            raise ValueError("Dieses Backend unterstützt keine verifizierte Zerlegungsanfrage im laufenden Block")
        return control.task_actions.request(generation, task_id, task_version, control.task_binding)


def _worker_handoff_snapshot(worker: Dict[str, Any]) -> Dict[str, Any]:
    worker = dict(worker)
    worker.pop("generation", None)
    worker.pop("task_action_binding", None)
    with _WORKER_CONTROL_LOCK:
        retained = _WORKER_EXECUTIONS.get(worker.get("id"))
        if retained is not None:
            execution = worker_execution_receipt(retained.worker_id, retained.start_request_id)
            worker["execution"] = execution
            if not execution["terminal"] and execution["state"] in {"starting", "stopping", "finishing", "unconfirmed"}:
                worker["status"] = execution["state"]
        control = _WORKER_CONTROLS.get(worker.get("id"))
        if control is not None and control.admission_pending:
            worker["status"] = "stopping" if control.stop_event.is_set() else "starting"
            worker["execution"] = worker_execution_receipt(control.worker_id, control.start_request_id)
            return worker
        if control and _thread_is_alive(control.thread) and not control.stop_event.is_set():
            worker["generation"] = control.generation
            worker["action_capabilities"] = {
                "handoff": control.supports_step_actions,
                "decompose": control.supports_step_actions,
            }
            worker["handoff_receipt"] = control.handoff.snapshot()
            worker["task_action_receipt"] = control.task_actions.snapshot()
            if (control.supports_step_actions
                    and control.task_binding is not None and not control.task_binding.closed
                    and worker.get("enabled", True) is True
                    and worker.get("allow_tools", True) is True and worker.get("max_tool_rounds") != 0):
                try:
                    control.task_binding.assert_active()
                    worker["task_action_binding"] = {
                        "task_id": control.task_binding.task_id,
                        "task_version": control.task_binding.task_snapshot()["task_version"],
                    }
                except Exception:
                    pass
    return worker


def _worker_execution_snapshots() -> list[dict]:
    active = _active_worker_ids()
    workers = list_workers(include_expired=True, active_worker_ids=active)
    from hub._services.chat.slots_config import core_system_agents_snapshot
    try:
        system_agents = core_system_agents_snapshot()["agents"]
    except (OSError, ValueError, TypeError):
        system_agents = []
    for agent in system_agents:
        if agent["execution_kind"] == "worker":
            workers.append({**_execution_worker_slot(agent["id"]),
                            "system": True, "deletable": agent["deletable"]})
    return [_worker_handoff_snapshot(worker) for worker in workers]


def _system_slots_snapshot() -> dict:
    """Configuration plus live controller/turn evidence; no provider is started."""
    from hub._services.chat.slots_config import core_system_agents_snapshot, system_slot_chat_id
    # Capture the file revision and RAM admissions together. A snapshot taken
    # before admission has an obsolete CAS token; one taken afterwards must
    # contain that admission, including the physical thread's cleanup tail.
    with _WORKER_CONTROL_LOCK:
        result = core_system_agents_snapshot()
        worker_states = {}
        for agent in result["agents"]:
            slot_id = agent["id"]
            control = _WORKER_CONTROLS.get(slot_id) or _WORKER_EXECUTIONS.get(slot_id)
            _, thread = _active_worker_control(slot_id)
            thread_alive = _thread_is_alive(thread)
            execution = (worker_execution_receipt(slot_id, control.start_request_id)
                         if control else worker_execution_receipt(slot_id)
                         if thread_alive else None)
            binding = getattr(control, "task_binding", None)
            task_active = (control is not None and _thread_is_alive(control.thread)
                           and binding is not None and not binding.closed)
            worker_states[slot_id] = (execution, thread_alive,
                                     binding.task_id if task_active else None)
    with _runtime_state_lock:
        sessions = list(runtime.sessions.items())
    with runtime._chat_turn_gates_lock:
        gates = dict(runtime._chat_turn_gates)
    system_ids = {agent["id"] for agent in result["agents"]}
    for agent in result["agents"]:
        slot_id = agent["id"]
        running_sessions = []
        for chat_id, session in sessions:
            mapped = (getattr(session, "system_slot_id", None) or system_slot_chat_id(chat_id))
            if mapped is None:
                if chat_id in system_ids:
                    mapped = chat_id
                elif str(chat_id).startswith("worker-"):
                    continue
                else:
                    mapped = "buddha_connector" if str(chat_id).isdigit() or str(chat_id).startswith(
                    ("tg:", "telegram", "wa:", "whatsapp", "signal:")) else "buddha_chat"
            gate = gates.get(str(chat_id))
            if mapped == slot_id and gate is not None:
                with gate.condition:
                    if gate.active_turns > 0:
                        running_sessions.append(session)
        execution, thread_alive, task_id = worker_states[slot_id]
        active_session = running_sessions[0] if running_sessions else None
        execution_state = execution["state"] if execution else None
        manual_paused = agent["status"] == "paused" and not agent["pause_info"].get("auto_paused", False)
        paused = not agent["enabled"] or agent["status"] == "paused" or agent["pause_info"]["is_paused"]
        # Process liveness protects admission and cleanup; Running describes
        # actual work. An idle continuous worker remains available (Living).
        worker_active = bool(thread_alive or execution_state in {
            "starting", "running", "stopping", "finishing"})
        running = bool(task_id is not None or running_sessions)
        if execution_state == "unconfirmed":
            if not worker_active:
                worker_active = None
            if not running:
                running = None
        agent.update({"runtime_verified": True,
                      "living": (agent["enabled"] and not paused) or worker_active is True or running is True,
                      "pause_info": {**agent["pause_info"], "is_paused": paused, "manual": manual_paused},
                      "running": running, "worker_active": worker_active,
                      "task_id": task_id, "execution": execution,
                      "current_tool": getattr(active_session, "current_tool", ""),
                      "tool_round": getattr(active_session, "tool_round", 0),
                      "runtime_reason_code": "live_controller",
                      "status": (execution_state if execution_state in {
                          "starting", "stopping", "finishing", "unconfirmed"} else
                          "running" if running else
                          "paused" if paused else "ready")})
    result["service_instance"] = _WORKER_SERVICE_INSTANCE
    return result


def _change_worker_configuration(worker_id: str, version: str, changes: Dict[str, Any]):
    with _WORKER_CONTROL_LOCK:
        control = _WORKER_CONTROLS.get(worker_id)
        if control is not None and not control.done_event.is_set():
            raise RuntimeError("worker_not_editable")
        return change_worker_configuration(worker_id, version, changes)


def _thread_is_alive(thread: Optional[threading.Thread]) -> bool:
    """Return a conservative liveness result for a registered thread."""
    if thread is None:
        return False
    probe = getattr(thread, "is_alive", None)
    if not callable(probe):
        return True
    try:
        return bool(probe())
    except Exception:
        return True


def _worker_terminal_status(worker: Dict[str, Any], requested_status: Optional[str] = None) -> str:
    if requested_status in ("paused", "idle"):
        return requested_status
    return "completed" if worker.get("type") == "once" else "idle"


def _worker_receipt(
    control: Optional[_WorkerControl],
    worker_id: str,
    *,
    confirmed: bool,
    final_status: str,
    outcome: str,
    status_persisted: bool = True,
) -> Dict[str, Any]:
    requested_at = control.requested_at if control else None
    return {
        "kind": "worker-revocation",
        "worker_id": worker_id,
        "generation": control.generation if control else None,
        "requested_at": requested_at,
        "confirmed_at": datetime.now(timezone.utc).isoformat() if confirmed else None,
        "confirmed": confirmed,
        "thread_alive": not confirmed,
        "final_status": final_status if confirmed else "stopping",
        "outcome": outcome,
        "status_persisted": status_persisted,
    }


def _worker_metadata_available(worker_id: str) -> bool:
    try:
        slot = _execution_worker_slot(worker_id)
        return isinstance(slot, dict) and slot.get("id") == worker_id
    except Exception:
        return False


def _record_worker_activity(
    control: _WorkerControl,
    activity: str,
    status: str = "ok",
    details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Record activity only while this generation still owns the worker."""
    with _WORKER_CONTROL_LOCK:
        if _WORKER_CONTROLS.get(control.worker_id) is not control or control.stop_event.is_set():
            return False
        if not _worker_metadata_available(control.worker_id):
            return False
        det = dict(details or {})
        try:
            slot = _execution_worker_slot(control.worker_id)
            if slot.get("resolved_model"):
                det.setdefault("resolved_model", slot["resolved_model"])
            if slot.get("model"):
                det.setdefault("model", slot["model"])
        except Exception:
            pass
        record_activity(control.worker_id, activity, status, det or None)
        return True


def _wait_worker_cooldown(control: _WorkerControl, event_type: str = "runs") -> bool:
    """Apply a configured run/task-count pause while keeping stop responsive."""
    worker_id = control.worker_id
    if not _worker_metadata_available(worker_id):
        return False
    if not bump_pause_counter(worker_id, event_type=event_type):
        return not control.stop_event.is_set()

    slot = _execution_worker_slot(worker_id)
    pause = get_slot_pause_info(slot)
    if not pause.get("is_paused") or pause.get("remaining_seconds", 0) <= 0:
        raise RuntimeError("Automatische Pause konnte nicht bestätigt werden")

    minutes = pause.get("pause_minutes", 0)
    if _update_worker_slot(control, {
        "status": "paused",
        "auto_paused": True,
        "current_activity": f"Automatische Pause ({minutes:g} min)",
    }) is None:
        return False
    _record_worker_activity(control, f"Automatische Pause gestartet ({minutes:g} min)", "ok")

    deadline = time.monotonic() + float(pause["remaining_seconds"])
    while not control.stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        control.stop_event.wait(min(1.0, remaining))
    if control.stop_event.is_set():
        return False

    updated = _update_worker_slot(control, {
        "status": "running",
        "auto_paused": False,
        "pause_started_at": "",
        "current_activity": "Automatische Pause beendet; nächster Lauf startet",
    })
    if updated is None:
        return False
    _record_worker_activity(control, "Automatische Pause beendet", "ok")
    return True


def _worker_pause_event_type(slot: Dict[str, Any], *, task_completed: bool) -> str:
    """Select a pause counter event without counting an unfinished handoff as a task."""
    basis = str(slot.get("pause_basis") or "runs").lower()
    if task_completed and basis == "tasks":
        return "tasks"
    return "runs"


def _worker_task_completed(slot: Dict[str, Any], completed_task_ids: Any) -> bool:
    """Match task-completion receipts to an explicitly assigned task, if any."""
    try:
        completed = {int(task_id) for task_id in completed_task_ids if int(task_id) > 0}
    except (TypeError, ValueError):
        return False
    if not completed:
        return False
    assigned_task_id = slot.get("task_id")
    if assigned_task_id in (None, "", 0, "0"):
        return True
    try:
        return int(assigned_task_id) in completed
    except (TypeError, ValueError):
        return False


def _worker_once_completion_changes(slot: Dict[str, Any], completed_task_ids: Any) -> dict:
    changes = {"status": "completed", "current_activity": "Abgeschlossen"}
    # A reusable blueprint owns its acquired task ID. A verified Done must
    # allow the next assigned task; an unfinished block keeps its continuation.
    if (slot.get("system") is True and slot.get("blueprint_id") is not None
            and _worker_task_completed(slot, completed_task_ids)):
        changes["task_id"] = None
    return changes


def _update_worker_slot(
    control: _WorkerControl,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Prevent a stale/cancelled generation from changing worker state."""
    with _WORKER_CONTROL_LOCK:
        if _WORKER_CONTROLS.get(control.worker_id) is not control or control.stop_event.is_set():
            return None
        return _persist_worker_metadata(control, updates)


def _persist_worker_metadata(control: _WorkerControl, updates: Dict[str, Any]):
    """Write only the owning generation; never repair a missing core profile."""
    with _WORKER_CONTROL_LOCK:
        current = _WORKER_CONTROLS.get(control.worker_id)
        retained = _WORKER_EXECUTIONS.get(control.worker_id)
        if ((current is not None and current is not control)
                or (retained is not None and retained is not control)
                or not _worker_metadata_available(control.worker_id)):
            return None
        return update_slot(control.worker_id, updates)


def _write_revocation_receipt(
    control: _WorkerControl,
    worker: Dict[str, Any],
    *,
    outcome: str,
) -> Dict[str, Any]:
    """Persist the terminal stop/pause state and its auditable receipt."""
    with _WORKER_CONTROL_LOCK:
        if control.receipt and control.receipt.get("confirmed"):
            return control.receipt

        final_status = control.stop_status or _worker_terminal_status(worker)
        current_control = _WORKER_CONTROLS.get(control.worker_id)
        retained = _WORKER_EXECUTIONS.get(control.worker_id)
        if ((current_control is not None and current_control is not control)
                or (retained is not None and retained is not control)):
            receipt = _worker_receipt(
                control,
                control.worker_id,
                confirmed=True,
                final_status=final_status,
                outcome=f"{outcome}-stale-generation",
                status_persisted=False,
            )
            control.receipt = receipt
            return receipt

        status_persisted = True
        try:
            changes = {"status": final_status, "current_activity": control.stop_activity}
            if final_status == "paused":
                changes.update(auto_paused=False, pause_started_at="")
            updated = _persist_worker_metadata(control, changes)
            status_persisted = updated is not None
        except Exception:
            status_persisted = False
            log.exception("Worker %s konnte Revocation-Status nicht speichern", control.worker_id)

        receipt = _worker_receipt(
            control,
            control.worker_id,
            confirmed=True,
            final_status=final_status,
            outcome=outcome,
            status_persisted=status_persisted,
        )
        control.receipt = receipt
        if _worker_metadata_available(control.worker_id):
            try:
                record_activity(control.worker_id, control.stop_activity,
                    "ok" if status_persisted else "error", {"receipt": receipt})
            except Exception:
                log.exception("Worker %s konnte Revocation-Receipt nicht protokollieren", control.worker_id)
        return receipt


def _active_worker_control(worker_id: str) -> tuple[Optional[_WorkerControl], Optional[threading.Thread]]:
    with _WORKER_CONTROL_LOCK:
        control = _WORKER_CONTROLS.get(worker_id)
        if control is None:
            retained = _WORKER_EXECUTIONS.get(worker_id)
            if retained is not None and (not retained.done_event.is_set() or _thread_is_alive(retained.thread)):
                control = retained
        thread = control.thread if control else _ACTIVE_WORKER_THREADS.get(worker_id)
        return control, thread


def _validate_worker_execution_fence(expected_execution):
    if expected_execution is not None and (
            not isinstance(expected_execution, dict)
            or set(expected_execution) != {"service_instance", "start_request_id", "generation"}
            or any(not isinstance(value, str) or len(value) != 32
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in expected_execution.values())):
        raise ValueError("Ungültige Ausführungsbindung für Stop")


def _request_worker_revocation(
    worker_id: str,
    worker: Dict[str, Any],
    *,
    requested_status: Optional[str] = None,
    activity: str = "Manuell gestoppt",
    expected_execution: Optional[Dict[str, str]] = None,
) -> tuple[bool, Dict[str, Any], Dict[str, Any], int]:
    """Fence selection/stop atomically; join only the captured physical thread."""
    _validate_worker_execution_fence(expected_execution)
    final_status = _worker_terminal_status(worker, requested_status)
    with _WORKER_CONTROL_LOCK:
        control, thread = _active_worker_control(worker_id)
        if expected_execution is not None:
            retained = _WORKER_EXECUTIONS.get(worker_id)
            if (retained is None or expected_execution["service_instance"] != _WORKER_SERVICE_INSTANCE
                    or expected_execution["start_request_id"] != retained.start_request_id
                    or expected_execution["generation"] != retained.generation):
                receipt = _worker_receipt(None, worker_id, confirmed=False, final_status=final_status,
                    outcome="execution-conflict", status_persisted=False)
                return False, worker, receipt, 409
            if _control_execution_receipt(retained)["terminal"]:
                receipt = _worker_receipt(retained, worker_id, confirmed=True, final_status=final_status,
                    outcome="already-terminal", status_persisted=False)
                receipt["execution"] = _control_execution_receipt(retained)
                return True, worker, receipt, 200
            if control is not retained:
                receipt = _worker_receipt(None, worker_id, confirmed=False, final_status=final_status,
                    outcome="execution-conflict", status_persisted=False)
                return False, worker, receipt, 409

        if control is None and _thread_is_alive(thread):
            receipt = _worker_receipt(None, worker_id, confirmed=False, final_status=final_status,
                outcome="unverifiable-live-thread", status_persisted=False)
            return False, worker, receipt, 409
        if control is None:
            receipt = _worker_receipt(None, worker_id, confirmed=True, final_status=final_status,
                outcome="no-live-thread")
            changes = {"status": final_status, "current_activity": activity}
            if final_status == "paused":
                changes.update(auto_paused=False, pause_started_at="")
            updated = update_slot(worker_id, changes)
            try:
                record_activity(worker_id, activity, "ok", {"receipt": receipt})
            except Exception:
                log.exception("Worker %s konnte Revocation-Receipt nicht protokollieren", worker_id)
            return True, updated, receipt, 200

        if not control.stop_event.is_set():
            if control.sequence_creator_authority is not None:
                # The persistent Stop flag and all unused grants share one write lock.
                # A racing acquire either commits before this Stop or sees revocation.
                control.sequence_creator_authority.revoke()
            control.stop_status = final_status
            control.stop_activity = activity
            control.requested_at = datetime.now(timezone.utc).isoformat()
            control.stop_event.set()
            control.handoff.cancel()
            control.task_actions.cancel()
        elif control.stop_status is None:
            control.stop_status = final_status

    # Never hold the controller lock while the captured worker finishes.
    if thread is not None and thread is not threading.current_thread() and _thread_is_alive(thread):
        try:
            thread.join(timeout=_WORKER_STOP_WAIT_SECONDS)
        except RuntimeError:
            log.exception("Worker %s konnte nicht auf das Ende warten", worker_id)

    with _WORKER_CONTROL_LOCK:
        thread_alive = _thread_is_alive(thread)
        if (thread_alive or control.admission_pending and not control.done_event.is_set()
                or control.launch_attempted and not control.done_event.is_set()):
            current = _WORKER_CONTROLS.get(worker_id)
            retained = _WORKER_EXECUTIONS.get(worker_id)
            owns_status = ((current is None or current is control) and (retained is None or retained is control)
                           and _worker_metadata_available(worker_id))
            receipt = _worker_receipt(control, worker_id, confirmed=False, final_status=final_status,
                outcome="revocation-pending" if owns_status else "revocation-pending-stale-generation",
                status_persisted=owns_status)
            control.receipt = receipt
            updated = worker
            if owns_status:
                updated = _persist_worker_metadata(control, {"status": "stopping",
                    "current_activity": f"Beendigung angefordert ({activity})"})
                try:
                    record_activity(worker_id, f"Beendigung angefordert ({activity})", "pending",
                                    {"receipt": receipt})
                except Exception:
                    log.exception("Worker %s konnte Pending-Receipt nicht protokollieren", worker_id)
            return False, updated, {**receipt, "execution": _control_execution_receipt(control)}, 409

        receipt = control.receipt
        if not receipt or not receipt.get("confirmed"):
            receipt = _write_revocation_receipt(control, worker, outcome="revocation-confirmed")
        try:
            updated = _execution_worker_slot(worker_id)
        except Exception:
            updated = worker
        receipt = {**receipt, "execution": _control_execution_receipt(control)}
        return bool(receipt.get("confirmed") and receipt.get("status_persisted", True)), updated, receipt, 200


def _active_worker_ids() -> set[str]:
    """Return set of currently running worker IDs, pruning dead threads."""
    dead: list[tuple[str, threading.Thread]] = []
    active = set()
    with _WORKER_CONTROL_LOCK:
        items = list(_ACTIVE_WORKER_THREADS.items())
        retained = list(_WORKER_EXECUTIONS.items())
    for wid, th in items:
        if _thread_is_alive(th):
            active.add(wid)
        else:
            dead.append((wid, th))
    with _WORKER_CONTROL_LOCK:
        for wid, th in dead:
            if _ACTIVE_WORKER_THREADS.get(wid) is th:
                _ACTIVE_WORKER_THREADS.pop(wid, None)
    for wid, control in retained:
        if not control.done_event.is_set() or _thread_is_alive(control.thread):
            active.add(wid)
    return active


# --- Konfiguration ---

def load_config() -> dict:
    config_path = os.path.expanduser("~/.config/bach/telegram_chat.json")
    config = {}

    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    config.setdefault("bot_token", "")
    config.setdefault("owner_id", "")
    config.setdefault("backend", {
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "default_model": "qwen3.8:27b-mlx",
    })

    if not config["bot_token"]:
        config["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not config["bot_token"]:
        tf = os.path.expanduser("~/.credentials/telegram_bot_token")
        if os.path.exists(tf):
            config["bot_token"] = open(tf, encoding="utf-8").read().strip()

    if not config["owner_id"]:
        config["owner_id"] = os.environ.get("TELEGRAM_OWNER_ID", "")
    if not config["owner_id"]:
        of = os.path.expanduser("~/.credentials/telegram_owner_id")
        if os.path.exists(of):
            config["owner_id"] = open(of, encoding="utf-8").read().strip()

    env_model = os.environ.get("OLLAMA_MODEL")
    if env_model:
        config["backend"]["default_model"] = env_model
    env_url = os.environ.get("OLLAMA_URL")
    if env_url:
        config["backend"]["base_url"] = env_url

    # Compute Lock config (default: disabled for users without memwatchdog)
    config.setdefault("compute_lock", {
        "enabled": False,
        "lock_path": DEFAULT_LOCK_PATH,
        "check_script": DEFAULT_CHECK_SCRIPT,
        "pause_method": "sigstop",
    })

    return config


CONFIG = load_config()
BOT_TOKEN = CONFIG["bot_token"]
OWNER_ID = CONFIG["owner_id"]

if not OWNER_ID:
    logging.getLogger("bach.telegram_chat").warning(
        "TELEGRAM OWNER_ID IST NICHT GESETZT - der Bot lehnt fail-closed "
        "JEDE Chat-Nachricht ab, bis owner_id in "
        "~/.config/bach/telegram_chat.json, TELEGRAM_OWNER_ID oder "
        "~/.credentials/telegram_owner_id gesetzt ist (eine leere OWNER_ID "
        "bedeutete vorher 'jeder darf')."
    )

# Backend + Runtime initialisieren
backend = create_backend(CONFIG["backend"])

try:
    from hub.bach_paths import DATA_DIR
    system_file = str(DATA_DIR / "system_prompt_buddha.txt")
except Exception:
    system_file = os.path.join(os.environ.get("PYTHONPATH", "."), "data", "system_prompt_buddha.txt")
if os.path.exists(system_file):
    system_prompt = open(system_file, encoding="utf-8").read().strip()
else:
    system_prompt = "Du bist ein lokaler BACH Chat-Assistent. Antworte auf Deutsch, präzise und klar."


session_store = None
try:
    from hub.bach_paths import BACH_DB
    if BACH_DB.exists():
        session_store = SQLiteChatSessionStore(BACH_DB)
        log.info("Chat-SessionStore an %s gebunden", BACH_DB)
except Exception as e:
    log.warning("Chat-SessionStore konnte nicht initialisiert werden: %s", e)

def _native_agent_operations(args, *, mode, allowed_tools):
    from hub.rheingold import get_lead_config
    from hub._services.agent_manage_service import AgentManager, verified_local_agent_model
    from hub._services.chat.bach_tools import _current_runtime_db
    if get_lead_config().get("mode") != "lead":
        raise RuntimeError("Agentenverwaltung benötigt den kanonischen Lead-Controller")
    def local_provider(slot):
        selected, model = _snapshot_chat_backend(slot["id"], worker_slot=slot, read_only=True)
        return verified_local_agent_model(selected, model)
    manager = AgentManager(db_path=_current_runtime_db(),
        execution_receipt=worker_execution_receipt, start_worker=start_worker_execution,
        local_provider=local_provider)
    return manager(args, mode=mode, allowed_tools=allowed_tools)


runtime = ChatRuntime(
    backend=backend,
    system_prompt=system_prompt,
    bach_app=_bach_app if HAS_BACH else None,
    memory_fn=_memory if HAS_BACH else None,
    injector=_injector if HAS_BACH else None,
    session_store=session_store,
    agent_operations=_native_agent_operations,
)

_global_defaults = {
    "mode": "safe",
    "think": True,
    "model": "",
    "max_tool_rounds": 12,
}
_runtime_state_lock = threading.RLock()


class WorkerBindingError(LookupError):
    """Raised when a worker dispatch cannot be bound to a registered ID."""


_LEGACY_WORKER_BINDING: ContextVar[Optional[str]] = ContextVar(
    "legacy_worker_binding",
    default=None,
)


@contextmanager
def legacy_worker_binding(chat_id: str):
    """Explicitly authorize the standalone ``worker.py`` session contract.

    ``worker.py`` creates IDs in the ``worker-<category>-<task-id>`` form and
    wraps each ``get_session``/``process`` call with this context. API and
    Control dispatches never enter it, so unknown worker IDs stay fail-closed.
    """
    normalized = str(chat_id or "")
    if not normalized.startswith("worker-") or normalized == "worker-":
        raise ValueError("Legacy-Worker-Bindung erwartet eine worker-* ID")
    token = _LEGACY_WORKER_BINDING.set(normalized)
    try:
        yield
    finally:
        _LEGACY_WORKER_BINDING.reset(token)


def _legacy_worker_binding_active(chat_id: str) -> bool:
    return _LEGACY_WORKER_BINDING.get() == str(chat_id or "")


def _is_strict_worker_id(chat_id: str) -> bool:
    normalized = str(chat_id or "")
    return normalized.startswith("worker-") and normalized != "worker-always-on"

# Pending actions for compute lock confirmations (keyed by chat_id)
# Format: {chat_id: {"kind": "compute_pause_for_ollama", "status": dict,
#                     "text": str, "timestamp": float}}
_pending_actions: dict = {}
_PENDING_TTL = 120  # seconds before a pending action expires

_orig_get_session = runtime.get_session

def _patched_get_session(chat_id: str):
    with _runtime_state_lock:
        session = _orig_get_session(chat_id)
        normalized = str(chat_id or "")
        if (getattr(session, "require_task_binding", False)
                and _WORKER_CONTROLS.get(normalized) is not None):
            # Keep the current controller's policy reader through process().
            return session
        try:
            worker_slot = _execution_worker_slot(normalized)
        except Exception:
            # An unreadable/ambiguous registry must not turn a restricted
            # Telegram chat ID into an ordinary tool-capable session.
            session.allow_tools = False
            session.worker_slot_reader = lambda: _execution_worker_slot(normalized)
            return session
        if worker_slot:
            session.allow_tools = worker_slot.get("allow_tools", True) is True
            session.worker_slot_reader = _execution_slot_reader(worker_slot)
            try:
                _apply_slot_to_session(chat_id, session, slot=worker_slot)
            except Exception as exc:
                session.allow_tools = False
                session.worker_slot_reader = lambda _error=exc: (_ for _ in ()).throw(_error)
            return session
        if session.worker_slot_reader is not None:
            # A formerly bound worker disappeared. Keep its live reader so
            # ChatRuntime reports an error instead of reopening tools.
            session.allow_tools = False
            return session
        if len(session.messages) == 0:
            if _global_defaults.get("mode"):
                session.mode = _global_defaults["mode"]
            if _global_defaults.get("model"):
                session.model = _global_defaults["model"]
            session.think = _global_defaults.get("think", True)
            if normalized.isdigit() or normalized.startswith((
                "idle", "worker-", "tg:", "telegram", "wa:", "whatsapp", "signal:"
            )):
                try:
                    _apply_slot_to_session(chat_id, session)
                except Exception as e:
                    if _is_strict_worker_id(normalized) and not _legacy_worker_binding_active(normalized):
                        raise
                    log.debug("Konnte Slot nicht auf Session anwenden: %s", e)
        return session

runtime.get_session = _patched_get_session


# --- Telegram-Handler ---

WELCOME = (
    "Hallo! Ich bin dein BACH Chat-Assistent.\n"
    f"Backend: {CONFIG['backend'].get('type', 'ollama')} | "
    f"Modell: {backend.get_default_model()}\n\n"
    "Modi & Modelle:\n"
    "  /mode [safe|full] — Sicherheitsmodus\n"
    "  /think — Denkmodus an (gründlich)\n"
    "  /nothink — Denkmodus aus (schnell)\n"
    "  /model <name> — Modell wechseln\n"
    "  /backend [ollama|claude|openai] — Backend wechseln\n"
    "  /maxrounds [0|5|10|20] — Max Tool-Runden (0=unbegrenzt)\n"
    "  /settings — Alle Einstellungen\n\n"
    "Chat:\n"
    "  /clear — Konversation zurücksetzen\n\n"
    + ("BACH Memory:\n"
       "  /remember <text> — Merken\n"
       "  /recall <suche> — Suchen\n"
       "  /facts — Gespeicherte Fakten\n\n"
       "BACH System:\n"
       "  /bach <befehl> — BACH-Befehl\n"
       "  /task <text> — Aufgabe anlegen\n"
       "  /tasks — Offene Aufgaben\n"
       "  /status — System-Status\n\n"
       if HAS_BACH else "")
    + "Sicherheit: Safe-Modus (Standard) = Dateiarbeit ohne Shell\n"
    "  /mode full bestätigt = zusätzlich Shell und freies Schreiben"
)


def _owner_check(update: Update) -> bool:
    """Fail-closed: eine leere/fehlende OWNER_ID heisst "niemanden
    hereinlassen", nicht "jeden hereinlassen". Vorher (Befund C) war eine
    leere OWNER_ID ein offener Bot fuer jeden Telegram-Nutzer - siehe die
    laute Warnung beim Modulstart weiter unten."""
    if not OWNER_ID:
        return False
    return str(update.effective_chat.id) == OWNER_ID


def _require_owner(handler_fn):
    """Wrappt einen Telegram-Handler mit _owner_check - zentral an der
    Registrierung (siehe main()), nicht einzeln in jeder Callback-Funktion.

    Befund C zeigte: von 19 registrierten Handlern hatten nur 5 ueberhaupt
    einen eigenen _owner_check-Aufruf; die restlichen 14 (u. a. /bach, das
    direkt in die bach_command-Routung geht, sowie /task, /remember,
    /recall, /facts fuer Memory-Zugriff) liefen fuer JEDEN Chat, sobald
    OWNER_ID gesetzt war. Ein Guard pro Registrierung statt pro Funktion
    ist der kleinere, root-cause-Fix: ein neuer Handler kann diesen Schritt
    nicht mehr vergessen, weil er ohnehin durch add_handler() muss."""
    @functools.wraps(handler_fn)
    async def wrapped(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _owner_check(update):
            if update.effective_message:
                await update.effective_message.reply_text("Zugriff nur für den Owner.")
            return
        return await handler_fn(update, ctx)
    return wrapped


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    try:
        archived_id = await asyncio.to_thread(
            runtime.clear_session, chat_id, archive_reason="Telegram /clear"
        )
    except RuntimeError:
        await update.message.reply_text(
            "Konversation konnte nicht gelöscht werden. Der bisherige Verlauf bleibt erhalten."
        )
        return
    if archived_id:
        await update.message.reply_text("Konversation archiviert. Eine neue Session ist bereit.")
    else:
        await update.message.reply_text("Konversation zurückgesetzt.")


async def cmd_think(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    runtime.get_session(str(update.effective_chat.id)).think = True
    await update.message.reply_text("Denkmodus AN")


async def cmd_nothink(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    runtime.get_session(str(update.effective_chat.id)).think = False
    await update.message.reply_text("Denkmodus AUS")


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            f"Modus: {session.mode}\n\n"
            "/mode safe — Lesen und Dateien bearbeiten, keine Shell\n"
            "/mode full bestätigt — zusätzlich Shell und freies Schreiben"
        )
        return
    m = args[0].lower()
    if m == "full":
        if len(args) < 2 or args[1].lower() != "bestätigt":
            await update.message.reply_text(
                "Full-Modus erlaubt Shell-Befehle und Dateischreiben.\n"
                "Aktivieren: /mode full bestätigt"
            )
            return
        session.mode = "full"
        await update.message.reply_text("Full-Modus aktiviert.")
    elif m == "safe":
        session.mode = "safe"
        await update.message.reply_text("Safe-Modus aktiviert.")
    else:
        await update.message.reply_text("Nutze: safe oder full")


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    args = ctx.args or []
    if not args:
        try:
            models = backend.list_models()
            backend_type = type(runtime.backend).__name__
            await update.message.reply_text(
                f"Aktiv: {session.model}\n"
                f"Backend: {backend_type}\n\n"
                f"Verfügbar:\n"
                + "\n".join(f"  {m}" for m in models)
                + "\n\nWechseln: /model <name>"
            )
        except Exception as e:
            await update.message.reply_text(f"Fehler: {e}")
        return
    session.model = args[0]
    await update.message.reply_text(f"Modell: {args[0]}")


BACKEND_PRESETS = {
    "ollama": {
        "type": "ollama",
        "base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "default_model": os.environ.get("OLLAMA_MODEL", "qwen3.8:27b-mlx"),
        "method": "api",
        "description": "Lokales Ollama (Qwen, Llama, etc.)",
    },
    "ollama-cloud": {
        "type": "ollama",
        "base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "default_model": os.environ.get("OLLAMA_CLOUD_MODEL", "kimi-k3:cloud"),
        "method": "api",
        "description": "Ollama Cloud Proxies (:cloud Modelle wie Kimi, GLM)",
    },
    "lmstudio": {
        "type": "lmstudio",
        "base_url": os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1"),
        "default_model": os.environ.get("LM_STUDIO_MODEL", "auto"),
        "method": "api",
        "description": "LM Studio (lokal, Port 1234)",
    },
    "hermes": {
        "type": "hermes",
        "base_url": os.environ.get("HERMES_URL", "https://openrouter.ai/api/v1"),
        "default_model": os.environ.get("HERMES_MODEL", "nousresearch/hermes-3-llama-3.1-8b"),
        "method": "api",
        "description": "Nous Hermes Agent (OpenRouter / Lokal)",
    },
    "openrouter": {
        "type": "openrouter",
        "base_url": os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1"),
        "default_model": os.environ.get("OPENROUTER_MODEL", "openrouter/free"),
        "free_only": True,
        "method": "api",
        "description": "OpenRouter (kostenloser Router und kostenlose Modelle)",
    },
    "claude": {
        "type": "claude-cli",
        "default_model": "sonnet",
        "method": "cli",
        "description": "Claude Code CLI (--continue Session)",
    },
    "claude-api": {
        "type": "claude-api",
        "default_model": "claude-sonnet-4-6",
        "method": "api",
        "description": "Anthropic API (braucht Key)",
    },
    "codex": {
        "type": "codex-cli",
        "default_model": "o4-mini",
        "method": "cli",
        "description": "Codex CLI (GPT-Modelle)",
    },
    "openai": {
        "type": "openai",
        "default_model": "gpt-4o",
        "method": "api",
        "description": "OpenAI API (braucht Key)",
    },
}


def _check_cli_available(name: str) -> str:
    import shutil
    if name == "claude":
        return "vorhanden" if shutil.which("claude") else "nicht gefunden"
    elif name == "codex":
        return "vorhanden" if shutil.which("codex") else "nicht gefunden"
    return ""


_API_KEY_SOURCES = {
    "claude-api": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "hermes": ("OPENROUTER_API_KEY", "openrouter_api_key"),
    "openrouter": ("OPENROUTER_API_KEY", "openrouter_api_key"),
}


def _load_api_key(name: str) -> str:
    source = _API_KEY_SOURCES.get(name)
    if source is None:
        return ""

    env_var, file_name = source
    configured = str(os.environ.get(env_var) or "").strip()
    if configured:
        return configured

    key_file = Path(os.path.expanduser(f"~/.credentials/{file_name}"))
    try:
        return key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _check_api_key(name: str) -> str:
    if name not in _API_KEY_SOURCES:
        return ""
    return "Key vorhanden" if _load_api_key(name) else "Key fehlt"


# Each cache entry must come from its exact requested configuration. The
# global chat backend can be a paid API and is never an Ollama alias.
_backends_pool: dict[str, Any] = {}
_backends_pool_lock = threading.Lock()


def _get_or_create_backend(backend_type: str, model: str = "") -> Any:
    backend_key = (backend_type or "ollama").lower().strip()
    cache_key = f"{backend_key}:{model}" if model else backend_key

    with _backends_pool_lock:
        if cache_key in _backends_pool:
            return _backends_pool[cache_key]
        if backend_key in _backends_pool and not model:
            return _backends_pool[backend_key]

        if backend_key in BACKEND_PRESETS:
            preset = BACKEND_PRESETS[backend_key].copy()
            if model:
                preset["default_model"] = model
            if preset["method"] == "api" and backend_key in ("claude-api", "openai", "hermes", "openrouter"):
                api_key = _load_api_key(backend_key)
                if api_key:
                    preset["api_key"] = api_key
            config = {k: v for k, v in preset.items() if k not in ("method", "description")}
        else:
            config = {"type": backend_key}
            if model:
                config["default_model"] = model

        try:
            b = create_backend(config)
            _backends_pool[cache_key] = b
            return b
        except Exception as e:
            log.warning("Konfiguriertes Backend %s konnte nicht erstellt werden", cache_key)
            raise WorkerBindingError("Konfiguriertes Backend ist nicht verfügbar; kein Anbieterwechsel") from e


def _resolve_slot_for_chat(chat_id: str) -> dict:
    try:
        cfg = load_slots_config()
    except Exception:
        cfg = {}
    slots = cfg.get("slots", {})
    str_id = str(chat_id)
    from hub._services.chat.slots_config import get_system_slot, system_slot_chat_id
    selected_id = system_slot_chat_id(str_id)
    if str_id.startswith("slot:") and selected_id is None:
        raise WorkerBindingError("Ungültige System-Steckplatz-Chat-ID")
    if selected_id or str_id in slots:
        selected = get_system_slot(selected_id or str_id)
        if not selected or selected.get("enabled", True) is not True:
            raise WorkerBindingError("Systemsteckplatz ist ausgeschaltet oder nicht verfügbar")
        return selected

    # 1. Check dynamic workers by canonical ID only. Display names are not
    # routing keys: duplicate names must remain unambiguous.
    for w in cfg.get("dynamic_workers", []):
        if w.get("id") == str_id:
            return w

    # 2. Always-On / Idle Worker
    if str_id in ("idle-worker", "worker-always-on") or str_id.startswith("idle"):
        return slots.get("buddha_always_on", DEFAULT_CORE_SLOTS["buddha_always_on"])

    # Unknown worker IDs must never inherit the always-on slot in API/Control
    # dispatch. The only permitted fallback is the explicit worker.py
    # context above, bound to this exact ID.
    if str_id.startswith("worker-"):
        if _legacy_worker_binding_active(str_id):
            return slots.get("buddha_always_on", DEFAULT_CORE_SLOTS["buddha_always_on"])
        raise WorkerBindingError(f"Worker-ID nicht registriert: {str_id}")

    # 3. Messaging Connectors (Telegram, WhatsApp, Signal)
    if str_id.isdigit() or any(str_id.startswith(p) for p in ("tg:", "telegram", "wa:", "whatsapp", "signal:")):
        conn_slot = slots.get("buddha_connector", DEFAULT_CORE_SLOTS["buddha_connector"])
        if (str_id.isdigit() or str_id.startswith("tg:") or str_id == "telegram") and "providers" in conn_slot:
            tg_cfg = conn_slot.get("providers", {}).get("telegram")
            if tg_cfg:
                combined = dict(conn_slot)
                combined.update(tg_cfg)
                return combined
        return conn_slot

    # 4. Default to Buddha Chat (Interactive)
    return slots.get("buddha_chat", DEFAULT_CORE_SLOTS["buddha_chat"])


def _registered_worker_slot(worker_id: str) -> Optional[dict]:
    """Return a dynamic worker bound by exact ID, never a core slot/name."""
    normalized = str(worker_id or "")
    if not normalized or normalized in DEFAULT_CORE_SLOTS:
        return None
    try:
        worker = get_worker_slot(normalized)
    except Exception:
        return None
    if not isinstance(worker, dict) or worker.get("id") != normalized:
        return None
    return worker


def _apply_slot_to_session(chat_id: str, session: Any, *, slot: dict | None = None) -> tuple[Any, str]:
    slot = slot if slot is not None else _resolve_slot_for_chat(chat_id)
    if slot.get("enabled", True) is not True:
        raise WorkerBindingError("Steckplatz ist ausgeschaltet")
    slot_backend_type = slot.get("backend") or "ollama"
    slot_model = slot.get("model") or ""

    target_backend = _get_or_create_backend(slot_backend_type, slot_model)
    session.backend = target_backend
    if slot_model:
        session.model = slot_model
    elif not getattr(session, "model", ""):
        session.model = getattr(target_backend, "default_model", "")

    if "mode" in slot:
        session.mode = slot["mode"]
    if "think" in slot:
        session.think = bool(slot["think"])
    if "allow_tools" in slot:
        # Apply the capability before parsing any other numeric settings.
        session.allow_tools = slot["allow_tools"] is True
    session.allowed_tools = slot.get("allowed_tools")
    if "max_tool_rounds" in slot:
        session.max_tool_rounds = int(slot["max_tool_rounds"])
    from hub._services.chat.slots_config import compose_worker_prompt, get_system_slot, system_slot_chat_id
    system_id = system_slot_chat_id(chat_id)
    if system_id or slot.get("id") in DEFAULT_CORE_SLOTS or slot.get("system"):
        session.custom_system_prompt = compose_worker_prompt(slot)
        if system_id or slot.get("id") in {"buddha_chat", "buddha_connector"}:
            session.system_slot_id = slot["id"]
            session.system_slot_reader = lambda: get_system_slot(slot["id"])
            from hub._services.chat.slots_config import CORE_EDITABLE_FIELDS
            session.system_slot_configuration = {key: slot.get(key) for key in CORE_EDITABLE_FIELDS if key != "enabled"}
    elif slot.get("system_prompt"):
        session.custom_system_prompt = slot["system_prompt"]

    return target_backend, session.model


async def cmd_backend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    current = type(runtime.backend).__name__
    current_cli = getattr(runtime.backend, "cli_name", "")

    if not args:
        lines = [f"Aktiv: {current}" + (f" ({current_cli})" if current_cli else "")]
        lines.append("")
        for name, preset in BACKEND_PRESETS.items():
            status = ""
            if preset["method"] == "cli":
                cli_name = preset["type"].replace("-cli", "")
                status = _check_cli_available(cli_name)
            elif preset["method"] == "api" and name in ("claude-api", "openai", "hermes", "openrouter"):
                status = _check_api_key(name)
            status_str = f" [{status}]" if status else ""
            lines.append(f"  {name} — {preset['description']}{status_str}")
        lines.append("")
        lines.append("Wechseln: /backend <name> [model]")
        lines.append("Beispiele:")
        lines.append("  /backend claude opus")
        lines.append("  /backend codex o4-mini")
        lines.append("  /backend ollama qwen3.8:27b-mlx")
        lines.append("  /backend lmstudio")
        lines.append("  /backend hermes")
        await update.message.reply_text("\n".join(lines))
        return

    name = args[0].lower()
    if name not in BACKEND_PRESETS:
        await update.message.reply_text(
            f"Unbekannt: {name}\nVerfügbar: {', '.join(BACKEND_PRESETS.keys())}"
        )
        return

    preset = BACKEND_PRESETS[name].copy()

    if len(args) > 1:
        preset["default_model"] = args[1]

    if preset["method"] == "api" and name in ("claude-api", "openai", "hermes", "openrouter"):
        env_var, file_name = _API_KEY_SOURCES[name]
        key_file = os.path.expanduser(f"~/.credentials/{file_name}")
        api_key = _load_api_key(name)
        if not api_key:
            await update.message.reply_text(
                f"Kein API-Key für {name}.\n"
                f"Setze {env_var} oder lege {key_file} an."
            )
            return
        preset["api_key"] = api_key

    try:
        config_for_backend = {k: v for k, v in preset.items()
                              if k not in ("method", "description")}
        new_backend = create_backend(config_for_backend)
        available, availability_status = await asyncio.to_thread(
            _checked_backend_availability,
            new_backend,
            preset["default_model"],
        )
        if not available:
            await update.message.reply_text(
                f"Backend nicht verfügbar: {availability_status}"
            )
            return

        with _runtime_state_lock:
            runtime.backend = new_backend
            session = runtime.get_session(str(update.effective_chat.id))
            session.model = preset["default_model"]
        _invalidate_backend_inventory_cache()

        method_str = "CLI-Session" if preset["method"] == "cli" else "API"
        owns_tools = getattr(new_backend, "manages_own_tools", False)
        tool_str = "CLI-eigene Tools" if owns_tools else "BACH Tool-Use"

        await update.message.reply_text(
            f"Backend: {name}\n"
            f"Modell: {preset['default_model']}\n"
            f"Methode: {method_str}\n"
            f"Tools: {tool_str}"
        )
    except Exception as e:
        await update.message.reply_text(f"Backend-Wechsel fehlgeschlagen: {e}")


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    n_msgs = len(session.messages)
    chars = sum(len(m.get("content", "")) for m in session.messages)
    mr = runtime.max_tool_rounds
    mr_label = "Tools aus" if mr == 0 else str(mr)
    tool_info = ""
    if session.current_tool:
        tool_info = f"\nAktives Tool: {session.current_tool} (Runde {session.tool_round})"
    elif session.last_tools:
        tool_info = f"\nLetzte Tools: {', '.join(session.last_tools)}"
    await update.message.reply_text(
        f"Backend: {CONFIG['backend'].get('type', 'ollama')}\n"
        f"Modus: {session.mode}\n"
        f"Denken: {'AN' if session.think else 'AUS'}\n"
        f"Modell: {session.model}\n"
        f"Max Tool-Runden: {mr_label}\n"
        f"Fackel: {get_fackel_preference().capitalize()}\n"
        f"BACH: {'Ja' if HAS_BACH else 'Nein'}\n"
        f"Kontext: {n_msgs} Nachrichten, ~{chars:,} Zeichen"
        + tool_info
    )


async def cmd_maxrounds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    if not args:
        mr = runtime.max_tool_rounds
        await update.message.reply_text(
            f"Max Tool-Runden: {'Tools aus' if mr == 0 else mr}\n\n"
            "/maxrounds 0 — Tools abschalten\n"
            "/maxrounds 5 — Max 5 Runden\n"
            "/maxrounds 10 — Max 10 Runden"
        )
        return
    try:
        val = int(args[0])
        if val < 0:
            val = 0
        runtime.max_tool_rounds = val
        _global_defaults["max_tool_rounds"] = val
        label = "Tools aus" if val == 0 else str(val)
        await update.message.reply_text(f"Max Tool-Runden: {label}")
    except ValueError:
        await update.message.reply_text("Nutzung: /maxrounds <zahl>")


# --- BACH Commands ---

async def cmd_remember(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text("Nutzung: /remember <text>")
        return
    try:
        if ":" in text and len(text.split(":")[0]) < 30:
            _memory("fact", text, "--conf=0.8", "--source=telegram")
            await update.message.reply_text(f"Fakt: {text}")
        else:
            _memory("write", text)
            await update.message.reply_text(f"Notiz: {text}")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_recall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    q = " ".join(ctx.args) if ctx.args else ""
    if not q:
        await update.message.reply_text("Nutzung: /recall <suche>")
        return
    try:
        r = _memory("search", q)
        await update.message.reply_text(str(r)[:4000] if r else "Nichts gefunden.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_facts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    try:
        r = _memory("facts")
        await update.message.reply_text(str(r)[:4000] if r else "Keine Fakten.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_bach(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Nutzung: /bach <handler> [operation] [args]\n"
            "Beispiele: /bach status, /bach task list, /bach mem facts"
        )
        return
    h = args[0]
    op = args[1] if len(args) > 1 else ""
    ex = args[2:] if len(args) > 2 else []
    try:
        ok, out = _bach_app.execute(h, op, ex)
        r = str(out)[:4000] if out else "(keine Ausgabe)"
        await update.message.reply_text(r if ok else "Fehler: " + r)
    except Exception as e:
        await update.message.reply_text(f"BACH Fehler: {e}")


async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text("Nutzung: /task <beschreibung>")
        return
    try:
        ok, out = _bach_app.execute("task", "add", [text])
        await update.message.reply_text(str(out)[:2000] if out else "Task erstellt.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    try:
        ok, out = _bach_app.execute("task", "list", [])
        await update.message.reply_text(str(out)[:4000] if out else "Keine offenen Tasks.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    parts = []
    try:
        models = backend.list_models()
        parts.append(f"Modelle: {', '.join(models)}\nAktiv: {session.model}")
    except Exception as e:
        parts.append(f"Backend: {e}")
    parts.append(f"Modus: {session.mode} | Denken: {'AN' if session.think else 'AUS'}")
    parts.append(f"Fackel: {get_fackel_preference().capitalize()}")
    if HAS_BACH:
        try:
            ok, out = _bach_app.execute("status", "", [])
            parts.append(str(out)[:1500])
        except Exception:
            parts.append("BACH: Fehler")
    await update.message.reply_text("\n\n".join(parts)[:4000])


async def cmd_fackel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return
    args = ctx.args or []
    current_pref = get_fackel_preference()
    if not args:
        status_text = "Ollama (Chat & Worker bevorzugt)" if current_pref == "ollama" else "Rechenjobs bevorzugt (Compute)"
        await update.message.reply_text(
            f"Fackel-Priorität: {status_text}\n\n"
            f"Umschalten:\n"
            f"/fackel ollama — Chat & Worker bevorzugen\n"
            f"/fackel compute — Rechenjobs bevorzugen (Standard)"
        )
        return
    pref = args[0].lower().strip()
    if pref in ("ollama", "chat", "worker"):
        set_fackel_preference("ollama", quelle="telegram")
        await update.message.reply_text("Fackel umgestellt: Ollama (Chat & Worker) bevorzugt.")
    elif pref in ("compute", "rechenjobs", "jobs"):
        set_fackel_preference("compute", quelle="telegram")
        await update.message.reply_text("Fackel umgestellt: Rechenjobs bevorzugt (Compute).")
    else:
        await update.message.reply_text("Nutze: /fackel ollama oder /fackel compute")



async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        return
    session = runtime.get_session(str(update.effective_chat.id))
    session.voice_output = not session.voice_output
    status = "AN" if session.voice_output else "AUS"
    await update.message.reply_text(f"Sprachausgabe: {status}")


async def _send_voice_reply(update, text: str):
    """Text als Sprachnachricht senden (macOS say + ffmpeg)."""
    tmp_aiff = None
    tmp_ogg = None
    try:
        import shutil
        if not shutil.which("say") or not shutil.which("ffmpeg"):
            return False

        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as aiff_file:
            tmp_aiff = aiff_file.name
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_file:
            tmp_ogg = ogg_file.name

        clean_text = text[:3000].replace('"', "'").replace("`", "'")

        proc = await asyncio.subprocess.create_subprocess_exec(
            "say", "-v", "Anna", "-o", tmp_aiff, clean_text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.wait(), timeout=30)

        proc = await asyncio.subprocess.create_subprocess_exec(
            "ffmpeg", "-y", "-i", tmp_aiff,
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
            "-application", "voip", tmp_ogg,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.wait(), timeout=15)

        if os.path.exists(tmp_ogg) and os.path.getsize(tmp_ogg) > 0:
            with open(tmp_ogg, "rb") as f:
                await update.message.reply_voice(voice=f)
            return True
    except Exception as e:
        log.error(f"TTS-Fehler: {e}")
    finally:
        for p in (tmp_aiff, tmp_ogg):
            if p and os.path.exists(p):
                os.unlink(p)
    return False


# --- Voice & Photo ---

async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    await update.effective_chat.send_action("typing")
    tmp_path = None

    try:
        tfile = await voice.get_file()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await tfile.download_to_drive(tmp_path)

        text = None
        try:
            from hub._services.voice.voice_stt import VoiceSTT
            if not hasattr(handle_voice, "_stt"):
                handle_voice._stt = VoiceSTT()
            available, engine = handle_voice._stt.is_available()
            if available:
                text = handle_voice._stt.transcribe_file(tmp_path, language="de")
                if text and text.startswith("[Fehler"):
                    text = None
        except ImportError:
            pass

        if not text:
            try:
                import whisper
                if not hasattr(handle_voice, "_whisper"):
                    await update.message.reply_text("Lade Whisper-Modell (einmalig)...")
                    handle_voice._whisper = whisper.load_model("base")
                result = handle_voice._whisper.transcribe(tmp_path, language="de")
                text = result.get("text", "").strip()
            except ImportError:
                await update.message.reply_text(
                    "Weder BACH VoiceSTT noch Whisper verfügbar.\n"
                    "pip install openai-whisper"
                )
                return

        if not text:
            await update.message.reply_text("Konnte keine Sprache erkennen.")
            return

        await update.message.reply_text(f"Erkannt: {text}")
        update.message.text = text
        await handle_message(update, ctx)

    except Exception as e:
        log.error(f"Voice-Fehler: {e}")
        await update.message.reply_text(f"Transkription fehlgeschlagen: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return

    photos = update.message.photo
    if not photos:
        return

    await update.effective_chat.send_action("typing")
    tmp_path = None

    try:
        photo = photos[-1]
        tfile = await photo.get_file()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        await tfile.download_to_drive(tmp_path)

        ocr_text = None

        try:
            from hub._services.document.ocr_service import OCREngineService
            ocr = OCREngineService()
            ocr_text = ocr.ocr_file(tmp_path, lang="deu")
            if ocr_text:
                ocr_text = ocr_text.strip()
        except (ImportError, Exception):
            pass

        if not ocr_text:
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(tmp_path)
                ocr_text = pytesseract.image_to_string(img, lang="deu").strip()
            except ImportError:
                pass

        caption = update.message.caption or ""

        if ocr_text and len(ocr_text) > 2:
            await update.message.reply_text(f"OCR:\n{ocr_text[:2000]}")
            query = caption if caption else f"Der User hat ein Bild mit folgendem Text geschickt:\n{ocr_text}"
        elif caption:
            query = caption
        else:
            await update.message.reply_text(
                "Kein Text im Bild erkannt. Sende eine Bildunterschrift für Kontext."
            )
            return

        update.message.text = query
        await handle_message(update, ctx)

    except Exception as e:
        log.error(f"Photo-Fehler: {e}")
        await update.message.reply_text(f"Bildverarbeitung fehlgeschlagen: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# --- Compute Lock Helpers ---

def _compute_lock_enabled(selected_backend=None) -> bool:
    """Check if compute lock feature is enabled and available."""
    return (HAS_COMPUTE_LOCK
            and CONFIG.get("compute_lock", {}).get("enabled", False)
            and isinstance(selected_backend or runtime.backend, OllamaBackend))


def _compute_lock_blocks(selected_backend=None) -> bool:
    """Laeuft gerade ein Rechenjob, der einen Modell-Load verbieten wuerde?

    Haengt in ``ChatRuntime.process``, damit JEDER Aufrufer davor haltmacht --
    der Idle-Worker ueber /api/chat lud das 18-GB-Modell bisher trotz aktivem
    Lock und draengte einen Sage-Job in den Swap (T-20260907-440775748).

    Den vom Nutzer per JA freigegebenen Telegram-Load blockiert das nicht:
    dort sind die Jobs vorher per SIGSTOP pausiert, und check_compute_active
    filtert gestoppte PIDs heraus -- der Lock meldet dann "inaktiv".
    """
    if not _compute_lock_enabled(selected_backend):
        return False
    if get_fackel_preference() == "ollama":
        return False
    cl_cfg = CONFIG.get("compute_lock", {})
    is_active, _status = check_compute_active(
        lock_path=cl_cfg.get("lock_path", DEFAULT_LOCK_PATH),
        check_script=cl_cfg.get("check_script", DEFAULT_CHECK_SCRIPT),
    )
    return is_active


runtime.compute_gate = _compute_lock_blocks


async def _handle_pending_action(chat_id: str, text: str, update: Update) -> bool:
    """Handle JA/NEIN reply to a pending compute lock question.

    Returns True if the message was consumed (caller should return).
    """
    pending = _pending_actions.get(chat_id)
    if not pending:
        return False

    # Check TTL
    if time.time() - pending["timestamp"] > _PENDING_TTL:
        del _pending_actions[chat_id]
        return False

    reply = text.strip().upper()

    if reply in ("JA", "J", "YES", "Y"):
        del _pending_actions[chat_id]
        status = pending["status"]
        original_text = pending["text"]

        await update.message.reply_text("Pausiere Compute-Jobs...")
        paused = pause_compute_jobs(status)

        if not paused:
            await update.message.reply_text(
                "Keine Jobs pausiert (evtl. bereits beendet). Fahre fort..."
            )
        else:
            pid_str = ", ".join(str(p) for p in paused)
            await update.message.reply_text(
                f"Pausiert: {pid_str}\n"
                "Starte Ollama-Anfrage..."
            )

        # Session flag VOR dem LLM-Call schreiben (Watchdog braucht es für Inferenz-Schutz)
        model = runtime.get_session(chat_id).model or runtime.backend.get_default_model()
        if _compute_lock_enabled():
            write_session_flag(chat_id, model,
                               effective_keep_alive_seconds=get_effective_keep_alive_seconds())

        # Run the original message through the LLM
        typing = asyncio.create_task(_keep_typing(update))
        success = False
        try:
            if _compute_lock_enabled():
                set_inferenz_active(True)
            answer = await runtime.process(original_text, chat_id, skip_compute_gate=True)
            for i in range(0, len(answer), 4000):
                await update.message.reply_text(answer[i:i + 4000])
            session = runtime.get_session(chat_id)
            if session.voice_output:
                await _send_voice_reply(update, answer)
            success = True
        except Exception as e:
            log.error(f"Chat-Fehler nach Compute-Pause: {e}")
            await update.message.reply_text(f"Fehler: {e}")
        finally:
            if _compute_lock_enabled():
                set_inferenz_active(False)
            typing.cancel()

        # Start resume monitor if jobs were paused
        if paused:
            if not success:
                log.info("Chat inference failed after pause, resuming compute jobs immediately: %s", paused)
                delete_session_flag()
                resume_compute_jobs(paused)
                await update.message.reply_text(
                    "Anfrage fehlgeschlagen. Pausierte Compute-Jobs wurden wieder fortgesetzt."
                )
            else:
                ollama_url = getattr(runtime.backend, "base_url", "http://localhost:11434")

                def _on_resume(pids):
                    log.info("Compute jobs resumed: %s", pids)

                start_resume_monitor(
                    model_name=model,
                    paused_pids=paused,
                    callback=_on_resume,
                    ollama_url=ollama_url,
                    idle_wait=90.0,
                )
                await update.message.reply_text(
                    f"Resume-Monitor gestartet. Jobs werden automatisch "
                    f"fortgesetzt wenn {model} entladen wird."
                )

        return True

    elif reply in ("NEIN", "N", "NO"):
        del _pending_actions[chat_id]
        await update.message.reply_text("OK, kein Ollama-Load. Nachricht verworfen.")
        return True

    # Not a JA/NEIN reply — treat as new message, expire the pending action
    del _pending_actions[chat_id]
    return False


# --- Hauptnachrichten-Handler ---

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return

    text = update.message.text
    if not text:
        return

    chat_id = str(update.effective_chat.id)

    # Handle pending compute lock confirmation (JA/NEIN)
    if chat_id in _pending_actions:
        consumed = await _handle_pending_action(chat_id, text, update)
        if consumed:
            return

    # Compute lock check: before Ollama call, check if compute jobs are running
    if _compute_lock_enabled():
        cl_cfg = CONFIG.get("compute_lock", {})
        is_active, status = check_compute_active(
            lock_path=cl_cfg.get("lock_path", DEFAULT_LOCK_PATH),
            check_script=cl_cfg.get("check_script", DEFAULT_CHECK_SCRIPT),
        )
        if is_active:
            pref = get_fackel_preference()
            if pref == "ollama":
                cl_cfg = CONFIG.get("compute_lock", {})
                paused = pause_compute_jobs(status)
                if paused:
                    pid_str = ", ".join(str(p) for p in paused)
                    await update.message.reply_text(
                        f"Fackel steht auf Ollama: Pausiere Compute-Jobs automatisch ({pid_str})...\n"
                        f"Starte Ollama-Anfrage..."
                    )
                model = runtime.get_session(chat_id).model or runtime.backend.get_default_model()
                write_session_flag(chat_id, model,
                                   effective_keep_alive_seconds=get_effective_keep_alive_seconds())
                typing = asyncio.create_task(_keep_typing(update))
                success = False
                try:
                    set_inferenz_active(True)
                    answer = await runtime.process(text, chat_id, skip_compute_gate=True)
                    for i in range(0, len(answer), 4000):
                        await update.message.reply_text(answer[i:i + 4000])
                    session = runtime.get_session(chat_id)
                    if session.voice_output:
                        await _send_voice_reply(update, answer)
                    success = True
                except Exception as e:
                    log.error(f"Chat-Fehler mit Ollama-Fackel: {e}")
                    await update.message.reply_text(f"Fehler: {e}")
                finally:
                    set_inferenz_active(False)
                    typing.cancel()

                if paused:
                    if not success:
                        log.info("Chat inference failed after auto-pause, resuming compute jobs: %s", paused)
                        delete_session_flag()
                        resume_compute_jobs(paused)
                        await update.message.reply_text(
                            "Anfrage fehlgeschlagen. Pausierte Compute-Jobs wurden wieder fortgesetzt."
                        )
                    else:
                        ollama_url = getattr(runtime.backend, "base_url", "http://localhost:11434")

                        def _on_resume(pids):
                            log.info("Compute jobs resumed: %s", pids)

                        start_resume_monitor(
                            model_name=model,
                            paused_pids=paused,
                            callback=_on_resume,
                            ollama_url=ollama_url,
                            idle_wait=90.0,
                        )
                        await update.message.reply_text(
                            f"Resume-Monitor gestartet. Jobs werden automatisch "
                            f"fortgesetzt wenn {model} entladen wird."
                        )
                return
            else:
                msg = format_status_message(status)
                _pending_actions[chat_id] = {
                    "kind": "compute_pause_for_ollama",
                    "status": status,
                    "text": text,
                    "timestamp": time.time(),
                }
                await update.message.reply_text(msg)
                return
        model = runtime.get_session(chat_id).model or runtime.backend.get_default_model()
        write_session_flag(chat_id, model,
                           effective_keep_alive_seconds=get_effective_keep_alive_seconds())

    typing = asyncio.create_task(_keep_typing(update))

    try:
        if _compute_lock_enabled():
            set_inferenz_active(True)
        answer = await runtime.process(text, chat_id)
        for i in range(0, len(answer), 4000):
            await update.message.reply_text(answer[i:i + 4000])
        session = runtime.get_session(chat_id)
        if session.voice_output:
            await _send_voice_reply(update, answer)
    except Exception as e:
        log.error(f"Chat-Fehler: {e}")
        await update.message.reply_text(f"Fehler: {e}")
    finally:
        if _compute_lock_enabled():
            set_inferenz_active(False)
        typing.cancel()


async def _keep_typing(update):
    try:
        while True:
            await update.effective_chat.send_action("typing")
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        pass


# --- Control API (Port 8081) ---

CONTROL_PORT = int(os.environ.get("BACH_CONTROL_PORT", "8081"))
TELEGRAM_VERIFIED = False

WEB_DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BACH Chat Control</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --bg-dark: #0b0d14;
  --bg-panel: #111420;
  --bg-card: #171b28;
  --bg-elevated: #1c2033;
  --accent: #d4485a;
  --accent-light: #e06b7e;
  --accent-blue: #5b8def;
  --accent-glow: rgba(212, 72, 90, 0.12);
  --text: #e2ded8;
  --text-muted: #6e7386;
  --text-dim: #454a5c;
  --border: #1e2236;
  --border-hover: #2a3048;
  --success: #4ade80;
  --warning: #f5c542;
  --error: #ef5350;
  --radius-sm: 8px;
  --radius-md: 14px;
  --radius-lg: 18px;
  --ease: cubic-bezier(0.4, 0, 0.2, 1);
  --duration: 200ms;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg-dark);
  color: var(--text);
  padding: 20px;
  line-height: 1.5;
}

h1 {
  color: var(--text);
  margin-bottom: 20px;
  font-size: 1.4em;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--text) 40%, var(--accent) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

a {
  color: var(--accent-light);
  text-decoration: none;
  transition: all var(--duration) var(--ease);
}

a:hover {
  background: var(--bg-elevated) !important;
  border-color: var(--border-hover) !important;
  color: var(--text) !important;
}

.card {
  background: var(--bg-panel);
  border-radius: var(--radius-md);
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid var(--border);
  transition: border-color var(--duration) var(--ease),
              box-shadow var(--duration) var(--ease);
}

.card:hover {
  border-color: var(--border-hover);
}

.card h2 {
  color: var(--text);
  font-size: 1rem;
  font-weight: 700;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  letter-spacing: -0.01em;
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}

.status-row:last-child {
  border: none;
}

.label {
  color: var(--text-muted);
  font-size: 0.85em;
}

.value {
  color: var(--accent-light);
  font-weight: 600;
  font-size: 0.85em;
}

.btn-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.btn {
  font-family: inherit;
  background: var(--bg-card);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 16px;
  cursor: pointer;
  font-size: 0.85em;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  line-height: 1.4;
  transition: all var(--duration) var(--ease);
}

.btn:hover {
  background: var(--bg-elevated);
  border-color: var(--border-hover);
  color: var(--text);
}

.btn:active {
  transform: scale(0.97);
}

.btn.active {
  background: var(--accent);
  color: var(--bg-dark);
  border-color: var(--accent);
  font-weight: 700;
  box-shadow: 0 2px 12px var(--accent-glow);
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}

.dot.green {
  background: var(--success);
  box-shadow: 0 0 8px rgba(74, 222, 128, 0.4);
}

.dot.red {
  background: var(--error);
  box-shadow: 0 0 8px rgba(239, 83, 80, 0.4);
}

.dot.yellow {
  background: var(--warning);
  box-shadow: 0 0 8px rgba(245, 197, 66, 0.4);
}

#toast {
  position: fixed;
  bottom: 20px;
  right: 20px;
  background: var(--accent);
  color: var(--bg-dark);
  padding: 10px 18px;
  border-radius: var(--radius-sm);
  display: none;
  font-weight: 600;
  font-size: 0.85em;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  z-index: 99;
}
</style>
</head>
<body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px">
  <h1>BACH Chat Control</h1>
  <a href="/activity" style="display:inline-block;padding:8px 14px;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:var(--radius-sm);text-decoration:none;font-size:0.85em;font-weight:600">📊 Zur Aktivitätsanzeige &amp; Worker Dashboard &rarr;</a>
</div>

<div class="card" id="status-card">
<h2><span class="dot green" id="conn-dot"></span>Status</h2>
<div class="status-row"><span class="label">Backend</span><span class="value" id="s-backend">-</span></div>
<div class="status-row"><span class="label">Modell</span><span class="value" id="s-model">-</span></div>
<div class="status-row"><span class="label">Modus</span><span class="value" id="s-mode">-</span></div>
<div class="status-row"><span class="label">Denken</span><span class="value" id="s-think">-</span></div>
<div class="status-row"><span class="label">BACH</span><span class="value" id="s-bach">-</span></div>
<div class="status-row"><span class="label">Sessions</span><span class="value" id="s-sessions">-</span></div>
<div class="status-row"><span class="label">Max Tool-Runden</span><span class="value" id="s-maxrounds">-</span></div>
<div class="status-row"><span class="label">Fackel</span><span class="value" id="s-fackel">-</span></div>
<div class="status-row" id="tool-activity" style="display:none"><span class="label">Aktives Tool</span><span class="value" id="s-tool"><span class="dot yellow"></span>-</span></div>
</div>

<div class="card">
<h2>Backend</h2>
<div class="btn-group" id="backend-btns"></div>
</div>

<div class="card">
<h2>Fackel (Ressourcen-Priorität)</h2>
<div class="btn-group">
<button class="btn" id="fackel-btn-compute" onclick="setFackel('compute')">Rechenjobs (Compute)</button>
<button class="btn" id="fackel-btn-ollama" onclick="setFackel('ollama')">Ollama (Chat &amp; Worker)</button>
</div>
</div>

<div class="card">
<h2>Modus</h2>
<div class="btn-group">
<button class="btn" onclick="setMode('safe')">Safe</button>
<button class="btn" onclick="setMode('full')">Full</button>
</div>
</div>

<div class="card">
<h2>Denkmodus</h2>
<div class="btn-group">
<button class="btn" onclick="setThink(true)">AN</button>
<button class="btn" onclick="setThink(false)">AUS</button>
</div>
</div>

<div class="card">
<h2>Max Tool-Runden</h2>
<div class="btn-group">
<button class="btn" onclick="setMaxRounds(5)">5</button>
<button class="btn" onclick="setMaxRounds(10)">10</button>
<button class="btn" onclick="setMaxRounds(20)">20</button>
<button class="btn" onclick="setMaxRounds(0)">Tools aus</button>
</div>
</div>

<div class="card">
<h2>Modelle</h2>
<div class="btn-group" id="model-btns"></div>
</div>

<div id="toast"></div>

<script>
const API = location.origin + '/api';
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2000);
}
function controlTokenForWrite() {
  let token = localStorage.getItem('bach-control-api-token') || '';
  if (!token) {
    token = window.prompt('Control-API-Token für schreibende Aktionen:') || '';
    if (token) localStorage.setItem('bach-control-api-token', token.trim());
  }
  return token.trim();
}
async function api(method, path, body) {
  try {
    const headers = {'Content-Type': 'application/json'};
    if (method !== 'GET' && method !== 'HEAD') {
      const token = controlTokenForWrite();
      if (token) headers['Authorization'] = 'Bearer ' + token;
    }
    const opts = {method, headers};
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(API + path, opts);
    return await r.json();
  } catch(e) {
    document.getElementById('conn-dot').className = 'dot red';
    return {error: e.message};
  }
}
async function refresh() {
  const s = await api('GET', '/status');
  if (s.error) return;
  document.getElementById('conn-dot').className = 'dot green';
  document.getElementById('s-backend').textContent = s.backend + (s.backend_cli ? ' (' + s.backend_cli + ')' : '');
  document.getElementById('s-model').textContent = s.model;
  document.getElementById('s-mode').textContent = s.mode;
  document.getElementById('s-think').textContent = s.think ? 'AN' : 'AUS';
  document.getElementById('s-bach').textContent = s.bach ? 'Ja' : 'Nein';
  document.getElementById('s-sessions').textContent = s.sessions;
  document.getElementById('s-maxrounds').textContent = s.max_tool_rounds === 0 ? 'Tools aus' : s.max_tool_rounds;
  const fackelVal = s.fackel_preference === 'ollama' ? 'Ollama (Inferenz)' : 'Rechenjobs (Compute)';
  const fackelEl = document.getElementById('s-fackel');
  if (fackelEl) fackelEl.textContent = fackelVal;
  const fComputeBtn = document.getElementById('fackel-btn-compute');
  const fOllamaBtn = document.getElementById('fackel-btn-ollama');
  if (fComputeBtn) fComputeBtn.className = 'btn' + (s.fackel_preference === 'compute' ? ' active' : '');
  if (fOllamaBtn) fOllamaBtn.className = 'btn' + (s.fackel_preference === 'ollama' ? ' active' : '');
  const toolEl = document.getElementById('tool-activity');
  if (s.current_tool) {
    toolEl.style.display = '';
    document.getElementById('s-tool').innerHTML = '<span class="dot yellow"></span>' + s.current_tool + ' (Runde ' + s.tool_round + ')';
  } else if (s.last_tools && s.last_tools.length) {
    toolEl.style.display = '';
    document.getElementById('s-tool').innerHTML = s.last_tools.join(', ');
  } else {
    toolEl.style.display = 'none';
  }

  const bs = await api('GET', '/backends');
  if (!bs.error) {
    const c = document.getElementById('backend-btns');
    c.innerHTML = '';
    for (const [name, info] of Object.entries(bs)) {
      const b = document.createElement('button');
      b.className = 'btn';
      b.textContent = name + (info.status ? ' [' + info.status + ']' : '');
      b.disabled = info.available !== true;
      b.title = info.status || 'Backend nicht verfügbar';
      b.onclick = () => setBackend(name);
      c.appendChild(b);
    }
  }

  const ms = await api('GET', '/models');
  if (!ms.error && ms.models) {
    const c = document.getElementById('model-btns');
    c.innerHTML = '';
    ms.models.forEach(m => {
      const b = document.createElement('button');
      b.className = 'btn' + (m === s.model ? ' active' : '');
      b.textContent = m;
      b.onclick = () => setModel(m);
      c.appendChild(b);
    });
  }
}
async function setBackend(name) {
  const r = await api('POST', '/backend', {name});
  toast(r.error || 'Backend: ' + name);
  refresh();
}
async function setMode(mode) {
  const r = await api('POST', '/mode', {mode});
  toast(r.error || 'Modus: ' + mode);
  refresh();
}
async function setThink(think) {
  const r = await api('POST', '/think', {think});
  toast(r.error || 'Denken: ' + (think ? 'AN' : 'AUS'));
  refresh();
}
async function setModel(model) {
  const r = await api('POST', '/model', {model});
  toast(r.error || 'Modell: ' + model);
  refresh();
}
async function setMaxRounds(rounds) {
  const r = await api('POST', '/max_tool_rounds', {rounds});
  toast(r.error || 'Max Runden: ' + (rounds === 0 ? 'Tools aus' : rounds));
  refresh();
}
async function setFackel(pref) {
  const r = await api('POST', '/fackel', {preference: pref});
  toast(r.error || 'Fackel: ' + (pref === 'ollama' ? 'Ollama' : 'Rechenjobs'));
  refresh();
}
refresh();
let _refreshTimer = setInterval(refresh, 30000);
document.addEventListener('visibilitychange', () => {
  clearInterval(_refreshTimer);
  if (!document.hidden) { refresh(); _refreshTimer = setInterval(refresh, 30000); }
});
</script>
</body>
</html>"""


# Task #1348 / T-20260926-652455601 Phase 2.2:
# Modularisiertes Activity- & Worker-Dashboard mit neutralem Backend-Vertrag und konfigurierbarem Branding.
try:
    from gui.activity_dashboard import render_activity_dashboard
except ImportError:
    from system.gui.activity_dashboard import render_activity_dashboard

WEB_ACTIVITY_DASHBOARD = render_activity_dashboard()


def _control_prompt_response() -> dict:
    """One config-file snapshot in the legacy Activity shape plus CAS metadata."""
    snapshot = core_prompt_snapshot()
    prompts = snapshot["prompts"]
    system = prompts["system_default"]
    roles = {
        key[len("role_"):]: {
            "id": key[len("role_"):],
            "text": value["effective"],
            "default": value["default"],
            "is_custom": value["is_custom"],
        }
        for key, value in prompts.items() if key.startswith("role_")
    }
    return {
        "ok": True,
        "configuration_version": snapshot["configuration_version"],
        "source_version": snapshot["source_version"],
        "templates": {
            "system_default": {
                "id": "system_default", "text": system["effective"],
                "default": system["default"], "is_custom": system["is_custom"],
            },
            "roles": roles,
        },
    }





def _get_active_session_state():
    try:
        sessions_copy = list(runtime.sessions.values())
        if sessions_copy:
            s = sessions_copy[0]
            return s.model, s.mode, s.think
    except Exception:
        pass
    backend_model = ""
    try:
        backend_model = runtime.backend.get_default_model()
    except Exception:
        pass
    return (
        _global_defaults.get("model") or backend_model or "?",
        _global_defaults.get("mode", "safe"),
        _global_defaults.get("think", True),
    )


def _get_session_model(chat_id: str) -> str:
    with _runtime_state_lock:
        session = runtime.sessions.get(chat_id)
        session_model = str(getattr(session, "model", "") or "").strip()
        if session_model:
            return session_model

        configured_default = str(_global_defaults.get("model") or "").strip()
        return configured_default or runtime.backend.get_default_model()


def _snapshot_chat_backend(chat_id: str, *, worker_slot: dict | None = None, read_only: bool = False):
    with _runtime_state_lock:
        normalized = str(chat_id or "")
        registered_worker = _registered_worker_slot(normalized)
        from hub._services.chat.slots_config import system_slot_chat_id
        selected_system_id = system_slot_chat_id(normalized)
        from hub._services.chat.agent_profile_context import profile_chat_id_agent
        profile_chat = profile_chat_id_agent(normalized) is not None
        if profile_chat:
            collision = _execution_worker_slot(normalized)
            if registered_worker is not None or isinstance(collision, dict) and collision.get("id") == normalized:
                raise ValueError("Profil-Chat-ID ist bereits als Worker-Slot gebunden")
            if runtime.session_store is None:
                raise ValueError("Profilstore fehlt")
            runtime.session_store.load_state(chat_id)
        if (
            _is_strict_worker_id(normalized)
            and registered_worker is None
            and not _legacy_worker_binding_active(normalized)
        ):
            _resolve_slot_for_chat(normalized)
        if not read_only:
            with runtime._chat_turn_gates_lock:
                gate = runtime._chat_turn_gates.get(normalized)
            if gate is not None:
                with gate.condition:
                    active = gate.active_turns > 0
                if active:
                    session = runtime.sessions.get(normalized)
                    if session is None or getattr(session, "backend", None) is None:
                        raise WorkerBindingError("Aktive Turn-Konfiguration fehlt")
                    problem = ChatRuntime._worker_backend_gate(session, session.backend, session.model)
                    if problem is not None:
                        raise WorkerBindingError(str(problem))
                    return session.backend, session.model
        if profile_chat:
            # New and restored profile sessions are bound by process() first.
            # Preparing a slot prompt here would precede verified profile text.
            if selected_system_id:
                selected = _resolve_slot_for_chat(normalized)
                return _get_or_create_backend(selected["backend"], selected["model"]), selected["model"]
            return runtime.backend, _get_session_model(chat_id)
        if read_only:
            # Readiness polls may run while an admitted turn waits for compute.
            # Resolve availability without creating or reconfiguring its session.
            selected_worker = worker_slot if worker_slot is not None else _execution_worker_slot(normalized)
            if worker_slot is not None and (not isinstance(worker_slot, dict) or worker_slot.get("id") != normalized):
                raise WorkerBindingError("Worker-Slot fehlt oder stimmt nicht überein")
            dedicated = (registered_worker is not None or selected_system_id is not None
                         or normalized in DEFAULT_CORE_SLOTS or normalized.startswith("slot:")
                         or normalized.isdigit() or normalized.startswith(
                             ("idle", "worker-", "tg:", "telegram", "wa:", "whatsapp", "signal:")))
            if isinstance(selected_worker, dict) and selected_worker.get("id") == normalized:
                selected = selected_worker
            elif dedicated:
                selected = _resolve_slot_for_chat(normalized)
            else:
                return runtime.backend, _get_session_model(chat_id)
            if selected.get("enabled", True) is not True:
                raise WorkerBindingError("Systemsteckplatz ist ausgeschaltet oder nicht verfügbar")
            return _get_or_create_backend(selected["backend"], selected["model"]), selected["model"]
        session = runtime.get_session(chat_id)
        if worker_slot is None and registered_worker is not None:
            worker_slot = registered_worker
        if worker_slot is None:
            try:
                discovered_slot = _execution_worker_slot(normalized)
            except Exception:
                # We cannot prove this ID is not a restricted worker when
                # slot storage is unreadable. Never fall back with tools.
                session.allow_tools = False
                raise
            if isinstance(discovered_slot, dict) and discovered_slot.get("id") == normalized:
                worker_slot = discovered_slot
        if worker_slot is not None and (
            not isinstance(worker_slot, dict) or worker_slot.get("id") != normalized
        ):
            session.allow_tools = False
            raise ValueError("Worker-Slot fehlt oder stimmt nicht überein")
        is_dynamic_worker = (
            isinstance(worker_slot, dict) and worker_slot.get("id") == normalized
        )
        if is_dynamic_worker:
            # API worker IDs are caller-supplied and need not start with
            # "worker-". Bind the live slot before any backend/model call.
            session.worker_slot_reader = _execution_slot_reader(worker_slot)
            session.allow_tools = worker_slot.get("allow_tools", True) is True
        uses_dedicated_slot = (
            is_dynamic_worker
            or registered_worker is not None
            or normalized in DEFAULT_CORE_SLOTS
            or normalized.startswith("slot:")
            or selected_system_id is not None
            or normalized.isdigit()
            or normalized.startswith((
                "idle", "worker-", "tg:", "telegram", "wa:", "whatsapp", "signal:"
            ))
        )
        if not uses_dedicated_slot:
            return runtime.backend, _get_session_model(chat_id)
        try:
            target_backend, model = _apply_slot_to_session(
                chat_id, session, slot=worker_slot if is_dynamic_worker else None
            )
            return target_backend, model
        except Exception:
            if is_dynamic_worker:
                session.allow_tools = False
            if (
                is_dynamic_worker
                or registered_worker is not None
                or _is_strict_worker_id(normalized)
                or normalized in DEFAULT_CORE_SLOTS
                or normalized.startswith("slot:")
                or selected_system_id is not None
            ) and not _legacy_worker_binding_active(normalized):
                raise
            return runtime.backend, _get_session_model(chat_id)


def _checked_backend_availability(selected_backend, model: str) -> tuple[bool, str]:
    timeout = 8.0 if isinstance(selected_backend, CLIBackend) else 1.5
    try:
        available, status = selected_backend.availability(model=model, timeout=timeout)
    except Exception:
        return False, "Prüfung fehlgeschlagen"
    return available is True, str(status or "nicht verfügbar")


_BACKEND_INVENTORY_TTL_SECONDS = 30.0
_backend_inventory_lock = threading.Lock()
_backend_inventory_cache = {
    "expires_at": 0.0,
    "signature": None,
    "value": None,
}


def _invalidate_backend_inventory_cache() -> None:
    with _backend_inventory_lock:
        _backend_inventory_cache.update(
            expires_at=0.0,
            signature=None,
            value=None,
        )


def _copy_backend_inventory(value: dict[str, dict]) -> dict[str, dict]:
    return {name: dict(entry) for name, entry in value.items()}


def _probe_backend_inventory_entry(
    name: str,
    preset: dict,
    selected_id: str,
    selected_model: str,
) -> tuple[bool, str]:
    if name == selected_id:
        return _checked_backend_availability(runtime.backend, selected_model)

    try:
        candidate_config = {
            key: value
            for key, value in preset.items()
            if key not in ("method", "description")
        }
        if preset["method"] == "cli":
            cli_name = preset["type"].replace("-cli", "")
            if _check_cli_available(cli_name) != "vorhanden":
                raise FileNotFoundError(cli_name)
        elif name in ("claude-api", "openai", "hermes", "openrouter"):
            api_key = _load_api_key(name)
            if not api_key:
                return False, "Key fehlt"
            candidate_config["api_key"] = api_key

        candidate = create_backend(candidate_config)
        return _checked_backend_availability(
            candidate,
            preset["default_model"],
        )
    except FileNotFoundError:
        return False, "nicht gefunden"
    except Exception:
        return False, "Prüfung fehlgeschlagen"


def _backend_inventory() -> dict[str, dict]:
    from concurrent.futures import ThreadPoolExecutor, wait

    selected_id = backend_identifier(runtime.backend)
    selected_model, _, _ = _get_active_session_state()
    signature = (id(runtime.backend), selected_id, selected_model)
    now = time.monotonic()

    with _backend_inventory_lock:
        cached_value = _backend_inventory_cache["value"]
        if (
            cached_value is not None
            and _backend_inventory_cache["signature"] == signature
            and now < _backend_inventory_cache["expires_at"]
        ):
            return _copy_backend_inventory(cached_value)

        pool = ThreadPoolExecutor(max_workers=max(1, len(BACKEND_PRESETS)))
        try:
            futures = {
                name: pool.submit(
                    _probe_backend_inventory_entry,
                    name,
                    preset,
                    selected_id,
                    selected_model,
                )
                for name, preset in BACKEND_PRESETS.items()
            }
            done, _pending = wait(futures.values(), timeout=2.0)
            backends = {}
            for name, preset in BACKEND_PRESETS.items():
                if futures[name] not in done:
                    available, status = False, "Prüfung dauert zu lange"
                else:
                    try:
                        available, status = futures[name].result()
                    except Exception:
                        available, status = False, "Prüfung fehlgeschlagen"
                backends[name] = {
                    "description": preset["description"],
                    "method": preset["method"],
                    "default_model": preset["default_model"],
                    "status": status,
                    "available": available,
                    "selected": name == selected_id,
                }
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        _backend_inventory_cache.update(
            expires_at=time.monotonic() + _BACKEND_INVENTORY_TTL_SECONDS,
            signature=signature,
            value=_copy_backend_inventory(backends),
        )
        return _copy_backend_inventory(backends)


def _optional_agent_id(value, *, query: bool = False):
    """Keep absent legacy requests unchanged; reject bool, aliases and fuzzy IDs."""
    if value is None:
        return None
    if query:
        if type(value) is not str or not value.isascii() or not value.isdecimal() or value.startswith("0"):
            raise ValueError("agent_id muss eine positive Ganzzahl sein")
        value = int(value)
    if type(value) is not int or value <= 0:
        raise ValueError("agent_id muss eine positive Ganzzahl sein")
    return value


def _profile_request(agent_id, chat_id):
    from hub._services.chat.agent_profile_context import (
        ProfileUnavailable, profile_chat_id_agent, resolve_profile,
    )
    if agent_id is None:
        if str(chat_id).startswith("agent:"):
            raise ProfileUnavailable("Profilbindung fehlt")
        return None
    if profile_chat_id_agent(chat_id) != agent_id:
        raise ProfileUnavailable("Profil-Chat-ID stimmt nicht mit agent_id überein")
    if runtime is None or runtime.session_store is None:
        raise ProfileUnavailable("Dauerhafter Profilstore fehlt")
    binding, text = resolve_profile(agent_id)
    state = runtime.session_store.load_state(chat_id)
    if state["binding"] not in (None, binding) or (state["binding"] is None and state["messages"]):
        raise ProfileUnavailable("Chatverlauf gehört zu einem anderen Kontext")
    ram = runtime.sessions.get(chat_id)
    if ram is not None and (getattr(ram, "profile_binding", None) != binding):
        raise ProfileUnavailable("RAM-Chat gehört zu einem anderen Kontext")
    return binding, text


def _query_agent_id(parsed_url):
    values = parse_qs(parsed_url.query, keep_blank_values=True).get("agent_id", [])
    if len(values) > 1:
        raise ValueError("agent_id darf nur einmal vorkommen")
    return _optional_agent_id(values[0], query=True) if values else None


def _control_chat_response(answer) -> tuple[dict, int]:
    text = str(answer or "").strip()
    if not text:
        return {"ok": False, "error": "Chat-Backend lieferte keine Antwort"}, 502
    if isinstance(answer, SuccessfulAnswer):
        response = {"ok": True, "answer": text}
        if getattr(answer, "completed_task_ids", ()):
            response["completed_task_ids"] = list(answer.completed_task_ids)
        return response, 200
    if text.startswith(("Backend-Fehler:", "Fehler:")):
        return {"ok": False, "answer": text, "error": text}, 502
    return {"ok": True, "answer": text}, 200


def _is_trusted_host(host: str) -> bool:
    normalized = str(host or "").strip().strip("[]").lower()
    if normalized in ("localhost", "127.0.0.1", "::1", socket.gethostname().lower()):
        return True
    if normalized.endswith(".local") or normalized.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        if ip.is_loopback or ip.is_private:
            return True
        # Tailscale Carrier Grade NAT range 100.64.0.0/10
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
    except ValueError:
        pass
    return False


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().strip("[]")
    if normalized.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_allowed_origin(origin: str, req_host: str = "") -> bool:
    if not origin:
        return True
    parsed = urlparse(str(origin or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return False
    # Same-Origin match against request Host header
    if req_host:
        norm_req_host = req_host.split(":")[0].strip().lower()
        if parsed.hostname and parsed.hostname.lower() == norm_req_host:
            return True
    return _is_trusted_host(parsed.hostname or "")


def _is_loopback_origin(origin: str) -> bool:
    """Kompatibilitäts-Wrapper."""
    return _is_allowed_origin(origin)


def _control_bind_host() -> str:
    bind_host = os.environ.get("BACH_CONTROL_HOST", "127.0.0.1").strip()
    allow_remote = os.environ.get("BACH_CONTROL_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes", "on")
    if not _is_loopback_host(bind_host):
        if not allow_remote:
            raise ValueError(
                "Control API darf ohne authentifizierten Ingress nur an Loopback binden"
            )
        if not get_control_api_token():
            raise ValueError(
                "Control API benötigt für Remote-Bind ein konfiguriertes Bearer-Token"
            )
    return bind_host


class QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def _enrich_activity_history_with_tasks(history: list[dict[str, Any]]) -> None:
    """Enrich activity items that reference task_id with required_model/assigned_slot from tasks."""
    if not history:
        return
    task_ids: set[int] = set()
    for item in history:
        tid = item.get("task_id")
        if tid is None and isinstance(item.get("details"), dict):
            tid = item["details"].get("task_id")
        if tid is not None:
            try:
                task_ids.add(int(tid))
            except (ValueError, TypeError):
                pass
    if not task_ids:
        return

    try:
        from hub.bach_paths import BACH_DB
        db_env = os.environ.get("BACH_DB")
        db_path = Path(db_env) if db_env else BACH_DB
        if not db_path.exists():
            return
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        try:
            placeholders = ",".join("?" for _ in task_ids)
            cursor = conn.execute(
                f"SELECT id, required_model, assigned_slot FROM tasks WHERE id IN ({placeholders})",
                list(task_ids),
            )
            mapping = {int(row[0]): (row[1], row[2]) for row in cursor.fetchall()}
        finally:
            conn.close()

        for item in history:
            tid = item.get("task_id")
            if tid is None and isinstance(item.get("details"), dict):
                tid = item["details"].get("task_id")
            try:
                tid_int = int(tid) if tid is not None else None
            except (ValueError, TypeError):
                tid_int = None
            if tid_int in mapping:
                req_m, ass_s = mapping[tid_int]
                if "required_model" not in item:
                    item["required_model"] = req_m
                if "assigned_slot" not in item:
                    item["assigned_slot"] = ass_s
            else:
                if "required_model" not in item:
                    item["required_model"] = None
                if "assigned_slot" not in item:
                    item["assigned_slot"] = None
    except Exception as exc:
        log.debug("Konnte Activity nicht mit Tasks anreichern: %s", exc)


def start_worker_execution(worker_id: str, *, custom_prompt: str | None = None,
                           start_request_id: str | None = None,
                           expected_service_instance: str | None = None,
                           expected_configuration_version: str | None = None) -> tuple[dict, int]:
    """Public admission never accepts creator authority from content or request fields."""
    return _start_worker_execution(worker_id, custom_prompt=custom_prompt, start_request_id=start_request_id,
        expected_service_instance=expected_service_instance,
        expected_configuration_version=expected_configuration_version)


def _start_sequence_worker_execution(worker_id, *, _creator_authority, **kwargs):
    from hub._services.chat.native_sequences import _SequenceCreatorAuthority
    if (not isinstance(_creator_authority, _SequenceCreatorAuthority)
            or _creator_authority.service_instance != _WORKER_SERVICE_INSTANCE):
        raise ValueError("Private Sequenzzulassung gehört nicht zu diesem Controller")
    return _start_worker_execution(worker_id, _creator_authority=_creator_authority, **kwargs)


def _start_worker_execution(worker_id: str, *, custom_prompt: str | None = None,
                           start_request_id: str | None = None,
                           expected_service_instance: str | None = None,
                           expected_configuration_version: str | None = None,
                           _creator_authority=None) -> tuple[dict, int]:
    """Reserve one observable admission before role checks or physical launch."""
    if not isinstance(worker_id, str) or not worker_id:
        return {"error": "id erforderlich"}, 400
    if expected_service_instance is not None and expected_service_instance != _WORKER_SERVICE_INSTANCE:
        return {"error": "Control-Instanz wurde geändert", "error_code": "service_instance_conflict"}, 409
    request_id = start_request_id if start_request_id is not None else uuid.uuid4().hex
    if (not isinstance(request_id, str) or len(request_id) != 32
            or any(char not in "0123456789abcdef" for char in request_id)):
        return {"error": "Ungültige Start-Request-ID"}, 400

    def rejected(response, status):
        # This synchronous response proves only that this exact request was
        # rejected before reservation; it says nothing about another run.
        return {**response, "admission": {"admitted": False, "worker_id": worker_id,
            "start_request_id": request_id, "service_instance": _WORKER_SERVICE_INSTANCE}}, status

    with _WORKER_CONTROL_LOCK:
        known = _WORKER_EXECUTIONS.get(worker_id)
        if known is not None and known.start_request_id == request_id:
            execution = worker_execution_receipt(worker_id, request_id)
            return {"ok": True, "execution": execution}, 200 if execution["terminal"] else 202
        if known is not None and not worker_execution_receipt(worker_id)["terminal"]:
            execution = worker_execution_receipt(worker_id)
            return rejected({"ok": False, "status": execution["state"], "error": "Vorheriger Start noch nicht beendet",
                    "execution": execution}, 409)
        current, thread = _active_worker_control(worker_id)
        if _thread_is_alive(thread):
            state = "stopping" if current is not None and current.stop_event.is_set() else "running"
            response = {"ok": False, "status": state,
                "error": "Worker-Beendigung läuft" if state == "stopping" else "Worker läuft bereits"}
            if current is not None and current.receipt:
                response["receipt"] = current.receipt
            return rejected(response, 409)
        try:
            from hub._services.chat.slots_config import worker_admission_transaction, system_worker_at_version
            with worker_admission_transaction() as advance_revision:
                if expected_configuration_version is not None:
                    slot = system_worker_at_version(worker_id, expected_configuration_version)
                else:
                    slot = _execution_worker_slot(worker_id)
                if not slot or slot.get("id") != worker_id:
                    return rejected({"error": f"Worker {worker_id} nicht gefunden"}, 404)
                if slot.get("enabled", True) is not True:
                    return rejected({"error": "Worker ist deaktiviert"}, 403)
                control = _WorkerControl(worker_id, start_request_id=request_id,
                                         admitted_worker={"id": worker_id, "type": slot.get("type")},
                                         slot_policy_reader=_execution_slot_reader(slot),
                                         sequence_creator_authority=_creator_authority)
                control.admission_handle = _WorkerAdmission()
                control.admission_pending = True
                control.thread = control.admission_handle
                # No RAM admission is published unless the durable revision
                # write succeeds. Keep the file lock until all registries agree.
                advance_revision()
                _WORKER_CONTROLS[worker_id] = control
                _ACTIVE_WORKER_THREADS[worker_id] = control.thread
                _WORKER_EXECUTIONS[worker_id] = control
        except Exception as exc:
            return rejected({"error": f"Worker-Slot nicht verifizierbar: {exc}"}, 503)
    try:
        response, status = _start_reserved_worker_execution(control, slot, custom_prompt)
        if status != 200:
            control.start_error = "admission_denied"
    except Exception:
        control.stop_event.set()
        control.start_error = "launch_unconfirmed" if control.launch_attempted else "admission_unconfirmed"
        response, status = {"error": "Worker-Start nicht bestätigt"}, 503
    finally:
        with _WORKER_CONTROL_LOCK:
            control.admission_pending = False
            control.admission_handle.finished.set()
            if not control.launch_attempted:
                control.done_event.set()
                if control.stop_event.is_set():
                    _write_revocation_receipt(control, slot, outcome="revocation-confirmed-before-worker-start")
                if _WORKER_CONTROLS.get(worker_id) is control:
                    _WORKER_CONTROLS.pop(worker_id, None)
                if _ACTIVE_WORKER_THREADS.get(worker_id) is control.admission_handle:
                    _ACTIVE_WORKER_THREADS.pop(worker_id, None)
    return {**response, "execution": worker_execution_receipt(worker_id, request_id)}, status


def _start_reserved_worker_execution(control, w, custom_prompt):
    worker_id = control.worker_id
    # Admission fixes the provider and execution policy for this generation.
    # A later edit requires an explicit new start, including while no task exists.
    control.slot_policy_reader()

    # Befehlsvertrag (agents_heart, Konzept 10.8): Rolle beglaubigen und
    # Assignment eröffnen, bevor der Worker-Thread startet (fail-closed).
    sub_mode = (w.get("sub_mode") or "").strip().lower()
    worker_instance_id = f"worker-{uuid.uuid4().hex}"
    try:
        board_assignment = begin_assignment(
            role_id=(sub_mode or "task_worker"),
            mode=(w.get("mode") or "full"),
            agent_instance_id=worker_instance_id,
            backend_id=w.get("backend") or "ollama",
            model_id=w.get("model") or "qwen3.8:27b-mlx",
            slot_id=worker_id,
            task_id=(w.get("task_id") if w.get("task_id") is not None else 0),
            session_id=worker_id,
            initiated_by=f"board:{worker_id}",
        )
    except AssignmentDenied as exc:
        return {"error": f"Assignment verweigert: {exc}"}, 400
    except ValueError as exc:
        return {"error": f"Assignment unvollständig: {exc}"}, 400

    def _run_worker_job():
        control.worker_thread_started = True
        control.admission_pending = False
        worker_error = None
        worker_session = None
        current_assignment = board_assignment
        assignment_task_id = w.get("task_id") or 0
        assignment_open = True
        try:
            if control.stop_event.is_set():
                return
            _update_worker_slot(control, {"status": "running", "auto_paused": False, "current_activity": "Starte Routine..."})
            _record_worker_activity(control, f"Worker gestartet: {w.get('name')}", "running")
            if control.stop_event.is_set():
                return
            _snapshot_chat_backend(worker_id, worker_slot=w)
            if control.stop_event.is_set():
                return
            if custom_prompt:
                initial_prompt = custom_prompt
            elif w.get("task_id"):
                initial_prompt = (
                    f"Führe Task #{w.get('task_id')} aus. Markiere ihn erst nach tatsächlicher "
                    f"Erledigung mit task_manage(action='done', task_id={w.get('task_id')}). "
                    "Bei Hindernissen nicht als erledigt markieren; dokumentiere den konkreten Fortsetzungsschritt."
                )
            elif w.get("sub_mode") == "hintergrund_worker":
                initial_prompt = (
                    "Prüfe die offenen Tasks in der von BACH verwendeten TaskDB und bearbeite die "
                    "wichtigste passende Aufgabe. Markiere sie erst nach tatsächlicher Erledigung mit "
                    "task_manage(action='done', task_id=<ID>). Bei Hindernissen bleibt die Task offen; "
                    "nenne den konkreten Fortsetzungsschritt."
                )
            elif w.get("sub_mode") == "boss_routing":
                initial_prompt = (
                    "Analysiere die offenen Aufgaben in der TaskDB, zerlege komplexe Aufgaben mit "
                    "task_manage(action='decompose') und nenne passende Fachrollen als Empfehlung. "
                    "Behaupte keine Zuweisung oder Übernahme, solange die TaskDB keinen Claim/Lease bestätigt."
                )
            elif w.get("sub_mode") == "expert_role":
                role = w.get("role_id") or "Experte"
                if role == "task-divider":
                    initial_prompt = "Analysiere komplexe offene Aufgaben im Backlog und zerlege sie in strukturierte Teilaufgaben via task_manage action='decompose'."
                elif role == "ticket-master":
                    initial_prompt = (
                        "Triagiere Aufgaben anhand der TaskDB. Nutze nur task_manage-Aktionen "
                        "list, detail, add, update und decompose; action='assign' ist nicht verfügbar. "
                        "Erstelle bei Bedarf konkrete Tasks und halte Tickets als Dokumentationsverweise. "
                        "Eine Task wird über den vorgesehenen Claim/Lease-Prozess übernommen; behaupte keine "
                        "Zuweisung, die die TaskDB nicht bestätigt."
                    )
                else:
                    initial_prompt = f"Arbeite als {role} die offenen Aufgaben deines Fachgebiets in BACH ab."
            else:
                initial_prompt = w.get("task_prompt") or (
                    "Prüfe offene Aufgaben und beginne mit der Bearbeitung. Markiere eine Task erst nach "
                    "tatsächlicher Erledigung mit task_manage(action='done', task_id=<ID>)."
                )

            prompt_to_run = initial_prompt
            run_count = 0

            while True:
                if control.stop_event.is_set():
                    break
                run_count += 1

                # Worker-State prüfen: wurde er pausiert oder gelöscht?
                current_slot = control.slot_policy_reader()
                if current_slot and current_slot.get("enabled", True) is not True:
                    _update_worker_slot(control, {"status": "idle", "current_activity": "Worker ist deaktiviert"})
                    break
                if not current_slot or current_slot.get("status") in ("paused", "idle", "stopping"):
                    log.info(f"Worker {worker_id} pausiert oder beendet.")
                    break

                # TTL prüfen
                exp_str = current_slot.get("expires_at")
                if exp_str:
                    try:
                        exp_dt = datetime.fromisoformat(exp_str)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) >= exp_dt:
                            log.info(f"Worker {worker_id} TTL abgelaufen.")
                            _update_worker_slot(control, {"status": "expired", "current_activity": "Ablaufzeit erreicht (Beendet)"})
                            _record_worker_activity(control, "Worker TTL abgelaufen", "ok")
                            return
                    except Exception:
                        pass

                # Re-snapshot each block: persistent workers must not
                # retain an old capability after a slot downgrade.
                target_backend, model = _snapshot_chat_backend(
                    worker_id, worker_slot=current_slot
                )
                with _WORKER_CONTROL_LOCK:
                    control.supports_step_actions = not getattr(target_backend, "manages_own_tools", False)

                if control.task_binding is None or control.task_binding.closed:
                    _retain_worker_task_receipts(control)
                    if control.lease_supervisor is not None:
                        control.lease_supervisor.close()
                        control.lease_supervisor = None
                    control.task_binding = _acquire_worker_task(control, current_slot, worker_instance_id)
                    if control.task_binding is None:
                        if current_slot.get("type") not in {"continuous", "persistent"}:
                            _update_worker_slot(control, {"status": "idle", "current_activity": "Keine passende übernehmbare Aufgabe"})
                            return
                        _update_worker_slot(control, {"current_activity": "Warte auf eine passende übernehmbare Aufgabe"})
                        if control.stop_event.wait(10):
                            break
                        continue
                    if _update_worker_slot(control, {"task_id": control.task_binding.task_id}) is None:
                        break
                    current_slot = {**current_slot, "task_id": control.task_binding.task_id}
                control.task_binding.assert_active()
                if assignment_open and str(assignment_task_id) != str(control.task_binding.task_id):
                    finish_assignment(current_assignment, status="released", result="role_authorized",
                                      reason="actual_task_acquired")
                    assignment_open = False
                if not assignment_open:
                    current_assignment = begin_assignment(
                        role_id=(current_slot.get("sub_mode") or "task_worker"),
                        mode=(current_slot.get("mode") or "full"),
                        agent_instance_id=worker_instance_id,
                        backend_id=current_slot.get("backend") or "ollama",
                        model_id=model,
                        slot_id=worker_id,
                        task_id=control.task_binding.task_id,
                        session_id=worker_id,
                        initiated_by=f"board:{worker_id}",
                    )
                    assignment_task_id = control.task_binding.task_id
                    assignment_open = True
                if control.lease_supervisor is None:
                    control.lease_supervisor = WorkerLeaseSupervisor(control.task_binding)
                    control.lease_supervisor.__enter__()

                if control.stop_event.is_set():
                    break
                loop = asyncio.new_event_loop()
                ans = ""
                try:
                    worker_session = runtime.get_session(worker_id)
                    worker_session.worker_slot_reader = control.slot_policy_reader
                    worker_session.worker_handoff = control.handoff
                    worker_session.worker_task_actions = control.task_actions
                    worker_session.worker_task_binding = control.task_binding
                    worker_session.require_task_binding = True
                    ans = loop.run_until_complete(
                        runtime.process(
                            _bound_worker_prompt(control.task_binding, prompt_to_run),
                            worker_id,
                            backend=target_backend,
                            model=model,
                            work_priority="background",
                        )
                    )
                finally:
                    loop.close()

                resolved = (getattr(worker_session, "resolved_model", None)
                            or getattr(target_backend, "last_resolved_model", None))
                if resolved:
                    _update_worker_slot(control, {"resolved_model": str(resolved)})

                if control.stop_event.is_set():
                    break
                if control.lease_supervisor.failure is not None:
                    raise control.lease_supervisor.failure
                if not control.task_binding.closed:
                    control.task_binding.assert_active()
                ans_str = str(ans)
                # FailedAnswer is a str subclass and may also be
                # restored as plain text after persistence. Neither
                # form may complete a once-worker or be logged as ok.
                if FailedAnswer.looks_like(ans):
                    _update_worker_slot(control, {
                        "status": "error",
                        "current_activity": ans_str[:120],
                    })
                    _record_worker_activity(
                        control,
                        f"Block {run_count}: {ans_str[:55]}",
                        "error",
                    )
                    return
                if not _record_worker_activity(control, f"Block {run_count}: {ans_str[:55]}", "ok"):
                    break

                # Only this run's authoritative Release/Decompose ACK
                # may complete the task; legacy string receipts cannot.
                completion_receipts = control.task_binding.completed_task_ids
                _retain_worker_task_receipts(control)
                task_completed = _worker_task_completed(current_slot, completion_receipts)
                task_reviewed = control.task_binding.task_id in control.task_binding.reviewed_task_ids
                if control.task_binding.closed and not task_completed and not task_reviewed:
                    finish_assignment(current_assignment, status="released",
                                      result="task_returned", reason="verified_lease_ack")
                    assignment_open = False
                    if current_slot.get("type") in {"continuous", "persistent"}:
                        returned = control.task_binding.task_snapshot()
                        control.deferred_task_versions[control.task_binding.task_id] = returned["task_version"]
                        if control.lease_supervisor is not None:
                            control.lease_supervisor.close()
                            control.lease_supervisor = None
                        worker_session.worker_task_binding = None
                        control.task_binding = None
                        if _update_worker_slot(control, {"status": "running", "task_id": None,
                                "current_activity": "Task zurückgegeben oder blockiert; suche nächste passende Aufgabe"}) is None:
                            break
                        _record_worker_activity(control, "Task zurückgegeben; unveränderte Version für diesen Lauf zurückgestellt", "pending")
                        if not _wait_worker_cooldown(control, event_type="runs") or control.stop_event.wait(10):
                            break
                        prompt_to_run = initial_prompt
                        continue
                    _update_worker_slot(control, {"status": "idle", "current_activity": "Task zurückgegeben oder blockiert"})
                    return

                # Einzellauf endet nach einem abgeschlossenen Block.
                if current_slot.get("type") == "once":
                    if task_reviewed:
                        _update_worker_slot(control, {"status": "idle", "task_id": None,
                            "current_activity": "PR bestätigt; Aufgabe wartet auf Prüfung"})
                        return
                    assigned_task_id = current_slot.get("task_id")
                    if assigned_task_id not in (None, "", 0, "0") and not task_completed:
                        _update_worker_slot(control, {
                            "status": "idle",
                            "current_activity": (
                                f"Task #{assigned_task_id} bleibt offen; Zwischenergebnis gespeichert"
                            ),
                        })
                        _record_worker_activity(
                            control,
                            f"Task #{assigned_task_id} ohne Abschlussbeleg beendet",
                            "pending",
                        )
                        return
                    _update_worker_slot(control, _worker_once_completion_changes(current_slot, completion_receipts))
                    return

                # Fortlaufende Profile dürfen ohne TTL bis zum manuellen
                # Stopp laufen; 0 bedeutet kein Ablaufdatum.
                if current_slot.get("type") not in {"continuous", "persistent"}:
                    _update_worker_slot(control, {"status": "idle", "current_activity": "Fertig: " + ans_str[:40]})
                    break

                if task_completed or task_reviewed:
                    finish_assignment(
                        current_assignment, status="completed" if task_completed else "released",
                        result="task_done" if task_completed else "task_review",
                        reason="verified_lease_ack",
                    )
                    assignment_open = False
                    # Die konfigurierte Task ist nur der erste Auftrag.
                    # Folgeaufträge dürfen nicht an ihre alte ID gebunden
                    # bleiben; der nächste Block erhält eine neue Besetzung.
                    if current_slot.get("task_id") not in (None, "", 0, "0"):
                        if _update_worker_slot(control, {"task_id": None}) is None:
                            break

                # Count a task only when task_manage returned a successful
                # completion receipt for this worker's assigned task.
                is_max_turns = "(Max Tool-Runden erreicht)" in ans_str and not (task_completed or task_reviewed)
                pause_event = _worker_pause_event_type(
                    current_slot,
                    task_completed=task_completed,
                )
                if not _wait_worker_cooldown(control, event_type=pause_event):
                    break

                # Prüfen ob Max-Tool-Runden erreicht wurden -> Handoff.
                if is_max_turns:
                    if _update_worker_slot(control, {
                        "status": "running",
                        "current_activity": f"Rundenübergabe (Block {run_count + 1} startet)..."
                    }) is None:
                        break
                    prompt_to_run = (
                        "Fortsetzung nach Rundenübergabe: Du hast dein bisheriges Tool-Budget erreicht. "
                        "Führe die angefangene Aufgabe nun nahtlos fort und schließe sie ab."
                    )
                    if control.stop_event.wait(2):
                        break
                elif task_completed or task_reviewed:
                    # A verified completion lets a continuous worker pick the next task.
                    if _update_worker_slot(control, {
                        "status": "running",
                        "current_activity": ("PR bestätigt; Aufgabe wartet auf Prüfung. " if task_reviewed else "Aufgabe fertig. ")
                            + f"Suche nächste Aufgabe (Lauf {run_count + 1})..."
                    }) is None:
                        break
                    if control.stop_event.wait(12):
                        break
                    prompt_to_run = (
                        "Prüfe die offenen Tasks in der von BACH verwendeten TaskDB und bearbeite die nächste "
                        "wichtige passende Aufgabe. Markiere sie erst nach tatsächlicher Erledigung mit "
                        "task_manage(action='done', task_id=<ID>)."
                    )
                else:
                    # Do not abandon or mark an unverified task complete.
                    if _update_worker_slot(control, {
                        "status": "running",
                        "current_activity": f"Task noch offen. Setze sie fort (Lauf {run_count + 1})..."
                    }) is None:
                        break
                    if control.stop_event.wait(2):
                        break
                    prompt_to_run = (
                        "Setze die zuletzt bearbeitete Task fort. Es liegt noch kein erfolgreicher "
                        "task_manage(action='done')-Beleg vor. Prüfe den aktuellen Taskstatus und arbeite "
                        "weiter; nur nach tatsächlicher Erledigung mit der konkreten Task-ID als done markieren."
                    )

            if control.stop_event.is_set():
                return
            latest_slot = _execution_worker_slot(worker_id)
            if not latest_slot or latest_slot.get("status") in ("paused", "idle", "completed", "expired", "stopping"):
                return
            next_status = _worker_terminal_status(latest_slot)
            _update_worker_slot(control, {"status": next_status, "current_activity": "Abgeschlossen"})
        except Exception as exc:
            worker_error = exc
            log.error(f"Worker {worker_id} Fehler: {exc}")
            if not control.stop_event.is_set():
                _update_worker_slot(control, {"status": "error", "current_activity": f"Fehler: {exc}"})
                _record_worker_activity(control, f"Fehler: {exc}", "error")
        finally:
            if control.lease_supervisor is not None:
                control.lease_supervisor.close()
            if control.task_binding is not None:
                control.task_binding.return_lease()
            if (worker_session is not None
                    and getattr(worker_session, "worker_task_binding", None) is control.task_binding):
                worker_session.worker_task_binding = None
            # Befehlsvertrag (agents_heart): Assignment in jedem
            # Ausstiegspfad beenden (assignment_ended, Konzept 10.8).
            try:
                if (control.task_binding is not None
                        and str(assignment_task_id) == str(control.task_binding.task_id)
                        and control.task_binding.task_id in control.task_binding.completed_task_ids):
                    _as_status, _as_result, _as_reason = (
                        "completed", "task_done", "verified_lease_ack")
                elif (control.task_binding is not None
                        and str(assignment_task_id) == str(control.task_binding.task_id)
                        and control.task_binding.task_id in control.task_binding.reviewed_task_ids):
                    _as_status, _as_result, _as_reason = (
                        "released", "task_review", "verified_lease_ack")
                elif worker_error is not None:
                    _as_status, _as_result, _as_reason = (
                        "error", "runtime_error", type(worker_error).__name__)
                elif control.stop_event.is_set():
                    _as_status, _as_result, _as_reason = "interrupted", "stopped", ""
                else:
                    _latest_status = (_execution_worker_slot(worker_id) or {}).get("status")
                    if _latest_status == "expired":
                        _as_status, _as_result, _as_reason = "released", "ttl_expired", ""
                    else:
                        _as_status, _as_result, _as_reason = "released", "not_finished", ""
                if assignment_open:
                    finish_assignment(current_assignment, status=_as_status,
                                      result=_as_result, reason=_as_reason)
            except Exception:
                log.warning(f"Worker {worker_id}: finish_assignment fehlgeschlagen",
                            exc_info=True)
            if control.stop_event.is_set():
                _write_revocation_receipt(
                    control,
                    w,
                    outcome=(
                        "revocation-confirmed-after-error"
                        if worker_error is not None
                        else "revocation-confirmed"
                    ),
                )
            with _WORKER_CONTROL_LOCK:
                control.handoff.cancel()
                control.task_actions.cancel()
                if _WORKER_CONTROLS.get(worker_id) is control:
                    handoff_receipt = control.handoff.snapshot()
                    if handoff_receipt:
                        try:
                            _persist_worker_metadata(control, {"handoff_receipt": handoff_receipt})
                        except Exception:
                            log.warning("Worker-Übergabebeleg konnte nicht gespeichert werden", exc_info=True)
                    task_action_receipt = control.task_actions.snapshot()
                    if task_action_receipt:
                        try:
                            _persist_worker_metadata(control, {"task_action_receipt": task_action_receipt})
                        except Exception:
                            log.warning("Worker-Zerlegungsbeleg konnte nicht gespeichert werden", exc_info=True)
                if worker_session is not None and getattr(worker_session, "worker_handoff", None) is control.handoff:
                    worker_session.worker_handoff = None
                if worker_session is not None and getattr(worker_session, "worker_task_actions", None) is control.task_actions:
                    worker_session.worker_task_actions = None
                registered_thread = _ACTIVE_WORKER_THREADS.get(worker_id)
                if registered_thread is threading.current_thread() or registered_thread is control.thread:
                    _ACTIVE_WORKER_THREADS.pop(worker_id, None)
                if _WORKER_CONTROLS.get(worker_id) is control:
                    _WORKER_CONTROLS.pop(worker_id, None)
                control.done_event.set()

    th = threading.Thread(target=_run_worker_job, daemon=True, name=f"worker-{worker_id}")
    with _WORKER_CONTROL_LOCK:
        current_control = _WORKER_CONTROLS.get(worker_id)
        current_slot = _execution_worker_slot(worker_id)
        if (current_control is not control or control.stop_event.is_set()
                or not current_slot
                or current_slot.get("enabled", True) is not True
                or _execution_worker_configuration(current_slot) != _execution_worker_configuration(w)):
            finish_assignment(board_assignment, status="interrupted", result="start_conflict", reason="configuration_changed")
            return {"error": "Worker oder Konfiguration inzwischen geändert"}, 409
        control.thread = th
        _WORKER_CONTROLS[worker_id] = control
        _ACTIVE_WORKER_THREADS[worker_id] = th
        control.launch_attempted = True
        try:
            th.start()
        except BaseException:
            control.stop_event.set()
            raise
        control.worker_thread_started = True
    return {"ok": True, "message": f"Worker {worker_id} gestartet"}, 200


_NATIVE_SEQUENCES = None
_NATIVE_SEQUENCES_LOCK = threading.RLock()


def _native_sequences():
    global _NATIVE_SEQUENCES
    with _NATIVE_SEQUENCES_LOCK:
        if _NATIVE_SEQUENCES is None:
            from hub._services.chat.native_sequences import NativeSequences, NativeGateway
            from hub._services.chat.sequence_store import SequenceStore
            from hub._services.skill_source_service import check_write_locks
            from hub._services.chat.bach_tools import _current_runtime_db
            if _native_task_client().mode != "local":
                raise RuntimeError("Native Ketten werden auf dem konfigurierten TaskDB-Lead ausgeführt")
            database = Path(_current_runtime_db())
            gateway = NativeGateway(service_instance=_WORKER_SERVICE_INSTANCE, start=_start_sequence_worker_execution,
                observe=worker_execution_receipt, result=worker_execution_result,
                stop=_request_worker_revocation, slot=_execution_worker_slot)
            _NATIVE_SEQUENCES = NativeSequences(SequenceStore(database,
                write_guard=lambda: check_write_locks(database)), gateway)
        return _NATIVE_SEQUENCES


class ControlHandler(BaseHTTPRequestHandler):
    def _sequence_response(self, action, body=None, query=None):
        from hub._services.chat.sequence_store import SequenceConflict
        body, query = body or {}, query or {}
        try:
            service = _native_sequences()
            if action == "catalog":
                result = service.catalog()
            elif action == "read_run":
                result = {"run": service.get_run(query.get("run_id", [""])[0])}
            else:
                allowed = {
                    "create": {"action", "definition"},
                    "update": {"action", "chain_id", "version", "definition"},
                    "delete": {"action", "chain_id", "version"},
                    "start": {"action", "chain_id", "request"},
                    "stop": {"action", "run_id"},
                }
                if action not in allowed or set(body) != allowed[action]:
                    raise ValueError("Ungültige Kettenaktion oder Felder")
                if action in {"update", "delete", "start"}:
                    if type(body["chain_id"]) is not int or body["chain_id"] <= 0:
                        raise ValueError("Gültige Ketten-ID erforderlich")
                if action == "create":
                    result = {"chain": service.store.save_chain(body["definition"])}
                elif action == "update":
                    result = {"chain": service.store.save_chain(body["definition"], chain_id=body["chain_id"], expected_version=body["version"])}
                elif action == "delete":
                    service.store.delete_chain(body["chain_id"], body["version"])
                    result = {"deleted": True, "chain_id": body["chain_id"]}
                elif action == "start":
                    result = service.start(body["chain_id"], body["request"])
                else:
                    result = service.stop(body["run_id"])
            self._json({"ok": True, **result})
        except SequenceConflict as exc:
            self._json({"error": str(exc)}, 409)
        except KeyError:
            self._json({"error": "Kette, Lauf oder Skill nicht gefunden"}, 404)
        except (ValueError, TypeError):
            self._json({"error": "Ungültige Kettendefinition, Bindung oder Eingabe"}, 400)
        except RuntimeError as exc:
            if str(exc) == "configuration_version_conflict":
                self._json({"error": "Living-Konfiguration inzwischen geändert"}, 409)
            else:
                self._json({"error": "Kettenlauf oder kanonische Quelle nicht verfügbar"}, 503)
        except Exception:
            log.exception("Native chain request could not be confirmed")
            self._json({"error": "Kettenaktion nicht bestätigt"}, 503)

    def log_message(self, fmt, *args):
        log.debug("ControlAPI: " + fmt % args)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _canonicalize_origin_for_header(self, origin: str) -> Optional[str]:
        if not origin or "\r" in origin or "\n" in origin:
            return None
        try:
            parsed = urlparse(origin)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return None
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return None
        if not hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None

        try:
            host = f"[{ipaddress.IPv6Address(hostname).compressed}]"
        except ValueError:
            if ":" in hostname:
                return None
            try:
                host = hostname.encode("idna").decode("ascii").lower()
            except UnicodeError:
                return None
            if "\r" in host or "\n" in host:
                return None
        if port is None:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"

    def _cors(self):
        raw_origin = str(self.headers.get("Origin") or "").strip()
        host = str(self.headers.get("Host") or "").strip()
        if not raw_origin or "\r" in raw_origin or "\n" in raw_origin:
            return
        if not _is_allowed_origin(raw_origin, host):
            return
        safe_origin = self._canonicalize_origin_for_header(raw_origin)
        if not safe_origin:
            return
        self.send_header("Access-Control-Allow-Origin", safe_origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _html(self, html):
        body = html.encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            try:
                return json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
        return {}

    def _allow_control_request(self) -> bool:
        if not is_control_api_authorized(self.headers):
            self._json({"error": "Control-API-Token erforderlich oder ungültig"}, 401)
            return False

        origin = str(self.headers.get("Origin") or "").strip()
        host = str(self.headers.get("Host") or "").strip()
        if origin and not _is_allowed_origin(origin, host):
            self._json({"error": "Fremd-Origin nicht erlaubt"}, 403)
            return False
        return True

    def _allow_json_post(self) -> bool:
        if not self._allow_control_request():
            return False

        content_type = str(self.headers.get("Content-Type") or "")
        media_type = content_type.partition(";")[0].strip().lower()
        if media_type != "application/json":
            self._json({"error": "Content-Type application/json erforderlich"}, 415)
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path in {"/api/marblerun/catalog", "/api/marblerun/run"}:
            if not self._allow_control_request():
                return
            self._sequence_response("catalog" if path.endswith("catalog") else "read_run", query=parse_qs(parsed_url.query))
            return

        if path == "/api/auth/check":
            # T-20260926-652455601: side-effect-free capability authentication.
            # Use the exact mutation guard; public status proves no write rights.
            if not self._allow_control_request():
                return
            self._json({"service": "bach-chat-control", "authenticated": True})

        elif path == "/":
            self._html(WEB_DASHBOARD)

        elif path == "/api/status":
            try:
                model, mode, think = _get_active_session_state()
                backend_name = type(runtime.backend).__name__
                cli_name = getattr(runtime.backend, "cli_name", "")
                owns_tools = getattr(runtime.backend, "manages_own_tools", False)
                active_tools = []
                current_tool = ""
                tool_round = 0
                sessions_snapshot = list(runtime.sessions.values())
                for s in sessions_snapshot:
                    if s.current_tool:
                        current_tool = s.current_tool
                        tool_round = s.tool_round
                    if s.last_tools:
                        active_tools = s.last_tools
                        break
                _SYS_IDS = {"idle-worker", "tray-prompt", "api-delegate", "claude-delegate"}
                now = time.time()
                items_snapshot = list(runtime.sessions.items())
                active_user = sum(
                    1 for cid, s in items_snapshot
                    if cid not in _SYS_IDS and (s.current_tool or now - s.last_active < 120)
                )
                self._json({
                    "service": "bach-chat-control",
                    "telegram_verified": TELEGRAM_VERIFIED,
                    "backend": backend_name,
                    "backend_id": backend_identifier(runtime.backend),
                    "backend_cli": cli_name,
                    "model": model,
                    "mode": mode,
                    "think": think,
                    "manages_own_tools": owns_tools,
                    "bach": HAS_BACH,
                    "sessions": len(sessions_snapshot),
                    "active_sessions": active_user,
                    "max_tool_rounds": runtime.max_tool_rounds,
                    "fackel_preference": get_fackel_preference(),
                    "compute_turn": runtime.compute_turn_status(),
                    "current_tool": current_tool,
                    "tool_round": tool_round,
                    "last_tools": active_tools,
                })
            except Exception as e:
                logger.warning(f"/api/status Snapshot-Fehler abgefangen: {e}")
                self._json({
                    "service": "bach-chat-control",
                    "telegram_verified": TELEGRAM_VERIFIED,
                    "backend": type(runtime.backend).__name__,
                    "backend_id": backend_identifier(runtime.backend),
                    "backend_cli": getattr(runtime.backend, "cli_name", ""),
                    "model": _global_defaults.get("model") or getattr(runtime.backend, "get_default_model", lambda: "?")(),
                    "mode": _global_defaults.get("mode", "safe"),
                    "think": _global_defaults.get("think", True),
                    "manages_own_tools": getattr(runtime.backend, "manages_own_tools", False),
                    "bach": HAS_BACH,
                    "sessions": len(list(runtime.sessions.keys())),
                    "active_sessions": 0,
                    "max_tool_rounds": runtime.max_tool_rounds,
                    "fackel_preference": get_fackel_preference(),
                    "compute_turn": runtime.compute_turn_status(),
                    "current_tool": "",
                    "tool_round": 0,
                    "last_tools": [],
                })

        elif path == "/api/backends":
            self._json(_backend_inventory())

        elif path == "/api/readiness":
            chat_id = parse_qs(parsed_url.query).get("chat_id", ["api-delegate"])[0]
            try:
                agent_id = _query_agent_id(parsed_url)
                if agent_id is None:
                    _profile_request(None, chat_id)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            if agent_id is not None and not self._allow_control_request():
                return
            try:
                selected_backend, model = _snapshot_chat_backend(chat_id, read_only=True)
            except WorkerBindingError as exc:
                self._json({"ok": False, "error": str(exc)}, 503)
                return
            except Exception as exc:
                self._json({"ok": False, "error": f"Slot-Konfiguration nicht verifizierbar: {exc}"}, 503)
                return
            available, availability_status = _checked_backend_availability(
                selected_backend,
                model,
            )
            result = {
                "available": available,
                "status": availability_status,
                "backend_id": backend_identifier(selected_backend),
                "model": model,
            }
            if agent_id is not None:
                try:
                    binding, _text = _profile_request(agent_id, chat_id)
                    capability = {"agent_id": agent_id, "available": True,
                        "context_class": binding["context_class"],
                        "db_version": binding["db_version"],
                        "source_version": binding["source_version"]}
                except Exception:
                    capability = {"agent_id": agent_id, "available": False,
                        "context_class": "agent-profile", "db_version": None,
                        "source_version": None, "reason": "Profilkontext nicht verfügbar"}
                result["profile_capability"] = capability
                result["can_chat"] = bool(available and capability["available"])
            self._json(result)

        elif path == "/api/models":
            try:
                requested_provider = parse_qs(parsed_url.query).get("provider", [""])[0].strip().lower()
                if requested_provider:
                    preset = BACKEND_PRESETS.get(requested_provider)
                    if not preset:
                        self._json({"error": "Unbekannter Provider"}, 400)
                        return
                    config = {key: value for key, value in preset.items()
                              if key not in ("method", "description")}
                    configured = True
                    if requested_provider in {"claude-api", "openai", "hermes", "openrouter"}:
                        api_key = _load_api_key(requested_provider)
                        configured = bool(api_key)
                        if api_key:
                            config["api_key"] = api_key
                    selected_backend = create_backend(config)
                    models = selected_backend.list_models()
                    self._json({
                        "provider": requested_provider,
                        "models": models,
                        "credential_configured": configured,
                    })
                else:
                    with _runtime_state_lock:
                        selected_backend = runtime.backend
                    models = selected_backend.list_models()
                    self._json({"models": models, "provider": backend_identifier(selected_backend)})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/history":
            if not self._allow_control_request():
                return
            chat_id = parse_qs(parsed_url.query).get("chat_id", ["gui-web"])[0]
            try:
                agent_id = _query_agent_id(parsed_url)
                agent_context = _profile_request(agent_id, chat_id)
                bound = (agent_context is not None and
                    runtime.session_store.load_state(chat_id)["binding"] == agent_context[0])
                messages = runtime.history(chat_id) if agent_context is None or bound else []
                response = {"ok": True, "chat_id": chat_id, "messages": messages}
                if agent_context is not None:
                    response.update({"agent_id": agent_context[0]["agent_id"],
                        "context_class": "agent-profile", "binding_confirmed": bound})
                self._json(response)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 409)
            except Exception:
                self._json({"ok": False, "error": "Profilverlauf nicht verifizierbar"}, 503)

        elif path == "/api/sessions":
            if not self._allow_control_request():
                return
            limit = int(parse_qs(parsed_url.query).get("limit", [50])[0])
            if runtime.session_store:
                try:
                    agent_id = _query_agent_id(parsed_url)
                    snapshots = runtime.session_store.list_snapshots(limit=limit)
                    if agent_id is not None:
                        _profile_request(agent_id, f"agent:{agent_id}:" + "0" * 32)
                        snapshots = [s for s in snapshots if s.get("agent_id") == agent_id
                            and s.get("context_class") == "agent-profile"]
                    else:
                        snapshots = [s for s in snapshots if s.get("context_class") != "agent-profile"]
                    self._json({"ok": True, "sessions": snapshots})
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self._json({"ok": False, "error": "Kein SessionStore konfiguriert"}, 500)

        elif path == "/api/session":
            if not self._allow_control_request():
                return
            try:
                sid = int(parse_qs(parsed_url.query).get("id", [0])[0])
            except ValueError:
                sid = 0
            if runtime.session_store and sid > 0:
                try:
                    snap = runtime.session_store.get_snapshot_by_id(sid)
                    if snap:
                        binding = snap.get("binding")
                        agent_id = _query_agent_id(parsed_url)
                        if binding is not None:
                            if agent_id != binding["agent_id"]:
                                self._json({"error": "Profilbindung erforderlich"}, 409)
                                return
                            current, _text = _profile_request(agent_id, snap["chat_id"])
                            if current != binding:
                                self._json({"error": "Profilquelle nicht mehr verifiziert"}, 409)
                                return
                        elif agent_id is not None:
                            self._json({"error": "Snapshot gehört keinem Agentenprofil"}, 409)
                            return
                        self._json({"ok": True, "session": snap})
                    else:
                        self._json({"error": "Snapshot nicht gefunden"}, 404)
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self._json({"error": "Ungültige oder fehlende Snapshot-ID"}, 400)

        elif path == "/activity":
            self._html(render_activity_dashboard())

        elif path == "/api/system-slots":
            if not self._allow_control_request():
                return
            try:
                self._json({"ok": True, **_system_slots_snapshot()})
            except Exception:
                self._json({"error": "System-Steckplätze nicht verifizierbar"}, 503)

        elif path == "/api/slots":
            if not self._allow_control_request():
                return
            try:
                cfg = load_slots_config()
                slots = cfg.get("slots", {})
                for sid, s in slots.items():
                    s["pause_info"] = get_slot_pause_info(s)
                workers = list_workers(include_expired=True, active_worker_ids=_active_worker_ids())
                for w in workers:
                    w["pause_info"] = get_slot_pause_info(w)
                self._json({
                    "ok": True,
                    "slots": slots,
                    "dynamic_workers": workers,
                    "fackel_preference": get_fackel_preference(),
                })
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers/configuration":
            worker_id = parse_qs(parsed_url.query).get("id", [""])[0]
            try:
                self._json({"ok": True, **worker_configuration_snapshot(worker_id)})
            except KeyError:
                self._json({"error": "Workerprofil nicht gefunden"}, 404)
            except Exception:
                self._json({"error": "Worker-Konfiguration nicht verfügbar"}, 503)

        elif path == "/api/workers":
            try:
                self._json({
                    "ok": True,
                    "workers": _worker_execution_snapshots(),
                })
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers/execution":
            if not self._allow_control_request():
                return
            query = parse_qs(parsed_url.query)
            worker_id = query.get("id", [""])[0]
            request_id = query.get("start_request_id", [None])[0]
            try:
                with _WORKER_CONTROL_LOCK:
                    if not worker_id or (worker_id not in _WORKER_EXECUTIONS and not _execution_worker_slot(worker_id)):
                        self._json({"error": "Worker nicht gefunden"}, 404)
                        return
                    self._json({"ok": True, "execution": worker_execution_receipt(worker_id, request_id)})
            except ValueError:
                self._json({"error": "Start-Request oder Slot nicht bestätigt",
                    "service_instance": _WORKER_SERVICE_INSTANCE}, 409)
            except Exception:
                self._json({"error": "Workerlauf nicht verifizierbar"}, 503)

        elif path == "/api/activity":
            try:
                q = parse_qs(parsed_url.query)

                def _query_int(key: str, default: int) -> int:
                    val = q.get(key, [str(default)])[0].strip()
                    return int(val) if val else default

                def _query_str_list(key: str) -> Optional[List[str]]:
                    vals = q.get(key)
                    if not vals:
                        return None
                    items = []
                    for v in vals:
                        items.extend([x.strip() for x in v.split(",") if x.strip()])
                    return items if items else None

                limit = _query_int("limit", 50)
                offset = _query_int("offset", 0)
                order = (q.get("order", ["desc"])[0] or "desc").lower()
                source = _query_str_list("source")
                status = _query_str_list("status")
                since = (q.get("since", [""])[0] or None)
                until = (q.get("until", [""])[0] or None)

                if order not in ("asc", "desc"):
                    self._json({"error": "order muss 'asc' oder 'desc' sein"}, 400)
                    return

                history = get_activity_history(
                    limit=limit,
                    offset=offset,
                    source=source,
                    status=status,
                    since=since,
                    until=until,
                    order=order,
                )
                _enrich_activity_history_with_tasks(history)
                self._json({
                    "ok": True,
                    "history": history,
                })
            except Exception as e:
                log.warning("/api/activity Fehler: %s", e, exc_info=True)
                self._json({"error": str(e)}, 500)

        elif path == "/api/prompts":
            if not self._allow_control_request():
                return
            try:
                self._json(_control_prompt_response())
            except (OSError, ValueError, TypeError):
                # In-memory defaults are a preview, not an attested active revision.
                self._json({"ok": True, "source": "in_memory_defaults",
                            "templates": get_prompt_templates()})

        elif path == "/api/chat/history":
            chat_id = parse_qs(parsed_url.query).get("chat_id", [""])[0]
            if not chat_id:
                self._json({"error": "chat_id erforderlich"}, 400)
            else:
                try:
                    agent_context = _profile_request(_query_agent_id(parsed_url), chat_id)
                    bound = (agent_context is not None and
                        runtime.session_store.load_state(chat_id)["binding"] == agent_context[0])
                    msgs = []
                    if agent_context is None or bound:
                        session = runtime.sessions.get(chat_id)
                        if session and session.messages:
                            msgs = session.messages
                        elif runtime.session_store:
                            msgs = runtime._load_messages(chat_id)
                    response = {"ok": True, "chat_id": chat_id, "messages": msgs}
                    if agent_context is not None:
                        response.update({"agent_id": agent_context[0]["agent_id"],
                            "context_class": "agent-profile", "binding_confirmed": bound})
                    self._json(response)
                except Exception as e:
                    self._json({"error": str(e)}, 500)

        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self._allow_json_post():
            return
        path = urlparse(self.path).path
        body = self._read_body()
        if not isinstance(body, dict):
            self._json({"error": "JSON-Objekt erforderlich"}, 400)
            return

        if path == "/api/marblerun/action":
            self._sequence_response(body.get("action"), body)
            return

        if path == "/api/backend":
            name = body.get("name", "")
            model = body.get("model", "")
            if name not in BACKEND_PRESETS:
                self._json({"error": f"Unbekannt: {name}"}, 400)
                return
            preset = BACKEND_PRESETS[name].copy()
            if model:
                preset["default_model"] = model
            elif name == "ollama":
                current_m = _global_defaults.get("model") or getattr(runtime.backend, "default_model", None)
                if current_m:
                    preset["default_model"] = current_m
            if preset["method"] == "api" and name in ("claude-api", "openai", "hermes", "openrouter"):
                api_key = _load_api_key(name)
                if not api_key:
                    self._json({"error": f"Kein API-Key für {name}"}, 400)
                    return
                preset["api_key"] = api_key
            try:
                config = {k: v for k, v in preset.items()
                          if k not in ("method", "description")}
                new_backend = create_backend(config)
                selected_model = preset["default_model"]
                available, availability_status = _checked_backend_availability(
                    new_backend,
                    selected_model,
                )
                if not available:
                    self._json({
                        "ok": False,
                        "error": f"Backend nicht verfügbar: {availability_status}",
                    }, 503)
                    return
                with _runtime_state_lock:
                    runtime.backend = new_backend
                    _global_defaults["model"] = selected_model
                    for s in list(runtime.sessions.values()):
                        s.model = selected_model
                _invalidate_backend_inventory_cache()
                self._json({"ok": True, "backend": name, "model": preset["default_model"]})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/mode":
            mode = body.get("mode", "")
            if mode not in ("safe", "full"):
                self._json({"error": "safe oder full"}, 400)
                return
            _global_defaults["mode"] = mode
            for s in list(runtime.sessions.values()):
                s.mode = mode
            self._json({"ok": True, "mode": mode})

        elif path == "/api/model":
            model = body.get("model", "")
            if not model:
                self._json({"error": "model erforderlich"}, 400)
                return
            _global_defaults["model"] = model
            for s in list(runtime.sessions.values()):
                s.model = model
            self._json({"ok": True, "model": model})

        elif path == "/api/think":
            think = body.get("think", True)
            _global_defaults["think"] = bool(think)
            for s in list(runtime.sessions.values()):
                s.think = bool(think)
            self._json({"ok": True, "think": bool(think)})

        elif path == "/api/max_tool_rounds":
            rounds = int(body.get("rounds", 0))
            if rounds < 0:
                rounds = 0
            runtime.max_tool_rounds = rounds
            _global_defaults["max_tool_rounds"] = rounds
            self._json({"ok": True, "max_tool_rounds": rounds})

        elif path == "/api/fackel":
            pref = str(body.get("preference", "")).lower().strip()
            if pref not in ("compute", "ollama"):
                self._json({"error": "preference muss 'compute' oder 'ollama' sein"}, 400)
                return
            try:
                set_fackel_preference(pref, quelle="api")
            except Exception as e:
                self._json({"error": f"Konnte Fackel nicht setzen: {e}"}, 500)
                return
            self._json({"ok": True, "fackel_preference": pref})

        elif path == "/api/chat":
            prompt = body.get("prompt", "")
            chat_id = body.get("chat_id", "api-delegate")
            try:
                agent_id = _optional_agent_id(body.get("agent_id"))
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            depth = int(self.headers.get("X-Delegation-Depth", "0"))
            if not prompt:
                self._json({"error": "prompt erforderlich"}, 400)
                return
            if depth >= 2:
                self._json({"error": "Maximale Delegationstiefe erreicht"}, 429)
                return
            try:
                agent_context = _profile_request(agent_id, chat_id)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 409)
                return
            except Exception:
                self._json({"ok": False, "error": "Profilbindung nicht verifizierbar"}, 503)
                return
            try:
                selected_backend, model = _snapshot_chat_backend(chat_id)
            except WorkerBindingError as exc:
                self._json({"ok": False, "error": str(exc)}, 503)
                return
            except Exception as exc:
                self._json({"ok": False, "error": f"Slot-Konfiguration nicht verifizierbar: {exc}"}, 503)
                return
            available, availability_status = _checked_backend_availability(
                selected_backend,
                model,
            )
            if not available:
                self._json({
                    "ok": False,
                    "error": f"Backend nicht verfügbar: {availability_status}",
                }, 503)
                return
            os.environ["BACH_DELEGATION_DEPTH"] = str(depth + 1)
            try:
                loop = asyncio.new_event_loop()
                try:
                    process_kwargs = {"backend": selected_backend, "model": model}
                    if agent_context is not None:
                        process_kwargs["agent_context"] = agent_context
                    answer = loop.run_until_complete(
                        runtime.process(prompt, chat_id, **process_kwargs)
                    )
                finally:
                    loop.close()
                if not isinstance(answer, FailedAnswer):
                    response, status = _control_chat_response(answer)
                    if agent_context is not None and status == 200:
                        response.update({"agent_id": agent_context[0]["agent_id"],
                            "context_class": "agent-profile", "binding_confirmed": True})
                    self._json(response, status)
                else:
                    text = str(answer)
                    self._json({"ok": False, "answer": text, "error": text}, 502)
            except ComputeLocked as e:
                self._json({"ok": False, "compute_locked": True, "answer": str(e)})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            finally:
                os.environ.pop("BACH_DELEGATION_DEPTH", None)

        elif path == "/api/transcribe":
            # Task #1338: Audio-Transkription im Buddha-Chat (Base64-in-JSON).
            # Domaenenlogik: hub/_services/voice/voice_stt.py::transcribe_b64_payload
            try:
                from hub._services.voice.voice_stt import transcribe_b64_payload
            except ImportError:
                self._json({"ok": False, "error": "Voice-Service nicht verfuegbar"}, 503)
                return
            response, status = transcribe_b64_payload(body)
            self._json(response, status)

        elif path == "/api/clear":
            chat_id = body.get("chat_id", "gui-web")
            try:
                _profile_request(_optional_agent_id(body.get("agent_id")), chat_id)
            except ValueError as exc:
                self._json({"ok": False, "chat_id": chat_id, "error": str(exc)}, 409)
                return
            except Exception:
                self._json({"ok": False, "chat_id": chat_id, "error": "Profilbindung nicht verifizierbar"}, 503)
                return
            try:
                archived_id = runtime.clear_session(chat_id, archive_reason="Control-API")
            except RuntimeError as exc:
                self._json({"ok": False, "chat_id": chat_id, "error": str(exc)}, 503)
                return
            self._json({"ok": True, "chat_id": chat_id, "archived_id": archived_id})

        elif path == "/api/fork":
            chat_id = body.get("chat_id", "gui-web")
            try:
                agent_id = _optional_agent_id(body.get("agent_id"))
                agent_context = _profile_request(agent_id, chat_id)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 409)
                return
            except Exception:
                self._json({"ok": False, "error": "Profilbindung nicht verifizierbar"}, 503)
                return
            try:
                snapshot_id = int(body.get("snapshot_id", 0))
            except (TypeError, ValueError):
                snapshot_id = 0
            if snapshot_id <= 0:
                self._json({"error": "snapshot_id erforderlich"}, 400)
                return
            try:
                count = runtime.fork_session(chat_id, snapshot_id, agent_context=agent_context)
                response = {"ok": True, "chat_id": chat_id, "snapshot_id": snapshot_id, "messages_count": count}
                if agent_context is not None:
                    response.update({"agent_id": agent_context[0]["agent_id"],
                        "context_class": "agent-profile", "binding_confirmed": True})
                self._json(response)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/slots":
            slot_id = body.get("slot_id") or body.get("id")
            updates = body.get("updates") or {}
            if not slot_id or not isinstance(updates, dict):
                self._json({"error": "slot_id und updates dict erforderlich"}, 400)
                return
            try:
                updated = update_slot(slot_id, updates)
                record_activity(slot_id, f"Slot {slot_id} aktualisiert", "ok")
                self._json({"ok": True, "slot": updated})
            except KeyError as e:
                self._json({"error": str(e)}, 404)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers":
            try:
                worker = add_worker(body)
                record_activity("system", f"Neuer Worker erstellt: {worker.get('name', worker.get('id'))}", "ok")
                self._json({"ok": True, "worker": worker})
            except ValueError as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path in ("/api/workers/delete", "/api/worker/delete"):
            worker_id = body.get("id") or body.get("worker_id")
            if not worker_id:
                self._json({"error": "id erforderlich"}, 400)
                return
            ok = remove_worker(worker_id)
            if ok:
                record_activity("system", f"Worker gelöscht: {worker_id}", "ok")
                self._json({"ok": True, "id": worker_id})
            else:
                self._json({"error": f"Worker {worker_id} nicht gefunden"}, 404)

        elif path == "/api/workers/toggle":
            worker_id = body.get("id") or body.get("worker_id")
            new_status = body.get("status")
            if not worker_id:
                self._json({"error": "id erforderlich"}, 400)
                return
            try:
                w = _execution_worker_slot(worker_id)
                if not w:
                    self._json({"error": "Worker nicht gefunden"}, 404)
                    return
                if not new_status:
                    new_status = "paused" if w.get("status") != "paused" else "idle"
                if new_status in ("paused", "idle"):
                    confirmed, updated, receipt, response_status = _request_worker_revocation(
                        worker_id,
                        w,
                        requested_status=new_status,
                        activity=f"Worker {new_status}",
                    )
                    response = {"ok": confirmed, "worker": updated, "receipt": receipt}
                    if not confirmed:
                        response["error"] = "Worker-Ende noch nicht nachgewiesen"
                    self._json(response, response_status)
                    return
                updated = update_slot(worker_id, {"status": new_status})
                record_activity(worker_id, f"Worker Status: {new_status}", "ok")
                self._json({"ok": True, "worker": updated})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers/stop":
            worker_id = body.get("id") or body.get("worker_id")
            if not worker_id:
                self._json({"error": "id erforderlich"}, 400)
                return
            try:
                expected_fields = ("service_instance", "start_request_id", "generation")
                expected_execution = None
                if any("expected_" + field in body for field in expected_fields):
                    expected_execution = {field: body.get("expected_" + field) for field in expected_fields}
                _validate_worker_execution_fence(expected_execution)
                try:
                    w = _execution_worker_slot(worker_id)
                except Exception:
                    if expected_execution is None:
                        raise
                    w = None
                if not w and expected_execution is not None:
                    with _WORKER_CONTROL_LOCK:
                        retained = _WORKER_EXECUTIONS.get(worker_id)
                        w = retained.admitted_worker if retained is not None else None
                if not w:
                    self._json({"error": "Worker nicht gefunden"}, 404)
                    return
                confirmed, updated, receipt, response_status = _request_worker_revocation(
                    worker_id,
                    w,
                    activity="Manuell gestoppt",
                    expected_execution=expected_execution,
                )
                response = {"ok": confirmed, "worker": updated, "receipt": receipt}
                if receipt.get("execution") is not None:
                    response["execution"] = receipt["execution"]
                if not confirmed:
                    response["error"] = "Worker-Ende noch nicht nachgewiesen"
                self._json(response, response_status)
            except ValueError:
                self._json({"error": "Ungültige Ausführungsbindung für Stop"}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers/configuration":
            try:
                result = _change_worker_configuration(body.get("id"), body.get("configuration_version"), body.get("changes"))
                self._json({"ok": True, **result})
            except KeyError:
                self._json({"error": "Workerprofil nicht gefunden"}, 404)
            except RuntimeError:
                self._json({"error": "Worker läuft oder Konfiguration inzwischen geändert"}, 409)
            except (TypeError, ValueError):
                self._json({"error": "Ungültige Worker-Konfiguration"}, 400)
            except Exception:
                self._json({"error": "Worker-Konfiguration konnte nicht bestätigt werden"}, 503)

        elif path == "/api/workers/decompose":
            worker_id, generation = body.get("id"), body.get("generation")
            task_id, task_version = body.get("task_id"), body.get("task_version")
            if (set(body) != {"id", "generation", "task_id", "task_version"}
                    or not isinstance(worker_id, str) or not worker_id or len(worker_id) > 80
                    or not isinstance(generation, str) or len(generation) != 32
                    or any(c not in "0123456789abcdef" for c in generation)
                    or type(task_id) is not int or task_id <= 0
                    or not isinstance(task_version, str) or len(task_version) != 64
                    or any(c not in "0123456789abcdef" for c in task_version)):
                self._json({"error": "Aktueller Workerlauf und Task-Inhaltsversion erforderlich"}, 400)
                return
            try:
                receipt = _request_worker_decomposition(worker_id, generation, task_id, task_version)
                self._json({"ok": True, "receipt": receipt}, 202)
            except ValueError as exc:
                self._json({"error": str(exc)}, 409)
            except Exception:
                self._json({"error": "Zerlegungsanfrage nicht verifizierbar"}, 503)

        elif path == "/api/workers/handoff":
            worker_id = body.get("id")
            generation = body.get("generation")
            if (not isinstance(worker_id, str) or not worker_id or len(worker_id) > 80
                    or not isinstance(generation, str) or len(generation) != 32
                    or any(c not in "0123456789abcdef" for c in generation)):
                self._json({"error": "Worker-ID und aktuelle Generation erforderlich"}, 400)
                return
            try:
                receipt = _request_worker_handoff(worker_id, generation)
                self._json({"ok": True, "receipt": receipt}, 202)
            except ValueError as exc:
                self._json({"error": str(exc)}, 409)
            except Exception:
                self._json({"error": "Workerlauf nicht verifizierbar"}, 503)

        elif path == "/api/workers/run":
            response, status = start_worker_execution(
                body.get("id") or body.get("worker_id"), custom_prompt=body.get("prompt"),
                start_request_id=body.get("start_request_id"),
                expected_service_instance=body.get("expected_service_instance"),
                expected_configuration_version=body.get("configuration_version"),
            )
            self._json(response, status)

        elif path == "/api/activity":
            source = body.get("source", "system")
            act = body.get("activity", "")
            st = body.get("status", "ok")
            dt = body.get("details", {})
            record_activity(source, act, st, dt)
            self._json({"ok": True})

        elif path == "/api/prompts":
            key = str(body.get("key", "")).strip()
            prompt_text = body.get("text", "")
            if not key or prompt_text is None:
                self._json({"error": "key und text erforderlich"}, 400)
                return
            try:
                if "configuration_version" in body:
                    change_core_prompt(key, body["configuration_version"], text=prompt_text)
                else:
                    update_prompt_template(key, prompt_text)
                record_activity("system", f"Prompt-Vorlage {key} aktualisiert", "ok")
                response = _control_prompt_response()
                response["key"] = key
                self._json(response)
            except KeyError:
                self._json({"error": "Unbekannte Prompt-ID"}, 404)
            except RuntimeError as e:
                if str(e) == "configuration_version_conflict":
                    self._json({"error": "Konfiguration inzwischen geändert"}, 409)
                else:
                    self._json({"error": "Prompt konnte nicht gespeichert werden"}, 503)
            except ValueError:
                self._json({"error": "Ungültiger Prompttext oder Zustand"}, 400)
            except Exception:
                self._json({"error": "Prompt konnte nicht gespeichert werden"}, 503)

        elif path == "/api/prompts/reset":
            key = body.get("key")
            try:
                if "configuration_version" in body:
                    change_core_prompt(str(key or ""), body["configuration_version"], reset=True)
                else:
                    reset_prompt_template(key)
                record_activity("system", f"Prompt-Vorlage(n) zurückgesetzt: {key or 'alle'}", "ok")
                response = _control_prompt_response()
                response["key"] = key
                self._json(response)
            except KeyError:
                self._json({"error": "Unbekannte Prompt-ID"}, 404)
            except RuntimeError as e:
                if str(e) == "configuration_version_conflict":
                    self._json({"error": "Konfiguration inzwischen geändert"}, 409)
                else:
                    self._json({"error": "Prompt konnte nicht zurückgesetzt werden"}, 503)
            except ValueError:
                self._json({"error": "Ungültiger Promptzustand"}, 400)
            except Exception:
                self._json({"error": "Prompt konnte nicht zurückgesetzt werden"}, 503)

        else:
            self._json({"error": "Not found"}, 404)

    def do_DELETE(self):
        if not self._allow_control_request():
            return
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/api/workers":
            params = parse_qs(parsed_url.query)
            worker_id = params.get("id", [""])[0]
            if not worker_id:
                self._json({"error": "id erforderlich"}, 400)
                return
            ok = remove_worker(worker_id)
            if ok:
                record_activity("system", f"Worker gelöscht: {worker_id}", "ok")
                self._json({"ok": True, "id": worker_id})
            else:
                self._json({"error": f"Worker {worker_id} nicht gefunden"}, 404)
        else:
            self._json({"error": "Method not allowed"}, 405)


def start_control_api():
    try:
        from hub._services.chat.slots_config import initialize_system_slots
        initialize_system_slots()
        # Reconcile any frozen running worker states from previous process runs
        try:
            reconcile_workers(active_worker_ids=_active_worker_ids())
        except Exception as e:
            log.warning("Konnte Worker beim Start nicht abgleichen: %s", e)

        bind_host = _control_bind_host()
        server = QuietHTTPServer((bind_host, CONTROL_PORT), ControlHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        actual_port = int(server.server_port)
        log.info("Control API auf %s:%s", bind_host, actual_port)
        print(f"Web-Dashboard: http://localhost:{actual_port}/")
        return server
    except (OSError, ValueError) as e:
        log.warning(f"Control API konnte nicht starten: {e}")
        return None


def verify_telegram_token() -> bool:
    """Verifiziert den Bot ohne Token oder Request-URL in Fehlerlogs offenzulegen."""
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
            timeout=8.0,
        )
    except httpx.HTTPError:
        log.error("Telegram-Verifikation nicht erreichbar")
        return False
    if response.status_code != 200:
        log.error("Telegram-Verifikation abgelehnt (HTTP %s)", response.status_code)
        return False
    try:
        payload = response.json()
    except ValueError:
        log.error("Telegram-Verifikation lieferte kein gültiges JSON")
        return False
    return bool(payload.get("ok") and payload.get("result", {}).get("id"))


def serve_control_only(server, reason: str) -> None:
    """Keep local Chat/Control available when the Telegram connector is offline."""
    message = f"{reason}; lokaler Chat/Control läuft im Offlinebetrieb weiter."
    log.warning(message)
    print(message)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def should_disable_telegram_bot() -> tuple[bool, str]:
    """Prüft, ob der Telegram-Bot auf diesem Host deaktiviert werden soll (z. B. Remote-Modus,
    Laptop-Client oder explizite Konfiguration), um einen 2. konkurrierenden Bot zu verhindern."""
    disable_env = os.environ.get("BACH_DISABLE_TELEGRAM_BOT", "").strip().lower()
    if disable_env in ("1", "true", "yes", "on"):
        return True, "Telegram-Bot per BACH_DISABLE_TELEGRAM_BOT deaktiviert"

    remote_host = os.environ.get("BACH_REMOTE_HOST", "").strip().lower()
    if remote_host and remote_host not in ("", "0", "false", "off", "local", "none"):
        return True, f"Telegram-Bot deaktiviert: Remote-Host aktiv ({remote_host})"

    bot_host = os.environ.get("BACH_TELEGRAM_BOT_HOST", "").strip().lower()
    if bot_host and bot_host not in (socket.gethostname().lower(), "localhost", "127.0.0.1"):
        return True, f"Telegram-Bot deaktiviert: Host ({socket.gethostname()}) ist nicht Bot-Host ({bot_host})"

    if CONFIG.get("telegram", {}).get("disabled") is True:
        return True, "Telegram-Bot in Konfiguration deaktiviert"

    return False, ""


def register_handlers(app) -> None:
    """Registriert ALLE Telegram-Handler - jeder gewrappt mit
    _require_owner() (Befund C: 14 von 19 Handlern hatten frueher gar
    keinen Owner-Check). Eigene Funktion statt Inline-Code in main(),
    damit ein Test die ECHTE Registrierung ausfuehren und pruefen kann,
    statt eine von Hand gepflegte Kopie der Handler-Liste zu bewachen."""
    app.add_handler(CommandHandler("start", _require_owner(cmd_start)))
    app.add_handler(CommandHandler("clear", _require_owner(cmd_clear)))
    app.add_handler(CommandHandler("think", _require_owner(cmd_think)))
    app.add_handler(CommandHandler("nothink", _require_owner(cmd_nothink)))
    app.add_handler(CommandHandler("mode", _require_owner(cmd_mode)))
    app.add_handler(CommandHandler("model", _require_owner(cmd_model)))
    app.add_handler(CommandHandler("backend", _require_owner(cmd_backend)))
    app.add_handler(CommandHandler("maxrounds", _require_owner(cmd_maxrounds)))
    app.add_handler(CommandHandler("settings", _require_owner(cmd_settings)))
    app.add_handler(CommandHandler("fackel", _require_owner(cmd_fackel)))

    if HAS_BACH:
        app.add_handler(CommandHandler("remember", _require_owner(cmd_remember)))
        app.add_handler(CommandHandler("recall", _require_owner(cmd_recall)))
        app.add_handler(CommandHandler("facts", _require_owner(cmd_facts)))
        app.add_handler(CommandHandler("bach", _require_owner(cmd_bach)))
        app.add_handler(CommandHandler("task", _require_owner(cmd_task)))
        app.add_handler(CommandHandler("tasks", _require_owner(cmd_tasks)))
        app.add_handler(CommandHandler("status", _require_owner(cmd_status)))

    app.add_handler(CommandHandler("voice", _require_owner(cmd_voice)))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _require_owner(handle_voice)))
    app.add_handler(MessageHandler(filters.PHOTO, _require_owner(handle_photo)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _require_owner(handle_message)))


def main():
    global TELEGRAM_VERIFIED
    control_server = start_control_api()
    if control_server is None:
        print("Chat/Control konnte nicht gestartet werden.")
        return 1

    # Crash recovery: resume any compute jobs stopped by a previous bot session
    if HAS_COMPUTE_LOCK and CONFIG.get("compute_lock", {}).get("enabled", False):
        try:
            resumed = recover_paused_jobs()
            if resumed:
                log.info("Crash recovery: resumed PIDs %s", resumed)
                print(f"Compute Lock: {len(resumed)} Jobs nach Crash resumed: {resumed}")
            else:
                print("Compute Lock: kein Crash-Recovery noetig")
        except Exception as e:
            log.warning("Crash recovery failed: %s", e)

    disabled, reason = should_disable_telegram_bot()
    if disabled:
        serve_control_only(control_server, reason)
        return 0

    if not BOT_TOKEN:
        serve_control_only(control_server, "Kein Telegram-Bot-Token")
        return 0
    if not verify_telegram_token():
        serve_control_only(control_server, "Telegram-Bot konnte nicht verifiziert werden")
        return 0
    TELEGRAM_VERIFIED = True
    print("Telegram Bot verifiziert")

    app = Application.builder().token(BOT_TOKEN).build()
    register_handlers(app)

    backend_type = CONFIG["backend"].get("type", "ollama")
    model = backend.get_default_model()
    cl_status = "AN" if _compute_lock_enabled() else "AUS"
    print(
        f"BACH Telegram Chat gestartet "
        f"(BACH: {'JA' if HAS_BACH else 'NEIN'}, "
        f"Backend: {backend_type}, Modell: {model}, Think: AN, "
        f"Compute-Lock: {cl_status})"
    )
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        control_server.shutdown()
        control_server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
