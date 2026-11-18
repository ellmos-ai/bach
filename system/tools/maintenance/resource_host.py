# SPDX-License-Identifier: MIT
"""Explicit single-authority resource host, using reviewed private configuration."""
from __future__ import annotations

import argparse
import json
import signal
import sys
from contextlib import suppress
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[2]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    host = None
    try:
        from hub._services.chat.resource_model_port import GuardedModelPort
        from hub._services.ocean_resources_provider import load_verified
        modules = load_verified(("ocean_resources.configuration",))
        host = modules["ocean_resources.configuration"].ConfiguredHost(
            args.config, args.sha256, model_port_factory=GuardedModelPort)
        def stop(_signum, _frame):
            host.service.stop()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print(json.dumps({"state": "LISTENING", "host_id": host.writer.host_id,
                          "authority_id": host.writer.authority_id, "port": host.service.port}), flush=True)
        host.serve_forever()
        host.close()
        return 0
    except Exception:  # noqa: BLE001 - fail closed without leaking configuration/HTTP detail
        # Shutdown never assumes a dead client or service means released RAM.
        # A pending execution journal fences the next writer until reconciliation.
        if host is not None:
            with suppress(Exception):  # Original HOLD remains; native journal is never cleared here.
                host.close()
        print(json.dumps({"state": "HOLD", "reason": "resource_host_configuration_or_lifecycle_unverified"}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
