"""Portable service entrypoint; paths come from this checkout and native config."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[2]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def load_handler():
    """Load the handler and its maintenance coordinator from this checkout."""
    from hub import scheduler
    from hub._services.docs import maintenance_cli

    root = SYSTEM_ROOT.resolve()
    for module_path in (scheduler.__file__, maintenance_cli.__file__):
        if not Path(module_path).resolve().is_relative_to(root):
            raise RuntimeError("maintenance_bootstrap_origin_unverified")
    return scheduler.SchedulerHandler


def _serve_target():
    """Accept only the configured local TaskDB-derived runtime for serve."""
    if len(sys.argv) < 2 or sys.argv[1] != "serve":
        return None
    configured_db = os.environ.get("BACH_DB")
    if not configured_db:
        return None
    task_db = Path(configured_db).expanduser()
    if not task_db.is_absolute():
        return None
    runtime = task_db.parent / "maintenance"
    expected = {
        "--runtime-dir": runtime.resolve(),
        "--config": (runtime / "config.json").resolve(),
    }
    args = sys.argv[2:]
    if any(
        value.startswith(flag + "=")
        for flag in expected
        for value in args
    ):
        return None
    for flag, target in expected.items():
        positions = [index for index, value in enumerate(args) if value == flag]
        if len(positions) > 1:
            return None
        if positions:
            index = positions[0]
            if index + 1 >= len(args):
                return None
            try:
                if Path(args[index + 1]).expanduser().resolve() != target:
                    return None
            except (OSError, RuntimeError, ValueError):
                return None
    return task_db, runtime


def _path_has_symlink(path):
    current = Path(path)
    while True:
        if current.is_symlink():
            return True
        if current == current.parent:
            return False
        current = current.parent


def _write_startup_failure(phase, error):
    try:
        target = _serve_target()
        if target is None:
            return False
        task_db, runtime = target
        if _path_has_symlink(task_db) or _path_has_symlink(runtime):
            return False
        task_db = task_db.resolve()
        runtime = runtime.resolve()
        config_path = runtime / "config.json"
        if (
            _path_has_symlink(config_path)
            or not config_path.is_file()
            or config_path.resolve().parent != runtime
        ):
            return False

        from hub._services.docs import maintenance_runtime

        system_root = SYSTEM_ROOT.resolve()
        runtime_source = Path(maintenance_runtime.__file__).resolve()
        expected_runtime_source = (
            system_root / "hub/_services/docs/maintenance_runtime.py"
        ).resolve()
        if runtime_source != expected_runtime_source:
            return False
        config = maintenance_runtime.load_config(config_path)
        guard = maintenance_runtime.CanonicalLockGuard(config)

        helper_path = SYSTEM_ROOT / "hub/_services/docs/maintenance_failure.py"
        if (
            helper_path.is_symlink()
            or not helper_path.is_file()
            or helper_path.stat().st_size > 32768
            or not helper_path.resolve().is_relative_to(system_root)
        ):
            return False
        spec = importlib.util.spec_from_file_location(
            "_bach_docs_maintenance_failure", helper_path
        )
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.write_failure_receipt(
            runtime,
            system_root.parent,
            phase,
            error,
            guard=guard,
            task_db=task_db,
        )
    except Exception:  # noqa: BLE001 - preserve primary failure and redact diagnostics
        return False


def main():
    phase = "handler_import"
    try:
        handler_type = load_handler()
        phase = "handler_init"
        handler = handler_type(SYSTEM_ROOT)
    except Exception as error:  # noqa: BLE001 - print only safe startup diagnostics
        name = type(error).__name__
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            name = "Exception"
        receipt = "written" if _write_startup_failure(phase, error) else "unavailable"
        print(
            f"maintenance failure phase={phase} exception={name} receipt={receipt}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    phase = "handler_dispatch"
    try:
        ok, result = handler.handle("maintenance", sys.argv[1:])
        print(result)
        return 0 if ok else 1
    except Exception as error:  # noqa: BLE001 - keep unexpected dispatch failures private
        name = type(error).__name__
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            name = "Exception"
        receipt = "written" if _write_startup_failure(phase, error) else "unavailable"
        print(
            f"maintenance failure phase={phase} exception={name} receipt={receipt}",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
