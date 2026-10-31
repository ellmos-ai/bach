# SPDX-License-Identifier: MIT
"""Current SKILL.md sources, local overrides and content-addressed history.

There is one active source per canonical skill ID and requested locale. A user
edit creates or updates the local override; upstream modules remain the
documented factory source.
Instructions never grant tools. Their SHA256 is pinned when a slot is created.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from hub._services.user_config_store import _exclusive_lock
from hub._services.display_assets import TICKET_SYMBOL_IDS

SKILL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
REVISION = re.compile(r"^[a-f0-9]{64}$")
LOCALE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$", re.I)
MAX_SOURCE_BYTES = 200_000
MAX_PROMPT_CHARS = 80_000
DEFAULT_LOCALE = "de"
ENGLISH_LOCALE = "en"
SKIP_DIRS = {"_archive", "archive", "node_modules", "__pycache__", "dist", "build"}


def user_skills_root() -> Path:
    root = Path(os.environ.get("BACH_USER_SKILLS_ROOT", str(Path.home() / ".bach/skills"))).expanduser()
    if not root.is_absolute():
        raise ValueError("Die lokale Skill-Wurzel muss absolut sein")
    return root


def skill_roots() -> list[Path]:
    configured = os.environ.get("BACH_SKILLS_ROOTS")
    if configured is not None:
        values = json.loads(configured)
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError("BACH_SKILLS_ROOTS muss eine Liste absoluter Pfade sein")
        roots = [Path(v).expanduser() for v in values]
        if any(not p.is_absolute() for p in roots):
            raise ValueError("Skill-Wurzeln müssen absolut sein")
    else:
        home = Path.home()
        roots = [home / "OneDrive/.TOPICS/.AI/.SKILLS/skills", home / ".agents/skills",
                 home / ".claude/skills"]
    return list(dict.fromkeys([user_skills_root(), *roots]))


def _source_bytes(path: Path, root: Path) -> bytes:
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Skill-Quelle liegt außerhalb ihrer registrierten Wurzel")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Skill-Quelle ist zu groß")
    data = path.read_bytes()
    if len(data) > MAX_SOURCE_BYTES or b"\x00" in data:
        raise ValueError("Skill-Quelle ist ungültig")
    data.decode("utf-8")
    return data


def _metadata(content: str) -> dict:
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        return {}
    chunks = content.split("---", 2)
    if len(chunks) != 3:
        return {}
    try:
        import yaml
        meta = yaml.safe_load(chunks[1])
        return meta if isinstance(meta, dict) else {}
    except (ImportError, ValueError):
        return dict(re.findall(r"^([A-Za-z_]+):\s*[\"']?([^\r\n]+)", chunks[1], re.M))
    except Exception:
        return {}


def normalize_locale(value: str | None) -> str | None:
    """Normalize a BCP-47-like locale without inventing a translation."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("_", "-").lower()
    return normalized if LOCALE.fullmatch(normalized) else None


def resolve_requested_locale(value: str | None = None) -> str:
    """Resolve the configured system locale, keeping an explicit request authoritative."""
    if value is None:
        try:
            from hub.lang import get_lang
            value = get_lang()
        except Exception:
            value = DEFAULT_LOCALE
    return normalize_locale(value) or DEFAULT_LOCALE


def _locale_chain(requested_locale: str) -> list[str]:
    chain = [requested_locale]
    if "-" in requested_locale:
        chain.append(requested_locale.split("-", 1)[0])
    chain.append(ENGLISH_LOCALE)
    return list(dict.fromkeys(chain))


def _skill_identity(meta: dict, directory_name: str) -> str:
    candidate = meta.get("canonical_skill_id") or meta.get("id") or directory_name
    return candidate if isinstance(candidate, str) and SKILL_ID.fullmatch(candidate) else directory_name


def _skill_locale(meta: dict) -> tuple[str, bool]:
    for key in ("locale", "language", "lang"):
        if key not in meta:
            continue
        locale = normalize_locale(meta.get(key))
        return (locale, True) if locale else ("", True)
    # Existing English SKILL.md files predate the optional field. Treating the
    # absent marker as English preserves them without treating another locale
    # as an English fallback.
    return ENGLISH_LOCALE, False


