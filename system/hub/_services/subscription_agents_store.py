# SPDX-License-Identifier: MIT
"""Persistenz fuer Subscription-Prompt-Agents.

Der Store haelt zwei Tabellen in EINER SQLite-Datenbank:

* ``subscription_prompt_agents`` - der Agent selbst (Name, Titel, Bild,
  vererbte Blueprint-Referenz, Modell, Status, Heartbeat/Expiry-Zeitpunkte).
* ``subscription_prompt_agent_prompts`` - der zugehoerige Prompt.

Beide Datensaetze sind fest gekoppelt: Wird ein Agent geloescht, verschwindet
sein Prompt in derselben Transaktion - und umgekehrt. Es wird zwischen den
beiden Teilschritten niemals ``commit()`` aufgerufen.

Die Verbindung kommt immer von aussen (``sqlite3.Connection``); der Store
kennt keinen globalen Datenbankpfad. Statuswerte:

* ``idle``    - angelegt, aber nicht gestartet
* ``running`` - laeuft, ``expires_at`` ist gesetzt (Auto-Logout)
* ``stopped`` - bewusst beendet
* ``expired`` - Heartbeat abgelaufen, Auto-Logout wurde ausgewertet
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_PROMPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

AGENT_TABLE = "subscription_prompt_agents"
PROMPT_TABLE = "subscription_prompt_agent_prompts"

MAX_NAME_CHARS = 80
MAX_TITLE_CHARS = 200
MAX_TEXT_CHARS = 20_000
MAX_SKILL_CHARS = 120
MAX_SKILLS = 50
MAX_MODEL_CHARS = 120
MAX_PROMPT_CHARS = 120_000

DEFAULT_HEARTBEAT_TTL_SECONDS = 900
MIN_HEARTBEAT_TTL_SECONDS = 60
MAX_HEARTBEAT_TTL_SECONDS = 86_400

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"
STATUS_EXPIRED = "expired"
_STATUSES = frozenset({STATUS_IDLE, STATUS_RUNNING, STATUS_STOPPED, STATUS_EXPIRED})

_AGENT_COLUMNS = (
    "id",
    "name",
    "title",
    "description",
    "avatar",
    "blueprint_id",
    "prompt_id",
    "skills_json",
    "model",
    "status",
    "last_heartbeat_at",
    "expires_at",
    "created_at",
    "updated_at",
)
_AGENT_SELECT = ", ".join(_AGENT_COLUMNS)


# --------------------------------------------------------------------------
# Zeit- und Typhelfer
# --------------------------------------------------------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} muss eine positive Ganzzahl sein")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} muss eine positive Ganzzahl sein") from None
    if number <= 0:
        raise ValueError(f"{field} muss eine positive Ganzzahl sein")
    return number


def _as_ttl(value: Any) -> int:
    if value is None:
        return DEFAULT_HEARTBEAT_TTL_SECONDS
    if isinstance(value, bool):
        raise ValueError("ttl_seconds muss eine Ganzzahl sein")
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        raise ValueError("ttl_seconds muss eine Ganzzahl sein") from None
    if ttl < MIN_HEARTBEAT_TTL_SECONDS or ttl > MAX_HEARTBEAT_TTL_SECONDS:
        raise ValueError(
            "ttl_seconds muss zwischen "
            f"{MIN_HEARTBEAT_TTL_SECONDS} und {MAX_HEARTBEAT_TTL_SECONDS} liegen"
        )
    return ttl


def _clean_text(
    value: Any,
    *,
    field: str,
    max_chars: int = MAX_TEXT_CHARS,
    allow_empty: bool = True,
) -> str:
    if value is None:
        if allow_empty:
            return ""
        raise ValueError(f"{field} darf nicht leer sein")
    if not isinstance(value, str):
        raise ValueError(f"{field} muss Text sein")
    text = value.strip()
    if len(text) > max_chars:
        raise ValueError(f"{field} ist zu lang (maximal {max_chars} Zeichen)")
    if not allow_empty and not text:
        raise ValueError(f"{field} darf nicht leer sein")
    return text


MODEL_BLOCKED_MESSAGE = (
    "Modell ist fuer Subscription-Prompt-Agents nicht waehlbar "
    "(Cloud- und interne Modelle sind gesperrt)"
)

BLOCKED_MODEL_BACKENDS = frozenset({"ollama-cloud", "openrouter", "openai", "anthropic"})
BLOCKED_MODEL_SUFFIXES = (":cloud",)
BLOCKED_MODEL_MARKERS = ("cloud", "intern", "internal")


def _clean_model(value: Any) -> str:
    """Prueft die Modellwahl; interne und Cloud-Modelle bleiben gesperrt."""
    model = _clean_text(value, field="Modell", max_chars=MAX_MODEL_CHARS)
    if not model:
        return ""
    lowered = model.lower()
    backend = lowered.split(":", 1)[0].strip()
    if (
        lowered.endswith(BLOCKED_MODEL_SUFFIXES)
        or backend in BLOCKED_MODEL_BACKENDS
        or any(marker in lowered for marker in BLOCKED_MODEL_MARKERS)
    ):
        raise ValueError(MODEL_BLOCKED_MESSAGE)
    return model


def _clean_name(value: Any) -> str:
    text = _clean_text(value, field="Name", max_chars=MAX_NAME_CHARS, allow_empty=False)
    name = text.lower()
    if _ID.fullmatch(name) is None:
        raise ValueError(
            "Name muss mit Buchstabe oder Ziffer beginnen und darf nur Buchstaben, "
            "Ziffern, Punkt, Unterstrich und Bindestrich enthalten"
        )
    return name


def _clean_prompt_id(value: Any) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError("prompt_id muss Text sein")
    prompt_id = value.strip()
    if _PROMPT_ID.fullmatch(prompt_id) is None:
        raise ValueError("prompt_id enthaelt unerlaubte Zeichen")
    return prompt_id


def _clean_avatar(value: Any) -> str:
    """Delegiert an die zentrale Avatar-Pruefung der Chat-Slots."""
    if value is None:
        return ""
    from hub._services.chat.slots_config import validate_agent_avatar

    return validate_agent_avatar(value)


def _clean_skills(value: Any) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        if not value.strip():
            return "[]"
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError("Skills muessen eine JSON-Liste sein") from None
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise ValueError("Skills muessen eine JSON-Liste sein")
    if len(parsed) > MAX_SKILLS:
        raise ValueError(f"Zu viele Skills (maximal {MAX_SKILLS})")
    cleaned: list[str] = []
    for item in parsed:
        text = _clean_text(item, field="Skill", max_chars=MAX_SKILL_CHARS, allow_empty=False)
        if text not in cleaned:
            cleaned.append(text)
    return json.dumps(cleaned, ensure_ascii=False)


def _clean_status(value: Any) -> str:
    status = _clean_text(value, field="Status", max_chars=20, allow_empty=False).lower()
    if status not in _STATUSES:
        raise ValueError("Status muss idle, running, stopped oder expired sein")
    return status


def _to_agent(row: Iterable[Any], now: datetime | None = None) -> dict:
    data = dict(zip(_AGENT_COLUMNS, tuple(row)))
    raw_skills = data.get("skills_json") or "[]"
    try:
        skills = json.loads(raw_skills)
    except json.JSONDecodeError:
        skills = []
    data["skills"] = skills if isinstance(skills, list) else []
    data["expired"] = _is_expired(data, now)
    return data


def _is_expired(agent: dict, now: datetime | None = None) -> bool:
    if agent.get("status") == STATUS_EXPIRED:
        return True
    expires = _parse_ts(agent.get("expires_at"))
    if expires is None:
        return False
    return expires <= (now or _utc_now())


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
def ensure_subscription_agent_schema(conn: sqlite3.Connection) -> None:
    """Legt Agent- und Prompt-Tabelle samt Indizes an (idempotent)."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {AGENT_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            blueprint_id INTEGER,
            prompt_id TEXT DEFAULT '',
            skills_json TEXT DEFAULT '[]',
            model TEXT DEFAULT '',
            status TEXT DEFAULT 'idle',
            last_heartbeat_at TEXT,
            expires_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for col, col_type in [
        ("title", "TEXT DEFAULT ''"),
        ("description", "TEXT DEFAULT ''"),
        ("avatar", "TEXT DEFAULT ''"),
        ("blueprint_id", "INTEGER"),
        ("prompt_id", "TEXT DEFAULT ''"),
        ("skills_json", "TEXT DEFAULT '[]'"),
        ("model", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'idle'"),
        ("last_heartbeat_at", "TEXT"),
        ("expires_at", "TEXT"),
        ("created_at", "TEXT"),
        ("updated_at", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {AGENT_TABLE} ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{AGENT_TABLE}_name ON {AGENT_TABLE}(name)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{AGENT_TABLE}_status ON {AGENT_TABLE}(status)"
    )

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PROMPT_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id TEXT NOT NULL UNIQUE,
            agent_id INTEGER,
            prompt_text TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for col, col_type in [
        ("agent_id", "INTEGER"),
        ("prompt_text", "TEXT DEFAULT ''"),
        ("created_at", "TEXT"),
        ("updated_at", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {PROMPT_TABLE} ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{PROMPT_TABLE}_prompt "
        f"ON {PROMPT_TABLE}(prompt_id)"
    )
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{PROMPT_TABLE}_agent "
        f"ON {PROMPT_TABLE}(agent_id) WHERE agent_id IS NOT NULL"
    )
    conn.commit()


# --------------------------------------------------------------------------
# Blueprint-Vererbung
# --------------------------------------------------------------------------
_BLUEPRINT_CANDIDATES = (
    "id",
    "name",
    "title",
    "description",
    "avatar",
    "skills_json",
    "persona_prompt",
    "start_prompt",
)


def _load_blueprint(conn: sqlite3.Connection, blueprint_id: Any) -> dict | None:
    """Liest die referenzierte Blueprint-Vorlage, ohne harte Spaltenannahme."""
    if blueprint_id is None or blueprint_id == "":
        return None
    target = _as_int(blueprint_id, "blueprint_id")
    try:
        info = conn.execute("PRAGMA table_info(agent_blueprints)").fetchall()
    except sqlite3.OperationalError:
        raise ValueError("Blueprints sind derzeit nicht verfuegbar") from None
    columns = [row[1] for row in info]
    if not columns:
        raise ValueError("Die referenzierte Vorlage wurde nicht gefunden")
    wanted = [name for name in _BLUEPRINT_CANDIDATES if name in columns]
    if "id" not in wanted:
        raise ValueError("Die referenzierte Vorlage wurde nicht gefunden")
    row = conn.execute(
        f"SELECT {', '.join(wanted)} FROM agent_blueprints WHERE id = ?",
        (target,),
    ).fetchone()
    if row is None:
        raise ValueError("Die referenzierte Vorlage wurde nicht gefunden")
    return dict(zip(wanted, tuple(row)))


def _apply_blueprint_defaults(payload: dict, blueprint: dict | None) -> None:
    """Fuellt leere Felder aus der Vorlage (Blueprint-Vererbung)."""
    if not blueprint:
        return
    if not str(payload.get("title") or "").strip():
        payload["title"] = blueprint.get("title") or blueprint.get("name") or ""
    if not str(payload.get("description") or "").strip():
        payload["description"] = blueprint.get("description") or ""
    if not str(payload.get("avatar") or "").strip():
        payload["avatar"] = blueprint.get("avatar") or ""
    skills = payload.get("skills")
    empty_skills = skills in (None, "", [], {})
    if empty_skills:
        raw = blueprint.get("skills_json")
        if isinstance(raw, str) and raw.strip() and raw.strip() != "[]":
            payload["skills"] = raw
    if not str(payload.get("prompt_text") or "").strip():
        payload["prompt_text"] = (
            blueprint.get("persona_prompt") or blueprint.get("start_prompt") or ""
        )


# --------------------------------------------------------------------------
# Prompt-Teil (gekoppelt an den Agenten)
# --------------------------------------------------------------------------
_PROMPT_COLUMNS = ("id", "prompt_id", "agent_id", "prompt_text", "created_at", "updated_at")
_PROMPT_SELECT = ", ".join(_PROMPT_COLUMNS)


def _to_prompt(row: Iterable[Any]) -> dict:
    return dict(zip(_PROMPT_COLUMNS, tuple(row)))


def _find_prompt(conn: sqlite3.Connection, *, prompt_id: str = "", agent_id: int | None = None):
    if agent_id is not None:
        return _to_prompt_or_none(
            conn.execute(
                f"SELECT {_PROMPT_SELECT} FROM {PROMPT_TABLE} WHERE agent_id = ?",
                (int(agent_id),),
            ).fetchone()
        )
    if not prompt_id:
        return None
    return _to_prompt_or_none(
        conn.execute(
            f"SELECT {_PROMPT_SELECT} FROM {PROMPT_TABLE} WHERE prompt_id = ?",
            (prompt_id,),
        ).fetchone()
    )


def _to_prompt_or_none(row) -> dict | None:
    if row is None:
        return None
    return _to_prompt(row)


def list_subscription_prompts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_PROMPT_SELECT} FROM {PROMPT_TABLE} ORDER BY id"
    ).fetchall()
    return [_to_prompt(row) for row in rows]


