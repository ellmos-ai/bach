#!/usr/bin/env python3
"""BACH's tool surface for the chat runtime -- the injected ``ToolProvider``.

Since wave 2 of the BACH-GUI module cut (decision D-20260830-002) the chat
runtime itself comes from the neutral module ``ellmos-chat``; the tools stay
here, because they are BACH: ``bach_command`` reaches the 110+ CHIAH handlers
through ``bach_app.execute``, and ``maintain``/``foerderbericht``/``weather``
lazily import ``hub._services.*``. The module never sees any of that -- it asks
``BachToolProvider`` for definitions and calls ``execute``.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import io
import json
import logging
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from ellmos_chat import Mode, as_mode
except ImportError:
    from enum import Enum

    class Mode(str, Enum):
        SAFE = "safe"
        FULL = "full"

    def as_mode(v):
        return Mode(str(getattr(v, "value", v)).strip().lower())

from hub import safe_exec
from hub._services.chat.worker_lease_binding import WorkerResultLimitLockedError
from hub._services.chat.worker_tool_errors import ToolErrorText
from hub._services.chat.worker_lease_binding import (
    WorkerLeaseBinding,
    WorkerResultLimitLockedError,
    WorkerTaskManageArgumentError,
)
from hub._services.task_lease_client import (
    LeaseConnectionError, LeaseDeniedError, LeaseProtocolError,
    LeaseSelfCheckRequiredError,
    TaskResultOperationError, _SAFE_DENIAL_REASONS,
)
from hub._services.limits import limit
from hub._services.read_file_formatter import (
    MAX_READ_FILE_LINES,
    MAX_READ_FILE_OFFSET,
    MAX_READ_FILE_OUTPUT_CHARS,
    format_read_file_output,
)

log = logging.getLogger("bach.chat")

_TASK_MANAGE_LOG_ACTIONS = frozenset({
    "add", "decompose", "detail", "done", "list", "submit_result", "update",
})
_COMPLETE_FLAG_HINT = (
    "complete fehlt: complete=true nur, wenn die Pflichtarbeit vollständig erledigt ist; "
    "sonst complete=false mit dem bisherigen Teilstand als result (die Task geht offen zurück)."
)


_PARTIAL_STATE_MARK = "\n\nTeilstand (Worker, "
_PARTIAL_STATE_SEAL_RE = re.compile(
    r"\n<!-- bach-worker-partial:v1 start=(\d{1,10}) chars=(\d{1,10}) sha256=([0-9a-f]{64}) -->"
)


def _return_partial_state(binding, args):
    """Replace only an intact, bounded partial state; preserve surrounding task text."""
    task_id = args["task_id"]
    description = binding.task_snapshot().get("description") or ""
    # The old free-form format has no known end. Preserve legacy/edited blocks
    # once rather than discard later decomposition receipts or operator notes.
    # The final seal belongs to the outer block, even if result quotes a seal.
    seals = list(_PARTIAL_STATE_SEAL_RE.finditer(description))
    if seals:
        seal = seals[-1]
        start = seal.start() - int(seal.group(2))
        previous = description[max(0, start):seal.start()]
        if (start == int(seal.group(1)) and previous.startswith(_PARTIAL_STATE_MARK)
                and hashlib.sha256(previous.encode("utf-8")).hexdigest() == seal.group(3)):
            description = description[:start] + description[seal.end():]
    block = (f"{_PARTIAL_STATE_MARK}{datetime.now().strftime('%Y-%m-%d %H:%M')}, complete=false):\n"
             f"{str(args.get('result') or '').strip()}")
    seal = (f"\n<!-- bach-worker-partial:v1 start={len(description)} chars={len(block)} "
            f"sha256={hashlib.sha256(block.encode('utf-8')).hexdigest()} -->")
    binding.execute_task_manage({"action": "update", "task_id": task_id,
                                 "description": description + block + seal}, _dispatch_marked=True)
    binding.execute_task_manage({"action": "update", "task_id": task_id, "status": "pending"},
                                _dispatch_marked=True)
    return f"Task #{task_id}: Teilstand gespeichert und offen zurückgegeben (pending); kein Abschluss."


# Fixed texts from validate_submission that a model needs to correct its result.
_PUBLIC_RESULT_ERRORS = ("Konkretes Ergebnis mit höchstens ",
                         "Eine Erledigungsbestätigung ist kein fachliches Ergebnis")


def _invalid_result_text(exc):
    """Neutral typed text (#379); only a known public check reason is added."""
    reason = str(exc)
    if reason.startswith(_PUBLIC_RESULT_ERRORS):
        return ToolErrorText(f"Taskergebnis ist ungültig: {reason}.", code="invalid_task_result")
    return ToolErrorText("Taskergebnis ist ungültig.", code="invalid_task_result")


def _log_bound_task_manage_denial(stage, binding, args, exc=None):
    """Finite operator diagnosis; never log tool arguments, result or ACK text."""
    action = args.get("action", "list") if type(args) is dict else None
    action = action if type(action) is str and action in _TASK_MANAGE_LOG_ACTIONS else "other"
    task_id = getattr(binding, "task_id", None)
    task_id = task_id if type(task_id) is int and task_id > 0 else 0
    generation = getattr(binding, "generation", None)
    generation = generation if type(generation) is str and re.fullmatch(r"[0-9a-f]{32}", generation) else "unknown"
    if isinstance(exc, WorkerResultLimitLockedError):
        kind = "result_limit"
    elif isinstance(exc, WorkerTaskManageArgumentError):
        kind = "argument_shape"
    elif isinstance(exc, LeaseSelfCheckRequiredError):
        kind = "self_check_required"
    elif isinstance(exc, LeaseDeniedError):
        kind = "lease_denied"
    elif isinstance(exc, LeaseProtocolError):
        kind = "lease_protocol"
    elif isinstance(exc, LeaseConnectionError):
        kind = "lease_connection"
    elif isinstance(exc, TaskResultOperationError):
        kind = "result_operation"
    elif isinstance(exc, ValueError):
        kind = "value_error"
    else:
        kind = "other"
    reason = (exc.reason if isinstance(exc, LeaseDeniedError)
              and type(exc.reason) is str and exc.reason in _SAFE_DENIAL_REASONS
              else "none")
    log.warning("bound_task_manage_denied stage=%s action=%s kind=%s reason=%s task_id=%d generation=%s",
                stage, action, kind, reason, task_id, generation)

_READ_EVIDENCE_SCHEMA = "ellmos.read-evidence.v1"
_READ_EVIDENCE_READ_ONLY_TOOLS = frozenset({"read_file", "search_text", "task_manage"})
_READ_EVIDENCE_REASONS = frozenset({
    "formatter_capability_unverified",
    "reviewer_profile_required",
    "versioned_format_required",
    "unsupported_output_format",
})


def _read_evidence_readonly_worker_enabled(worker_task_binding, allowed_tools) -> bool:
    """Require an active fenced binding and the exact current read-only tool profile."""
    if not isinstance(worker_task_binding, WorkerLeaseBinding):
        return False
    if not isinstance(allowed_tools, (set, frozenset, tuple, list)):
        return False
    if len(allowed_tools) != len(_READ_EVIDENCE_READ_ONLY_TOOLS):
        return False
    try:
        if any(type(tool) is not str for tool in allowed_tools):
            return False
        if frozenset(allowed_tools) != _READ_EVIDENCE_READ_ONLY_TOOLS:
            return False
        # The runtime supplies allowed_tools only after its live worker-profile
        # reader has refreshed the session. The lease check binds this tool
        # schema to the active fenced task dispatch; routing metadata is not a
        # provider or model capability signal.
        worker_task_binding.assert_active()
        return True
    except Exception:  # noqa: BLE001 - Invalid runtime authority fails closed.
        return False

def _read_evidence_formatter():
    """Return only the installed formatter with the exact bounded v1 API."""
    try:
        module = importlib.import_module("ellmos_chat.read_evidence")
        formatter = getattr(module, "format_read_evidence", None)
        if (getattr(module, "READ_EVIDENCE_SCHEMA", None) != _READ_EVIDENCE_SCHEMA
                or type(getattr(module, "MAX_LINES", None)) is not int
                or module.MAX_LINES != MAX_READ_FILE_LINES
                or type(getattr(module, "MAX_CHARS", None)) is not int
                or module.MAX_CHARS != MAX_READ_FILE_OUTPUT_CHARS
                or not callable(formatter)):
            return None
        parameters = inspect.signature(formatter).parameters
        required = {
            "text", "start_line", "source_eof", "start_char_offset",
            "max_lines", "max_chars", "source_complete", "source_sha256",
        }
        if any(
            name not in parameters
            or parameters[name].kind not in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            for name in required
        ):
            return None
        return formatter
    except Exception:  # noqa: BLE001 - Missing or incompatible formatter stays unavailable.
        return None


def _read_evidence_unavailable(reason_code: str) -> str:
    if reason_code not in _READ_EVIDENCE_REASONS:
        reason_code = "formatter_capability_unverified"
    return json.dumps({
        "schema": "bach.read-evidence-capability.v1",
        "requested_schema": _READ_EVIDENCE_SCHEMA,
        "available": False,
        "reason_code": reason_code,
    }, ensure_ascii=False, separators=(",", ":"))


def _versioned_read_file_tool(tool: dict, *, formatter_available: bool) -> dict:
    """Build an isolated v1 schema for the exact fenced read-only worker profile."""
    versioned = copy.deepcopy(tool)
    description = (
        "Datei im bereits freigegebenen Leseumfang als ellmos.read-evidence.v1 lesen. "
        "output_format ist erforderlich; start_line und start_char_offset sind der "
        "Cursor aus der letzten Antwort. Das Format erteilt keine zusätzliche Pfadfreigabe."
    )
    if not formatter_available:
        description += " Der installierte v1-Formatter ist nicht bestätigt; Aufrufe melden unavailable."
    versioned["function"]["description"] = description
    versioned["function"]["parameters"] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Dateipfad im bestehenden freigegebenen Leseumfang"},
            "output_format": {
                "type": "string",
                "enum": [_READ_EVIDENCE_SCHEMA],
                "description": "Erforderliches versioniertes Belegformat.",
            },
            "start_line": {
                "type": "integer", "minimum": 1, "maximum": MAX_READ_FILE_OFFSET,
                "description": "1-basierte physische Startzeile; Standard 1.",
            },
            "start_char_offset": {
                "type": "integer", "minimum": 0, "maximum": MAX_READ_FILE_OFFSET,
                "description": "Unicode-Zeichenoffset innerhalb der ersten Zeile; Standard 0.",
            },
            "max_lines": {
                "type": "integer", "minimum": 1, "maximum": MAX_READ_FILE_LINES,
                "description": "Höchstens so viele physische Zeilen; Standard 200.",
            },
            "max_chars": {
                "type": "integer", "minimum": 1, "maximum": MAX_READ_FILE_OUTPUT_CHARS,
                "description": "Höchstens so viele Zeileninhaltszeichen; Standard 4000.",
            },
        },
        "required": ["path", "output_format"],
        "additionalProperties": False,
    }
    return versioned


def _read_evidence_request(args: dict):
    allowed = {
        "path", "output_format", "start_line", "start_char_offset", "max_lines", "max_chars",
    }
    if set(args) - allowed:
        return None
    path = args.get("path")
    if type(path) is not str or not path:
        return None
    if args.get("output_format") != _READ_EVIDENCE_SCHEMA:
        return None
    start_line = args.get("start_line", 1)
    char_offset = args.get("start_char_offset", 0)
    max_lines = args.get("max_lines", MAX_READ_FILE_LINES)
    max_chars = args.get("max_chars", MAX_READ_FILE_OUTPUT_CHARS)
    if (type(start_line) is not int or not 1 <= start_line <= MAX_READ_FILE_OFFSET
            or type(char_offset) is not int or not 0 <= char_offset <= MAX_READ_FILE_OFFSET
            or type(max_lines) is not int or not 1 <= max_lines <= MAX_READ_FILE_LINES
            or type(max_chars) is not int or not 1 <= max_chars <= MAX_READ_FILE_OUTPUT_CHARS):
        return None
    return path, start_line, char_offset, max_lines, max_chars


class _ReadEvidenceCursorError(Exception):
    """A requested character cursor is beyond the contents of its physical line."""


def _read_evidence_skip_lines(stream, start_line: int) -> bool:
    for _ in range(start_line - 1):
        while True:
            part = stream.readline(8192)
            if not part:
                return False
            if part.endswith("\n"):
                break
    return True


def _read_evidence_cursor_prefix(stream, char_offset: int) -> tuple[str, bool]:
    """Skip a bounded cursor on one normalized line, returning at most one lookahead char."""
    remaining = char_offset
    while remaining:
        size = min(8192, remaining + 1)
        part = stream.readline(size)
        if not part:
            raise _ReadEvidenceCursorError
        terminated = part.endswith("\n")
        content_length = len(part) - (1 if terminated else 0)
        if terminated:
            if content_length < remaining:
                raise _ReadEvidenceCursorError
            return part[remaining:], False
        if content_length > remaining:
            return part[remaining:], False
        if content_length < remaining:
            if len(part) < size:
                raise _ReadEvidenceCursorError
            remaining -= content_length
            continue
        if len(part) < size:
            return "", True
        lookahead = stream.read(1)
        if not lookahead:
            return "", True
        return lookahead, False
    return "", False


def _read_evidence_source_chunk(stream, *, start_line: int, char_offset: int,
                                max_lines: int, max_chars: int) -> tuple[str, bool]:
    if not _read_evidence_skip_lines(stream, start_line):
        return "", True
    prefix, eof_at_cursor = _read_evidence_cursor_prefix(stream, char_offset)
    if eof_at_cursor:
        return "", True
    read_limit = max_chars + 2 * max_lines
    remaining = read_limit + 1 - len(prefix)
    tail = stream.read(remaining)
    source = prefix + tail
    if len(source) > read_limit:
        return source[:read_limit], False
    return source, True


