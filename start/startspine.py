#!/usr/bin/env python3
"""BACH Startspine: sichere, pfadunabhängige Prozess- und Portsteuerung.

Die Startspine verwaltet ausschließlich Runtime-Metadaten. Fachliche Daten und
deren Source of Truth bleiben unverändert in den jeweiligen BACH-Modulen.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import psutil
except ImportError:  # pragma: no cover - durch Runtime-Prüfung abgedeckt
    psutil = None


START_DIR = Path(__file__).resolve().parent
ROOT_DIR = START_DIR.parent
SYSTEM_DIR = ROOT_DIR / "system"
CHAT_DIR = SYSTEM_DIR / "hub" / "_services" / "chat"
SCHEMA_VERSION = 1
LOCAL_HOSTS = {"", "127.0.0.1", "localhost", "::1"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _runtime_dir() -> Path:
    override = os.environ.get("BACH_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "BACH" / "runtime"
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "bach" / "runtime"


def _paths() -> dict[str, Path]:
    runtime = _runtime_dir()
    return {
        "runtime": runtime,
        "state": runtime / "startspine.json",
        "discovery": runtime / "discovery.json",
        "lease": runtime / "startspine.lease",
        "logs": runtime / "logs",
        "receipts": runtime / "receipts",
        "specs": runtime / "specs",
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else (default or {})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default or {}


def _base_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(ROOT_DIR),
        "updated_at": _now(),
        "services": {},
    }


def _load_state() -> dict[str, Any]:
    state = _read_json(_paths()["state"], _base_state())
    state.setdefault("schema_version", SCHEMA_VERSION)
    state.setdefault("root", str(ROOT_DIR))
    state.setdefault("services", {})
    return state


def _save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _now()
    _atomic_json(_paths()["state"], state)


def _process_identity(pid: int | None) -> dict[str, Any] | None:
    if not pid or psutil is None:
        return None
    try:
        proc = psutil.Process(int(pid))
        return {
            "pid": proc.pid,
            "create_time": proc.create_time(),
            "name": proc.name(),
            "cmdline": proc.cmdline(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return None


def _identity_matches(pid: int | None, created: float | None) -> bool:
    identity = _process_identity(pid)
    if identity is None or created is None:
        return False
    return abs(float(identity["create_time"]) - float(created)) < 1.0


@contextmanager
def _operation_lease(timeout: float = 5.0):
    """Serialisiert mutierende Start/Stop-Aufrufe; fremde Locks werden nie gelöscht."""
    if psutil is None:
        raise RuntimeError("psutil fehlt; sichere Prozesszuordnung ist nicht möglich")
    paths = _paths()
    paths["runtime"].mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    identity = _process_identity(os.getpid())
    payload = {
        "pid": os.getpid(),
        "create_time": identity["create_time"] if identity else None,
        "created_at": _now(),
        "root": str(ROOT_DIR),
    }
    while True:
        try:
            fd = os.open(str(paths["lease"]), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            break
        except FileExistsError:
            existing = _read_json(paths["lease"])
            if existing and not _identity_matches(existing.get("pid"), existing.get("create_time")):
                try:
                    paths["lease"].unlink()
                except FileNotFoundError:
                    pass
                continue
            if not existing:
                try:
                    lease_age = time.time() - paths["lease"].stat().st_mtime
                except FileNotFoundError:
                    continue
                if lease_age > 10:
                    paths["lease"].unlink(missing_ok=True)
                    continue
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Startspine ist bereits aktiv (PID {existing.get('pid', '?')})"
                )
            time.sleep(0.1)
    try:
        yield
    finally:
        current = _read_json(paths["lease"])
        if current.get("pid") == os.getpid():
            paths["lease"].unlink(missing_ok=True)


def _url_ready(url: str, timeout: float = 1.0) -> bool:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _json_url(url: str, timeout: float = 1.0) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                return None
            payload = json.loads(response.read())
            return payload if isinstance(payload, dict) else None
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _chat_payload_ready(payload: dict[str, Any] | None) -> bool:
    return bool(
        payload
        and payload.get("service") == "bach-chat-control"
        and isinstance(payload.get("telegram_verified"), bool)
    )


def _ollama_payload_ready(payload: dict[str, Any] | None) -> bool:
    return bool(payload and isinstance(payload.get("models"), list))


def _ollama_ready(host: str = "127.0.0.1") -> bool:
    return _ollama_payload_ready(_json_url(f"http://{host}:11434/api/tags"))


def _listener_owner(port: int) -> dict[str, Any] | None:
    if psutil is None:
        return None
    try:
        for conn in psutil.net_connections(kind="inet"):
            if not conn.laddr or int(conn.laddr.port) != int(port):
                continue
            if conn.status != psutil.CONN_LISTEN or not conn.pid:
                continue
            identity = _process_identity(conn.pid)
            if identity:
                return identity
    except (psutil.AccessDenied, OSError):
        return None
    return None


def _process_listens(record: dict[str, Any], port: int | None) -> bool:
    if psutil is None or not port or not _child_identity_alive(record):
        return False
    try:
        proc = psutil.Process(int(record["pid"]))
        connections = proc.net_connections(kind="inet")
        return any(
            conn.laddr
            and int(conn.laddr.port) == int(port)
            and conn.status == psutil.CONN_LISTEN
            for conn in connections
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return False


def _bindable(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in {"", "localhost"} else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((bind_host, port))
        return True
    except OSError:
        return False


def _resolve_port(host: str, desired: int, span: int = 100) -> tuple[int, dict[str, Any] | None]:
    owner = _listener_owner(desired)
    bindable = _bindable(host, desired)
    if owner is None and bindable:
        return desired, None
    if owner is None and not bindable:
        owner = {"pid": "unbekannt", "name": "nicht auflösbarer Listener", "cmdline": []}
    for port in range(desired + 1, min(desired + span + 1, 65536)):
        if _listener_owner(port) is None and _bindable(host, port):
            return port, owner
    raise RuntimeError(f"Kein freier Port im Bereich {desired}-{desired + span}")


def _service_health(name: str, record: dict[str, Any]) -> bool:
    if name == "gui":
        return _url_ready(f"http://{record['host']}:{record['actual_port']}/")
    if name == "chat":
        payload = _json_url(
            f"http://{record['host']}:{record['actual_port']}/api/status"
        )
        return _chat_payload_ready(payload)
    if name == "tray":
        ready = _read_json(_ready_receipt_path("tray"))
        return bool(
            _identity_matches(record.get("pid"), record.get("create_time"))
            and ready.get("launch_id") == record.get("launch_id")
            and ready.get("pid") == record.get("pid")
        )
    return False


def _service_ready_owned(name: str, record: dict[str, Any]) -> bool:
    if not _record_is_owned(record) or not _service_health(name, record):
        return False
    if name in {"gui", "chat"}:
        return _process_listens(record, record.get("actual_port"))
    return True


def _receipt_path(name: str) -> Path:
    return _paths()["receipts"] / f"{name}.json"


def _ready_receipt_path(name: str) -> Path:
    return _paths()["receipts"] / f"{name}.ready.json"


def _sync_receipt(name: str, record: dict[str, Any]) -> dict[str, Any]:
    receipt = _read_json(_receipt_path(name))
    if receipt.get("launch_id") == record.get("launch_id"):
        for key in (
            "supervisor_pid", "supervisor_create_time", "pid", "create_time",
            "started_at", "ended_at", "exit_code", "command",
        ):
            if key in receipt:
                record[key] = receipt[key]
    return record


def _child_identity_alive(record: dict[str, Any]) -> bool:
    return _identity_matches(record.get("pid"), record.get("create_time"))


def _supervisor_identity_alive(record: dict[str, Any]) -> bool:
    return _identity_matches(
        record.get("supervisor_pid"),
        record.get("supervisor_create_time"),
    )


def _same_root(left: str | None, right: Path = ROOT_DIR) -> bool:
    if not left:
        return False
    try:
        return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))
    except (OSError, TypeError, ValueError):
        return False


def _record_is_owned(record: dict[str, Any]) -> bool:
    return _same_root(record.get("root")) and _child_identity_alive(record)


def _supervisor_is_owned(record: dict[str, Any]) -> bool:
    return _same_root(record.get("root")) and _supervisor_identity_alive(record)


def _record_has_live_identity(record: dict[str, Any]) -> bool:
    return _child_identity_alive(record) or _supervisor_identity_alive(record)


def _load_mutable_state() -> dict[str, Any]:
    state = _load_state()
    foreign_live = [
        name
        for name, record in state.get("services", {}).items()
        if _record_has_live_identity(record) and not _same_root(record.get("root"))
    ]
    if foreign_live:
        raise RuntimeError(
            "Runtime-State enthält lebende Services eines anderen oder unbekannten "
            f"BACH-Roots; keine Mutation: {', '.join(sorted(foreign_live))}"
        )
    if _same_root(state.get("root")):
        return state
    live = [
        name
        for name, record in state.get("services", {}).items()
        if _record_has_live_identity(record)
    ]
    if live:
        raise RuntimeError(
            "Runtime-State gehört zu einem anderen BACH-Root "
            f"({state.get('root')}); lebende Services werden nicht übernommen: "
            f"{', '.join(sorted(live))}"
        )
    return _base_state()


def _wait_for_receipt(name: str, launch_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        receipt = _read_json(_receipt_path(name))
        if receipt.get("launch_id") == launch_id and receipt.get("pid"):
            return receipt
        time.sleep(0.05)
    return {}


def _wait_ready(name: str, record: dict[str, Any], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    while time.monotonic() < deadline:
        _sync_receipt(name, record)
        if record.get("exit_code") is not None:
            return False
        if _service_ready_owned(name, record):
            if name not in {"chat", "tray"}:
                return True
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= 1.0:
                return True
        else:
            stable_since = None
        time.sleep(0.2)
    return False


def _child_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SYSTEM_DIR) + (os.pathsep + existing if existing else "")
    if extra:
        env.update(extra)
    return env


def _spawn_supervisor(name: str, spec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    paths = _paths()
    for key in ("runtime", "logs", "receipts", "specs"):
        paths[key].mkdir(parents=True, exist_ok=True)
    launch_id = f"{int(time.time() * 1000)}-{os.getpid()}"
    spec = dict(spec)
    spec["launch_id"] = launch_id
    spec_path = paths["specs"] / f"{name}-{launch_id}.json"
    _atomic_json(spec_path, spec)
    _receipt_path(name).unlink(missing_ok=True)
    _ready_receipt_path(name).unlink(missing_ok=True)

    command = [sys.executable, str(Path(__file__).resolve()), "_run-child", "--service", name, "--spec", str(spec_path)]
    kwargs: dict[str, Any] = {
        "cwd": str(ROOT_DIR),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    supervisor = subprocess.Popen(command, **kwargs)
    supervisor_identity = _process_identity(supervisor.pid)
    return {
        "launch_id": launch_id,
        "supervisor_pid": supervisor.pid,
        "supervisor_create_time": supervisor_identity["create_time"] if supervisor_identity else None,
    }, launch_id


def _start_service(
    state: dict[str, Any],
    name: str,
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    required: bool,
    host: str | None = None,
    desired_port: int | None = None,
    actual_port: int | None = None,
    readiness_timeout: float = 15.0,
) -> bool:
    existing = state["services"].get(name, {})
    _sync_receipt(name, existing)
    compatible = (
        existing.get("host") == host
        and existing.get("desired_port") == desired_port
    )
    if name == "tray":
        compatible = compatible and existing.get("actual_port") == actual_port
    if existing and compatible and _service_ready_owned(name, existing):
        existing["status"] = "online" if name != "tray" else "running"
        existing["reused_at"] = _now()
        print(f"[OK] {name}: bereits aktiv (PID {existing['pid']})")
        return True
    if existing and _record_has_live_identity(existing):
        if not _stop_record(name, existing):
            print(f"[FEHLER] {name}: vorhandener eigener Prozess konnte nicht sicher beendet werden")
            _save_state(state)
            return False

    log_path = _paths()["logs"] / f"{name}.log"
    env_overrides = {
        key: value
        for key, value in env.items()
        if os.environ.get(key) != value
    }
    spec = {
        "command": command,
        "cwd": str(cwd),
        "env_overrides": env_overrides,
        "log": str(log_path),
    }
    supervisor, launch_id = _spawn_supervisor(name, spec)
    record: dict[str, Any] = {
        **supervisor,
        "name": name,
        "required": required,
        "host": host,
        "desired_port": desired_port,
        "actual_port": actual_port,
        "status": "starting",
        "log": str(log_path),
        "root": str(ROOT_DIR),
        "started_at": _now(),
    }
    state["services"][name] = record
    _save_state(state)
    receipt = _wait_for_receipt(name, launch_id)
    record.update(receipt)
    _save_state(state)

    ready = _wait_ready(name, record, readiness_timeout)
    record["status"] = ("online" if name != "tray" else "running") if ready else "failed"
    if not ready:
        _sync_receipt(name, record)
        if _record_is_owned(record) or _supervisor_is_owned(record):
            _stop_record(name, record)
        _sync_receipt(name, record)
        record["status"] = "failed"
        record["failed_at"] = _now()
        exit_note = f", Exit {record.get('exit_code')}" if record.get("exit_code") is not None else ""
        level = "FEHLER" if required else "WARNUNG"
        print(f"[{level}] {name}: nicht bereit{exit_note}; Log: {log_path}")
    else:
        endpoint = f" {host}:{actual_port}" if actual_port else ""
        print(f"[OK] {name}:{endpoint} (PID {record.get('pid')})")
    _save_state(state)
    return ready or not required


def _terminate_identity(pid: int | None, created: float | None, label: str) -> tuple[bool, str]:
    if not pid:
        return True, f"{label}: keine PID"
    identity = _process_identity(pid)
    if identity is None:
        return True, f"{label}: bereits beendet"
    if created is None or abs(float(identity["create_time"]) - float(created)) >= 1.0:
        return False, f"{label}: PID {pid} gehört nicht mehr zum registrierten Prozess; nicht beendet"
    try:
        proc = psutil.Process(int(pid))
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            if not _identity_matches(pid, created):
                return True, f"{label}: beendet"
            proc.kill()
            proc.wait(timeout=3)
        return True, f"{label}: PID {pid} beendet"
    except psutil.NoSuchProcess:
        return True, f"{label}: bereits beendet"
    except (psutil.AccessDenied, psutil.TimeoutExpired) as exc:
        return False, f"{label}: PID {pid} nicht beendet ({exc})"


def _wait_for_exit_receipt(name: str, record: dict[str, Any], timeout: float = 2.0) -> bool:
    """Give the owned supervisor time to persist the child's exit code.

    The child has already ended when this is called. Terminating the
    supervisor immediately can otherwise win the race against its final
    receipt write and leave ``exit_code`` permanently null.
    """
    if record.get("exit_code") is not None:
        return True
    deadline = time.monotonic() + timeout
    while _supervisor_identity_alive(record) and time.monotonic() < deadline:
        # Do not read the receipt while the supervisor may be replacing it.
        # On Windows, opening the destination concurrently can make
        # os.replace() fail and strand the completed payload in its temp file.
        time.sleep(0.05)
    _sync_receipt(name, record)
    return record.get("exit_code") is not None


def _terminate_owned_supervisor_children(record: dict[str, Any]) -> tuple[bool, list[str]]:
    """Stop descendants only when their supervisor identity and BACH root are proven."""
    if psutil is None or not _supervisor_is_owned(record):
        return True, []
    try:
        supervisor = psutil.Process(int(record["supervisor_pid"]))
        descendants = supervisor.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return True, []
    ok = True
    messages = []
    for child in reversed(descendants):
        try:
            created = child.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        child_ok, message = _terminate_identity(
            child.pid,
            created,
            f"supervisor-kind-{child.pid}",
        )
        ok = child_ok and ok
        messages.append(message)
    return ok, messages


def _stop_record(name: str, record: dict[str, Any]) -> bool:
    _sync_receipt(name, record)
    descendants_ok = True
    descendant_messages: list[str] = []
    if not _child_identity_alive(record):
        descendants_ok, descendant_messages = _terminate_owned_supervisor_children(record)
    ok_child, child_msg = _terminate_identity(record.get("pid"), record.get("create_time"), name)
    ok_child = descendants_ok and ok_child
    if ok_child:
        _wait_for_exit_receipt(name, record)
    ok_supervisor, supervisor_msg = _terminate_identity(
        record.get("supervisor_pid"), record.get("supervisor_create_time"), f"{name}-supervisor"
    )
    _sync_receipt(name, record)
    print(f"[INFO] {child_msg}")
    for message in descendant_messages:
        print(f"[INFO] {message}")
    if record.get("supervisor_pid") != record.get("pid"):
        print(f"[INFO] {supervisor_msg}")
    record["status"] = "stopped" if ok_child and ok_supervisor else "stop-failed"
    record["stopped_at"] = _now()
    return ok_child and ok_supervisor


def _discovery(
    state: dict[str, Any],
    desired_gui: int,
    desired_control: int,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    services: dict[str, Any] = {}
    for name, record in state.get("services", {}).items():
        _sync_receipt(name, record)
        running = _child_identity_alive(record)
        supervisor_running = _supervisor_identity_alive(record)
        ready = _service_ready_owned(name, record)
        owner = _listener_owner(record.get("actual_port")) if record.get("actual_port") else None
        ownership = "owned" if (
            _same_root(record.get("root"))
            and _process_listens(record, record.get("actual_port"))
        ) else (
            "foreign" if owner else "none"
        )
        if name == "tray":
            ownership = (
                "owned" if running and _same_root(record.get("root"))
                else ("foreign-root" if running else "none")
            )
        services[name] = {
            **record,
            "running": running,
            "supervisor_running": supervisor_running,
            "ready": ready,
            "ownership": ownership,
        }
    host = "127.0.0.1"
    ollama_ready = _ollama_ready(host)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "root": str(ROOT_DIR),
        "registered_root": state.get("root"),
        "root_mismatch": not _same_root(state.get("root")),
        "desired_ports": {"gui": desired_gui, "control": desired_control},
        "services": services,
        "ollama": {
            "host": host,
            "port": 11434,
            "ready": ollama_ready,
            "status": "online" if ollama_ready else "offline",
            "required": False,
        },
    }
    if persist:
        _atomic_json(_paths()["discovery"], payload)
    return payload


def _port_value(value: int | None, env_name: str, default: int) -> int:
    port = value if value is not None else int(os.environ.get(env_name, str(default)))
    if not 1 <= int(port) <= 65535:
        raise ValueError(f"Ungültiger Port für {env_name}: {port}")
    return int(port)


def command_start(args: argparse.Namespace) -> int:
    host = args.host or os.environ.get("BACH_HOST", "127.0.0.1")
    gui_port = _port_value(args.gui_port, "BACH_GUI_PORT", 8000)
    control_port = _port_value(args.control_port, "BACH_CONTROL_PORT", 8081)
    requested = args.gui or args.chat or args.tray
    if not requested:
        args.gui = True
        args.tray = True

    remote = host not in LOCAL_HOSTS
    if remote and (args.gui or args.chat):
        print("[FEHLER] Remote-Hosts werden nur gelesen; lokale GUI/Chat-Prozesse werden nicht fern gestartet.")
        return 2

    with _operation_lease():
        state = _load_mutable_state()
        ok = True
        actual_gui = gui_port
        actual_control = control_port

        if args.gui:
            gui_existing = state["services"].get("gui", {})
            _sync_receipt("gui", gui_existing)
            if (
                gui_existing.get("desired_port") == gui_port
                and gui_existing.get("host") == "127.0.0.1"
                and _service_ready_owned("gui", gui_existing)
            ):
                actual_gui = int(gui_existing["actual_port"])
                displaced = None
            else:
                actual_gui, displaced = _resolve_port("127.0.0.1", gui_port)
            if displaced:
                print(
                    f"[WARNUNG] Wunschport {gui_port} gehört PID {displaced['pid']} "
                    f"({displaced['name']}); BACH nutzt {actual_gui}."
                )
            ok = _start_service(
                state,
                "gui",
                command=[sys.executable, str(SYSTEM_DIR / "gui" / "server.py"), "--host", "127.0.0.1", "--port", str(actual_gui)],
                cwd=SYSTEM_DIR,
                env=_child_environment(),
                required=True,
                host="127.0.0.1",
                desired_port=gui_port,
                actual_port=actual_gui,
                readiness_timeout=args.readiness_timeout,
            ) and ok
        else:
            gui_record = state["services"].get("gui", {})
            if _record_is_owned(gui_record):
                actual_gui = int(gui_record.get("actual_port", gui_port))

        if args.chat:
            chat_existing = state["services"].get("chat", {})
            _sync_receipt("chat", chat_existing)
            if (
                chat_existing.get("desired_port") == control_port
                and chat_existing.get("host") == "127.0.0.1"
                and _service_ready_owned("chat", chat_existing)
            ):
                actual_control = int(chat_existing["actual_port"])
                displaced = None
            else:
                actual_control, displaced = _resolve_port("127.0.0.1", control_port)
            if displaced:
                print(
                    f"[WARNUNG] Wunschport {control_port} gehört PID {displaced['pid']} "
                    f"({displaced['name']}); BACH nutzt {actual_control}."
                )
            ok = _start_service(
                state,
                "chat",
                command=[sys.executable, "-m", "hub._services.chat.telegram_chat"],
                cwd=SYSTEM_DIR,
                env=_child_environment({
                    "BACH_CONTROL_HOST": "127.0.0.1",
                    "BACH_CONTROL_PORT": str(actual_control),
                }),
                required=True,
                host="127.0.0.1",
                desired_port=control_port,
                actual_port=actual_control,
                readiness_timeout=args.readiness_timeout,
            ) and ok
        else:
            chat_record = state["services"].get("chat", {})
            if _record_is_owned(chat_record):
                actual_control = int(chat_record.get("actual_port", control_port))
            elif not remote:
                actual_control, displaced = _resolve_port("127.0.0.1", control_port)
                if displaced:
                    print(
                        f"[WARNUNG] Control-Wunschport {control_port} ist fremd belegt; "
                        f"der Tray wartet offline auf {actual_control}."
                    )

        if args.tray:
            tray_host = host if remote else "127.0.0.1"
            tray_control = control_port if remote else actual_control
            tray_gui = gui_port if remote else actual_gui
            ok = _start_service(
                state,
                "tray",
                command=[
                    sys.executable,
                    str(CHAT_DIR / "chat_tray.py"),
                    "--host", tray_host,
                    "--port", str(tray_control),
                    "--gui-port", str(tray_gui),
                    "--ollama-host", "127.0.0.1",
                ],
                cwd=SYSTEM_DIR,
                env=_child_environment(),
                required=True,
                host=tray_host,
                desired_port=tray_control,
                actual_port=tray_control,
                readiness_timeout=args.readiness_timeout,
            ) and ok

        _save_state(state)
        discovery = _discovery(state, gui_port, control_port)

    if args.open_browser and args.gui and ok and os.environ.get("BACH_NO_BROWSER") != "1":
        webbrowser.open(f"http://127.0.0.1:{actual_gui}")
    print(f"[INFO] Discovery: {_paths()['discovery']}")
    _print_status(discovery)
    return 0 if ok else 1


def _print_status(discovery: dict[str, Any]) -> None:
    print("BACH Service-Status")
    print("===================")
    if discovery.get("root_mismatch"):
        print(
            "  [WARNUNG] Runtime-State gehört zu anderem Root: "
            f"{discovery.get('registered_root')}; aktuell: {discovery.get('root')}"
        )
    services = discovery.get("services", {})
    for name in ("gui", "chat", "tray"):
        item = services.get(name)
        if not item:
            print(f"  {name}: nicht registriert")
            continue
        endpoint = ""
        if item.get("host") and item.get("actual_port"):
            endpoint = f" {item['host']}:{item['actual_port']}"
        state = "ONLINE" if item.get("ready") else ("LÄUFT/OFFLINE" if item.get("running") else "OFFLINE")
        print(
            f"  {name}:{endpoint} {state}; PID={item.get('pid', '-')} "
            f"Owner={item.get('ownership', 'none')} Exit={item.get('exit_code', '-')}"
        )
    ollama = discovery.get("ollama", {})
    print(f"  ollama: {ollama.get('host')}:{ollama.get('port')} {ollama.get('status', 'offline').upper()} (optional)")


def command_status(args: argparse.Namespace) -> int:
    host = args.host or os.environ.get("BACH_HOST", "127.0.0.1")
    gui_port = _port_value(args.gui_port, "BACH_GUI_PORT", 8000)
    control_port = _port_value(args.control_port, "BACH_CONTROL_PORT", 8081)
    if host not in LOCAL_HOSTS:
        ollama_host = "127.0.0.1"
        local_ollama_ready = _ollama_ready(ollama_host)
        remote_chat_ready = _chat_payload_ready(
            _json_url(f"http://{host}:{control_port}/api/status")
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "root": str(ROOT_DIR),
            "services": {
                "gui": {"host": host, "actual_port": gui_port, "ready": _url_ready(f"http://{host}:{gui_port}/"), "running": False, "ownership": "remote"},
                "chat": {
                    "host": host,
                    "actual_port": control_port,
                    "ready": remote_chat_ready,
                    "running": False,
                    "ownership": "remote",
                },
            },
            "ollama": {
                "host": ollama_host,
                "port": 11434,
                "ready": local_ollama_ready,
                "status": "online" if local_ollama_ready else "offline",
                "required": False,
            },
        }
    else:
        state = _load_state()
        payload = _discovery(state, gui_port, control_port, persist=False)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_status(payload)
        print(f"[INFO] Runtime-State: {_paths()['state']}")
    required_failed = any(
        item.get("required") and not item.get("ready")
        for item in payload.get("services", {}).values()
    )
    return 1 if required_failed else 0


def command_stop(args: argparse.Namespace) -> int:
    requested = set(args.services.split(",")) if args.services != "all" else {"gui", "chat", "tray"}
    unknown = requested - {"gui", "chat", "tray"}
    if unknown:
        print(f"[FEHLER] Unbekannte Services: {', '.join(sorted(unknown))}")
        return 2
    with _operation_lease():
        state = _load_mutable_state()
        ok = True
        for name in ("tray", "chat", "gui"):
            if name not in requested:
                continue
            record = state["services"].get(name)
            if not record:
                print(f"[INFO] {name}: nicht registriert")
                continue
            ok = _stop_record(name, record) and ok
        _save_state(state)
        _discovery(
            state,
            _port_value(None, "BACH_GUI_PORT", 8000),
            _port_value(None, "BACH_CONTROL_PORT", 8081),
        )
    return 0 if ok else 1


def command_run_child(args: argparse.Namespace) -> int:
    """Interner Supervisor: erfasst Kind-PID und Exit-Code in einem Receipt."""
    spec_path = Path(args.spec).resolve()
    spec = _read_json(spec_path)
    if not spec or not isinstance(spec.get("command"), list):
        return 2
    receipt_path = _receipt_path(args.service)
    supervisor_identity = _process_identity(os.getpid())
    env = os.environ.copy()
    overrides = spec.get("env_overrides")
    if isinstance(overrides, dict):
        env.update({str(k): str(v) for k, v in overrides.items()})
    env["BACH_STARTSPINE_LAUNCH_ID"] = str(spec.get("launch_id") or "")
    env["BACH_STARTSPINE_SERVICE"] = str(args.service)
    log_path = Path(spec["log"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab", buffering=0) as log_handle:
        child = subprocess.Popen(
            [str(item) for item in spec["command"]],
            cwd=spec.get("cwd") or str(ROOT_DIR),
            env={str(k): str(v) for k, v in env.items()},
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
        child_identity = _process_identity(child.pid)
        receipt = {
            "launch_id": spec.get("launch_id"),
            "service": args.service,
            "supervisor_pid": os.getpid(),
            "supervisor_create_time": supervisor_identity["create_time"] if supervisor_identity else None,
            "pid": child.pid,
            "create_time": child_identity["create_time"] if child_identity else None,
            "command": spec["command"],
            "started_at": _now(),
            "exit_code": None,
        }
        _atomic_json(receipt_path, receipt)
        exit_code = child.wait()
        receipt["exit_code"] = exit_code
        receipt["ended_at"] = _now()
        _atomic_json(receipt_path, receipt)
        spec_path.unlink(missing_ok=True)
        return int(exit_code)


def command_autostart_install(_args: argparse.Namespace) -> int:
    if os.name != "nt":
        print("[FEHLER] Windows-Autostart ist nur unter Windows verfügbar.")
        return 2
    task_command = subprocess.list2cmdline(
        [str(Path(sys.executable)), str(Path(__file__).resolve()), "start", "--tray"]
    )
    result = subprocess.run(
        [
            "schtasks",
            "/create",
            "/tn", "BACH Chat Tray",
            "/tr", task_command,
            "/sc", "onlogon",
            "/rl", "highest",
            "/f",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        print(f"[FEHLER] Autostart konnte nicht erstellt werden: {detail}")
        return int(result.returncode)
    readback = subprocess.run(
        ["schtasks", "/query", "/tn", "BACH Chat Tray", "/fo", "list"],
        text=True,
        capture_output=True,
        check=False,
    )
    if readback.returncode != 0:
        print("[FEHLER] Autostart wurde erstellt, aber der Readback ist fehlgeschlagen.")
        return 1
    print("[OK] Autostart-Eintrag erstellt und zurückgelesen: BACH Chat Tray")
    return 0


def command_autostart_remove(_args: argparse.Namespace) -> int:
    if os.name != "nt":
        print("[FEHLER] Windows-Autostart ist nur unter Windows verfügbar.")
        return 2
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", "BACH Chat Tray", "/f"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        print(f"[FEHLER] Autostart konnte nicht entfernt werden: {detail}")
        return int(result.returncode)
    readback = subprocess.run(
        ["schtasks", "/query", "/tn", "BACH Chat Tray"],
        text=True,
        capture_output=True,
        check=False,
    )
    if readback.returncode == 0:
        print("[FEHLER] Autostart ist nach dem Entfernen weiterhin registriert.")
        return 1
    print("[OK] Autostart-Eintrag entfernt; Readback bestätigt Abwesenheit.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BACH Startspine")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Services sicher starten")
    start.add_argument("--gui", action="store_true")
    start.add_argument("--chat", action="store_true")
    start.add_argument("--tray", action="store_true")
    start.add_argument("--host", help="Tray-/Remote-Host; Standard BACH_HOST oder 127.0.0.1")
    start.add_argument("--gui-port", type=int)
    start.add_argument("--control-port", type=int)
    start.add_argument("--open-browser", action="store_true")
    start.add_argument("--readiness-timeout", type=float, default=15.0)
    start.set_defaults(func=command_start)

    status = sub.add_parser("status", help="Readiness, Ownership, PIDs und Ports anzeigen")
    status.add_argument("--host")
    status.add_argument("--gui-port", type=int)
    status.add_argument("--control-port", type=int)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    stop = sub.add_parser("stop", help="Nur von der Startspine registrierte Prozesse beenden")
    stop.add_argument("--services", default="all", help="all oder Kommaliste: gui,chat,tray")
    stop.set_defaults(func=command_stop)

    autostart_install = sub.add_parser(
        "autostart-install",
        help="Windows-Autostart mit absoluten, sicher gequoteten Pfaden einrichten",
    )
    autostart_install.set_defaults(func=command_autostart_install)

    autostart_remove = sub.add_parser(
        "autostart-remove",
        help="Windows-Autostart entfernen",
    )
    autostart_remove.set_defaults(func=command_autostart_remove)

    child = sub.add_parser("_run-child", help=argparse.SUPPRESS)
    child.add_argument("--service", required=True)
    child.add_argument("--spec", required=True)
    child.set_defaults(func=command_run_child)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"[FEHLER] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
