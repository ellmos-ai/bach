# SPDX-License-Identifier: MIT
"""Operator-managed model aliases in the existing configuration authority.

Bindings name principals, not model quality. Reviewer tiers remain exclusively
in worker_policy_settings. A general enrolled device cannot grant either.
"""
from __future__ import annotations

import re

from . import worker_policy_settings as settings
from .model_provenance import reported_model

KEY = "worker_model_principals.v1"
SCHEMA = "bach.worker-model-principals.v1"
CATALOG_KEY = "worker_model_principal_catalog.v1"
CATALOG_SCHEMA = "bach.worker-model-principal-catalog.v1"
BACKENDS = frozenset({"ollama", "openai", "lmstudio", "hermes", "openrouter", "claude-api"})
_HEX = re.compile(r"[a-f0-9]{64}\Z")


class IdentityPermissionDenied(PermissionError):
    pass


def require_operator(conn, token):
    """Resolve the existing explicit operator right under the caller's writer."""
    if not conn.in_transaction:
        raise IdentityPermissionDenied("Operatorprüfung benötigt eine Transaktion")
    if (not isinstance(token, str) or not token.strip() or len(token) > 256
            or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                "AND name='task_result_operators'").fetchone()):
        raise IdentityPermissionDenied("Gesonderte Operatorberechtigung erforderlich")
    from gui.device_auth import _hash_token
    row = conn.execute("SELECT d.id FROM devices d JOIN task_result_operators o "
                       "ON o.device_id=d.id WHERE d.token_hash=? AND d.status='active'",
                       (_hash_token(token),)).fetchone()
    if row is None:
        raise IdentityPermissionDenied("Operatorberechtigung fehlt oder wurde widerrufen")
    return "operator-device:" + str(row[0])


def _principal(value):
    if (type(value) is not str or not value or value != value.strip() or len(value) > 180
            or any(ord(c) < 32 or ord(c) == 127 for c in value) or "://" in value):
        raise ValueError("Ungültige Modellprincipal-ID")
    return value


