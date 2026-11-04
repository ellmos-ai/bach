#!/usr/bin/env python3
"""
BACH Unified System Tray

Cross-platform (macOS/Windows/Linux) System Tray für das BACH OS.
Steuert: Chat-Backend, Services, Prompts (PromptBoard), Idle Worker.

Voraussetzungen:
  pip install pystray Pillow

Start:
  python chat_tray.py [--port 8081] [--host lead.example]
  BACH_IDLE_WORKER=0  -> Host startet keinen neuen Always-On-Lauf
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
from pathlib import Path

# BACH system path: resolve from this file's location (system/hub/_services/chat/)
_here = Path(__file__).resolve()
_system_dir = str(_here.parents[3])
_root_dir = str(_here.parents[4])
for _p in (_system_dir, _root_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hub.bach_paths import BACH_DB
from hub._services.chat.control_auth import get_control_api_auth_header
from hub._services.chat.tray_worker_execution import NativeWorkerObserver, WORKER_ID

try:
    from hub._services.recurring.recurring_tasks import check_recurring_tasks
    HAS_RECURRING = True
except ImportError:
    HAS_RECURRING = False

if sys.stdout is None:
    try:
        _tray_log_dir = Path.home() / ".bach"
        _tray_log_dir.mkdir(parents=True, exist_ok=True)
        _tray_log_file = open(_tray_log_dir / "chat_tray.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = _tray_log_file
        sys.stderr = _tray_log_file
    except Exception:
        pass

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        sys.stderr.reconfigure(encoding='utf-8')
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode


class _NoWorkerRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Benötigt: pip install pystray Pillow")
    sys.exit(1)

DEFAULT_PROMPTS = {
    "Aufgaben": {
        "Offene Tasks zeigen": "Zeige alle offenen Tasks sortiert nach Priorität",
        "Tagesplan erstellen": "Erstelle einen Tagesplan basierend auf meinen offenen Tasks und Prioritäten",
        "Nächste Aufgabe": "Was ist die wichtigste Aufgabe die ich als nächstes erledigen sollte?",
    },
    "System": {
        "Systemstatus": "Gib einen Überblick über den aktuellen BACH-Systemstatus",
        "Wartungscheck": "Führe einen Wartungscheck durch: DB-Größe, Logs, offene Issues",
        "Übersetzungen prüfen": "Prüfe die Qualität der Übersetzungen in der Datenbank und berichte Probleme",
    },
    "Wissen": {
        "Memory durchsuchen": "Durchsuche mein Memory nach: ",
        "Zusammenfassung": "Fasse die letzten Aktivitäten und Änderungen zusammen",
        "Facts abrufen": "Zeige alle gespeicherten Facts",
    },
}

PROMPTBOARD_LIBRARY_ENV = "BACH_PROMPTBOARD_LIBRARY"
PROMPTBOARD_APP_ENV = "BACH_PROMPTBOARD_APP"
TRAY_LOCK_FILE = Path.home() / ".bach" / "chat_tray.lock"


def _is_terminal_parked(task) -> bool:
    """Fuer den idle-worker terminal (nicht neu aufziehbar), wenn der Task
    erledigt (completed_at), geparkt (status='blocked') oder an eine zukuenftige
    due_date gebunden ist. Ohne jeden dieser Marker greift der alte
    completed_at-Einzelzweig unveraendert (Rueckwaerts-kompatibel).

    T-20260912-1240loop / #1235 4x-Claim / #1293 Option A: der Terminal-Waechter
    pruefte nur completed_at, sodass geparkte Gate-Tasks (kein completed_at, da
    NICHT fertig) nach 300s-Client-Timeout auf 'open' zurueckgesetzt und erneut
    claimt wurden (Resurrektions-Loop).
    """
    if not isinstance(task, dict):
        return False
    if task.get("completed_at"):
        return True
    if task.get("status") in ("blocked", "done", "completed", "cancelled"):
        return True
    # 5. Pfad (T-20260915-1235loop): due_date kann beim Claim-Zyklus auf None
    # gesetzt werden (reopen/clear_fields). claimed_by ist der robuste Marker
    # fuer "in Bearbeitung" — auch wenn due_date verloren geht.
    if task.get("claimed_by") and task.get("status") in ("in_progress", "blocked"):
        return True
    due = task.get("due_date")
    if due:
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(str(due).replace("Z", ""))
            if d.tzinfo is not None:
                d = d.replace(tzinfo=None)
            return d > _dt.now()
        except Exception:
            return False
    return False


def _has_task_completion_receipt(response, task_id) -> bool:
    """Only a matching tool-confirmed ID can complete an Always-On run."""
    if not isinstance(response, dict) or response.get("ok") is not True:
        return False
    ids = response.get("completed_task_ids", [])
    return isinstance(ids, list) and any(type(tid) is int and tid == task_id for tid in ids)


def _pending_fields(pending):
    """Felder des idle_pending-Tupels inkl. exakter Send-chat_id (#1303).

    Der Send-Pfad (_process_idle_task) schickt den Task-Prompt an
    'idle-{role_id}-{task_id}'; der Settle-Pfad (_settle_pending_task) pollte
    vor #1303 hartkodiert 'idle-task-{task_id}' -- eine chat_id, an die NIE
    gesendet wurde. Jede Idle-Session >300s Client-Timeout endete so als
    "ohne Antwort oder Transkript" (PATH A), obwohl die Antwort im
    Transkript der echten Send-chat_id lag (Evidenz: chat_tray.py.bak-universal
    -- vorm Universal-Worker-Refaktor nutzten BEIDE Pfade einheitlich
    'idle-task-{id}', der Refaktor aenderte nur den Send-Pfad).

    Neu: das Tupel traegt die Send-chat_id als 4. Element. Rueckgabe:
    (task_id, seit, title, chat_id). Legacy-Tupel (2/3 Elemente, nur waehrend
    des Deploy-Fensters moeglich) fallen defensiv auf den alten Praefix
    zurueck.
    """
    if not pending:
        return None, 0.0, "", ""
    p = tuple(pending)
    if len(p) >= 4:
        return p[0], p[1], p[2], p[3]
    if len(p) >= 3:
        return p[0], p[1], p[2], f"idle-task-{p[0]}"
    return p[0], p[1], f"Task #{p[0]}", f"idle-task-{p[0]}"


def acquire_single_instance_lock(lock_path: Path = TRAY_LOCK_FILE):
    """Return an open, exclusively locked handle -- or None if another tray holds it.

    Single-instance contract for the tray: the lock is an OS-held byte-range
    (Windows, msvcrt) or flock (POSIX) lock on an open handle, so the OS drops it
    when the holder dies. A crashed tray therefore never leaves a stale lock
    behind, and no PID guessing is needed. Keep the returned handle alive for
    the tray's whole lifetime.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def mark_tray_ready(icon):
    """Publish readiness only after pystray starts its event loop."""
    icon.visible = True
    receipt = os.environ.get("BACH_STARTSPINE_READY_RECEIPT", "")
    launch_id = os.environ.get("BACH_STARTSPINE_LAUNCH_ID", "")
    if not receipt or not launch_id:
        return
    target = Path(receipt)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"launch_id": launch_id, "pid": os.getpid()}) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def get_tray_device_token() -> str:
    """Resolve the device token for tray GUI access.

    Checks environment variable, explicit or default token file, and OS keyring.
    """
    token = str(os.environ.get("BACH_DEVICE_TOKEN_TRAY") or os.environ.get("BACH_DEVICE_TOKEN") or "").strip()
    if token:
        return token
    token_file = str(os.environ.get("BACH_DEVICE_TOKEN_FILE") or "").strip()
    if token_file:
        try:
            return Path(token_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            pass
    default_file = Path.home() / ".credentials" / "bach_device_token_tray"
    if default_file.exists():
        try:
            return default_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            pass
    try:
        from hub.secrets_handler import get_secret_value
        return str(get_secret_value("bach_device_token_tray") or "").strip()
    except Exception:
        return ""


class BACHTray:

    POLL_INTERVAL = 5
    IDLE_THRESHOLD = 1  # Always-On prüft direkt; kein Leerlauf- oder Sitzungsfenster
    IDLE_CHAT_ID = "idle-worker"
    PENDING_TTL = 1800   # Legacy-Metadatum; Ablauf beweist kein physisches Ende.

    def __init__(self, host="127.0.0.1", port=8081, gui_port=8000,
                 ollama_host="127.0.0.1", remote=False,
                 activity_url=None, gui_url=None, brand="bach", execution_state_path=None):
        self.brand = (brand or "bach").lower()
        self.host = host
        self.remote = remote
        self.base_url = f"http://{host}:{port}"
        self.control_api_auth_header = get_control_api_auth_header()
        self.gui_url = (
            gui_url
            or os.environ.get("BACH_GUI_URL")
            or f"http://{host}:{gui_port}"
        )
        tray_token = get_tray_device_token()
        self.gui_auth_header = f"Bearer {tray_token}" if tray_token else None
        self.activity_url = (
            activity_url
            or os.environ.get("BACH_ACTIVITY_URL")
            or f"{self.gui_url}/agenten/running"
        )
        self.ollama_url = f"http://{ollama_host}:11434"
        self.telegram_url = "https://t.me/bach_assistant_bot"
        self.state = {
            "backend": "?",
            "backend_cli": "",
            "model": "?",
            "mode": "safe",
            "think": True,
            "bach": False,
            "sessions": 0,
            "connected": False,
            "max_tool_rounds": 12,
            "fackel_preference": "compute",
            "current_tool": "",
            "last_tools": [],
            "ram_claiming": {"loaded_models": [], "claimed_gib": 0.0},
        }
        self.backends = {}
        self.models = []
        self.slots = {}
        self.dynamic_workers = []
        self.icon = None
        self._stop = threading.Event()

        self.services = {"gui": False, "control": False, "ollama": False}
        self.permissions = {
            "system_tools": True,
            "browser_control": True,
            "camera": False,
            "microphone": False,
            "screen_capture": False,
            "voice_tts": True,
            "speech_to_text": True,
            "smarthome_robotics": False,
            "ollama": True,
        }
        self.talk_config = {
            "persona": "buddha",
            "operating_mode": "ptt",
            "primary_model": "qwen3.8:27b-mlx",
            "fast_relay_model": "smollm2:360m",
            "summon_policy": "knock",
        }

        # Idle-Worker ist per Default aktiv (deaktivierbar via BACH_IDLE_WORKER=0)
        self.idle_enabled = not remote and os.environ.get("BACH_IDLE_WORKER", "1").strip().lower() not in ("0", "false", "no", "off")
        self.idle_consecutive = 0
        self.idle_task_name = None
        self.idle_processing = False
        self.idle_pending = None   # Unbestätigte Legacy-Aufrufe bleiben gesperrt.
        self._idle_run_lock = threading.Lock()
        endpoint_key = hashlib.sha256(self.base_url.encode("utf-8")).hexdigest()[:24]
        intent_path = execution_state_path or (
            Path.home() / ".bach" / f"{self.brand}_worker_{endpoint_key}.json")
        self._native_worker = NativeWorkerObserver(
            self.base_url, intent_path, lambda *args: self._worker_request(*args))
        self._recurring_tick = 0

        self.max_status_failures = 3
        self._failed_status_count = 0
        self.prompt_source = "defaults"
        self.favorite_prompts = {}
        self.modular_status = {}
        self.modular_standalone_count = 0
        self._reload_modular_status()
        self.prompts = self._load_prompts()

    # --- API ---

    def _api(self, method, path, body=None, base=None, timeout=8):
        target_base = base or self.base_url
        url = target_base + path
        data = json.dumps(body).encode() if body else None
        headers = {"Content-Type": "application/json"} if data else {}
        if self.control_api_auth_header and target_base == self.base_url:
            headers["Authorization"] = self.control_api_auth_header
        elif self.gui_auth_header and target_base == self.gui_url:
            headers["Authorization"] = self.gui_auth_header
        req = urllib.request.Request(
            url, data=data, method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _worker_request(self, method, path, body=None):
        """Return status and JSON without redirects, retries or GUI fallback."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.control_api_auth_header:
            headers["Authorization"] = self.control_api_auth_header
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers=headers)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoWorkerRedirect())
        try:
            try:
                response = opener.open(request, timeout=8)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                code = response.code
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                return code, None
            value = json.loads(data.decode("utf-8"))
            return code, value if isinstance(value, dict) else None
        except (urllib.error.URLError, OSError, ValueError):
            return None, None

    def _check_url(self, url, timeout=2):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    @staticmethod
    def _safe_worker_execution(worker_id, execution):
        if not isinstance(execution, dict):
            return None
        if (execution.get("schema") != "bach.worker-execution.v1"
                or execution.get("worker_id") != worker_id
                or execution.get("state") not in {
                    "idle", "starting", "running", "stopping", "finishing", "terminal", "unconfirmed"
                }
                or type(execution.get("terminal")) is not bool):
            return None
        safe = {"schema": execution["schema"], "worker_id": worker_id,
                "state": execution["state"], "terminal": execution["terminal"]}
        for key in ("service_instance", "start_request_id", "generation"):
            value = execution.get(key)
            if value is None and key != "service_instance":
                safe[key] = None
            elif isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value):
                safe[key] = value
            else:
                return None
        heartbeat = execution.get("heartbeat_at")
        if heartbeat is not None:
            if not isinstance(heartbeat, str) or len(heartbeat) > 40 or "\x00" in heartbeat:
                return None
            try:
                datetime.datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
            except ValueError:
                return None
            safe["heartbeat_at"] = heartbeat
        error_code = execution.get("error_code")
        if isinstance(error_code, str) and re.fullmatch(r"[a-z0-9_:-]{1,64}", error_code):
            safe["error_code"] = error_code
        task_id = execution.get("active_task_id")
        if type(task_id) is int and task_id > 0:
            safe["active_task_id"] = task_id
            holder = execution.get("lease_worker_id")
            if (safe["state"] == "running" and safe["terminal"] is False
                    and isinstance(holder, str)
                    and re.fullmatch(r"worker-[0-9a-f]{32}@[A-Za-z0-9][A-Za-z0-9._-]{0,63}", holder)):
                safe["lease_worker_id"] = holder
        provider_request = BACHTray._safe_provider_request(
            execution.get("provider_request"),
            generation=safe.get("generation"),
            execution_state=safe["state"],
            execution_terminal=safe["terminal"],
            active_task_id=safe.get("active_task_id"),
        )
        if provider_request is not None:
            safe["provider_request"] = provider_request
        return safe

    @staticmethod
    def _safe_provider_request(request, *, generation, execution_state,
                               execution_terminal, active_task_id=None):
        """Project only typed lifecycle metadata into the tray DTO."""
        if not isinstance(request, dict):
            return None
        request_id = request.get("request_id")
        request_generation = request.get("generation")
        task_id = request.get("task_id")
        if (not isinstance(request_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", request_id)
                or not isinstance(request_generation, str)
                or request_generation != generation
                or not isinstance(request_generation, str)
                or not re.fullmatch(r"[0-9a-f]{32}", request_generation)
                or type(task_id) is not int or task_id <= 0):
            return None
        request_state = request.get("state")
        phase = request.get("phase")
        phases = {
            "registered", "request_starting", "transport_open",
            "awaiting_response_headers", "response_headers_received",
            "first_stream_chunk_received", "response_completed",
            "request_aborted", "request_failed", "response_cleanup_complete",
            "client_cleanup_complete", "runtime_call_complete",
        }
        if (not isinstance(request_state, str) or request_state not in {"active", "terminal"}
                or not isinstance(phase, str) or phase not in phases):
            return None
        phase_at = request.get("phase_at")
        if not isinstance(phase_at, str) or len(phase_at) > 40 or "\x00" in phase_at:
            return None
        try:
            datetime.datetime.fromisoformat(phase_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        terminal_reasons = {
            "worker_stop", "total_deadline", "httpx_read_timeout", "provider_error",
            "backend_error", "backend_returned", "runtime_cancelled",
            "dispatch_rejected", "response_completed",
        }
        terminal_reason = request.get("terminal_reason")
        if (terminal_reason is not None
                and (not isinstance(terminal_reason, str) or terminal_reason not in terminal_reasons)):
            return None
        runtime_complete = request.get("runtime_call_complete")
        if type(runtime_complete) is not bool:
            return None
        if request_state == "terminal":
            if (not runtime_complete or phase != "runtime_call_complete"
                    or execution_state in {"idle", "starting"}):
                return None
        else:
            if (runtime_complete or phase == "runtime_call_complete"
                    or execution_state not in {"running", "stopping", "finishing"}):
                return None
        if execution_terminal and request_state != "terminal":
            return None
        if active_task_id is not None and active_task_id != task_id:
            return None
        transport = request.get("transport")
        if not isinstance(transport, str) or transport not in {"ollama_httpx", "unavailable"}:
            return None
        details_available = request.get("transport_details_available")
        cancellation_supported = request.get("cancellation_supported")
        if (type(details_available) is not bool or type(cancellation_supported) is not bool
                or details_available != (transport == "ollama_httpx")
                or cancellation_supported != (transport == "ollama_httpx")):
            return None
        fence_available = request.get("task_fence_available")
        task_fence = request.get("task_fence")
        if type(fence_available) is not bool:
            return None
        if fence_available:
            if type(task_fence) is not int or task_fence <= 0:
                return None
        elif task_fence is not None:
            return None
        bool_fields = ("cancel_requested", "observer_error")
        if any(type(request.get(key)) is not bool for key in bool_fields):
            return None
        cleanup_values = {}
        for key in ("response_cleanup_complete", "client_cleanup_complete"):
            value = request.get(key)
            if value is not None and type(value) is not bool:
                return None
            cleanup_values[key] = value
        return {
            "request_id": request_id,
            "generation": request_generation,
            "task_id": task_id,
            "task_fence": task_fence,
            "task_fence_available": fence_available,
            "state": request_state,
            "phase": phase,
            "phase_at": phase_at,
            "terminal_reason": terminal_reason,
            "transport": transport,
            "transport_details_available": details_available,
            "cancellation_supported": cancellation_supported,
            "cancel_requested": request["cancel_requested"],
            "response_cleanup_complete": cleanup_values["response_cleanup_complete"],
            "client_cleanup_complete": cleanup_values["client_cleanup_complete"],
            "runtime_call_complete": runtime_complete,
            "observer_error": request["observer_error"],
        }

    @staticmethod
    def _persistent_cloud_profile(worker):
        if not isinstance(worker, dict):
            return False
        backend, model = worker.get("backend"), worker.get("model")
        if not isinstance(model, str) or not model.strip():
            return False
        return (backend in {"ollama-cloud", "openrouter"}
                or backend == "ollama" and model.lower().endswith(":cloud"))

    def _dynamic_worker_start_enabled(self, worker):
        if (self.state.get("connected") is not True
                or not isinstance(worker, dict)
                or worker.get("runtime_verified") is not True
                or worker.get("worker_active") is not False
                or worker.get("running") is not False
                or worker.get("enabled") is not True
                or worker.get("status") not in {"idle", "error", "completed"}):
            return False
        pause = worker.get("pause_info")
        if isinstance(pause, dict) and pause.get("is_paused") is True:
            return False
        execution = worker.get("execution")
        if execution is not None:
            execution = self._safe_worker_execution(worker.get("id"), execution)
            if execution is None or execution["state"] not in {"idle", "terminal"}:
                return False
            if execution["state"] == "terminal" and execution["terminal"] is not True:
                return False
        return True

    def _persistent_worker_toggle_enabled(self, worker):
        if not isinstance(worker, dict):
            return False
        if worker.get("persistent_opt_in") is True:
            return True
        return (self._dynamic_worker_start_enabled(worker)
                and worker.get("type") in {"continuous", "persistent"}
                and self._persistent_cloud_profile(worker))

    def _worker_runtime_lines(self, worker):
        if not isinstance(worker, dict) or worker.get("runtime_verified") is not True:
            return ["Laufstatus: nicht geprüft", "Generation: nicht bestätigt",
                    "Task: unbekannt", "Heartbeat: unbekannt"]
        execution = self._safe_worker_execution(worker.get("id"), worker.get("execution"))
        active = worker.get("worker_active")
        running = worker.get("running")
        if execution is not None:
            state = execution["state"]
            if state == "running" and active is True:
                runtime = "läuft"
            elif state == "starting" and active is True:
                runtime = "Start wird geprüft"
            elif state in {"stopping", "finishing"} and active is True:
                runtime = "Beendigung läuft"
            elif state == "terminal" and execution["terminal"] is True:
                runtime = "beendet"
            elif state == "idle" and active is False and running is False:
                runtime = "bereit"
            elif state == "unconfirmed" or active is None or running is None:
                runtime = "nicht bestätigt"
            else:
                runtime = "widersprüchlicher Status"
            generation = execution.get("generation")
            generation_label = (f"letzte Generation {generation[:8]}" if state == "terminal"
                                else f"Generation {generation[:8]}" if generation
                                else "keine aktive Generation")
            heartbeat = execution.get("heartbeat_at")
            heartbeat_label = (heartbeat[:19].replace("T", " ") if heartbeat else "unbekannt")
            error_code = execution.get("error_code")
            error_label = f"Fehlercode: {error_code}" if error_code else None
            active_task_id = execution.get("active_task_id")
        else:
            runtime = "bereit" if active is False and running is False else "nicht bestätigt"
            generation_label = "keine aktive Generation" if active is False else "Generation unbekannt"
            heartbeat_label = "unbekannt"
            error_label = None
            active_task_id = None
        task_label = f"aktive Task #{active_task_id}" if type(active_task_id) is int and active_task_id > 0 else (
            "keine aktive Task" if running is False else "Task unbekannt")
        lines = [f"Laufstatus: {runtime}", f"{generation_label}", f"Task: {task_label}",
                 f"Heartbeat: {heartbeat_label}"]
        queue_status = worker.get("queue_status")
        outcome = queue_status.get("outcome") if isinstance(queue_status, dict) else None
        if outcome in {"empty_queue", "selection_excluded", "acquire_denied", "selection_error"}:
            lines.append(f"Wartegrund: {outcome}")
        if error_label:
            lines.append(error_label)
        return lines

    def _toggle_persistent_worker_action(self, worker_id):
        def action(*_):
            if self.state.get("connected") is not True:
                self._notify_error("Controlstatus nicht bestätigt; Dauerstart bleibt unverändert")
                return
            endpoint = "/api/workers/configuration?" + urlencode({"id": worker_id})
            current = self._api("GET", endpoint)
            if (not isinstance(current, dict) or current.get("ok") is not True
                    or current.get("id") != worker_id
                    or not isinstance(current.get("configuration_version"), str)
                    or type(current.get("persistent_opt_in")) is not bool):
                self._notify_error("Dauerstart konnte nicht sicher gelesen werden")
                return
            desired = not current["persistent_opt_in"]
            if desired:
                profile = next((w for w in self.dynamic_workers if w.get("id") == worker_id), None)
                if not self._persistent_worker_toggle_enabled({**(profile or {}), "persistent_opt_in": False}):
                    self._notify_error("Dauerstart ist für dieses Profil derzeit nicht verfügbar")
                    return
            result = self._api("POST", "/api/workers/configuration", {
                "id": worker_id,
                "configuration_version": current["configuration_version"],
                "changes": {"persistent_opt_in": desired},
            })
            if (not isinstance(result, dict) or result.get("ok") is not True
                    or result.get("persistent_opt_in") is not desired):
                self._notify_error("Dauerstart konnte nicht bestätigt werden")
                return
            if self.icon:
                self.icon.notify("Dauerstart geändert", "BACH Worker")
            self._refresh()
            self._update_icon()
        return action

    def _refresh(self):
        status = self._api("GET", "/api/status", timeout=8)
        if status and "backend" in status:
            self._failed_status_count = 0
            self.state.update(status)
            self.state["connected"] = True
        else:
            self._failed_status_count += 1
            if self._failed_status_count >= self.max_status_failures:
                self.state["connected"] = False

        bs = self._api("GET", "/api/backends")
        if bs and not bs.get("error"):
            self.backends = bs

        ms = self._api("GET", "/api/models")
        if ms and "models" in ms:
            self.models = ms["models"]

        slots_resp = self._api("GET", "/api/slots")
        if slots_resp and slots_resp.get("ok"):
            self.slots = slots_resp.get("slots", {})
            workers = slots_resp.get("dynamic_workers", [])
            runtime_response = self._api("GET", "/api/workers")
            runtime_by_id = {}
            if (isinstance(runtime_response, dict) and runtime_response.get("ok") is True
                    and isinstance(runtime_response.get("workers"), list)):
                runtime_by_id = {w.get("id"): w for w in runtime_response["workers"]
                                 if isinstance(w, dict) and isinstance(w.get("id"), str)}
            self.dynamic_workers = []
            for source in workers if isinstance(workers, list) else []:
                if not isinstance(source, dict) or not isinstance(source.get("id"), str):
                    continue
                worker = dict(source)
                live = runtime_by_id.get(worker["id"])
                verified = (isinstance(live, dict) and live.get("runtime_verified") is True
                            and type(live.get("worker_active")) is bool
                            and type(live.get("running")) is bool)
                worker["runtime_verified"] = verified
                worker["worker_active"] = live.get("worker_active") if verified else None
                worker["running"] = live.get("running") if verified else None
                worker["queue_status"] = live.get("queue_status") if verified else None
                worker["execution"] = (self._safe_worker_execution(worker["id"], live.get("execution"))
                                        if verified else None)
                worker["runtime_status"] = live.get("status") if verified else None
                worker["persistent_opt_in"] = worker.get("persistent_opt_in") is True
                self.dynamic_workers.append(worker)
            if "fackel_preference" in slots_resp:
                self.state["fackel_preference"] = slots_resp["fackel_preference"]

        self.services["control"] = self.state["connected"]
        self.services["gui"] = self._check_url(self.gui_url + "/")
        self.services["ollama"] = self._check_url(self.ollama_url + "/api/tags")
        if self.services["ollama"]:
            ps_resp = self._api("GET", "/api/ps", base=self.ollama_url, timeout=2)
            models_ps = ps_resp.get("models", []) if isinstance(ps_resp, dict) else []
            names_ps = [str(m.get("name") or m.get("model") or "").strip() for m in models_ps if isinstance(m, dict) and (m.get("name") or m.get("model"))]
            bytes_ps = sum(int(m.get("size_vram") or m.get("size") or 0) for m in models_ps if isinstance(m, dict) and isinstance(m.get("size_vram") or m.get("size"), (int, float)))
            self.state["ram_claiming"] = {"loaded_models": names_ps, "claimed_gib": round(bytes_ps / (1024 ** 3), 1) if bytes_ps > 0 else 0.0}

        if not self.remote and ("fackel_preference" not in self.state or not self.state.get("fackel_preference")):
            try:
                from hub.compute_lock import get_fackel_preference
                self.state["fackel_preference"] = get_fackel_preference()
            except Exception:
                self.state.setdefault("fackel_preference", "compute")
        elif not self.remote and not self.state.get("connected"):
            try:
                from hub.compute_lock import get_fackel_preference
                pref = get_fackel_preference()
                if pref in ("ollama", "compute"):
                    self.state["fackel_preference"] = pref
            except Exception:
                pass

    # --- PromptBoard ---

    def _promptboard_project_dirs(self):
        dirs = []
        # 1. Plan D canonical local dev repos
        local_dev = Path(os.environ.get("LOCAL_DEV_REPOS", r"C:\_Local_DEV\repos"))
        for repo_name in (
            "promptboard",
            "PromptBoard",
            "REL-PUB_PromptBoard-tasksolver-1136-1137",
            "REL-PUB_PromptBoard",
        ):
            p = local_dev / repo_name
            if p.exists() and p not in dirs:
                dirs.append(p)

        # 2. OneDrive software directories
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            for sub in ("DATA", "LLM"):
                for folder in ("REL-PUB_PromptBoard", "PromptBoard"):
                    p = (
                        Path(user_profile)
                        / "OneDrive"
                        / ".TOPICS"
                        / ".SOFTWARE"
                        / sub
                        / folder
                    )
                    if p.exists() and p not in dirs:
                        dirs.append(p)
        return dirs

    def _promptboard_project_dir(self):
        dirs = self._promptboard_project_dirs()
        return dirs[0] if dirs else None

    def _promptboard_library_candidates(self):
        candidates = []
        env_path = os.environ.get(PROMPTBOARD_LIBRARY_ENV)
        if env_path:
            candidates.append(Path(env_path).expanduser())

        candidates.append(Path.home() / ".promptboard" / "library.json")

        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "PromptBoard" / "library.json")

        for project_dir in self._promptboard_project_dirs():
            for sub in (
                project_dir / "library.json",
                project_dir / "data" / "library.json",
                project_dir / "_tmp_accessibility_check" / "library.json",
            ):
                if sub not in candidates:
                    candidates.append(sub)

        return candidates

    def _promptboard_app_candidates(self):
        candidates = []
        env_path = os.environ.get(PROMPTBOARD_APP_ENV)
        if env_path:
            candidates.append(Path(env_path).expanduser())

        for project_dir in self._promptboard_project_dirs():
            dist_dir = project_dir / "dist"
            if dist_dir.exists():
                candidates.extend(
                    sorted(
                        dist_dir.glob("PromptBoard-*-win64.exe"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                )
            releases_dir = project_dir / "releases"
            if releases_dir.exists():
                candidates.extend(
                    sorted(
                        releases_dir.glob("**/PromptBoard-*-win64.exe"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                )
            store_dir = project_dir / "store_package"
            if store_dir.exists():
                candidates.extend(
                    sorted(
                        store_dir.glob("**/PromptBoard-*-win64.exe"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                )
            candidates.extend([
                project_dir / "start.bat",
                project_dir / "releases" / "PromptBoard.msix",
            ])
        return candidates

    def _promptboard_app_path(self):
        for candidate in self._promptboard_app_candidates():
            if candidate.exists():
                return candidate
        return None

    def _coerce_prompt_mapping(self, payload):
        if not isinstance(payload, dict):
            return {}

        # BACH tray native format: {"Kategorie": {"Name": "Prompt"}}
        native = {}
        for category, prompts in payload.items():
            if not isinstance(prompts, dict):
                continue
            clean_prompts = {
                str(name): str(text)
                for name, text in prompts.items()
                if str(name).strip() and str(text).strip()
            }
            if clean_prompts:
                native[str(category) or "Prompts"] = clean_prompts
        if native:
            return native

        # PromptBoard library.json format: {"items": [{name, content, category, item_type}]}
        items = payload.get("items")
        if not isinstance(items, list):
            return {}

        imported = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            content = str(item.get("content") or "").strip()
            if not name or not content:
                continue
            category = str(item.get("category") or item.get("item_type") or "PromptBoard").strip()
            imported.setdefault(category or "PromptBoard", {})[name] = content
        return imported

    def _read_prompt_file(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return self._coerce_prompt_mapping(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _make_prompt_preview(self, text: str, max_len: int = 70) -> str:
        """Create a clean, single-line preview string for prompt menus."""
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(cleaned) > max_len:
            return cleaned[:max_len - 3] + "..."
        return cleaned

    def _load_db_prompts(self):
        """Load curated prompts and favorites from BACH's canonical database (prompt_templates)."""
        db_path = BACH_DB
        if not db_path.is_file():
            return {}
        try:
            with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name, text, category, tags FROM prompt_templates WHERE text IS NOT NULL AND text != ''"
                )
                db_prompts = {}
                fav_prompts = {}
                for name, text, category, tags in cursor.fetchall():
                    cat = (category.strip() if category and category.strip() else "BACH")
                    name_str = str(name).strip()
                    text_str = str(text).strip()
                    db_prompts.setdefault(cat, {})[name_str] = text_str
                    tags_lower = (str(tags) if tags else "").lower()
                    if any(f in tags_lower for f in ("favorite", "favorit", "star", "pinned")):
                        fav_prompts[name_str] = {
                            "text": text_str,
                            "category": cat,
                            "preview": self._make_prompt_preview(text_str),
                        }
                if fav_prompts:
                    self.favorite_prompts = fav_prompts
                return db_prompts
        except Exception:
            return {}

    def _ensure_initial_favorites(self, prompts):
        """Seed favorites from available prompts if no explicit favorites are marked yet."""
        if self.favorite_prompts:
            return
        favs = {}
        for cat, p_map in prompts.items():
            for name, text in p_map.items():
                favs[name] = {
                    "text": text,
                    "category": cat,
                    "preview": self._make_prompt_preview(text),
                }
                if len(favs) >= 4:
                    break
            if len(favs) >= 4:
                break
        self.favorite_prompts = favs

    def _load_prompts(self):
        config_dir = os.path.expanduser("~/.config/bach")
        prompts_path = Path(config_dir) / "prompts.json"
        prompts = self._read_prompt_file(prompts_path)
        if prompts:
            self.prompt_source = str(prompts_path)
            self._ensure_initial_favorites(prompts)
            return prompts

        for candidate in self._promptboard_library_candidates():
            prompts = self._read_prompt_file(candidate)
            if prompts:
                self.prompt_source = str(candidate)
                self._ensure_initial_favorites(prompts)
                return prompts

        db_prompts = self._load_db_prompts()
        if db_prompts:
            self.prompt_source = "bach_db"
            self._ensure_initial_favorites(db_prompts)
            return db_prompts

        self.prompt_source = "defaults"
        self._ensure_initial_favorites(DEFAULT_PROMPTS)
        return DEFAULT_PROMPTS

    def _reload_prompts(self, *_):
        self.favorite_prompts = {}
        self.prompts = self._load_prompts()
        if self.icon:
            fav_count = len(self.favorite_prompts)
            total_count = sum(len(p) for p in self.prompts.values())
            self.icon.notify(f"{fav_count} Favoriten, {total_count} Prompts geladen", "BACH Prompts")
            self._update_icon()

    def _reload_modular_status(self):
        try:
            from hub._services.ocean_stack_bridge import ocean_modularized_services_status
            self.modular_status = ocean_modularized_services_status()
            self.modular_standalone_count = sum(1 for v in self.modular_status.values() if v.get("standalone"))
        except Exception:
            self.modular_status = {}
            self.modular_standalone_count = 0

    def _trigger_modules_sync(self, icon=None, item=None):
        try:
            from hub._services.ocean_stack_bridge import auto_switch_to_standalone_modules
            auto_switch_to_standalone_modules()
            self._reload_modular_status()
            if self.icon:
                self.icon.menu = self._build_menu()
                self.icon.notify(f"Module synchronisiert ({self.modular_standalone_count}/12 aktiv)", "BACH Module")
        except Exception:
            pass

    def _build_modular_status_menu_items(self):
        items = []
        count = self.modular_standalone_count
        total = max(12, len(self.modular_status))
        items.append(pystray.MenuItem(f"Status: {count}/{total} aktiv (Standalone-Modus)", None, enabled=False))
        items.append(pystray.MenuItem("🔄 Modul-Sync ausführen (bach update modules --sync)", self._trigger_modules_sync))
        items.append(pystray.Menu.SEPARATOR)
        if self.modular_status:
            for mod_name, info in sorted(self.modular_status.items()):
                status_icon = "✅" if info.get("standalone") else "⚠️"
                st = "standalone" if info.get("standalone") else info.get("status", "legacy")
                items.append(pystray.MenuItem(f"{status_icon} {mod_name} ({st})", None, enabled=False))
        else:
            items.append(pystray.MenuItem("(Keine Modul-Daten)", None, enabled=False))
        return items

    def modular_status_smoke_snapshot(self):
        return {
            "standalone_count": self.modular_standalone_count,
            "total_modularized": len(self.modular_status),
            "modules": {k: v.get("status") for k, v in self.modular_status.items()},
            "auto_update_ready": True,
        }

    def promptboard_smoke_snapshot(self):
        app_path = self._promptboard_app_path()
        library_candidates = []
        for candidate in self._promptboard_library_candidates():
            library_candidates.append({
                "path": str(candidate),
                "exists": candidate.exists(),
            })

        prompt_count = sum(len(prompts) for prompts in self.prompts.values())
        return {
            "app_path": str(app_path) if app_path else None,
            "app_found": app_path is not None,
            "library_candidates": library_candidates,
            "library_found": any(item["exists"] for item in library_candidates),
            "menu_has_open_app": app_path is not None,
            "prompt_source": self.prompt_source,
            "using_default_prompts": self.prompt_source == "defaults",
            "prompt_categories": list(self.prompts.keys()),
            "prompt_count": prompt_count,
            "favorite_count": len(self.favorite_prompts),
            "modular_standalone_count": self.modular_standalone_count,
        }

    def _copy_to_clipboard(self, text):
        try:
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
            elif sys.platform == "win32":
                subprocess.run(["clip"], input=text.encode("utf-16le"), check=False)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"],
                               input=text.encode("utf-8"), check=False)
            if self.icon:
                self.icon.notify("In Zwischenablage kopiert", "BACH Prompt")
        except FileNotFoundError:
            pass

    def _send_prompt(self, prompt):
        result = self._api("POST", "/api/chat", {
            "prompt": prompt,
            "chat_id": "tray-prompt",
        }, timeout=300)
        answer = (result or {}).get("answer", "")[:120]
        if not self.icon:
            return
        if result and result.get("ok"):
            self.icon.notify(answer, "BACH Antwort")
        else:
            # Ein gefangener Backend-Fehler liefert seit T-20260906-743610852
            # ok=False, traegt die Ursache aber im Antworttext. Die anzeigen,
            # statt sie gegen ein nacktes "fehlgeschlagen" zu tauschen.
            self.icon.notify(answer or "Senden fehlgeschlagen", "BACH Fehler")

    def _make_prompt_copy_action(self, text):
        def action(*_):
            self._copy_to_clipboard(text)
        return action

    def _make_prompt_send_action(self, text):
        def action(*_):
            threading.Thread(target=self._send_prompt, args=(text,), daemon=True).start()
        return action

    def _make_prompt_open_chat_action(self, text):
        def action(*_):
            self._copy_to_clipboard(text)
            import webbrowser
            webbrowser.open(f"{self.gui_url}/chat")
            if self.icon:
                self.icon.notify("Prompt kopiert & Chat geöffnet", "BACH Prompt")
        return action

    # --- Idle Worker ---

    def _always_on_can_start(self):
        slot = self.slots.get(WORKER_ID)
        if (self.remote or not self.idle_enabled or self.state.get("connected") is not True
                or not isinstance(slot, dict) or slot.get("id") != WORKER_ID
                or slot.get("enabled") is not True):
            return False
        pause = slot.get("pause_info")
        # Unattended pickup is local only. Cloud starts require a user action.
        return (slot.get("backend") in {"ollama", "lmstudio"}
                and ":cloud" not in str(slot.get("model") or "").lower()
                and isinstance(pause, dict) and pause.get("is_paused") is False)

    def _idle_tick(self):
        if self.remote or self.idle_processing:
            return
        # A logged-in or open foreground session does not disarm Always-On.
        # Disabled/cooling slots are still observed to settle owned starts.
        if self._always_on_can_start():
            self._recurring_tick += 1
        if self._always_on_can_start() and HAS_RECURRING and self._recurring_tick % 180 == 0:
            try:
                check_recurring_tasks()
            except Exception:
                pass
        threading.Thread(target=self._process_idle_task, daemon=True).start()

    def _settle_pending_task(self) -> bool:
        """Legacy chat/history cannot prove the physical caller has ended.

        Retain an unknown pre-migration call for controlled deployment drain;
        neither elapsed time, TaskDB status nor model text authorizes restart.
        """
        return not self.idle_pending

    def _is_blocked_by_dep(self, task) -> bool:
        """Prueft fail-closed, ob ein Kandidat auf unerledigte Vorgaenger wartet.

        Die Task-API liefert ``is_blocked_by_dep``. Fehlt das Feld (aeltere
        server.py) und hat der Task ``depends_on``, wird der Detail-Endpunkt
        gefragt; laesst sich der Status nicht klaeren, gilt der Task als
        blockiert, damit der Idle-Worker nicht auf fehlenden Vorarbeiten aufbaut.
        """
        if not isinstance(task, dict):
            return False
        if "is_blocked_by_dep" in task:
            return bool(task.get("is_blocked_by_dep"))
        if not str(task.get("depends_on") or "").strip():
            return False
        tid = task.get("id")
        if not tid:
            return True
        detail = self._api("GET", f"/api/tasks/{tid}", base=self.gui_url)
        if isinstance(detail, dict) and "is_blocked_by_dep" in detail:
            return bool(detail.get("is_blocked_by_dep"))
        return True

    def _process_idle_task(self):
        if not self._settle_pending_task():
            return
        if not self._idle_run_lock.acquire(blocking=False):
            return
        self.idle_processing = True
        try:
            slot = self.slots.get(WORKER_ID, {})
            request_stop = not self.remote and (
                not self.idle_enabled or isinstance(slot, dict) and slot.get("enabled") is False)
            self._native_worker.step(allow_start=self._always_on_can_start(), request_stop=request_stop)
        except Exception:
            # Observation failure is not a task failure or permission to retry.
            self._native_worker.status = "unconfirmed"
            self._native_worker.execution = None
            print("[Always-On] Laufstatus nicht bestätigt; kein erneuter Start")
        finally:
            self.idle_processing = False
            self.idle_task_name = None
            self.idle_consecutive = 0
            self._idle_run_lock.release()
            self._update_icon()

    # --- Icons ---

    def _make_icon(self, color):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill=color)
        try:
            if sys.platform == "darwin":
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
            elif sys.platform == "win32":
                font = ImageFont.truetype("arial", 32)
            else:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
            letter = "O" if getattr(self, "brand", "bach") == "ocean" else "B"
            offset_x = 13 if letter == "O" else 14
            draw.text((offset_x, 10), letter, fill="white", font=font)
        except OSError:
            letter = "O" if getattr(self, "brand", "bach") == "ocean" else "B"
            offset_x = 14 if letter == "O" else 16
            draw.text((offset_x, 14), letter, fill="white")
        return img

    @property
    def _icon_image(self):
        if self._always_on_runtime_label(self.slots.get(WORKER_ID, {})).startswith("Running"):
            return self._make_icon((90, 120, 220, 255))  # actual native inference
        if self.state["connected"]:
            if self.state.get("mode") == "full":
                return self._make_icon((255, 165, 0, 255))  # orange = full
            return self._make_icon((0, 200, 100, 255))  # green = connected safe
        return self._make_icon((180, 40, 40, 255))  # red = disconnected

    # --- Menu ---

    def _build_menu(self):
        items = []
        always_status_str = self._always_on_runtime_label(
            self.slots.get("buddha_always_on", {})
        )
        target_label = "Ziel: Server (Tunnel)" if self.remote else "Ziel: Lokal"
        items.append(pystray.MenuItem(target_label, None, enabled=False))

        # ── Status ──
        if self.state["connected"]:
            mode_str = (self.state.get("mode") or "safe").upper()
            think_str = "AN" if self.state.get("think") else "AUS"
            items.append(pystray.MenuItem(
                f"Modus: {mode_str} | Denken: {think_str}", None, enabled=False,
            ))
            items.append(pystray.Menu.SEPARATOR)

            chat_slot = self.slots.get("buddha_chat", {})
            always_slot = self.slots.get("buddha_always_on", {})
            conn_slot = self.slots.get("buddha_connector", {})

            chat_model = chat_slot.get("model") or self.state.get("model", "?")
            chat_backend = chat_slot.get("backend") or "ollama"
            chat_rounds = chat_slot.get("max_tool_rounds", 12)
            chat_mode = chat_slot.get("mode", "safe")
            chat_think = chat_slot.get("think", True)

            always_model = always_slot.get("model") or "qwen3.8:27b-mlx"
            always_backend = always_slot.get("backend") or "ollama"
            always_rounds = always_slot.get("max_tool_rounds", 25)
            always_mode = always_slot.get("mode", "full")
            always_status_str = self._always_on_runtime_label(always_slot)

            conn_model = conn_slot.get("model") or "qwen3.8:27b-mlx"
            conn_backend = conn_slot.get("backend") or "ollama"
            conn_rounds = conn_slot.get("max_tool_rounds", 10)

            # Deine Agenten (Direkte Modell-Bindung & Claim-Klassen 1-4)
            items.append(
                pystray.MenuItem(
                    "🤖 Deine Agenten (Modell-Bindung & Claim)",
                    None,
                    enabled=False,
                )
            )
            # Agent 1: Buddha Chat (Klasse 1 = Interaktiv)
            chat_subitems = [
                pystray.MenuItem(
                    "Claim-Klasse: 1 · Direkt interaktiv (höchster Modell-Vorrang)",
                    None,
                    enabled=False,
                )
            ]
            if self.models:
                chat_model_items = [
                    pystray.MenuItem(m, self._make_slot_model_action("buddha_chat", m),
                                     checked=lambda item, m=m, s=chat_model: m == s)
                    for m in self.models[:15]
                ]
                chat_subitems.append(pystray.MenuItem(f"Modell-Bindung: {chat_model}", pystray.Menu(*chat_model_items)))

            chat_backend_items = [
                pystray.MenuItem(name.capitalize(), self._make_slot_backend_action("buddha_chat", name),
                                 checked=lambda item, n=name, b=chat_backend: n.lower() == b.lower())
                for name in self.backends.keys()
            ]
            if chat_backend_items:
                chat_subitems.append(pystray.MenuItem(f"Backend: {chat_backend}", pystray.Menu(*chat_backend_items)))

            chat_round_items = [
                pystray.MenuItem("Unbegrenzt" if v == 0 else f"{v} Turns",
                                 self._make_slot_rounds_action("buddha_chat", v),
                                 checked=lambda item, v=v, cr=chat_rounds: cr == v)
                for v in [5, 10, 12, 15, 20, 0]
            ]
            chat_subitems.append(pystray.MenuItem(f"Max Turns: {'Unbegrenzt' if chat_rounds == 0 else chat_rounds}", pystray.Menu(*chat_round_items)))
            chat_subitems.append(pystray.MenuItem("Safe-Modus", self._make_slot_mode_action("buddha_chat", "safe"),
                                                  checked=lambda item, cm=chat_mode: cm == "safe"))
            chat_subitems.append(pystray.MenuItem("Full-Modus", self._make_slot_mode_action("buddha_chat", "full"),
                                                  checked=lambda item, cm=chat_mode: cm == "full"))
            chat_subitems.append(pystray.MenuItem("Denkmodus", lambda *_: self._toggle_slot_think("buddha_chat"),
                                                  checked=lambda item, ct=chat_think: ct))
            items.append(pystray.MenuItem(f"💬 Buddha Chat [Klasse 1]: {chat_model}", pystray.Menu(*chat_subitems)))

            # Agent 2: Buddha Always-On (Klasse 4 = Autonomer Hintergrund)
            always_subitems = [
                pystray.MenuItem(
                    "Claim-Klasse: 4 · Autonomer Hintergrund (pausiert für Klassen 1–3)",
                    None,
                    enabled=False,
                )
            ]
            if self.models:
                always_model_items = [
                    pystray.MenuItem(m, self._make_slot_model_action("buddha_always_on", m),
                                     checked=lambda item, m=m, s=always_model: m == s)
                    for m in self.models[:15]
                ]
                always_subitems.append(pystray.MenuItem(f"Modell-Bindung: {always_model}", pystray.Menu(*always_model_items)))

            always_backend_items = [
                pystray.MenuItem(name.capitalize(), self._make_slot_backend_action("buddha_always_on", name),
                                 checked=lambda item, n=name, b=always_backend: n.lower() == b.lower())
                for name in self.backends.keys()
            ]
            if always_backend_items:
                always_subitems.append(pystray.MenuItem(f"Backend: {always_backend}", pystray.Menu(*always_backend_items)))

            always_round_items = [
                pystray.MenuItem("Unbegrenzt" if v == 0 else f"{v} Turns",
                                 self._make_slot_rounds_action("buddha_always_on", v),
                                 checked=lambda item, v=v, ar=always_rounds: ar == v)
                for v in [10, 20, 25, 30, 50, 0]
            ]
            always_subitems.append(pystray.MenuItem(f"Max Turns: {'Unbegrenzt' if always_rounds == 0 else always_rounds}", pystray.Menu(*always_round_items)))
            always_subitems.append(pystray.MenuItem("Full-Modus (Schreibrechte)", self._make_slot_mode_action("buddha_always_on", "full"),
                                                    checked=lambda item, am=always_mode: am == "full"))
            always_subitems.append(pystray.MenuItem("Safe-Modus", self._make_slot_mode_action("buddha_always_on", "safe"),
                                                    checked=lambda item, am=always_mode: am == "safe"))
            act_text = self.idle_task_name or always_slot.get("current_activity") or "Wartet auf Leerlauf"
            always_subitems.append(pystray.MenuItem(f"Aktivität: {act_text[:35]}", None, enabled=False))
            items.append(pystray.MenuItem(f"⚡ Buddha Always-On [Klasse 4 · {always_status_str}]: {always_model}", pystray.Menu(*always_subitems)))

            # Agent 3: Buddha Connector (Klasse 2 = Delegierter Vordergrund / Messaging)
            conn_subitems = [
                pystray.MenuItem(
                    "Claim-Klasse: 2 · Delegierter Auftrag / Messaging",
                    None,
                    enabled=False,
                )
            ]
            if self.models:
                conn_model_items = [
                    pystray.MenuItem(m, self._make_slot_model_action("buddha_connector", m),
                                     checked=lambda item, m=m, s=conn_model: m == s)
                    for m in self.models[:15]
                ]
                conn_subitems.append(pystray.MenuItem(f"Modell-Bindung: {conn_model}", pystray.Menu(*conn_model_items)))

            conn_backend_items = [
                pystray.MenuItem(name.capitalize(), self._make_slot_backend_action("buddha_connector", name),
                                 checked=lambda item, n=name, b=conn_backend: n.lower() == b.lower())
                for name in self.backends.keys()
            ]
            if conn_backend_items:
                conn_subitems.append(pystray.MenuItem(f"Backend: {conn_backend}", pystray.Menu(*conn_backend_items)))

            conn_round_items = [
                pystray.MenuItem(f"{v} Turns", self._make_slot_rounds_action("buddha_connector", v),
                                 checked=lambda item, v=v, cr=conn_rounds: cr == v)
                for v in [5, 10, 15, 20]
            ]
            conn_subitems.append(pystray.MenuItem(f"Max Turns: {conn_rounds}", pystray.Menu(*conn_round_items)))
            conn_subitems.append(pystray.MenuItem("Telegram öffnen", self._open_telegram))
            items.append(pystray.MenuItem(f"📱 Buddha Connector [Klasse 2]: {conn_model}", pystray.Menu(*conn_subitems)))

            # Agent 4: Buddha Talk / Funkgerät (Klasse 1 = Interaktiv · ellmos-talk Live-Stimme & Modell-Summon)
            tcfg = getattr(self, "talk_config", {}) or {}
            talk_persona = tcfg.get("persona", "buddha")
            talk_op_mode = tcfg.get("operating_mode", "ptt")
            talk_primary_model = tcfg.get("primary_model") or chat_model
            talk_summon = tcfg.get("summon_policy", "knock")
            op_labels = {
                "ptt": "Funkgerät · PTT",
                "duplex": "Live-Duplex",
                "wake_word": "Wake-Word",
                "off": "Aus",
            }
            talk_mode_str = op_labels.get(talk_op_mode, "Funkgerät · PTT")
            talk_subitems = [
                pystray.MenuItem(
                    "Claim-Klasse: 1 · Direkt interaktiv (Sprachkanal)",
                    None,
                    enabled=False,
                ),
                pystray.MenuItem("🎙️ Begleitfenster öffnen (Companion)", self._open_talk_companion),
                pystray.MenuItem("⚡ In Living & Running konfigurieren...", self._open_talk_running),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    f"Betriebsart: {talk_mode_str}",
                    pystray.Menu(
                        pystray.MenuItem(
                            "📻 Funkgerät (Push-to-Talk)",
                            self._make_talk_config_action("operating_mode", "ptt"),
                            checked=lambda item, m=talk_op_mode: m == "ptt",
                        ),
                        pystray.MenuItem(
                            "🎙️ Live-Duplex (Freisprechen)",
                            self._make_talk_config_action("operating_mode", "duplex"),
                            checked=lambda item, m=talk_op_mode: m == "duplex",
                        ),
                        pystray.MenuItem(
                            "👂 Wake-Word („Hey Buddha“)",
                            self._make_talk_config_action("operating_mode", "wake_word"),
                            checked=lambda item, m=talk_op_mode: m == "wake_word",
                        ),
                        pystray.MenuItem(
                            "⏸️ Aus",
                            self._make_talk_config_action("operating_mode", "off"),
                            checked=lambda item, m=talk_op_mode: m == "off",
                        ),
                    ),
                ),
                pystray.MenuItem(
                    f"Persona / Agenten-Bindung: {talk_persona.capitalize()}",
                    pystray.Menu(
                        pystray.MenuItem(
                            "🧘 Buddha (Lokal)",
                            self._make_talk_config_action("persona", "buddha"),
                            checked=lambda item, p=talk_persona: p == "buddha",
                        ),
                        pystray.MenuItem(
                            "🟣 Claude (Opus / Sonnet)",
                            self._make_talk_config_action("persona", "claude"),
                            checked=lambda item, p=talk_persona: p == "claude",
                        ),
                        pystray.MenuItem(
                            "🔵 Gemini (Antigravity)",
                            self._make_talk_config_action("persona", "gemini"),
                            checked=lambda item, p=talk_persona: p == "gemini",
                        ),
                        pystray.MenuItem(
                            "🟢 Codex (GPT)",
                            self._make_talk_config_action("persona", "codex"),
                            checked=lambda item, p=talk_persona: p == "codex",
                        ),
                    ),
                ),
                pystray.MenuItem(
                    f"Modell-Eigenstart: {talk_summon}",
                    pystray.Menu(
                        pystray.MenuItem(
                            "🔔 Funkgerät-Anklopfen (Header-Signal)",
                            self._make_talk_config_action("summon_policy", "knock"),
                            checked=lambda item, sp=talk_summon: sp == "knock",
                        ),
                        pystray.MenuItem(
                            "⚡ Auto-Popup (bei Präsenz via Sensation)",
                            self._make_talk_config_action("summon_policy", "auto_popup"),
                            checked=lambda item, sp=talk_summon: sp == "auto_popup",
                        ),
                        pystray.MenuItem(
                            "🔕 Stumm (Kein Modell-Anruf)",
                            self._make_talk_config_action("summon_policy", "muted"),
                            checked=lambda item, sp=talk_summon: sp == "muted",
                        ),
                    ),
                ),
            ]
            items.append(
                pystray.MenuItem(
                    f"📻 Buddha Talk [{talk_mode_str}]: {talk_primary_model}",
                    pystray.Menu(*talk_subitems),
                )
            )

            # Dynamic Workers Submenu
            workers_subitems = []
            for w in self.dynamic_workers:
                wid = w.get("id", "worker")
                wname = w.get("name", wid)
                wstatus = w.get("status", "idle")
                wmodel = w.get("model", "?")
                wturns = w.get("max_tool_rounds", 20)
                wrole = w.get("role", "General")
                persistent_label = "Dauerstart: an" if w.get("persistent_opt_in") is True else "Dauerstart: aus"

                if self._dynamic_worker_start_enabled(w):
                    start_item = pystray.MenuItem("▶ Starten", self._run_worker_action(wid))
                else:
                    start_item = pystray.MenuItem("Start gesperrt: Laufstatus/Profil prüfen", None, enabled=False)

                w_actions = [
                    pystray.MenuItem(f"Rolle: {wrole} | {wturns} Turns", None, enabled=False),
                    pystray.MenuItem(f"Profilstatus: {wstatus}", None, enabled=False),
                    pystray.MenuItem(persistent_label, None, enabled=False),
                    *[pystray.MenuItem(line, None, enabled=False) for line in self._worker_runtime_lines(w)],
                    start_item,
                    pystray.MenuItem(
                        "Dauerstart beim Control-Neustart",
                        self._toggle_persistent_worker_action(wid),
                        checked=lambda item, w=w: w.get("persistent_opt_in") is True,
                        enabled=lambda item, w=w: self._persistent_worker_toggle_enabled(w),
                    ),
                    pystray.MenuItem("▶ Fortsetzen" if wstatus == "paused" else "⏸ Pausieren",
                                     self._toggle_worker_action(wid, wstatus)),
                    pystray.MenuItem("🗑 Worker löschen", self._delete_worker_action(wid)),
                ]
                workers_subitems.append(pystray.MenuItem(f"{wname} [Profil: {wstatus}] ({wmodel})", pystray.Menu(*w_actions)))

            if workers_subitems:
                workers_subitems.append(pystray.Menu.SEPARATOR)
            workers_subitems.append(pystray.MenuItem("+ Neuer Worker... (Web GUI)", self._open_running))
            items.append(pystray.MenuItem(f"🛠 Dynamische Worker ({len(self.dynamic_workers)})", pystray.Menu(*workers_subitems)))

            items.append(pystray.Menu.SEPARATOR)

            # RAM-Distributor & Modell-Runtime (Ressourcen-Priorität)
            fackel_label = self._fackel_runtime_label()
            ram_claim = self.state.get("ram_claiming") or {}
            loaded_models = ram_claim.get("loaded_models") or []
            claimed_gib = ram_claim.get("claimed_gib") or 0.0
            ram_line = (
                f"RAM-Belegung: {len(loaded_models)} Modell(e) ({', '.join(loaded_models[:2])}) · {claimed_gib:.1f} GiB"
                if loaded_models
                else "RAM-Belegung: 0 Modelle im Speicher (0.0 GiB belegt)"
            )
            fackel_items = [
                pystray.MenuItem(
                    ram_line,
                    None,
                    enabled=False,
                ),
                pystray.MenuItem(
                    "Claim-Klassen: 1 Interaktiv → 2 Auftrag → 3 Termin → 4 Hintergrund",
                    None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Ollama / Chat & Worker bevorzugen",
                    lambda *_: self._set_fackel("ollama"),
                    checked=lambda item: self.state.get("fackel_preference", "compute") == "ollama",
                ),
                pystray.MenuItem(
                    "Rechenjobs bevorzugen (Compute)",
                    lambda *_: self._set_fackel("compute"),
                    checked=lambda item: self.state.get("fackel_preference", "compute") == "compute",
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "🔓 Modell & RAM jetzt für andere Prozesse freigeben (Compute-Vorrang + Unload)",
                    self._release_model_for_compute,
                ),
                pystray.MenuItem(
                    "📖 Doku: Modell- & RAM-Claiming öffnen (/help)",
                    self._open_claiming_docs,
                ),
            ]
            items.append(pystray.MenuItem(fackel_label, pystray.Menu(*fackel_items)))

            # Tool-Aktivität
            ct = self.state.get("current_tool", "")
            lt = self.state.get("last_tools", [])
            if ct:
                items.append(pystray.MenuItem(
                    f"Tool: {ct} (Runde {self.state.get('tool_round', 0)})",
                    None, enabled=False,
                ))
            elif lt:
                items.append(pystray.MenuItem(
                    f"Letzte Tools: {', '.join(lt)}",
                    None, enabled=False,
                ))

        else:
            items.append(pystray.MenuItem("Nicht verbunden", None, enabled=False))
            items.append(pystray.MenuItem(f"Versuche: {self.base_url}", None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)

        # ── Services ──
        svc_items = []
        svc_labels = {
            "gui": "GUI Dashboard (:8000)",
            "control": "Control API (:8081)",
            "ollama": "Ollama (:11434)",
        }
        for key, label in svc_labels.items():
            status_icon = "✅" if self.services.get(key) else "❌"
            svc_items.append(pystray.MenuItem(
                f"{status_icon} {label}", None, enabled=False,
            ))
        items.append(pystray.MenuItem("Services", pystray.Menu(*svc_items)))

        # ── Berechtigungen (Permissions Sub-Flyout, #3768) ──
        perm_labels = (
            ("system_tools", "System-Tools (Shell & Skripte)"),
            ("browser_control", "Browser-Steuerung"),
            ("camera", "Kamera (ellmos-sensation Präsenz)"),
            ("microphone", "Mikrofon (Wake-Word & Ambiente)"),
            ("screen_capture", "Bildschirmaufnahme (Open-Compute)"),
            ("voice_tts", "Sprachausgabe (Voice TTS / Talk)"),
            ("speech_to_text", "Spracheingabe (Diktat / STT)"),
            ("smarthome_robotics", "SmartHome & Robotik-Steuerung"),
            ("ollama", "Lokale Ollama-Modelle"),
        )
        perm_items = [
            pystray.MenuItem(
                label,
                self._make_permission_toggle_action(pkey),
                checked=lambda item, pkey=pkey: bool(self.permissions.get(pkey, False)),
            )
            for pkey, label in perm_labels
        ]
        items.append(pystray.MenuItem("🛡️ Berechtigungen (Permissions)", pystray.Menu(*perm_items)))

        # ── ⭐ Favoriten-Prompts (Schnellzugriff & Auto-Vorschau) ──
        fav_items = []
        if self.favorite_prompts:
            for fav_name, fav_data in self.favorite_prompts.items():
                f_text = fav_data["text"] if isinstance(fav_data, dict) else str(fav_data)
                f_preview = fav_data.get("preview") if isinstance(fav_data, dict) else self._make_prompt_preview(f_text)
                sub_items = [
                    pystray.MenuItem(f"🔍 \"{f_preview}\"", None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(f"📋 Kopieren", self._make_prompt_copy_action(f_text)),
                    pystray.MenuItem(f"▶ Direkt senden", self._make_prompt_send_action(f_text)),
                    pystray.MenuItem(f"💬 Im Chat öffnen (Entwurf)", self._make_prompt_open_chat_action(f_text)),
                ]
                fav_items.append(pystray.MenuItem(f"⭐ {fav_name}", pystray.Menu(*sub_items)))
        else:
            fav_items.append(pystray.MenuItem("(Keine Favoriten — in Bibliothek als ⭐ markieren)", None, enabled=False))

        fav_items.append(pystray.Menu.SEPARATOR)
        fav_items.append(pystray.MenuItem("📚 Prompt-Bibliothek (Web) öffnen", self._open_prompt_library))
        fav_items.append(pystray.MenuItem("🔄 Prompts neu laden", self._reload_prompts))
        items.append(pystray.MenuItem(f"⭐ Favoriten-Prompts ({len(self.favorite_prompts)})", pystray.Menu(*fav_items)))

        # ── 📦 Standalone-Module & Auto-Update Status ──
        mod_items = self._build_modular_status_menu_items()
        items.append(pystray.MenuItem(f"📦 Standalone-Module ({self.modular_standalone_count}/12 aktiv)", pystray.Menu(*mod_items)))

        # ── PromptBoard ──
        prompt_items = []
        app_path = self._promptboard_app_path()
        if app_path:
            prompt_items.append(pystray.MenuItem("PromptBoard App öffnen", self._open_promptboard))
        prompt_items.append(pystray.MenuItem("Prompt-Bibliothek (Web) öffnen", self._open_prompt_library))
        prompt_items.append(pystray.MenuItem("PromptBoard in BACH importieren", self._import_promptboard_action))
        prompt_items.append(pystray.MenuItem("Prompts nach PromptBoard exportieren", self._export_promptboard_action))
        prompt_items.append(pystray.Menu.SEPARATOR)
        for category, prompts in self.prompts.items():
            cat_items = []
            for name, text in prompts.items():
                preview = self._make_prompt_preview(text)
                prompt_subitems = [
                    pystray.MenuItem(f"🔍 \"{preview}\"", None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        f"\U0001F4CB {name}",
                        self._make_prompt_copy_action(text),
                    ),
                    pystray.MenuItem(
                        f"▶ Senden: {name}",
                        self._make_prompt_send_action(text),
                    ),
                    pystray.MenuItem(
                        f"💬 Im Chat öffnen: {name}",
                        self._make_prompt_open_chat_action(text),
                    ),
                ]
                cat_items.append(pystray.MenuItem(name, pystray.Menu(*prompt_subitems)))
            prompt_items.append(pystray.MenuItem(category, pystray.Menu(*cat_items)))
        if prompt_items:
            items.append(pystray.MenuItem("PromptBoard", pystray.Menu(*prompt_items)))

        items.append(pystray.Menu.SEPARATOR)

        # ── Always-On Worker ──
        idle_label = f"Buddha Always-On: {always_status_str}"
        idle_items = [
            pystray.MenuItem(
                "Buddha Always-On aktiviert",
                lambda *_: self._toggle_slot_enabled("buddha_always_on"),
                checked=lambda item: self.slots.get("buddha_always_on", {}).get("enabled") is True,
                enabled=self.state.get("connected") is True,
            ),
        ]
        if self.remote:
            idle_items.append(pystray.MenuItem("Einstellung wird auf dem verbundenen Server gespeichert", None, enabled=False))
        elif not self.idle_enabled:
            idle_items.append(pystray.MenuItem("Host-Worker durch BACH_IDLE_WORKER deaktiviert", None, enabled=False))
        idle_items.append(pystray.MenuItem(
            f"Aufgabenprüfung alle {self.POLL_INTERVAL}s · unabhängig von Chats",
            None, enabled=False,
        ))
        items.append(pystray.MenuItem(idle_label, pystray.Menu(*idle_items)))

        items.append(pystray.Menu.SEPARATOR)

        # ── Zugangswege ──
        gui_label = "Ocean Dashboard" if getattr(self, "brand", "bach") == "ocean" else "GUI Dashboard"
        items.append(pystray.MenuItem(gui_label, self._open_gui, default=True))
        chat_label = "Ocean Chat" if getattr(self, "brand", "bach") == "ocean" else "Buddha Chat"
        quick_items = [
            pystray.MenuItem(f"💬 {chat_label}", self._open_webchat),
            pystray.MenuItem("🎙️ ELLMOS Talk (Live-Stimme)", self._open_talk),
            pystray.MenuItem("🎙️ Sprach-Prompt aufnehmen (Chat-Handoff)", self._record_audio_prompt_action),
            pystray.MenuItem("⚡ Agenten · Running und Verlauf", self._open_running),
            pystray.MenuItem("📚 Agenten-Bibliothek · Vorlagen", self._open_blueprints),
            pystray.MenuItem("📖 Hilfe & Claim-Doku", self._open_claiming_docs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📱 Telegram", self._open_telegram),
        ]
        items.append(pystray.MenuItem("🧭 Direktzugriff (Seiten & Kanäle)", pystray.Menu(*quick_items)))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Beenden", self._quit))

        return pystray.Menu(*items)

    # --- Actions ---

    def _make_permission_toggle_action(self, key: str):
        def action(*_):
            new_val = not bool(self.permissions.get(key, False))
            result = self._api("POST", "/api/permissions", {"key": key, "enabled": new_val}, base=self.gui_url)
            confirmed = result.get("permissions") if isinstance(result, dict) else None
            if not isinstance(confirmed, dict) or confirmed.get(key) is not new_val:
                self._notify_error("Berechtigungsänderung")
                return
            self.permissions[key] = confirmed[key]
            self._update_icon()
        return action

    def _open_talk(self, *_):
        import webbrowser
        webbrowser.open(f"{self.gui_url}/talk")

    def _open_talk_companion(self, *_):
        import webbrowser
        webbrowser.open(f"{self.gui_url}/talk?companion=1")

    def _open_talk_running(self, *_):
        import webbrowser
        webbrowser.open(f"{self.gui_url}/agenten/running#talk-slot")

    def _make_talk_config_action(self, key: str, value: str):
        def action(*_):
            result = self._api("POST", "/api/talk/config", {key: value}, base=self.gui_url)
            cfg = result.get("config") if isinstance(result, dict) else None
            if isinstance(cfg, dict):
                self.talk_config.update(cfg)
            else:
                self.talk_config[key] = value
            self._update_icon()
        return action

    def _notify_error(self, action_name):
        if self.icon:
            self.icon.notify(f"{action_name} fehlgeschlagen", "BACH")

    def _make_backend_action(self, name):
        def action(*_):
            payload = {"name": name}
            if self.state.get("model") and self.models and self.state["model"] in self.models:
                payload["model"] = self.state["model"]
            result = self._api("POST", "/api/backend", payload)
            if result is None:
                self._notify_error(f"Backend → {name}")
            self._refresh()
            self._update_icon()
        return action

    def _make_model_action(self, model):
        def action(*_):
            result = self._api("POST", "/api/model", {"model": model})
            if result is None:
                self._notify_error(f"Modell → {model}")
            self._refresh()
            self._update_icon()
        return action

    def _set_mode(self, mode, *_):
        result = self._api("POST", "/api/mode", {"mode": mode})
        if result is None:
            self._notify_error(f"Modus → {mode}")
        self._refresh()
        self._update_icon()

    def _toggle_think(self, *_):
        new_val = not self.state["think"]
        result = self._api("POST", "/api/think", {"think": new_val})
        if result is None:
            self._notify_error("Think-Toggle")
        self._refresh()
        self._update_icon()

    def _make_rounds_action(self, rounds):
        def action(*_):
            result = self._api("POST", "/api/max_tool_rounds", {"rounds": rounds})
            if result is None:
                self._notify_error(f"Tool-Rounds → {rounds}")
            self._refresh()
            self._update_icon()
        return action

    def _set_fackel(self, pref, *_):
        result = self._api("POST", "/api/fackel", {"preference": pref})
        if result is None and not self.remote:
            try:
                from hub.compute_lock import set_fackel_preference
                set_fackel_preference(pref, quelle="tray")
                self.state["fackel_preference"] = pref
            except Exception:
                self._notify_error(f"Fackel → {pref}")
                return
        elif result is not None:
            self.state["fackel_preference"] = pref
        else:
            self._notify_error(f"Fackel → {pref}")
            return
        self._refresh()
        self._update_icon()
        if self.icon:
            label = "Ollama (Chat & Worker)" if pref == "ollama" else "Rechenjobs (Compute)"
            self.icon.notify(f"Fackel: {label} bevorzugt", "BACH")

    def _toggle_idle(self, *_):
        # Compatibility callback: the tray and GUI both change the persistent
        # Core-Agent setting; no process-local toggle can diverge from Running.
        self._toggle_slot_enabled("buddha_always_on")


    def _fackel_runtime_label(self):
        """Separate actual local inference ownership from its configured priority."""
        preference = self.state.get("fackel_preference")
        preferred = {"ollama": "Ollama", "compute": "Rechenjobs"}.get(preference, "nicht geprüft")
        turn = self.state.get("compute_turn")
        if (self.state.get("connected") is not True or not isinstance(turn, dict)
                or type(turn.get("active")) is not bool):
            owner = "Status nicht geprüft"
        elif not turn["active"]:
            owner = "lokale Inferenz frei"
        else:
            owner = {"foreground": "Chat", "background": "Hintergrundworker"}.get(
                turn.get("priority"), "lokale Inferenz belegt")
        return f"Fackel: {owner} · Priorität: {preferred}"

    def _always_on_runtime_label(self, slot):
        """Show configured Living state separately from live inference evidence."""
        if self.state.get("connected") is not True:
            return "Nicht verbunden · Status nicht geprüft"
        if not isinstance(slot, dict) or not slot:
            return "Status nicht geprüft"
        turn = self.state.get("compute_turn")
        if isinstance(turn, dict) and turn.get("active") is True:
            chat_id = str(turn.get("chat_id") or "")
            priority = turn.get("priority")
            if priority == "background" and chat_id == WORKER_ID:
                if slot.get("enabled") is not True:
                    return "Running · beendet aktuellen Schritt"
                if not self.remote and not self.idle_enabled:
                    return "Running · Hoststart deaktiviert"
                return "Running · bearbeitet eine Aufgabe"
        observer = getattr(self, "_native_worker", None)
        if not self.remote and observer is not None and observer.intent is not None:
            if observer.status in {"stopping", "finishing"}:
                return "Living · Beendigung läuft"
            if observer.status == "starting":
                return "Living · Start wird geprüft"
            if observer.status == "unconfirmed":
                return "Living · Laufstatus nicht bestätigt"
        if self.idle_pending:
            return "Living · Vorheriger Lauf nicht bestätigt"
        if slot.get("enabled") is not True:
            return "manuell pausiert"
        if not self.remote and not self.idle_enabled:
            return "Host-Worker deaktiviert"
        if isinstance(turn, dict) and turn.get("active") is True and turn.get("priority") == "foreground":
            return "Living · Chat hat den Rechenvorrang"
        pause = slot.get("pause_info")
        if isinstance(pause, dict) and pause.get("is_paused"):
            return f"automatische Pause · {pause.get('remaining_minutes', 0):g} min"
        if isinstance(turn, dict) and type(turn.get("active")) is bool:
            return "Living · aktiviert, wartet"
        return "Living · aktiviert; Laufstatus nicht geprüft"

    def _open_activity(self, *_):
        import webbrowser
        webbrowser.open(self.activity_url)

    def _open_running(self, *_):
        import webbrowser
        webbrowser.open(f"{self.gui_url}/agenten/running")

    def _open_blueprints(self, *_):
        import webbrowser
        webbrowser.open(f"{self.gui_url}/agenten/blueprints")

    def _open_claiming_docs(self, *_):
        import webbrowser
        webbrowser.open(f"{self.gui_url}/help?topic=claiming")

    def _release_model_for_compute(self, *_):
        self._set_fackel("compute")
        self._api("POST", "/api/slots", {"slot_id": "buddha_always_on", "updates": {"enabled": False}})
        loaded = (self.state.get("ram_claiming") or {}).get("loaded_models") or []
        target_models = list(dict.fromkeys([*loaded, self.state.get("model")]))
        for m in target_models:
            if m and m != "?":
                self._api("POST", "/api/generate", {"model": m, "keep_alive": 0}, base=self.ollama_url, timeout=3)
        self._refresh()
        self._update_icon()
        if self.icon:
            self.icon.notify("Modell & RAM für externe Prozesse freigegeben", "BACH")

    def _make_slot_model_action(self, slot_id, model):
        def action(*_):
            res = self._api("POST", "/api/slots", {"slot_id": slot_id, "updates": {"model": model}})
            if res is None or res.get("error"):
                self._notify_error(f"{slot_id} Modell → {model}")
            self._refresh()
            self._update_icon()
        return action

    def _make_slot_backend_action(self, slot_id, backend_name):
        def action(*_):
            res = self._api("POST", "/api/slots", {"slot_id": slot_id, "updates": {"backend": backend_name}})
            if res is None or res.get("error"):
                self._notify_error(f"{slot_id} Backend → {backend_name}")
            self._refresh()
            self._update_icon()
        return action

    def _make_slot_rounds_action(self, slot_id, rounds):
        def action(*_):
            res = self._api("POST", "/api/slots", {"slot_id": slot_id, "updates": {"max_tool_rounds": rounds}})
            if res is None or res.get("error"):
                self._notify_error(f"{slot_id} Turns → {rounds}")
            self._refresh()
            self._update_icon()
        return action

    def _make_slot_mode_action(self, slot_id, mode):
        def action(*_):
            res = self._api("POST", "/api/slots", {"slot_id": slot_id, "updates": {"mode": mode}})
            if res is None or res.get("error"):
                self._notify_error(f"{slot_id} Modus → {mode}")
            self._refresh()
            self._update_icon()
        return action

    def _toggle_slot_think(self, slot_id):
        slot = self.slots.get(slot_id, {})
        new_think = not slot.get("think", True)
        res = self._api("POST", "/api/slots", {"slot_id": slot_id, "updates": {"think": new_think}})
        if res is None or res.get("error"):
            self._notify_error(f"{slot_id} Think-Toggle")
        self._refresh()
        self._update_icon()

    def _toggle_slot_enabled(self, slot_id):
        if self.state.get("connected") is not True:
            self._notify_error(f"{slot_id}: Control API nicht verbunden; Einstellung bleibt unverändert")
            return
        slot = self.slots.get(slot_id, {})
        new_enabled = not slot.get("enabled", True)
        res = self._api("POST", "/api/slots", {"slot_id": slot_id, "updates": {"enabled": new_enabled}})
        if res is None or res.get("error"):
            self._notify_error(f"{slot_id} Status-Toggle")
        self._refresh()
        self._update_icon()

    def _run_worker_action(self, worker_id):
        def action(*_):
            res = self._api("POST", "/api/workers/run", {"id": worker_id})
            if res is None or res.get("error"):
                self._notify_error(f"Worker {worker_id} Start")
            elif self.icon:
                self.icon.notify(f"Worker {worker_id} gestartet", "BACH Worker")
            self._refresh()
            self._update_icon()
        return action

    def _toggle_worker_action(self, worker_id, current_status):
        def action(*_):
            new_status = "idle" if current_status == "paused" else "paused"
            res = self._api("POST", "/api/workers/toggle", {"id": worker_id, "status": new_status})
            if res is None or res.get("error"):
                self._notify_error(f"Worker {worker_id} Toggle")
            self._refresh()
            self._update_icon()
        return action

    def _delete_worker_action(self, worker_id):
        def action(*_):
            res = self._api("POST", "/api/workers/delete", {"id": worker_id})
            if res is None or res.get("error"):
                self._notify_error(f"Worker {worker_id} Löschen")
            elif self.icon:
                self.icon.notify(f"Worker {worker_id} gelöscht", "BACH Worker")
            self._refresh()
            self._update_icon()
        return action

    def _open_gui(self, *_):
        import webbrowser
        webbrowser.open(self.gui_url)

    def _open_webchat(self, *_):
        import webbrowser
        # The standalone webchat on :8080 went with the retired claude_bridge;
        # the working chat is the GUI page (plan item 1.1.6).
        webbrowser.open(f"{self.gui_url}/chat")

    def _open_prompt_library(self, *_):
        import webbrowser
        webbrowser.open(f"{self.gui_url}/prompt-library")

    def _open_promptboard(self, *_):
        app_path = self._promptboard_app_path()
        if not app_path:
            if self.icon:
                self.icon.notify("PromptBoard-App nicht gefunden", "BACH PromptBoard")
            return
        try:
            if sys.platform == "win32" and app_path.suffix.lower() in {".bat", ".msix", ".exe"}:
                os.startfile(str(app_path))
            else:
                subprocess.Popen(
                    [str(app_path)],
                    cwd=str(app_path.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except OSError:
            if self.icon:
                self.icon.notify("PromptBoard-Start fehlgeschlagen", "BACH PromptBoard")

    def _import_promptboard_action(self, *_):
        """Imports prompts from PromptBoard library.json into BACH DB."""
        try:
            from hub.prompt import PromptHandler
            handler = PromptHandler(_root_dir)
            _, result = handler.handle("import-promptboard", [])
            data = json.loads(result) if isinstance(result, str) and result.strip().startswith("{") else {}
            imported = data.get("imported", 0)
            skipped = data.get("skipped", 0)
            if self.icon:
                self.icon.notify(
                    f"PromptBoard-Import: {imported} neu, {skipped} bestehend.",
                    "BACH PromptBoard"
                )
            self.prompts = self._load_prompts()
            self._update_icon()
        except Exception as e:
            if self.icon:
                self.icon.notify(f"Import fehlgeschlagen: {e}", "BACH PromptBoard")

    def _export_promptboard_action(self, *_):
        """Exports prompts from BACH DB into PromptBoard library.json."""
        try:
            from hub.prompt import PromptHandler
            handler = PromptHandler(_root_dir)
            _, result = handler.handle("export-promptboard", [])
            data = json.loads(result) if isinstance(result, str) and result.strip().startswith("{") else {}
            exported = data.get("exported", 0)
            updated = data.get("updated", 0)
            total = data.get("total", 0)
            if self.icon:
                self.icon.notify(
                    f"PromptBoard-Export: {exported} neu, {updated} aktualisiert ({total} gesamt).",
                    "BACH PromptBoard"
                )
            self.prompts = self._load_prompts()
            self._update_icon()
        except Exception as e:
            if self.icon:
                self.icon.notify(f"Export fehlgeschlagen: {e}", "BACH PromptBoard")

    def _record_audio_prompt_action(self, *_):
        """Triggers audio prompt recording via ellmos-voice-io or speech interface handoff."""
        def record_worker():
            try:
                from hub._services.ocean_stack_bridge import load_voice_io_module
                mod = load_voice_io_module()
                voice = mod.VoiceIO()
                stt_ok, engine = voice.stt.available()
                if not stt_ok:
                    if self.icon:
                        self.icon.notify("Kein STT-Modul (Whisper/Vosk) installiert. Öffne Talk Web-GUI...", "BACH Sprach-Prompt")
                    import webbrowser
                    webbrowser.open(f"{self.gui_url}/talk")
                    return
                if self.icon:
                    self.icon.notify(f"STT aktiv ({engine}). Öffne Spracheingabe im Chat...", "BACH Sprach-Prompt")
                import webbrowser
                webbrowser.open(f"{self.gui_url}/chat?voice=1")
            except Exception as e:
                if self.icon:
                    self.icon.notify(f"Sprach-Interface: Öffne Talk ({e})...", "BACH Sprach-Prompt")
                import webbrowser
                webbrowser.open(f"{self.gui_url}/talk")

        threading.Thread(target=record_worker, daemon=True).start()

    def _open_telegram(self, *_):
        import webbrowser
        webbrowser.open(self.telegram_url)

    def _quit(self, *_):
        self._stop.set()
        if self.icon:
            self.icon.stop()

    def _update_icon(self):
        if self.icon:
            self.icon.icon = self._icon_image
            self.icon.menu = self._build_menu()

    def _menu_signature(self):
        worker_sig = tuple(
            (w.get("id"), w.get("status"), w.get("model"), w.get("current_activity"), w.get("max_tool_rounds"))
            for w in getattr(self, "dynamic_workers", [])
        )
        slot_sig = tuple(
            (k, v.get("model"), v.get("backend"), v.get("max_tool_rounds"), v.get("mode"), v.get("enabled"), v.get("current_activity"))
            for k, v in sorted(getattr(self, "slots", {}).items())
        )
        return (
            self.state.get("connected"),
            self.state.get("mode"),
            self.state.get("think"),
            self.state.get("fackel_preference"),
            self._fackel_runtime_label(),
            self._always_on_runtime_label(self.slots.get("buddha_always_on")),
            self.state.get("current_backend"),
            self.state.get("current_model"),
            len(getattr(self, "models", [])),
            getattr(self, "idle_task_name", None),
            getattr(self, "active_tool", None),
            worker_sig,
            slot_sig,
        )

    # --- Polling ---

    def _poll_loop(self):
        old_sig = self._menu_signature()
        while not self._stop.is_set():
            self._refresh()
            new_sig = self._menu_signature()
            if new_sig != old_sig:
                self._update_icon()
                old_sig = new_sig
            self._idle_tick()
            self._stop.wait(self.POLL_INTERVAL)

    # --- Run ---

    def run(self):
        self._refresh()
        app_name = f"{self.brand}-system" if hasattr(self, "brand") else "bach-system"
        app_title = "Open Ocean" if getattr(self, "brand", "bach") == "ocean" else "BACH System"
        self.icon = pystray.Icon(
            app_name,
            self._icon_image,
            app_title,
            self._build_menu(),
        )

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

        self.icon.run(setup=mark_tray_ready)


def main():
    parser = argparse.ArgumentParser(description="BACH Unified System Tray")
    parser.add_argument("--host", default="127.0.0.1", help="Control API Host")
    parser.add_argument("--port", type=int, default=8081, help="Control API Port")
    parser.add_argument("--gui-port", type=int, default=8000, help="Web-GUI Port")
    parser.add_argument("--activity-url", default=None, help="Konfigurierbare Aktivitätsanzeige-URL")
    parser.add_argument("--gui-url", default=None, help="Konfigurierbare GUI-URL")
    parser.add_argument("--ollama-host", default="127.0.0.1", help="Ollama Host")
    parser.add_argument("--remote", action="store_true", help="Remote-Client ohne lokale Schreib-Fallbacks")
    parser.add_argument("--brand", default="bach", choices=["bach", "ocean"], help="System tray branding (bach oder ocean)")
    parser.add_argument(
        "--smoke-promptboard",
        action="store_true",
        help="Print PromptBoard tray detection smoke data and exit",
    )
    args = parser.parse_args()

    tray = BACHTray(host=args.host, port=args.port, gui_port=args.gui_port,
                    ollama_host=args.ollama_host, remote=args.remote,
                    activity_url=args.activity_url, gui_url=args.gui_url,
                    brand=args.brand)
    if args.smoke_promptboard:
        print(json.dumps(tray.promptboard_smoke_snapshot(), ensure_ascii=False, indent=2))
        return
    lock_file = Path.home() / ".bach" / f"{args.brand}_tray.lock" if args.brand != "bach" else TRAY_LOCK_FILE
    lock = acquire_single_instance_lock(lock_file)
    if lock is None:
        print(f"BACH Tray ({args.brand}) läuft bereits (Single-Instance-Lock: {lock_file}).", file=sys.stderr)
        sys.exit(3)
    tray._instance_lock = lock  # keep the OS lock alive for the tray's lifetime
    tray.run()


if __name__ == "__main__":
    main()
