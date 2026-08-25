#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
agents_export.py - AGENTS.md and Claude Code Agent exporter
============================================================

The default export remains the historical, human-readable ``AGENTS.md``
mirror.  ``--format agent`` is an opt-in export for Claude Code project
subagents.  It deliberately uses the database as the identity source and
never overwrites an existing file.

The Claude Code format is a Markdown file with YAML frontmatter.  BACH-only
metadata (the database row, persona file and skill path) is kept in the body,
because unknown frontmatter keys are not accepted by all Claude Code versions.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


AGENT_FORMAT = "agent"
MARKDOWN_FORMATS = {"markdown", "md", "default", "agents"}
DEFAULT_AGENT_OUTPUT = Path(".claude") / "agents"

# These are the fields supported by Claude Code file-based subagents.  Keep
# this list deliberately explicit: BACH metadata belongs in the body, not in
# an extension field that may make Claude refuse to load the file.
ALLOWED_AGENT_FRONTMATTER = frozenset(
    {
        "name",
        "description",
        "tools",
        "disallowedTools",
        "model",
        "permissionMode",
        "maxTurns",
        "skills",
        "mcpServers",
        "hooks",
        "memory",
        "background",
        "effort",
        "isolation",
        "color",
        "initialPrompt",
    }
)
REQUIRED_AGENT_FRONTMATTER = frozenset({"name", "description"})
VALID_AGENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _clean(value: Any) -> str:
    """Return a deterministic, NFC-normalized string for DB/file values."""

    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip()


def _slugify(value: str, fallback: str = "agent") -> str:
    """Convert a DB name to Claude Code's lowercase-hyphen name syntax."""

    # NFKD turns common accented names into stable ASCII identifiers while
    # leaving the original Unicode value untouched in the generated prompt.
    ascii_value = unicodedata.normalize("NFKD", _clean(value)).encode(
        "ascii", "ignore"
    ).decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or fallback


def _yaml_quote(value: str) -> str:
    """Emit a YAML-safe deterministic scalar without a YAML dependency."""

    return json.dumps(_clean(value), ensure_ascii=False)


def _yaml_list(values: Iterable[str]) -> str:
    return "[" + ", ".join(_yaml_quote(v) for v in values if _clean(v)) + "]"


def _relative_display_path(path: Path, bach_root: Path, system_root: Path) -> str:
    """Return a portable path reference for the generated agent body."""

    resolved = path.resolve()
    for base, prefix in ((bach_root.resolve(), ""), (system_root.resolve(), "system/")):
        try:
            rel = resolved.relative_to(base)
        except ValueError:
            continue
        value = rel.as_posix()
        return f"{prefix}{value}" if prefix else value
    return path.as_posix()


