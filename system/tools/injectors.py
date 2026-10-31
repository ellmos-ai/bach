#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: injectors
Version: 2.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-10-31
Anthropic-Compatible: True

Description:
    Duenner Injektor-Adapter ueber den memoryhooker-Seam (hub/memory_hook_provider.py)
    und TimeManager.timebeat() (S3-Nachlauf T-20260926-537523074).

    Oeffentliches API (InjectorSystem, InjectorConfig, TimeInjector, ToolInjector.get_startup_reminder,
    TaskAssigner) bleibt fuer bach_api.injector und hub/inject.py unveraendert;
    Strategy, Context, Tool-Warn und Between laufen ausschliesslich ueber context_triggers
    in der BACH-DB und den memoryhooker-Seam.
"""

from __future__ import annotations

__version__ = "2.0.0"
__author__ = "BACH Team"

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


class InjectorConfig:
    """Konfiguration fuer Injektoren (config.json -> 'injectors')."""

    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.config = self._load()

    def _load(self) -> dict:
        default = {
            "strategy_injector": True,
            "context_injector": True,
            "time_injector": True,
            "between_injector": True,
            "timebeat_interval": 60,
        }

        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    default.update(loaded.get("injectors", {}))
            except (json.JSONDecodeError, OSError):
                pass

        return default

    def save(self) -> None:
        try:
            full_config = {}
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    full_config = json.load(f)

            full_config["injectors"] = self.config

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(full_config, f, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, OSError):
            pass

    def toggle(self, injector: str) -> bool:
        if injector in self.config:
            self.config[injector] = not self.config[injector]
            self.save()
            return self.config[injector]
        return False

    def is_enabled(self, injector: str) -> bool:
        return self.config.get(injector, False)


class ToolInjector:
    """Erinnert an verfuegbare Tools bei Session-Start.

    Die fruehere Duplikat-Warnung (check_before_create) laeuft seit S3 ueber
    context_triggers (source='tool_warn', Seed: Migration 046) im memoryhooker-Seam.
    """

    TOOL_CATEGORIES = {
        "OCR & Dokumente": [
            "tools/c_ocr_engine.py - Tesseract + PyMuPDF OCR",
            "tools/doc_search.py - Dokumentensuche (DB + Dateisystem)",
            "skills/_services/document/scanner_service.py - Inbox-Scanner",
            "skills/_services/document/ocr_service.py - OCR-Service",
        ],
        "Daten-Import/Export": [
            "tools/data_importer.py - Generischer CSV/JSON Import (Schema-Erkennung, Rollback)",
            "tools/folder_diff_scanner.py - Ordner-Ueberwachung mit Diff",
        ],
        "Domain-Handler (bach CLI)": [
            "bach steuer - Steuer (status, beleg, posten, export)",
            "bach haushalt - Haushalt (due, routinen, fixkosten, insurance-check, einkauf)",
            "bach gesundheit - Gesundheit (diagnosen, medikamente, labor, termine)",
            "bach contact - Kontakte (list, search, add, birthday)",
            "bach abo - Abos (list, check, export)",
        ],
        "Generatoren": [
            "tools/cv_generator.py - Lebenslauf aus Ordnerstruktur + DB",
            "tools/mcp_server.py - MCP-Server fuer IDE-Integration",
        ],
    }

    @classmethod
    def get_startup_reminder(cls, base_path: Path = None) -> str:
        """Gibt Tool-Uebersicht fuer Session-Start zurueck."""
        lines = ["[VERFUEGBARE TOOLS - Deine Haende]"]

        tool_count = 0
        try:
            import sqlite3
            system_root = Path(__file__).resolve().parent.parent
            try:
                from hub.bach_paths import BACH_DB
                db = Path(BACH_DB)
                if base_path:
                    local_db = base_path / "data" / "bach.db"
                    if local_db.exists() and base_path.resolve() not in (system_root, system_root.parent):
                        db = local_db
            except ImportError:
                db = (base_path / "data" / "bach.db") if base_path else (Path.home() / ".bach" / "bach.db")

            if db.exists():
                conn = sqlite3.connect(str(db))
                tool_count = conn.execute(
                    "SELECT COUNT(*) FROM tools WHERE is_available = 1"
                ).fetchone()[0]
                conn.close()
        except Exception:
            pass

        if tool_count:
            lines.append(f"  {tool_count} Tools in bach.db registriert")

        for category, tools in cls.TOOL_CATEGORIES.items():
            lines.append(f"  {category}:")
            for tool in tools:
                lines.append(f"    - {tool}")

        lines.append("")
        lines.append("  Tool-Suche:   bach tools search <begriff>")
        lines.append("  Tool-Hilfe:   docs/help/tools/<toolname>.txt (100+ Hilfe-Dateien)")
        lines.append("  Tool-DB:      bach tools list (alle registrierten Tools)")
        lines.append("  Empfehlung:   bach tool suggest '<beschreibung>'")
        return "\n".join(lines)


class TimeInjector:
    """Regelmaessige Zeit-Updates (Timebeat) via tools.time_system.TimeManager."""

    def __init__(self, interval: int = 60, base_path: Path = None):
        self.interval = interval
        self.base_path = base_path
        self.manager = None
        if base_path:
            try:
                from tools.time_system import TimeManager
                self.manager = TimeManager(base_path)
                self.manager.set_interval(interval)
            except (ImportError, AttributeError):
                pass

    def check(self) -> Optional[str]:
        """Timebeat, falls faellig (TimeManager.timebeat())."""
        if not self.manager:
            return None
        return self.manager.timebeat()


class TaskAssigner:
    """Automatische Aufgaben-Zuweisung."""

    def __init__(self, tasks_file: Path):
        self.tasks_file = tasks_file

    def assign(self, max_minutes: int = 5) -> Optional[dict]:
        if not self.tasks_file.exists():
            return None

        try:
            with open(self.tasks_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            tasks = data.get("tasks", [])
            open_tasks = [t for t in tasks if t.get("status") == "open"]

            if not open_tasks:
                return None

            prio_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_tasks = sorted(
                open_tasks,
                key=lambda t: prio_order.get(t.get("priority", "medium"), 2),
            )

            for task in sorted_tasks:
                desc_len = len(task.get("description", task.get("task", "")))
                estimated_min = max(2, min(15, desc_len / 50))

                if estimated_min <= max_minutes:
                    task["estimated_minutes"] = estimated_min
                    return task

            sorted_tasks[0]["estimated_minutes"] = max_minutes
            return sorted_tasks[0]

        except (json.JSONDecodeError, OSError):
            return None

    def decompose(self, task: dict) -> List[dict]:
        description = task.get("description", task.get("task", ""))
        steps = []
        numbered = re.findall(r"\d+[.)]\s*([^.!?\n]+)", description)
        if numbered:
            for i, step in enumerate(numbered, 1):
                steps.append({
                    "step": i,
                    "description": step.strip(),
                    "estimated_minutes": 3,
                })
        else:
            steps = [
                {"step": 1, "description": "Verstehen & Planen", "estimated_minutes": 2},
                {"step": 2, "description": "Implementieren", "estimated_minutes": 5},
                {"step": 3, "description": "Testen & Dokumentieren", "estimated_minutes": 3},
            ]
        return steps


class InjectorSystem:
    """Duenner Adapter fuer alle Injektoren (Seam + TimeManager)."""

    def __init__(self, base_path: Path, db_path: Optional[Path] = None):
        self.base_path = Path(base_path)
        self.db_path = Path(db_path) if db_path else None
        self.config = InjectorConfig(self.base_path / "config.json")
        self.time_injector = TimeInjector(self.config.config.get("timebeat_interval", 60), self.base_path)
        self.task_assigner = TaskAssigner(self.base_path / "DATA" / "tasks.json")
        self._tool_reminder_shown = False
        self._hook = None
        self._state = None

    def _resolve_db_path(self) -> Path:
        if self.db_path is not None:
            return Path(self.db_path)
        system_root = Path(__file__).resolve().parent.parent
        if str(system_root) not in sys.path:
            sys.path.insert(0, str(system_root))
        try:
            from hub.bach_paths import BACH_DB
            db = Path(BACH_DB)
        except Exception:
            db = Path.home() / ".bach" / "bach.db"
        if self.base_path:
            local_db = self.base_path / "data" / "bach.db"
            if local_db.exists() and self.base_path.resolve() not in (system_root, system_root.parent):
                return local_db
        return db

    def _get_seam(self):
        system_root = Path(__file__).resolve().parent.parent
        if str(system_root) not in sys.path:
            sys.path.insert(0, str(system_root))
        from hub.memory_hook_provider import ExternalMemoryHook, external_memoryhooker_available

        if not external_memoryhooker_available():
            return None, None
        db_path = self._resolve_db_path()
        if self._hook is None or self._hook.backend.db_path != db_path:
            try:
                self._hook = ExternalMemoryHook(
                    db_path=db_path,
                    config_path=self.base_path / "data" / "memoryhooker.toml",
                )
                self._state = self._hook._mod["SessionState"]()
            except Exception as exc:
                log.warning("InjectorSystem Seam-Initialisierung fehlgeschlagen: %s", exc)
                return None, None
        return self._hook, self._state

    def _disabled_injectors(self) -> frozenset:
        from hub.memory_hook_provider import INJECTOR_SWITCHES
        return frozenset(
            key for key, switch in INJECTOR_SWITCHES.items()
            if not self.config.is_enabled(switch)
        )

    def process(self, text: str, context: dict = None, skip=(), cli_hints: bool = True) -> List[str]:
        """Verarbeitet Text durch den memoryhooker-Seam + TimeManager."""
        injections: List[str] = []
        skip_set = set(skip or ())

        hook, state = self._get_seam()
        if hook is not None and state is not None:
            from hub.memory_hook_provider import CLI_ONLY_INJECTORS
            active_keys = hook.handled_injectors() - self._disabled_injectors() - skip_set - CLI_ONLY_INJECTORS
            if active_keys:
                try:
                    injections.extend(
                        hook._trigger_hints(text, state, active_keys, cli_hints=cli_hints)
                    )
                except Exception as exc:
                    log.warning("InjectorSystem Seam-Aufruf fehlgeschlagen: %s", exc)

        if self.config.is_enabled("time_injector") and "time" not in skip_set:
            time_msg = self.time_injector.check()
            if time_msg:
                injections.append(time_msg)

        return injections

    def get_tool_reminder(self) -> Optional[str]:
        """Gibt Tool-Erinnerung fuer Session-Start zurueck (einmalig)."""
        if not self._tool_reminder_shown:
            self._tool_reminder_shown = True
            return ToolInjector.get_startup_reminder(self.base_path)
        return None

    def check_between(self, last_command: str, session_ending: bool = False) -> Optional[str]:
        """Prueft Between-Tasks Erinnerung ueber den memoryhooker-Seam (Cooldown: 3 Min)."""
        if session_ending or not self.config.is_enabled("between_injector"):
            return None
        hook, state = self._get_seam()
        if hook is None or state is None:
            return None
        if "between" not in hook.handled_injectors():
            return None
        try:
            hints = hook._trigger_hints(last_command or "", state, {"between"}, cli_hints=True)
            return hints[0] if hints else None
        except Exception as exc:
            log.warning("InjectorSystem Between-Aufruf fehlgeschlagen: %s", exc)
            return None

    def is_on_cooldown(self, injector_name: str) -> bool:
        """Prueft ob ein Injektor im aktuellen Seam-State im Cooldown ist."""
        return self._cooldown_remaining(injector_name) > 0

    def _cooldown_remaining(self, cd_key: str) -> int:
        system_root = Path(__file__).resolve().parent.parent
        if str(system_root) not in sys.path:
            sys.path.insert(0, str(system_root))
        from hub.memory_hook_provider import HOOKER_INJECTORS, _CLI_STATE_FILENAME

        cooldown_sec = HOOKER_INJECTORS.get(cd_key, 120)
        last_ts = None
        if self._state is not None:
            last_ts = self._state.trigger_last_ts.get(cd_key)
        if last_ts is None:
            state_file = self._resolve_db_path().parent / _CLI_STATE_FILENAME
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    last_ts = (data.get("trigger_last_ts") or {}).get(cd_key)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
        if last_ts is None:
            return 0
        try:
            import memoryhooker.triggers as mht
            now_ts = mht.time.time()
        except Exception:
            now_ts = time.time()
        try:
            remaining = cooldown_sec - (now_ts - float(last_ts))
            return max(0, int(remaining))
        except (TypeError, ValueError):
            return 0

    def assign_task(self, max_minutes: int = 5) -> Tuple[bool, str]:
        task = self.task_assigner.assign(max_minutes)
        if not task:
            return False, "Keine passende Aufgabe gefunden."

        result = f"""[AUFGABE ZUGEWIESEN]
