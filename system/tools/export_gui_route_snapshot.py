"""Export the backend routes as `METHOD /path` lines for the GUI route-contract test (PB-2, #3986).

The GUI repo cannot import the backend, so it keeps a snapshot (`tests/fixtures/backend-routes.v1.json`) and
fails when a page calls a route that is not in it. Regenerate after route changes:

    PYTHONIOENCODING=utf-8 python tools/export_gui_route_snapshot.py <ellmos-system-gui>/tests/fixtures/backend-routes.v1.json
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PROXY = "/api/chat-control/{control_path}"


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path)


def build_snapshot() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from gui import server
        spec_paths = server.app.openapi()["paths"]
        routes = {f"{m.upper()} {_norm(p)}" for p, ops in spec_paths.items() for m in ops if m.upper() in _METHODS}
        for route in server.app.routes:
            for m in getattr(route, "methods", None) or ():
                if m in _METHODS:
                    routes.add(f"{m} {_norm(getattr(route, 'path', ''))}")
        # the proxy forwards a fixed whitelist: list the real paths, not the wildcard
        routes = {r for r in routes if not r.endswith(" " + _norm(_PROXY))}
        for sub in sorted(server.CHAT_CONTROL_PATHS):
            routes.update({f"GET /api/chat-control/{sub}", f"POST /api/chat-control/{sub}"})
    return {"schema": "bach.gui-route-snapshot.v1", "routes": sorted(routes)}


if __name__ == "__main__":
    text = json.dumps(build_snapshot(), indent=1, ensure_ascii=False) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
