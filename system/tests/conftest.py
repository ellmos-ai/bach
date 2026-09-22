#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testweite Isolation der BACH-Datenbank + produktiver ~/.bach-Pfade.

hub.bach_paths loest Pfade zuerst ueber Env-Vars auf (BACH_LOCAL_DIR, BACH_DB,
BACH_BACKUPS_DIR).
Ohne diese Isolation laufen Tests, die App/Database/Backup ohne eigenen Pfad
instanziieren (z. B. TestApp.test_db_lazy), gegen die ECHTE Produktiv-DB
~/.bach/bach.db — am 2026-09-01 hat genau das real Migrationen gegen
Produktivdaten ausgefuehrt (PR-#10-Review, Vorfallsbericht; Bereinigung
dokumentiert in T-20260901-620606145).

Die urspruengliche Isolation deckte nur BACH_DB ab. Ein Volllauf am 2026-09-02
zeigte, dass Tests trotzdem in ~/.bach/bach_secrets.json, ~/.bach/backups/
und ~/.bach/plans schreiben, weil secrets_handler.py und plan_agent.py ihre
Pfade nicht (nur) ueber hub.bach_paths aufloesen (T-20260902-646684582).
Deshalb hier zusaetzlich BACH_BACKUPS_DIR/BACH_SECRETS_FILE/BACH_PLANS_DIR
setzen — dieselbe Env-Var-Isolation, nur fuer die drei weiteren Pfade.

