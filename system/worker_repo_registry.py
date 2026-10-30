"""Stub-Implementierung fuer den Worker-Repo-Registry-Scope.

Dieses Modul ist ein minimaler Stub, der die von
`system/tests/test_worker_scope_snapshot.py` erwarteten Kandidaten-
Funktionen bereitstellt. Es liest ausschliesslich aus der unter
``$HOME/.bach/worker_repo_registry.v1.json`` liegenden Test-Registry
und liefert Reasoncode-Scaffolding zurueck.
"""

import json
import os
from pathlib import Path


REGISTRY_NAME = "worker_repo_registry.v1.json"


def _registry_path() -> Path:
    home = os.environ.get("HOME")
    if not home:
        raise RuntimeError("HOME ist nicht gesetzt")
    return Path(home) / ".bach" / REGISTRY_NAME


def _load_registry() -> dict:
    path = _registry_path()
    if not path.exists():
        raise FileNotFoundError(f"Registry nicht gefunden: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _new_scope_repo() -> dict:
    """Lade die isolierte Registry und gib einen Reasoncode-Scaffold zurueck.

    Die Funktion erwartet keine Argumente und liest die Registry aus
    ``$HOME/.bach/worker_repo_registry.v1.json``.
    """
    data = _load_registry()
    return {
        "scope": "repo",
        "reason": "isolated_registry_loaded",
        "code": "SCOPE_REPO_OK",
        "registry_binding": data.get("binding"),
        "registry_version": data.get("version"),
    }


def _install_lock_scanner() -> dict:
    """Gib einen Reasoncode-Scaffold fuer den Lock-Scanner zurueck.

    Dieser Stub fuehrt keine echten Dateisystem-Operationen durch.
    """
    return {
        "scope": "lock_scanner",
        "reason": "lock_scanner_stub_installed",
        "code": "LOCK_SCANNER_OK",
    }
