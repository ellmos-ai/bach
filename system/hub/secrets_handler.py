#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""BACH secrets management backed by the operating-system keyring.

Secret values live exclusively in the OS credential store.  ``bach.db`` and
``~/.bach/bach_secrets.json`` contain metadata plus a backend marker, never a
credential.  Legacy plaintext stores are migrated transactionally and are
only scrubbed after every keyring write has been read back successfully.
"""

from __future__ import annotations

import getpass
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    import keyring as _system_keyring
except ImportError:  # pragma: no cover - exercised through an injected backend
    _system_keyring = None

_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

try:
    from core.database import get_connection as _get_connection

    GET_CONNECTION = _get_connection
except ImportError:
    def GET_CONNECTION():
        return sqlite3.connect(str(BACH_DB))


# BACH_SECRETS_FILE (Testisolation, T-20260902-646684582): sonst schreiben
# Tests, die GET_CONNECTION isolieren aber keinen eigenen system_config-Eintrag
# 'secrets_file_path' anlegen, in die produktive ~/.bach/bach_secrets.json.
# Backward-kompatible Konstante fuer bestehende Importe/Tests. get_secrets_file_path()
# liest die Env-Var selbst zur Aufrufzeit (siehe dort) statt diese Konstante zu
# verwenden, damit ein spaeter (z. B. per Fixture) gesetzter Wert nicht an einem
# beim Modul-Import eingefrorenen Stand vorbeilaeuft.
DEFAULT_SECRETS_FILE = Path(
    os.environ.get("BACH_SECRETS_FILE", str(Path.home() / ".bach" / "bach_secrets.json"))
).expanduser()
KEYRING_SERVICE = "ellmos-bach"
KEYRING_MARKER = "keyring://ellmos-bach"


class SecretsBackendError(RuntimeError):
    """Raised when the OS credential store is unavailable or inconsistent."""


def _backend_or_raise(backend=None):
    backend = backend or _system_keyring
    if backend is None:
        raise SecretsBackendError(
            "Kein OS-Schlüsselbund verfügbar; Installation mit requirements.txt prüfen."
        )
    try:
        active = backend.get_keyring() if hasattr(backend, "get_keyring") else backend
        priority = getattr(active, "priority", 1)
        if priority is not None and priority <= 0:
            raise SecretsBackendError("Der aktive OS-Schlüsselbund ist nicht nutzbar.")
    except SecretsBackendError:
        raise
    except Exception as exc:
        raise SecretsBackendError("OS-Schlüsselbund konnte nicht initialisiert werden.") from exc
    return backend


def get_secrets_file_path():
    """Return the configured metadata-index path.

    Precedence: BACH_SECRETS_FILE env override > system_config DB row > default.
    The env var is read here at call time (not via the frozen DEFAULT_SECRETS_FILE
    constant) and wins over a persisted DB row. Root cause of T-20260902-646684582
    Befund A: this function used to check the DB row FIRST, so a host whose DB
    already carried a 'secrets_file_path' row (production config, set via
    'bach settings set secrets_file_path=...') silently overrode the env-var
    isolation tests rely on - the BACH_SECRETS_FILE fix never took effect there.
    An override that a stored DB value can defeat isn't an override; the same
    "env beats stored default" rule already applies to BACH_DB/BACH_BACKUPS_DIR/
    BACH_PLANS_DIR, so this makes secrets_file_path consistent with its siblings.
    """
    env_override = os.environ.get("BACH_SECRETS_FILE")
    if env_override:
        return Path(env_override).expanduser()
    try:
        conn = GET_CONNECTION()
        try:
            row = conn.execute(
                "SELECT value FROM system_config WHERE key = 'secrets_file_path'"
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            return Path(row[0]).expanduser()
    except (sqlite3.Error, OSError):
        pass
    return Path.home() / ".bach" / "bach_secrets.json"


def get_secret_value(key: str, connection=None, keyring_backend=None):
    """Resolve a secret without writing it to stdout.

    Legacy plaintext is never returned to consumers. Run ``bach secrets sync``
    to migrate it; an unavailable or incomplete keyring fails closed.
    """
    backend = _backend_or_raise(keyring_backend)
    try:
        value = backend.get_password(KEYRING_SERVICE, key)
    except Exception as exc:
        raise SecretsBackendError("Secret konnte nicht aus dem OS-Schlüsselbund gelesen werden.") from exc
    return value


class SecretsHandler:
    """Manage secret metadata and values stored in the OS keyring."""

    def __init__(self, secrets_file=None, keyring_backend=None):
        self.secrets_file = Path(secrets_file) if secrets_file else get_secrets_file_path()
        self.keyring = _backend_or_raise(keyring_backend)
        self.conn = GET_CONNECTION()

    def __del__(self):
        if getattr(self, "conn", None):
            self.conn.close()

    def _keyring_get(self, key):
        try:
            return self.keyring.get_password(KEYRING_SERVICE, key)
        except Exception as exc:
            raise SecretsBackendError(
                "Secret konnte nicht aus dem OS-Schlüsselbund gelesen werden."
            ) from exc

    def _keyring_set(self, key, value):
        try:
            self.keyring.set_password(KEYRING_SERVICE, key, value)
            if self.keyring.get_password(KEYRING_SERVICE, key) != value:
                raise SecretsBackendError("Keyring-Schreibprüfung fehlgeschlagen.")
        except SecretsBackendError:
            raise
        except Exception as exc:
            raise SecretsBackendError(
                "Secret konnte nicht verifiziert in den OS-Schlüsselbund geschrieben werden."
            ) from exc

    def _keyring_delete(self, key):
        try:
            if self._keyring_get(key) is not None:
                self.keyring.delete_password(KEYRING_SERVICE, key)
        except SecretsBackendError:
            raise
        except Exception as exc:
            raise SecretsBackendError(
                "Secret konnte nicht aus dem OS-Schlüsselbund gelöscht werden."
            ) from exc

    def list_secrets(self):
        rows = self.conn.execute(
            """
            SELECT key, description, category, source
            FROM secrets
            ORDER BY category, key
            """
        ).fetchall()
        if not rows:
            print("Keine Secrets vorhanden.")
            return
        print(f"\n{'Key':<30} {'Category':<12} {'Description':<40} {'Backend':<10}")
        print("-" * 100)
        for key, desc, category, source in rows:
            desc = desc or ""
            desc_short = (desc[:37] + "...") if len(desc) > 40 else desc
            backend = "keyring" if self._keyring_get(key) is not None else (source or "missing")
            print(f"{key:<30} {(category or 'general'):<12} {desc_short:<40} {backend:<10}")
        print(f"\nGesamt: {len(rows)} Secrets")

    def get_secret(self, key, *, report=True):
        row = self.conn.execute(
            "SELECT description FROM secrets WHERE key = ?", (key,)
        ).fetchone()
        value = self._keyring_get(key)
        if value is None:
            if report:
                print(f"FEHLER: Secret '{key}' nicht gefunden.", file=sys.stderr)
            return None
        if report:
            description = row[0] if row else ""
            print(f"Key: {key}")
            print(f"Description: {description or ''}")
            print("Value: [geschützt; keine Ausgabe auf stdout]")
        return value

    def set_secret(self, key, value, description="", category="general"):
        if not key or key.startswith("_example_"):
            raise ValueError("Ungültiger Secret-Key.")
        old_value = self._keyring_get(key)
        self._keyring_set(key, value)
        try:
            exists = self.conn.execute(
                "SELECT id FROM secrets WHERE key = ?", (key,)
            ).fetchone() is not None
            if exists:
                self.conn.execute(
                    """
                    UPDATE secrets
                    SET value = ?, description = ?, category = ?, source = 'keyring',
                        updated_at = datetime('now')
                    WHERE key = ?
                    """,
                    (KEYRING_MARKER, description, category, key),
                )
                action = "aktualisiert"
            else:
                self.conn.execute(
                    """
                    INSERT INTO secrets
                        (key, value, description, category, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'keyring', datetime('now'), datetime('now'))
                    """,
                    (key, KEYRING_MARKER, description, category),
                )
                action = "erstellt"
            self._sync_to_file(commit=False)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            if old_value is None:
                self._keyring_delete(key)
            else:
                self._keyring_set(key, old_value)
            raise
        print(f"OK: Eintrag {action} (OS-Schlüsselbund).")
        return True

    def delete_secret(self, key):
        row = self.conn.execute("SELECT id FROM secrets WHERE key = ?", (key,)).fetchone()
        old_value = self._keyring_get(key)
        if row is None and old_value is None:
            print(f"WARN: Secret '{key}' nicht gefunden.")
            return False
        self._keyring_delete(key)
        try:
            self.conn.execute("DELETE FROM secrets WHERE key = ?", (key,))
            self._sync_to_file(commit=False)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            if old_value is not None:
                self._keyring_set(key, old_value)
            raise
        print(f"OK: Secret '{key}' gelöscht.")
        return True

    def _load_index(self):
        if not self.secrets_file.exists():
            return {"meta": {}, "secrets": {}}
        try:
            with self.secrets_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            raise ValueError(f"Secrets-Metadatenindex ist nicht lesbar: {self.secrets_file}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("secrets", {}), dict):
            raise ValueError("Secrets-Metadatenindex hat ein ungültiges Format.")
        return data

    def migrate_legacy(self):
        """Move all legacy plaintext values to the keyring, then scrub stores."""
        data = self._load_index()
        records = {}
        for row in self.conn.execute(
            "SELECT key, value, description, category, created_at FROM secrets"
        ).fetchall():
            key, value, description, category, created = row
            if key.startswith("_example_"):
                continue
            records[key] = {
                "value": None if value == KEYRING_MARKER else value,
                "description": description or "",
                "category": category or "general",
                "created_at": created,
            }

        for key, item in data.get("secrets", {}).items():
            if key.startswith("_example_") or not isinstance(item, dict):
                continue
            current = records.setdefault(
                key,
                {
                    "value": None,
                    "description": item.get("description", ""),
                    "category": item.get("category", "general"),
                    "created_at": item.get("created_at"),
                },
            )
            file_value = item.get("value")
            if file_value == KEYRING_MARKER:
                file_value = None
            if current["value"] is not None and file_value is not None and current["value"] != file_value:
                raise SecretsBackendError(
                    f"Konflikt zwischen Datei und DB für Secret '{key}'; Migration abgebrochen."
                )
            if current["value"] is None and file_value is not None:
                current["value"] = file_value
            if not current["description"]:
                current["description"] = item.get("description", "")
            if current["category"] == "general" and item.get("category"):
                current["category"] = item["category"]

        newly_created = []
        migrated = 0
        try:
            for key, item in records.items():
                legacy_value = item["value"]
                existing = self._keyring_get(key)
                if legacy_value is not None:
                    if existing is not None and existing != legacy_value:
                        raise SecretsBackendError(
                            f"Keyring-Konflikt für Secret '{key}'; Migration abgebrochen."
                        )
                    if existing is None:
                        self._keyring_set(key, legacy_value)
                        newly_created.append(key)
                    migrated += 1
                elif existing is None:
                    raise SecretsBackendError(
                        f"Secret '{key}' hat weder Legacy-Wert noch Keyring-Eintrag."
                    )

            self.conn.execute("BEGIN")
            for key, item in records.items():
                self.conn.execute(
                    """
                    INSERT INTO secrets
                        (key, value, description, category, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'keyring', COALESCE(?, datetime('now')), datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        description = excluded.description,
                        category = excluded.category,
                        source = 'keyring',
                        updated_at = datetime('now')
                    """,
                    (
                        key,
                        KEYRING_MARKER,
                        item["description"],
                        item["category"],
                        item["created_at"],
                    ),
                )
            self._sync_to_file(commit=False)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            for key in newly_created:
                try:
                    self._keyring_delete(key)
                except SecretsBackendError:
                    pass
            raise

        # Remove deleted plaintext from SQLite freelists/WAL after the durable commit.
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        try:
            self.conn.execute("VACUUM")
        except sqlite3.Error:
            pass
        return migrated

    def sync_from_file(self, enforce_authority=True, *, quiet=False):
        """Migrate legacy values and refresh the metadata index.

        ``enforce_authority`` remains accepted for API compatibility, but a
        missing file never deletes credentials.  That old behaviour could turn
        a transient filesystem problem into a credential-loss incident.
        """
        try:
            count = self.migrate_legacy()
        except (ValueError, SecretsBackendError) as exc:
            if not quiet:
                print(f"FEHLER: Secrets-Sync abgebrochen: {exc}", file=sys.stderr)
            return False
        if not quiet:
            print(f"OK: Secrets im OS-Schlüsselbund verifiziert: {count} Legacy-Einträge migriert")
        return True

    def _sync_to_file(self, *, commit=True):
        rows = self.conn.execute(
            """
            SELECT key, description, category, created_at
            FROM secrets
            ORDER BY key
            """
        ).fetchall()
        secrets = {
            key: {
                "backend": "keyring",
                # Compatibility marker: legacy BACH versions copy this field
                # into SQLite. It is a locator, never a credential value.
                "value": KEYRING_MARKER,
                "description": description or "",
                "category": category or "general",
                "created_at": created,
            }
            for key, description, category, created in rows
            if not key.startswith("_example_")
        }
        data = {
            "meta": {
                "version": "2.0",
                "updated": datetime.now().isoformat(),
                "backend": "os-keyring",
                "contains_secret_values": False,
            },
            "secrets": secrets,
            "notes": [
                "Metadata only. Secret values are stored in the operating-system keyring.",
                "Do not add a value field to this file.",
            ],
        }
        self.secrets_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.secrets_file.with_name(self.secrets_file.name + ".tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.secrets_file)
        if commit:
            self.conn.commit()


def _print_help():
    print(
        """
BACH Secrets-Management

Verwendung:
    bach secrets list
    bach secrets get <key>               Verfügbarkeit prüfen; Wert wird nie ausgegeben
    bach secrets set <key> [Optionen]     Wert interaktiv verdeckt eingeben
    bach secrets set <key> --stdin        Wert aus stdin lesen
    bach secrets delete <key>
    bach secrets sync                     Legacy-Klartext sicher migrieren

Optionen für set:
    --desc=TEXT
    --category=CAT
    --stdin

Secret-Werte in Prozessargumenten sind gesperrt. Werte liegen ausschließlich
im OS-Schlüsselbund; bach.db und ~/.bach/bach_secrets.json enthalten Metadaten.
"""
    )


def handle_secrets_command(args):
    if not args or args[0] in ("-h", "--help"):
        _print_help()
        return
    handler = SecretsHandler()
    subcommand = args[0]

    if subcommand == "list":
        handler.list_secrets()
    elif subcommand == "get":
        if len(args) < 2:
            print("FEHLER: Key fehlt. Verwendung: bach secrets get <key>", file=sys.stderr)
            return
        handler.get_secret(args[1])
    elif subcommand == "set":
        if len(args) < 2:
            print("FEHLER: Key fehlt. Verwendung: bach secrets set <key> [--stdin]", file=sys.stderr)
            return
        key = args[1]
        description = ""
        category = "general"
        use_stdin = False
        for arg in args[2:]:
            if arg.startswith("--desc="):
                description = arg[len("--desc="):]
            elif arg.startswith("--category="):
                category = arg[len("--category="):]
            elif arg == "--stdin":
                use_stdin = True
            else:
                print(
                    "FEHLER: Secret-Werte in Prozessargumenten sind gesperrt; interaktiv oder --stdin verwenden.",
                    file=sys.stderr,
                )
                return
        if use_stdin:
            value = sys.stdin.read()
            if value.endswith("\n"):
                value = value[:-1]
            if value.endswith("\r"):
                value = value[:-1]
        elif sys.stdin.isatty():
            value = getpass.getpass("Secret-Wert: ")
        else:
            print("FEHLER: Nicht-interaktive Eingabe erfordert --stdin.", file=sys.stderr)
            return
        handler.set_secret(key, value, description, category)
    elif subcommand == "delete":
        if len(args) < 2:
            print("FEHLER: Key fehlt. Verwendung: bach secrets delete <key>", file=sys.stderr)
            return
        handler.delete_secret(args[1])
    elif subcommand == "sync":
        if not handler.sync_from_file(enforce_authority=False):
            raise SystemExit(1)
    else:
        print(f"FEHLER: Unbekannter Subcommand: {subcommand}", file=sys.stderr)
        print("Verwendung: bach secrets [list|get|set|delete|sync]", file=sys.stderr)


if __name__ == "__main__":
    handle_secrets_command(sys.argv[1:])
