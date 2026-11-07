# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Standalone Skills Module
Autarker Skill-Katalog und Frontmatter-Parser für BACH und Ocean.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class SkillMetadata:
    name: str
    version: str = "1.0.0"
    type: str = "skill"
    description: str = ""
    author: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    path: str = ""
    tools: list[str] = field(default_factory=list)
    prompt_template: str = ""
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class SkillRegistry:
    """Autarker Skill-Katalog für BACH und Ocean."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillMetadata] = {}

    def parse_skill_markdown(self, path_or_content: str | Path) -> tuple[bool, dict[str, Any]]:
        """Extrahiert Frontmatter und Metadaten aus SKILL.md."""
        try:
            content = ""
            file_path = ""
            if isinstance(path_or_content, Path) or (isinstance(path_or_content, str) and "\n" not in path_or_content and Path(path_or_content).is_file()):
                p = Path(path_or_content)
                file_path = str(p.resolve())
                content = p.read_text(encoding="utf-8")
            else:
                content = str(path_or_content)

            metadata: dict[str, Any] = {}
            body = content

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm_text = parts[1]
                    body = parts[2].strip()
                    for line in fm_text.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k = k.strip().lower()
                            v = v.strip()
                            if v.startswith("[") and v.endswith("]"):
                                items = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
                                metadata[k] = items
                            elif v.lower() in ("true", "yes"):
                                metadata[k] = True
                            elif v.lower() in ("false", "no"):
                                metadata[k] = False
                            else:
                                metadata[k] = v.strip("'\"")

            name = metadata.get("name") or (Path(file_path).parent.name if file_path else "unnamed_skill")
            return True, {
                "name": name,
                "version": metadata.get("version", "1.0.0"),
                "type": metadata.get("type", "skill"),
                "description": metadata.get("description", ""),
                "author": metadata.get("author", ""),
                "category": metadata.get("category", "general"),
                "tags": metadata.get("tags", []),
                "path": file_path,
                "body": body,
            }
        except Exception as exc:
            return False, {"error": str(exc)}

    def register_skill(self, skill: SkillMetadata | dict[str, Any]) -> bool:
        """Registriert einen Skill."""
        if isinstance(skill, dict):
            name = skill.get("name")
            if not name:
                return False
            meta = SkillMetadata(
                name=name,
                version=skill.get("version", "1.0.0"),
                type=skill.get("type", "skill"),
                description=skill.get("description", ""),
                author=skill.get("author", ""),
                category=skill.get("category", "general"),
                tags=list(skill.get("tags", [])),
                path=skill.get("path", ""),
                tools=list(skill.get("tools", [])),
                prompt_template=skill.get("prompt_template", ""),
                enabled=bool(skill.get("enabled", True)),
            )
        else:
            meta = skill

        self._skills[meta.name] = meta
        return True

    def discover_skills(self, root_dir: str | Path) -> list[SkillMetadata]:
        """Sucht rekursiv nach SKILL.md-Dateien und registriert sie."""
        found = []
        p = Path(root_dir)
        if not p.is_dir():
            return found

        for skill_file in p.rglob("SKILL.md"):
            ok, data = self.parse_skill_markdown(skill_file)
            if ok and data.get("name"):
                meta = SkillMetadata(
                    name=data["name"],
                    version=data.get("version", "1.0.0"),
                    type=data.get("type", "skill"),
                    description=data.get("description", ""),
                    author=data.get("author", ""),
                    category=data.get("category", "general"),
                    tags=data.get("tags", []),
                    path=data.get("path", str(skill_file)),
                    prompt_template=data.get("body", "")[:200],
                )
                self.register_skill(meta)
                found.append(meta)
        return found

    def get_skill(self, name: str) -> Optional[SkillMetadata]:
        return self._skills.get(name)

    def list_skills(self, category: Optional[str] = None, tag: Optional[str] = None, enabled_only: bool = False) -> list[SkillMetadata]:
        res = list(self._skills.values())
        if category:
            res = [s for s in res if s.category.lower() == category.lower()]
        if tag:
            res = [s for s in res if any(t.lower() == tag.lower() for t in s.tags)]
        if enabled_only:
            res = [s for s in res if s.enabled]
        return res

    def search_skills(self, query: str) -> list[SkillMetadata]:
        q = query.lower()
        res = []
        for s in self._skills.values():
            if q in s.name.lower() or q in s.description.lower() or any(q in t.lower() for t in s.tags):
                res.append(s)
        return res

    def enable_skill(self, name: str) -> bool:
        if name in self._skills:
            self._skills[name].enabled = True
            return True
        return False

    def disable_skill(self, name: str) -> bool:
        if name in self._skills:
            self._skills[name].enabled = False
            return True
        return False
