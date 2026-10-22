"""Projektquellen-Register: hostlokales Repositoryregister in der BACH-Datenbank.

Jeder Eintrag bindet einen versionierten ``repo_key`` an einen
hostlokalen Projekt-Checkout (origin, approved_ref, worktrees_root).
Das Register ist fail-closed: Ohne Eintrag, ohne übereinstimmende
Register-Revision oder ohne passenden Origin wird kein Pfad
zurückgegeben. Das Register klont und fetcht niemals selbst; die
Pflege (add/update/remove) ist ausschließlich dem Actor ``user``
über die Settings-CLI erlaubt.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_ACTOR_USER = "user"

# Nur für Tests überschreibbar; Produktionscode lässt den Wert unangetastet.
_DB_PATH_OVERRIDE: str | Path | None = None


def _db_path() -> Path:
    if _DB_PATH_OVERRIDE is not None:
        return Path(_DB_PATH_OVERRIDE)
    try:
        from ..bach_paths import BACH_DB
    except ImportError:
        from hub.bach_paths import BACH_DB
    return Path(BACH_DB)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _ensure_table(conn)
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_source_register (
            repo_key TEXT PRIMARY KEY,
            checkout_path TEXT NOT NULL,
            origin TEXT NOT NULL,
            approved_ref TEXT NOT NULL,
            worktrees_root TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_user(actor: str) -> None:
    if actor != _ACTOR_USER:
        raise RuntimeError("Registerpflege ist ausschließlich dem Actor 'user' erlaubt")


def validate_repo_key(repo_key: str) -> str:
    if not isinstance(repo_key, str) or not REPO_KEY_PATTERN.match(repo_key):
        raise RuntimeError(
            "repo_key ungültig: nur Kleinbuchstaben, Ziffern und Bindestrich "
            "(maximal 64 Zeichen, beginnend mit Kleinbuchstabe oder Ziffer)"
        )
    return repo_key


def validate_origin(origin: str) -> str:
    if not isinstance(origin, str):
        raise RuntimeError("origin muss eine Zeichenkette sein")
    stripped = origin.strip()
    if not stripped or any(character.isspace() for character in stripped):
        raise RuntimeError("origin darf keine Leerzeichen enthalten")
    parsed = urlparse(stripped)
    if parsed.scheme != "https":
        raise RuntimeError("origin muss eine https-URL sein")
    if not parsed.netloc or not parsed.hostname:
        raise RuntimeError("origin ohne Host")
    if "@" in parsed.netloc:
        raise RuntimeError("origin darf keine Nutzerinformationen enthalten")
    if parsed.query or parsed.fragment:
        raise RuntimeError("origin darf keine Query- oder Fragmentanteile enthalten")
    return stripped


def validate_checkout_path(checkout_path: "str | Path") -> Path:
    if not isinstance(checkout_path, (str, Path)):
        raise RuntimeError("checkout_path muss ein absoluter Pfad sein")
    path = Path(checkout_path)
    if not path.is_absolute():
        raise RuntimeError("checkout_path muss ein absoluter Pfad sein")
    if path.is_symlink():
        raise RuntimeError("checkout_path darf kein Symlink sein")
    if not path.is_dir():
        raise RuntimeError("checkout_path ist kein Verzeichnis")
    git_dir = path / ".git"
    if not git_dir.exists():
        raise RuntimeError("checkout_path enthält kein .git")
    if git_dir.is_symlink():
        raise RuntimeError(".git im checkout_path darf kein Symlink sein")
    return path


def _git_output(cwd: Path, args: "list[str]") -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git {' '.join(args)} fehlgeschlagen: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} fehlgeschlagen: {detail}")
    return (completed.stdout or "").strip()


def read_origin_url(checkout_path: "str | Path") -> str:
    url = _git_output(Path(checkout_path), ["config", "--get", "remote.origin.url"])
    if not url:
        raise RuntimeError("remote.origin.url ist im Projekt-Checkout nicht konfiguriert")
    return validate_origin(url)


def read_head_sha(checkout_path: "str | Path") -> str:
    sha = _git_output(Path(checkout_path), ["rev-parse", "HEAD"])
    if not sha:
        raise RuntimeError("HEAD konnte im Projekt-Checkout nicht gelesen werden")
    return sha


def list_entries() -> "list[dict]":
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM project_source_register ORDER BY repo_key"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def read_entry(repo_key: str) -> dict:
    repo_key = validate_repo_key(repo_key)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM project_source_register WHERE repo_key = ?",
            (repo_key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise RuntimeError(f"Kein Projektquellen-Registereintrag für {repo_key!r}")
    entry = dict(row)
    entry["revision"] = int(entry["revision"])
    return entry


def register_revision(repo_key: str) -> int:
    return int(read_entry(repo_key)["revision"])


def add_entry(
    *,
    actor: str,
    repo_key: str,
    checkout_path: "str | Path",
    origin: "str | None" = None,
    approved_ref: "str | None" = None,
    worktrees_root: "str | Path | None" = None,
) -> dict:
    _require_user(actor)
    repo_key = validate_repo_key(repo_key)
    checkout = validate_checkout_path(checkout_path)
    if origin is None:
        origin_value = read_origin_url(checkout)
    else:
        origin_value = validate_origin(origin)
    if approved_ref is None:
        ref_value = read_head_sha(checkout)
    else:
        ref_value = str(approved_ref).strip()
        if not ref_value:
            raise RuntimeError("approved_ref darf nicht leer sein")
    if worktrees_root is None:
        worktrees_value = str(Path.home() / "services" / f"{repo_key}-worktrees")
    else:
        worktrees_value = str(Path(worktrees_root))
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT repo_key FROM project_source_register WHERE repo_key = ?",
            (repo_key,),
        ).fetchone()
        if existing is not None:
            raise RuntimeError(f"repo_key {repo_key!r} ist bereits registriert")
        conn.execute(
            """
            INSERT INTO project_source_register
                (repo_key, checkout_path, origin, approved_ref, worktrees_root,
                 revision, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                repo_key,
                str(checkout),
                origin_value,
                ref_value,
                worktrees_value,
                _utcnow(),
                actor,
            ),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return read_entry(repo_key)


