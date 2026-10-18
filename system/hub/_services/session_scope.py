# SPDX-License-Identifier: MIT
"""BACH-local session addressing; no second store or module-owned state."""
from uuid import uuid4


def parse_scope(args):
    """Parse scope before ``--``; preserve summary tokens after it literally."""
    values = {}
    text = []
    index = 0
    while index < len(args):
        arg = str(args[index])
        if arg == "--":
            text.extend(str(value) for value in args[index + 1:])
            break
        key = arg.split("=", 1)[0]
        if key in ("--session", "--session-id", "--partner", "--partner-id"):
            name = "session_id" if key.startswith("--session") else "partner_id"
            if "=" in arg:
                value = arg.split("=", 1)[1]
            else:
                index += 1
                value = str(args[index]) if index < len(args) else ""
            if not value.strip() or value.startswith("--") or name in values:
                raise ValueError(f"Invalid or duplicate {key}")
            values[name] = value.lower() if name == "partner_id" else value
        else:
            text.append(arg)
        index += 1
    if values.get("session_id") and not values.get("partner_id"):
        raise ValueError("--session requires --partner for ownership validation")
    return " ".join(text) or None, values


def select_session(conn, *, session_id=None, partner_id=None):
    """Return one open session, or reject ambiguity/invalid explicit identity."""
    where = ["ended_at IS NULL"]
    params = []
    if session_id is not None:
        if not partner_id:
            raise ValueError("session_id requires partner_id")
        where.append("session_id = ?")
        params.append(session_id)
    if partner_id is not None:
        where.append("LOWER(partner_id) = ?")
        params.append(partner_id.lower())
    rows = conn.execute(
        "SELECT id, session_id, started_at, tasks_created, partner_id "
        "FROM memory_sessions WHERE " + " AND ".join(where) + " LIMIT 2", params
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("Ambiguous open sessions; specify --session and --partner")
    if session_id is not None and not rows:
        raise ValueError("Session is missing, closed, or belongs to another partner")
    return rows[0] if rows else None


def new_session_id(now):
    return f"session_{now.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:12]}"