def _relative_source_path(item: dict) -> str:
    try:
        return str(Path(item["path"]).relative_to(Path(item["root"])))
    except (KeyError, ValueError):
        return "SKILL.md"


def _public_source_item(item: dict, *, include_content: bool = False) -> dict:
    result = {k: v for k, v in item.items() if k not in {"path", "root"}}
    result["source_path"] = str(item["path"])
    result["source_path_relative"] = _relative_source_path(item)
    if include_content:
        data = _source_bytes(item["path"], item["root"])
        result["content"] = data.decode("utf-8")
        result["content_sha256"] = hashlib.sha256(data).hexdigest()
    return result


def source_catalog(
    roots: list[Path] | None = None,
    requested_locale: str | None = None,
    *,
    include_unresolved: bool = False,
) -> dict[str, dict]:
    """Bounded locale-aware scan; archived copies and symlink directories are excluded."""
    requested = resolve_requested_locale(requested_locale)
    variants: dict[str, list[dict]] = {}
    visited = 0
    scan_roots = roots if roots is not None else skill_roots()
    for root in scan_roots:
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            parent = Path(directory)
            depth = len(parent.relative_to(root).parts)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
                             and depth < 6 and not (parent / d).is_symlink())
            visited += 1
            if visited > 4096:
                raise RuntimeError("Skill-Katalog überschreitet die begrenzte Scanweite")
            if "SKILL.md" not in files or not SKILL_ID.fullmatch(parent.name):
                continue
            path = parent / "SKILL.md"
            try:
                data = _source_bytes(path, root)
            except (OSError, ValueError, UnicodeError):
                continue
            content = data.decode("utf-8")
            meta = _metadata(content)
            canonical_id = _skill_identity(meta, parent.name)
            locale, locale_declared = _skill_locale(meta)
            if not locale:
                continue
            item = {
                "id": canonical_id, "canonical_skill_id": canonical_id,
                "name": str(meta.get("name") or canonical_id),
                "category": str(meta.get("category") or (parent.parent.name if parent.parent != root else "general")),
                "role": str(meta.get("description") or "")[:300],
                "version": str(meta.get("version") or "ohne Versionsnummer"),
                "symbol": meta.get("symbol") if isinstance(meta.get("symbol"), str) and meta["symbol"] in TICKET_SYMBOL_IDS else "",
                "locale": locale, "locale_declared": locale_declared,
                "requested_locale": requested, "resolved_locale": locale,
                "fallback_used": locale != requested,
                "available_locales": [],
                "content_sha256": hashlib.sha256(data).hexdigest(),
                "source_version": hashlib.sha256(data).hexdigest(),
                "evidence_type": "filesystem_present", "source_kind": "local_override" if root == user_skills_root() else "factory",
                "path": path, "root": root,
            }
            variants.setdefault(canonical_id, [])
            if not any(existing["locale"] == locale for existing in variants[canonical_id]):
                variants[canonical_id].append(item)

    result: dict[str, dict] = {}
    for canonical_id, candidates in variants.items():
        available = sorted({candidate["locale"] for candidate in candidates})
        selected = next((candidate for wanted in _locale_chain(requested)
                         for candidate in candidates if candidate["locale"] == wanted), None)
        if selected is None:
            if not include_unresolved:
                continue
            template = candidates[0]
            result[canonical_id] = {
                "id": canonical_id, "canonical_skill_id": canonical_id,
                "name": canonical_id, "category": template["category"], "role": "",
                "version": "", "symbol": "", "locale": None,
                "locale_declared": False, "requested_locale": requested,
                "resolved_locale": None, "fallback_used": False,
                "available_locales": available, "content_sha256": None,
                "source_version": None, "evidence_type": "language_variant_missing",
                "source_kind": template["source_kind"], "missing_locale": True,
            }
            continue
        selected = dict(selected)
        selected["available_locales"] = available
        selected["missing_locale"] = False
        result[canonical_id] = selected
    return result