ID: {task.get('id', '?')}
Task: {task.get('task', '')[:60]}
Priorität: {task.get('priority', 'medium')}
Geschätzt: ~{task.get('estimated_minutes', '?')} Min

Zu komplex? Nutze: --task decompose {task.get('id', '')}"""

        return True, result

    def decompose_task(self, task_id: str) -> Tuple[bool, str]:
        tasks_file = self.base_path / "DATA" / "tasks.json"
        if not tasks_file.exists():
            return False, "Keine Tasks-Datei"

        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            task = None
            for t in data.get("tasks", []):
                if t.get("id") == task_id:
                    task = t
                    break

            if not task:
                return False, f"Task {task_id} nicht gefunden"

            steps = self.task_assigner.decompose(task)
            result = f"[AUFGABE ZERLEGT: {task_id}]\n\n"
            for step in steps:
                result += f"  {step['step']}. {step['description']} (~{step['estimated_minutes']} Min)\n"

            return True, result

        except Exception as e:
            return False, f"Fehler: {e}"

    def toggle(self, injector: str) -> Tuple[bool, str]:
        valid = ["strategy_injector", "context_injector", "time_injector", "between_injector"]
        if injector not in valid:
            return False, f"Unbekannter Injektor. Verfügbar: {', '.join(valid)}"

        new_state = self.config.toggle(injector)
        status = "AN" if new_state else "AUS"
        return True, f"{injector}: {status}"

    def status(self) -> str:
        lines = ["[INJEKTOR-STATUS]", ""]
        cooldown_map = {
            "strategy_injector": "strategy",
            "context_injector": "context",
            "between_injector": "between",
        }

        for key, value in self.config.config.items():
            if key.endswith("_injector"):
                status = "AN" if value else "AUS"
                name = key.replace("_injector", "").title()

                cd_key = cooldown_map.get(key)
                if cd_key:
                    remaining = self._cooldown_remaining(cd_key)
                    if remaining > 0:
                        status += f" (Cooldown: {remaining}s)"

                lines.append(f"  {name:12} {status}")

        lines.append("")
        lines.append("Toggle: --inject toggle <name>")
        lines.append("Cooldowns: strategy=2min, context=1min, between=3min")
        return "\n".join(lines)
