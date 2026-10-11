# SPDX-License-Identifier: MIT
"""CLI/API handler for side-effect-free subscription-agent prompt previews."""
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseHandler
from ._services.subscription_agents_composer import (
    MAX_REQUEST_BYTES, SubscriptionAgentsComposer,
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Doppelte JSON-Felder sind nicht zulässig")
        result[key] = value
    return result


def _read_request(path_text: str) -> dict:
    try:
        path = Path(path_text).expanduser()
        with path.open("rb") as source:
            raw = source.read(MAX_REQUEST_BYTES + 1)
    except OSError:
        raise ValueError("Request-Datei ist nicht lesbar") from None
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("Request-Datei überschreitet 256 KB")
    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ValueError("Request-Datei muss gültiges UTF-8-JSON mit eindeutigen Feldern enthalten") from None
    if not isinstance(request, dict):
        raise ValueError("Request-Datei muss ein JSON-Objekt enthalten")
    return request


class SubscriptionAgentsHandler(BaseHandler):
    @property
    def profile_name(self):
        return "subscription_agents"

    @property
    def target_file(self):
        return self._canonical_db

    def get_operations(self):
        return {"compose": "Versionierte Onboarding-Promptvorschau aus aktuellen BACH-Quellen erstellen"}

    def handle(self, operation, args, dry_run=False):
        args = list(args or ())
        if (operation != "compose" or len(args) != 1 or not isinstance(args[0], str)
                or not args[0] or args[0].startswith("-")):
            return False, "bach subscription_agents compose <Request-JSON-Datei>"
        try:
            request = _read_request(args[0])
            result = SubscriptionAgentsComposer(task_db_path=self._canonical_db).compose(request)
            return True, json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            return False, str(exc)

