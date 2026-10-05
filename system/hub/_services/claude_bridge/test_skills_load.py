#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Test-Skript für _load_startup_skills()
"""
import sys
from pathlib import Path

# BACH_DIR setzen
BRIDGE_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = BRIDGE_DIR.parent
HUB_DIR = SERVICES_DIR.parent
SYSTEM_DIR = HUB_DIR.parent
BACH_DIR = SYSTEM_DIR.parent  # wie skill_loader.py: 5x parent -> /Users/lukas/services/bach

# Log-Funktion (vereinfacht)
def log(msg: str, level: str = "INFO"):
    print(f"[{level}] {msg}")

# Skills-Lader
def _load_startup_skills() -> str:
    """Lädt SKILL.md + persoenlicher-assistent beim Start."""
    skills = []

    # 1. SKILL.md (root)
    root_skill = BACH_DIR / "SKILL.md"
    if root_skill.exists():
        try:
            content = root_skill.read_text(encoding='utf-8')
            skills.append(f"### SKILL.md (Root-Skill)\n{content}")
            log("SKILL.md geladen", "INFO")
        except Exception as e:
            log(f"SKILL.md lesen fehlgeschlagen: {e}", "WARN")
    else:
        log("SKILL.md nicht gefunden", "WARN")

    # 2. Persönlicher Assistent
    assistant_skill = BACH_DIR / "system" / "agents" / "persoenlicher-assistent" / "SKILL.md"
    if assistant_skill.exists():
        try:
            content = assistant_skill.read_text(encoding='utf-8')
            skills.append(f"### Persönlicher Assistent\n{content}")
            log("persoenlicher-assistent SKILL.md geladen", "INFO")
        except Exception as e:
            log(f"persoenlicher-assistent SKILL.md lesen fehlgeschlagen: {e}", "WARN")
    else:
        # Fallback: skills/persoenlicher-assistent.txt (alte Struktur)
        assistant_skill_alt = BACH_DIR / "skills" / "persoenlicher-assistent.txt"
        if assistant_skill_alt.exists():
            try:
                content = assistant_skill_alt.read_text(encoding='utf-8')
                skills.append(f"### Persönlicher Assistent\n{content}")
                log("skills/persoenlicher-assistent.txt geladen", "INFO")
            except Exception as e:
                log(f"skills/persoenlicher-assistent.txt lesen fehlgeschlagen: {e}", "WARN")
        else:
            # Fallback 2: agents/persoenlicher-assistent.txt
            assistant_skill_alt2 = BACH_DIR / "agents" / "persoenlicher-assistent.txt"
            if assistant_skill_alt2.exists():
                try:
                    content = assistant_skill_alt2.read_text(encoding='utf-8')
                    skills.append(f"### Persönlicher Assistent\n{content}")
                    log("agents/persoenlicher-assistent.txt geladen", "INFO")
                except Exception as e:
                    log(f"agents/persoenlicher-assistent.txt lesen fehlgeschlagen: {e}", "WARN")

    if not skills:
        return "# Keine Skills geladen (SKILL.md fehlt)"

    return "\n\n".join(skills)


if __name__ == "__main__":
    print("=" * 60)
    print("TEST: _load_startup_skills()")
    print("=" * 60)
    print(f"BACH_DIR: {BACH_DIR}")
    print("=" * 60)

    result = _load_startup_skills()

    print("\n=== ERGEBNIS ===")
    print(f"Länge: {len(result)} Zeichen")
    print("\n=== VORSCHAU (erste 800 Zeichen) ===")
    print(result[:800])
    print("\n=== ENDE ===")
