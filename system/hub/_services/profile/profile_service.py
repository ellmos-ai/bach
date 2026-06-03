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
BACH Profile Service
====================
Laedt User-Profil aus profile.json und merged mit DB-Overrides
aus assistant_user_profile. Stellt Prompt-Kontext bereit.

Tabelle: assistant_user_profile (category, key, value, confidence, learned_from)
JSON:    user/profile.json (stats, traits, values, goals, preferences)
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any


class ProfileService:
    """Laedt, merged und liefert User-Profildaten fuer Prompts und Anzeige."""

    def __init__(self, profile_path: Path, db_path: Path):
        """
        Args:
            profile_path: Pfad zu user/profile.json (PROJECT ROOT, nicht system/)
            db_path: Pfad zur kanonischen BACH-Datenbank (BACH_DB)
        """
        self.profile_path = Path(profile_path)
        self.db_path = Path(db_path)
        self._cache: Optional[dict] = None

    # =========================================================================
    # LOAD / MERGE
    # =========================================================================

    def load_profile(self) -> dict:
        """Laedt profile.json und merged mit DB-Overrides.

        Prioritaet: DB-Werte ueberschreiben JSON-Werte (DB = gelernt/aktueller).

        Returns:
            Gemergtes Profil-Dict
        """
        # 1. JSON laden
        profile = self._load_json()

        # 2. DB-Overrides laden und mergen
        db_overrides = self._load_db_overrides()
        if db_overrides:
            profile = self._merge_overrides(profile, db_overrides)

        self._cache = profile
        return profile

    def _load_json(self) -> dict:
        """Laedt profile.json."""
        if self.profile_path.exists():
            try:
                return json.loads(self.profile_path.read_text(encoding='utf-8'))
            except Exception as e:
                print(f"[WARN] profile.json laden fehlgeschlagen: {e}")
        return {}

    def _load_db_overrides(self) -> list:
        """Laedt alle Eintraege aus assistant_user_profile.

        Returns:
            Liste von (category, key, value, confidence) Tupeln
        """
        if not self.db_path.exists():
            return []
        try:
            conn = sqlite3.connect(str(self.db_path))
            rows = conn.execute(
                "SELECT category, key, value, confidence FROM assistant_user_profile"
            ).fetchall()
            conn.close()
            return rows
        except Exception:
            return []

    def _merge_overrides(self, profile: dict, overrides: list) -> dict:
        """Merged DB-Overrides in das Profil.

        DB-Kategorien mappen auf JSON-Struktur:
          - 'trait'       -> profile['traits'][key] = value
          - 'value'       -> profile['values'] (append if not present)
          - 'preference'  -> profile['preferences'][key] = value
          - 'stat'        -> profile['stats'][key] = value
          - 'goal'        -> profile['goals']['learned'][key] = value
          - andere        -> profile['db_overrides'][category][key] = value
        """
        for category, key, value, confidence in overrides:
            if category == 'trait':
                profile.setdefault('traits', {})[key] = value
            elif category == 'value':
                vals = profile.setdefault('values', [])
                if value and value not in vals:
                    vals.append(value)
            elif category == 'preference':
                profile.setdefault('preferences', {})[key] = value
            elif category == 'stat':
                profile.setdefault('stats', {})[key] = value
            elif category == 'goal':
                profile.setdefault('goals', {}).setdefault('learned', {})[key] = value
            else:
                # Generische Kategorie -> db_overrides bucket
                profile.setdefault('db_overrides', {}).setdefault(category, {})[key] = value
        return profile

    # =========================================================================
    # GETTERS
    # =========================================================================

    def _get_profile(self) -> dict:
        """Cached profile loader."""
        if self._cache is None:
            self.load_profile()
        return self._cache or {}

    def get_stats(self) -> dict:
        """Return stats dict (name, role, language, etc.)."""
        return self._get_profile().get('stats', {})

    def get_traits(self) -> dict:
        """Return traits dict (communication_style, detail_preference, etc.)."""
        return self._get_profile().get('traits', {})

    def get_values(self) -> list:
        """Return values list."""
        return self._get_profile().get('values', [])

    def get_goals(self) -> dict:
        """Return goals dict."""
        return self._get_profile().get('goals', {})

    def get_preferences(self) -> dict:
        """Return preferences dict."""
        return self._get_profile().get('preferences', {})

    # =========================================================================
    # PROMPT CONTEXT (max ~200 tokens)
    # =========================================================================

    def get_prompt_context(self) -> str:
        """Erzeugt einen kompakten Textblock fuer LLM-Prompt-Injektion.

        Format (deutsch, max ~200 Tokens):
          USER-PROFIL:
          - Name: User | Rolle: Lead Developer
          - Kommunikation: direkt, hoher Detailgrad, technisch expert
          - Werte: Privacy First, Local Execution, Open Source, Zero Dependencies
          - Coding: Python, clean/documented/typed, standard-lib
          - Assistent: proaktiv, professional but friendly
          - Ziele: BACH v2 stabilization, Full digital sovereignty
        """
        p = self._get_profile()
        if not p:
            return ""

        lines = ["USER-PROFIL:"]

        # Stats
        stats = p.get('stats', {})
        name = stats.get('name', '?')
        role = stats.get('role', '')
        lang = stats.get('language', '')
        stat_parts = [f"Name: {name}"]
        if role:
            stat_parts.append(f"Rolle: {role}")
        if lang:
            stat_parts.append(f"Sprache: {lang}")
        lines.append("- " + " | ".join(stat_parts))

        # Traits
        traits = p.get('traits', {})
        if traits:
            trait_str = ", ".join(f"{v}" for v in traits.values())
            lines.append(f"- Kommunikation: {trait_str}")

        # Values
        values = p.get('values', [])
        if values:
            lines.append(f"- Werte: {', '.join(values)}")

        # Preferences -> coding + assistant
        prefs = p.get('preferences', {})
        coding = prefs.get('coding', {})
        if coding:
            parts = []
            if coding.get('language'):
                parts.append(coding['language'])
            if coding.get('style'):
                parts.append(coding['style'])
            if coding.get('frameworks'):
                parts.append(', '.join(coding['frameworks']))
            if parts:
                lines.append(f"- Coding: {', '.join(parts)}")

        assistant = prefs.get('assistant', {})
        if assistant:
            parts = []
            if assistant.get('proactiveness'):
                parts.append(f"Proaktivitaet: {assistant['proactiveness']}")
            if assistant.get('tone'):
                parts.append(assistant['tone'])
            if parts:
                lines.append(f"- Assistent: {', '.join(parts)}")

        # Goals (kurz)
        goals = p.get('goals', {})
        short = goals.get('short_term', [])
        long_g = goals.get('long_term', [])
        all_goals = short[:2] + long_g[:1]  # Max 3 Ziele
        if all_goals:
            lines.append(f"- Ziele: {', '.join(all_goals)}")

        return "\n".join(lines)

    # =========================================================================
    # STARTUP SUMMARY (einzeilig fuer Konsole)
    # =========================================================================

    def get_startup_summary(self) -> str:
        """Einzeilige Zusammenfassung fuer Startup-Anzeige.

        Returns:
            z.B. "[PROFIL] User: User | Stil: direkt, technisch | Werte: Privacy First, Local"
        """
        p = self._get_profile()
        if not p:
            return "[PROFIL] Kein Profil geladen"

        stats = p.get('stats', {})
        traits = p.get('traits', {})
        values = p.get('values', [])

        name = stats.get('name', '?')
        style_parts = []
        if traits.get('communication_style'):
            style_parts.append(traits['communication_style'])
        if traits.get('technical_depth'):
            style_parts.append(traits['technical_depth'])
        style = ", ".join(style_parts) if style_parts else "?"

        val_str = ", ".join(values[:2]) if values else "?"

        return f"[PROFIL] User: {name} | Stil: {style} | Werte: {val_str}"

    # =========================================================================
    # DB WRITE
    # =========================================================================

    def update_trait(self, key: str, value: str, confidence: str = "mittel", source: str = "observation"):
        """Schreibt einen Trait in die assistant_user_profile DB-Tabelle.

        Args:
            key: Trait-Schluessel (z.B. 'humor_style')
            value: Trait-Wert (z.B. 'trocken')
            confidence: 'niedrig' | 'mittel' | 'hoch'
            source: Woher die Info stammt (z.B. 'observation', 'user_stated')
        """
        self._upsert_db('trait', key, value, confidence, source)

    def _upsert_db(self, category: str, key: str, value: str,
                   confidence: str = "mittel", source: str = "sync"):
        """Insert or Update in assistant_user_profile."""
        if not self.db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO assistant_user_profile (category, key, value, confidence, learned_from, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    learned_from = excluded.learned_from,
                    updated_at = excluded.updated_at
            """, (category, key, value, confidence, source, now, now))
            conn.commit()
            conn.close()
            # Cache invalidieren
            self._cache = None
        except Exception as e:
            print(f"[WARN] Profile DB write fehlgeschlagen: {e}")

    # =========================================================================
    # SYNC FROM JSON -> DB
    # =========================================================================

    def sync_from_json(self) -> dict:
        """Synchronisiert profile.json in die assistant_user_profile DB-Tabelle.

        Idempotent: Kann bei jedem Startup aufgerufen werden.
        Ueberschreibt nur wenn DB-Eintrag noch nicht existiert ODER
        learned_from='sync' ist (also nicht manuell gelernt).

        Returns:
            Dict mit synced/skipped/errors Zaehler
        """
        result = {"synced": 0, "skipped": 0, "errors": 0}
        profile = self._load_json()
        if not profile:
            return result

        if not self.db_path.exists():
            result["errors"] = 1
            return result

        try:
            conn = sqlite3.connect(str(self.db_path))
            now = datetime.now().isoformat()

            # Stats -> category='stat'
            for key, value in profile.get('stats', {}).items():
                if self._sync_row(conn, 'stat', key, str(value), now):
                    result["synced"] += 1
                else:
                    result["skipped"] += 1

            # Traits -> category='trait'
            for key, value in profile.get('traits', {}).items():
                if self._sync_row(conn, 'trait', key, str(value), now):
                    result["synced"] += 1
                else:
                    result["skipped"] += 1

            # Values -> category='value', key='value_N'
            for i, value in enumerate(profile.get('values', [])):
                key = f"value_{i}"
                if self._sync_row(conn, 'value', key, str(value), now):
                    result["synced"] += 1
                else:
                    result["skipped"] += 1

            # Preferences -> category='preference'
            prefs = profile.get('preferences', {})
            for section, section_data in prefs.items():
                if isinstance(section_data, dict):
                    for key, value in section_data.items():
                        pref_key = f"{section}.{key}"
                        pref_value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
                        if self._sync_row(conn, 'preference', pref_key, pref_value, now):
                            result["synced"] += 1
                        else:
                            result["skipped"] += 1

            # Goals -> category='goal'
            goals = profile.get('goals', {})
            for goal_type, goal_list in goals.items():
                if isinstance(goal_list, list):
                    for i, goal in enumerate(goal_list):
                        goal_key = f"{goal_type}_{i}"
                        if self._sync_row(conn, 'goal', goal_key, str(goal), now):
                            result["synced"] += 1
                        else:
                            result["skipped"] += 1

            conn.commit()
            conn.close()
            # Cache invalidieren
            self._cache = None
        except Exception as e:
            print(f"[WARN] Profile sync fehlgeschlagen: {e}")
            result["errors"] += 1

        return result

    def _sync_row(self, conn: sqlite3.Connection, category: str, key: str,
                  value: str, now: str) -> bool:
        """Synct eine einzelne Zeile. Ueberschreibt nur sync-Eintraege.

        Returns:
            True wenn geschrieben, False wenn uebersprungen
        """
        # Pruefen ob manuell gelernter Eintrag existiert
        existing = conn.execute(
            "SELECT learned_from FROM assistant_user_profile WHERE category=? AND key=?",
            (category, key)
        ).fetchone()

        if existing and existing[0] != 'sync':
            # Manuell gelernt -> nicht ueberschreiben
            return False

        conn.execute("""
            INSERT INTO assistant_user_profile (category, key, value, confidence, learned_from, created_at, updated_at)
            VALUES (?, ?, ?, 'hoch', 'sync', ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                learned_from = excluded.learned_from,
                updated_at = excluded.updated_at
        """, (category, key, value, now, now))
        return True

    # =========================================================================
    # RPG CHARACTER CARD
    # =========================================================================

    def get_rpg_card(self) -> str:
        """Generiert eine RPG-Style Character Card als Text.

        Returns:
            Mehrzeiliger Text im RPG-Charakter-Format
        """
        p = self._get_profile()
        if not p:
            return "[Kein Profil geladen]"

        stats = p.get('stats', {})
        traits = p.get('traits', {})
        values = p.get('values', [])
        goals = p.get('goals', {})
        prefs = p.get('preferences', {})

        name = stats.get('name', 'Unknown')
        role = stats.get('role', 'Adventurer')

        lines = []
        lines.append("+" + "=" * 50 + "+")
        lines.append(f"|{'CHARACTER SHEET':^50}|")
        lines.append("+" + "=" * 50 + "+")
        lines.append(f"| Name:  {name:<42}|")
        lines.append(f"| Class: {role:<42}|")
        lines.append(f"| Lang:  {stats.get('language', '?'):<42}|")
        lines.append(f"| OS:    {stats.get('os', '?'):<42}|")
        lines.append("+" + "-" * 50 + "+")

        # Traits as stats
        lines.append(f"|{'TRAITS':^50}|")
        lines.append("+" + "-" * 50 + "+")
        trait_map = {
            'communication_style': 'COM',
            'detail_preference': 'DET',
            'technical_depth': 'TEC'
        }
        for key, abbr in trait_map.items():
            val = traits.get(key, '?')
            bar_len = {'direct': 8, 'high': 9, 'expert': 10, 'medium': 6, 'low': 3}.get(val, 5)
            bar = '#' * bar_len + '.' * (10 - bar_len)
            lines.append(f"| {abbr}: [{bar}] {val:<33}|")

        # Values
        lines.append("+" + "-" * 50 + "+")
        lines.append(f"|{'VALUES':^50}|")
        lines.append("+" + "-" * 50 + "+")
        for v in values:
            lines.append(f"|  * {v:<46}|")

        # Goals
        lines.append("+" + "-" * 50 + "+")
        lines.append(f"|{'QUEST LOG':^50}|")
        lines.append("+" + "-" * 50 + "+")
        for g in goals.get('short_term', []):
            lines.append(f"|  [ACTIVE] {g:<38}|")
        for g in goals.get('long_term', []):
            lines.append(f"|  [EPIC]   {g:<38}|")

        # Preferences
        lines.append("+" + "-" * 50 + "+")
        lines.append(f"|{'EQUIPMENT':^50}|")
        lines.append("+" + "-" * 50 + "+")
        coding = prefs.get('coding', {})
        if coding.get('language'):
            lines.append(f"|  Weapon:  {coding['language']:<39}|")
        if coding.get('style'):
            lines.append(f"|  Style:   {coding['style']:<39}|")
        if coding.get('frameworks'):
            fw = ', '.join(coding['frameworks'])
            lines.append(f"|  Toolkit: {fw:<39}|")

        lines.append("+" + "=" * 50 + "+")

        return "\n".join(lines)