def _read_evidence_payload_valid(payload, rendered: str, *, start_line: int, char_offset: int,
                                 max_lines: int, max_chars: int) -> bool:
    """Accept only the bounded, canonical v1 payload for the requested cursor."""
    keys = {
        "schema", "start_line", "end_line", "lines", "eof", "truncated",
        "truncation_reason", "next_cursor", "source_complete", "source_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != keys:
        return False
    if payload.get("schema") != _READ_EVIDENCE_SCHEMA:
        return False
    if (type(payload.get("eof")) is not bool or type(payload.get("truncated")) is not bool
            or payload["eof"] == payload["truncated"]):
        return False
    if payload.get("source_complete") is not False or payload.get("source_sha256") is not None:
        return False
    lines = payload.get("lines")
    if not isinstance(lines, list) or len(lines) > max_lines:
        return False
    if sum(len(row.get("text", "")) for row in lines if isinstance(row, dict)
           and type(row.get("text")) is str) > max_chars:
        return False
    row_keys = {"line", "char_offset", "text", "line_complete"}
    for index, row in enumerate(lines):
        if not isinstance(row, dict) or set(row) != row_keys:
            return False
        expected_line = start_line + index
        expected_offset = char_offset if index == 0 else 0
        if (type(row.get("line")) is not int or row["line"] != expected_line
                or type(row.get("char_offset")) is not int or row["char_offset"] != expected_offset
                or type(row.get("text")) is not str or type(row.get("line_complete")) is not bool):
            return False
    if lines:
        if (type(payload.get("start_line")) is not int or payload["start_line"] != lines[0]["line"]
                or type(payload.get("end_line")) is not int or payload["end_line"] != lines[-1]["line"]):
            return False
    elif payload.get("start_line") is not None or payload.get("end_line") is not None:
        return False
    cursor = payload.get("next_cursor")
    if payload["truncated"]:
        if payload.get("truncation_reason") not in {"max_lines", "max_chars", "source_chunk"}:
            return False
        if (not isinstance(cursor, dict) or set(cursor) != {"line", "char_offset"}
                or type(cursor.get("line")) is not int or cursor["line"] < 1
                or type(cursor.get("char_offset")) is not int or cursor["char_offset"] < 0):
            return False
        if lines:
            last = lines[-1]
            last_offset = last["char_offset"] + len(last["text"])
            if cursor["line"] == last["line"]:
                if cursor["char_offset"] < last_offset:
                    return False
            elif cursor["line"] != last["line"] + 1 or cursor["char_offset"] != 0:
                return False
        elif cursor["line"] < start_line or (cursor["line"] == start_line and cursor["char_offset"] < char_offset):
            return False
    elif payload.get("truncation_reason") is not None or cursor is not None:
        return False
    try:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return False
    return canonical == rendered


def _format_read_evidence_within_budget(formatter, text: str, *, start_line: int,
                                        char_offset: int, source_eof: bool,
                                        max_lines: int, max_chars: int) -> str | None:
    line_limit = max_lines
    char_limit = max_chars
    for _ in range(24):
        try:
            rendered = formatter(
                text,
                start_line=start_line,
                source_eof=source_eof,
                start_char_offset=char_offset,
                max_lines=line_limit,
                max_chars=char_limit,
                source_complete=False,
                source_sha256=None,
            )
        except Exception:  # noqa: BLE001 - Formatter failures are redacted and unavailable.
            return None
        if type(rendered) is not str:
            return None
        try:
            payload = json.loads(rendered)
        except (TypeError, ValueError):
            return None
        if not _read_evidence_payload_valid(
            payload, rendered, start_line=start_line, char_offset=char_offset,
            max_lines=line_limit, max_chars=char_limit,
        ):
            return None
        if len(rendered) <= MAX_READ_FILE_OUTPUT_CHARS:
            return rendered
        factor = max(0.1, min(0.75, (MAX_READ_FILE_OUTPUT_CHARS / len(rendered)) * 0.75))
        new_lines = max(1, int(line_limit * factor))
        new_chars = max(1, int(char_limit * factor))
        if new_lines == line_limit and new_chars == char_limit:
            if char_limit > 1:
                new_chars -= 1
            elif line_limit > 1:
                new_lines -= 1
            else:
                return None
        line_limit, char_limit = new_lines, new_chars
    return None



try:
    from hub.bach_paths import BACH_DB as _RUNTIME_DB
    from hub.task_audit import (
        COMPLETED_STATUSES,
        GateReopenBlocked,
        apply_task_field_changes,
    )
    RUNTIME_BACH_DB = str(_RUNTIME_DB)
except ImportError:
    RUNTIME_BACH_DB = os.environ.get("BACH_DB", "")
    apply_task_field_changes = None
    COMPLETED_STATUSES = frozenset({"completed", "done"})

    class GateReopenBlocked(Exception):
        """Fallback, wenn hub.task_audit nicht importierbar ist (kein Guard, aber
        die except-Zweige in update_task muessen GateReopenBlocked fangen koennen)."""

_INITIAL_RUNTIME_DB = RUNTIME_BACH_DB
_INITIAL_TASK_AUDIT = apply_task_field_changes


def _current_runtime_db() -> str:
    # If bach_tools.RUNTIME_BACH_DB was explicitly changed, use it
    if RUNTIME_BACH_DB != _INITIAL_RUNTIME_DB:
        return RUNTIME_BACH_DB
    # Otherwise check if chat_runtime.RUNTIME_BACH_DB was changed (e.g. via monkeypatch)
    cr = sys.modules.get("hub._services.chat.chat_runtime")
    if cr is not None and hasattr(cr, "RUNTIME_BACH_DB"):
        if cr.RUNTIME_BACH_DB != _INITIAL_RUNTIME_DB:
            return cr.RUNTIME_BACH_DB
    return RUNTIME_BACH_DB


def _current_apply_task_field_changes():
    # If bach_tools.apply_task_field_changes was explicitly changed, use it
    if apply_task_field_changes is not _INITIAL_TASK_AUDIT:
        return apply_task_field_changes
    # Otherwise check if chat_runtime.apply_task_field_changes was changed (e.g. via monkeypatch)
    cr = sys.modules.get("hub._services.chat.chat_runtime")
    if cr is not None and hasattr(cr, "apply_task_field_changes"):
        if cr.apply_task_field_changes is not _INITIAL_TASK_AUDIT:
            return cr.apply_task_field_changes
    return apply_task_field_changes


# --- Sicherheit ---

BLOCKED_PATTERNS = [
    re.compile(r"rm\s+(-[rRf]+\s+)?/($|\s)"),
    re.compile(r"rm\s+(-[rRf]+\s+)?~($|\s)"),
    re.compile(r"mkfs\b"),
    re.compile(r"dd\s+if="),
    re.compile(r">\s*/dev/sd"),
    re.compile(r":\(\)\s*\{"),
]

# Nur lesende Befehle, die selbst keine anderen Programme starten.
# Entfernt (Argument-Ebene - ohne ein einziges Metazeichen waere ueber sie
# beliebige Ausfuehrung oder Schreiben moeglich gewesen): env, docker, pip,
# pip3, brew, curl und bach (umging die bach_command-Allowlist). Im
# Full-Modus bleiben sie ueber execute_command erreichbar.
# grep ist ebenfalls raus: Inhaltssuche laeuft ueber search_text, das den
# Secrets-Deny pro Datei anwendet. find bleibt (liefert nur Dateinamen),
# ohne ausfuehrende/schreibende Aktionen und nicht auf Secrets-Vorfahren.
SAFE_BASES = frozenset({
    "ls", "cat", "head", "tail", "find", "wc", "file", "stat",
    "echo", "date", "which", "whoami", "hostname", "uname",
    "df", "du", "uptime", "ps", "top", "sw_vers", "sysctl",
    "ollama", "git",
})

# find-Aktionen, die Programme starten, loeschen oder Dateien schreiben.
_FIND_DENY_PREFIXES = ("-exec", "-ok", "-delete", "-fprint", "-fls")
# git: nur lesende Unterbefehle, keine globalen Optionen davor (-c,
# --config-env, --exec-path, -C ...). Aliase sind damit automatisch aus.
# diff fehlt bewusst: mit --no-index oder Pfaden ausserhalb des Arbeitsbaums
# liest es beliebige Verzeichnisse rekursiv (Inhalte, nicht nur Namen).
_GIT_READ_SUBCOMMANDS = frozenset({
    "status", "log", "show", "branch", "rev-parse", "ls-files",
})
_GIT_DENY_ARGS = ("--output", "--upload-pack", "--receive-pack",
                  "--exec", "--ext-diff", "--textconv")
_GIT_BRANCH_READ_ARGS = frozenset({
    "--list", "-l", "-a", "--all", "-r", "--remotes", "-v", "-vv",
    "--show-current", "--no-color",
})
_OLLAMA_READ_SUBCOMMANDS = frozenset({"list", "ls", "ps", "show", "--version", "-v"})


def check_safe_shell_args(tokens: list) -> Optional[str]:
    """Argument-Ebene fuer safe_shell: Fehlermeldung oder None.

    tokens sind bereits tokenisiert und entquotet (Metazeichen-Verkettung
    faengt safe_exec vorher ab). Hier geht es um Optionen, mit denen ein
    an sich lesender Befehl doch etwas ausfuehrt oder schreibt."""
    base = safe_exec.base_command_name(tokens[0])
    rest = tokens[1:]
    for t in rest:
        # Positionsargumente und Werte von --opt=wert gleichermassen pruefen.
        value = t.split("=", 1)[1] if t.startswith("-") and "=" in t else t
        if value and not value.startswith("-") and _is_secret_path(Path(value)):
            return "Secrets-Pfad als Argument"
        if value.lower().startswith("ext::"):
            return "ext::-Transport ist nicht erlaubt"
    if base == "find":
        for t in rest:
            if t.lower().startswith(_FIND_DENY_PREFIXES):
                return f"find-Aktion {t} ist nicht erlaubt"
    recursive = base in ("du", "find") or (base == "ls" and any(
        t == "--recursive" or (t.startswith("-") and not t.startswith("--") and "R" in t)
        for t in rest))
    if recursive:
        if base == "find":
            # Startpfade stehen vor dem ersten Ausdruck (-name, (, ! ...),
            # nach den fuehrenden Optionen -H/-L/-P, -O<n> und -D <arg>.
            targets = []
            i = 0
            while i < len(rest) and (rest[i] in ("-H", "-L", "-P", "-D")
                                     or rest[i].startswith("-O")):
                i += 2 if rest[i] == "-D" else 1
            for t in rest[i:]:
                if t.startswith(("-", "(", "!")):
                    break
                targets.append(t)
            targets = targets or ["."]
        else:
            targets = [t for t in rest if not t.startswith("-")] or ["."]
        if any(_contains_secret_location(Path(t)) for t in targets):
            return "rekursiver Befehl auf ein Verzeichnis mit Secrets - list_directory nutzen"
    if base == "git":
        if not rest or rest[0] not in _GIT_READ_SUBCOMMANDS:
            return "git: nur " + ", ".join(sorted(_GIT_READ_SUBCOMMANDS)) + " ohne globale Optionen"
        for t in rest[1:]:
            if t.startswith(_GIT_DENY_ARGS):
                return f"git-Option {t} ist nicht erlaubt"
        if rest[0] == "branch" and not all(t in _GIT_BRANCH_READ_ARGS for t in rest[1:]):
            return "git branch: nur auflisten (--list, -a, -r, -v, --show-current)"
    elif base == "ollama":
        if not rest or rest[0] not in _OLLAMA_READ_SUBCOMMANDS:
            return "ollama: nur list, ps, show"
    elif base == "sysctl":
        if any(t in ("-w", "--write") or "=" in t for t in rest):
            return "sysctl: nur lesen"
    elif base == "date":
        if any(t in ("-s", "--set") or t.startswith("--set=") for t in rest):
            return "date: Setzen ist nicht erlaubt"
    elif base == "hostname":
        if any(not t.startswith("-") or t in ("-F", "--file") for t in rest):
            return "hostname: Setzen ist nicht erlaubt"
    return None

CMD_TIMEOUT = limit("BACH_CMD_TIMEOUT")


def is_blocked(cmd: str) -> bool:
    return any(pat.search(cmd) for pat in BLOCKED_PATTERNS)


def is_safe_command(cmd: str) -> bool:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    if not parts:
        return False
    return os.path.basename(parts[0]) in SAFE_BASES


BLOCKED_WRITE_PREFIXES = (
    "/etc", "/usr", "/bin", "/sbin", "/System", "/Library",
    "/var/root", "/private/etc",
)

BACH_SYSTEM_DIR = str(Path(__file__).resolve().parents[2])


# Kleiner, harter Deny fuer die offensichtlichsten Secrets-Orte in den
# LESE-Werkzeugen list_directory/read_file/search_text (direkt aus
# LLM-Argumenten, potenziell prompt-injection-gesteuert). Zusaetzlich
# gilt die Wurzel-Allowlist _ALLOWED_FS_ROOTS mit Symlink-Aufloesung
# (siehe _fs_root_allowed weiter unten); die Secrets-Deny-Liste bleibt
# als zusaetzliche Schicht darueber.
_SECRET_PATH_SEGMENTS = frozenset({".ssh", ".credentials", "credentials"})
# Einzelne Dateien mit Tokens/Zugangsdaten (u. a. die Bot-Konfiguration
# ~/.config/bach/telegram_chat.json mit dem Bot-Token).
_SECRET_FILE_NAMES = frozenset({
    "telegram_chat.json", "bach_secrets.json",
    ".npmrc", ".netrc", ".pypirc", "auth.json",
})


def _resolve(p) -> Path:
    cr = sys.modules.get("hub._services.chat.chat_runtime")
    if cr is not None and hasattr(cr, "_resolve"):
        fn = getattr(cr, "_resolve")
        if fn is not None and fn is not _resolve and not getattr(fn, "_in_resolve", False):
            try:
                fn._in_resolve = True
                try:
                    return fn(p)
                finally:
                    fn._in_resolve = False
            except Exception:
                pass
    try:
        return Path(p).expanduser().resolve()
    except OSError:
        return Path(p).expanduser()


def _norm(p: Path) -> str:
    return os.path.normcase(str(p)).rstrip("\\/")


def _is_under(child: Path, parent: Path) -> bool:
    c, par = _norm(child), _norm(parent)
    return c == par or c.startswith(par + os.sep)


# Wurzel-Allowlist fuer die LESE-Werkzeuge list_directory/read_file/
# search_text: nur Pfade unterhalb des Home-Verzeichnisses oder des
# BACH-Systemverzeichnisses sind erlaubt. Alles wird vor dem Vergleich
# aufgeloest (Symlinks), damit ein Symlink in einem erlaubten Ast, der
# ausserhalb zeigt (z. B. nach /etc), blockiert wird.
_ALLOWED_FS_ROOTS = tuple(
    _resolve(p) for p in (Path.home(), Path(BACH_SYSTEM_DIR))
)


def _fs_root_allowed(resolved: Path) -> bool:
    cr = sys.modules.get("hub._services.chat.chat_runtime")
    if cr is not None and hasattr(cr, "_ALLOWED_FS_ROOTS"):
        roots = getattr(cr, "_ALLOWED_FS_ROOTS")
    else:
        roots = _ALLOWED_FS_ROOTS
    return any(_is_under(resolved, r) for r in roots)


def _secret_locations() -> list:
    """Bekannte Secrets-Orte, fuer den Vorfahren-Check rekursiver Befehle.
    ~/.config/bach (Bot-Konfiguration mit Token) und die secrets_handler-
    Ablage (BACH_SECRETS_FILE bzw. ~/.bach/bach_secrets.json) gehoeren dazu."""
    home = _resolve(Path.home())
    locs = [home / ".ssh", home / ".credentials", home / "CREDENTIALS",
            home / ".config" / "bach", home / ".bach"]
    env_file = os.environ.get("BACH_SECRETS_FILE")
    if env_file:
        locs.append(_resolve(env_file))
    return locs


def _is_secret_path(p: Path) -> bool:
    """`~` und `..` erst aufloesen (expanduser+resolve), DANN pruefen -
    sonst kann ein relativer Pfad oder ein Symlink den Vergleich auf den
    falschen (unaufgeloesten) Pfad umlenken und den Deny umgehen."""
    resolved = _resolve(p)
    if any(seg.lower() in _SECRET_PATH_SEGMENTS for seg in resolved.parts):
        return True
    home = _resolve(Path.home())
    if _is_under(resolved, home / ".config" / "bach"):
        return True
    env_file = os.environ.get("BACH_SECRETS_FILE")
    if env_file and _is_under(resolved, _resolve(env_file)):
        return True
    name = resolved.name.lower()
    if _is_under(resolved.parent, home / ".bach") and ("token" in name or "secret" in name):
        return True
    return (name.endswith(".pem") or name.startswith("id_")
            or name in _SECRET_FILE_NAMES
            or name == ".env" or name.startswith(".env."))

def _task_code_reader_enabled(worker_task_binding, allowed_tools, mode: str) -> bool:
    if worker_task_binding is None or not isinstance(allowed_tools, (set, frozenset, tuple, list)):
        return False
    # A review is deliberately unable to start a worktree. Its private grant
    # must still select the strict task reader, never the generic home reader.
    # The grant and current parent revision are validated on every actual read.
    if getattr(worker_task_binding, "_review_grant", None) is not None:
        return True
    if "start_task_worktree" not in allowed_tools:
        return False
    available = {tool["function"]["name"] for tool in tools_for_mode(mode, bound_worker=True)}
    return "start_task_worktree" in available


def _authorize_task_reader(worker_task_binding, path):
    from hub._services.chat import worker_write_guard
    scope = worker_write_guard.authorize_task_read(
        worker_task_binding, path, secret_check=_is_secret_path,
    )
    return worker_write_guard, scope

def _contains_secret_location(p: Path) -> bool:
    """True, wenn ein REKURSIVER Befehl auf p an Secrets vorbeikommen
    koennte: p ist selbst geheim, ein Vorfahre eines bekannten Secrets-Orts,
    ein Dateisystem-Wurzelverzeichnis oder hat ein direktes Unterverzeichnis
    mit Secrets-Namen.
    ponytail: tiefer verschachtelte Secrets-Ordner unter fremden Pfaden sieht
    der Check nicht; die volle Loesung ist die Wurzel-Allowlist im Folgeticket."""
    resolved = _resolve(p)
    if _is_secret_path(resolved) or len(resolved.parts) <= 1:
        return True
    if any(_is_under(loc, resolved) for loc in _secret_locations()):
        return True
    try:
        return any(c.name.lower() in _SECRET_PATH_SEGMENTS
                   for c in resolved.iterdir() if c.is_dir())
    except OSError:
        return False


def _authorized_file_mutation_paths(source, destination, worker_task_binding=None):
    """Resolve file mutation paths through the bound task or trusted host root.

    Unbound tools use only the code-derived BACH_ROOT. Environment variables and
    caller-provided roots are not authority. This path check is not an OS sandbox
    and cannot make path-based copy/move syscalls atomic against later renames.
    """
    if worker_task_binding is not None:
        from hub._services.chat.worker_write_guard import authorize_mutation
        _, paths = authorize_mutation(worker_task_binding, paths=(source, destination))
        return paths

    try:
        from hub.bach_paths import BACH_ROOT
        from tools.fs_protection import sanitize_host_path

        trusted_root = Path(BACH_ROOT).expanduser().resolve(strict=True)
        if not trusted_root.is_dir():
            raise ValueError("BACH_ROOT ist kein Verzeichnis")

        def checked_path(value, *, must_exist):
            if not isinstance(value, str) or not value.strip() or chr(0) in value:
                raise ValueError("Pfad fehlt oder ist ungültig")
            expanded = os.path.expanduser(value)
            if not os.path.isabs(expanded):
                expanded = os.path.join(os.getcwd(), expanded)
            lexical = os.path.abspath(expanded)
            normalized = os.path.realpath(lexical)
            root_text = os.path.realpath(os.fspath(trusted_root))
            path_key = os.path.normcase(normalized)
            root_key = os.path.normcase(root_text)
            root_prefix = root_key.rstrip(os.sep) + os.sep
            if path_key == root_key or not path_key.startswith(root_prefix):
                raise ValueError("Pfad liegt außerhalb des BACH-Roots")
            if path_key != os.path.normcase(lexical):
                raise ValueError("Symlink- oder Ancestor-Umleitung erkannt")
            # Pass the exact normcase-normalized, prefix-checked value to both
            # the native sanitizer and downstream filesystem sinks.
            sanitized = Path(sanitize_host_path(
                path_key,
                base_path=trusted_root,
                allowed_roots=(trusted_root,),
                must_exist=must_exist,
            )).resolve(strict=must_exist)
            if os.path.normcase(os.fspath(sanitized)) != path_key:
                raise ValueError("Sanitisierter Pfad weicht vom geprüften Pfad ab")
            return Path(path_key)

        return (
            checked_path(source, must_exist=True),
            checked_path(destination, must_exist=False),
        )
    except Exception:
        raise ValueError(
            "Ungebundene Dateioperation blockiert: Quelle und Ziel müssen im "
            "codegestützten BACH-Root liegen; ein externer Host-Root ist nicht freigegeben."
        ) from None


def is_safe_write_path(path_str: str, mode: str) -> Optional[str]:
    """Return error message if the path is blocked for writes, else None.

    Hier laufen alle schreibenden Werkzeuge ausser write_file zusammen --
    edit_file, move_file, copy_file, recycle, create_directory. Deshalb steht
    das Plan-Gate hier und nicht in fuenf Aufrufstellen: Im Planmodus wird
    nicht geschrieben, auch dann nicht, wenn ein Modell ein Werkzeug aufruft,
    das ihm gar nicht angeboten wurde (T-20260912-605163733).
    """
    if mode == "plan":
        return "Planmodus: es wird geplant, nicht geschrieben"
    if mode != "safe":
        return None
    p = str(Path(path_str).resolve())
    for prefix in BLOCKED_WRITE_PREFIXES:
        if p.startswith(prefix):
            return f"Schreibzugriff auf {prefix}/ im Safe-Mode nicht erlaubt"
    if p.startswith(BACH_SYSTEM_DIR) and "/user/" not in p.lower():
        return "Schreibzugriff auf BACH-Systemdateien im Safe-Mode nicht erlaubt"
    return None


def run_shell(cmd: str, timeout: int = CMD_TIMEOUT) -> str:
    """Fuehrt cmd ueber eine echte Shell aus (Pipes/&&/Umleitung erlaubt).

    NUR fuer interne Aufrufer mit FESTEM, nicht von aussen kontrolliertem
    cmd (system_status/ollama_info-Vorlagen). Fuer alles, was direkt aus
    LLM-Tool-Argumenten stammt, IMMER run_shell_restricted() nehmen
    (safe_shell/execute_command) - siehe hub/safe_exec.py fuer den Grund.
    """
    timeout = min(max(timeout, 5), 120)
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, stdin=subprocess.DEVNULL,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if r.returncode != 0:
            return _tool_effect_unconfirmed()
        out = r.stdout
        if r.stderr:
            out += "\n[stderr] " + r.stderr
        return (out or "(keine Ausgabe)")[:4000]
    except subprocess.TimeoutExpired:
        return _tool_effect_unconfirmed()
    except Exception:  # noqa: BLE001 -- After subprocess start, expose only the bounded unknown-effect result.
        return _tool_effect_unconfirmed()


def run_shell_restricted(cmd: str, timeout: int = CMD_TIMEOUT,
                          allowed: Optional[FrozenSet[str]] = None) -> str:
    """Fuehrt cmd fail-closed aus - IMMER shell=False (hub/safe_exec.py).

    Fuer safe_shell/execute_command: cmd kommt direkt aus einem
    LLM-Tool-Aufruf. Der fruehere Bug dort: der Basisbefehl wurde geprueft
    (is_safe_command/is_blocked), der KOMPLETTE String aber danach trotzdem
    per shell=True ausgefuehrt - Metazeichen wie && | ; $() erlaubten
    beliebige Befehlsverkettung unabhaengig von der Pruefung.
    safe_exec.resolve_executable() loest argv[0] per shutil.which() auf und
    lehnt nicht zitierte Metazeichen fail-closed ab. `allowed=None`
    (execute_command/Full-Modus) heisst "jeder Basisbefehl", Verkettung
    bleibt trotzdem verboten.
    """
    timeout = min(max(timeout, 5), 120)
    try:
        argv = safe_exec.resolve_executable(cmd, allowed)
    except safe_exec.CommandRejected as e:
        return _tool_policy_denial("command_not_authorized", "BLOCKIERT: Befehl ist aus Sicherheitsgründen gesperrt.")
    try:
        r = subprocess.run(
            argv, shell=False, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, stdin=subprocess.DEVNULL,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if r.returncode != 0:
            return _tool_effect_unconfirmed()
        out = r.stdout
        if r.stderr:
            out += "\n[stderr] " + r.stderr
        return (out or "(keine Ausgabe)")[:4000]
    except subprocess.TimeoutExpired:
        return _tool_effect_unconfirmed()
    except Exception:  # noqa: BLE001 -- After subprocess start, expose only the bounded unknown-effect result.
        return _tool_effect_unconfirmed()


def run_argv(argv: list, timeout: int = CMD_TIMEOUT) -> str:
    """Fuehrt ein FERTIGES argv aus - immer shell=False, kein Tokenisieren.

    Fuer Faelle wie 'ollama show <modell>': genau EIN Argument kommt aus
    einem LLM-Tool-Aufruf, der Rest ist fest. Da nie eine Shell beteiligt
    ist, kann das Argument nicht ausbrechen - unabhaengig davon, was es
    enthaelt (kein shlex.quote()-Escaping noetig, das unter Windows ohnehin
    nicht griff, siehe Befund D)."""
    timeout = min(max(timeout, 5), 120)
    try:
        r = subprocess.run(
            argv, shell=False, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, stdin=subprocess.DEVNULL,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if r.returncode != 0:
            return _tool_effect_unconfirmed()
        out = r.stdout
        if r.stderr:
            out += "\n[stderr] " + r.stderr
        return (out or "(keine Ausgabe)")[:4000]
    except subprocess.TimeoutExpired:
        return _tool_effect_unconfirmed()
    except Exception:  # noqa: BLE001 -- After subprocess start, expose only the bounded unknown-effect result.
        return _tool_effect_unconfirmed()


# --- Tool-Definitionen ---

def _tool(name, desc, props, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
            },
        },
    }


# Einzige Quelle fuer die bach_command-Handler: sowohl die Tool-Schema-
# Beschreibung (fuers Modell) als auch die Laufzeit-Allowlist (fuer den
# Dispatch) werden HIERAUS gebaut - ein Handler in dieser Liste zu ergaenzen
# reicht, es kann nicht mehr auseinanderlaufen (Befund B: die Schema-
# Beschreibung war rein deskriptiv, der Dispatch pruefte den vom Modell
# gelieferten Handler-String gar nicht gegen irgendeine Liste - "sandbox"
# war z. B. ueber bach_command erreichbar, obwohl es dort nie beworben
# wurde). "sandbox" bleibt ausgeschlossen: es hat seine eigene, engere
# Shell-Allowlist (hub/sandbox.py) und ist ueber bach_command nicht als
# Umweg dorthin gedacht.
BACH_COMMAND_HANDLERS = (
    "status", "task", "mem", "search", "help", "tools", "denkarium",
    "calendar", "contact", "routine", "timer", "countdown", "news",
    "newspaper", "lesson", "snapshot", "partner", "connector", "msg",
    "backup", "web-parse", "web-scrape", "skills", "agent", "maintain",
    "sync", "abo", "steuer", "gesundheit", "mediplaner", "haushalt",
    "versicherung", "inbox", "wiki",
)

TOOLS_SAFE = [
    _tool("agent_manage", "Agenten und Blueprints anlegen, als Living einrichten und lokale Worker starten. Cloud-Worker startet ausschließlich der Nutzer.", {
        "action": {"type": "string", "enum": ["list", "blueprint_create", "materialize", "start_local"]},
        "blueprint": {"type": "object", "description": "Neuer Blueprint mit name, title, persona_role, persona_prompt, skills, governance und expected_version=0"},
        "blueprint_id": {"type": "integer"},
        "expected_version": {"type": "integer"},
        "configuration_version": {"type": "string", "description": "Aktuelle Konfigurationsversion aus action=list"},
        "execution": {"type": "object", "description": "Expliziter Anbieter, Modell und Modus für den neuen Living-Steckplatz"},
        "slot_id": {"type": "string"},
    }, ["action"]),
    _tool("skill_create", "SKILL.md als lokale Anleitung anlegen. Änderungen benötigen die aktuelle Quellenversion; Skills erteilen keine Werkzeugrechte.", {
        "name": {"type": "string", "description": "Skill-ID"},
        "content": {"type": "string", "description": "Vollständige SKILL.md mit Beschreibung und Ablauf"},
        "source_version": {"type": "string", "description": "0 für eine neue ID; SHA256 für eine ausdrücklich gewünschte Änderung"},
    }, ["name", "content", "source_version"]),
    _tool("list_directory", "Dateien und Ordner in einem Verzeichnis auflisten", {
        "path": {"type": "string", "description": "Verzeichnispfad"},
        "details": {"type": "boolean", "description": "Ausführlich mit Rechten und Größe"},
    }),
    _tool("read_file", "Datei lesen (max. 200 physische Zeilen); Task-Reads zeigen standardmäßig 1-basierte Zeilennummern und Bereichs-/Abschneidungshinweise. Zeilenangaben sind Navigationshilfe, kein Wahrheitsbeleg; unnummerierte oder abgeschnittene Zitate sind nicht verifiziert. line_numbers=false erhält die rohe Legacy-Ausgabe.", {
        "path": {"type": "string", "description": "Dateipfad"},
        "lines": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Maximale Zeilenzahl (Standard 50, bei Task-Reads 200; Ausgabe höchstens 4000 Zeichen)"},
        "offset": {"type": "integer", "minimum": 1, "maximum": 2147483647, "description": "Physische Startzeile (1-basiert, Standard 1)"},
        "line_numbers": {"type": "boolean", "description": "Zeilennummern und Metadaten anzeigen; Standard an für Task-Reads, sonst aus."},
    }, ["path"]),
    _tool("search_text", "In Dateien nach einem Muster suchen (grep)", {
        "pattern": {"type": "string", "description": "Suchmuster (Regex)"},
        "path": {"type": "string", "description": "Suchpfad"},
        "recursive": {"type": "boolean", "description": "Rekursiv"},
    }, ["pattern"]),
    _tool("system_status", "Systemstatus: Uptime, RAM, Disk, CPU", {}),
    _tool("ollama_info", "Ollama-Informationen abrufen", {
        "action": {"type": "string", "enum": ["list", "running", "show"]},
        "model": {"type": "string", "description": "Modellname (nur bei show)"},
    }),
    _tool("bach_command", "BACH-Befehl ausführen (Memory, Tasks, Kalender, Denkarium, News, etc.)", {
        "handler": {"type": "string", "description": "Handler: " + ", ".join(BACH_COMMAND_HANDLERS)},
        "operation": {"type": "string", "description": "Operation: list, add, done, facts, write, read, search, context, today, brainstorm, promote, stats, fetch, generate, create, load"},
        "args": {"type": "array", "items": {"type": "string"}, "description": "Argumente"},
    }, ["handler"]),
    _tool("get_datetime", "Aktuelles Datum und Uhrzeit abfragen", {}),
    _tool("safe_shell", "Lesenden Shell-Befehl ausführen", {
        "command": {"type": "string", "description": "Shell-Befehl (nur lesende Befehle erlaubt)"},
        "cwd": {"type": "string", "description": "Task-Arbeitsverzeichnis"},
    }, ["command"]),
    _tool("web_search", "Im Internet nach Informationen suchen (DuckDuckGo)", {
        "query": {"type": "string", "description": "Suchanfrage"},
        "max_results": {"type": "integer", "description": "Maximale Ergebnisse (Standard 5, max 10)"},
    }, ["query"]),
    _tool("task_manage", "BACH-Tasks verwalten: anlegen, zerlegen, auflisten, aktualisieren, Status ändern", {
        "action": {"type": "string", "enum": ["list", "add", "done", "submit_result", "detail", "update", "decompose"],
                   "description": "Bei gebundener Task: list ohne task_id; update-Status (pending/open/blocked) ohne Inhaltsfelder; decompose mit subtasks=[{\"title\":\"Kind\",\"description\":\"Arbeit\"}], close_parent=false. Ergebnis nur mit submit_result (done als Alias) und complete=true/false abgeben. Abschluss nach konfiguriertem Modus."},
        "title": {"type": "string", "description": "Task-Titel (bei add)"},
        "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"], "description": "Priorität (Standard P3)"},
        "task_id": {"type": "integer", "description": "Task-ID (bei done/detail/update/decompose)"},
        "result": {"type": "string", "description": "Fertiges Worker-Ergebnis bei submit_result/done, höchstens 3000 Zeichen. Im einfachen Modus ohne vorgegebenen Vertrag genügt ein konkreter Ergebnistext als ausdrückliche Fertigmeldung; tatsächliche Arbeit und Prüfung nennen. Ein negativer oder unvollständiger JSON-Selbstcheck ist keine Fertigmeldung. Offene Pflichtarbeit oder Teilstand: submit_result mit complete=false (Teilstand wird gespeichert, Task bleibt offen). Andere Modi folgen ihrer Review-Regel."},
        "complete": {"type": "boolean", "description": "Pflicht bei submit_result/done einer gebundenen Task: true nur, wenn die Pflichtarbeit vollständig erledigt ist; false speichert result als Teilstand in der Task und gibt sie offen zurück (pending)."},
        "description": {"type": "string", "description": "Bei add/update: was zu tun ist UND was dafuer zu lesen ist."},
        "category": {"type": "string", "description": "Projekt-/Themenzuordnung"},
        "status": {"type": "string", "description": "Status (bei update, z.B. pending, open, in_progress, completed)"},
        "depends_on": {"type": "string", "description": "IDs vorausgesetzter Tasks, kommagetrennt"},
        "assigned_to": {"type": "string", "description": "Zuständige Fachrolle oder Agentenkennung"},
        "assigned_slot": {"type": "string", "description": "Verfügbarer Steckplatz aus agent_manage action=list"},
        "required_model": {"type": "string", "description": "Optionale feste Modellbindung"},
        "result_max_chars": {"type": "integer", "description": "Optionales Task-Ausgabelimit von 1 bis 3000 Zeichen; bei task_manage(update) weglassen zum Beibehalten"},
        "subtasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "string"},
                    "depends_on": {"type": "string"},
                    "assigned_slot": {"type": "string"},
                    "required_model": {"type": "string"},
                    "assigned_to": {"type": "string"},
                    "result_max_chars": {"type": "integer"},
                },
                "required": ["title"]
            },
            "description": "Liste von Teilaufgaben bei action='decompose'"
        },
        "sequential": {"type": "boolean", "description": "Bei decompose: ob Teilaufgaben sequentiell voneinander abhängen sollen"},
        "close_parent": {"type": "boolean", "description": "Worker müssen false verwenden; Zerlegung ist kein erledigter Auftrag."}
    }, ["action"]),
    _tool("maintain", "Systemwartung: fällige Tasks prüfen, Wartungsoperationen ausführen", {
        "action": {"type": "string", "enum": ["check", "run", "health", "services", "sync"],
                   "description": "check=fällige Tasks, run=Wartung, health=BACH-Status, services=Service-Check, sync=OneDrive→Mirror"},
        "operation": {"type": "string",
                      "description": "Bei run: registry, skills, docs, backup, clean, memory, recurring"},
    }, ["action"]),
    _tool("foerderbericht", "Förderbericht-Pipeline: Anonymisierung und Berichterstellung", {
        "action": {"type": "string", "enum": ["prepare", "status", "cleanup"],
                   "description": "prepare=Phase 1 (Anonymisierung, kein LLM), status=Pipeline-Status, cleanup=Zwischendateien löschen"},
        "zeitraum": {"type": "string", "description": "Berichtszeitraum (z.B. '01.01.2025 - 31.12.2025')"},
        "eltern": {"type": "array", "items": {"type": "string"}, "description": "Elternnamen zur Anonymisierung"},
        "adresse": {"type": "string", "description": "Klienten-Adresse zur Anonymisierung"},
    }, ["action"]),
    _tool("delegate", "Aufgabe an Claude Code oder Codex CLI delegieren", {
        "target": {"type": "string", "enum": ["claude", "codex"], "description": "Ziel-Agent"},
        "prompt": {"type": "string", "description": "Aufgabe oder Frage für den Agenten"},
        "context": {"type": "string", "description": "Optionaler Kontext zur Aufgabe"},
    }, ["target", "prompt"]),
    _tool("weather", "Aktuelles Wetter für einen Ort oder Koordinaten abfragen (wttr.in)", {
        "location": {"type": "string", "description": "Ortsname (z.B. 'Berlin') oder Koordinaten ('52.52,13.405')"},
    }, ["location"]),
    _tool("edit_file", "Text in einer Datei ersetzen (suchen und ersetzen)", {
        "path": {"type": "string", "description": "Dateipfad"},
        "old_text": {"type": "string", "description": "Zu ersetzender Text (muss exakt vorkommen)"},
        "new_text": {"type": "string", "description": "Neuer Text"},
        "all": {"type": "boolean", "description": "Alle Vorkommen ersetzen (Standard: nur erstes)"},
    }, ["path", "old_text", "new_text"]),
    _tool("move_file", "Datei oder Ordner verschieben oder umbenennen", {
        "source": {"type": "string", "description": "Quellpfad"},
        "destination": {"type": "string", "description": "Zielpfad"},
    }, ["source", "destination"]),
    _tool("copy_file", "Datei oder Ordner kopieren", {
        "source": {"type": "string", "description": "Quellpfad"},
        "destination": {"type": "string", "description": "Zielpfad"},
    }, ["source", "destination"]),
    _tool("file_info", "Detaillierte Informationen zu einer Datei oder einem Ordner", {
        "path": {"type": "string", "description": "Pfad zur Datei oder zum Ordner"},
    }, ["path"]),
    _tool("recycle", "Datei oder Ordner in den Papierkorb verschieben (wiederherstellbar)", {
        "path": {"type": "string", "description": "Pfad zum Löschen (wird in Papierkorb verschoben)"},
    }, ["path"]),
    _tool("create_directory", "Neuen Ordner erstellen (inkl. Elternordner)", {
        "path": {"type": "string", "description": "Pfad des neuen Ordners"},
    }, ["path"]),
    _tool("web_fetch", "Inhalt einer URL abrufen (Webseite, API, JSON)", {
        "url": {"type": "string", "description": "Die abzurufende URL"},
        "extract_text": {"type": "boolean", "description": "Nur sichtbaren Text extrahieren (bei HTML, Standard: true)"},
        "max_chars": {"type": "integer", "description": "Maximale Zeichenanzahl (Standard 4000, max 8000)"},
    }, ["url"]),
    _tool("start_task_worktree", "Erzeugt einen isolierten Git-Worktree für eine Aufgabe unter ~/services/bach-worktrees/task-<id>", {
        "task_id": {"type": "integer", "description": "ID der Aufgabe"},
    }, ["task_id"]),
    _tool("finish_task", "Schließt die Aufgabe im Worktree ab: führt Tests aus, committet, pusht und erstellt einen PR. Bei Abbruch setzt is_wip=True einen WIP-Commit.", {
        "task_id": {"type": "integer", "description": "ID der Aufgabe"},
        "message": {"type": "string", "description": "Commit- und PR-Beschreibung"},
        "is_wip": {"type": "boolean", "description": "True falls unvollständig/Abbruch (sichert WIP-Stand ohne PR)"},
    }, ["task_id", "message"]),
    _tool("cleanup_task_worktree", "Entfernt den Worktree für eine Aufgabe, nachdem der PR gemergt ist.", {
        "task_id": {"type": "integer", "description": "ID der Aufgabe"},
    }, ["task_id"]),
]