def read_skill(
    skill_id: str,
    *,
    roots: list[Path] | None = None,
    requested_locale: str | None = None,
) -> dict:
    if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
        raise ValueError("Ungültige Skill-ID")
    item = source_catalog(roots, requested_locale=requested_locale).get(skill_id)
    if item is None:
        raise KeyError("Keine aktuelle SKILL.md-Quelle für diese Sprachfassung")
    data = _source_bytes(item["path"], item["root"])
    revision = hashlib.sha256(data).hexdigest()
    result = {**_public_source_item(item), "source_version": revision,
              "content_sha256": revision, "content": data.decode("utf-8"),
              "version_path": str(_history_directory(skill_id)[1] / (revision + ".md")),
              "editable": True,
            "edit_kind": "local_override", "tools_granted": False}
    return result


def skill_library(roots: list[Path] | None = None, requested_locale: str | None = None) -> dict:
    requested = resolve_requested_locale(requested_locale)
    catalog = source_catalog(roots, requested_locale=requested, include_unresolved=True)
    items = []
    unresolved = []
    for item in catalog.values():
        public = {k: v for k, v in item.items() if k not in {"path", "root"}}
        public["description"] = item["role"]
        if item.get("missing_locale"):
            unresolved.append(public)
        else:
            public["source_path_relative"] = _relative_source_path(item)
            items.append(public)
    items.sort(key=lambda x: x["name"].casefold())
    unresolved.sort(key=lambda x: x["canonical_skill_id"].casefold())
    available = sorted({locale for item in (*items, *unresolved) for locale in item.get("available_locales", [])})
    return {"schema": "bach.skill-library.v1", "skills": items,
            "unresolved_skills": unresolved, "count": len(items),
            "categories": sorted({x["category"] for x in items}),
            "available_locales": available, "requested_locale": requested,
            "source": "current_SKILL.md", "declared_only_included": False}


def _contained_user_path(root: Path, candidate: Path) -> Path:
    """Resolve a local skill path and reject escapes or symlink components."""
    root = Path(root).expanduser().resolve()
    candidate = Path(candidate)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise PermissionError("Skill-Pfad liegt außerhalb seiner Wurzel") from None
    current = candidate
    while current != root and root in current.parents:
        if current.is_symlink():
            raise PermissionError("Skill-Pfad darf keine Symlink-Komponente enthalten")
        current = current.parent
    return resolved


def _history_directory(skill_id: str, write_root: Path | None = None) -> tuple[Path, Path]:
    if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
        raise ValueError("Ungültige Skill-ID")
    root = Path(write_root or user_skills_root()).expanduser().resolve()
    directory = _contained_user_path(root, root / ".history" / skill_id)
    return root, directory


def _local_override_target(write_root: Path, skill_id: str, locale: str, category: Any) -> Path:
    if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
        raise ValueError("Ungültige Skill-ID")
    if not isinstance(locale, str) or not LOCALE.fullmatch(locale):
        raise ValueError("Ungültige Skill-Sprache")
    write_root = Path(write_root).expanduser().resolve()
    if locale == ENGLISH_LOCALE:
        return write_root / skill_id / "SKILL.md"
    category_dir = category if isinstance(category, str) and SKILL_ID.fullmatch(category) else "general"
    return write_root / locale / category_dir / skill_id / "SKILL.md"