def _database_has_agent_tables(path: Path) -> bool:
    """Check a candidate DB without creating or mutating it."""

    if not path.exists():
        return False
    conn = None
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        rows = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('bach_agents', 'bach_experts')
            """
        ).fetchall()
        return {row[0] for row in rows} == {"bach_agents", "bach_experts"}
    except (OSError, sqlite3.Error):
        return False
    finally:
        if conn is not None:
            conn.close()


def _frontmatter_block(document: str) -> str | None:
    """Extract a YAML frontmatter block from a Markdown document."""

    text = document.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    return text[4:end]


def _parse_simple_frontmatter(document: str) -> dict[str, Any] | None:
    """Parse the small metadata subset needed from persona/agent files.

    PyYAML is intentionally not required by BACH.  This parser handles the
    scalar, list and two-level mapping forms used by the persona template and
    by Claude Code's frontmatter.  It is also strict enough for validation:
    malformed lines are simply left out and subsequently reported.
    """

    block = _frontmatter_block(document)
    if block is None:
        return None

    result: dict[str, Any] = {}
    top_section: str | None = None
    nested_key: str | None = None

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0 and ":" in stripped:
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            top_section = key if value in {"", "|", ">"} else None
            nested_key = None
            if value in {"", "|", ">"}:
                result[key] = {} if value == "" and key in {"persona", "runtime"} else ""
            elif value.startswith("[") and value.endswith("]"):
                result[key] = _parse_inline_list(value)
            else:
                result[key] = _parse_scalar(value)
            continue

        if top_section is None or indent == 0:
            continue
        section = result.get(top_section)

        # A top-level list (for example ``skills:`` followed by ``- foo``).
        if stripped.startswith("-"):
            if isinstance(section, dict) and nested_key:
                nested = section.setdefault(nested_key, [])
                if isinstance(nested, list):
                    nested.append(_parse_scalar(stripped[1:].strip()))
            elif section in ("", None):
                result[top_section] = [_parse_scalar(stripped[1:].strip())]
            elif isinstance(section, list):
                section.append(_parse_scalar(stripped[1:].strip()))
            continue

        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not isinstance(section, dict):
            continue
        if indent <= 2:
            nested_key = key if value == "" else None
            if value == "":
                section[key] = []
            elif value.startswith("[") and value.endswith("]"):
                section[key] = _parse_inline_list(value)
            else:
                section[key] = _parse_scalar(value)
        elif nested_key:
            nested = section.setdefault(nested_key, {})
            if isinstance(nested, dict):
                nested[key] = _parse_scalar(value)
    return result


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    if value.lower() in {"null", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            pass
    # Persona files use inline comments for skill paths.  Comments are only
    # stripped when separated by whitespace so a URL or a name containing '#'
    # remains intact.
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _parse_inline_list(value: str) -> list[Any]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    # JSON is valid YAML for the quoted form emitted by this exporter.
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return [_parse_scalar(item) for item in inner.split(",") if item.strip()]


def _section_value(metadata: dict[str, Any], section: str, key: str) -> Any:
    value = metadata.get(section, {})
    return value.get(key) if isinstance(value, dict) else None


class AgentsExporter:
    """Generate the historical AGENTS.md mirror or Claude Code agents."""

    def __init__(
        self,
        bach_root: Path,
        *,
        db_path: Path | None = None,
        output_path: Path | None = None,
        persona_dir: Path | None = None,
    ):
        self.bach_root = Path(bach_root)

        # Auto-Detect: Root vs. system/ installation.
        if (self.bach_root / "system").exists():
            self.system_root = self.bach_root / "system"
        else:
            self.system_root = self.bach_root
            self.bach_root = self.system_root.parent

        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            # Use BACH's central path resolver when available.  Falling back
            # to a fixture/local DB with the required tables keeps standalone
            # tool use and temporary exporter fixtures working.  An empty
            # OneDrive copy is never preferred over the central DB.
            local_db = self.system_root / "data" / "bach.db"
            if _database_has_agent_tables(local_db):
                self.db_path = local_db
            else:
                try:
                    from hub.bach_paths import BACH_DB

                    self.db_path = Path(BACH_DB)
                except Exception:
                    self.db_path = local_db

        self.output_path = Path(output_path) if output_path else self.bach_root / "AGENTS.md"
        self.persona_dir = (
            Path(persona_dir)
            if persona_dir is not None
            else self.system_root / "agents" / "personas"
        )

    # ------------------------------------------------------------------
    # Historical AGENTS.md export (kept semantically unchanged)
    # ------------------------------------------------------------------

    def generate(
        self,
        format: str | None = None,
        *,
        output_dir: Path | str | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Generate the requested export format.

        ``generate()`` without a format is the legacy AGENTS.md operation.
        ``format='agent'`` is opt-in and never changes that operation.
        """

        normalized = _clean(format).lower() if format is not None else ""
        if normalized == AGENT_FORMAT:
            return self.generate_agents(output_dir=output_dir, dry_run=dry_run)
        if normalized and normalized not in MARKDOWN_FORMATS:
            return False, f"[ERROR] Unbekanntes Exportformat: {format}"
        if output_dir is not None or dry_run:
            return False, "[ERROR] --output/--dry-run sind nur für --format agent gültig"

        if not self._check_tables():
            return False, "✗ Tabellen bach_agents oder bach_experts nicht gefunden"

        agents = self._get_agents()
        experts = self._get_experts()
        content = self._build_content(agents, experts)
        self.output_path.write_text(content, encoding="utf-8")
        return True, f"✓ AGENTS.md generiert: {self.output_path}"

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Datenbank nicht gefunden: {self.db_path}")
        uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def _check_tables(self) -> bool:
        """Prüfe ob beide Tabellen existieren, ohne eine DB anzulegen."""

        conn = None
        try:
            conn = self._connect_readonly()
            rows = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN ('bach_agents', 'bach_experts')
                """
            ).fetchall()
        except (OSError, sqlite3.Error):
            return False
        finally:
            if conn is not None:
                conn.close()
        return {row[0] for row in rows} == {"bach_agents", "bach_experts"}

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _get_table_rows(self, table: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        conn = self._connect_readonly()
        try:
            available = self._table_columns(conn, table)
            selected = [column for column in columns if column in available]
            if not selected:
                return []
            order_by = "name" if "name" in available else selected[0]
            query = f"SELECT {', '.join(selected)} FROM {table} ORDER BY {order_by}"
            rows = conn.execute(query).fetchall()
        finally:
            conn.close()
        return [dict(zip(selected, row)) for row in rows]

    def _get_agents(self) -> list[dict]:
        """Get all boss agents, tolerating older fixture schemas."""

        columns = (
            "id",
            "name",
            "display_name",
            "type",
            "category",
            "description",
            "skill_path",
            "is_active",
            "version",
            "language",
            "persona",
        )
        rows = self._get_table_rows("bach_agents", columns)
        agents = []
        for row in rows:
            agents.append(
                {
                    "id": row.get("id"),
                    "name": row.get("name", ""),
                    "display_name": row.get("display_name", ""),
                    "type": row.get("type", ""),
                    "category": row.get("category", ""),
                    "description": row.get("description", ""),
                    "path": row.get("skill_path", ""),
                    "status": "active" if row.get("is_active", 1) else "inactive",
                    "version": row.get("version", ""),
                    "language": row.get("language", ""),
                    "persona": row.get("persona", ""),
                    "kind": "agent",
                }
            )
        return agents

    def _get_experts(self) -> list[dict]:
        """Get all experts, tolerating older fixture schemas."""

        columns = (
            "id",
            "name",
            "display_name",
            "domain",
            "description",
            "skill_path",
            "is_active",
            "version",
            "language",
            "persona",
        )
        rows = self._get_table_rows("bach_experts", columns)
        experts = []
        for row in rows:
            experts.append(
                {
                    "id": row.get("id"),
                    "name": row.get("name", ""),
                    "display_name": row.get("display_name", ""),
                    "type": row.get("domain", ""),
                    "description": row.get("description", ""),
                    "path": row.get("skill_path", ""),
                    "status": "active" if row.get("is_active", 1) else "inactive",
                    "version": row.get("version", ""),
                    "language": row.get("language", ""),
                    "persona": row.get("persona", ""),
                    "kind": "expert",
                }
            )
        return experts

    # ------------------------------------------------------------------
    # Claude Code agent export
    # ------------------------------------------------------------------

    def generate_agents(
        self,
        *,
        output_dir: Path | str | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Export active DB agents and experts as Claude Code subagents.

        Existing files are read back and left untouched.  A byte-identical
        existing file is reported as already exported; a differing file is a
        conflict and fails the operation.  Invalid rows are skipped with an
        explicit diagnostic so one bad persona cannot overwrite another.
        """

        if not self._check_tables():
            return False, "[ERROR] Tabellen bach_agents oder bach_experts nicht gefunden"

        destination = self._resolve_output_dir(output_dir)
        rows = self._get_agents() + self._get_experts()
        diagnostics: list[str] = [
            f"[INFO] Claude-Code-Agent-Export nach {destination}",
            "[INFO] DB ist Identitätsquelle; Persona-Dateien liefern optionale Laufzeit-/Skill-Metadaten.",
        ]

        candidates: list[tuple[dict[str, Any], str, str]] = []
        seen_slugs: dict[str, dict[str, Any]] = {}
        fatal = False

        # Stable ordering is independent of SQLite row order and language.
        rows = sorted(
            rows,
            key=lambda row: (
                _slugify(_clean(row.get("name")) or "agent"),
                _clean(row.get("kind")),
                _clean(row.get("language")),
                str(row.get("id") or ""),
            ),
        )

        for row in rows:
            name = _clean(row.get("name"))
            display_name = _clean(row.get("display_name")) or name
            label = f"{row.get('kind', 'agent')} {name or '<ohne Name>'}"
            if not name:
                diagnostics.append(f"[ERROR] {label}: DB-Name fehlt; übersprungen")
                fatal = True
                continue
            if _clean(row.get("status")).lower() != "active":
                diagnostics.append(f"[WARN] {label}: inaktiv; keine Datei erzeugt")
                continue

            slug = _slugify(name)
            previous = seen_slugs.get(slug)
            if previous is not None:
                diagnostics.append(
                    f"[ERROR] Namenskonflikt '{slug}': "
                    f"{previous.get('kind')} {previous.get('name')} vs. {label}; übersprungen"
                )
                fatal = True
                continue
            seen_slugs[slug] = row

            skill_path, skill_error = self._resolve_skill_path(row.get("path"))
            if skill_error:
                diagnostics.append(f"[ERROR] {label}: {skill_error}; übersprungen")
                fatal = True
                continue

            persona_file, persona_meta, persona_warning, persona_error = (
                self._find_persona_metadata(name, display_name)
            )
            if persona_warning:
                diagnostics.append(f"[WARN] {label}: {persona_warning}")
            if persona_error:
                diagnostics.append(f"[ERROR] {label}: {persona_error}; übersprungen")
                fatal = True
                continue

            skills = self._skills_for(row, skill_path, persona_meta)
            runtime = self._runtime_for(persona_meta)
            document = self._build_agent_document(
                row=row,
                slug=slug,
                display_name=display_name,
                skill_path=skill_path,
                persona_file=persona_file,
                skills=skills,
                runtime=runtime,
            )
            validation_errors = self.validate_agent_document(document)
            if validation_errors:
                diagnostics.extend(
                    f"[ERROR] {label}: Frontmatter/Datei ungültig: {error}"
                    for error in validation_errors
                )
                fatal = True
                continue
            candidates.append((row, slug, document))

        if not candidates:
            diagnostics.append("[ERROR] Keine exportierbare aktive Agent-/Expertenzeile gefunden")
            return False, "\n".join(diagnostics)

        written = 0
        unchanged = 0
        for row, slug, document in candidates:
            target = destination / f"{slug}.md"
            if target.exists():
                try:
                    current = target.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    diagnostics.append(f"[ERROR] Fremddatei {target} nicht lesbar: {exc}")
                    fatal = True
                    continue
                if current == document:
                    diagnostics.append(f"[OK] Unverändert vorhanden: {target}")
                    unchanged += 1
                else:
                    diagnostics.append(
                        f"[ERROR] Fremddatei-/Namenskonflikt: {target} existiert und wird nicht überschrieben"
                    )
                    fatal = True
                continue

            if dry_run:
                diagnostics.append(f"[DRY-RUN] Würde erzeugen: {target}")
                written += 1
                continue

            try:
                destination.mkdir(parents=True, exist_ok=True)
                # Exclusive creation is a second race-safe guard against a
                # foreign writer appearing after the existence check.
                with target.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(document)
                readback = target.read_text(encoding="utf-8")
                if readback != document:
                    diagnostics.append(f"[ERROR] Readback-Abweichung: {target}")
                    fatal = True
                    continue
                diagnostics.append(f"[OK] Erzeugt und gelesen: {target}")
                written += 1
            except FileExistsError:
                diagnostics.append(
                    f"[ERROR] Fremddatei-/Namenskonflikt: {target} erschien während des Exports; nicht überschrieben"
                )
                fatal = True
            except OSError as exc:
                diagnostics.append(f"[ERROR] Schreiben fehlgeschlagen {target}: {exc}")
                fatal = True

        diagnostics.append(
            f"[INFO] Ergebnis: {written} geplant/erzeugt, {unchanged} unverändert, "
            f"{len(candidates)} Kandidat(en), Ausgabe={'DRY-RUN' if dry_run else 'LIVE'}"
        )
        if fatal:
            diagnostics.append(
                "[WARN] Nicht exportierte Zeilen oder Konflikte wurden nicht automatisch bereinigt."
            )
        return not fatal, "\n".join(diagnostics)

    # Backwards-friendly descriptive alias for callers that do not use the
    # overloaded generate() method.
    export_agents = generate_agents

    def _resolve_output_dir(self, output_dir: Path | str | None) -> Path:
        if output_dir is None:
            return self.bach_root / DEFAULT_AGENT_OUTPUT
        candidate = Path(output_dir).expanduser()
        return candidate if candidate.is_absolute() else self.bach_root / candidate

    def _resolve_skill_path(self, raw_path: Any) -> tuple[Path | None, str | None]:
        raw = _clean(raw_path)
        if not raw:
            return None, "Skill-Pfad fehlt"
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            # DB paths historically use system-relative paths.  A root-relative
            # fallback makes temporary fixtures and newer exports convenient.
            system_candidate = self.system_root / candidate
            root_candidate = self.bach_root / candidate
            candidate = system_candidate if system_candidate.exists() else root_candidate
        if not candidate.exists():
            return None, f"Skill-Pfad fehlt: {raw}"
        if candidate.is_dir():
            skill_files = sorted(
                [path for path in candidate.iterdir() if path.is_file() and path.name.lower() == "skill.md"],
                key=lambda path: path.name.casefold(),
            )
            if not skill_files:
                return None, f"Skill-Pfad enthält keine SKILL.md: {raw}"
        return candidate, None

    def _find_persona_metadata(
        self, name: str, display_name: str
    ) -> tuple[Path | None, dict[str, Any] | None, str | None, str | None]:
        if not self.persona_dir.exists():
            return None, None, None, None
        matches: list[tuple[Path, dict[str, Any]]] = []
        name_fold = name.casefold()
        display_fold = display_name.casefold()
        for path in sorted(self.persona_dir.glob("*.md"), key=lambda item: item.name.casefold()):
            try:
                metadata = _parse_simple_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if not metadata:
                continue
            file_name = _clean(metadata.get("name"))
            file_display = _clean(_section_value(metadata, "persona", "display_name"))
            stem = path.stem.casefold()
            if file_name.casefold() == name_fold or stem == name_fold or file_display.casefold() == display_fold:
                matches.append((path, metadata))
        if len(matches) > 1:
            names = ", ".join(path.name for path, _ in matches)
            return None, None, None, f"mehrdeutige Persona-Dateien: {names}"
        if not matches:
            return None, None, None, None
        path, metadata = matches[0]
        file_name = _clean(metadata.get("name"))
        if file_name and file_name.casefold() != name_fold:
            return (
                None,
                None,
                None,
                f"Persona-Datei {path.name} nennt '{file_name}', DB nennt '{name}'",
            )
        file_display = _clean(_section_value(metadata, "persona", "display_name"))
        warning = None
        if file_display and file_display != display_name:
            warning = (
                f"Persona-Datei {path.name} weicht beim Display-Namen ab "
                f"('{file_display}' != '{display_name}'); DB wird verwendet"
            )
        return path, metadata, warning, None

    def _skills_for(
        self, row: dict[str, Any], skill_path: Path, persona_meta: dict[str, Any] | None
    ) -> list[str]:
        skills: list[str] = []
        raw_skills = persona_meta.get("skills") if persona_meta else None
        if isinstance(raw_skills, list):
            skills.extend(_clean(value) for value in raw_skills if _clean(value))
        elif raw_skills:
            skills.append(_clean(raw_skills))
        if not skills:
            # For a directory skill path the folder name is the most useful
            # portable identifier; a SKILL.md file uses its parent folder.
            source = skill_path if skill_path.is_dir() else skill_path.parent
            skills.append(source.name)
        # Stable de-duplication while preserving the metadata order.
        return list(dict.fromkeys(skills))

    def _runtime_for(self, persona_meta: dict[str, Any] | None) -> dict[str, Any]:
        if not persona_meta:
            return {}
        runtime = persona_meta.get("runtime")
        if not isinstance(runtime, dict):
            return {}
        result: dict[str, Any] = {}
        model = _clean(runtime.get("model"))
        if model and model.lower() not in {"null", "none"}:
            result["model"] = model
        max_turns = runtime.get("max_turns")
        if isinstance(max_turns, int) and max_turns > 0:
            result["maxTurns"] = max_turns
        tools = runtime.get("tools")
        if isinstance(tools, list):
            result["tools"] = [_clean(tool) for tool in tools if _clean(tool)]
        elif tools:
            result["tools"] = [_clean(tools)]
        return result

    def _build_agent_document(
        self,
        *,
        row: dict[str, Any],
        slug: str,
        display_name: str,
        skill_path: Path,
        persona_file: Path | None,
        skills: list[str],
        runtime: dict[str, Any],
    ) -> str:
        persona = _clean(row.get("persona"))
        description = _clean(row.get("description"))
        kind_label = "Boss-Agent" if row.get("kind") == "agent" else "Experte"
        role = _clean(row.get("type"))
        prompt_description = description or persona or f"{kind_label} {display_name}"
        if role:
            front_description = f"{display_name} ({role}) - {prompt_description}"
        else:
            front_description = f"{display_name} - {prompt_description}"

        frontmatter: list[str] = [
            "---",
            f"name: {slug}",
            f"description: {_yaml_quote(front_description)}",
        ]
        if runtime.get("model"):
            frontmatter.append(f"model: {_yaml_quote(runtime['model'])}")
        if runtime.get("maxTurns"):
            frontmatter.append(f"maxTurns: {runtime['maxTurns']}")
        if runtime.get("tools"):
            frontmatter.append(f"tools: {_yaml_list(runtime['tools'])}")
        if skills:
            frontmatter.append(f"skills: {_yaml_list(skills)}")
        frontmatter.append("---")

        source_path = _relative_display_path(skill_path, self.bach_root, self.system_root)
        persona_source = (
            _relative_display_path(persona_file, self.bach_root, self.system_root)
            if persona_file
            else "DB (keine Persona-Datei gefunden)"
        )
        body = [
            f"# {display_name}",
            "",
            f"Du bist {display_name}, ein {kind_label.lower()} von BACH.",
            "",
            "## Persona",
            "",
            persona or description or "Keine Persona-Beschreibung in der DB hinterlegt.",
            "",
            "## BACH-Quellen",
            "",
            f"- DB-Tabelle: `bach_{'agents' if row.get('kind') == 'agent' else 'experts'}`",
            f"- DB-Name: `{_clean(row.get('name'))}`",
            f"- Skill-/Pfadbezug: `{source_path}`",
            f"- Persona-Quelle: `{persona_source}`",
        ]
        if description and description != persona:
            body.extend(["", "## Aufgabenbezug", "", description])
        return "\n".join(frontmatter + [""] + body) + "\n"

    @staticmethod
    def validate_agent_document(document: str) -> list[str]:
        """Validate required/allowed frontmatter and basic Markdown shape."""

        block = _frontmatter_block(document)
        if block is None:
            return ["YAML-Frontmatter fehlt oder ist nicht abgeschlossen"]
        metadata = _parse_simple_frontmatter(document)
        if metadata is None:
            return ["YAML-Frontmatter konnte nicht gelesen werden"]
        errors: list[str] = []
        unknown = set(metadata) - ALLOWED_AGENT_FRONTMATTER
        if unknown:
            errors.append(f"nicht erlaubte Felder: {', '.join(sorted(unknown))}")
        missing = REQUIRED_AGENT_FRONTMATTER - set(metadata)
        if missing:
            errors.append(f"Pflichtfelder fehlen: {', '.join(sorted(missing))}")
        name = _clean(metadata.get("name"))
        if name and not VALID_AGENT_NAME.fullmatch(name):
            errors.append("name muss lowercase mit Bindestrichen sein")
        if "description" in metadata and not _clean(metadata.get("description")):
            errors.append("description darf nicht leer sein")
        body = document.replace("\r\n", "\n").split("\n---\n", 1)
        if len(body) != 2 or not body[1].strip():
            errors.append("System-Prompt/Body fehlt")
        return errors

    # ------------------------------------------------------------------
    # Legacy Markdown rendering (unchanged text contract)
    # ------------------------------------------------------------------

    def _build_content(self, agents: list[dict], experts: list[dict]) -> str:
        """Build AGENTS.md content (legacy renderer)."""

        lines = []
        lines.append("# BACH Agents & Experts")
        lines.append("")
        lines.append(f"**Generiert:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("**Quelle:** bach.db (bach_agents, bach_experts)")
        lines.append("**Generator:** `bach export mirrors` oder `python tools/agents_export.py`")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Boss-Agenten (Orchestrierer)")
        lines.append("")
        lines.append("Boss-Agenten orchestrieren komplexe Workflows und delegieren an Experten.")
        lines.append("")

        for agent in agents:
            display = agent.get("display_name") or agent["name"]
            lines.append(f"### {display}")
            lines.append(f"- **Name:** {agent['name']}")
            lines.append(f"- **Typ:** {agent['type']}")
            lines.append(f"- **Kategorie:** {agent.get('category', 'N/A')}")
            lines.append(f"- **Pfad:** `{agent['path']}`")
            lines.append(f"- **Status:** {agent['status']}")
            lines.append(f"- **Version:** {agent.get('version', 'N/A')}")
            if agent.get("description"):
                lines.append(f"- **Beschreibung:** {agent['description']}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Experten (Spezialisierte Ausführer)")
        lines.append("")
        lines.append("Experten führen spezifische Aufgaben aus und werden von Boss-Agenten delegiert.")
        lines.append("")

        for expert in experts:
            display = expert.get("display_name") or expert["name"]
            lines.append(f"### {display}")
            lines.append(f"- **Name:** {expert['name']}")
            lines.append(f"- **Domain:** {expert['type']}")
            lines.append(f"- **Pfad:** `{expert['path']}`")
            lines.append(f"- **Status:** {expert['status']}")
            lines.append(f"- **Version:** {expert.get('version', 'N/A')}")
            if expert.get("description"):
                lines.append(f"- **Beschreibung:** {expert['description']}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Status-Kategorien")
        lines.append("")
        lines.append("- **FUNCTIONAL:** Voll funktionsfähig, produktionsbereit")
        lines.append("- **PARTIAL:** Grundfunktionen vorhanden, aber unvollständig")
        lines.append("- **SKELETON:** Struktur vorhanden, aber Implementierung fehlt weitgehend")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Charakter-Modell (ENT-41)")
        lines.append("")
        lines.append("Jeder Boss-Agent hat eine `## Charakter` Section in seiner SKILL.md:")
        lines.append("- **Ton:** Wie kommuniziert der Agent?")
        lines.append("- **Schwerpunkt:** Woran orientiert er sich?")
        lines.append("- **Haltung:** Welche Werte vertritt er?")
        lines.append("")
        lines.append("Siehe: BACH_Dev/MASTERPLAN_PENDING.txt → SQ049 Agenten-Audit & Upgrade")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Arbeitsprinzipien")
        lines.append("")
        lines.append("Alle Agenten folgen den globalen Arbeitsprinzipien aus Root-SKILL.md:")
        lines.append("- Unterscheiden was eigen, was fremd")
        lines.append("- Text ist Wahrheit")
        lines.append("- Erst lesen, dann ändern")
        lines.append("- Keine Duplikate erzeugen")
        lines.append("- Flexibel auf User-Korrekturen reagieren")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Nutzung")
        lines.append("")
        lines.append("```bash")
        lines.append("# Boss-Agent starten (mit Partner-Delegation)")
        lines.append("bach agent start bueroassistent --partner=claude-code")
        lines.append("")
        lines.append("# Experten direkt aufrufen (falls erlaubt)")
        lines.append('bach expert run bewerbungsexperte --task="Anschreiben für Stelle X"')
        lines.append("")
        lines.append("# Agent-Liste anzeigen")
        lines.append("bach agent list")
        lines.append("")
        lines.append("# Expert-Liste anzeigen")
        lines.append("bach expert list")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Datei-Synchronisation")
        lines.append("")
        lines.append("Diese Datei wird automatisch generiert aus:")
        lines.append("- `bach_agents` (Tabelle für Boss-Agenten)")
        lines.append("- `bach_experts` (Tabelle für Experten)")
        lines.append("")
        lines.append("**Trigger:**")
        lines.append("- `bach --shutdown` (via finalize_on_idle)")
        lines.append("- `bach export mirrors` (manuell)")
        lines.append("")
        lines.append("**dist_type:** 1 (TEMPLATE) - resetbar, aber anpassbar")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Siehe auch")
        lines.append("")
        lines.append("- **PARTNERS.md** - LLM-Partner und Delegation")
        lines.append("- **USECASES.md** - Anwendungsfälle")
        lines.append("- **WORKFLOWS.md** - 25 Protocol-Skills als Index")
        lines.append("- **CHAINS.md** - Toolchains")
        lines.append("")

        return "\n".join(lines)


def main() -> int:
    """CLI for the agents exporter."""

    parser = argparse.ArgumentParser(description="BACH Agent-/Persona-Export")
    parser.add_argument(
        "--format",
        choices=("markdown", "agent"),
        default="markdown",
        help="markdown=historische AGENTS.md, agent=Claude-Code-Dateien",
    )
    parser.add_argument("--output", "-o", help="Ausgabeordner für --format agent")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Nur prüfen/auflisten, nichts schreiben")
    parser.add_argument("--db", help="Optionale Test-/Fixture-Datenbank")
    parser.add_argument("--root", help="BACH-Root für relative Skill-/Persona-Pfade")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.parent  # system/
    bach_root = Path(args.root).expanduser() if args.root else script_dir.parent
    exporter = AgentsExporter(bach_root, db_path=Path(args.db) if args.db else None)
    success, message = exporter.generate(
        format=args.format,
        output_dir=args.output,
        dry_run=args.dry_run,
    )
    print(message)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