def validate_bindings(bindings):
    if type(bindings) is not list or len(bindings) > 128:
        raise ValueError("Ungültige Modellzuordnungen")
    output, observations = [], {}
    for entry in bindings:
        settings._object(entry, {"principal_id", "backend_id", "route_sha256",
                                 "requested_models", "reported_models"})
        principal = _principal(entry["principal_id"])
        backend, route = entry["backend_id"], entry["route_sha256"]
        if type(backend) is not str or backend not in BACKENDS:
            raise ValueError("Unbekannter Modellanbieter")
        if type(route) is not str or not _HEX.fullmatch(route):
            raise ValueError("Bestätigte Controllerroute erforderlich")
        normalized = {}
        for field in ("requested_models", "reported_models"):
            values = entry[field]
            if (type(values) is not list or not 1 <= len(values) <= 64
                    or any(reported_model(v) is None for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError("Explizite eindeutige Modellaliasliste erforderlich")
            normalized[field] = list(values)
        for model in normalized["reported_models"]:
            key = (backend, route, model)
            if key in observations and observations[key] != principal:
                raise ValueError("Eine tatsächliche Modellroute hat mehrere Principals")
            observations[key] = principal
        output.append({"principal_id": principal, "backend_id": backend,
                       "route_sha256": route, **normalized})
    return output


def identity_snapshot(conn):
    """Pure DB projection; never DDL, enrollment, inference or key retrieval."""
    stored = settings._stored(conn, KEY)
    values = [] if stored["values"] is None else stored["values"]
    try:
        bindings = validate_bindings(values)
    except (ValueError, TypeError) as exc:
        raise settings.PolicyUnavailable("Gespeicherte Modellzuordnungen sind ungültig") from exc
    return {"schema": SCHEMA, "availability": "available",
            "configuration_version": settings._digest(stored), "bindings": bindings}


def read_model_bindings(db_path=None):
    with settings._connection(db_path) as conn:
        return identity_snapshot(conn)


def model_principal_catalog(conn):
    """One global model namespace, independent of native/external source.

    Existing native bindings already register canonical model principals.
    The explicit catalog additionally permits a genuine external-only model
    without inventing a native backend route or provider observation.
    """
    stored = settings._stored(conn, CATALOG_KEY)
    values = ({"principal_ids": [], "retired_principal_ids": []}
              if stored["values"] is None else stored["values"])
    try:
        settings._object(values, {"principal_ids", "retired_principal_ids"})
        normalized = {}
        for field, limit in (("principal_ids", 256), ("retired_principal_ids", 4096)):
            entries = values[field]
            if type(entries) is not list or len(entries) > limit:
                raise ValueError("Principal-Liste erforderlich")
            normalized[field] = [_principal(value) for value in entries]
            if len(set(normalized[field])) != len(entries):
                raise ValueError("Doppelte Modellprincipal-ID")
        configured, retired = normalized["principal_ids"], normalized["retired_principal_ids"]
        if set(configured) & set(retired):
            raise ValueError("Stillgelegter Modellprincipal ist aktiv")
    except (ValueError, TypeError) as exc:
        raise settings.PolicyUnavailable("Globaler Modellprincipal-Katalog ist ungültig") from exc
    native = identity_snapshot(conn)
    principals = sorted((set(configured) | {binding["principal_id"] for binding in native["bindings"]})
                        - set(retired))
    return {"schema": CATALOG_SCHEMA, "availability": "available",
            "configuration_version": settings._digest({"catalog": stored,
                "native_configuration_version": native["configuration_version"]}),
            "principal_ids": principals, "explicit_principal_ids": list(configured),
            "retired_principal_ids": list(retired)}


def read_model_principal_catalog(db_path=None):
    with settings._connection(db_path) as conn:
        return model_principal_catalog(conn)


def write_model_principal_catalog(payload, *, operator_token, db_path=None):
    settings._object(payload, {"configuration_version", "principal_ids"})
    values = payload["principal_ids"]
    if type(values) is not list or len(values) > 256:
        raise ValueError("Globale Modellprincipal-Liste erforderlich")
    principals = [_principal(value) for value in values]
    if len(set(principals)) != len(principals):
        raise ValueError("Globale Modellprincipal-IDs müssen eindeutig sein")
    if type(payload["configuration_version"]) is not str or not _HEX.fullmatch(payload["configuration_version"]):
        raise ValueError("Gültige globale Konfigurationsrevision erforderlich")
    with settings._connection(db_path, write=True) as conn:
        actor = require_operator(conn, operator_token)
        before = model_principal_catalog(conn)
        if payload["configuration_version"] != before["configuration_version"]:
            raise settings.PolicyConflict("Globaler Modellkatalog wurde parallel geändert")
        retired = set(before["retired_principal_ids"])
        if retired & set(principals):
            raise ValueError("Stillgelegte globale Modellprincipal-ID darf nicht wiederverwendet werden")
        native_ids = {binding["principal_id"] for binding in identity_snapshot(conn)["bindings"]}
        # Removing an explicit principal which has no remaining native route
        # permanently retires that identifier. Re-adding the same text must
        # never revive an old external receipt with a different meaning.
        retired |= set(before["explicit_principal_ids"]) - set(principals) - native_ids
        if len(retired) > 4096:
            raise ValueError("Globale Modellprincipal-Historie ist voll")
        settings._persist(conn, CATALOG_KEY,
                          {"principal_ids": principals, "retired_principal_ids": sorted(retired)},
                          actor=actor)
        return {"schema": CATALOG_SCHEMA, "updated": True, "worker_started": False,
                "configuration_version": model_principal_catalog(conn)["configuration_version"]}


def write_model_bindings(payload, *, operator_token, db_path=None):
    registration_fields = {"expected_catalog_version", "new_principal_id"}
    registration = isinstance(payload, dict) and bool(set(payload) & registration_fields)
    fields = {"configuration_version", "bindings"}
    settings._object(payload, fields | registration_fields if registration else fields)
    bindings = validate_bindings(payload["bindings"])
    if registration:
        expected_catalog = payload["expected_catalog_version"]
        if type(expected_catalog) is not str or not _HEX.fullmatch(expected_catalog):
            raise ValueError("Bestätigte Katalogversion erforderlich")
        new_principal = _principal(payload["new_principal_id"])
    with settings._connection(db_path, write=True) as conn:
        actor = require_operator(conn, operator_token)
        before = identity_snapshot(conn)
        if payload["configuration_version"] != before["configuration_version"]:
            raise settings.PolicyConflict("Modellzuordnungen wurden parallel geändert")
        catalog = model_principal_catalog(conn)
        retired = set(catalog["retired_principal_ids"])
        if registration:
            if expected_catalog != catalog["configuration_version"]:
                raise settings.PolicyConflict("Modellprincipal-Katalog wurde parallel geändert")
            if new_principal in set(catalog["principal_ids"]) | retired:
                raise settings.PolicyConflict("Neue Modellprincipal-ID ist bereits belegt")
            if (len(bindings) != len(before["bindings"]) + 1
                    or bindings[:-1] != before["bindings"]
                    or bindings[-1]["principal_id"] != new_principal):
                raise ValueError("Registrierung muss bestehende Bindungen erhalten und genau eine neue anfügen")
        if any(binding["principal_id"] in retired for binding in bindings):
            raise ValueError("Stillgelegte globale Modellprincipal-ID darf nicht neu gebunden werden")
        remaining = set(catalog["explicit_principal_ids"]) | {binding["principal_id"] for binding in bindings}
        new_retired = retired | (set(catalog["principal_ids"]) - remaining)
        if len(new_retired) > 4096:
            raise ValueError("Globale Modellprincipal-Historie ist voll")
        settings._persist(conn, KEY, bindings, actor=actor)
        if new_retired != retired:
            settings._persist(conn, CATALOG_KEY,
                              {"principal_ids": catalog["explicit_principal_ids"],
                               "retired_principal_ids": sorted(new_retired)}, actor=actor)
        result = {"schema": SCHEMA, "updated": True, "worker_started": False,
                  "configuration_version": identity_snapshot(conn)["configuration_version"]}
        if registration:
            result.update({"catalog_configuration_version": model_principal_catalog(conn)["configuration_version"],
                           "new_principal_id": new_principal})
        return result


def principal_for_route(snapshot, *, backend_id, route_sha256, requested_model):
    """A planned route is usable only when it selects one approved principal."""
    if snapshot.get("availability") != "available":
        return None
    matches = {row["principal_id"] for row in snapshot["bindings"]
               if row["backend_id"] == backend_id and row["route_sha256"] == route_sha256
               and requested_model in row["requested_models"]}
    return next(iter(matches)) if len(matches) == 1 else None


def principal_for_execution(snapshot, execution):
    """Resolve only a linked actual return, never a request or slot label."""
    if (snapshot.get("availability") != "available" or not isinstance(execution, dict)
            or execution.get("availability") != "available"
            or execution.get("model_provenance") != "provider_reported"
            or reported_model(execution.get("observed_model")) is None):
        return None
    bound = resolve_binding(snapshot, backend_id=execution.get("backend_id"),
                            route_sha256=execution.get("route_sha256"),
                            requested_model=execution.get("requested_model"),
                            observed_model=execution["observed_model"])
    version = execution.get("identity_configuration_version")
    if (bound is None or type(version) is not str or not _HEX.fullmatch(version)
            or execution.get("model_principal_id") != bound["principal_id"]
            or execution.get("identity_binding_sha256") != settings._digest(bound)):
        return None
    return bound["principal_id"]


def resolve_binding(snapshot, *, backend_id, route_sha256, requested_model, observed_model):
    """Current aliases only; by itself this never attests historical execution."""
    if snapshot.get("availability") != "available" or reported_model(observed_model) is None:
        return None
    matches = [row for row in snapshot["bindings"]
               if row["backend_id"] == backend_id and row["route_sha256"] == route_sha256
               and requested_model in row["requested_models"] and observed_model in row["reported_models"]]
    # Duplicate rows cannot supply ambiguous historical binding digests.
    return matches[0] if len(matches) == 1 else None
