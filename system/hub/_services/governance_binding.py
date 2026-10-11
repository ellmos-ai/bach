# SPDX-License-Identifier: MIT
"""Gepinnte Governance-Referenzen von Blueprints und ihre Laufbindung (P05 3b/3c).

Normen bleiben in ``policy-registry``. Dieses Modul liest sie ausschließlich über
``policy_registry_adapter.observe()`` und hält nur Pins ``(id, version, sha256)``.
Über allen Blueprint-Schichten steht der hostlokale globale Mindestvertrag
(``BACH_GOVERNANCE_GLOBAL_FILE``); fehlt die Datei, verbietet er nichts zusätzlich.
Jede Abweisung ist geschlossen; ``str(exc)`` ist der stabile Fehlercode.
Vertrag: ``docs/architecture/GOVERNANCE-BINDING-v1.md``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "bach.governance-binding.v1"
GLOBAL_SCHEMA = "bach.governance-global.v1"
REGISTRY = "policy-registry"
LAYER_ROLES = ("role", "agent")  # Blueprint-Schichten; "global" setzt nur der Host.
REF_FIELDS = {"registry", "id", "version", "sha256", "role"}
INHERITS_FIELDS = {"blueprint_id", "version", "sha256"}
BINDING_FIELDS = {"schema", "refs", "inherits", "global", "profile", "tool_whitelist",
                  "legacy", "effective_sha256"}
MAX_REFS = 64
MAX_INHERITANCE_DEPTH = 8
PIN_LOG_LIMIT = 100
RUN_RECHECK_SECONDS = 60.0  # Prüfabstand innerhalb eines Laufs, siehe verify_slot_throttled
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TEXT = re.compile(r"^[^\x00-\x1f]{1,256}$")
_ROLE_ORDER = {"global": 0, "role": 1, "agent": 2}


class GovernanceRejected(ValueError):
    """Geschlossene Abweisung; ``str(exc)`` ist der stabile Fehlercode."""


def canonical_sha256(value: Any) -> str:
    """sha256 über kanonisches JSON: sort_keys, kompakte Trenner, UTF-8 ohne Escapes."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ref(raw: Any, roles) -> dict[str, str]:
    if type(raw) is not dict or set(raw) != REF_FIELDS:
        raise GovernanceRejected("policy_ref_invalid")
    if (raw["registry"] != REGISTRY
            or any(not isinstance(raw[key], str) or not _TEXT.fullmatch(raw[key]) for key in ("id", "version"))
            or not isinstance(raw["sha256"], str) or not _SHA256.fullmatch(raw["sha256"])):
        raise GovernanceRejected("policy_ref_invalid")
    if raw["role"] not in roles:
        raise GovernanceRejected("policy_ref_role_invalid")
    return dict(raw)


def declared(governance: dict) -> tuple[list[dict], dict | None]:
    """Strukturprüfung der Blueprint-Felder ``policy_refs`` und ``inherits_from``."""
    refs = governance.get("policy_refs")
    refs = [] if refs is None else refs
    if type(refs) is not list or len(refs) > MAX_REFS:
        raise GovernanceRejected("policy_ref_invalid")
    refs = [_ref(item, LAYER_ROLES) for item in refs]
    if len({ref["id"] for ref in refs}) != len(refs):
        raise GovernanceRejected("policy_ref_invalid")
    inherits = governance.get("inherits_from")
    if inherits is not None and (
            type(inherits) is not dict or set(inherits) != INHERITS_FIELDS
            or type(inherits["blueprint_id"]) is not int or inherits["blueprint_id"] <= 0
            or type(inherits["version"]) is not int or inherits["version"] <= 0
            or not isinstance(inherits["sha256"], str) or not _SHA256.fullmatch(inherits["sha256"])):
        raise GovernanceRejected("inherits_from_invalid")
    return refs, (dict(inherits) if inherits is not None else None)


def global_file() -> Path:
    configured = os.environ.get("BACH_GOVERNANCE_GLOBAL_FILE")
    if configured:
        return Path(configured).expanduser()
    from hub.bach_paths import LOCAL_BACH_DIR
    return LOCAL_BACH_DIR / "governance_global.json"


