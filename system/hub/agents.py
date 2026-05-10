# SPDX-License-Identifier: MIT
"""
Agents Handler - Agenten-Verwaltung
===================================

--agents list        Alle Agenten auflisten
--agents info <n>    Agenten-Details
--agents active      Nur aktive Agenten
--agents rename <n> <display_name>  Display-Name aendern
"""
import sqlite3
from pathlib import Path
from .base import BaseHandler
from .lang import get_lang, t

# Pfade aus zentraler Konfiguration (Single Source of Truth)
# Fallback falls bach_paths nicht importierbar
try:
    from .bach_paths import AGENTS_DIR as _AGENTS_DIR, EXPERTS_DIR as _EXPERTS_DIR
    _PATHS_FROM_BACH = True
except ImportError:
    _AGENTS_DIR = None
    _EXPERTS_DIR = None
    _PATHS_FROM_BACH = False


def resolve_agent_name(db_path, query: str) -> dict:
    """
    Loest einen Agenten/Experten ueber mehrere Strategien auf.

    Sucht in dieser Reihenfolge:
    1. Exakter technischer Name (name)
    2. Exakter Display-Name (display_name)
    3. Substring in name, display_name oder description
    4. Fuzzy-Match (Levenshtein-Distanz <= 2)

    Args:
        db_path: Pfad zur bach.db
        query: Suchbegriff (Name, Display-Name, Beschreibung)

    Returns:
        dict mit keys: name, display_name, persona, description, type, source_table
        oder None wenn nicht gefunden
    """
    if not db_path or not Path(db_path).exists():
        return None

    query_lower = query.lower().strip()
    if not query_lower:
        return None

    def _levenshtein(s1: str, s2: str) -> int:
        """Einfache Levenshtein-Distanz."""
        if len(s1) < len(s2):
            return _levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Strategie 1+2+3: Exakt name, exakt display_name, Substring
        for table, type_label in [('bach_agents', 'boss'), ('bach_experts', 'expert')]:
            try:
                cursor.execute(f"""
                    SELECT name, display_name, persona, description
                    FROM {table}
                    WHERE LOWER(name) = ?
                       OR LOWER(display_name) = ?
                       OR LOWER(name) LIKE ?
                       OR LOWER(display_name) LIKE ?
                       OR LOWER(COALESCE(description, '')) LIKE ?
                       OR LOWER(COALESCE(persona, '')) LIKE ?
                    ORDER BY
                        CASE WHEN LOWER(name) = ? THEN 0
                             WHEN LOWER(display_name) = ? THEN 1
                             WHEN LOWER(name) LIKE ? THEN 2
                             WHEN LOWER(display_name) LIKE ? THEN 3
                             ELSE 4 END
                    LIMIT 1
                """, (query_lower, query_lower,
                      f'%{query_lower}%', f'%{query_lower}%',
                      f'%{query_lower}%', f'%{query_lower}%',
                      query_lower, query_lower,
                      f'%{query_lower}%', f'%{query_lower}%'))
                row = cursor.fetchone()
                if row:
                    conn.close()
                    return {
                        'name': row['name'],
                        'display_name': row['display_name'] or row['name'],
                        'persona': row['persona'] or '',
                        'description': row['description'] if 'description' in row.keys() else '',
                        'type': type_label,
                        'source_table': table,
                    }
            except sqlite3.OperationalError:
                continue

        # Strategie 4: Fuzzy-Match (Levenshtein <= 2)
        best_match = None
        best_dist = 3  # Maximal akzeptierte Distanz
        for table, type_label in [('bach_agents', 'boss'), ('bach_experts', 'expert')]:
            try:
                cursor.execute(f"SELECT name, display_name, persona, description FROM {table}")
                for row in cursor.fetchall():
                    for field in [row['name'], row['display_name']]:
                        if not field:
                            continue
                        dist = _levenshtein(query_lower, field.lower())
                        if dist < best_dist:
                            best_dist = dist
                            best_match = {
                                'name': row['name'],
                                'display_name': row['display_name'] or row['name'],
                                'persona': row['persona'] or '',
                                'description': row['description'] if 'description' in row.keys() else '',
                                'type': type_label,
                                'source_table': table,
                            }
            except sqlite3.OperationalError:
                continue

        conn.close()
        return best_match
    except Exception:
        pass
    return None