def get_subscription_prompt(conn: sqlite3.Connection, prompt_id: Any) -> dict | None:
    pid = _clean_prompt_id(prompt_id)
    if not pid:
        raise ValueError("prompt_id darf nicht leer sein")
    return _find_prompt(conn, prompt_id=pid)


def create_subscription_prompt(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Legt einen freien Prompt an und koppelt ihn optional an einen Agenten."""
    if not isinstance(payload, dict):
        raise ValueError("payload muss ein JSON-Objekt sein")
    moment = now or _utc_now()
    stamp = _iso(moment)
    prompt_text = _clean_text(
        payload.get("prompt_text"), field="Prompt", max_chars=MAX_PROMPT_CHARS
    )
    prompt_id = _clean_prompt_id(payload.get("prompt_id")) or uuid.uuid4().hex
    agent_id = None
    if payload.get("agent_id") not in (None, ""):
        agent_id = _as_int(payload.get("agent_id"), "agent_id")
        if get_subscription_agent(conn, agent_id) is None:
            raise ValueError("Der angegebene Agent wurde nicht gefunden")
        if _find_prompt(conn, agent_id=agent_id) is not None:
            raise ValueError("Der Agent besitzt bereits einen Prompt")
    conn.execute(
        f"INSERT INTO {PROMPT_TABLE} (prompt_id, agent_id, prompt_text, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (prompt_id, agent_id, prompt_text, stamp, stamp),
    )
    if agent_id is not None:
        conn.execute(
            f"UPDATE {AGENT_TABLE} SET prompt_id = ?, updated_at = ? WHERE id = ?",
            (prompt_id, stamp, agent_id),
        )
    conn.commit()
    created = _find_prompt(conn, prompt_id=prompt_id)
    return created or {}


def update_subscription_prompt(
    conn: sqlite3.Connection,
    prompt_id: Any,
    payload: dict,
    *,
    now: datetime | None = None,
) -> dict:
    pid = _clean_prompt_id(prompt_id)
    current = _find_prompt(conn, prompt_id=pid)
    if current is None:
        raise ValueError("Prompt wurde nicht gefunden")
    if not isinstance(payload, dict):
        raise ValueError("payload muss ein JSON-Objekt sein")
    prompt_text = _clean_text(
        payload.get("prompt_text"), field="Prompt", max_chars=MAX_PROMPT_CHARS
    )
    stamp = _iso(now or _utc_now())
    conn.execute(
        f"UPDATE {PROMPT_TABLE} SET prompt_text = ?, updated_at = ? WHERE prompt_id = ?",
        (prompt_text, stamp, pid),
    )
    if current.get("agent_id"):
        conn.execute(
            f"UPDATE {AGENT_TABLE} SET updated_at = ? WHERE id = ?",
            (stamp, int(current["agent_id"])),
        )
    conn.commit()
    return _find_prompt(conn, prompt_id=pid) or {}


def delete_subscription_prompt(conn: sqlite3.Connection, prompt_id: Any) -> bool:
    """Loescht den Prompt und den gekoppelten Agenten in EINER Transaktion."""
    pid = _clean_prompt_id(prompt_id)
    if not pid:
        raise ValueError("prompt_id darf nicht leer sein")
    row = conn.execute(
        f"SELECT agent_id FROM {PROMPT_TABLE} WHERE prompt_id = ?", (pid,)
    ).fetchone()
    if row is None:
        return False
    agent_id = row[0]
    conn.execute(f"DELETE FROM {PROMPT_TABLE} WHERE prompt_id = ?", (pid,))
    if agent_id:
        conn.execute(f"DELETE FROM {AGENT_TABLE} WHERE id = ?", (int(agent_id),))
    conn.commit()
    return True


# --------------------------------------------------------------------------
# Agent-Teil
# --------------------------------------------------------------------------
def list_subscription_agents(
    conn: sqlite3.Connection,
    *,
    include_expired: bool = False,
    reap: bool = True,
    now: datetime | None = None,
) -> list[dict]:
    """Listet Agenten; abgelaufene Heartbeats werden als beendet markiert."""
    moment = now or _utc_now()
    rows = conn.execute(
        f"SELECT {_AGENT_SELECT} FROM {AGENT_TABLE} ORDER BY name"
    ).fetchall()
    agents = [_to_agent(row, moment) for row in rows]

    expired_ids = [
        int(agent["id"])
        for agent in agents
        if agent["expired"] and agent.get("status") != STATUS_EXPIRED
    ]
    if expired_ids and reap:
        placeholders = ", ".join("?" for _ in expired_ids)
        conn.execute(
            f"UPDATE {AGENT_TABLE} SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
            (STATUS_EXPIRED, _iso(moment), *expired_ids),
        )
        conn.commit()
        for agent in agents:
            if int(agent["id"]) in expired_ids:
                agent["status"] = STATUS_EXPIRED
    if include_expired:
        return agents
    return [agent for agent in agents if not agent["expired"]]


def get_subscription_agent(conn: sqlite3.Connection, agent_id: Any) -> dict | None:
    try:
        target = _as_int(agent_id, "id")
    except ValueError:
        return None
    row = conn.execute(
        f"SELECT {_AGENT_SELECT} FROM {AGENT_TABLE} WHERE id = ?", (target,)
    ).fetchone()
    if row is None:
        return None
    agent = _to_agent(row)
    prompt = _find_prompt(conn, agent_id=target)
    if prompt is None and agent.get("prompt_id"):
        prompt = _find_prompt(conn, prompt_id=str(agent["prompt_id"]))
    agent["prompt_text"] = prompt["prompt_text"] if prompt else ""
    return agent


def _unique_name(conn: sqlite3.Connection, base: str) -> str:
    taken = {row[0] for row in conn.execute(f"SELECT name FROM {AGENT_TABLE}")}
    if base not in taken:
        return base
    for index in range(2, 1000):
        suffix = f"-{index}"
        candidate = base[: MAX_NAME_CHARS - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
    raise ValueError("Es konnte kein freier Name erzeugt werden")


def create_subscription_agent(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Legt Agent und Prompt gemeinsam an (Blueprint-Vererbung inklusive)."""
    if not isinstance(payload, dict):
        raise ValueError("payload muss ein JSON-Objekt sein")
    merged = dict(payload)
    blueprint = _load_blueprint(conn, merged.get("blueprint_id"))
    _apply_blueprint_defaults(merged, blueprint)

    name = _clean_name(merged.get("name"))
    title = _clean_text(merged.get("title"), field="Titel", max_chars=MAX_TITLE_CHARS)
    description = _clean_text(merged.get("description"), field="Beschreibung")
    avatar = _clean_avatar(merged.get("avatar"))
    skills_json = _clean_skills(merged.get("skills"))
    model = _clean_model(merged.get("model"))
    prompt_text = _clean_text(
        merged.get("prompt_text"), field="Prompt", max_chars=MAX_PROMPT_CHARS
    )
    prompt_id = _clean_prompt_id(merged.get("prompt_id")) or uuid.uuid4().hex
    blueprint_id = blueprint["id"] if blueprint else None
    stamp = _iso(now or _utc_now())

    if conn.execute(
        f"SELECT id FROM {AGENT_TABLE} WHERE name = ?", (name,)
    ).fetchone() is not None:
        raise ValueError("Dieser Name ist bereits vergeben")

    try:
        cursor = conn.execute(
            f"INSERT INTO {AGENT_TABLE} "
            "(name, title, description, avatar, blueprint_id, prompt_id, skills_json, "
            " model, status, last_heartbeat_at, expires_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
            (
                name,
                title,
                description,
                avatar,
                blueprint_id,
                prompt_id,
                skills_json,
                model,
                STATUS_IDLE,
                stamp,
                stamp,
            ),
        )
    except sqlite3.IntegrityError:
        raise ValueError("Dieser Name ist bereits vergeben") from None
    agent_id = int(cursor.lastrowid)
    conn.execute(
        f"INSERT INTO {PROMPT_TABLE} (prompt_id, agent_id, prompt_text, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (prompt_id, agent_id, prompt_text, stamp, stamp),
    )
    conn.commit()
    created = get_subscription_agent(conn, agent_id)
    if created is None:  # pragma: no cover - defensive
        raise RuntimeError("Agent konnte nicht gelesen werden")
    return created


def update_subscription_agent(
    conn: sqlite3.Connection,
    agent_id: Any,
    payload: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Aktualisiert Agent und (falls mitgeschickt) den gekoppelten Prompt."""
    target = _as_int(agent_id, "id")
    current = get_subscription_agent(conn, target)
    if current is None:
        raise ValueError("Agent wurde nicht gefunden")
    if not isinstance(payload, dict):
        raise ValueError("payload muss ein JSON-Objekt sein")

    assignments: list[str] = []
    values: list[Any] = []
    if "name" in payload:
        name = _clean_name(payload.get("name"))
        if name != current["name"] and conn.execute(
            f"SELECT id FROM {AGENT_TABLE} WHERE name = ? AND id <> ?", (name, target)
        ).fetchone() is not None:
            raise ValueError("Dieser Name ist bereits vergeben")
        assignments.append("name = ?")
        values.append(name)
    if "title" in payload:
        assignments.append("title = ?")
        values.append(
            _clean_text(payload.get("title"), field="Titel", max_chars=MAX_TITLE_CHARS)
        )
    if "description" in payload:
        assignments.append("description = ?")
        values.append(_clean_text(payload.get("description"), field="Beschreibung"))
    if "avatar" in payload:
        assignments.append("avatar = ?")
        values.append(_clean_avatar(payload.get("avatar")))
    if "skills" in payload or "skills_json" in payload:
        assignments.append("skills_json = ?")
        values.append(_clean_skills(payload.get("skills", payload.get("skills_json"))))
    if "model" in payload:
        assignments.append("model = ?")
        values.append(_clean_model(payload.get("model")))
    if "status" in payload:
        assignments.append("status = ?")
        values.append(_clean_status(payload.get("status")))
    if "blueprint_id" in payload:
        blueprint = _load_blueprint(conn, payload.get("blueprint_id"))
        assignments.append("blueprint_id = ?")
        values.append(blueprint["id"] if blueprint else None)

    stamp = _iso(now or _utc_now())
    if assignments:
        assignments.append("updated_at = ?")
        values.append(stamp)
        values.append(target)
        conn.execute(
            f"UPDATE {AGENT_TABLE} SET {', '.join(assignments)} WHERE id = ?",
            tuple(values),
        )

    if "prompt_text" in payload:
        prompt_text = _clean_text(
            payload.get("prompt_text"), field="Prompt", max_chars=MAX_PROMPT_CHARS
        )
        prompt = _find_prompt(conn, agent_id=target)
        if prompt is None:
            prompt_id = _clean_prompt_id(current.get("prompt_id")) or uuid.uuid4().hex
            conn.execute(
                f"INSERT INTO {PROMPT_TABLE} "
                "(prompt_id, agent_id, prompt_text, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (prompt_id, target, prompt_text, stamp, stamp),
            )
            conn.execute(
                f"UPDATE {AGENT_TABLE} SET prompt_id = ?, updated_at = ? WHERE id = ?",
                (prompt_id, stamp, target),
            )
        else:
            conn.execute(
                f"UPDATE {PROMPT_TABLE} SET prompt_text = ?, updated_at = ? WHERE agent_id = ?",
                (prompt_text, stamp, target),
            )

    conn.commit()
    updated = get_subscription_agent(conn, target)
    if updated is None:  # pragma: no cover - defensiv
        raise ValueError("Agent wurde nicht gefunden")
    return updated


def delete_subscription_agent(conn: sqlite3.Connection, agent_id: Any) -> bool:
    """Loescht Agent und gekoppelten Prompt in EINER Transaktion."""
    target = _as_int(agent_id, "id")
    row = conn.execute(
        f"SELECT prompt_id FROM {AGENT_TABLE} WHERE id = ?", (target,)
    ).fetchone()
    if row is None:
        return False
    prompt_id = row[0]
    conn.execute(f"DELETE FROM {PROMPT_TABLE} WHERE agent_id = ?", (target,))
    if prompt_id:
        conn.execute(f"DELETE FROM {PROMPT_TABLE} WHERE prompt_id = ?", (prompt_id,))
    conn.execute(f"DELETE FROM {AGENT_TABLE} WHERE id = ?", (target,))
    conn.commit()
    return True


def duplicate_subscription_agent(
    conn: sqlite3.Connection,
    agent_id: Any,
    *,
    name: Any = None,
    now: datetime | None = None,
) -> dict:
    """Kopiert Agent samt Prompt unter neuem Namen."""
    source = get_subscription_agent(conn, agent_id)
    if source is None:
        raise ValueError("Agent wurde nicht gefunden")
    if name not in (None, ""):
        new_name = _clean_name(name)
    else:
        new_name = _unique_name(conn, f"{source['name']}-copy")
    payload = {
        "name": new_name,
        "title": source.get("title") or source["name"],
        "description": source.get("description") or "",
        "avatar": source.get("avatar") or "",
        "blueprint_id": source.get("blueprint_id"),
        "skills": source.get("skills") or [],
        "model": source.get("model") or "",
        "prompt_text": source.get("prompt_text") or "",
    }
    return create_subscription_agent(conn, payload, now=now)


def record_subscription_agent_heartbeat(
    conn: sqlite3.Connection,
    agent_id: Any,
    *,
    ttl_seconds: Any = DEFAULT_HEARTBEAT_TTL_SECONDS,
    now: datetime | None = None,
) -> dict:
    """Setzt den Auto-Logout-Zeitpunkt neu und markiert den Agenten als laufend."""
    target = _as_int(agent_id, "id")
    ttl = _as_ttl(ttl_seconds)
    if conn.execute(
        f"SELECT id FROM {AGENT_TABLE} WHERE id = ?", (target,)
    ).fetchone() is None:
        raise ValueError("Agent wurde nicht gefunden")
    moment = now or _utc_now()
    stamp = _iso(moment)
    expires = _iso(moment + timedelta(seconds=ttl))
    conn.execute(
        f"UPDATE {AGENT_TABLE} SET status = ?, last_heartbeat_at = ?, expires_at = ?, "
        "updated_at = ? WHERE id = ?",
        (STATUS_RUNNING, stamp, expires, stamp, target),
    )
    conn.commit()
    updated = get_subscription_agent(conn, target)
    if updated is None:  # pragma: no cover - defensiv
        raise ValueError("Agent wurde nicht gefunden")
    return updated


def stop_subscription_agent(
    conn: sqlite3.Connection,
    agent_id: Any,
    *,
    now: datetime | None = None,
) -> dict:
    """Beendet den Agenten und loescht den Auto-Logout-Zeitpunkt."""
    target = _as_int(agent_id, "id")
    if conn.execute(
        f"SELECT id FROM {AGENT_TABLE} WHERE id = ?", (target,)
    ).fetchone() is None:
        raise ValueError("Agent wurde nicht gefunden")
    stamp = _iso(now or _utc_now())
    conn.execute(
        f"UPDATE {AGENT_TABLE} SET status = ?, expires_at = NULL, updated_at = ? WHERE id = ?",
        (STATUS_STOPPED, stamp, target),
    )
    conn.commit()
    updated = get_subscription_agent(conn, target)
    if updated is None:  # pragma: no cover - defensiv
        raise ValueError("Agent wurde nicht gefunden")
    return updated