def global_contract(path: Path | None = None) -> dict[str, Any]:
    """Hostlokaler Mindestvertrag ``{schema, policy_refs, forbidden_tools}``."""
    path = Path(path) if path else global_file()
    if not path.is_file():
        return {"policy_refs": [], "forbidden_tools": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (type(raw) is not dict or set(raw) != {"schema", "policy_refs", "forbidden_tools"}
                or raw["schema"] != GLOBAL_SCHEMA or type(raw["policy_refs"]) is not list
                or type(raw["forbidden_tools"]) is not list or len(raw["policy_refs"]) > MAX_REFS):
            raise ValueError
        refs = [_ref(item, ("global",)) for item in raw["policy_refs"]]
        from .chat.bach_tools import TOOLS_FULL
        known = {tool["function"]["name"] for tool in TOOLS_FULL}
        forbidden = raw["forbidden_tools"]
        if (len({ref["id"] for ref in refs}) != len(refs)
                or any(not isinstance(name, str) or name not in known for name in forbidden)):
            raise ValueError
    except (OSError, ValueError) as exc:
        raise GovernanceRejected("governance_global_invalid") from exc
    return {"policy_refs": sorted(refs, key=lambda ref: ref["id"]), "forbidden_tools": sorted(set(forbidden))}


def _registry_index(observe: Callable | None) -> dict[str, dict]:
    from . import policy_registry_adapter as adapter
    try:
        # Projektion ohne Pfade/Volltexte; verify() hat jede lokale Quelle gegen ihren Hash geprüft.
        snapshot = (observe or adapter.observe)()
    except adapter.PolicyProviderUnavailable as exc:
        raise GovernanceRejected("policy_provider_unavailable") from exc
    except adapter.PolicySnapshotChanged as exc:
        raise GovernanceRejected("policy_registry_changed") from exc
    return {entry["id"]: entry for entry in snapshot["entries"]}


def verify_ref(ref: dict, index: dict[str, dict]) -> None:
    entry = index.get(ref["id"])
    if entry is None:
        raise GovernanceRejected("policy_ref_unknown")
    if entry.get("version") != ref["version"]:
        raise GovernanceRejected("policy_ref_stale")
    if entry.get("source_sha256") != ref["sha256"]:
        raise GovernanceRejected("policy_ref_hash_mismatch")
    if entry.get("source_verified") is not True:
        raise GovernanceRejected("policy_ref_unverified")
    # "superseded" bleibt gepinnt gültig; ein Wechsel braucht die explizite Migration.
    if (entry.get("kind") not in {"policy", "rule", "decision"} or entry.get("adoption") != "adopted"
            or entry.get("status") not in {"active", "superseded"}):
        raise GovernanceRejected("policy_ref_not_binding")


def _row(conn, blueprint_id: int) -> dict | None:
    cursor = conn.execute("SELECT * FROM agent_blueprints WHERE id = ?", (blueprint_id,))
    row = cursor.fetchone()
    return None if row is None else dict(zip([column[0] for column in cursor.description], row))


def _governance(row: dict) -> dict:
    governance = json.loads(row.get("governance_json") or "{}")
    if not isinstance(governance, dict):
        raise GovernanceRejected("governance_invalid")
    return governance


def blueprint_sha256(row: dict) -> str:
    """Inhaltshash einer gespeicherten Blueprint-Zeile (Pin für ``inherits_from``)."""
    governance = {key: value for key, value in _governance(row).items() if key != "pin_log"}
    return canonical_sha256({
        "kind": row.get("kind") or "agent", "persona_role": row.get("persona_role") or "",
        "persona_prompt": row.get("persona_prompt") or "", "animus_type": row.get("animus_type") or "",
        "modus": row.get("modus") or "", "skills": json.loads(row.get("skills_json") or "[]"),
        "contractus": json.loads(row.get("contractus_json") or "{}"), "governance": governance})


def inheritance(conn, inherits: dict | None, *, self_id: int | None = None) -> list[dict]:
    """Verfolgt die gepinnte Vererbungskette; jede Stufe muss exakt auflösen."""
    parents, seen = [], {self_id}
    while inherits is not None:
        if len(parents) >= MAX_INHERITANCE_DEPTH:
            raise GovernanceRejected("inherits_from_too_deep")
        if inherits["blueprint_id"] in seen:
            raise GovernanceRejected("inherits_from_cycle")
        seen.add(inherits["blueprint_id"])
        row = _row(conn, inherits["blueprint_id"])
        if row is None:
            raise GovernanceRejected("inherits_from_unknown")
        if row.get("version") != inherits["version"]:
            raise GovernanceRejected("inherits_from_stale")
        if blueprint_sha256(row) != inherits["sha256"]:
            raise GovernanceRejected("inherits_from_hash_mismatch")
        governance = _governance(row)
        refs, next_inherits = declared(governance)
        parents.append({"pin": inherits, "refs": refs, "governance": governance})
        inherits = next_inherits
    return parents


def granted_tools(tool_whitelist: Any) -> set[str]:
    """Echte Werkzeugnamen einer Whitelist (Aliase aufgelöst), wie bei der Materialisierung."""
    from .blueprint_service import expand_tool_whitelist
    return expand_tool_whitelist(tool_whitelist)


def _effective(binding: dict) -> str:
    return canonical_sha256({key: binding[key] for key in BINDING_FIELDS - {"effective_sha256"}})


def resolve(conn, governance: dict, *, blueprint_id: int | None = None,
            observe: Callable | None = None, contract: dict | None = None) -> dict[str, Any]:
    """Löst den effektiven Satz serverseitig auf (Save, Materialize, Start)."""
    return resolve_layers(conn, governance, blueprint_id=blueprint_id, observe=observe,
                          contract=contract)[0]


def resolve_layers(conn, governance: dict, *, blueprint_id: int | None = None,
                   observe: Callable | None = None, contract: dict | None = None):
    """Wie ``resolve``, zusätzlich die Governance der Elternvorlagen (nächste zuerst).

    Reihenfolge der Schichten: global (Host) → Elternvorlagen → eigener Blueprint.
    Eine untere Schicht ergänzt nur; sie darf weder einen höheren Pin ersetzen
    noch ein global verbotenes Werkzeug freigeben.
    """
    own_refs, inherits = declared(governance)
    parents = inheritance(conn, inherits, self_id=blueprint_id)
    contract = global_contract() if contract is None else contract
    forbidden = set(contract["forbidden_tools"])
    # Ohne Hostvertrag bleibt die bisherige Save-Prüfung unverändert (Legacy).
    if forbidden and granted_tools(governance.get("tool_whitelist")) & forbidden:
        raise GovernanceRejected("governance_global_violation")
    pinned: dict[str, dict] = {ref["id"]: ref for ref in contract["policy_refs"]}
    for layer_refs in [parent["refs"] for parent in reversed(parents)] + [own_refs]:
        for ref in layer_refs:
            higher = pinned.get(ref["id"])
            if higher is None:
                pinned[ref["id"]] = ref
            elif (higher["version"], higher["sha256"]) != (ref["version"], ref["sha256"]):
                raise GovernanceRejected("governance_global_violation" if higher["role"] == "global"
                                         else "policy_ref_override")
    refs = sorted(pinned.values(), key=lambda ref: (_ROLE_ORDER[ref["role"]], ref["id"]))
    if refs:
        index = _registry_index(observe)
        for ref in refs:
            verify_ref(ref, index)
    binding = {"schema": SCHEMA, "refs": refs,
               "inherits": [parent["pin"] for parent in parents],
               # Inhalt der Host-Schicht selbst, damit effective_sha256 sie kanonisch mitbindet.
               "global": contract,
               "profile": governance.get("profile"), "tool_whitelist": governance.get("tool_whitelist"),
               "legacy": not own_refs and inherits is None}
    binding["effective_sha256"] = _effective(binding)
    return binding, [parent["governance"] for parent in parents]


def check_stored(binding: Any) -> dict:
    """Formprüfung einer gespeicherten Bindung; der Hash wird nachgerechnet."""
    if (type(binding) is not dict or set(binding) != BINDING_FIELDS or binding["schema"] != SCHEMA
            or type(binding["refs"]) is not list or type(binding["inherits"]) is not list
            or type(binding["global"]) is not dict
            or type(binding["legacy"]) is not bool or binding["effective_sha256"] != _effective(binding)):
        raise GovernanceRejected("governance_binding_invalid")
    for ref in binding["refs"]:
        _ref(ref, tuple(_ROLE_ORDER))
    return binding


def verify_run(binding: Any, allowed_tools: Any, *, observe: Callable | None = None,
               contract: dict | None = None) -> dict | None:
    """Prüfung bei jedem Lauf: Pins lösen noch exakt auf, der Host-Vertrag ist unverändert.

    Ein vor 3b materialisierter Steckplatz hat keine Bindung (legacy); auch für ihn gelten
    die global verbotenen Werkzeuge.
    """
    if binding is not None:
        check_stored(binding)
    contract = global_contract() if contract is None else contract
    if set(allowed_tools or []) & set(contract["forbidden_tools"]):
        raise GovernanceRejected("governance_global_violation")
    if binding is None:
        return None
    if contract != binding["global"]:
        raise GovernanceRejected("governance_global_changed")
    if binding["refs"]:
        index = _registry_index(observe)
        for ref in binding["refs"]:
            verify_ref(ref, index)
    return binding


def verify_slot_throttled(slot: dict, checked_at: list, *, clock: Callable = time.monotonic) -> None:
    """``verify_run`` im Policy-Reader des Controllers (Admission und laufende Lesungen).

    Die erste Lesung eines Readers (= Admission) prüft immer. Weitere Lesungen desselben
    Laufs prüfen höchstens alle ``RUN_RECHECK_SECONDS``; Slotinhalt und Freigaben deckt der
    Policy-Snapshot des Controllers ohnehin bei jeder Lesung ab.
    """
    # ponytail: Zeitfenster, weil observe() bei jedem Lesen alle lokalen Registry-Quellen hasht;
    # bei Bedarf durch einen Cache nach Registry-Stand ersetzen.
    now = clock()
    if not checked_at or now - checked_at[0] >= RUN_RECHECK_SECONDS:
        verify_run(slot.get("governance_binding"), slot.get("allowed_tools"))
        checked_at[:] = [now]


def receipt_binding(binding: Any) -> dict[str, Any]:
    """Projektion für ``bach.worker-execution.v1``; ohne Bindung gilt der Lauf als legacy."""
    if not isinstance(binding, dict):
        return {"effective_sha256": None, "refs": [], "legacy": True}
    return {"effective_sha256": binding["effective_sha256"], "refs": binding["refs"],
            "legacy": binding["legacy"]}


def run_receipt_fields(slot: dict) -> dict[str, Any]:
    """Additive Felder des Laufbelegs (3c), festgehalten bei der Admission."""
    # Die Fallback-Kette (3d) kommt mit P06; bis dahin läuft immer Glied 0 des Steckplatzes.
    return {"governance_binding": receipt_binding(slot.get("governance_binding")),
            "model_binding": {"chain_index": 0, "backend": slot.get("backend"), "model": slot.get("model"),
                              "switch_reason": None}}


def _pins(governance: dict) -> dict:
    refs = governance.get("policy_refs") if isinstance(governance.get("policy_refs"), list) else []
    return {"refs": {json.dumps(ref, sort_keys=True): str(ref.get("id") if isinstance(ref, dict) else ref)
                     for ref in refs},
            "inherits_from": governance.get("inherits_from")}


def with_pin_log(previous: dict, governance: dict, *, blueprint_version: int) -> dict:
    """Pinwechsel nur per Save mit CAS; der Server protokolliert ihn append-only im Blueprint.

    Ein vom Client mitgesendetes ``pin_log`` wird verworfen und durch den gespeicherten Stand ersetzt.
    """
    log = previous.get("pin_log") if isinstance(previous.get("pin_log"), list) else []
    result = {key: value for key, value in governance.items() if key != "pin_log"}
    before, after = _pins(previous), _pins(result)
    if before != after:
        moved = before["refs"].keys() ^ after["refs"].keys()
        changed = sorted({before["refs"].get(key) or after["refs"][key] for key in moved})
        if before["inherits_from"] != after["inherits_from"]:
            changed.append("inherits_from")
        log = log + [{"at": datetime.now(timezone.utc).isoformat(), "blueprint_version": blueprint_version,
                      "changed": changed, "pins_sha256": canonical_sha256(
                          {"refs": sorted(after["refs"]), "inherits_from": after["inherits_from"]})}]
    if log:
        result["pin_log"] = log[-PIN_LOG_LIMIT:]
    return result
