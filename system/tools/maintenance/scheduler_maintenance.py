"""Portable service entrypoint; paths come from this checkout and native config."""

from __future__ import annotations

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
        print(
            f"maintenance failure phase={phase} exception={name}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    ok, result = handler.handle("maintenance", sys.argv[1:])
    print(result)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