def update_entry(
    *,
    actor: str,
    repo_key: str,
    checkout_path: "str | Path | None" = None,
    origin: "str | None" = None,
    approved_ref: "str | None" = None,
    worktrees_root: "str | Path | None" = None,
) -> dict:
    _require_user(actor)
    repo_key = validate_repo_key(repo_key)
    current = read_entry(repo_key)
    checkout_value = current["checkout_path"]
    origin_value = current["origin"]
    ref_value = current["approved_ref"]
    worktrees_value = current["worktrees_root"]
    if checkout_path is not None:
        checkout_value = str(validate_checkout_path(checkout_path))
    if origin is not None:
        origin_value = validate_origin(origin)
    if approved_ref is not None:
        ref_value = str(approved_ref).strip()
        if not ref_value:
            raise RuntimeError("approved_ref darf nicht leer sein")
    if worktrees_root is not None:
        worktrees_value = str(Path(worktrees_root))
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE project_source_register
               SET checkout_path = ?,
                   origin = ?,
                   approved_ref = ?,
                   worktrees_root = ?,
                   revision = revision + 1,
                   updated_at = ?,
                   updated_by = ?
             WHERE repo_key = ?
            """,
            (
                checkout_value,
                origin_value,
                ref_value,
                worktrees_value,
                _utcnow(),
                actor,
                repo_key,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                f"Registereintrag {repo_key!r} konnte nicht aktualisiert werden"
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return read_entry(repo_key)


def remove_entry(*, actor: str, repo_key: str) -> None:
    _require_user(actor)
    repo_key = validate_repo_key(repo_key)
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM project_source_register WHERE repo_key = ?",
            (repo_key,),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Kein Projektquellen-Registereintrag für {repo_key!r}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def resolve_repo(
    repo_key: str,
    expected_revision: "int | str | None",
    expected_origin: "str | None" = None,
) -> Path:
    repo_key = validate_repo_key(repo_key)
    if expected_revision is None:
        raise RuntimeError("expected_revision erforderlich: Register-Revision fehlt")
    try:
        expected_revision_int = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("expected_revision muss eine Ganzzahl sein") from exc
    entry = read_entry(repo_key)
    if entry["revision"] != expected_revision_int:
        raise RuntimeError(
            "Register-Revision divergiert: "
            f"erwartet {expected_revision_int}, aktuell {entry['revision']}"
        )
    checkout = validate_checkout_path(entry["checkout_path"])
    live_origin = read_origin_url(checkout)
    if live_origin != entry["origin"]:
        raise RuntimeError("origin des Projekt-Checkouts weicht vom Registereintrag ab")
    if expected_origin is not None:
        expected_origin_value = validate_origin(expected_origin)
        if expected_origin_value != entry["origin"]:
            raise RuntimeError("expected_origin weicht vom Registereintrag ab")
    # Bewusst ohne Clone und ohne Fetch: Das Register liest nur hostlokal.
    return checkout