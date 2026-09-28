# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Fail-closed authentication gate for read-only application projections.

Configuration contains only non-secret OS-keyring references. The signed
transit manifest is authenticated and its snapshot hash is verified before a
domain-specific projection reader is allowed to open SQLite.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class ProjectionTransportAuthError(ValueError):
    """The transport authentication configuration or artifact is unsafe."""


_TOP_LEVEL_FIELDS = {
    "active_key_id",
    "keys",
    "trusted_senders",
    "trust_source",
}
_REFERENCE_FIELDS = {"key_id", "service", "account", "sender"}
_SECRET_FIELD_NAMES = {"secret", "password", "token", "value", "key_material"}


@dataclass(frozen=True, slots=True)
class AuthenticatedProjectionSnapshot:
    """Private immutable bytes bound to one authenticated transit manifest."""

    path: Path
    source_name: str
    sha256: str


@contextmanager
def authenticated_projection_snapshot(
    manifest_path: str | Path,
    auth_config: Mapping[str, Any],
    *,
    expected_namespace: str,
    secret_resolver: Any | None = None,
) -> Iterator[AuthenticatedProjectionSnapshot]:
    """Yield a private immutable copy of exactly the bytes that passed hashing.

    ``verify_authenticated_snapshot`` from the pinned sqlite-transit-sync API
    authenticates manifest identity and the transit file. The copy is then read
    once through an already-open source handle and independently bound to that
    verified size and digest. Consumers never reopen the mutable transit path.
    """
    try:
        from sqlite_transit_sync import (
            HMACKeyReference,
            OSKeyringSecretResolver,
            load_hmac_authenticator,
            verify_authenticated_snapshot,
        )
    except ImportError as exc:
        raise ProjectionTransportAuthError(
            "sqlite-transit-sync mit Auth-Preflight ist nicht installiert."
        ) from exc

    config = _validated_auth_config(auth_config)
    references = [HMACKeyReference(**entry) for entry in config["keys"]]
    resolver = secret_resolver or OSKeyringSecretResolver()
    try:
        authenticator = load_hmac_authenticator(
            references,
            active_key_id=config["active_key_id"],
            resolver=resolver,
            trusted_senders=config["trusted_senders"],
            trust_source=config["trust_source"],
        )
        manifest = Path(manifest_path).expanduser()
        if manifest.suffix != ".json":
            raise ProjectionTransportAuthError(
                "Der authentifizierte Projektionspfad muss auf .json enden."
            )
        snapshot = manifest.with_suffix("")
        verified = verify_authenticated_snapshot(
            manifest, snapshot, authenticator=authenticator
        )
    except ProjectionTransportAuthError:
        raise
    except Exception:
        raise ProjectionTransportAuthError(
            "Projektions-Transportauthentifizierung fehlgeschlagen."
        ) from None
    if verified.namespace != expected_namespace:
        raise ProjectionTransportAuthError(
            "Authentifizierter Snapshot gehört zum falschen Projektions-Namespace."
        )
    private_dir = Path(tempfile.mkdtemp(prefix="bach-authenticated-projection-"))
    private_path = private_dir / "projection.sqlite"
    try:
        try:
            os.chmod(private_dir, 0o700)
            digest = hashlib.sha256()
            size = 0
            with open(verified.path, "rb") as source, open(private_path, "xb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            copied_hash = digest.hexdigest()
            if size != verified.size or copied_hash != verified.sha256:
                raise ProjectionTransportAuthError(
                    "Authentifizierter Snapshot wurde beim privaten Snapshot-Aufbau ausgetauscht."
                )
            os.chmod(private_path, 0o400)
        except ProjectionTransportAuthError:
            raise
        except OSError as exc:
            raise ProjectionTransportAuthError(
                "Privater authentifizierter Projektions-Snapshot konnte nicht erstellt werden."
            ) from exc
        yield AuthenticatedProjectionSnapshot(
            path=private_path,
            source_name=verified.path.name,
            sha256=verified.sha256,
        )
    finally:
        try:
            os.chmod(private_path, 0o600)
        except OSError:
            pass
        shutil.rmtree(private_dir, ignore_errors=True)


def validate_transport_auth_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize secret-free keyring references without resolving them."""
    return _validated_auth_config(config)


def _validated_auth_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ProjectionTransportAuthError("transport_auth muss ein Objekt sein.")
    unexpected = set(config) - _TOP_LEVEL_FIELDS
    if unexpected:
        raise ProjectionTransportAuthError(
            f"Unbekannte transport_auth-Felder: {sorted(unexpected)}"
        )
    if _contains_secret_field(config):
        raise ProjectionTransportAuthError(
            "Secretwerte sind in transport_auth verboten; nur Keyring-Referenzen verwenden."
        )
    active_key_id = config.get("active_key_id")
    trust_source = config.get("trust_source", "projection-os-keyring")
    keys = config.get("keys")
    trusted_senders = config.get("trusted_senders")
    if not isinstance(active_key_id, str) or not active_key_id:
        raise ProjectionTransportAuthError("active_key_id fehlt.")
    if not isinstance(trust_source, str) or not trust_source:
        raise ProjectionTransportAuthError("trust_source fehlt.")
    if not isinstance(keys, list) or not keys:
        raise ProjectionTransportAuthError("keys muss eine nicht leere Liste sein.")
    normalized_keys: list[dict[str, str]] = []
    for index, entry in enumerate(keys):
        if not isinstance(entry, Mapping) or set(entry) != _REFERENCE_FIELDS:
            raise ProjectionTransportAuthError(
                f"keys[{index}] muss exakt key_id, service, account und sender enthalten."
            )
        if not all(isinstance(entry[field], str) and entry[field] for field in _REFERENCE_FIELDS):
            raise ProjectionTransportAuthError(f"keys[{index}] enthält leere Referenzen.")
        normalized_keys.append(dict(entry))
    if (
        not isinstance(trusted_senders, list)
        or not trusted_senders
        or not all(isinstance(sender, str) and sender for sender in trusted_senders)
    ):
        raise ProjectionTransportAuthError(
            "trusted_senders muss eine nicht leere String-Liste sein."
        )
    return {
        "active_key_id": active_key_id,
        "keys": normalized_keys,
        "trusted_senders": list(trusted_senders),
        "trust_source": trust_source,
    }


def _contains_secret_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in _SECRET_FIELD_NAMES or _contains_secret_field(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_field(child) for child in value)
    return False