Auf Modulebene (nicht als Fixture), damit die Env-Vars gesetzt sind, BEVOR
Testmodule die betroffenen Module importieren. Die Suite erzwingt ihre privaten
Pfade; geerbte Shell- oder CI-Werte duerfen nie auf Produktivdaten zeigen.
"""

import atexit
import os
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import pytest

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="bach_test_db_"))
_TEST_PROCESS_GUARD_DIR = Path(__file__).resolve().parent / "_test_process_guard"
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["BACH_LOCAL_DIR"] = str(_TEST_DB_DIR)
os.environ["BACH_DB"] = str(_TEST_DB_DIR / "bach_test.db")
os.environ["BACH_BACKUPS_DIR"] = str(_TEST_DB_DIR / "backups")
os.environ["BACH_SECRETS_FILE"] = str(_TEST_DB_DIR / "bach_secrets.json")
os.environ["BACH_PLANS_DIR"] = str(_TEST_DB_DIR / "plans")
os.environ["BACH_RESEARCH_DIR"] = str(_TEST_DB_DIR / "research")
# Sicherheitsgrenzen werden von der Suite erzwungen. Geerbte Shell-/CI-Werte
# dürfen Testisolation und Host-Prozessschutz nicht abschalten.
os.environ["BACH_RUNTIME_DIR"] = str(_TEST_DB_DIR / "runtime")
os.environ["BACH_TEST_MODE"] = "1"
os.environ["PYTHONPATH"] = os.pathsep.join(
    part
    for part in (
        str(_TEST_PROCESS_GUARD_DIR),
        os.environ.get("PYTHONPATH", ""),
    )
    if part
)
os.environ["BACH_FACKEL_PREFERENCE_PATH"] = str(
    _TEST_DB_DIR / "fackel_preference.json"
)
os.environ["BACH_SLOTS_CONFIG_PATH"] = str(_TEST_DB_DIR / "slots_config.json")


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_private_slots_config():
    """Materialize the private slots config before strict Control API tests."""
    from hub._services.chat import slots_config

    path = os.environ["BACH_SLOTS_CONFIG_PATH"]
    initialize = getattr(slots_config, "initialize_slots_config", None)
    if initialize is not None:
        initialize(path)
    else:
        slots_config.load_slots_config(path)

_SOURCE_SYSTEM_ROOT = Path(__file__).resolve().parent.parent
_PROTECTED_SOURCE_RUNTIME_ROOTS = (
    _SOURCE_SYSTEM_ROOT / "data",
    _SOURCE_SYSTEM_ROOT / "system" / "data",
    _SOURCE_SYSTEM_ROOT / "tools" / "llmauto" / "logs",
)
_SOURCE_RUNTIME_WRITE_ATTEMPTS = set()


def _source_runtime_path(path_like):
    """Return a protected source-runtime path, if *path_like* resolves there."""
    try:
        candidate = Path(path_like).resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if candidate.name.endswith(".pyc") or "__pycache__" in candidate.parts:
        return None
    for root in _PROTECTED_SOURCE_RUNTIME_ROOTS:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        return candidate
    return None


def _audit_source_runtime_writes(event, args):
    """Fail closed when tests try to write runtime state into the checkout."""
    if event == "open":
        if not _opens_for_write(
            args[1] if len(args) > 1 else None,
            args[2] if len(args) > 2 else None,
        ):
            return
        targets = args[:1]
    elif event in _WRITE_EVENTS:
        targets = args[:2] if event in {"os.rename", "os.replace", "shutil.move"} else args[:1]
    else:
        return
    for target in targets:
        protected = _source_runtime_path(target)
        if protected is not None:
            message = f"source runtime write blocked: {event}: {protected}"
            _SOURCE_RUNTIME_WRITE_ATTEMPTS.add(message)
            raise RuntimeError(message)


def _destructive_process_reason(command):
    """Describe process-control commands that must never run from tests."""
    if isinstance(command, (str, bytes)):
        rendered = os.fsdecode(command)
        executable = rendered
    elif isinstance(command, (list, tuple)):
        rendered = " ".join(
            os.fsdecode(part)
            for part in command
            if isinstance(part, (str, bytes, os.PathLike))
        )
        executable = os.fsdecode(command[0]) if command else ""
    else:
        return None
    lowered = rendered.casefold()
    executable_lower = executable.casefold()
    executable_name = Path(executable_lower).name
    unguarded_python = re.compile(
        r"(?:^|[;&|]\s*)(?:\"[^\"]*python(?:\d+(?:\.\d+)*)?\.exe\"|"
        r"[^\s\"]*python(?:\d+(?:\.\d+)*)?(?:\.exe)?)\s+"
        r"(?:-[a-df-hj-rt-z0-9]+\s+)*(?<!-)-(?:[a-df-hj-rt-z0-9]*[eis][a-z0-9]*)(?:\s|$)",
        re.IGNORECASE,
    )
    if unguarded_python.search(rendered):
        return "Python child without inherited safety guard"
    if executable_name.startswith("python") and isinstance(command, (list, tuple)):
        options = []
        for part in command[1:]:
            s = str(part)
            if s in {"-c", "-m"}:
                break
            if not s.startswith("-") or s == "-":
                break
            options.append(s)
        if any(
            not opt.startswith("--") and any(c in "eEisIS" for c in opt[1:])
            for opt in options
        ):
            return "Python child without inherited safety guard"
    if "onedrive" in executable_lower and "/shutdown" in lowered:
        return "OneDrive shutdown"
    if any(token in executable_lower for token in (
        "taskkill", "stop-process", "kill-process", "pkill", "killall",
    )):
        return "process termination"
    if "osascript" in executable_lower and "quit" in lowered:
        return "application termination"
    if executable_name in {
        "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
        "sh", "bash", "zsh",
    } and any(token in lowered for token in (
        "taskkill", "stop-process", "kill-process", "pkill", "killall",
        "onedrive.exe /shutdown", "onedrive.exe\" /shutdown", " kill ",
    )):
        return "shell-mediated process termination"
    return None


def _protected_subprocess_env(env=None):
    """Force the test safety contract into every spawned child process."""
    protected = dict(os.environ if env is None else env)
    existing = protected.get("PYTHONPATH", "")
    paths = [part for part in existing.split(os.pathsep) if part]
    guard_path = str(_TEST_PROCESS_GUARD_DIR)
    paths = [part for part in paths if Path(part) != _TEST_PROCESS_GUARD_DIR]
    protected["PYTHONPATH"] = os.pathsep.join([guard_path, *paths])
    protected["BACH_TEST_MODE"] = "1"
    protected["BACH_RUNTIME_DIR"] = os.environ["BACH_RUNTIME_DIR"]
    return protected


def _snapshot_home_bach():
    """mtime jeder Datei/jedes Ordners unter ~/.bach, sofern vorhanden.

    Eintraege, die waehrend des Scans verschwinden oder nicht lesbar sind,
    werden uebersprungen: der Waechter soll ein Urteil liefern, nicht den
    ganzen Lauf mit einem Error abbrechen.
    """
    root = Path.home() / ".bach"
    if not root.exists():
        return None
    snapshot = {}
    for path in root.rglob("*"):
        try:
            snapshot[str(path.relative_to(root))] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshot


# --------------------------------------------------------------------------
# Zurechnung der ~/.bach-Schreibzugriffe (T-20260912-679116669)
#
# Der mtime-Vergleich oben sieht das VERZEICHNIS, nicht den Verursacher. Auf
# einem Rechner mit laufendem BACH-Dienst (chat_tray.py haelt sein Log unter
# ~/.bach) war damit jeder Volllauf rot, ohne dass die Suite etwas angefasst
# hatte. Ein Waechter, der regelmaessig grundlos anschlaegt, wird ignoriert --
# und dann faellt der echte Schreibzugriff nicht mehr auf.
#
# Deshalb zwei Quellen statt einer:
#   1. mtime-Diff  -> deckt auch Subprozesse ab, kann aber nicht zurechnen;
#      zaehlt als Beweis nur, wenn beim Sitzungsstart KEIN fremder BACH-Dienst
#      lief. Ohne solche Dienste (CI, sauberer Rechner) ist er damit exakt und
#      die Suite bleibt so streng wie bisher.
#   2. Audit-Hook  -> was DIESER Prozess unter ~/.bach oeffnet/anlegt. Exakt
#      zurechenbar, weil ein fremder Prozess ihn nie ausloest. Er wird NUR
#      installiert, wenn tatsaechlich ein fremder Dienst laeuft: ein
#      Audit-Hook verteuert jedes open() im Prozess (hier gemessen: rund 30 %
#      auf E/A-lastigen Abschnitten). Genau dann ist er aber noetig, weil
#      Punkt 1 in dieser Lage nichts mehr beweisen kann.
# --------------------------------------------------------------------------

_HOME_BACH_DIR = Path.home() / ".bach"
_OWN_HOME_WRITES = set()

#: Audit-Events, die eine Datei anlegen/veraendern (open wird gesondert geprueft).
_WRITE_EVENTS = frozenset({
    "os.mkdir", "os.rmdir", "os.rename", "os.remove", "os.replace",
    "os.truncate", "os.link", "os.symlink", "shutil.copyfile",
    "shutil.copymode", "shutil.copystat", "shutil.move",
})

#: Woran ein residenter BACH-Dienst in der Prozessliste erkennbar ist.
_BACH_SERVICE_HINTS = (
    "chat_tray.py", "session_daemon.py", "bridge_daemon.py",
    "daemon_service.py", "bach.py",
)

# Source-runtime writes must be blocked independently of resident BACH services.
sys.addaudithook(_audit_source_runtime_writes)


def _note_write_if_under(path, root, sink):
    """Legt `path` relativ in `sink` ab, wenn es unter `root` liegt.

    Laeuft im Audit-Hook bei JEDEM open() -- darf deshalb niemals werfen und
    nichts Teures tun. Unbrauchbare Argumente (Dateideskriptor als int, Bytes
    mit kaputtem Encoding) werden still verworfen.
    """
    try:
        target = os.path.abspath(os.fsdecode(os.fspath(path)))
        base = os.path.abspath(os.fsdecode(os.fspath(root)))
    except (TypeError, ValueError, OSError, UnicodeDecodeError):
        return
    if os.name == "nt":
        target_cmp, base_cmp = target.lower(), base.lower()
    else:
        target_cmp, base_cmp = target, base
    # Nur echte Kinder: "~/.bach_backup" ist NICHT "~/.bach".
    if not target_cmp.startswith(base_cmp + os.sep):
        return
    try:
        sink.add(os.path.relpath(target, base).replace("\\", "/"))
    except (TypeError, ValueError):
        return


def _opens_for_write(mode, flags):
    """True, wenn dieses open() schreiben kann.

    builtins.open meldet den Modus als String, os.open die O_*-Flags als int.
    """
    if isinstance(mode, str):
        return any(zeichen in mode for zeichen in "wax+")
    if isinstance(flags, int):
        return bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND
                             | os.O_CREAT | os.O_TRUNC))
    return False


def _audit_home_writes(event, args):
    """Audit-Hook: merkt sich Schreibzugriffe DIESES Prozesses unter ~/.bach."""
    try:
        if event == "open":
            if not _opens_for_write(
                args[1] if len(args) > 1 else None,
                args[2] if len(args) > 2 else None,
            ):
                return
        elif event not in _WRITE_EVENTS:
            return
        if args:
            _note_write_if_under(args[0], _HOME_BACH_DIR, _OWN_HOME_WRITES)
    except Exception:  # ein Waechter darf den Lauf nie zum Absturz bringen
        return


def _foreign_bach_processes():
    """Residente BACH-Dienste, die NICHT zu diesem Testlauf gehoeren.

    Wird bewusst beim Sitzungsstart erhoben: Was schon lief, bevor der erste
    Test begann, kann kein Waisenprozess dieses Laufs sein.
    """
    try:
        import psutil
    except ImportError:
        return []
    eigene = {os.getpid()}
    try:
        eigene |= {kind.pid for kind in psutil.Process().children(recursive=True)}
    except Exception:
        pass
    gefunden = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = proc.info["pid"]
            if pid in eigene:
                continue
            kommandozeile = " ".join(proc.info.get("cmdline") or ())
            treffer = next(
                (hinweis for hinweis in _BACH_SERVICE_HINTS if hinweis in kommandozeile),
                None,
            )
            if treffer:
                gefunden.append((pid, treffer))
        except Exception:
            continue
    return gefunden


def _classify_home_writes(own_writes, changed, foreign):
    """Urteil des Waechters: (fail, meldung).

    - Eigene Schreibzugriffe sind immer rot, auch wenn nebenher ein Dienst
      laeuft -- sonst waere der Waechter genau dann blind, wenn entwickelt wird.
    - Eine Verzeichnisaenderung ohne eigenen Schreibzugriff ist nur dann rot,
      wenn kein fremder Dienst als Verursacher in Frage kommt.
    """
    eigene = sorted(own_writes)
    if eigene:
        return True, (
            "Testlauf hat produktives ~/.bach veraendert "
            f"(T-20260902-646684582): {eigene} -- dieser Testprozess hat dort "
            "geschrieben (Audit-Hook)."
        )
    geaendert = sorted(changed)
    if not geaendert:
        return False, None
    if foreign:
        verursacher = ", ".join(f"PID {pid} ({name})" for pid, name in foreign)
        return False, (
            f"~/.bach hat sich waehrend des Laufs geaendert: {geaendert}. Dieser "
            "Testprozess hat dort nicht geschrieben; beim Sitzungsstart liefen "
            f"bereits fremde BACH-Dienste: {verursacher}. Nicht der Suite "
            "zugerechnet (T-20260912-679116669)."
        )
    return True, (
        "Testlauf hat produktives ~/.bach veraendert "
        f"(T-20260902-646684582): {geaendert} -- kein fremder BACH-Dienst lief "
        "beim Sitzungsstart, die Aenderung geht auf diesen Lauf (z. B. ueber "
        "einen Subprozess)."
    )


@pytest.fixture(scope="session", autouse=True)
def _guard_production_bach_dir():
    """Regressionswaechter: kein Testlauf darf ~/.bach anfassen (T-20260902-646684582).

    Ein Volllauf am 2026-09-02 zeigte Schreibzugriffe auf die produktive
    ~/.bach/bach_secrets.json, ~/.bach/backups und ~/.bach/plans trotz
    BACH_DB-Isolation. Diese Fixture haelt die Zusage ein: mtime jeder Datei
    unter ~/.bach muss vor und nach der Suite identisch sein.

    Frueher meldete dieser Waechter auch fremde Schreiber (T-20260912-679116669):
    Er misst das VERZEICHNIS, nicht den Verursacher. Laeuft nebenher ein
    residenter BACH-Prozess -- chat_tray.py, session_daemon.py oder ein
    manueller `bach`-Aufruf --, schreibt DER nach ~/.bach, ohne die Env-Vars
    dieser conftest je zu sehen. Gemessen am 2026-09-12: chat_tray.log, PID
    10204, gestartet sieben Stunden vor dem Lauf -- die Suite war rot, ohne
    etwas angefasst zu haben. Deshalb zaehlt jetzt der Audit-Hook (exakt
    zurechenbar), und der mtime-Diff ist nur noch dann ein Beweis, wenn beim
    Sitzungsstart kein fremder Dienst lief. Details: _classify_home_writes().
    """
    if os.environ.get("BACH_ALLOW_HOME_WRITES"):
        # Opt-out fuer Laeufe, in denen sich ~/.bach legitim aendert.
        yield
        return
    before = _snapshot_home_bach()
    foreign = _foreign_bach_processes()
    _OWN_HOME_WRITES.clear()
    if foreign:
        # Nur hier noetig -- und nur hier ist der Aufschlag gerechtfertigt.
        sys.addaudithook(_audit_home_writes)
    yield
    changed = []
    if before is not None:
        after = _snapshot_home_bach()
        changed = [
            k for k in before.keys() | (after or {}).keys()
            if before.get(k) != (after or {}).get(k)
        ]
    fail, meldung = _classify_home_writes(_OWN_HOME_WRITES, changed, foreign)
    if meldung and not fail:
        # pytest >= 9 zeigt UserWarnings aus dem Teardown einer Session-Scoped-
        # Fixture nicht mehr in der Warnungs-Summary an (gemessen: 9.0.3,
        # #1304); ein print waehrend des Teardowns faellt in die fd-Capture.
        # Selbst atexit+print(file=sys.stderr) stirbt, weil pytest die globalen
        # Stream-OBJEKTE vor dem Interpreter-Exit schliesst ("I/O operation on
        # closed file"). Robuster Kanal: os.write direkt auf fd 2 -- der
        # Deskriptor selbst bleibt bis Prozessende offen. Sichtbar im Terminal
        # UND im Subprozess-Output (test_home_guard_attribution #1304).
        atexit.register(os.write, 2, f"[Home-Guard] {meldung}\n".encode("utf-8", "replace"))
        warnings.warn(meldung, stacklevel=1)
    assert not fail, meldung


@pytest.fixture(scope="session", autouse=True)
def _guard_source_runtime_dirs():
    """Make swallowed source-runtime write errors fail the complete test run."""
    yield
    assert not _SOURCE_RUNTIME_WRITE_ATTEMPTS, (
        "Tests attempted writes below checkout runtime directories: "
        f"{sorted(_SOURCE_RUNTIME_WRITE_ATTEMPTS)}"
    )


@pytest.fixture(autouse=True)
def _reset_lang_cache():
    """Reihenfolge-Leckage ueber hub.lang beheben (T-20260902-646684582, Befund B).

    hub.lang haelt die aufgeloeste Sprache in einem PROZESSWEITEN globalen
    Cache (_t_lang_cache). Jeder Test/Handler, der get_lang()/set_lang() auf
    Spanisch/Englisch stellt (direkt oder ueber einen DB-Wert), aendert diesen
    Cache fuer den Rest der Suite — unabhaengig davon, welche DB spaeter
    genutzt wird. Vor/nach jedem Test zuruecksetzen macht den naechsten Test
    unabhaengig vom vorherigen.
    """
    from hub.lang import clear_t_cache
    clear_t_cache()
    yield
    clear_t_cache()


@pytest.fixture(autouse=True)
def _guard_real_process_control(monkeypatch):
    """Do not let unit/integration tests terminate real host processes."""
    real_run = subprocess.run
    real_popen = subprocess.Popen
    real_os_kill = os.kill

    def guarded_run(args, *popenargs, **kwargs):
        reason = _destructive_process_reason(args)
        if reason:
            raise RuntimeError(f"real {reason} blocked in test: {args!r}")
        kwargs["env"] = _protected_subprocess_env(kwargs.get("env"))
        return real_run(args, *popenargs, **kwargs)

    class GuardedPopen(real_popen):
        def __init__(self, args, *popenargs, **kwargs):
            reason = _destructive_process_reason(args)
            if reason:
                raise RuntimeError(f"real {reason} blocked in test: {args!r}")
            kwargs["env"] = _protected_subprocess_env(kwargs.get("env"))
            super().__init__(args, *popenargs, **kwargs)

    def is_own_test_process(pid):
        if pid == os.getpid():
            return True
        try:
            import psutil

            process = psutil.Process(pid)
            while process is not None:
                if process.ppid() == os.getpid():
                    return True
                process = process.parent()
        except Exception:
            return False
        return False

    def guarded_os_kill(pid, sig):
        if sig != 0 and not is_own_test_process(pid):
            raise RuntimeError(f"real foreign process termination blocked in test: PID {pid}")
        return real_os_kill(pid, sig)

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(os, "kill", guarded_os_kill)

    try:
        import psutil
    except ImportError:
        return

    real_terminate = psutil.Process.terminate
    real_kill = psutil.Process.kill

    def guarded_terminate(process):
        if not is_own_test_process(process.pid):
            raise RuntimeError(
                f"real foreign process termination blocked in test: PID {process.pid}"
            )
        return real_terminate(process)

    def guarded_kill(process):
        if not is_own_test_process(process.pid):
            raise RuntimeError(
                f"real foreign process kill blocked in test: PID {process.pid}"
            )
        return real_kill(process)

    monkeypatch.setattr(psutil.Process, "terminate", guarded_terminate)
    monkeypatch.setattr(psutil.Process, "kill", guarded_kill)
