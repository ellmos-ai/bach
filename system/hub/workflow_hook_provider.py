# SPDX-License-Identifier: MIT
"""
workflowhooker Provider-Seam (MODULRUECKTRANSFER Stufe 6)
=========================================================

In-process-Anbindung des externen Moduls `workflowhooker` an
HookRegistry.emit (core/hooks.py) -- "ereignisbasierte Step-Trigger"
(Schnittstellenmatrix MODULRUECKTRANSFER-PLAN.md, Nr. 7).

Architektur: core bleibt frei von hub-Importen (AST-Waechter-Regel der
Stufen 2-5). HookRegistry stellt nur einen generischen Interceptor-Slot
bereit (register_interceptor); dieser Seam liefert das Callable und
installiert es idempotent ueber hub/__init__.py beim Paketimport.

Der Interceptor mappt BACH-Lifecycle-Events auf die Hook-Events des Moduls
und laesst _run_active_checks (Budget + Cooldown + Idle-Selbstabschaltung,
siehe workflowhooker/cli.py) die Checks laufen:

  before_command / after_command  ~  UserPromptSubmit-Charakter
  after_task_done                 ~  Stop-Charakter (Abschluss-Gate)

Rollback (Plan-Regel 4.1): BACH_USE_EXTERNAL_WORKFLOWHOOKS=0/false/no/off
stoppt den Interceptor live -- er bleibt registriert, liefert aber nichts
mehr (Registry-Slot bleibt thereby reversibel ohne Neustart).

Fehlt das Modul oder der Contract, failt der Seam geschlossen: keine
Meldung, eine Log-Warnung. Ein Check bleibt laut Modul-Default inaktiv,
bis BACH ihn aktiviert (Default hier: closing_gate, zurueckhaltend);
drift_warning/scope_guard sind ueber workflowhooker.toml zuschaltbar.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

#: Name des externen Python-Moduls (requirements.txt-Pin).
WORKFLOWHOOKER_MODULE = "workflowhooker"

#: Rollback-Schalter (Plan-Regel 4.1).
ROLLBACK_ENV = "BACH_USE_EXTERNAL_WORKFLOWHOOKS"
_OFF_VALUES = {"0", "false", "no", "off"}

#: BACH-Events, an denen der Interceptor laeuft (Plan: Step-Trigger).
#: Bewusst nur AFTER-Events: BACH hat fuer before_command keine Ausgabe- bzw.
#: Anhangstelle, eine Meldung dort wuerde das Session-Budget verbrauchen,
#: ohne je sichtbar zu werden (empirisch im Nachweislauf gefangen). Vor-
#: Events bleiben optional ueber den events-Parameter zuschaltbar.
DEFAULT_EVENTS = ("after_command", "after_task_done")

#: Zurueckhaltende Default-Checks (Modul-Default waere: keine).
DEFAULT_CHECKS = ("closing_gate",)

#: Contract-Symbole (Submodul.Attribut), die das externe Modul bereitstellen
#: muss (fail-closed). Bewusst inkl. cli._run_active_checks: Dort steckt der
#: Budget-/Cooldown-/Idle-Guard -- API-Drift faellt hier sofort auf.
_REQUIRED_SYMBOLS = {
    "CHECK_REGISTRY": ("checks", "CHECK_REGISTRY"),
    "CheckRunner": ("checks", "CheckRunner"),
    "SessionState": ("state", "SessionState"),
    "state_path_for_session": ("state", "state_path_for_session"),
    "load_config": ("config", "load_config"),
    "default_config": ("config", "default_config"),
    "CompositeStateSource": ("sources", "CompositeStateSource"),
    "FilesStateSource": ("sources", "FilesStateSource"),
    "GitStateSource": ("sources", "GitStateSource"),
    "_run_active_checks": ("cli", "_run_active_checks"),
}

_INTERCEPTOR_NAME = "external-workflowhooker"


def external_workflowhooker_available() -> bool:
    """True, wenn das Modul installiert ist UND kein Rollback-Schalter gesetzt ist."""
    if os.environ.get(ROLLBACK_ENV, "").strip().lower() in _OFF_VALUES:
        return False
    try:
        return importlib.util.find_spec(WORKFLOWHOOKER_MODULE) is not None
    except (ImportError, ValueError):
        return False


def _default_config_path() -> Path:
    try:
        from .bach_paths import BACH_DB
        base = Path(BACH_DB).parent
    except Exception:
        base = Path.home() / ".bach"
    return base / "workflowhooker.toml"


class ExternalWorkflowInterceptor:
    """Callable(event, context) -> list[str] | None fuer HookRegistry.emit."""

    def __init__(self, project_dir: Optional[str | Path] = None,
                 config_path: Optional[str | Path] = None,
                 state_dir: Optional[str | Path] = None,
                 events: tuple[str, ...] = DEFAULT_EVENTS,
                 checks: tuple[str, ...] = DEFAULT_CHECKS,
                 session_id: str = "bach-runtime"):
        resolved = {}
        missing = []
        for logical, (submodule, attr) in _REQUIRED_SYMBOLS.items():
            try:
                sub = importlib.import_module(f"{WORKFLOWHOOKER_MODULE}.{submodule}")
                resolved[logical] = getattr(sub, attr)
            except (ImportError, AttributeError):
                missing.append(f"{submodule}.{attr}")
        if missing:
            raise RuntimeError(
                f"workflowhooker-Contract verletzt, fehlende Symbole: {missing}"
            )
        self._mod = resolved
        self._runner = resolved["_run_active_checks"]

        cfg = None
        path = Path(config_path).expanduser() if config_path else _default_config_path()
        if path and path.exists():
            try:
                cfg = self._mod["load_config"](path)
            except Exception as e:
                log.warning("workflowhooker.toml unlesbar (%s), nutze Defaults", e)
                cfg = None
        if cfg is None:
            cfg = self._mod["default_config"]()
        active = list(cfg.mode.checks) if getattr(cfg.mode, "checks", None) else []
        if not active:
            active = list(checks)
        cfg.mode.checks = active
        self._config = cfg

        self._project_dir = Path(project_dir).expanduser() if project_dir else Path.cwd()
        self._state_dir = Path(state_dir).expanduser() if state_dir else None
        self._session_id = session_id
        self._events = tuple(events)
        self._state = None
        self._state_loaded = False

    # -- State (persistiert, damit Budget/Cooldown sitzungsuebergreifend greift)

    def _state_path(self) -> Path:
        return self._mod["state_path_for_session"](self._session_id, self._state_dir)

    def _load_state(self):
        if self._state_loaded:
            return self._state
        path = self._state_path()
        if path.exists():
            try:
                self._state = self._mod["SessionState"].load(path)
            except Exception as e:
                log.warning("workflowhooker-State unlesbar (%s), starte neu", e)
        if self._state is None:
            self._state = self._mod["SessionState"]()
        self._state_loaded = True
        return self._state

    def _save_state(self) -> None:
        try:
            path = self._state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._state.save(path)
        except Exception as e:  # State ist Optimierung, kein Muss
            log.warning("workflowhooker-State nicht schreibbar: %s", e)

    # -- Interceptor-Pfad ---------------------------------------------------

    def __call__(self, event: str, context: dict) -> Optional[list]:
        """Laesst die aktiven Checks laufen; Budget/Cooldown/Idle im Modul."""
        if not external_workflowhooker_available():
            return None
        if event not in self._events:
            return None
        if not self._config.mode.checks:
            return None
        try:
            state = self._load_state()
            message = self._runner(self._config, self._project_dir, state)
        except Exception as e:
            log.warning("workflowhooker-Interceptor fehlgeschlagen (fail-soft): %s", e)
            return None
        self._save_state()
        if not message:
            return None
        return [str(message)]


_interceptor_installed = False


def install_workflow_interceptor(registry) -> bool:
    """Haengt den Interceptor idempotent an die HookRegistry an.

    registry: HookRegistry-Instanz (core/hooks.py). Rueckgabe False, wenn
    Modul fehlt, Rollback aktiv oder Registry den Slot ablehnt (Duplikat).
    """
    global _interceptor_installed
    if _interceptor_installed:
        return True
    if not external_workflowhooker_available():
        return False
    if not hasattr(registry, "register_interceptor"):
        log.warning("HookRegistry hat keinen Interceptor-Slot (core/hooks.py zu alt?)")
        return False
    try:
        interceptor = ExternalWorkflowInterceptor(
            project_dir=_bach_repo_root(),
        )
    except Exception as e:
        log.warning("workflowhooker-Seam fail-closed: %s", e)
        return False
    ok = registry.register_interceptor(interceptor, name=_INTERCEPTOR_NAME, priority=90)
    if ok:
        _interceptor_installed = True
        log.info("workflowhooker-Interceptor aktiv (Checks: %s)", ", ".join(interceptor._config.mode.checks))
    return bool(ok)


def _bach_repo_root() -> Path:
    """Repo-Root von hub/ aus (Git-/Files-Quellen beziehen darauf ihren Zustand)."""
    try:
        from .bach_paths import BACH_ROOT
        return Path(BACH_ROOT)
    except Exception:
        return Path(__file__).resolve().parent.parent.parent


def reset_interceptor_install_state() -> None:
    """Nur fuer Tests."""
    global _interceptor_installed
    _interceptor_installed = False