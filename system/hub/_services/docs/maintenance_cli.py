"""Explicit CLI activation; read/plan never start a scheduler or create jobs."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from .maintenance_runtime import (
    CONFIG_SCHEMA,
    CanonicalLockGuard,
    MaintenanceRuntime,
    load_config,
    readonly_status,
    validate_config,
)


def handle(handler, args, dry_run=False):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("status", "plan", "launch-plan", "configure", "tick", "serve"),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--lock-tools-root", type=Path)
    parser.add_argument("--protected-root", type=Path, action="append", default=[])
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--assigned-slot")
    parser.add_argument("--required-model")
    parser.add_argument("--enable", action="store_true")
    try:
        options = parser.parse_args(args)
    except SystemExit:
        return False, "Ungültige Wartungsoptionen"
    root = handler.base_path.parent.resolve()
    runtime = (
        (options.runtime_dir or handler.user_db.parent / "maintenance")
        .expanduser()
        .resolve()
    )
    config_path = (options.config or runtime / "config.json").expanduser().resolve()
    canonical_runtime = (handler.user_db.parent / "maintenance").resolve()
    if options.action in {"configure", "tick", "serve", "launch-plan"} and (
        runtime != canonical_runtime or config_path != canonical_runtime / "config.json"
    ):
        return (
            False,
            "Wartungsbetrieb verlangt kanonische Runtime und Konfiguration der TaskDB",
        )
    if options.action == "status":
        return True, json.dumps(
            readonly_status(runtime, root=root, config_path=config_path),
            ensure_ascii=False,
        )
    if options.action == "launch-plan":
        from .maintenance_launch import launch_plan

        try:
            return True, json.dumps(
                launch_plan(
                    root,
                    # Resolving a venv symlink selects global Python and loses
                    # the installed consumer dependencies at service startup.
                    Path(sys.executable).absolute(),
                    handler.user_db.resolve(),
                    runtime,
                    config_path,
                ),
                ensure_ascii=False,
            )
        except (OSError, ValueError):
            return False, "Installierte Pfade für den Wartungsstart nicht bestätigt"
    if options.action in {"plan", "configure"}:
        tools = options.lock_tools_root
        if tools is None and os.environ.get("BACH_LOCK_TOOLS_ROOT"):
            tools = Path(os.environ["BACH_LOCK_TOOLS_ROOT"])
        plan = {
            "schema": CONFIG_SCHEMA,
            "enabled": options.enable,
            "interval_seconds": options.interval_seconds,
            "poll_seconds": options.poll_seconds,
            "min_available_mib": 512,
            "max_state_db_bytes": 67108864,
            "lock_tools_root": str(tools.expanduser().resolve()) if tools else None,
            "protected_roots": list(
                dict.fromkeys(
                    str(p.resolve())
                    for p in [root, handler.user_db.parent, *options.protected_root]
                )
            ),
            "worker_binding": {
                key: value
                for key, value in {
                    "assigned_slot": options.assigned_slot,
                    "required_model": options.required_model,
                }.items()
                if value
            },
        }
        if options.action == "plan" or dry_run:
            return True, json.dumps(
                {
                    "configuration": plan,
                    "applied": False,
                    "activation_requires_explicit_enable": True,
                },
                ensure_ascii=False,
            )
        if tools is None or not options.protected_root:
            return (
                False,
                "Lock-Werkzeuge und OneDrive-/Projektzwilling explizit angeben",
            )
        guard = CanonicalLockGuard(plan)
        try:
            validate_config(plan)
            guard(config_path)
            if config_path.exists() or config_path.is_symlink():
                return (
                    False,
                    "Bestehende Wartungskonfiguration wird nicht überschrieben",
                )
            if any(p.is_symlink() for p in config_path.parents):
                raise PermissionError("Invalid configuration path")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            guard(config_path)
            with config_path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(plan, ensure_ascii=False, indent=2))
            load_config(config_path)
            return True, json.dumps(
                {"configured": True, "enabled": plan["enabled"], "started": False}
            )
        except (OSError, ValueError):
            return (
                False,
                "Wartungskonfiguration nicht bestätigt; Locks/Pfade/Budget prüfen",
            )
    if dry_run:
        return True, json.dumps({"applied": False, "started": False})
    try:
        config = load_config(config_path)
        if not config["enabled"]:
            return False, "Wartungsbetrieb ist nicht ausdrücklich aktiviert"
        runtime_service = MaintenanceRuntime(
            root, handler._external_state_db(), runtime, config_path
        )
        if options.action == "tick":
            return True, json.dumps(runtime_service.tick(), ensure_ascii=False)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: runtime_service.stop_event.set())
        runtime_service.serve()
        return True, "Wartungsbetrieb beendet"
    except Exception:  # noqa: BLE001 - CLI boundary must not disclose native credential-bearing errors
        return (
            False,
            "Wartungsbetrieb nicht bestätigt; Konfiguration, Ownership und Provider prüfen",
        )