def read_skill_history(
    skill_id: str,
    revision: str,
    *,
    write_root: Path | None = None,
    requested_locale: str | None = None,
) -> dict:
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError("Ungültige Skill-Quellenversion")
    root, directory = _history_directory(skill_id, write_root)
    path = directory / (revision + ".md")
    if not path.is_file():
        raise KeyError("Historische Skill-Fassung fehlt")
    raw = _source_bytes(path, root)
    if hashlib.sha256(raw).hexdigest() != revision:
        raise ValueError("Skill-Historie stimmt nicht mit ihrer Quellenversion überein")
    meta = _metadata(raw.decode("utf-8"))
    locale, locale_declared = _skill_locale(meta)
    requested = resolve_requested_locale(requested_locale)
    return {"id": skill_id, "canonical_skill_id": skill_id,
            "source_version": revision, "content_sha256": revision,
            "content": raw.decode("utf-8"),
            "version": str(meta.get("version") or "ohne Versionsnummer"),
            "locale": locale, "locale_declared": locale_declared,
            "requested_locale": requested, "resolved_locale": locale,
            "fallback_used": locale != requested,
            "source_path": str(path), "version_path": str(path),
            "symbol": meta.get("symbol") if isinstance(meta.get("symbol"), str) and meta["symbol"] in TICKET_SYMBOL_IDS else "",
            "archived_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def list_skill_history(skill_id: str, requested_locale: str | None = None) -> dict:
    _, directory = _history_directory(skill_id)
    items = []
    if directory.is_dir():
        paths = sorted(directory.iterdir(), key=lambda p: p.name)
        if len(paths) > 500:
            raise ValueError("Skill-Historie überschreitet die Lesegrenze")
        for path in paths:
            if path.suffix == ".md" and REVISION.fullmatch(path.stem):
                item = read_skill_history(skill_id, path.stem, requested_locale=requested_locale)
                items.append({k: v for k, v in item.items() if k != "content"})
    return {"schema": "bach.skill-history.v1", "id": skill_id,
            "canonical_skill_id": skill_id,
            "requested_locale": resolve_requested_locale(requested_locale),
            "versions": sorted(items, key=lambda x: x["archived_at"], reverse=True)}


def pin_skills(
    ids: list[str],
    *,
    roots: list[Path] | None = None,
    requested_locale: str | None = None,
) -> list[dict]:
    if (not isinstance(ids, list) or len(ids) > 30
            or any(not isinstance(item, str) or not SKILL_ID.fullmatch(item) for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Bis zu 30 unterschiedliche Skills auswählen")
    catalog = source_catalog(roots, requested_locale=requested_locale) if ids else {}
    pins = []
    for skill_id in ids:
        if (not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id)
                or skill_id not in catalog or catalog[skill_id].get("missing_locale")):
            raise ValueError("Skill hat keine ausführbare SKILL.md-Quelle für die angeforderte Sprache: " + str(skill_id))
        item = catalog[skill_id]
        data = _source_bytes(item["path"], item["root"])
        pins.append({"id": skill_id, "source_version": hashlib.sha256(data).hexdigest(),
                     "version": item["version"]})
    load_skill_instructions(pins, roots=roots)
    return pins


def validate_skill_refs(pins: list[dict]) -> list[dict]:
    """Validate saved pin metadata without requiring its source to remain current."""
    if not isinstance(pins, list) or len(pins) > 30:
        raise ValueError("Ungültige Skill-Bindung")
    seen = set()
    for pin in pins:
        if (not isinstance(pin, dict) or set(pin) != {"id", "source_version", "version"}
                or not isinstance(pin["id"], str) or not SKILL_ID.fullmatch(pin["id"])
                or not isinstance(pin["source_version"], str) or not REVISION.fullmatch(pin["source_version"])
                or not isinstance(pin["version"], str) or pin["id"] in seen):
            raise ValueError("Skill benötigt eine gültige Quellenversion")
        seen.add(pin["id"])
    return [dict(pin) for pin in pins]


def skill_binding_status(pins: list[dict], *, roots: list[Path] | None = None) -> list[dict]:
    refs = validate_skill_refs(pins)
    if not refs:
        return []
    try:
        catalog = source_catalog(roots)
    except (OSError, ValueError, RuntimeError):
        catalog = None
    return [{"id": pin["id"], "source_version": pin["source_version"], "state":
             "unavailable" if catalog is None else "missing" if pin["id"] not in catalog else
             "current" if catalog[pin["id"]]["source_version"] == pin["source_version"] else "source_changed"}
            for pin in refs]


def load_skill_instructions(pins: list[dict], *, roots: list[Path] | None = None) -> str:
    refs = validate_skill_refs(pins)
    if not refs:
        return ""
    catalog = source_catalog(roots)
    parts = []
    for pin in refs:
        item = catalog.get(pin["id"])
        if item is None:
            raise ValueError("Gebundene Skill-Quelle fehlt: " + pin["id"])
        data = _source_bytes(item["path"], item["root"])
        if hashlib.sha256(data).hexdigest() != pin["source_version"]:
            raise RuntimeError("Skill wurde geändert; Steckplatz neu einrichten: " + pin["id"])
        parts.append("--- SKILL: " + pin["id"] + " · " + pin["source_version"] + " ---\n"
                     + data.decode("utf-8"))
    text = "\n\n".join(parts)
    if len(text) > MAX_PROMPT_CHARS:
        raise ValueError("Gewählte Skill-Anleitungen überschreiten das Promptbudget")
    return text


def check_write_locks(path: Path) -> None:
    """Use the installed canonical scanner, including parent and twin locks."""
    configured = os.environ.get("BACH_LOCK_TOOLS_ROOT")
    directory = Path(configured).expanduser() if configured else Path.home() / "OneDrive/_scripts"
    scanner = directory / "lock_scan.py"
    config = directory / "lock_roots.json"
    if not scanner.is_file() or not config.is_file():
        raise PermissionError("Kanonischer Lock-Scanner ist für Skill-Schreibzugriffe nicht konfiguriert")
    target = path if path.is_dir() else path.parent
    while not target.exists() and target != target.parent:
        target = target.parent
    # --check-dir already includes all overlapping ancestor and twin locks.
    # Recursively scanning every ancestor also scans unrelated sibling trees.
    result = subprocess.run([sys.executable, "-S", str(scanner), "--check-dir", str(target),
                             "--strict", "--json"],
                            capture_output=True, text=True, encoding="utf-8", timeout=15,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        state = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise PermissionError("Lock-Status konnte nicht bestätigt werden") from None
    if (not isinstance(state, dict) or result.returncode != 0
            or state.get("checked") != str(target.resolve())
            or state.get("locks") != [] or state.get("hook_guards") != []
            or state.get("descendants_complete") is not True
            or state.get("twin_status") not in {"ok", "not-applicable"}):
        raise PermissionError("Skill-Schreibbereich ist gesperrt oder ungeprüft")



def save_skill(skill_id: str, content: str, expected_version: str, *,
               roots: list[Path] | None = None, write_root: Path | None = None,
               requested_locale: str | None = None,
               guard: Callable[[Path], None] | None = None) -> dict:
    if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
        raise ValueError("Ungültige Skill-ID")
    if (not isinstance(content, str) or not content.strip() or "\x00" in content
            or len(content.encode("utf-8")) > MAX_SOURCE_BYTES):
        raise ValueError("Skill benötigt gültigen UTF-8-Inhalt bis 200 KB")
    if expected_version != "0" and (not isinstance(expected_version, str) or not REVISION.fullmatch(expected_version)):
        raise ValueError("Aktuelle Quellenversion erforderlich")
    write_root = Path(write_root or user_skills_root()).expanduser().resolve()
    all_roots = [write_root, *(roots if roots is not None else skill_roots())]
    checker = guard or check_write_locks
    initial_source = source_catalog(all_roots, requested_locale=requested_locale).get(skill_id)
    if initial_source and Path(initial_source["root"]).resolve() == Path(write_root).resolve():
        target = Path(initial_source["path"])
    else:
        locale = initial_source.get("locale") if initial_source else None
        if not isinstance(locale, str) or not LOCALE.fullmatch(locale):
            locale = (normalize_locale(requested_locale) or ENGLISH_LOCALE
                      if requested_locale is not None else ENGLISH_LOCALE)
        target = _local_override_target(
            Path(write_root), skill_id, locale,
            initial_source.get("category") if initial_source else "general",
        )
    candidate_target = Path(target)
    target = candidate_target.resolve()
    if not target.is_relative_to(write_root):
        raise PermissionError("Skill-Schreibpfad liegt außerhalb seiner Wurzel")
    if any(parent.is_symlink() for parent in (candidate_target, *candidate_target.parents)
           if parent != write_root):
        raise PermissionError("Skill-Schreibpfad darf keine Symlink-Komponente enthalten")
    if (target.exists() or target.is_symlink()) and (
            initial_source is None or Path(initial_source["path"]).resolve() != target.resolve()):
        raise RuntimeError("skill_source_version_conflict")
    checker(target)
    if (any(parent.is_symlink() for parent in (target, *target.parents))
            or target.with_name(target.name + ".lock").is_symlink()
            or (write_root / ".history").is_symlink()
            or (write_root / ".history" / skill_id).is_symlink()):
        raise PermissionError("Skill-Schreibbereich darf kein Symlink sein")
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(target):
        current = source_catalog(all_roots, requested_locale=requested_locale).get(skill_id)
        if ((initial_source is None) != (current is None)
                or (initial_source is not None and current is not None
                    and (Path(current["root"]).resolve() != Path(initial_source["root"]).resolve()
                         or Path(current["path"]).resolve() != Path(initial_source["path"]).resolve()))):
            raise RuntimeError("skill_source_version_conflict")
        previous = _source_bytes(current["path"], current["root"]) if current else None
        actual = hashlib.sha256(previous).hexdigest() if previous is not None else "0"
        if actual != expected_version:
            raise RuntimeError("skill_source_version_conflict")
        _, history = _history_directory(skill_id, write_root)
        if not history.is_relative_to(write_root):
            raise PermissionError("Skill-Historie liegt außerhalb ihrer Wurzel")
        checker(history)
        if history.is_symlink() or history.parent.is_symlink():
            raise PermissionError("Skill-Historie darf kein Symlink sein")
        history.mkdir(parents=True, exist_ok=True)
        if previous is not None:
            archived = history / (actual + ".md")
            checker(archived)
            if archived.is_symlink():
                raise PermissionError("Skill-Historie darf kein Symlink sein")
            if archived.exists():
                if archived.read_bytes() != previous:
                    raise RuntimeError("Skill-Historie ist beschädigt")
            else:
                with archived.open("xb") as f:
                    f.write(previous)
        checker(target)
        if any(parent.is_symlink() for parent in (target, *target.parents)):
            raise PermissionError("Skill-Schreibbereich darf kein Symlink sein")
        if current and _source_bytes(current["path"], current["root"]) != previous:
            raise RuntimeError("skill_source_version_conflict")
        data = content.encode("utf-8")
        fd, temp = tempfile.mkstemp(prefix=".skill-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    saved = read_skill(skill_id, roots=all_roots, requested_locale=requested_locale)
    if saved["source_version"] != hashlib.sha256(data).hexdigest():
        raise RuntimeError("Gespeicherte Skill-Quelle nicht bestätigt")
    return {"success": True, **saved, "previous_version": actual,
            "receipt": {"source_saved": True, "tools_granted": False, "agent_started": False}}



def delete_skill(skill_id: str, expected_version: str, *,
                 roots: list[Path] | None = None, write_root: Path | None = None,
                 guard: Callable[[Path], None] | None = None) -> dict:
    """CAS-remove only the local override created by a native promotion."""
    if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
        raise ValueError("Ungültige Skill-ID")
    if not isinstance(expected_version, str) or not REVISION.fullmatch(expected_version):
        raise ValueError("Aktuelle Quellenversion erforderlich")
    write_root = (write_root or user_skills_root()).expanduser().resolve()
    all_roots = list(dict.fromkeys([write_root, *(roots if roots is not None else skill_roots())]))
    checker = guard or check_write_locks
    current = source_catalog(all_roots).get(skill_id)
    if current is None or Path(current["root"]).resolve() != write_root:
        raise RuntimeError("skill_source_version_conflict")
    target = Path(current["path"])
    checker(target)
    if any(parent.is_symlink() for parent in (target, *target.parents)):
        raise PermissionError("Skill-Schreibbereich darf kein Symlink sein")
    with _exclusive_lock(target):
        current = source_catalog(all_roots).get(skill_id)
        if (current is None or Path(current["root"]).resolve() != write_root
                or Path(current["path"]).resolve() != target.resolve()):
            raise RuntimeError("skill_source_version_conflict")
        previous = _source_bytes(current["path"], current["root"])
        actual = hashlib.sha256(previous).hexdigest()
        if actual != expected_version:
            raise RuntimeError("skill_source_version_conflict")
        checker(target)
        latest = source_catalog(all_roots).get(skill_id)
        if (latest is None or Path(latest["root"]).resolve() != write_root
                or Path(latest["path"]).resolve() != target.resolve()
                or hashlib.sha256(_source_bytes(latest["path"], latest["root"])).hexdigest() != expected_version):
            raise RuntimeError("skill_source_version_conflict")
        target.unlink()
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    return {"success": True, "id": skill_id, "previous_version": expected_version,
            "receipt": {"source_removed": True, "tools_granted": False, "agent_started": False}}
