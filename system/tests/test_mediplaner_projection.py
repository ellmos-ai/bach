# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Contract tests for the read-only MediPlaner reminder consumer."""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.mediplaner_projection import (
    MediplanerProjectionError,
    format_mediplaner_briefing,
    read_legacy_unauthenticated_mediplaner_projection,
    read_mediplaner_projection,
)  # noqa: E402
from hub._services.projection_transport_auth import (  # noqa: E402
    ProjectionTransportAuthError,
    authenticated_projection_snapshot,
)
from hub.daily_agent import DailyAgentHandler  # noqa: E402

from sqlite_transit_sync import (  # noqa: E402
    HMACKeyReference,
    SyncConfig,
    TransitSync,
    load_hmac_authenticator,
)


class _MappingResolver:
    def __init__(self, value: bytes = b"T" * 32):
        self.value = value

    def resolve_secret(self, _reference):
        return self.value


def _assert_secret_free_exception_chain(exc: BaseException, sentinel: str) -> None:
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert sentinel not in str(exc)
    assert sentinel not in rendered
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        assert sentinel not in str(current)
        assert sentinel not in repr(current)
        pending.extend(
            linked
            for linked in (current.__cause__, current.__context__)
            if linked is not None
        )


def test_consumer_resolver_failure_never_exposes_secret_in_exception_chain(tmp_path):
    sentinel = "BACH-CONSUMER-SECRET-SENTINEL-e921"
    auth_config = {
        "active_key_id": "test-v1",
        "keys": [
            {
                "key_id": "test-v1",
                "service": "synthetic-projection-tests",
                "account": "mediplaner-v1",
                "sender": "mediplaner-primary",
            }
        ],
        "trusted_senders": ["mediplaner-primary"],
        "trust_source": "synthetic-keyring",
    }

    class FailingResolver:
        def resolve_secret(self, _reference):
            raise RuntimeError(sentinel)

    with patch(
        "sqlite_transit_sync.OSKeyringSecretResolver", return_value=FailingResolver()
    ):
        with pytest.raises(ProjectionTransportAuthError) as caught:
            with authenticated_projection_snapshot(
                tmp_path / "not-reached.sqlite-snapshot.json",
                auth_config,
                expected_namespace="mediplaner-reminder-v1",
            ):
                pytest.fail("Keyring-Fehler darf keinen Snapshot liefern")

    _assert_secret_free_exception_chain(caught.value, sentinel)


def _authenticated_projection(path: Path, tmp_path: Path):
    reference = HMACKeyReference(
        "mediplaner-v1",
        "synthetic-projection-tests",
        "mediplaner-v1",
        "mediplaner-primary",
    )
    resolver = _MappingResolver()
    auth_config = {
        "active_key_id": reference.key_id,
        "keys": [reference.as_dict()],
        "trusted_senders": ["mediplaner-primary"],
        "trust_source": "synthetic-keyring",
    }
    authenticator = load_hmac_authenticator(
        [reference],
        active_key_id=reference.key_id,
        resolver=resolver,
        trusted_senders=auth_config["trusted_senders"],
        trust_source=auth_config["trust_source"],
    )
    sync = TransitSync(
        SyncConfig(
            database=path,
            transit=tmp_path / "transit",
            state=tmp_path / "transport-state.json",
            node_id="mediplaner-primary",
            namespace="mediplaner-reminder-v1",
        ),
        authenticator=authenticator,
    )
    snapshot = sync.push()
    return snapshot, auth_config, resolver