TOOLS_FULL = TOOLS_SAFE + [
    _tool("execute_command", "Beliebigen Shell-Befehl ausführen (nur im Full-Modus)", {
        "command": {"type": "string", "description": "Shell-Befehl"},
        "timeout": {"type": "integer", "description": "Timeout in Sekunden (max 120)"},
        "cwd": {"type": "string", "description": "Task-Arbeitsverzeichnis"},
    }, ["command"]),
    _tool("write_file", "Datei schreiben oder erstellen", {
        "path": {"type": "string", "description": "Dateipfad"},
        "content": {"type": "string", "description": "Dateiinhalt"},
    }, ["path", "content"]),
]

#: Aus TOOLS_SAFE fuer den Planmodus ausgenommen.
#:
#: `safe` heisst "ohne beliebige Shell", nicht "ohne Schreiben" -- /mode full
#: kuendigt dem Nutzer ausdruecklich "Shell-Befehle und Dateischreiben" an,
#: also ist safe der Modus, in dem man mit Dateien arbeitet, ohne die Shell zu
#: oeffnen. Fuer den interaktiven Chat ist das richtig. Ein Planlauf braucht
#: davon nichts: Er liest, und sein einziges Ergebnis sind Tasks.
_NICHT_IM_PLAN = frozenset({
    # veraendern das Dateisystem
    "edit_file", "move_file", "copy_file", "recycle", "create_directory",
    # veraendern BACH-Zustand jenseits der Tasks
    "bach_command", "maintain", "foerderbericht", "agent_manage", "skill_create",
    # startet einen fremden Agenten, der diese Grenze nicht kennt
    "delegate",
    # Worker-Git-Werkzeuge gehoeren nicht in den Planmodus
    "start_task_worktree", "finish_task", "cleanup_task_worktree",
})

