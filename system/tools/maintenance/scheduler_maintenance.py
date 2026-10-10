"""Portable service entrypoint; paths come from this checkout and native config."""

from __future__ import annotations

import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[2]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def main():
    from hub.scheduler import SchedulerHandler

    handler = SchedulerHandler(SYSTEM_ROOT)
    ok, result = handler.handle("maintenance", sys.argv[1:])
    print(result)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
