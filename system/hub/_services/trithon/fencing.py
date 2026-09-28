"""Trithon Phase 5: Authentisierte Nodes, Epochen, Lead-Terme und Fencing.

Fail-closed durchgehend: fehlende oder unlesbare State-Dateien fuehren zu
Ablehnung statt zu stiller Zulassung. Baut bewusst NICHT auf
routing_contract-Exceptions auf (eigenes FencingError).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class FencingError(Exception):
    """Fehler beim Lead-Claim / Fencing (stale Term, Auth-Fehler, ...)."""


NODES_FILE = "nodes.json"
TERM_FILE = "term.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Optional[dict]:
    """JSON lesen; bei fehlender/kaputter Datei None (fail-closed)."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_nodes(state_dir: str | Path) -> dict:
    """nodes.json laden; fehlt sie -> leere Node-Menge (fail-closed)."""
    data = _read_json(Path(state_dir) / NODES_FILE)
    if data is None:
        return {"nodes": {}}
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        return {"nodes": {}}
    return {"nodes": nodes}


def save_nodes(state_dir: str | Path, data: dict) -> None:
    _write_json_atomic(Path(state_dir) / NODES_FILE, data)


def register_node(state_dir: str | Path, node_id: str, token: str, salt: Optional[str] = None) -> dict:
    """Node mit Secret registrieren. Gibt den Node-Eintrag zurueck."""
    if not node_id or not token:
        raise FencingError("node_id und token sind erforderlich")
    data = load_nodes(state_dir)
    entry = {
        "node_id": node_id,
        "token": token,
        "salt": salt,
        "registered_at": _utc_now(),
    }
    data["nodes"][node_id] = entry
    save_nodes(state_dir, data)
    return entry


def authenticate(state_dir: str | Path, node_id: str, token: str) -> bool:
    """Prueft node_id/token. Fail-closed: unbekannte Nodes werden abgelehnt."""
    if not node_id or not token:
        return False
    nodes = load_nodes(state_dir)["nodes"]
    entry = nodes.get(node_id)
    if not isinstance(entry, dict):
        return False
    stored = entry.get("token")
    if not isinstance(stored, str):
        return False
    return stored == token


def _load_term(state_dir: str | Path) -> dict:
    data = _read_json(Path(state_dir) / TERM_FILE)
    if data is None:
        return {"term": 0, "epoch": 0, "leader": None, "fencing_token": None}
    term = data.get("term")
    if not isinstance(term, int) or term < 0:
        term = 0
    epoch = data.get("epoch")
    if not isinstance(epoch, int) or epoch < 0:
        epoch = 0
    return {
        "term": term,
        "epoch": epoch,
        "leader": data.get("leader"),
        "fencing_token": data.get("fencing_token"),
    }


def current_term(state_dir: str | Path) -> int:
    """Aktueller Lead-Term (0 = noch nie ein Lead gewaehlt)."""
    return _load_term(state_dir)["term"]


def current_epoch(state_dir: str | Path) -> int:
    return _load_term(state_dir)["epoch"]


def bump_epoch(state_dir: str | Path) -> int:
    """Neue Epoche markieren (Term bleibt erhalten, monoton ueber Epochen hinweg)."""
    state = _load_term(state_dir)
    state["epoch"] += 1
    state["updated_at"] = _utc_now()
    _write_json_atomic(Path(state_dir) / TERM_FILE, state)
    return state["epoch"]


def _fencing_token(node_id: str, term: int, salt: Optional[str]) -> str:
    raw = f"{salt or ''}:{node_id}:{term}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def claim_lead(
    state_dir: str | Path,
    node_id: str,
    token: str,
    term: Optional[int] = None,
) -> dict:
    """Lead uebernehmen. Authentisiert, monoton steigender Term, Fencing-Token.

    term=None -> aktueller Term + 1. Expliziter Term muss strikt groesser sein
    als der bisherige, sonst FencingError (stale Term / Split-Brain-Schutz).
    """
    if not authenticate(state_dir, node_id, token):
        raise FencingError(f"Node '{node_id}' ist nicht authentisiert")
    state = _load_term(state_dir)
    new_term = state["term"] + 1 if term is None else term
    if not isinstance(new_term, int) or new_term <= state["term"]:
        raise FencingError(
            f"Stale Term: {new_term} <= aktueller Term {state['term']}"
        )
    salt = load_nodes(state_dir)["nodes"].get(node_id, {}).get("salt")
    fencing = _fencing_token(node_id, new_term, salt)
    record = {
        "term": new_term,
        "epoch": state["epoch"],
        "leader": node_id,
        "fencing_token": fencing,
        "updated_at": _utc_now(),
    }
    _write_json_atomic(Path(state_dir) / TERM_FILE, record)
    return {
        "leader": node_id,
        "term": new_term,
        "epoch": state["epoch"],
        "fencing_token": fencing,
        "salt": salt,
    }


def check_fencing(state_dir: str | Path, term: int, fencing_token: str) -> bool:
    """True, wenn (term, fencing_token) dem aktuellen Lead entspricht."""
    if not isinstance(term, int) or not fencing_token:
        return False
    state = _load_term(state_dir)
    if state["leader"] is None:
        return False
    return state["term"] == term and state["fencing_token"] == fencing_token
