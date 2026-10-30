"""Provider-neutral profile deletion workflow with explicit safety ports.

Adapters own identity, process/lease proofs and storage transactions. They
must hold their profile/controller locks while calling this operation.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any


class ProfileDeletionRejected(RuntimeError):
    """A profile cannot be safely archived and removed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def archive_then_remove_profile(
    profile_id: str,
    profile: Mapping[str, Any],
    *,
    assert_inactive: Callable[[Mapping[str, Any]], None],
    terminal_records: Callable[[Mapping[str, Any]], Iterable[Mapping[str, Any]]],
    archive: Callable[[str, tuple[Mapping[str, Any], ...]], Any],
    remove: Callable[[], bool],
) -> bool:
    """Prove inactivity, archive terminal receipts, then persist removal.

    The caller supplies the platform-specific controller/lease guard and
    storage operations. It must invoke this function inside the same locked
    transaction that protects profile admission and configuration writes.
    Archive failure propagates and prevents profile removal.
    """
    if type(profile_id) is not str or not profile_id:
        raise ProfileDeletionRejected("profile_identity_invalid")
    if not isinstance(profile, Mapping) or profile.get("id") != profile_id:
        raise ProfileDeletionRejected("profile_identity_mismatch")
    if not callable(assert_inactive):
        raise ProfileDeletionRejected("execution_proof_required")
    if not callable(terminal_records) or not callable(archive) or not callable(remove):
        raise ProfileDeletionRejected("deletion_port_unavailable")

    assert_inactive(profile)
    records = tuple(terminal_records(profile))
    if any(
        not isinstance(record, Mapping) or record.get("phase") != "terminal"
        for record in records
    ):
        raise ProfileDeletionRejected("terminal_receipts_unconfirmed")

    archive(profile_id, records)
    return bool(remove())
