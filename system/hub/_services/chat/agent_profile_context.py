"""Strict, local profile context for human Control chats."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from hub.bach_paths import AGENTS_DIR, BACH_DB

# Explicit compatibility for the current canonical DB slugs. DB skill_path is
# legacy metadata and never controls a filesystem read.
_PROFILES = {
    "persoenlicher-assistent": ("persoenlicher-assistent", "1.2.0", "ffca4acaa2957a5c0e660e6210368322db57cb5e9dfbd72ac627ed8b5e56e26d"),
    "gesundheitsassistent": ("gesundheitsassistent", "2.0.0", "b1a4d6f66b5ec896bd2a7977ce0d905223b087d2f4822e4a255a12b40b5e8289"),
    "bueroassistent": ("bueroassistent", "1.0.0", "ceb8b1cd6b20373e9e7cd4dfce5be724c471a6bdb27ed6c6a410c56218e33371"),
    "ati": ("ati-agent", "1.2.0", "7f0d775b9b51134fc4229543f0a14eb63cd1a5510c12493e986b71d92f6a29d4"),
}
_PROFILE_ID = re.compile(r"^agent:([1-9][0-9]*):([a-f0-9]{32})$")
_FIELDS = ("context_class", "agent_id", "exact_slug", "db_version", "source_version", "profile_sha256")


class ProfileUnavailable(ValueError):
    """A requested profile cannot safely be bound."""


def profile_chat_id_agent(chat_id: str) -> int | None:
    match = _PROFILE_ID.fullmatch(chat_id) if type(chat_id) is str else None
    return int(match.group(1)) if match else None


def binding_metadata(binding: dict | None) -> dict | None:
    if binding is None:
        return None
    if type(binding) is not dict or set(binding) != set(_FIELDS):
        raise ProfileUnavailable("Profilbindung ist unvollständig")
    if binding.get("context_class") != "agent-profile" or type(binding.get("agent_id")) is not int or binding["agent_id"] <= 0:
        raise ProfileUnavailable("Profilbindung ist ungültig")
    for key in _FIELDS[2:]:
        if type(binding[key]) is not str or not binding[key]:
            raise ProfileUnavailable("Profilbindung ist ungültig")
    return {key: binding[key] for key in _FIELDS}


def resolve_profile(agent_id: int) -> tuple[dict, str]:
    if type(agent_id) is not int or agent_id <= 0:
        raise ProfileUnavailable("agent_id muss eine positive Ganzzahl sein")
    if not BACH_DB.is_file():
        raise ProfileUnavailable("Lokale Profildatenbank fehlt")
    try:
        conn = sqlite3.connect(BACH_DB.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=5.0)
        try:
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute("SELECT name, version, is_active FROM bach_agents WHERE id = ?", (agent_id,)).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        raise ProfileUnavailable("Profilrecord nicht verifizierbar") from exc
    if len(rows) != 1:
        raise ProfileUnavailable("Agentenprofil nicht gefunden")
    slug, db_version, is_active = rows[0]
    if type(slug) is not str or slug not in _PROFILES or is_active != 1:
        raise ProfileUnavailable("Agentenprofil nicht verfügbar")
    if type(db_version) is not str or not db_version:
        raise ProfileUnavailable("Profilversion fehlt")
    expected_name, source_version, expected_hash = _PROFILES[slug]
    if db_version != source_version:
        raise ProfileUnavailable("Datenbank- und Profilversion stimmen nicht überein")
    try:
        root = AGENTS_DIR.resolve(strict=True)
    except OSError as exc:
        raise ProfileUnavailable("Vertrauenswürdiger Agentenroot fehlt") from exc
    file = root / slug / "SKILL.md"
    try:
        path = file.resolve(strict=True)
        if not path.is_relative_to(root) or path.parent != root / slug or not path.is_file() or file.is_symlink():
            raise ProfileUnavailable("Profilpfad ist nicht autorisiert")
        if path.stat().st_size > 16384:
            raise ProfileUnavailable("Profildatei ist zu groß")
        data = path.read_bytes()
        if len(data) > 16384 or hashlib.sha256(data).hexdigest() != expected_hash:
            raise ProfileUnavailable("Profilquelle entspricht nicht der Freigabe")
        text = data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProfileUnavailable("Profilquelle nicht lesbar") from exc
    frontmatter = re.match(r"\A---\s*\n(.*?)\n---(?:\n|\Z)", text, re.DOTALL)
    if frontmatter is None:
        raise ProfileUnavailable("Profilmetadaten fehlen")
    fields = dict(match.groups() for line in frontmatter.group(1).splitlines()
                  if (match := re.fullmatch(r"(name|version):\s*([^\r\n]+)", line)))
    if fields.get("name") != expected_name or fields.get("version") != source_version:
        raise ProfileUnavailable("Profilmetadaten entsprechen nicht der Freigabe")
    binding = {"context_class": "agent-profile", "agent_id": agent_id,
               "exact_slug": slug, "db_version": db_version,
               "source_version": source_version, "profile_sha256": expected_hash}
    return binding, text


def require_current_binding(binding: dict) -> tuple[dict, str]:
    saved = binding_metadata(binding)
    current, text = resolve_profile(saved["agent_id"])
    if saved != current:
        raise ProfileUnavailable("Gespeicherte Profilbindung ist nicht mehr aktuell")
    return current, text
