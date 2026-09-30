"""Trithon Phase 5: Authentisierte Nodes, Epochen, Lead-Terme und Fencing.

Fail-closed durchgehend: fehlende oder unlesbare State-Dateien fuehren zu
Ablehnung statt zu stiller Zulassung. Baut bewusst NICHT auf
routing_contract-Exceptions auf (eigenes FencingError).

Local state only: filelock uses a Windows byte-range lock or POSIX flock on
one stable lock file. This serializes processes sharing this host-local
directory; it is not a quorum, distributed lease, or cloud-sync lock. Reads
observe atomically replaced records. Mutations hold the lock through validation
and replacement. A fresh directory is initialized during node registration;
partial, missing-existing or corrupt state requires explicit operator recovery.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout


class FencingError(Exception):
    """Fehler beim Lead-Claim / Fencing (stale Term, Auth-Fehler, ...)."""


NODES_FILE = "nodes.json"
TERM_FILE = "term.json"
LOCK_FILE = ".fencing.lock"
LOCK_TIMEOUT_SECONDS = 5


@contextmanager
def _state_lock(state_dir: str | Path):
    directory = Path(state_dir).resolve()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with FileLock(str(directory / LOCK_FILE), timeout=LOCK_TIMEOUT_SECONDS):
            yield directory
    except (OSError, Timeout) as exc:
        raise FencingError("Local fencing state is unavailable or locked") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict | None:
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
            fh.flush()
            os.fsync(fh.fileno())
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
    """Replace the node registry under the same lock as claims (operator API)."""
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        raise FencingError("Invalid node registry")
    _validate_nodes(data)
    with _state_lock(state_dir) as directory:
        _prepare_registration(directory)
        _write_json_atomic(directory / NODES_FILE, data)


def _prepare_registration(directory: Path) -> dict:
    """Initialize only a wholly fresh directory; never reset an existing term."""
    nodes_path = directory / NODES_FILE
    term_path = directory / TERM_FILE
    if not nodes_path.exists() and not term_path.exists():
        # The first file also marks an interrupted initialization. A later call
        # refuses a missing nodes file rather than silently recovering authority.
        _write_json_atomic(term_path, {"term": 0, "epoch": 0,
                                     "leader": None, "fencing_token": None})
        return {"nodes": {}}
    _load_term(directory)
    data = _read_json(nodes_path)
    if data is None or not isinstance(data.get("nodes"), dict):
        raise FencingError("Existing node registry is missing or corrupt")
    return data


def _validate_nodes(data: dict) -> None:
    for node_id, entry in data["nodes"].items():
        if (not isinstance(node_id, str) or not node_id or not isinstance(entry, dict)
                or entry.get("node_id") != node_id
                or not isinstance(entry.get("token"), str) or not entry["token"]
                or (entry.get("salt") is not None and not isinstance(entry["salt"], str))):
            raise FencingError("Invalid registered node")


def register_node(state_dir: str | Path, node_id: str, token: str, salt: str | None = None) -> dict:
    """Node mit Secret registrieren. Gibt den Node-Eintrag zurueck."""
    if (not isinstance(node_id, str) or not node_id
            or not isinstance(token, str) or not token
            or (salt is not None and not isinstance(salt, str))):
        raise FencingError("node_id und token sind erforderlich")
    entry = {
        "node_id": node_id,
        "token": token,
        "salt": salt,
        "registered_at": _utc_now(),
    }
    with _state_lock(state_dir) as directory:
        data = _prepare_registration(directory)
        _validate_nodes(data)
        data["nodes"][node_id] = entry
        _write_json_atomic(directory / NODES_FILE, data)
    return entry


def authenticate(state_dir: str | Path, node_id: str, token: str) -> bool:
    """Prueft node_id/token. Fail-closed: unbekannte Nodes werden abgelehnt."""
    if not isinstance(node_id, str) or not node_id or not isinstance(token, str) or not token:
        return False
    nodes = load_nodes(state_dir)["nodes"]
    entry = nodes.get(node_id)
    if not isinstance(entry, dict):
        return False
    stored = entry.get("token")
    if not isinstance(stored, str):
        return False
    return hmac.compare_digest(stored.encode("utf-8"), token.encode("utf-8"))


def _load_term(state_dir: str | Path) -> dict:
    data = _read_json(Path(state_dir) / TERM_FILE)
    if data is None:
        if not (Path(state_dir) / TERM_FILE).exists() and not (Path(state_dir) / NODES_FILE).exists():
            return {"term": 0, "epoch": 0, "leader": None, "fencing_token": None}
        raise FencingError("Existing term state is missing or corrupt")
    term = data.get("term")
    epoch = data.get("epoch")
    if not {"term", "epoch", "leader", "fencing_token"}.issubset(data):
        raise FencingError("Incomplete term state")
    if type(term) is not int or term < 0 or type(epoch) is not int or epoch < 0:
        raise FencingError("Invalid term or epoch")
    leader = data.get("leader")
    fence = data.get("fencing_token")
    if leader is None and fence is None:
        pass
    elif (term == 0 or not isinstance(leader, str) or not leader
          or not isinstance(fence, str) or len(fence) != 64
          or any(char not in "0123456789abcdef" for char in fence)):
        raise FencingError("Invalid leader or fencing token")
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
    with _state_lock(state_dir) as directory:
        nodes = _read_json(directory / NODES_FILE)
        if nodes is None or not isinstance(nodes.get("nodes"), dict):
            raise FencingError("Register a node before changing the epoch")
        _validate_nodes(nodes)
        state = _load_term(directory)
        state["epoch"] += 1
        state["leader"] = None
        state["fencing_token"] = None
        state["updated_at"] = _utc_now()
        _write_json_atomic(directory / TERM_FILE, state)
    return state["epoch"]


def _fencing_token(node_id: str, term: int, salt: str | None) -> str:
    raw = f"{salt or ''}:{node_id}:{term}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def claim_lead(
    state_dir: str | Path,
    node_id: str,
    token: str,
    term: int | None = None,
) -> dict:
    """Lead uebernehmen. Authentisiert, monoton steigender Term, Fencing-Token.

    term=None -> aktueller Term + 1. Expliziter Term muss strikt groesser sein
    als der bisherige, sonst FencingError (stale Term / Split-Brain-Schutz).
    """
    with _state_lock(state_dir) as directory:
        if not authenticate(directory, node_id, token):
            raise FencingError(f"Node '{node_id}' ist nicht authentisiert")
        state = _load_term(directory)
        new_term = state["term"] + 1 if term is None else term
        if type(new_term) is not int or new_term <= state["term"]:
            raise FencingError(
                f"Stale Term: {new_term} <= aktueller Term {state['term']}"
            )
        salt = load_nodes(directory)["nodes"].get(node_id, {}).get("salt")
        fencing = _fencing_token(node_id, new_term, salt)
        record = {
            "term": new_term,
            "epoch": state["epoch"],
            "leader": node_id,
            "fencing_token": fencing,
            "updated_at": _utc_now(),
        }
        _write_json_atomic(directory / TERM_FILE, record)
    return {
        "leader": node_id,
        "term": new_term,
        "epoch": state["epoch"],
        "fencing_token": fencing,
        "salt": salt,
    }


def check_fencing(state_dir: str | Path, term: int, fencing_token: str) -> bool:
    """True, wenn (term, fencing_token) dem aktuellen Lead entspricht."""
    if type(term) is not int or not isinstance(fencing_token, str) or not fencing_token:
        return False
    try:
        state = _load_term(state_dir)
    except FencingError:
        return False
    if state["leader"] is None:
        return False
    return state["term"] == term and state["fencing_token"] == fencing_token
