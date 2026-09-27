# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Compatibility adapter for sqlite-transit-sync's removed HMAC prefight API.

The pinned venv of ``sqlite_transit_sync`` no longer exports the legacy helper
``HMACKeyReference``, ``OSKeyringSecretResolver``, ``load_hmac_authenticator``
and ``verify_authenticated_snapshot``.  This module emulates that surface on top
of the new API (``HMACKey``, ``HMACSnapshotAuthenticator`` and ``TransitSync``)
so existing callers in BACH keep working without a full rewrite.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlite_transit_sync import HMACKey, HMACSnapshotAuthenticator, Snapshot
from sqlite_transit_sync.core import SyncError


__all__ = [
    "HMACKeyReference",
    "OSKeyringSecretResolver",
    "load_hmac_authenticator",
    "verify_authenticated_snapshot",
]


@dataclass(frozen=True, slots=True)
class HMACKeyReference:
    """Non-secret description of an HMAC key stored outside the manifest."""

    key_id: str
    service: str
    account: str
    sender: str

    def as_dict(self) -> dict[str, str]:
        return {
            "key_id": self.key_id,
            "service": self.service,
            "account": self.account,
            "sender": self.sender,
        }


class OSKeyringSecretResolver:
    """Resolve secrets from the operating-system keyring.

    Falls back to environment variables when the keyring module is not
    available or the entry cannot be read.
    """

    def resolve_secret(self, reference: HMACKeyReference) -> bytes:
        service = reference.service
        account = reference.account

        # Try the real OS keyring first.
        try:
            import keyring  # type: ignore[import-untyped]

            value = keyring.get_password(service, account)
            if value:
                return value.encode("utf-8")
        except Exception:
            pass

        # Environment fallback: BACH_<service>_<account>
        env_name = f"BACH_{service.upper()}_{account.upper()}".replace("-", "_")
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value.encode("utf-8")

        raise SyncError(
            f"HMAC secret for {reference.key_id!r} could not be resolved"
        )


class _SecretResolutionFailed:
    """Sentinel returned when a resolver raises, so secrets stay local."""


def _resolve_secret(resolver: Any, reference: HMACKeyReference) -> bytes | _SecretResolutionFailed:
    """Call the resolver while keeping any secret-bearing exception local."""
    try:
        return resolver.resolve_secret(reference)
    except Exception:
        return _SecretResolutionFailed()


def load_hmac_authenticator(
    references: Iterable[HMACKeyReference],
    *,
    active_key_id: str,
    resolver: Any,
    trusted_senders: Iterable[str] | None = None,
    trust_source: str = "application-key-ring",
) -> HMACSnapshotAuthenticator:
    """Build an ``HMACSnapshotAuthenticator`` from keyring references."""

    keys: dict[str, HMACKey] = {}
    for reference in references:
        secret = _resolve_secret(resolver, reference)
        if isinstance(secret, _SecretResolutionFailed):
            raise SyncError(
                f"HMAC secret for {reference.key_id!r} could not be resolved"
            )
        if not isinstance(secret, bytes) or not secret:
            raise SyncError(f"Resolver returned invalid secret for {reference.key_id!r}")
        keys[reference.key_id] = HMACKey(
            sender=reference.sender,
            secret=secret,
        )

    return HMACSnapshotAuthenticator(
        keys=keys,
        active_key_id=active_key_id,
        trusted_senders=trusted_senders,
        trust_source=trust_source,
    )


def verify_authenticated_snapshot(
    manifest_path: str | Path,
    snapshot_path: str | Path,
    *,
    authenticator: HMACSnapshotAuthenticator,
) -> Snapshot:
    """Fail-closed verification of a signed transit manifest and its snapshot.

    Returns a ``Snapshot`` value object that has already passed sender,
    signature and SHA-256 checks.
    """

    manifest_path = Path(manifest_path).expanduser()
    snapshot_path = Path(snapshot_path).expanduser()

    if not manifest_path.is_file():
        raise SyncError(f"Manifest not found: {manifest_path}")
    if not snapshot_path.is_file():
        raise SyncError(f"Snapshot not found: {snapshot_path}")

    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if not isinstance(manifest, Mapping):
        raise SyncError("Manifest is not a JSON object")

    expected_fields = {
        "protocol",
        "namespace",
        "node_id",
        "created_at",
        "snapshot",
        "sha256",
        "size",
    }
    if not expected_fields.issubset(manifest):
        raise SyncError("Manifest is missing required fields")

    if manifest.get("snapshot") != snapshot_path.name:
        raise SyncError("Manifest snapshot name does not match supplied snapshot")

    # Verify integrity first.
    digest = hashlib.sha256()
    size = 0
    with open(snapshot_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)

    if digest.hexdigest() != manifest.get("sha256"):
        raise SyncError("Snapshot SHA-256 digest does not match manifest")
    if size != manifest.get("size"):
        raise SyncError("Snapshot size does not match manifest")

    # Authenticate the manifest envelope.
    auth = manifest.get("auth")
    if not isinstance(auth, Mapping):
        raise SyncError("Manifest has no valid authentication envelope")

    authenticator.verify(manifest, auth)

    return Snapshot(
        path=snapshot_path,
        manifest_path=manifest_path,
        node_id=manifest["node_id"],
        namespace=manifest["namespace"],
        created_at=manifest["created_at"],
        sha256=manifest["sha256"],
        size=manifest["size"],
    )