def _create_projection(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE projection_metadata (
            contract_id TEXT NOT NULL PRIMARY KEY,
            contract_version TEXT NOT NULL,
            publisher_component TEXT NOT NULL,
            publisher_instance TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            source_checkpoint INTEGER NOT NULL
        );
        CREATE TABLE medication_due (
            record_ref TEXT NOT NULL PRIMARY KEY,
            due_at TEXT NOT NULL,
            window_end_at TEXT NOT NULL,
            reminder_kind TEXT NOT NULL,
            state TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL
        );
        CREATE TABLE inventory_warning (
            record_ref TEXT NOT NULL PRIMARY KEY,
            warning_band TEXT NOT NULL,
            event_at TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL
        );
        CREATE TABLE projection_tombstones (
            record_type TEXT NOT NULL,
            record_ref TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            retain_until TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL,
            PRIMARY KEY (record_type, record_ref)
        );
        """
    )
    conn.execute(
        "INSERT INTO projection_metadata VALUES (?, ?, ?, ?, ?, ?)",
        (
            "org.ellmos.mediplaner.reminder-projection",
            "1.0.0",
            "mediplaner-v5-projection-adapter",
            "mediplaner-primary",
            "2026-08-22T08:00:00Z",
            41,
        ),
    )
    conn.executemany(
        "INSERT INTO medication_due VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("a" * 32, "2026-08-22T08:00:00Z", "2026-08-22T08:30:00Z", "medication-due", "due", 1, 41, "mediplaner-primary"),
            ("c" * 32, "2026-08-22T09:00:00Z", "2026-08-22T09:30:00Z", "medication-due", "suppressed", 1, 41, "mediplaner-primary"),
        ],
    )
    conn.executemany(
        "INSERT INTO inventory_warning VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("b" * 32, "attention", "2026-08-22T08:00:00Z", 1, 41, "mediplaner-primary"),
            ("d" * 32, "none", "2026-08-22T08:00:00Z", 1, 41, "mediplaner-primary"),
        ],
    )
    conn.commit()
    conn.close()


def test_reads_only_actionable_opaque_records_without_mutation(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    projection = read_legacy_unauthenticated_mediplaner_projection(
        path, previous_checkpoint=40
    )
    text = format_mediplaner_briefing(projection, include_receipt=True)

    assert [row.record_ref for row in projection.due_records] == ["a" * 32]
    assert [row.record_ref for row in projection.inventory_warnings] == ["b" * 32]
    assert "MEDIPLANER-FÄLLIGKEITEN (1)" in text
    assert "BESTANDSWARNUNGEN (1)" in text
    assert "aaaaaaaaaaaa…" in text and "bbbbbbbbbbbb…" in text
    assert "cccccccccccc" not in text and "dddddddddddd" not in text
    assert "contract=org.ellmos.mediplaner.reminder-projection@1.0.0" in text
    assert "read_only=true" in text
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_authenticated_manifest_is_verified_before_projection_open(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    snapshot, auth_config, resolver = _authenticated_projection(path, tmp_path)

    projection = read_mediplaner_projection(
        manifest_path=snapshot.manifest_path,
        transport_auth=auth_config,
        secret_resolver=resolver,
        previous_checkpoint=40,
    )

    assert projection.source_checkpoint == 41
    assert projection.publisher_instance == "mediplaner-primary"


def test_normal_consumer_rejects_direct_unauthenticated_database(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)

    with pytest.raises(TypeError):
        read_mediplaner_projection(path)  # type: ignore[misc]


def test_adversarial_exchange_after_auth_is_not_consumed(tmp_path, monkeypatch):
    import sqlite_transit_sync

    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    snapshot, auth_config, resolver = _authenticated_projection(path, tmp_path)
    real_verify = sqlite_transit_sync.verify_authenticated_snapshot

    def verify_then_exchange(*args, **kwargs):
        verified = real_verify(*args, **kwargs)
        replacement = tmp_path / "attacker.sqlite"
        replacement.write_bytes(b"not the authenticated database")
        replacement.replace(verified.path)
        return verified

    monkeypatch.setattr(
        sqlite_transit_sync,
        "verify_authenticated_snapshot",
        verify_then_exchange,
    )
    with pytest.raises(MediplanerProjectionError, match="ausgetauscht"):
        read_mediplaner_projection(
            manifest_path=snapshot.manifest_path,
            transport_auth=auth_config,
            secret_resolver=resolver,
        )


def test_auth_failure_does_not_advance_daily_agent_checkpoint(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    snapshot, auth_config, resolver = _authenticated_projection(path, tmp_path)
    refs = tmp_path / "auth-refs.json"
    refs.write_text(json.dumps(auth_config), encoding="utf-8")

    ok, text = handler.handle(
        "config",
        [
            "mediplaner_briefing",
            f"--manifest={snapshot.manifest_path}",
            f"--auth-refs-file={refs}",
        ],
    )
    assert ok is True and "bleibt deaktiviert" in text
    snapshot.path.write_bytes(b"tampered")

    with patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver):
        ok, text = handler.handle(
            "briefing",
            [f"--mediplaner-manifest={snapshot.manifest_path}"],
            dry_run=False,
        )

    assert ok is False
    assert "Transportauthentifizierung fehlgeschlagen" in text
    conn = sqlite3.connect(handler.db_path)
    stored = json.loads(
        conn.execute(
            "SELECT settings_json FROM briefing_config "
            "WHERE module_name = 'mediplaner_briefing'"
        ).fetchone()[0]
    )
    conn.close()
    assert "last_checkpoint" not in stored
    assert "secret" not in json.dumps(stored).lower()


def test_authenticated_daily_agent_path_persists_checkpoint_after_success(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    snapshot, auth_config, resolver = _authenticated_projection(path, tmp_path)
    refs = tmp_path / "auth-refs.json"
    refs.write_text(json.dumps(auth_config), encoding="utf-8")
    ok, _ = handler.handle(
        "config",
        [
            "mediplaner_briefing",
            f"--manifest={snapshot.manifest_path}",
            f"--auth-refs-file={refs}",
        ],
    )
    assert ok is True

    with patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver):
        ok, text = handler.handle(
            "briefing",
            [f"--mediplaner-manifest={snapshot.manifest_path}"],
            dry_run=False,
        )

    assert ok is True, text
    conn = sqlite3.connect(handler.db_path)
    stored = json.loads(
        conn.execute(
            "SELECT settings_json FROM briefing_config "
            "WHERE module_name = 'mediplaner_briefing'"
        ).fetchone()[0]
    )
    conn.close()
    assert stored["last_checkpoint"] == 41
    assert stored["publisher_instance"] == "mediplaner-primary"


def test_config_rejects_secret_values(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    refs = tmp_path / "unsafe-auth-refs.json"
    refs.write_text(
        json.dumps(
            {
                "active_key_id": "v1",
                "keys": [{
                    "key_id": "v1",
                    "service": "svc",
                    "account": "acct",
                    "sender": "mediplaner-primary",
                    "secret": "must-not-be-here",
                }],
                "trusted_senders": ["mediplaner-primary"],
            }
        ),
        encoding="utf-8",
    )
    ok, text = handler.handle(
        "config",
        [
            "mediplaner_briefing",
            f"--manifest={tmp_path / 'future.json'}",
            f"--auth-refs-file={refs}",
        ],
    )
    assert ok is False
    assert "Secretwerte" in text


def test_config_rejects_direct_unauthenticated_consumer_path(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    ok, text = handler.handle(
        "config",
        ["mediplaner_briefing", f"--projection={tmp_path / 'projection.sqlite'}"],
    )
    assert ok is False
    assert "unauthentifizierte Projektionspfade" in text
    conn = sqlite3.connect(handler.db_path)
    settings = conn.execute(
        "SELECT settings_json FROM briefing_config "
        "WHERE module_name = 'mediplaner_briefing'"
    ).fetchone()[0]
    conn.close()
    assert json.loads(settings) == {}


def test_transport_failure_does_not_advance_consumer_checkpoint(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    refs = tmp_path / "auth-refs.json"
    refs.write_text(
        json.dumps(
            {
                "active_key_id": "v1",
                "keys": [{
                    "key_id": "v1", "service": "svc", "account": "acct",
                    "sender": "mediplaner-primary",
                }],
                "trusted_senders": ["mediplaner-primary"],
                "trust_source": "synthetic-keyring",
            }
        ),
        encoding="utf-8",
    )
    ok, _ = handler.handle(
        "config",
        [
            "mediplaner_briefing",
            f"--manifest={tmp_path / 'missing.sqlite-snapshot.json'}",
            f"--auth-refs-file={refs}",
        ],
    )
    assert ok is True
    with patch(
        "sqlite_transit_sync.OSKeyringSecretResolver", return_value=_MappingResolver()
    ):
        ok, _ = handler.handle(
            "briefing",
            [f"--mediplaner-manifest={tmp_path / 'missing.sqlite-snapshot.json'}"],
            dry_run=False,
        )
    assert ok is False
    conn = sqlite3.connect(handler.db_path)
    settings = json.loads(
        conn.execute(
            "SELECT settings_json FROM briefing_config "
            "WHERE module_name = 'mediplaner_briefing'"
        ).fetchone()[0]
    )
    conn.close()
    assert "last_checkpoint" not in settings


def test_consumer_commit_crash_does_not_advance_checkpoint(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    snapshot, auth_config, resolver = _authenticated_projection(path, tmp_path)
    refs = tmp_path / "auth-refs.json"
    refs.write_text(json.dumps(auth_config), encoding="utf-8")
    ok, _ = handler.handle(
        "config",
        [
            "mediplaner_briefing",
            f"--manifest={snapshot.manifest_path}",
            f"--auth-refs-file={refs}",
        ],
    )
    assert ok is True
    with (
        patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver),
        patch.object(
            handler,
            "_persist_projection_checkpoints",
            side_effect=RuntimeError("synthetischer Commit-Absturz"),
        ),
    ):
        ok, _ = handler.handle(
            "briefing",
            [f"--mediplaner-manifest={snapshot.manifest_path}"],
            dry_run=False,
        )
    assert ok is False
    conn = sqlite3.connect(handler.db_path)
    settings = json.loads(
        conn.execute(
            "SELECT settings_json FROM briefing_config "
            "WHERE module_name = 'mediplaner_briefing'"
        ).fetchone()[0]
    )
    conn.close()
    assert "last_checkpoint" not in settings


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("ALTER TABLE medication_due ADD COLUMN medication_name TEXT", "Spalten-Allowlist"),
        ("UPDATE projection_metadata SET publisher_component = 'other'", "publisher_component"),
        ("UPDATE medication_due SET reminder_kind = 'other'", "reminder_kind"),
        ("UPDATE medication_due SET window_end_at = '2026-08-22T07:59:00Z'", "Fälligkeitsfenster"),
        ("UPDATE inventory_warning SET warning_band = 'secret'", "warning_band"),
    ],
)
def test_contract_drift_fails_closed(tmp_path, statement, message):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    conn = sqlite3.connect(path)
    conn.execute(statement)
    conn.commit()
    conn.close()

    with pytest.raises(MediplanerProjectionError, match=message):
        read_legacy_unauthenticated_mediplaner_projection(path)


def test_unclosed_sidecar_and_consumer_loop_fail_closed(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    Path(f"{path}-wal").write_bytes(b"synthetic")
    with pytest.raises(MediplanerProjectionError, match="nicht geschlossen"):
        read_legacy_unauthenticated_mediplaner_projection(path)

    Path(f"{path}-wal").unlink()
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE projection_metadata SET publisher_instance = 'bach-reminder-consumer'"
    )
    conn.execute(
        "UPDATE medication_due SET publisher_instance = 'bach-reminder-consumer'"
    )
    conn.execute(
        "UPDATE inventory_warning SET publisher_instance = 'bach-reminder-consumer'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(MediplanerProjectionError, match="Loop-Guard"):
        read_legacy_unauthenticated_mediplaner_projection(path)


def test_tombstone_retention_and_active_collision_are_checked(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO projection_tombstones VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "inventory_warning", "b" * 32, "2026-08-22T08:00:00Z",
            "2026-10-22T08:00:00Z", 1, 41, "mediplaner-primary",
        ),
    )
    conn.commit()
    conn.close()

    with pytest.raises(MediplanerProjectionError, match="Tombstone kollidiert"):
        read_legacy_unauthenticated_mediplaner_projection(path)

    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM projection_tombstones")
    conn.execute(
        "INSERT INTO projection_tombstones VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "inventory_warning", "e" * 32, "2026-08-22T08:00:00Z",
            "2026-08-23T08:00:00Z", 1, 41, "mediplaner-primary",
        ),
    )
    conn.commit()
    conn.close()
    with pytest.raises(MediplanerProjectionError, match="Offline-Intervall"):
        read_legacy_unauthenticated_mediplaner_projection(path)


@pytest.mark.parametrize(
    ("table", "column", "value", "message"),
    [
        ("medication_due", "publisher_instance", "other-publisher", "Publisher-Provenienz"),
        ("medication_due", "source_checkpoint", 40, "Quell-Checkpoint"),
        ("inventory_warning", "publisher_instance", "other-publisher", "Publisher-Provenienz"),
        ("inventory_warning", "source_checkpoint", 40, "Quell-Checkpoint"),
    ],
)
def test_record_provenance_must_match_metadata(tmp_path, table, column, value, message):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    conn = sqlite3.connect(path)
    conn.execute(f'UPDATE "{table}" SET "{column}" = ?', (value,))
    conn.commit()
    conn.close()

    with pytest.raises(MediplanerProjectionError, match=message):
        read_legacy_unauthenticated_mediplaner_projection(path)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("publisher_instance", "other-publisher", "Publisher-Provenienz"),
        ("source_checkpoint", 40, "Quell-Checkpoint"),
    ],
)
def test_tombstone_provenance_must_match_metadata(tmp_path, column, value, message):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO projection_tombstones VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "inventory_warning", "e" * 32, "2026-08-22T08:00:00Z",
            "2026-10-22T08:00:00Z", 1, 41, "mediplaner-primary",
        ),
    )
    conn.execute(
        f'UPDATE projection_tombstones SET "{column}" = ?', (value,)
    )
    conn.commit()
    conn.close()

    with pytest.raises(MediplanerProjectionError, match=message):
        read_legacy_unauthenticated_mediplaner_projection(path)


def test_checkpoint_must_advance(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    with pytest.raises(MediplanerProjectionError, match="nicht neuer"):
        read_legacy_unauthenticated_mediplaner_projection(
            path, previous_checkpoint=41
        )


def test_sqlite_uri_metacharacters_in_path_are_quoted(tmp_path):
    directory = tmp_path / "projection # %"
    directory.mkdir()
    path = directory / "mediplaner.sqlite"
    _create_projection(path)

    projection = read_legacy_unauthenticated_mediplaner_projection(path)

    assert projection.database_name == "mediplaner.sqlite"


def _handler_with_briefing_db(tmp_path: Path) -> DailyAgentHandler:
    system_dir = tmp_path / "system"
    (system_dir / "data").mkdir(parents=True)
    handler = DailyAgentHandler(system_dir)
    handler.db_path = system_dir / "data" / "bach.db"
    conn = sqlite3.connect(handler.db_path)
    conn.execute(
        """
        CREATE TABLE briefing_config (
            module_name TEXT PRIMARY KEY,
            is_active INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            settings_json TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "INSERT INTO briefing_config VALUES ('mediplaner_briefing', 0, 60, '{}')"
    )
    conn.commit()
    conn.close()
    return handler


def _configure_delivery_database(
    handler: DailyAgentHandler, manifest: Path, auth_config: dict
) -> None:
    conn = sqlite3.connect(handler.db_path)
    conn.execute(
        "UPDATE briefing_config SET is_active = 1, settings_json = ? "
        "WHERE module_name = 'mediplaner_briefing'",
        (
            json.dumps(
                {
                    "manifest_path": str(manifest),
                    "transport_auth": auth_config,
                }
            ),
        ),
    )
    conn.execute(
        """
        CREATE TABLE connector_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector_name TEXT NOT NULL,
            direction TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            content TEXT NOT NULL,
            processed INTEGER NOT NULL,
            error TEXT,
            retry_count INTEGER NOT NULL,
            max_retries INTEGER NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def test_daily_agent_can_preview_mediplaner_projection(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    projection = tmp_path / "mediplaner.sqlite"
    _create_projection(projection)
    snapshot, auth_config, resolver = _authenticated_projection(projection, tmp_path)
    _configure_delivery_database(handler, snapshot.manifest_path, auth_config)

    with patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver):
        ok, text = handler.handle(
            "briefing",
            ["--mediplaner-receipt", "--dry-run"],
            dry_run=True,
        )

    assert ok is True
    assert "MEDIPLANER-FÄLLIGKEITEN (1)" in text
    assert "BESTANDSWARNUNGEN (1)" in text
    assert "publisher=mediplaner-primary" in text
    conn = sqlite3.connect(handler.db_path)
    settings = conn.execute(
        "SELECT settings_json FROM briefing_config WHERE module_name = 'mediplaner_briefing'"
    ).fetchone()[0]
    conn.close()
    assert "last_checkpoint" not in json.loads(settings)


def test_daily_agent_persists_checkpoint_and_rejects_replay(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    projection = tmp_path / "mediplaner.sqlite"
    _create_projection(projection)
    snapshot, auth_config, resolver = _authenticated_projection(projection, tmp_path)
    _configure_delivery_database(handler, snapshot.manifest_path, auth_config)

    with patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver):
        ok, _ = handler.handle("briefing", [], dry_run=False)
    assert ok is True

    conn = sqlite3.connect(handler.db_path)
    settings = __import__("json").loads(
        conn.execute(
            "SELECT settings_json FROM briefing_config "
            "WHERE module_name = 'mediplaner_briefing'"
        ).fetchone()[0]
    )
    conn.close()
    assert settings["last_checkpoint"] == 41
    assert settings["publisher_instance"] == "mediplaner-primary"
    assert len(settings["last_projection_sha256"]) == 64

    with patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver):
        ok, text = handler.handle("briefing", [], dry_run=False)
    assert ok is False
    assert "nicht neuer als der Consumer-Checkpoint" in text



def test_later_projection_failure_does_not_consume_mediplaner_checkpoint(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    projection = tmp_path / "mediplaner.sqlite"
    _create_projection(projection)
    snapshot, auth_config, resolver = _authenticated_projection(projection, tmp_path)
    _configure_delivery_database(handler, snapshot.manifest_path, auth_config)

    with patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver):
        ok, text = handler.handle(
            "briefing",
            [f"--routinika-manifest={tmp_path / 'missing-routinika.json'}"],
            dry_run=False,
        )

    assert ok is False
    assert "routinika_briefing" in text
    conn = sqlite3.connect(handler.db_path)
    settings = conn.execute(
        "SELECT settings_json FROM briefing_config WHERE module_name = 'mediplaner_briefing'"
    ).fetchone()[0]
    conn.close()
    assert "last_checkpoint" not in __import__("json").loads(settings)


def test_failed_delivery_does_not_consume_projection(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    projection = tmp_path / "mediplaner.sqlite"
    _create_projection(projection)
    snapshot, auth_config, resolver = _authenticated_projection(projection, tmp_path)
    _configure_delivery_database(handler, snapshot.manifest_path, auth_config)
    connector = MagicMock()
    connector.send_message.return_value = False

    with (
        patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver),
        patch(
            "hub.connector.ConnectorHandler._instantiate",
            return_value=(connector, ""),
        ),
    ):
        ok, text = handler.handle("deliver", ["--telegram"], dry_run=False)

    assert ok is False
    assert "nicht gesendet" in text
    conn = sqlite3.connect(handler.db_path)
    settings = conn.execute(
        "SELECT settings_json FROM briefing_config WHERE module_name = 'mediplaner_briefing'"
    ).fetchone()[0]
    conn.close()
    assert "last_checkpoint" not in __import__("json").loads(settings)


def test_successful_delivery_persists_then_duplicate_skips_before_replay(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    projection = tmp_path / "mediplaner.sqlite"
    _create_projection(projection)
    snapshot, auth_config, resolver = _authenticated_projection(projection, tmp_path)
    _configure_delivery_database(handler, snapshot.manifest_path, auth_config)
    connector = MagicMock()
    connector.send_message.return_value = True

    with (
        patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver),
        patch(
            "hub.connector.ConnectorHandler._instantiate",
            return_value=(connector, ""),
        ),
    ):
        first_ok, _ = handler.handle("deliver", ["--telegram"], dry_run=False)

    with (
        patch("sqlite_transit_sync.OSKeyringSecretResolver", return_value=resolver),
        patch("hub.connector.ConnectorHandler._instantiate") as instantiate,
    ):
        second_ok, second_text = handler.handle("deliver", ["--telegram"], dry_run=False)

    assert first_ok is True and second_ok is True
    assert "[SKIP]" in second_text
    instantiate.assert_not_called()
    conn = sqlite3.connect(handler.db_path)
    settings = __import__("json").loads(
        conn.execute(
            "SELECT settings_json FROM briefing_config "
            "WHERE module_name = 'mediplaner_briefing'"
        ).fetchone()[0]
    )
    conn.close()
    assert settings["last_checkpoint"] == 41


def test_daily_agent_stores_only_inactive_consumer_settings(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    manifest = tmp_path / "future-mediplaner.sqlite-snapshot.json"
    refs = tmp_path / "auth-refs.json"
    refs.write_text(
        json.dumps(
            {
                "active_key_id": "v1",
                "keys": [{
                    "key_id": "v1",
                    "service": "svc",
                    "account": "acct",
                    "sender": "mediplaner-primary",
                }],
                "trusted_senders": ["mediplaner-primary"],
                "trust_source": "synthetic-keyring",
            }
        ),
        encoding="utf-8",
    )

    ok, text = handler.handle(
        "config",
        [
            "mediplaner_briefing",
            f"--manifest={manifest}",
            f"--auth-refs-file={refs}",
            "--minimum-offline-seconds=2592000",
        ],
    )

    assert ok is True
    assert "bleibt deaktiviert" in text
    conn = sqlite3.connect(handler.db_path)
    row = conn.execute(
        "SELECT is_active, settings_json FROM briefing_config "
        "WHERE module_name = 'mediplaner_briefing'"
    ).fetchone()
    conn.close()
    assert row[0] == 0
    assert __import__("json").loads(row[1]) == {
        "minimum_offline_seconds": 2592000,
        "manifest_path": str(manifest.resolve()),
        "transport_auth": json.loads(refs.read_text(encoding="utf-8")),
    }