#: Werkzeuge eines Planlaufs: lesen, nachschlagen, Pakete anlegen.
#: Abgeleitet statt aufgezaehlt -- so bleibt TOOLS_PLAN automatisch eine
#: Teilmenge von TOOLS_SAFE, auch wenn dort etwas hinzukommt.
TOOLS_PLAN = [t for t in TOOLS_SAFE
              if t["function"]["name"] not in _NICHT_IM_PLAN]


def tools_for_mode(mode: str, *, bound_worker: bool = False) -> list:
    """Werkzeugliste zum Sitzungsmodus.

    Ein unbekannter Modus faellt bewusst auf `safe` zurueck und nicht auf
    `full`: Ein Tippfehler darf nie mehr Rechte geben als angefordert.
    """
    tools = TOOLS_FULL if mode == "full" else TOOLS_PLAN if mode == "plan" else TOOLS_SAFE
    if bound_worker:
        # Native tasks may use their selected provider, never the legacy
        # paid delegation fallback or destructive post-merge cleanup.
        return [tool for tool in tools if tool["function"]["name"] not in {
            "delegate", "cleanup_task_worktree",
        }]
    return tools


#: Werkzeuge nach Bedarf (BACH-Harness, 25.10.2026): Steht dieses Meta-Werkzeug
#: in den allowed_tools eines gebundenen Workers, bekommt er zuerst nur den
#: Kernsatz und holt Gruppen selbst nach. Die übrigen allowed_tools bleiben die
#: Obergrenze; Gruppen öffnen nie ein Werkzeug außerhalb davon.
REQUEST_TOOLS = "request_tools"
CORE_TOOLS = frozenset({"task_manage", "read_file", "search_text", "list_directory"})
TOOL_GROUPS = {
    "dateien": ("Dateien schreiben", ("write_file", "edit_file", "create_directory", "file_info",
                                      "move_file", "copy_file", "recycle")),
    "lieferung": ("Code-Lieferung/Git", ("start_task_worktree", "finish_task")),
    "ausfuehren": ("Ausführen", ("execute_command", "safe_shell")),
    "web": ("Web", ("web_search", "web_fetch")),
    "system": ("System", ("system_status", "ollama_info", "get_datetime", "bach_command",
                          "maintain", "weather", "foerderbericht")),
    "skills": ("Skills", ("skill_create", "agent_manage")),
}


def tool_groups_available(tools) -> dict:
    """Gruppen mit ihren Werkzeugen, soweit sie in ``tools`` schon freigegeben sind."""
    offered = {tool["function"]["name"] for tool in tools}
    groups = {group: [name for name in names if name in offered]
              for group, (_label, names) in TOOL_GROUPS.items()}
    return {group: names for group, names in groups.items() if names}


def on_demand_tools(tools, requested_groups) -> list:
    """Kernsatz, angeforderte Gruppen und ungruppierte Werkzeuge; dazu request_tools.

    ``tools`` ist der bereits nach Modus und allowed_tools gefilterte Satz.
    """
    groups = tool_groups_available(tools)
    grouped = {name for _label, names in TOOL_GROUPS.values() for name in names}
    keep = {name for group in requested_groups for name in groups.get(group, ())}
    result = [tool for tool in tools if tool["function"]["name"] in keep
              or tool["function"]["name"] in CORE_TOOLS
              or tool["function"]["name"] not in grouped]
    missing = [group for group in groups if group not in requested_groups]
    if missing:
        result.append(_tool(
            REQUEST_TOOLS,
            "Weitere Werkzeuge ab der nächsten Runde freischalten. Gruppen:\n" + "\n".join(
                f"{group}: {TOOL_GROUPS[group][0]} ({', '.join(groups[group])})" for group in missing),
            {"group": {"type": "string", "enum": missing}}, ["group"]))
    return result


# --- Delegation ---

def _delegate_claude_api(prompt: str, api_key: str,
                         model: str = "claude-sonnet-4-6") -> str:
    import httpx
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        data = r.json()
        if r.status_code != 200:
            return _tool_effect_unconfirmed()
        blocks = data.get("content", [])
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return (text or "(keine Antwort)")[:3000]
    except Exception:  # noqa: BLE001 -- Redact provider failures because response state may be uncertain.
        return _tool_effect_unconfirmed()


# --- Tool-Ausführung ---

def _task_route_fields(conn, payload):
    """Persist requested dispatch bindings; an old schema must never ignore them."""
    result = {key: payload[key] for key in ("assigned_slot", "required_model") if key in payload}
    if any(not isinstance(value, str) or len(value) > 200 or "\x00" in value for value in result.values()):
        raise ValueError("Task-Zuweisung benötigt gültige Textwerte")
    if result:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if set(result) - columns:
            raise ValueError("TaskDB unterstützt diese Steckplatz-Zuweisung noch nicht")
    return result


def _review_tool_grants(binding, grants):
    """Private review authority always narrows configurable tool permissions."""
    if getattr(binding, "_review_grant", None) is not None:
        readonly = {"read_file", "search_text", "task_manage"}
        return frozenset(readonly if grants is None else readonly.intersection(grants))
    return grants


def _tool_policy_denial(reason: str, text: str) -> ToolErrorText:
    """Return an explicit finite policy denial; never infer from text."""
    return ToolErrorText(text, code="tool_policy_denied", reason=reason)


def _tool_effect_unconfirmed() -> ToolErrorText:
    """An operation may have run or partially changed state before failing."""
    return ToolErrorText(
        "Werkzeugausführung nicht bestätigt; Wirkung unbekannt.",
        code="bach_tool_effect_unconfirmed",
    )