class AgentsHandler(BaseHandler):
    """Handler fuer --agents Operationen"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        # Pfade: aus bach_paths oder Fallback relativ zu base_path
        self.agents_dir = _AGENTS_DIR if _PATHS_FROM_BACH else base_path / "agents"
        self.experts_dir = _EXPERTS_DIR if _PATHS_FROM_BACH else base_path / "agents" / "_experts"

    @property
    def profile_name(self) -> str:
        return "agents"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": t("agents_list_desc", default="Alle Agenten und Experten auflisten"),
            "info": t("agents_info_desc", default="Agenten-Details anzeigen"),
            "active": t("agents_active_desc", default="Nur aktive Agenten"),
            "sync": t("agents_sync_desc", default="Neue Filesystem-Experten automatisch in DB eintragen"),
            "rename": t("agents_rename_desc", default="Display-Name aendern (--agents rename <name> <neuer-name>)"),
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.db_path.exists():
            return False, t("db_not_found", default="Datenbank nicht gefunden")

        if operation == "info" and args:
            return self._info(args[0])
        elif operation == "rename" and args:
            if len(args) < 2:
                return False, t("agents_rename_syntax_error", default="[ERROR] Syntax: --agents rename <name> <neuer-display-name>")
            return self._rename(args[0], " ".join(args[1:]))
        elif operation == "active":
            return self._list(active_only=True)
        elif operation == "sync":
            return self._sync(dry_run=dry_run)
        else:
            return self._list(active_only=False)

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _scan_filesystem(self) -> tuple:
        """
        Scannt Filesystem nach Boss-Agenten und Experten.

        Boss-Agenten:  agents/*/SKILL.md  (Unterordner ohne fuehrendes _)
        Experten:      agents/_experts/*/CONCEPT.md  (nur Status: AKTIV)

        Pfade kommen aus bach_paths.py (Single Source of Truth).

        Returns:
            (boss_agents, experts) - beide als dict {key: entry}
        """
        boss_agents = {}
        experts = {}

        # --- Boss-Agenten ---
        if self.agents_dir and self.agents_dir.exists():
            for subdir in sorted(self.agents_dir.iterdir()):
                # Nur echte Unterordner, keine _* Systemordner, keine Dateien
                if not subdir.is_dir() or subdir.name.startswith('_'):
                    continue
                skill_file = subdir / "SKILL.md"
                if skill_file.exists():
                    key = subdir.name.lower()
                    boss_agents[key] = {
                        'name': subdir.name,
                        'file': skill_file,
                        'in_db': False,
                        'is_active': False,
                        'type': 'boss',
                    }

        # --- Experten ---
        if self.experts_dir and self.experts_dir.exists():
            for subdir in sorted(self.experts_dir.iterdir()):
                if not subdir.is_dir() or subdir.name.startswith('_'):
                    continue
                concept = subdir / "CONCEPT.md"
                if not concept.exists():
                    continue
                # Status aus Datei lesen
                try:
                    content = concept.read_text(encoding='utf-8', errors='ignore')
                    aktiv = 'Status: AKTIV' in content
                except Exception:
                    aktiv = False
                key = subdir.name.lower()
                experts[key] = {
                    'name': subdir.name,
                    'file': concept,
                    'in_db': False,
                    'is_active': False,
                    'aktiv_in_file': aktiv,
                    'type': 'expert',
                }

        return boss_agents, experts

    def _load_db_status(self, boss_agents: dict, experts: dict, active_only: bool):
        """Reichert Filesystem-Eintraege mit DB-Status an."""
        if not self.db_path.exists():
            return

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # --- bach_agents Tabelle (Boss-Agenten) ---
            # TOWER_OF_BABEL: Sprach-Filter mit Fallback auf DE
            lang = get_lang()
            try:
                ba_query = "SELECT name, is_active, display_name, persona FROM bach_agents WHERE language = ?"
                ba_params = [lang]
                if active_only:
                    ba_query += " AND is_active = 1"
                cursor.execute(ba_query, ba_params)
                ba_rows = cursor.fetchall()
                # Fallback: wenn keine Ergebnisse fuer aktuelle Sprache, DE laden
                if not ba_rows and lang != 'de':
                    cursor.execute(ba_query.replace("language = ?", "language = 'de'"), ['de'])
                    ba_rows = cursor.fetchall()
                for row in ba_rows:
                    key = row['name'].lower()
                    if key in boss_agents:
                        boss_agents[key]['in_db'] = True
                        boss_agents[key]['is_active'] = bool(row['is_active'])
                        boss_agents[key]['display_name'] = row['display_name'] or ''
                        boss_agents[key]['persona'] = row['persona'] or ''
            except sqlite3.OperationalError:
                pass  # bach_agents existiert noch nicht

            # --- agents Tabelle (Legacy / manuell eingetragene) ---
            query = "SELECT name, type, is_active FROM agents"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY name"
            cursor.execute(query)

            for row in cursor.fetchall():
                key = row['name'].lower()
                is_active = bool(row['is_active'])
                if key in boss_agents:
                    boss_agents[key]['in_db'] = True
                    boss_agents[key]['is_active'] = is_active
                    boss_agents[key]['type'] = row['type']
                elif key in experts:
                    experts[key]['in_db'] = True
                    experts[key]['is_active'] = is_active
                else:
                    # Nur in DB, nicht im Filesystem -> unter Boss-Agenten listen
                    boss_agents[key] = {
                        'name': row['name'],
                        'file': None,
                        'in_db': True,
                        'is_active': is_active,
                        'type': row['type'],
                    }

            # --- bach_experts Tabelle (Experten, TOWER_OF_BABEL: sprachsensitiv) ---
            try:
                exp_query = "SELECT name, is_active, display_name, persona FROM bach_experts WHERE language = ?"
                exp_params = [lang]
                if active_only:
                    exp_query += " AND is_active = 1"
                cursor.execute(exp_query, exp_params)
                exp_rows = cursor.fetchall()
                if not exp_rows and lang != 'de':
                    cursor.execute(exp_query.replace("language = ?", "language = 'de'"), ['de'])
                    exp_rows = cursor.fetchall()
                for row in exp_rows:
                    key = row['name'].lower()
                    is_active = bool(row['is_active'])
                    if key in experts:
                        experts[key]['in_db'] = True
                        experts[key]['is_active'] = is_active
                        experts[key]['display_name'] = row['display_name'] or ''
                        experts[key]['persona'] = row['persona'] or ''
                    elif key not in boss_agents:
                        # Nur in bach_experts, nicht im Filesystem
                        experts[key] = {
                            'name': row['name'],
                            'file': None,
                            'in_db': True,
                            'is_active': is_active,
                            'aktiv_in_file': False,
                            'type': 'expert',
                            'display_name': row['display_name'] or '',
                            'persona': row['persona'] or '',
                        }
            except sqlite3.OperationalError:
                pass  # bach_experts Tabelle existiert noch nicht

            conn.close()
        except Exception as e:
            pass  # DB-Fehler nicht crashen lassen

    def _status_icon(self, entry: dict) -> str:
        if entry.get('in_db') and entry.get('is_active'):
            return "[X]"
        elif entry.get('in_db'):
            return "[-]"
        else:
            return "[ ]"

    def _format_display_name(self, entry: dict) -> str:
        """Formatiert display_name Suffix fuer Listing.

        Zeigt display_name in Klammern, aber nur wenn er sich vom
        technischen Namen unterscheidet und gesetzt ist.
        """
        dn = entry.get('display_name', '')
        name = entry.get('name', '')
        if dn and dn.lower() != name.lower():
            return f" ({dn})"
        return ""

    def _list(self, active_only: bool) -> tuple:
        """Agenten und Experten auflisten - aus bach_paths + DB."""
        results = [t("boss_agents", default="AGENTEN"), "=" * 40]

        boss_agents, experts = self._scan_filesystem()
        self._load_db_status(boss_agents, experts, active_only)

        # --- Boss-Agenten ausgeben ---
        results.append(f"\n[{t('boss_agents', default='BOSS-AGENTEN')}]")
        if boss_agents:
            for key, agent in sorted(boss_agents.items()):
                dn_str = self._format_display_name(agent)
                type_str = f" ({agent.get('type', 'boss')})"
                results.append(f"  {self._status_icon(agent)} {agent['name']}{dn_str}{type_str}")
        else:
            results.append(f"  ({t('not_found', default='keine gefunden')})")

        # --- Experten ausgeben ---
        results.append(f"\n[{t('experts', default='EXPERTEN')}]")
        if experts:
            for key, expert in sorted(experts.items()):
                dn_str = self._format_display_name(expert)
                # Datei-Status ergaenzen wenn nur Filesystem
                file_status = ""
                if not expert.get('in_db') and not expert.get('aktiv_in_file', True):
                    file_status = f" ({t('inactive', default='inaktiv')})"
                results.append(f"  {self._status_icon(expert)} {expert['name']}{dn_str}{file_status}")
        else:
            results.append(f"  ({t('not_found', default='keine gefunden')})")

        results.append("\n" + "=" * 40)
        results.append(f"{t('legend', default='Legende')}: [X]=DB+{t('active', default='aktiv')} [-]=DB+{t('inactive', default='inaktiv')} [ ]={t('agents_file_only', default='nur Datei')}")
        results.append(f"Pfade: {self.agents_dir} {'(bach_paths)' if _PATHS_FROM_BACH else '(fallback)'}")
        results.append(f"\n{t('details', default='Details')}: --agents info <n>")

        return True, "\n".join(results)

    def _rename(self, query: str, new_display_name: str) -> tuple:
        """Aendert den display_name eines Agenten oder Experten.

        Args:
            query: Technischer Name oder aktueller Display-Name
            new_display_name: Neuer Display-Name

        Returns:
            (success, message) Tuple
        """
        # Validierung
        new_display_name = new_display_name.strip()
        if not new_display_name:
            return False, t("display_name_empty", default="[ERROR] Display-Name darf nicht leer sein.")
        if len(new_display_name) > 30:
            return False, f"{t('display_name_too_long', default='[ERROR] Display-Name zu lang')} ({len(new_display_name)}/30)."

        # Agent/Experte finden
        resolved = resolve_agent_name(self.db_path, query)
        if not resolved:
            return False, f"[ERROR] {t('not_found', default='nicht gefunden')}: {query}"

        table = resolved['source_table']
        name = resolved['name']
        old_display = resolved['display_name']

        # Update in DB
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE {table} SET display_name = ? WHERE name = ?",
                (new_display_name, name)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            return False, f"[ERROR] {t('db_update_failed', default='DB-Update fehlgeschlagen')}: {e}"

        return True, (
            f"{t('display_name_changed', default='[OK] Display-Name geaendert')}\n"
            f"  Agent:  {name}\n"
            f"  {t('previous_label', default='Vorher')}: {old_display}\n"
            f"  {t('now_label', default='Jetzt')}:  {new_display_name}"
        )

    def _parse_concept(self, concept_file: Path) -> dict:
        """
        Liest Metadaten aus einer CONCEPT.md.

        Erwartet dieses Format im Header:
            # EXPERTE: Display Name
            ## Status: AKTIV
            Version: 1.0.0
            Erstellt: ...
            Parent-Agent: boss-agent-name
        """
        meta = {}
        try:
            lines = concept_file.read_text(encoding='utf-8', errors='ignore').splitlines()
            for line in lines[:20]:  # Nur Header-Bereich
                line = line.strip()
                if line.startswith('# EXPERTE:'):
                    meta['display_name'] = line.replace('# EXPERTE:', '').strip()
                elif line.startswith('Version:'):
                    meta['version'] = line.replace('Version:', '').strip()
                elif line.startswith('Parent-Agent:'):
                    meta['parent_agent'] = line.replace('Parent-Agent:', '').strip().lower()
            # Erste Beschreibungszeile nach dem Header
            in_desc = False
            for line in lines:
                if '## 1.' in line or 'Ueberblick' in line or 'Beschreibung' in line:
                    in_desc = True
                    continue
                if in_desc and line.strip() and not line.startswith('#'):
                    meta['description'] = line.strip()[:200]
                    break
        except Exception:
            pass
        return meta

    def _sync(self, dry_run: bool = False) -> tuple:
        """
        Synct alle Filesystem-Experten (Status: AKTIV) in bach_experts.

        Nur Experten mit [ ] (nicht in DB) werden eingetragen.
        Parent-Agent wird aus CONCEPT.md gelesen und gegen bach_agents aufgeloest.
        """
        boss_agents, experts = self._scan_filesystem()
        self._load_db_status(boss_agents, experts, active_only=False)

        # Nur [ ] Experten (Filesystem, aber nicht in bach_experts)
        to_sync = [(k, e) for k, e in sorted(experts.items())
                   if not e.get('in_db') and e.get('file')]

        if not to_sync:
            return True, t("agents_sync_ok", default="[OK] Alle Experten bereits in DB eingetragen. Nichts zu tun.")

        if dry_run:
            lines = [f"[DRY-RUN] {len(to_sync)} {t('experts', default='Experte(n)')} {t('agents_would_sync', default='wuerden eingetragen')}:"]
            for key, e in to_sync:
                lines.append(f"  + {e['name']}")
            return True, "\n".join(lines)

        # Bach-Agent-ID-Mapping laden
        ba_map = {}
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM bach_agents")
            for row in cursor.fetchall():
                ba_map[row['name'].lower()] = row['id']
            conn.close()
        except Exception:
            pass

        conn = self._get_conn()
        cursor = conn.cursor()
        synced = []
        errors = []

        for key, expert in to_sync:
            meta = self._parse_concept(expert['file'])
            parent_name = meta.get('parent_agent', '')
            agent_id = ba_map.get(parent_name, 1)  # Fallback: ID 1

            # Skill-Pfad relativ zu system/
            try:
                rel_path = str(expert['file'].relative_to(self.base_path))
            except ValueError:
                rel_path = str(expert['file'])

            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO bach_experts
                        (name, display_name, agent_id, description, skill_path, version, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                """, (
                    expert['name'],
                    meta.get('display_name', expert['name']),
                    agent_id,
                    meta.get('description', ''),
                    rel_path,
                    meta.get('version', '1.0.0'),
                ))
                synced.append(f"  + {expert['name']} (Parent: {parent_name or '?'})")
            except Exception as e:
                errors.append(f"  ! {expert['name']}: {e}")

        conn.commit()
        conn.close()

        lines = []
        if synced:
            lines.append(f"[OK] {len(synced)} {t('experts', default='Experte(n)')} {t('agents_synced', default='eingetragen')}:")
            lines.extend(synced)
        if errors:
            lines.append(f"\n[{t('error_generic', default='FEHLER')}] {len(errors)} {t('agents_sync_failed', default='fehlgeschlagen')}:")
            lines.extend(errors)

        return True, "\n".join(lines)

    def _info(self, name: str) -> tuple:
        """Agenten-Details - sucht via resolve_agent_name, dann Legacy-Tabelle."""
        _yes = t("yes_label", default="Ja")
        _no = t("no_label", default="Nein")

        # Zuerst ueber Name-Resolver versuchen (bach_agents / bach_experts)
        resolved = resolve_agent_name(self.db_path, name)

        conn = self._get_conn()
        cursor = conn.cursor()

        if resolved:
            table = resolved['source_table']
            canonical = resolved['name']
            try:
                cursor.execute(f"SELECT * FROM {table} WHERE name = ?", (canonical,))
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                row = None

            if row:
                display = resolved['display_name']
                persona = resolved.get('persona', '')
                label = "AGENT" if resolved['type'] == 'boss' else t('experts', default='EXPERTE')
                header = f"{label}: {canonical}"
                if display and display.lower() != canonical.lower():
                    header += f" ({display})"

                results = [header, "=" * 40]
                results.append(f"ID:            {row['id']}")
                results.append(f"{t('display_name_label', default='Display-Name')}:  {display}")
                results.append(f"{t('active', default='Aktiv')}:         {_yes if row['is_active'] else _no}")
                row_keys = row.keys()
                desc = row['description'] if 'description' in row_keys else '-'
                results.append(f"{t('description_label', default='Beschreibung')}:  {desc or '-'}")
                if persona:
                    results.append(f"{t('persona_label', default='Persona')}:       {persona}")
                if 'domain' in row_keys:
                    results.append(f"Domain:        {row['domain'] or '-'}")
                if 'skill_path' in row_keys:
                    results.append(f"{t('skill_path_label', default='Skill-Pfad')}:    {row['skill_path'] or '-'}")

                conn.close()
                return True, "\n".join(results)

        # Fallback: Legacy agents Tabelle
        cursor.execute("""
            SELECT * FROM agents
            WHERE name LIKE ? OR id = ?
        """, (f"%{name}%", name if name.isdigit() else -1))

        agent = cursor.fetchone()

        if agent:
            results = [f"AGENT: {agent['name']}", "=" * 40]
            results.append(f"ID:          {agent['id']}")
            results.append(f"Type:        {agent['type']}")
            results.append(f"{t('active', default='Aktiv')}:       {_yes if agent['is_active'] else _no}")
            results.append(f"{t('description_label', default='Beschreibung')}: {agent['description'] or '-'}")

            # Synergien
            cursor.execute("""
                SELECT a2.name, s.synergy_type, s.description
                FROM agent_synergies s
                JOIN agents a2 ON s.agent_b_id = a2.id
                WHERE s.agent_a_id = ?
            """, (agent['id'],))
            synergies = cursor.fetchall()
            if synergies:
                results.append(f"\n{t('synergies_label', default='Synergien')}:")
                for s in synergies:
                    results.append(f"  -> {s['name']} ({s['synergy_type']})")

            conn.close()
            return True, "\n".join(results)

        conn.close()
        return False, f"{t('not_found', default='nicht gefunden')}: {name}"