def exec_tool(name: str, args: Any, mode: str, bach_app=None,
              default_model: str = "", *, worker_task_binding=None,
              require_task_binding: bool = False, agent_operations=None,
              allowed_tools=None) -> str:
    allowed_tools = _review_tool_grants(worker_task_binding, allowed_tools)
    if allowed_tools is not None and name not in allowed_tools:
        return _tool_policy_denial("tool_not_authorized", "BLOCKIERT: Werkzeug ist für diesen Agenten nicht freigegeben.")
    if require_task_binding and worker_task_binding is None:
        return ToolErrorText("Taskbindung fehlt; Werkzeug nicht ausgeführt.", code="task_binding_required")
    if worker_task_binding is not None:
        try:
            worker_task_binding.assert_active()
        except Exception:
            return _tool_policy_denial("worker_context_denied", "BLOCKIERT: Taskbindung oder Workerlauf ist nicht mehr aktiv.")
        from hub._services.chat import worker_write_guard
        if worker_write_guard.is_write_tool(name):
            try:
                worker_write_guard.require_write_grant(name, allowed_tools)
            except worker_write_guard.WorkerWriteGuardError as exc:
                return _tool_policy_denial("write_grant_denied", "BLOCKIERT: Schreibfreigabe ist für diesen Worker nicht vorhanden.")
        if name not in {tool["function"]["name"] for tool in tools_for_mode(mode, bound_worker=True)}:
            return _tool_policy_denial("mode_not_authorized", "BLOCKIERT: Werkzeug ist in diesem Worker-Modus nicht verfügbar.")
        # Shared by the chat loop and the managed CLI bridge. Preserve proof
        # before dispatch, including reads and uncertain tool outcomes.
        mark_dispatch = getattr(worker_task_binding, "mark_tool_dispatch", None)
        if callable(mark_dispatch):
            mark_dispatch()
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            args = {}

    task_code_capability = _task_code_reader_enabled(worker_task_binding, allowed_tools, mode)

    if worker_task_binding is not None and name == "start_task_worktree":
        if (not isinstance(args, dict) or type(args.get("task_id")) is not int
                or args["task_id"] != worker_task_binding.task_id):
            return _tool_policy_denial("task_target_mismatch", "BLOCKIERT: Worktree gehört nicht zur gebundenen Task.")

    try:
        if name in {"agent_manage", "skill_create"} and mode not in {"safe", "full"}:
            return _tool_policy_denial("mode_not_authorized", "BLOCKIERT: Agenten- und Skillverwaltung ist in diesem Modus nicht verfügbar.")
        if name == "agent_manage":
            if agent_operations is None:
                return _tool_policy_denial("provider_unavailable", "BLOCKIERT: Nativer Agentencontroller ist nicht angebunden.")
            grants = {tool["function"]["name"] for tool in tools_for_mode(mode, bound_worker=worker_task_binding is not None)}
            if allowed_tools is not None:
                grants &= set(allowed_tools)
            return json.dumps(agent_operations(args, mode=mode, allowed_tools=grants), ensure_ascii=False)

        if name == "skill_create":
            if not isinstance(args, dict) or set(args) != {"name", "content", "source_version"}:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Skill benötigt ID, vollständigen Inhalt und Quellenversion.")
            from hub._services.skill_source_service import save_skill
            saved = save_skill(args["name"], args["content"], args["source_version"])
            return json.dumps({k: v for k, v in saved.items() if k != "content"}, ensure_ascii=False)

        if name == "list_directory":
            if task_code_capability:
                try:
                    read_guard, scope = _authorize_task_reader(worker_task_binding, args.get("path") or ".")
                except Exception:  # noqa: BLE001 - Leseberechtigung bei jeder Unsicherheit sperren.
                    return _tool_policy_denial("task_read_scope_denied", "BLOCKIERT: Task-Lesebereich nicht bestätigt.")
                if scope.requested_is_file:
                    return _tool_policy_denial("directory_expected", "BLOCKIERT: Ein Verzeichnis ist erforderlich.")
                children = {}
                for child in (*scope.files, *scope.directories):
                    if child != scope.requested and child.parent == scope.requested:
                        children[child.name] = child
                details = args.get("details")
                lines = []
                for name_part, child in sorted(children.items()):
                    if details:
                        is_dir = child in scope.directories
                        size = 0 if is_dir else scope.sizes.get(child, 0)
                        lines.append(f"{'d' if is_dir else '-'} {size:>10} {name_part}")
                    else:
                        lines.append(name_part)
                return ("\n".join(lines) or "(leer)")[:4000]
            # Kein Subprocess/Shell mehr (frueher: run_shell("ls ..." per
            # shell=True) mit shlex.quote() auf den Pfad - shlex.quote()
            # eskript POSIX-Single-Quotes, die auf Windows'
            # shell=True->cmd.exe NICHT als Quotierung wirken, sondern als
            # literale Zeichen; Metazeichen im Pfad waeren dort trotzdem
            # von cmd.exe interpretiert worden. pathlib kennt keine Shell.
            target = Path(args.get("path") or os.path.expanduser("~"))
            resolved = _resolve(target)
            if not _fs_root_allowed(resolved):
                return _tool_policy_denial("path_not_authorized", "BLOCKIERT: Pfad außerhalb der erlaubten Wurzeln.")
            if _is_secret_path(resolved):
                return _tool_policy_denial("secret_path_denied", "BLOCKIERT: Secrets-Verzeichnis darf nicht aufgelistet werden.")
            try:
                entries = sorted(resolved.iterdir(), key=lambda e: e.name)
            except OSError:
                return _tool_effect_unconfirmed()
            details = args.get("details")
            lines = []
            for e in entries:
                if _is_secret_path(e):
                    continue
                if details:
                    try:
                        st = e.stat()
                        kind = "d" if e.is_dir() else "-"
                        lines.append(f"{kind} {st.st_size:>10} {e.name}")
                    except OSError:
                        lines.append(f"? {e.name}")
                else:
                    lines.append(e.name)
            return ("\n".join(lines) or "(leer)")[:4000]

        if name == "read_file":
            if not isinstance(args, dict):
                return "Fehler: Ungültige read_file-Parameter."
            readonly_worker_profile = _read_evidence_readonly_worker_enabled(worker_task_binding, allowed_tools)
            requested_format = args.get("output_format")
            if readonly_worker_profile and requested_format is None:
                return _read_evidence_unavailable("versioned_format_required")
            formatter = None
            evidence_request = None
            if "output_format" in args:
                if type(requested_format) is not str or requested_format != _READ_EVIDENCE_SCHEMA:
                    return _read_evidence_unavailable("unsupported_output_format")
                if not readonly_worker_profile:
                    return _read_evidence_unavailable("reviewer_profile_required")
                formatter = _read_evidence_formatter()
                if formatter is None:
                    return _read_evidence_unavailable("formatter_capability_unverified")
                evidence_request = _read_evidence_request(args)
                if evidence_request is None:
                    return "Fehler: Ungültige read-evidence-Parameter."
            p = args.get("path", "")
            if not p:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Ein Datei-Pfad ist erforderlich.")
            if task_code_capability:
                try:
                    read_guard, scope = _authorize_task_reader(worker_task_binding, p)
                except Exception:  # noqa: BLE001 - Leseberechtigung bei jeder Unsicherheit sperren.
                    return _tool_policy_denial("task_read_scope_denied", "BLOCKIERT: Task-Lesebereich nicht bestätigt.")
                if not scope.requested_is_file:
                    return _tool_policy_denial("task_read_scope_denied", "BLOCKIERT: Im Task-Lesebereich muss eine freigegebene Datei angegeben werden.")
                resolved = scope.requested
            else:
                resolved = _resolve(p)
                if not _fs_root_allowed(resolved):
                    return _tool_policy_denial("path_not_authorized", "BLOCKIERT: Pfad außerhalb der erlaubten Wurzeln.")
                if _is_secret_path(resolved):
                    return _tool_policy_denial("secret_path_denied", "BLOCKIERT: Secrets-Datei darf nicht gelesen werden.")
            if evidence_request is not None:
                _, start_line, char_offset, max_lines, max_chars = evidence_request
                try:
                    if task_code_capability:
                        with (
                            read_guard.open_authorized_task_file(scope, resolved) as binary,
                            io.TextIOWrapper(
                                binary, encoding="utf-8", errors="replace", newline=None,
                            ) as fh,
                        ):
                            text, source_eof = _read_evidence_source_chunk(
                                fh, start_line=start_line, char_offset=char_offset,
                                max_lines=max_lines, max_chars=max_chars,
                            )
                    else:
                        with open(
                            resolved, "r", encoding="utf-8", errors="replace", newline=None,
                        ) as fh:
                            text, source_eof = _read_evidence_source_chunk(
                                fh, start_line=start_line, char_offset=char_offset,
                                max_lines=max_lines, max_chars=max_chars,
                            )
                except _ReadEvidenceCursorError:
                    return "Fehler: Der read-evidence-Cursor liegt außerhalb der Zeile."
                except OSError:
                    if task_code_capability:
                        return "BLOCKIERT: Task-Datei konnte nicht sicher gelesen werden."
                    return "Fehler: Datei konnte nicht gelesen werden"
                except Exception:  # noqa: BLE001 - Fehlerdetails bleiben aus dem Beleg-DTO heraus.
                    return _read_evidence_unavailable("formatter_capability_unverified")
                rendered = _format_read_evidence_within_budget(
                    formatter, text, start_line=start_line, char_offset=char_offset,
                    source_eof=source_eof, max_lines=max_lines, max_chars=max_chars,
                )
                return rendered if rendered is not None else _read_evidence_unavailable(
                    "formatter_capability_unverified"
                )
            # Task readers page by the 4000-character output cap, not by 50 lines:
            # fewer calls for the same context (BACH harness, 25.10.2026).
            requested_lines = args.get("lines", MAX_READ_FILE_LINES if task_code_capability else 50)
            if type(requested_lines) is not int or requested_lines < 1:
                return "Fehler: lines muss eine positive Ganzzahl sein."
            lines = min(requested_lines, MAX_READ_FILE_LINES)
            if "offset" in args:
                raw_offset = args["offset"]
            elif "start" in args:
                raw_offset = args["start"]
            else:
                raw_offset = args.get("start_line", 1)
            if (type(raw_offset) is not int
                    or not 1 <= raw_offset <= MAX_READ_FILE_OFFSET):
                return "Fehler: offset muss eine gültige positive Ganzzahl sein."
            if "line_numbers" in args:
                line_numbers = args["line_numbers"]
                if type(line_numbers) is not bool:
                    return "Fehler: line_numbers muss boolesch sein."
            else:
                line_numbers = task_code_capability
            end_line = raw_offset + lines - 1
            picked = []
            total_lines = 0
            try:
                if task_code_capability:
                    with (
                        read_guard.open_authorized_task_file(scope, resolved) as binary,
                        io.TextIOWrapper(binary, encoding="utf-8", errors="replace") as fh,
                    ):
                        for line_number, line in enumerate(fh, start=1):
                            total_lines = line_number
                            if raw_offset <= line_number <= end_line:
                                picked.append((line_number, line))
                else:
                    with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
                        for line_number, line in enumerate(fh, start=1):
                            total_lines = line_number
                            if raw_offset <= line_number <= end_line:
                                picked.append((line_number, line))
            except OSError:
                return _tool_effect_unconfirmed()
            except Exception:  # noqa: BLE001 - Lesefehler bleiben ohne Inhaltsausgabe.
                return _tool_effect_unconfirmed()
            if not line_numbers:
                raw_text = "".join(line for _number, line in picked) or "(keine Zeilen)"
                return raw_text[:MAX_READ_FILE_OUTPUT_CHARS]
            return format_read_file_output(
                picked,
                offset=raw_offset,
                requested_lines=requested_lines,
                effective_lines=lines,
                total_lines=total_lines,
            )

        if name == "search_text":
            pat = args.get("pattern", "")
            if not isinstance(pat, str) or len(pat) > 1024:
                return _tool_policy_denial("search_pattern_invalid", "BLOCKIERT: Suchmuster ist ungültig oder zu lang.")
            p = Path(args.get("path") or ".")
            task_scope = None
            task_guard = None
            if task_code_capability:
                try:
                    task_guard, task_scope = _authorize_task_reader(worker_task_binding, p)
                except Exception:  # noqa: BLE001 - unklarer Task-Lesebereich bleibt gesperrt.
                    return _tool_policy_denial("task_read_scope_denied", "BLOCKIERT: Task-Lesebereich nicht bestätigt.")
                resolved = task_scope.requested
            else:
                resolved = _resolve(p)
                if not _fs_root_allowed(resolved):
                    return _tool_policy_denial("path_not_authorized", "BLOCKIERT: Pfad außerhalb der erlaubten Wurzeln.")
                if _is_secret_path(resolved):
                    return _tool_policy_denial("secret_path_denied", "BLOCKIERT: Secrets-Pfad darf nicht durchsucht werden.")
            recursive = args.get("recursive", True)
            import regex
            try:
                rx = regex.compile(pat, regex.VERSION0)
            except regex.error as e:
                return _tool_policy_denial("search_pattern_invalid", "BLOCKIERT: Suchmuster ist ungültig.")
            if task_scope is not None:
                if task_scope.requested_is_file:
                    files = [resolved]
                else:
                    files = [f for f in task_scope.files
                             if f != resolved and resolved in f.parents
                             and (recursive or f.parent == resolved)]
            else:
                files = resolved.rglob("*") if recursive and resolved.is_dir() else (
                    resolved.glob("*") if resolved.is_dir() else [resolved]
                )
            hits = []
            deadline = time.monotonic() + 5
            bytes_read = 0
            for n, f in enumerate(files):
                if time.monotonic() >= deadline:
                    return _tool_effect_unconfirmed()
                if n >= 5000:
                    break
                fr = f if task_scope is not None else _resolve(f)
                if task_scope is not None:
                    if fr not in task_scope.files:
                        continue
                elif not _fs_root_allowed(fr) or _is_secret_path(fr):
                    continue
                if not fr.is_file() or len(hits) >= 200:
                    continue
                try:
                    with ExitStack() as stack:
                        if task_scope is not None:
                            binary = stack.enter_context(
                                task_guard.open_authorized_task_file(task_scope, fr)
                            )
                        else:
                            binary = stack.enter_context(open(fr, "rb"))
                        fh = stack.enter_context(
                            io.TextIOWrapper(binary, encoding="utf-8", errors="replace")
                        )
                        i = 0
                        while line := fh.readline(65536):
                            i += 1
                            bytes_read += len(line.encode("utf-8"))
                            remaining = deadline - time.monotonic()
                            if bytes_read > 8_388_608 or remaining <= 0:
                                return _tool_effect_unconfirmed()
                            if rx.search(line, timeout=min(.05, remaining), concurrent=True):
                                hits.append(f"{f}:{i}:{line.rstrip()}")
                                if len(hits) >= 200:
                                    break
                except TimeoutError:
                    return _tool_effect_unconfirmed()
                except OSError:
                    continue
            return ("\n".join(hits) or "(keine Treffer)")[:4000]

        if name == "system_status":
            values = [
                run_shell("uptime"),
                run_shell("df -h / | tail -1"),
                run_shell("memory_pressure | head -3"),
                run_shell("sysctl -n machdep.cpu.brand_string"),
            ]
            failure = next((value for value in values if isinstance(value, ToolErrorText)), None)
            if failure is not None:
                return failure
            parts = [values[0], "Disk: " + values[1], "Speicher: " + values[2], "CPU: " + values[3]]
            return "\n".join(parts)[:4000]

        if name == "ollama_info":
            act = args.get("action", "list")
            if act == "list":
                return run_shell("ollama list")
            if act == "running":
                return run_shell("ollama ps")
            if act == "show":
                # "model" kommt aus einem LLM-Tool-Argument, nicht aus einer
                # festen Vorlage - deshalb NICHT run_shell() (shell=True):
                # argv-Liste + shell=False, das Argument wird nie von einer
                # Shell interpretiert (kein shlex.quote()-Escaping noetig
                # oder moeglich Windows-Umgehung, siehe Befund D).
                m = args.get("model", default_model)
                return run_argv(["ollama", "show", m])
            return _tool_policy_denial("unsupported_action", "BLOCKIERT: Ollama-Aktion ist nicht verfügbar.")

        if name == "bach_command":
            if worker_task_binding is not None and args.get("handler") == "task":
                try:
                    return worker_task_binding.execute_task_command(args.get("operation", ""), args.get("args", []))
                except Exception:
                    return _tool_effect_unconfirmed()
            if not bach_app:
                return _tool_policy_denial("provider_unavailable", "BACH ist für diesen Werkzeugaufruf nicht verfügbar.")
            _HANDLER_ALIASES = {
                "kalender": "calendar", "kontakte": "contact",
                "contacts": "contact", "routinen": "routine",
                "routines": "routine", "notes": "denkarium",
                "timers": "timer", "counters": "countdown",
                "lessons": "lesson", "partners": "partner",
                "agents": "agent", "messages": "msg",
            }
            h = args.get("handler", "")
            h = _HANDLER_ALIASES.get(h, h)
            if h not in BACH_COMMAND_HANDLERS:
                return _tool_policy_denial("handler_not_allowed", "BLOCKIERT: BACH-Handler ist nicht freigegeben.")
            op = args.get("operation", "")
            ex = args.get("args", [])
            ok, out = bach_app.execute(h, op, ex)
            r = str(out)[:4000] if out else "(keine Ausgabe)"
            return r if ok else _tool_effect_unconfirmed()

        if name == "get_datetime":
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")

        if name == "safe_shell":
            cmd = args.get("command", "")
            if not isinstance(cmd, str) or not cmd:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Befehl fehlt oder ist ungültig.")
            if not is_safe_command(cmd):
                return _tool_policy_denial("command_not_authorized", "BLOCKIERT: Befehl ist nicht in der Safe-Liste.")
            if is_blocked(cmd):
                return _tool_policy_denial("command_not_authorized", "BLOCKIERT: Befehl ist aus Sicherheitsgründen gesperrt.")
            try:
                tokens = [safe_exec.dequote(t) for t in safe_exec.tokenize(cmd)]
            except safe_exec.CommandRejected as e:
                return _tool_policy_denial("command_not_authorized", "BLOCKIERT: Befehl ist aus Sicherheitsgründen gesperrt.")
            reason = check_safe_shell_args(tokens)
            if reason:
                return _tool_policy_denial("command_not_authorized", "BLOCKIERT: Befehl ist aus Sicherheitsgründen gesperrt.")
            if worker_task_binding is not None:
                from hub._services.chat.worker_write_guard import authorize_safe_read, run_bound_check
                try:
                    if args.get("cwd"):
                        return run_bound_check(worker_task_binding, cmd, args.get("cwd"), safe=True)
                    # Read-only analysis does not create or mutate a task tree.
                    # It still requires the current private lease; the existing
                    # shell allowlist, tokenization, and path/secret checks above
                    # remain mandatory.
                    authorize_safe_read(worker_task_binding)
                    return run_shell_restricted(cmd, allowed=SAFE_BASES)
                except Exception as e:
                    return _tool_effect_unconfirmed()
            return run_shell_restricted(cmd, allowed=SAFE_BASES)
        if name == "execute_command":
            if mode != "full":
                return _tool_policy_denial("mode_not_authorized", "BLOCKIERT: Dieses Werkzeug benötigt den Full-Modus.")
            cmd = args.get("command", "")
            t = int(args.get("timeout", CMD_TIMEOUT))
            if is_blocked(cmd):
                return _tool_policy_denial("command_not_authorized", "BLOCKIERT: Befehl ist aus Sicherheitsgründen gesperrt.")
            if worker_task_binding is not None:
                from hub._services.chat.worker_write_guard import run_bound_check
                try:
                    return run_bound_check(worker_task_binding, cmd, args.get("cwd"), t)
                except Exception as e:
                    return _tool_effect_unconfirmed()
            from hub.worker_git import is_live_path_blocked
            cmd_lower = cmd.lower()
            if any(git_mut in cmd_lower for git_mut in ["git commit", "git checkout -b", "git merge", "git push", "git rebase"]):
                cwd = args.get("cwd") or args.get("path") or "."
                if not any(token in cmd for token in ["bach-worktrees", "task-"]):
                    if is_live_path_blocked(cwd):
                        return _tool_policy_denial("path_not_authorized", "BLOCKIERT: Ausführungspfad ist nicht freigegeben.")
            log.info("FULL-CMD: execution requested (payload omitted)")
            return run_shell_restricted(cmd, t, allowed=None)

        if name == "start_task_worktree":
            from hub.worker_git import start_task_worktree
            tid = args.get("task_id")
            try:
                private = ({"worker_task_binding": worker_task_binding,
                            "require_task_binding": require_task_binding}
                           if worker_task_binding is not None or require_task_binding else {})
                if task_code_capability:
                    private["task_code_capability"] = True
                wt = start_task_worktree(tid, **private)
                return f"Worktree erstellt: {wt}"
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "finish_task":
            from hub.worker_git import finish_task
            tid = args.get("task_id")
            msg = args.get("message", "")
            is_wip = bool(args.get("is_wip", False))
            try:
                private = ({"worker_task_binding": worker_task_binding,
                            "require_task_binding": require_task_binding}
                           if worker_task_binding is not None or require_task_binding else {})
                res = finish_task(tid, msg, is_wip=is_wip, **private)
                return json.dumps(res, ensure_ascii=False)
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "cleanup_task_worktree":
            from hub.worker_git import cleanup_task_worktree
            tid = args.get("task_id")
            try:
                private = ({"worker_task_binding": worker_task_binding,
                            "require_task_binding": require_task_binding}
                           if worker_task_binding is not None or require_task_binding else {})
                ok = cleanup_task_worktree(tid, **private)
                return f"Worktree aufgeräumt: {ok}"
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "write_file":
            if mode != "full":
                return _tool_policy_denial("mode_not_authorized", "BLOCKIERT: Dieses Werkzeug benötigt den Full-Modus.")
            p = args.get("path", "")
            c = args.get("content", "")
            if not p:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Ein gültiger Pfad ist erforderlich.")
            from hub.worker_git import is_live_path_blocked
            if err := is_live_path_blocked(p):
                return _tool_policy_denial("write_path_denied", "BLOCKIERT: Schreibpfad nicht freigegeben.")
            if worker_task_binding is not None:
                from hub._services.chat.worker_write_guard import authorize_mutation
                try:
                    _, (target_file,) = authorize_mutation(worker_task_binding, paths=(p,))
                    p = str(target_file)
                    authorize_mutation(worker_task_binding, paths=(target_file.parent,))
                except Exception as e:
                    return _tool_policy_denial("write_path_denied", "BLOCKIERT: Task-Schreibpfad nicht bestätigt.")
            try:
                Path(p).parent.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001 -- Filesystem operation may have started; report a bounded unknown effect.
                return _tool_effect_unconfirmed()
            if worker_task_binding is not None:
                try:
                    _, (target_file,) = authorize_mutation(worker_task_binding, paths=(p,))
                    p = str(target_file)
                except Exception as e:
                    return _tool_effect_unconfirmed()
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(c)
            except Exception:  # noqa: BLE001 -- A write may be partial; suppress exception details and report unknown.
                return _tool_effect_unconfirmed()
            log.info(f"WRITE: {p} ({len(c)} chars)")
            return f"Geschrieben: {p} ({len(c)} Zeichen)"

        if name == "web_search":
            query = args.get("query", "")
            if not query:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Suchanfrage fehlt.")
            max_r = min(int(args.get("max_results", 5)), 10)
            try:
                from duckduckgo_search import DDGS
                results = DDGS().text(query, max_results=max_r)
                if not results:
                    return f"Keine Ergebnisse für: {query}"
                out = []
                for r in results:
                    title = r.get("title", "")
                    href = r.get("href", "")
                    body = r.get("body", "")[:300]
                    out.append(f"**{title}**\n{href}\n{body}")
                return "\n\n".join(out)[:4000]
            except ImportError:
                return _tool_policy_denial("provider_unavailable", "Web-Suche ist nicht verfügbar.")
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "task_manage":
            if worker_task_binding is not None:
                if not isinstance(args, dict):
                    _log_bound_task_manage_denial("arguments", worker_task_binding, args)
                    return ToolErrorText("Ungültige Task-Werkzeugargumente.", code="invalid_task_arguments")
                action = args.get("action", "list")
                if not isinstance(action, str):
                    _log_bound_task_manage_denial("arguments", worker_task_binding, args)
                    return ToolErrorText("Taskaktion muss Text sein.", code="invalid_task_arguments")
                if action not in ("list", "detail", "done", "submit_result", "update", "decompose", "add"):
                    _log_bound_task_manage_denial("arguments", worker_task_binding, args)
                    return _tool_policy_denial("unsupported_action", "BLOCKIERT: Taskaktion wird nicht unterstützt.")
                partial = False
                # Review children submit a structured verdict, not work; the flag is not theirs.
                completion = getattr(worker_task_binding, "_review_grant", None) is None and (
                    action in ("done", "submit_result")
                    or (action == "update" and args.get("status") in ("done", "completed")))
                if action in ("done", "submit_result"):
                    if type(args.get("task_id")) is not int:
                        _log_bound_task_manage_denial("task_id_type", worker_task_binding, args)
                        return ToolErrorText("task_id muss eine numerische Ganzzahl sein.", code="invalid_task_arguments")
                    try:
                        max_chars = worker_task_binding.task_snapshot().get("result_max_chars")
                    except Exception as exc:  # noqa: BLE001 -- Failed task preflight must fail closed before dispatch.
                        _log_bound_task_manage_denial("submission_exception", worker_task_binding, args, exc)
                        return ToolErrorText("Taskoperation nicht bestätigt; Taskbindung prüfen.", code="task_preflight_unavailable")
                    try:
                        from hub._services.task_result_service import validate_submission
                        # Reuse canonical result checks without exposing private worker state.
                        validate_submission(
                            {"generation": "argument-validation", "result": args.get("result")},
                            max_chars=max_chars,
                        )
                    except ValueError as exc:
                        _log_bound_task_manage_denial("submission_validation", worker_task_binding, args, exc)
                        return _invalid_result_text(exc)
                    except Exception as exc:
                        _log_bound_task_manage_denial("submission_exception", worker_task_binding, args, exc)
                        return ToolErrorText("Taskoperation nicht bestätigt; Taskbindung prüfen.", code="task_preflight_unavailable")
                if completion:
                    # BACH #2210: after the public argument checks, a model must state
                    # explicitly whether the work is complete.
                    complete = args.get("complete")
                    if type(complete) is not bool:
                        _log_bound_task_manage_denial("completion_flag", worker_task_binding, args)
                        return ToolErrorText(_COMPLETE_FLAG_HINT, code="invalid_task_arguments")
                    partial = complete is False
                    if partial and action == "update":
                        # The done alias skipped the public result check above.
                        try:
                            from hub._services.task_result_service import validate_submission
                            validate_submission({"generation": "argument-validation", "result": args.get("result")},
                                                max_chars=worker_task_binding.task_snapshot().get("result_max_chars"))
                        except ValueError as exc:
                            _log_bound_task_manage_denial("submission_validation", worker_task_binding, args, exc)
                            return _invalid_result_text(exc)
                        except Exception as exc:
                            _log_bound_task_manage_denial("submission_exception", worker_task_binding, args, exc)
                            return ToolErrorText("Taskoperation nicht bestätigt; Taskbindung prüfen.", code="task_preflight_unavailable")
                    args = {key: value for key, value in args.items() if key != "complete"}
                try:
                    if partial:
                        response = _return_partial_state(worker_task_binding, args)
                    else:
                        response = worker_task_binding.execute_task_manage(args, _dispatch_marked=True)
                    # The operation has released its binding lock. Git must not
                    # run inside the submission transaction or controller lock.
                    try:
                        worker_task_binding.capture_confirmed_scope()
                    except Exception:
                        # Optional evidence must never hide a confirmed ACK.
                        pass
                    return response
                except WorkerResultLimitLockedError as exc:
                    _log_bound_task_manage_denial("dispatch", worker_task_binding, args, exc)
                    # This bounded policy denial is safe to explain and leaves the lease active.
                    return ToolErrorText(WorkerResultLimitLockedError.user_message, code="task_result_limit_locked")
                except LeaseSelfCheckRequiredError as exc:
                    _log_bound_task_manage_denial("dispatch", worker_task_binding, args, exc)
                    return ToolErrorText(LeaseSelfCheckRequiredError.user_message, code="invalid_task_result")
                except WorkerTaskManageArgumentError as exc:
                    _log_bound_task_manage_denial("arguments", worker_task_binding, args, exc)
                    return ToolErrorText(exc.user_message, code="invalid_task_arguments")
                except Exception as exc:
                    _log_bound_task_manage_denial("dispatch", worker_task_binding, args, exc)
                    # The task operation may have applied before the acknowledgement was lost.
                    return ToolErrorText("Taskoperation nicht bestätigt; Taskbindung prüfen.", code="task_operation_unconfirmed")
            if require_task_binding:
                return ToolErrorText("Taskbindung fehlt; Taskoperation nicht ausgeführt.", code="task_binding_required")
            if args.get("action") == "done" and args.get("result") is not None:
                return _tool_policy_denial("task_binding_required", "Taskergebnis braucht eine gebundene Worker-Task; Abschluss nicht ausgeführt.")
            action = args.get("action", "list")
            runtime_db = _current_runtime_db()
            task_audit_fn = _current_apply_task_field_changes()
            try:
                conn = sqlite3.connect(runtime_db)
                conn.row_factory = sqlite3.Row
                try:
                    if action == "list":
                        rows = conn.execute(
                            "SELECT id, title, priority, status FROM tasks "
                            "WHERE status IN ('pending','in-progress') "
                            "ORDER BY priority, id DESC LIMIT 20"
                        ).fetchall()
                        if not rows:
                            return "Keine offenen Tasks."
                        lines = [f"[{r['id']}] {r['priority']} {r['status']}: {r['title']}" for r in rows]
                        return "\n".join(lines)

                    if action == "add":
                        title = args.get("title", "")
                        if not isinstance(title, str) or not title.strip():
                            return _tool_policy_denial("invalid_arguments", "Kein Titel angegeben")
                        prio = args.get("priority", "P3")
                        assignee = args.get("assigned_to") or "bach"
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        values = {"title": title, "description": args.get("description", ""),
                            "category": args.get("category", ""), "depends_on": args.get("depends_on", ""),
                            "priority": prio, "status": "pending", "assigned_to": assignee,
                            "created_at": now, "updated_at": now, **_task_route_fields(conn, args)}
                        if "result_max_chars" in args:
                            from hub._services.task_result_service import validate_submission
                            try:
                                validate_submission({"generation": "argument-validation", "result": "x"},
                                                    max_chars=args["result_max_chars"])
                            except ValueError as exc:
                                return ToolErrorText(str(exc), code="invalid_task_arguments")
                            from hub._services.task_schema import ensure_task_result_contract_columns
                            ensure_task_result_contract_columns(conn)
                            values["result_max_chars"] = args["result_max_chars"]
                        cur = conn.execute("INSERT INTO tasks (" + ", ".join(values) + ") VALUES ("
                            + ", ".join("?" for _ in values) + ")", list(values.values()))
                        conn.commit()
                        zusatz = f" [{args['category']}]" if args.get("category") else ""
                        return f"Task #{cur.lastrowid} erstellt: {title} ({prio}){zusatz}"

                    if action == "done":
                        tid = args.get("task_id")
                        if type(tid) is not int or tid <= 0:
                            return _tool_policy_denial("invalid_arguments", "Keine Task-ID angegeben")
                        # Serialisiere Lesen und Statuswechsel. Ohne die Schreibtransaktion
                        # könnten zwei Worker gleichzeitig einen offenen Status lesen und
                        # beide einen erfolgreichen Abschlussbeleg ausstellen.
                        conn.execute("BEGIN IMMEDIATE")
                        existing = conn.execute(
                            "SELECT * FROM tasks WHERE id=?", (tid,)
                        ).fetchone()
                        if not existing:
                            return _tool_policy_denial("resource_not_found", f"Task #{tid} nicht gefunden")
                        if str(existing["status"] or "").strip().lower() in COMPLETED_STATUSES:
                            return _tool_policy_denial("state_conflict", f"Task #{tid} war bereits erledigt.")
                        from hub._services.task_result_service import ResultConflict, assert_completion_allowed
                        try:
                            assert_completion_allowed(conn, tid)
                        except ResultConflict as exc:
                            conn.rollback()
                            return _tool_policy_denial("state_conflict", f"Task #{tid} nicht erledigt: {exc}")
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if task_audit_fn is not None:
                            # T-20260906-833218904: schliesst dieselbe task_history-Luecke
                            # wie server.py/headless.py/task.py -- 'done' zaehlt ueber
                            # hub.task_audit.COMPLETED_STATUSES als Abschluss.
                            task_audit_fn(conn, tid, dict(existing), {"status": "done"},
                                          changed_by="chat-runtime", now=now)
                        else:
                            # Fallback: identischer sys.path-Vorbehalt wie RUNTIME_BACH_DB
                            # oben -- Aktion soll auch ohne hub.task_audit funktionieren,
                            # nur ohne Audit-Trail.
                            conn.execute(
                                "UPDATE tasks SET status='done', completed_at=?, updated_at=? WHERE id=?",
                                (now, now, tid)
                            )
                        conn.commit()
                        return f"Task #{tid} erledigt."

                    if action == "detail":
                        tid = args.get("task_id")
                        if type(tid) is not int or tid <= 0:
                            return _tool_policy_denial("invalid_arguments", "Keine Task-ID angegeben")
                        row = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
                        if not row:
                            return _tool_policy_denial("resource_not_found", f"Task #{tid} nicht gefunden")
                        return "\n".join(f"{k}: {row[k]}" for k in row.keys())

                    if action == "update":
                        tid = args.get("task_id")
                        if type(tid) is not int or tid <= 0:
                            return _tool_policy_denial("invalid_arguments", "Keine Task-ID angegeben")
                        existing = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
                        if not existing:
                            return _tool_policy_denial("resource_not_found", f"Task #{tid} nicht gefunden")
                        updates = {}
                        for fld in ("title", "description", "category", "priority", "status", "depends_on", "assigned_to"):
                            if fld in args and args[fld] is not None:
                                updates[fld] = args[fld]
                        if "result_max_chars" in args:
                            from hub._services.task_result_service import validate_submission
                            try:
                                validate_submission({"generation": "argument-validation", "result": "x"},
                                                    max_chars=args["result_max_chars"])
                            except ValueError as exc:
                                return ToolErrorText(str(exc), code="invalid_task_arguments")
                            from hub._services.task_schema import ensure_task_result_contract_columns
                            ensure_task_result_contract_columns(conn)
                            updates["result_max_chars"] = args["result_max_chars"]
                        updates.update(_task_route_fields(conn, args))
                        if not updates:
                            return _tool_policy_denial("no_updates", "Keine Felder zum Aktualisieren angegeben")
                        if str(updates.get("status") or "").strip().lower() in COMPLETED_STATUSES:
                            from hub._services.task_result_service import ResultConflict, assert_completion_allowed
                            conn.execute("BEGIN IMMEDIATE")
                            try:
                                assert_completion_allowed(conn, tid, changes=updates)
                            except ResultConflict as exc:
                                conn.rollback()
                                return _tool_policy_denial("state_conflict", f"Task #{tid} nicht aktualisiert: {exc}")
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if task_audit_fn is not None:
                             # T-20260916-1330 (TRANSFER-09 / #1235 Resurrektion-Bypass):
                             # Der Terminal-Park-Guard im Choke-Point blockiert einen
                             # Reopen auf open|pending|in_progress fuer einen gate-geparkten
                             # Task. Das Agent-Tool darf den Task NICHT resurrektieren
                             # (Fail-Closed) -- stattdessen klare Meldung, damit der
                             # Operator bei Bedarf via CLI `reopen`/`unblock` (allow_reopen)
                             # oder GUI explicit wieder oeffnet.
                            try:
                                task_audit_fn(conn, tid, dict(existing), updates,
                                              changed_by="chat-runtime", now=now)
                            except GateReopenBlocked as exc:
                                conn.rollback()
                                return _tool_policy_denial("state_conflict", f"[WARN] Task #{tid} ist terminal geparkt (Gate-Haltefrist) -- Reopen blockiert: {exc}. Fuer einen bewussten Reopen `bach task reopen {tid}` (oder unblock) nutzen.")
                        else:
                            updates["updated_at"] = now
                            set_str = ", ".join(f"{k}=?" for k in updates.keys())
                            conn.execute(f"UPDATE tasks SET {set_str} WHERE id=?", list(updates.values()) + [tid])
                        conn.commit()
                        return f"Task #{tid} aktualisiert: {', '.join(updates.keys())}"

                    if action == "decompose":
                        tid = args.get("task_id")
                        subtasks = args.get("subtasks", [])
                        if type(tid) is not int or tid <= 0 or not isinstance(subtasks, list) or not subtasks:
                            return _tool_policy_denial("invalid_arguments", "task_id und subtasks (Liste von Objekten mit title, description) erforderlich")
                        if any(
                            not isinstance(st, dict)
                            or not isinstance(st.get("title"), str)
                            or not st["title"].strip()
                            or not isinstance(st.get("description", ""), str)
                            for st in subtasks
                        ):
                            return _tool_policy_denial("invalid_arguments", "Task nicht zerlegt: jede Teilaufgabe braucht einen nicht leeren Titel und eine Textbeschreibung.")
                        if "close_parent" in args and type(args["close_parent"]) is not bool:
                            return _tool_policy_denial("invalid_arguments", "Task nicht zerlegt: close_parent muss true oder false sein.")
                        # Lesen, Teilaufgaben und Elternabschluss bilden eine
                        # Transaktion; konkurrierende Worker sehen den neuen Status.
                        conn.execute("BEGIN IMMEDIATE")
                        parent = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
                        if not parent:
                            return _tool_policy_denial("resource_not_found", f"Task #{tid} nicht gefunden")
                        if str(parent["status"] or "").strip().lower() not in {
                            "open", "pending", "in_progress", "in-progress",
                        }:
                            return _tool_policy_denial("state_conflict", f"Task #{tid} nicht zerlegt: Eltern-Task ist nicht offen.")
                        if args.get("close_parent", True):
                            from hub._services.task_result_service import ResultConflict, assert_completion_allowed
                            try:
                                assert_completion_allowed(conn, tid, changes={"status": "completed"})
                            except ResultConflict as exc:
                                conn.rollback()
                                return _tool_policy_denial("state_conflict", f"Task #{tid} nicht zerlegt: {exc}")
                        parent_dict = dict(parent)
                        p_desc = str(parent_dict.get("description") or "")
                        p_title = str(parent_dict.get("title") or "").strip()
                        if (
                            "[Teilaufgabe zu #" in p_desc
                            or ("[In " in p_desc and "Teilaufgaben zerlegt" in p_desc)
                            or p_title.lower().startswith(("edit: ", "folge-task: ", "subtask: "))
                        ):
                            conn.rollback()
                            return _tool_policy_denial("state_conflict", f"Task #{tid} ('{p_title}') ist bereits eine Teilaufgabe oder wurde bereits zerlegt und kann nicht weiter rekursiv aufgeteilt werden. Bitte führe die Aufgabe direkt im Code aus oder aktualisiere sie mit action='update'.")
                        cat = args.get("category") or parent_dict.get("category") or ""
                        assignee = args.get("assigned_to") or parent_dict.get("assigned_to") or "bach"
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        created_ids = []
                        prev_id = None
                        for st in subtasks:
                            st_title = st["title"].strip()
                            st_desc = st.get("description", "")
                            if f"[Teilaufgabe zu #{tid}]" not in st_desc:
                                st_desc = f"[Teilaufgabe zu #{tid}] {st_desc}".strip()
                            st_prio = st.get("priority", parent_dict.get("priority") or "P3")
                            st_dep = st.get("depends_on") or (str(prev_id) if (args.get("sequential") and prev_id) else "")
                            st_assignee = st.get("assigned_to") or assignee
                            routing = {key: args[key] for key in ("assigned_slot", "required_model") if key in args}
                            routing.update({key: st[key] for key in ("assigned_slot", "required_model") if key in st})
                            values = {"title": st_title, "description": st_desc, "category": cat,
                                "depends_on": st_dep, "priority": st_prio, "status": "pending",
                                "assigned_to": st_assignee, "created_at": now, "updated_at": now,
                                **_task_route_fields(conn, routing)}
                            cap_present = ("result_max_chars" in st or "result_max_chars" in args
                                           or "result_max_chars" in parent_dict)
                            if cap_present:
                                cap = st.get("result_max_chars", args.get(
                                    "result_max_chars", parent_dict.get("result_max_chars")))
                                from hub._services.task_result_service import validate_submission
                                try:
                                    validate_submission({"generation": "argument-validation", "result": "x"},
                                                        max_chars=cap)
                                except ValueError as exc:
                                    conn.rollback()
                                    return ToolErrorText(str(exc), code="invalid_task_arguments")
                                from hub._services.task_schema import ensure_task_result_contract_columns
                                ensure_task_result_contract_columns(conn)
                                values["result_max_chars"] = cap
                            cur = conn.execute("INSERT INTO tasks (" + ", ".join(values) + ") VALUES ("
                                + ", ".join("?" for _ in values) + ")", list(values.values()))
                            prev_id = cur.lastrowid
                            created_ids.append(prev_id)
                        if not created_ids:
                            # Ohne angelegte Teilaufgabe ist nichts zerlegt: den
                            # Eltern-Task nicht schliessen, sonst verschwindet
                            # Arbeit ohne Nachfolger aus dem offenen Pool.
                            conn.rollback()
                            return _tool_policy_denial("invalid_arguments", f"Task #{tid} nicht zerlegt: keine Teilaufgabe mit Titel angegeben. subtasks braucht Objekte mit title und description.")
                        if args.get("close_parent", True):
                            note = f"\n[In {len(created_ids)} Teilaufgaben zerlegt: {created_ids}]"
                            if task_audit_fn is not None:
                                task_audit_fn(conn, tid, parent_dict,
                                              {"status": "completed",
                                               "description": (parent_dict.get("description") or "") + note},
                                              changed_by="chat-runtime", now=now)
                            else:
                                conn.execute(
                                    "UPDATE tasks SET status='completed', description=COALESCE(description, '') || ?, "
                                    "completed_at=?, updated_at=? WHERE id=?",
                                    (note, now, now, tid)
                                )
                        conn.commit()
                        return f"Task #{tid} in {len(created_ids)} Teilaufgaben zerlegt: IDs {created_ids}"

                    return _tool_policy_denial("unsupported_action", f"Unbekannte Aktion: {action}")
                finally:
                    conn.close()
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "maintain":
            action = args.get("action", "check")
            operation = args.get("operation", "")
            try:
                if action == "check":
                    base = str(Path(__file__).parent.parent.parent.parent)
                    if base not in sys.path:
                        sys.path.insert(0, base)
                    from hub._services.recurring.recurring_tasks import list_recurring_tasks
                    tasks = list_recurring_tasks()
                    if not tasks:
                        return "Keine wiederkehrenden Tasks konfiguriert."
                    lines = []
                    for tid, info in tasks.items():
                        status = info.get("status", "?")
                        due = info.get("next_due", "?")
                        text = info.get("task_text", tid)[:60]
                        marker = "🔴 FÄLLIG" if status == "overdue" else ("🟡 bald" if status == "due_soon" else "✅")
                        lines.append(f"{marker} {tid}: {text} (nächst: {due})")
                    return "\n".join(lines)
                elif action == "run":
                    if not operation:
                        return "Bitte 'operation' angeben: registry, skills, docs, backup, clean, memory, recurring"
                    op_map = {
                        "registry": "maintain registry",
                        "skills": "maintain skills",
                        "docs": "maintain docs report",
                        "backup": "backup status",
                        "clean": "maintain clean",
                        "memory": "mem gc",
                        "recurring": "recurring check",
                    }
                    cmd = op_map.get(operation)
                    if not cmd:
                        return _tool_policy_denial("unsupported_action", "BLOCKIERT: Wartungsoperation ist nicht verfügbar.")
                    parts = cmd.split()
                    handler, op_args = parts[0], " ".join(parts[1:])
                    return run_shell(f"cd {shlex.quote(str(Path(__file__).parent.parent.parent.parent))} && "
                                     f"PYTHONIOENCODING=utf-8 python bach.py --{handler} {op_args}", 60)
                elif action == "health":
                    return run_shell(f"cd {shlex.quote(str(Path(__file__).parent.parent.parent.parent))} && "
                                     f"PYTHONIOENCODING=utf-8 python bach.py status", 60)
                elif action == "services":
                    http_checks = {
                        "GUI Dashboard (:8000)": "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8000/",
                        "Ollama (:11434)": "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:11434/api/tags",
                    }
                    proc_checks = {
                        "Telegram Bot": "telegram_chat",
                        "GUI Server": "gui/server\\.py",
                        "Chat Tray": "chat_tray",
                    }
                    lines = ["BACH Service-Check:"]
                    lines.append("  ✅ Control API (:8081) — läuft (diese Anfrage)")
                    for svc, cmd in http_checks.items():
                        code = run_shell(cmd)
                        if isinstance(code, ToolErrorText):
                            return code
                        code = code.strip()
                        ok = code == "200"
                        lines.append(f"  {'✅' if ok else '❌'} {svc} — HTTP {code}")
                    for svc, pattern in proc_checks.items():
                        ps_out = run_shell(f"pgrep -f '{pattern}' 2>/dev/null")
                        if isinstance(ps_out, ToolErrorText):
                            return ps_out
                        ps_out = ps_out.strip()
                        if ps_out:
                            pids = ps_out.replace('\n', ', ')
                            lines.append(f"  ✅ {svc} — PID {pids}")
                        else:
                            lines.append(f"  ❌ {svc} — nicht gefunden")
                    uptime = run_shell('uptime')
                    if isinstance(uptime, ToolErrorText):
                        return uptime
                    lines.append(f"  Uptime: {uptime.strip()}")
                    return "\n".join(lines)
                elif action == "sync":
                    sync_script = Path.home() / "services" / "bach" / "sync_mirror.sh"
                    if not sync_script.exists():
                        return "Sync-Script nicht gefunden: ~/services/bach/sync_mirror.sh"
                    out = run_shell(f"bash {sync_script} 2>&1")
                    if isinstance(out, ToolErrorText):
                        return out
                    return f"OneDrive → Mirror Sync abgeschlossen.\n{out.strip()}" if out.strip() else "OneDrive → Mirror Sync abgeschlossen (keine Änderungen)."
                else:
                    return _tool_policy_denial("unsupported_action", "BLOCKIERT: Wartungsaktion ist nicht verfügbar.")
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "foerderbericht":
            action = args.get("action", "status")
            try:
                base = str(Path(__file__).parent.parent.parent.parent)
                if base not in sys.path:
                    sys.path.insert(0, base)
                from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline
                pipeline = FoerderberichtPipeline()
                lock_file = pipeline.base_path / ".pipeline_lock"

                if action == "status":
                    data_roh = pipeline.base_path / "data_roh"
                    client_count = (
                        len([d for d in data_roh.iterdir() if d.is_dir()])
                        if data_roh.exists() else 0
                    )
                    prompt_exists = (pipeline.base_path / "data_bundled" / "prompt.txt").exists()
                    state = "Pipeline läuft." if lock_file.exists() else "Pipeline bereit."
                    status = state + "\n"
                    status += f"Akte erkannt: {'ja' if client_count else 'nein'} ({client_count} Ordner)\n"
                    status += f"Anonymisierter Prompt vorhanden: {'ja' if prompt_exists else 'nein'}"
                    return status

                elif action == "prepare":
                    zeitraum = args.get("zeitraum", "01.01.2025 - 31.12.2025")
                    eltern = args.get("eltern")
                    adresse = args.get("adresse")
                    result = pipeline.prepare_prompt(
                        berichtszeitraum=zeitraum,
                        parent_names=eltern,
                        client_address=adresse,
                    )
                    if result.success:
                        return (f"Phase 1 abgeschlossen. Tarnname: {result.tarnname}\n"
                                f"Anonymisierter Prompt bereit.\n"
                                f"Dauer: {result.duration_s:.1f}s\nSchritte: {', '.join(result.steps_completed)}")
                    return _tool_effect_unconfirmed()

                elif action == "cleanup":
                    for folder in ["data_ano", "data_bundled"]:
                        p = pipeline.base_path / folder
                        if p.exists():
                            import shutil
                            shutil.rmtree(p)
                            p.mkdir()
                    if lock_file.exists():
                        lock_file.unlink()
                    return "Zwischendateien gelöscht (data_ano/, data_bundled/), Lock entfernt."

                return _tool_policy_denial("unsupported_action", "BLOCKIERT: Berichtaktion ist nicht verfügbar.")
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "delegate":
            target = args.get("target", "")
            prompt = args.get("prompt", "")
            context = args.get("context", "")
            if target not in ("claude", "codex"):
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Delegationsziel ist ungültig.")
            if not prompt:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Delegationsanfrage fehlt.")
            depth = int(os.environ.get("BACH_DELEGATION_DEPTH", "0"))
            if depth >= 2:
                return _tool_policy_denial("state_conflict", "BLOCKIERT: Maximale Delegationstiefe erreicht.")
            full_prompt = prompt
            if context:
                full_prompt = f"Kontext: {context}\n\nAufgabe: {prompt}"
            env = {**os.environ, "PYTHONIOENCODING": "utf-8",
                   "BACH_DELEGATION_DEPTH": str(depth + 1)}
            log.info("DELEGATE: execution requested (payload omitted)")
            if target == "claude":
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    kf = Path.home() / ".credentials" / "anthropic_api_key"
                    if kf.exists():
                        api_key = kf.read_text(encoding="utf-8").strip()
                if api_key:
                    return _delegate_claude_api(full_prompt, api_key)
                cmd = ["claude", "-p", full_prompt]
            else:
                cmd = ["codex", "exec", full_prompt]
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=limit("BACH_DELEGATE_TIMEOUT"),
                    stdin=subprocess.DEVNULL, env=env,
                )
                if r.returncode != 0:
                    return _tool_effect_unconfirmed()
                out = (r.stdout or "").strip()
                return (out or "(keine Ausgabe)")[:3000]
            except subprocess.TimeoutExpired:
                return _tool_effect_unconfirmed()
            except FileNotFoundError:
                return _tool_policy_denial("provider_unavailable", "Delegationsanbieter ist nicht verfügbar.")
            except Exception:  # noqa: BLE001 -- Delegation may have run; suppress backend details and report unknown.
                return _tool_effect_unconfirmed()

        if name == "weather":
            location = args.get("location", "")
            if not location:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Ein Ort ist erforderlich.")
            try:
                from hub._services.weather.weather_service import get_weather_text
                parts = location.replace(" ", "").split(",")
                if len(parts) == 2:
                    try:
                        lat, lon = float(parts[0]), float(parts[1])
                        return get_weather_text(lat, lon)
                    except ValueError:
                        pass
                url = f"https://wttr.in/{urllib.parse.quote(location)}?format=j1&lang=de"
                req = urllib.request.Request(url, headers={"User-Agent": "BACH/1.0"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                cc = data["current_condition"][0]
                area = data.get("nearest_area", [{}])[0]
                area_name = area.get("areaName", [{}])[0].get("value", location)
                country = area.get("country", [{}])[0].get("value", "")
                desc = cc.get("lang_de", [{}])
                desc_text = desc[0].get("value", cc.get("weatherDesc", [{}])[0].get("value", "")) if desc else cc.get("weatherDesc", [{}])[0].get("value", "")
                temp = cc.get("temp_C", "?")
                feels = cc.get("FeelsLikeC", "?")
                hum = cc.get("humidity", "?")
                wind = cc.get("windspeedKmph", "?")
                return (f"Wetter in {area_name}, {country}:\n"
                        f"Temperatur: {temp}°C (gefühlt: {feels}°C) | {desc_text}\n"
                        f"Wind: {wind} km/h | Luftfeuchtigkeit: {hum}%")
            except Exception as e:
                return _tool_effect_unconfirmed()

        if name == "edit_file":
            p = args.get("path", "")
            old_text = args.get("old_text", "")
            new_text = args.get("new_text", "")
            if not p or not old_text:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Pfad und Suchtext sind erforderlich.")
            from hub.worker_git import is_live_path_blocked
            if is_live_path_blocked(p):
                return _tool_policy_denial("path_not_authorized", "BLOCKIERT: Schreibpfad ist nicht freigegeben.")
            if is_safe_write_path(p, mode):
                if mode == "plan":
                    return _tool_policy_denial("mode_not_authorized", "BLOCKIERT: Schreibzugriff ist im Planmodus nicht freigegeben.")
                return _tool_policy_denial("write_path_denied", "BLOCKIERT: Schreibpfad ist nicht freigegeben.")
            if worker_task_binding is not None:
                from hub._services.chat.worker_write_guard import authorize_mutation
                try:
                    _, (target_file,) = authorize_mutation(worker_task_binding, paths=(p,))
                    p = str(target_file)
                except Exception:  # noqa: BLE001 -- Path authorization uncertainty must remain denied.
                    return _tool_policy_denial("write_path_denied", "BLOCKIERT: Task-Schreibpfad nicht bestätigt.")
            try:
                content = Path(p).read_text(encoding="utf-8")
            except FileNotFoundError:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Quelldatei wurde nicht gefunden.")
            except Exception:  # noqa: BLE001 -- Suppress file-system details from the public result.
                return _tool_effect_unconfirmed()
            if old_text not in content:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Der angegebene Suchtext wurde nicht gefunden.")
            if args.get("all"):
                new_content = content.replace(old_text, new_text)
                count = content.count(old_text)
            else:
                new_content = content.replace(old_text, new_text, 1)
                count = 1
            try:
                if worker_task_binding is not None:
                    from hub._services.chat.worker_write_guard import authorize_mutation
                    _, (target_file,) = authorize_mutation(worker_task_binding, paths=(p,))
                    p = str(target_file)
                Path(p).write_text(new_content, encoding="utf-8")
                log.info(f"EDIT: {p} ({count}x ersetzt)")
                return f"Bearbeitet: {p} ({count} Ersetzung{'en' if count > 1 else ''})"
            except Exception:  # noqa: BLE001 -- An edit may be partial; suppress exception details and report unknown.
                return _tool_effect_unconfirmed()

        if name == "move_file":
            src = args.get("source", "")
            dst = args.get("destination", "")
            if not isinstance(src, str) or not isinstance(dst, str) or not src.strip() or not dst.strip():
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Quelle und Ziel müssen gültige Pfadtexte sein.")
            if chr(0) in src or chr(0) in dst:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Quelle oder Ziel enthält einen ungültigen Pfad.")
            if is_safe_write_path(src, mode) or is_safe_write_path(dst, mode):
                return _tool_policy_denial("write_path_denied", "BLOCKIERT: Quell- oder Zielpfad ist nicht freigegeben.")
            try:
                import shutil
                source_path, destination_path = _authorized_file_mutation_paths(
                    src, dst, worker_task_binding)
                source_stat = source_path.stat()
                source_identity = (source_stat.st_dev, source_stat.st_ino)
                source_is_directory = source_path.is_dir()
                # Re-authorize both paths immediately before the move sink.
                # This narrows the path-swap window but does not make it atomic.
                confirmed_source, confirmed_destination = _authorized_file_mutation_paths(
                    src, dst, worker_task_binding)
                if (confirmed_source, confirmed_destination) != (source_path, destination_path):
                    raise ValueError("Quelle oder Ziel wurde während der Pfadprüfung umgeleitet")
                confirmed_stat = confirmed_source.stat()
                if (confirmed_stat.st_dev, confirmed_stat.st_ino) != source_identity:
                    raise ValueError("Quelle wurde während der Pfadprüfung ersetzt")
                if confirmed_source.is_dir() != source_is_directory:
                    raise ValueError("Quelltyp änderte sich während der Pfadprüfung")
                shutil.move(str(confirmed_source), str(confirmed_destination))
                log.info("MOVE: Datei im geprüften BACH-Bereich verschoben")
                return f"Verschoben: {source_path} → {destination_path}"
            except Exception:  # noqa: BLE001 -- A move may be partial; suppress exception details and report unknown.
                return _tool_effect_unconfirmed()

        if name == "copy_file":
            src = args.get("source", "")
            dst = args.get("destination", "")
            if not isinstance(src, str) or not isinstance(dst, str) or not src.strip() or not dst.strip():
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Quelle und Ziel müssen gültige Pfadtexte sein.")
            if chr(0) in src or chr(0) in dst:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Quelle oder Ziel enthält einen ungültigen Pfad.")
            if is_safe_write_path(dst, mode):
                return _tool_policy_denial("write_path_denied", "BLOCKIERT: Zielpfad ist nicht freigegeben.")
            try:
                import shutil
                source_path, destination_path = _authorized_file_mutation_paths(
                    src, dst, worker_task_binding)
                source_is_directory = source_path.is_dir()
                # Re-resolve both raw caller paths immediately before the copy
                # sink; this catches a changed symlink/ancestor during dispatch.
                confirmed_source, confirmed_destination = _authorized_file_mutation_paths(
                    src, dst, worker_task_binding)
                if (confirmed_source, confirmed_destination) != (source_path, destination_path):
                    raise ValueError("Quelle oder Ziel wurde während der Pfadprüfung umgeleitet")
                if confirmed_source.is_dir() != source_is_directory:
                    raise ValueError("Quelltyp änderte sich während der Pfadprüfung")
                if source_is_directory:
                    shutil.copytree(
                        str(confirmed_source), str(confirmed_destination), symlinks=True)
                else:
                    shutil.copy2(
                        str(confirmed_source), str(confirmed_destination), follow_symlinks=False)
                log.info("COPY: Datei im geprüften BACH-Bereich kopiert")
                return f"Kopiert: {confirmed_source} → {confirmed_destination}"
            except Exception:  # noqa: BLE001 -- A copy may be partial; suppress exception details and report unknown.
                return _tool_effect_unconfirmed()

        if name == "file_info":
            p = args.get("path", "")
            if not p:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Ein Pfad ist erforderlich.")
            try:
                st = os.stat(p)
                import stat
                ftype = "Ordner" if stat.S_ISDIR(st.st_mode) else "Datei"
                size = st.st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                elif size < 1024 * 1024 * 1024:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size / (1024 * 1024 * 1024):.2f} GB"
                mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                ctime = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
                perms = oct(st.st_mode)[-3:]
                lines = [
                    f"Typ: {ftype}",
                    f"Pfad: {p}",
                    f"Größe: {size_str}",
                    f"Geändert: {mtime}",
                    f"Erstellt: {ctime}",
                    f"Rechte: {perms}",
                ]
                if ftype == "Ordner":
                    try:
                        entries = os.listdir(p)
                        lines.append(f"Einträge: {len(entries)}")
                    except PermissionError:
                        lines.append("Einträge: (keine Berechtigung)")
                return "\n".join(lines)
            except FileNotFoundError:
                return _tool_policy_denial("resource_not_found", "Datei oder Verzeichnis wurde nicht gefunden.")
            except Exception:  # noqa: BLE001 -- Suppress file-system details from the public result.
                return _tool_effect_unconfirmed()

        if name == "recycle":
            p = args.get("path", "")
            if not p:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Ein Datei-Pfad ist erforderlich.")
            if worker_task_binding is not None:
                from hub._services.chat.worker_write_guard import block_bound_recycle
                try:
                    block_bound_recycle(worker_task_binding)
                except Exception:  # noqa: BLE001 -- Recycle authorization uncertainty must remain denied.
                    return _tool_policy_denial("write_grant_denied", "BLOCKIERT: Papierkorboperationen sind für gebundene Worker gesperrt.")
            if is_safe_write_path(p, mode):
                return _tool_policy_denial("write_path_denied", "BLOCKIERT: Papierkorbpfad ist nicht freigegeben.")
            if not os.path.exists(p):
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Quelldatei wurde nicht gefunden.")
            try:
                trash = Path.home() / ".Trash"
                basename = Path(p).name
                dest = trash / basename
                if dest.exists():
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    dest = trash / f"{Path(basename).stem}_{ts}{Path(basename).suffix}"
                import shutil
                shutil.move(p, str(dest))
                log.info(f"RECYCLE: {p} -> {dest}")
                return f"In Papierkorb verschoben: {p}"
            except Exception:  # noqa: BLE001 -- Recycle may have run; suppress exception details and report unknown.
                return _tool_effect_unconfirmed()

        if name == "create_directory":
            p = args.get("path", "")
            if not p:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Ein Verzeichnispfad ist erforderlich.")
            if is_safe_write_path(p, mode):
                return _tool_policy_denial("write_path_denied", "BLOCKIERT: Verzeichnispfad ist nicht freigegeben.")
            if worker_task_binding is not None:
                from hub._services.chat.worker_write_guard import authorize_mutation
                try:
                    _, (target_dir,) = authorize_mutation(worker_task_binding, paths=(p,))
                    p = str(target_dir)
                except Exception:  # noqa: BLE001 -- Directory authorization uncertainty must remain denied.
                    return _tool_policy_denial("write_path_denied", "BLOCKIERT: Task-Verzeichnispfad nicht bestätigt.")
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001 -- Directory creation may have started; report unknown.
                return _tool_effect_unconfirmed()
            if worker_task_binding is not None:
                try:
                    authorize_mutation(worker_task_binding, paths=(p,))
                except Exception:  # noqa: BLE001 -- Post-create authorization failure cannot prove no effect.
                    return _tool_effect_unconfirmed()
            log.info("MKDIR: geprüftes Verzeichnis erstellt")
            return f"Ordner erstellt: {p}"

        if name == "web_fetch":
            url = args.get("url", "")
            if not url:
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Eine HTTP- oder HTTPS-URL ist erforderlich.")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                return _tool_policy_denial("invalid_arguments", "BLOCKIERT: Nur HTTP- und HTTPS-URLs sind erlaubt.")
            extract = args.get("extract_text", True)
            max_chars = min(int(args.get("max_chars", 4000)), 8000)
            try:
                # Use the existing provider seam with pinned public DNS,
                # redirect validation and response limits. Never fetch a
                # private Control API/cloud metadata address from tool input.
                from hub.web_scrape import WebScrapeHandler
                r, error = WebScrapeHandler(Path(BACH_SYSTEM_DIR))._request(url)
                if r is None:
                    return _tool_effect_unconfirmed()
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    return json.dumps(json.loads(r.text), indent=2, ensure_ascii=False)[:max_chars]
                text = r.text
                if extract and "html" in ct.lower():
                    try:
                        from lxml import html as lxml_html
                        doc = lxml_html.fromstring(text)
                        for el in doc.xpath("//script|//style|//noscript"):
                            el.getparent().remove(el)
                        text = doc.text_content()
                    except Exception:
                        text = re.sub(r"<[^>]+>", "", text)
                    text = re.sub(r"\n{3,}", "\n\n", text).strip()
                return text[:max_chars]
            except Exception:  # noqa: BLE001 -- Suppress provider details from the public result.
                return _tool_effect_unconfirmed()

        return _tool_policy_denial("tool_not_authorized", "BLOCKIERT: Unbekanntes Werkzeug.")
    except Exception:  # noqa: BLE001 -- Keep unexpected tool failures redacted and fail closed.
        return _tool_effect_unconfirmed()


# --- Chat Runtime ---

# --- Loop-Mode (/auto) -----------------------------------------------------
# Der Tool-Loop endet normalerweise, sobald das Modell eine Antwort ohne
# Werkzeugaufruf schickt - es fragt dann zurueck statt weiterzubauen. Im
# Loop-Mode wird stattdessen automatisch nachgeschoben.
def ist_fertig(antwort: str | None, fenster: int = 300) -> bool:
    """FERTIG am Anfang oder am Ende der Antwort.

    Die Auftraege verlangen FERTIG als Abschluss; nur den Anfang zu pruefen
    liess lange Abschlussberichte als offen gelten.
    """
    text = (antwort or "").upper()
    return "FERTIG" in text[:fenster] or "FERTIG" in text[-fenster:]


AUTO_NUDGE = (
    "Weiter. Frage nicht nach und warte nicht auf Bestaetigung - du arbeitest autonom. "
    "Baue oder erledige den naechsten offenen Punkt direkt. "
    "Erst wenn die Aufgabe vollstaendig erledigt ist, antworte mit dem Wort FERTIG."
)

HANDOFF_PROMPT = (
    "Dein Kontextfenster ist fast voll. Schreibe JETZT eine Uebergabe an dich "
    "selbst, damit du gleich mit leerem Kontext weiterarbeiten kannst. Du "
    "verlierst alles, was nicht in dieser Uebergabe steht - der Verlauf, die "
    "gelesenen Dateien, deine Zwischenergebnisse.\n\n"
    "Halte dich an dieses Format, kurz und konkret:\n"
    "AUFTRAG: <worum geht es, in einem Satz>\n"
    "ERLEDIGT: <was fertig ist, mit Dateinamen>\n"
    "STAND: <was gerade halb fertig ist>\n"
    "OFFEN: <was noch zu tun ist, in der Reihenfolge>\n"
    "GEPRUEFT: <welche Pruefbefehle laufen, mit Ergebnis>\n"
    "SACKGASSEN: <was du schon erfolglos versucht hast - damit du es nicht wiederholst>\n"
    "RESUME: <der naechste konkrete Befehl oder Schritt>\n\n"
    "Keine Erklaerungen, keine Hoeflichkeit, nur die Uebergabe."
)

GOAL_CHECK = (
    "Bevor du fertig bist, pruefe streng gegen dieses Ziel:\n{goal}\n\n"
    "Gehe jeden Punkt einzeln durch und pruefe nach, ob er wirklich umgesetzt ist - "
    "schau im Code oder im Ergebnis nach, verlasse dich nicht auf deine Erinnerung. "
    "Fehlt etwas, baue es jetzt. Ist wirklich alles erfuellt, antworte nur mit FERTIG."
)



# --- ToolProvider (ellmos-chat) ---

class BachToolProvider:
    """BACH's tools behind the module's ``ToolProvider`` protocol.

    Deliberately not a ``ToolRegistry``: BACH defines every tool the registry
    would have built in, plus the ones it does not (``bach_command``,
    ``task_manage``, ``maintain``, ``foerderbericht``, ``delegate``,
    ``ollama_info``, ``move_file``, ``copy_file``, ``recycle``), and it exposes
    ``edit_file``/``create_directory`` in Safe mode behind
    ``is_safe_write_path``. Starting from the registry would mean overriding
    almost all of it and still inheriting a ``read_file_write`` tool BACH never
    had. Adopting the module's hardened built-ins is a separate, user-visible
    decision -- its ``safe_shell`` refuses ``git``/``docker``/``curl``, which
    BACH's system prompt advertises.
    """

    def __init__(self, bach_app=None, default_model: Callable[[], str] | None = None,
                 *, worker_task_binding=None, require_task_binding=False, guard=None, allowed_tools=None,
                 agent_operations=None):
        self.bach_app = bach_app
        self._default_model = default_model
        self._worker_task_binding = worker_task_binding
        self._require_task_binding = require_task_binding
        self._guard = guard
        effective = _review_tool_grants(worker_task_binding, allowed_tools)
        self._allowed_tools = None if effective is None else frozenset(effective)
        self._agent_operations = agent_operations

    def get_tools(self, mode) -> list[dict]:
        if self._guard is not None:
            try:
                self._guard()
            except Exception:
                return []
        if self._require_task_binding and self._worker_task_binding is None:
            return []
        if self._worker_task_binding is not None:
            try:
                self._worker_task_binding.assert_active()
            except Exception:
                return []
        m = self._mode(mode)
        tools = tools_for_mode(m, bound_worker=self._worker_task_binding is not None)
        if self._allowed_tools is None:
            return tools
        filtered = [tool for tool in tools if tool["function"]["name"] in self._allowed_tools]
        if _read_evidence_readonly_worker_enabled(self._worker_task_binding, self._allowed_tools):
            formatter_available = _read_evidence_formatter() is not None
            filtered = copy.deepcopy(filtered)
            for index, tool in enumerate(filtered):
                if tool["function"]["name"] == "read_file":
                    filtered[index] = _versioned_read_file_tool(
                        tool, formatter_available=formatter_available,
                    )
                    break
        return filtered

    @staticmethod
    def _mode(mode):
        # BACH's planning mode is broader than the module's SAFE/FULL enum:
        # it reads and creates tasks, without file writes or delegation.
        if isinstance(mode, str) and mode.strip().lower() == "plan":
            return "plan"
        return as_mode(mode).value

    def execute(self, name: str, args: Any, mode) -> str:
        if self._allowed_tools is not None and name not in self._allowed_tools:
            return _tool_policy_denial("tool_not_authorized", "BLOCKIERT: Werkzeug ist für diesen Agenten nicht freigegeben.")
        if self._guard is not None:
            try:
                self._guard()
            except Exception:
                return _tool_policy_denial("worker_context_denied", "BLOCKIERT: Werkzeugfreigabe oder Workerlauf ist nicht mehr aktuell.")
        try:
            selected_mode = self._mode(mode)
        except ValueError:
            return _tool_policy_denial("mode_unavailable", "BLOCKIERT: Unbekannter Werkzeugmodus.")
        return exec_tool(
            name,
            args,
            selected_mode,
            bach_app=self.bach_app,
            default_model=self._default_model() if self._default_model else "",
            worker_task_binding=self._worker_task_binding,
            require_task_binding=self._require_task_binding,
            agent_operations=self._agent_operations,
            allowed_tools=self._allowed_tools,
        )
