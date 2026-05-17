# SPDX-License-Identifier: MIT
"""
Startup Handler - Session starten (DB-basiert)
==============================================

Mit Directory-Scan, Memory-Check, und Session-Kontinuitaet.

Nutzermodi (v1.1.37):
    gui     - Startet GUI Dashboard (Default)
    text    - Startet nur Konsole, kein Browser
    dual    - Startet GUI + Konsole
    silent  - Startet nichts automatisch

Partner-Sessions (v1.1.38):
    --partner=NAME  Schliesst vorherige Session desselben Partners automatisch
                    und oeffnet neue. Ermoeglicht parallele Partner-Sessions.
                    Beispiel: --partner=claude, --partner=gemini
"""
import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from .base import BaseHandler


class StartupHandler(BaseHandler):
    """Handler fuer --startup - DB-basiert"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        self.user_config_path = base_path / "data" / "user_config.json"

    @property
    def profile_name(self) -> str:
        return "startup"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "run": "Komplettes Startprotokoll (Standard)",
            "quick": "Schnellstart ohne Dir-Scan",
            "mode": "Modus aendern: gui|text|dual|silent"
        }

    def _load_user_config(self) -> dict:
        """Laedt User-Config fuer Startup-Modus."""
        if self.user_config_path.exists():
            try:
                return json.loads(self.user_config_path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                pass
        # Default-Config
        return {
            "startup_mode": "gui",
            "startup_modes": {
                "gui": {"gui": True, "console": False},
                "text": {"gui": False, "console": True},
                "dual": {"gui": True, "console": True},
                "silent": {"gui": False, "console": False}
            }
        }

    def _save_user_config(self, config: dict):
        """Speichert User-Config."""
        config["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        self.user_config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def _get_startup_mode(self, args: list) -> str:
        """Ermittelt Startup-Modus aus Args oder Config."""
        # 1. Flag-Argument pruefen: --mode=gui oder --mode gui
        for i, arg in enumerate(args):
            if arg.startswith("--mode="):
                return arg.split("=", 1)[1].lower()
            if arg == "--mode" and i + 1 < len(args):
                return args[i + 1].lower()

        # 2. Aus Config laden
        config = self._load_user_config()
        return config.get("startup_mode", "gui")

    def _get_partner_id(self, args: list) -> str:
        """Ermittelt Partner-ID aus Args. Default: 'user'.
        
        Spezielle Werte:
        - 'new' oder 'nameless': Generiert eindeutige ID (partner_HHMMSS)
        - Beliebiger Name: Wird als Partner-ID verwendet (auch neue)
        """
        for arg in args:
            if arg.startswith("--partner="):
                partner = arg.split("=", 1)[1].lower()
                
                # Neue Partner ohne Namen -> generierte ID
                if partner in ('new', 'nameless', 'anon', 'anonymous'):
                    from datetime import datetime
                    return f"partner_{datetime.now().strftime('%H%M%S')}"
                
                return partner
        return "user"

    def _close_partner_session(self, partner_id: str) -> tuple:
        """Schliesst aktive Session eines Partners automatisch.

        Returns:
            tuple: (session_closed: bool, session_id: str or None)
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # Suche nach aktiver Session des Partners
            cursor.execute("""
                SELECT id, session_id FROM memory_sessions
                WHERE partner_id = ? AND ended_at IS NULL
                ORDER BY id DESC LIMIT 1
            """, (partner_id,))
            row = cursor.fetchone()

            if row:
                session_db_id, session_id = row
                now = datetime.now().isoformat()

                # Session automatisch schliessen
                cursor.execute("""
                    UPDATE memory_sessions
                    SET ended_at = ?,
                        summary = COALESCE(summary, '') || ' [AUTO-CLOSED: Neue Session gestartet]'
                    WHERE id = ?
                """, (now, session_db_id))
                conn.commit()
                return True, session_id

            return False, None
        finally:
            conn.close()

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        # Modus-Aenderung
        if operation == "mode" and args:
            new_mode = args[0].lower()
            valid_modes = ["gui", "text", "dual", "silent"]
            if new_mode in valid_modes:
                config = self._load_user_config()
                old_mode = config.get("startup_mode", "gui")
                config["startup_mode"] = new_mode
                self._save_user_config(config)
                return True, f"[OK] Startup-Modus geaendert: {old_mode} -> {new_mode}"
            else:
                return False, f"[ERROR] Ungueltiger Modus: {new_mode}\nGueltig: {', '.join(valid_modes)}"

        quick = operation == "quick"
        startup_mode = self._get_startup_mode(args)
        partner_id = self._get_partner_id(args)

        # Hook: before_startup
        try:
            from core.hooks import hooks
            hooks.emit('before_startup', {
                'partner': partner_id, 'mode': startup_mode, 'quick': quick
            })
        except Exception:
            pass

        success, message = self._run_startup(quick, dry_run, startup_mode, partner_id)

        # Hook: after_startup
        try:
            from core.hooks import hooks as _hooks
            _hooks.emit('after_startup', {
                'partner': partner_id, 'mode': startup_mode, 'success': success
            })
        except Exception:
            pass

        return success, message
    
    def _get_conn(self):
        return sqlite3.connect(self.db_path)
    
    def _clock_in_partner(self, partner_id: str) -> bool:
        """Stempelt Partner ein (partner_presence Tabelle).
        
        Markiert alte 'online' Eintraege als 'crashed' falls vorhanden.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Alte aktive Sessions als crashed markieren
        cursor.execute("""
            UPDATE partner_presence 
            SET status = 'crashed', clocked_out = ?, updated_at = ?
            WHERE partner_name = ? AND status = 'online'
        """, (now, now, partner_id))
        
        # Neu einstempeln
        cursor.execute("""
            INSERT INTO partner_presence 
            (partner_name, status, clocked_in, last_heartbeat, session_id, created_at, updated_at)
            VALUES (?, 'online', ?, ?, ?, ?, ?)
        """, (partner_id, now, now, session_id, now, now))
        
        conn.commit()
        conn.close()
        return True
    
    def _clock_out_partner(self, partner_id: str) -> bool:
        """Stempelt Partner aus."""
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE partner_presence 
            SET status = 'offline', clocked_out = ?, updated_at = ?
            WHERE partner_name = ? AND status = 'online'
        """, (now, now, partner_id))
        
        conn.commit()
        conn.close()
        return True
    
    def _get_online_partners(self, timeout_minutes: int = 5) -> list:
        """Holt alle online Partner (Heartbeat-Check)."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Cutoff fuer Heartbeat-Timeout
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(minutes=timeout_minutes)).isoformat()
        
        cursor.execute("""
            SELECT partner_name, clocked_in, last_heartbeat, current_task
            FROM partner_presence 
            WHERE status = 'online' AND last_heartbeat > ?
        """, (cutoff,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [{'partner': r[0], 'clocked_in': r[1], 'heartbeat': r[2], 'task': r[3]} for r in rows]
    
    def _lazy_auto_sync(self) -> list:
        """Lazy Auto-Sync: Nur geaenderte Ordner synchronisieren (SQ044).

        Prueft mtime der Ordner skills/ und tools/. Nur wenn sich ein Ordner
        seit dem letzten Sync geaendert hat, wird er synchronisiert.
        Zustand wird in data/sync_state.json gespeichert.
        """
        sync_state_path = self.base_path / "data" / "sync_state.json"
        sync_dirs = {
            "skills": self.base_path / "skills",
            "tools": self.base_path / "tools",
        }
        results = []

        # Gespeicherten State laden
        state = {}
        if sync_state_path.exists():
            try:
                state = json.loads(sync_state_path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                state = {}

        changed_dirs = []
        for name, dir_path in sync_dirs.items():
            if not dir_path.exists():
                continue
            # Ordner-mtime pruefen (rekursiv: neueste Datei zaehlt)
            current_mtime = self._get_dir_mtime(dir_path)
            stored_mtime = state.get(f"{name}_mtime", 0)
            if current_mtime > stored_mtime:
                changed_dirs.append(name)

        if not changed_dirs:
            return []

        # Nur geaenderte Ordner synchronisieren
        try:
            from .sync import SyncHandler
            sync_handler = SyncHandler(self.base_path)

            synced_count = 0
            for dir_name in changed_dirs:
                if dir_name == "skills":
                    success, msg = sync_handler._sync_skills()
                elif dir_name == "tools":
                    success, msg = sync_handler._sync_tools()
                else:
                    continue

                if success:
                    # mtime aktualisieren
                    dir_path = sync_dirs[dir_name]
                    state[f"{dir_name}_mtime"] = self._get_dir_mtime(dir_path)
                    synced_count += 1

            if synced_count > 0:
                results.append(f"[AUTO-SYNC] {', '.join(changed_dirs)} synchronisiert")
                # State speichern
                try:
                    sync_state_path.write_text(
                        json.dumps(state, indent=2),
                        encoding='utf-8'
                    )
                except OSError:
                    pass
        except Exception as e:
            results.append(f"[AUTO-SYNC] Fehler: {e}")

        return results

    def _get_dir_mtime(self, dir_path: Path) -> float:
        """Ermittelt die neueste mtime aller Dateien in einem Ordner (rekursiv)."""
        max_mtime = 0.0
        try:
            for f in dir_path.rglob("*"):
                if f.is_file() and not f.name.startswith((".", "_")):
                    try:
                        mt = f.stat().st_mtime
                        if mt > max_mtime:
                            max_mtime = mt
                    except OSError:
                        pass
        except OSError:
            pass
        return max_mtime

    def _count_startup_resources(self) -> dict:
        """Ermittelt die Startup-Ressourcen fuer das aktuelle Layout robust."""
        counts = {
            "agents": 0,
            "workflows": 0,
            "skills": 0,
            "tools": 0,
            "help": 0,
        }

        workflows_dir = self.base_path / "skills" / "workflows"
        if workflows_dir.exists():
            workflow_files = {
                str(path)
                for pattern in ("*.md", "*.txt")
                for path in workflows_dir.rglob(pattern)
            }
            counts["workflows"] = len(workflow_files)

        help_dir = self.base_path / "docs" / "help"
        if help_dir.exists():
            counts["help"] = len(list(help_dir.rglob("*.txt")))

        conn = self._get_conn()
        try:
            counts["tools"] = conn.execute(
                "SELECT COUNT(*) FROM tools WHERE is_available = 1"
            ).fetchone()[0]
        except sqlite3.Error:
            tools_dir = self.base_path / "tools"
            counts["tools"] = len(list(tools_dir.glob("*.py"))) if tools_dir.exists() else 0

        agent_count = 0
        agent_tables_found = False
        for table in ("bach_agents", "bach_experts"):
            try:
                agent_count += conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE COALESCE(is_active, 1) = 1"
                ).fetchone()[0]
                agent_tables_found = True
            except sqlite3.Error:
                continue
        counts["agents"] = agent_count if agent_tables_found else self._count_agent_dirs()

        try:
            counts["skills"] = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        except sqlite3.Error:
            counts["skills"] = self._count_skill_files()
        finally:
            conn.close()

        return counts

    def _count_agent_dirs(self) -> int:
        """Zaehlt Agenten und Experten ueber vorhandene SKILL.md-Verzeichnisse."""
        count = 0
        for root in (self.base_path / "agents", self.base_path / "agents" / "_experts"):
            if not root.exists():
                continue
            for child in root.iterdir():
                if child.is_dir() and (child / "SKILL.md").exists():
                    count += 1
        return count

    def _count_skill_files(self) -> int:
        """Faellt fuer Skills auf einen vorsichtigen Dateisystem-Count zurueck."""
        skills_dir = self.base_path / "skills"
        if not skills_dir.exists():
            return 0

        skill_files = []
        for path in skills_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.name.lower() == "readme.md":
                continue
            if path.suffix.lower() not in {".md", ".txt"}:
                continue
            skill_files.append(path)
        return len(skill_files)

    def _ati_status_lines(self) -> list[str]:
        """Erzeugt den ATI-Statusblock fuer das Startup-Protokoll."""
        lines = ["", "[ATI AGENT]"]
        ati_path = self.base_path / "agents" / "ati"

        if (ati_path / "SKILL.md").exists():
            lines.append(" ATI Ordner vorhanden")
            lines.append(" Software-Entwicklungs-Tasks: bach ati task list (geplant)")
            lines.append(" AUFGABEN.txt Scanner: bach ati scan (geplant)")
        else:
            lines.append(" [SKIP] ATI Agent nicht eingerichtet")

        return lines

    def _run_startup(self, quick: bool, dry_run: bool, startup_mode: str = "gui", partner_id: str = "user") -> tuple:
        results = []
        now = datetime.now()

        results.append("=" * 55)
        results.append("         BACH SESSION STARTUP")
        results.append("=" * 55)
        results.append(f" Zeit: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})")
        results.append(f" Modus: {startup_mode.upper()}")
        results.append(f" Partner: {partner_id.upper()}")
        results.append("=" * 55)

        # Partner-Session-Management: Alte Session desselben Partners schliessen
        if not dry_run:
            closed, old_session_id = self._close_partner_session(partner_id)
            if closed:
                results.append("")
                results.append(f"[AUTO-CLOSE] Vorherige {partner_id.upper()}-Session beendet: {old_session_id}")
            
            # ══════════════════════════════════════════════════════════════
            # STEMPELKARTE: Partner einstempeln (v1.1.71)
            # ══════════════════════════════════════════════════════════════
            try:
                self._clock_in_partner(partner_id)
            except Exception as e:
                pass  # Silent fail - nicht kritisch
        
        if dry_run:
            results.append("[DRY-RUN] Keine Aenderungen")

        # ══════════════════════════════════════════════════════════════
        # 0. USER-PROFIL laden und anzeigen + DB-Sync
        # ══════════════════════════════════════════════════════════════
        try:
            import sys
            profile_svc_dir = str(self.base_path / "hub" / "_services" / "profile")
            if profile_svc_dir not in sys.path:
                sys.path.insert(0, profile_svc_dir)
            from profile_service import ProfileService
            project_root = self.base_path.parent
            ps = ProfileService(
                profile_path=project_root / "user" / "profile.json",
                db_path=self.db_path
            )
            # Sync profile.json -> DB (idempotent)
            if not dry_run:
                sync_result = ps.sync_from_json()
                if sync_result.get("synced", 0) > 0:
                    results.append("")
                    results.append(f"[PROFIL-SYNC] {sync_result['synced']} Eintraege synchronisiert")
            # Einzeilige Zusammenfassung
            summary = ps.get_startup_summary()
            if summary:
                results.append("")
                results.append(summary)
        except Exception as e:
            pass  # Silent fail - Profil ist nicht kritisch

        # 0. Directory Scan (nicht bei quick)
        if not quick:
            results.append("")
            results.append("[DIRECTORY SCAN]")
            try:
                from tools.dirscan import DirectoryScanner
                scanner = DirectoryScanner(self.base_path)
                has_changes, scan_report = scanner.startup_check()
                results.append(scan_report)
            except Exception as e:
                results.append(f" [SKIP] Dir-Scan: {e}")

        # ══════════════════════════════════════════════════════════════
        # 0.05 MEMORY SYNC - MEMORY.md generieren (SQ065)
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            try:
                import sys
                tools_dir = str(self.base_path / "tools")
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from memory_sync import MemorySync

                bach_root = self.base_path.parent
                sync = MemorySync(bach_root)
                success, msg = sync.generate(partner=partner_id, project="BACH")

                if success:
                    results.append("")
                    results.append("[MEMORY SYNC]")
                    results.append(f" {msg}")
            except Exception as e:
                pass  # Silent fail - nicht kritisch

        # ══════════════════════════════════════════════════════════════
        # 0.06 WORKING MEMORY CLEANUP - Abgelaufene Einträge (SQ043)
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            try:
                import sys
                tools_dir = str(self.base_path / "tools")
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from memory_working_cleanup import WorkingMemoryCleanup

                cleanup = WorkingMemoryCleanup(self.db_path)
                # Auto-Cleanup nur für expired Einträge
                success, msg = cleanup.cleanup(dry_run=False)

                # Nur bei tatsächlichem Cleanup anzeigen
                if success and "0 expired" not in msg:
                    results.append("")
                    results.append("[WORKING MEMORY CLEANUP]")
                    results.append(f" {msg}")
            except Exception as e:
                pass  # Silent fail - nicht kritisch

        # 0.07 SECRETS SYNC - Datei → DB (Datei-autoritär, SQ076)
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            try:
                from hub.secrets_handler import SecretsHandler

                handler = SecretsHandler()
                # SYNC: Datei → DB (enforce_authority=True)
                # Wenn Datei fehlt: alle Secrets aus DB löschen (Datei-Autorität)
                handler.sync_from_file(enforce_authority=True)

                # Keine Ausgabe bei erfolgreichem SYNC (zu verbose)
                # Nur Fehler würden via Exception gemeldet
            except Exception as e:
                pass  # Silent fail - nicht kritisch (z.B. Datei fehlt)

        # ══════════════════════════════════════════════════════════════
        # 0.08 LAZY AUTO-SYNC - Skills/Tools bei Aenderung synchen (SQ044)
        # ══════════════════════════════════════════════════════════════
        if not dry_run and not quick:
            try:
                sync_results = self._lazy_auto_sync()
                if sync_results:
                    results.append("")
                    results.extend(sync_results)
            except Exception:
                pass  # Silent fail - nicht kritisch

        # ══════════════════════════════════════════════════════════════
        # 0.1 NUL CLEANER - Windows NUL-Dateien entfernen
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            try:
                from tools.nulcleaner import clean_nul_files_headless
                # BACH_ROOT (eine Ebene ueber system/) reinigen
                bach_root = self.base_path.parent
                nul_result = clean_nul_files_headless(str(bach_root), verbose=False)
                if nul_result['found'] > 0:
                    results.append("")
                    results.append("[NUL CLEANER]")
                    results.append(f" Gefunden: {nul_result['found']} | Geloescht: {nul_result['deleted']}")
                    if nul_result['errors']:
                        results.append(f" [!] {len(nul_result['errors'])} Fehler beim Loeschen")
            except Exception:
                pass  # Silent fail - nicht kritisch

        # ══════════════════════════════════════════════════════════════
        # 0.5 PROBLEMS FIRST - Fehler automatisch melden (von CHIAH)
        # ══════════════════════════════════════════════════════════════
        try:
            from tools.problems_first import scan_problems, format_problems_report
            problems = scan_problems(self.base_path, hours=24)
            if problems['total'] > 0:
                results.append("")
                results.append(format_problems_report(problems))
        except Exception as e:
            pass  # Silent fail - nicht kritisch
        
        # ══════════════════════════════════════════════════════════════
        # 0.6 PATH HEALER CHECK (dry-run) - Pfadprobleme erkennen
        # ══════════════════════════════════════════════════════════════
        try:
            from tools.c_path_healer import BachPathHealer
            healer = BachPathHealer(str(self.base_path))
            heal_result = healer.heal_all(dry_run=True)
            
            healed_count = len(heal_result.get('healed_files', []))
            if healed_count > 0:
                results.append("")
                results.append("[PATH HEALER]")
                results.append(f" [!] {healed_count} Dateien mit Pfadproblemen gefunden")
                for f in heal_result['healed_files'][:3]:
                    fname = Path(f['file']).name if isinstance(f, dict) and 'file' in f else str(f)[:30]
                    results.append(f"   - {fname}")
                if healed_count > 3:
                    results.append(f"   ... und {healed_count - 3} weitere")
                results.append(" --> bach maintain heal --execute zum Reparieren")
        except Exception as e:
            pass  # Silent fail - nicht kritisch
        
        # ══════════════════════════════════════════════════════════════
        # 0.7 REGISTRY WATCHER CHECK - Datenbank/JSON Konsistenz
        # ══════════════════════════════════════════════════════════════
        try:
            import sys
            sys.path.insert(0, str(self.base_path / "tools" / "maintenance"))
            from registry_watcher import RegistryWatcher

            watcher = RegistryWatcher(base_path=self.base_path)
            report = watcher.check_all()
            summary = report.get("summary", {})
            actionable = summary.get("actionable_issues", 0)

            if actionable > 0:
                results.append("")
                results.append("[REGISTRY WATCHER]")
                results.append(f" [!] {actionable} aktuelle Registry-Probleme")
                stale = summary.get("stale_entries", 0)
                if stale:
                    results.append(f" [i] {stale} stale/umgezogene DB-Eintraege getrennt erkannt")
                results.append(" --> bach --maintain registry fuer Details")
        except Exception as e:
            pass  # Silent fail - nicht kritisch
        
        # ══════════════════════════════════════════════════════════════
        # 0.75 KERNEL SEAL CHECK - Integritätsprüfung (SQ021)
        # ══════════════════════════════════════════════════════════════
        if not quick and not dry_run:
            conn = None
            try:
                conn = self._get_conn()
                cursor = conn.execute("SELECT kernel_hash FROM instance_identity LIMIT 1")
                row = cursor.fetchone()
                stored_hash = row[0] if row and row[0] else None

                if stored_hash:
                    # Schnell-Check: Stichprobe von 5 CORE-Dateien
                    cursor = conn.execute("""
                        SELECT path FROM distribution_manifest
                        WHERE dist_type = 2
                        ORDER BY RANDOM()
                        LIMIT 5
                    """)
                    sample_files = [r[0] for r in cursor.fetchall()]

                    # Prüfe ob Sample-Dateien existieren
                    missing = []
                    for rel_path in sample_files:
                        if not rel_path.startswith('system/'):
                            file_path = self.base_path.parent / 'system' / rel_path
                        else:
                            file_path = self.base_path.parent / rel_path
                        if not file_path.exists():
                            missing.append(rel_path)

                    if missing:
                        results.append("")
                        results.append("[KERNEL SEAL]")
                        results.append(f" [!] {len(missing)}/5 CORE-Dateien fehlen")
                        results.append(" --> Integritaet kompromittiert?")
                        results.append(" --> bach seal check fuer Details")
            except Exception as e:
                pass  # Silent fail - nicht kritisch
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        # ══════════════════════════════════════════════════════════════
        # 0.8 SKILL HEALTH MONITOR - Skill/Agent Validierung
        # ══════════════════════════════════════════════════════════════
        try:
            from skill_health_monitor import SkillHealthMonitor
            monitor = SkillHealthMonitor(self.base_path)
            is_healthy, report = monitor.check_all()
            
            if not is_healthy and monitor.issues:
                results.append("")
                results.append("[SKILL HEALTH]")
                results.append(f" [!] {len(monitor.issues)} Skill-Probleme gefunden")
                for issue in monitor.issues[:3]:
                    results.append(f"   - {issue.get('message', '')[:40]}")
                if len(monitor.issues) > 3:
                    results.append(f"   ... und {len(monitor.issues) - 3} weitere")
                results.append(" --> bach maintain skills fuer Details")
        except Exception as e:
            pass  # Silent fail - nicht kritisch
        
        # ══════════════════════════════════════════════════════════════
        # 0.9 KERNEL HASH CHECK - Siegelsystem (SQ021, ENT-14)
        # ══════════════════════════════════════════════════════════════
        if not quick:
            try:
                import hashlib
                import sqlite3

                conn = sqlite3.connect(str(self.db_path))
                try:
                    # CORE-Dateien aus distribution_manifest lesen (dist_type=2)
                    core_files = conn.execute(
                        "SELECT path FROM distribution_manifest WHERE dist_type = 2 ORDER BY path"
                    ).fetchall()

                    if core_files:
                        system_dir = self.base_path
                        bach_root = self.base_path.parent
                        combined_hash = hashlib.sha256()
                        files_hashed = 0

                        for (rel_path,) in core_files:
                            if '*' in rel_path:
                                continue
                            abs_path = system_dir / rel_path
                            if not abs_path.exists():
                                abs_path = bach_root / rel_path
                            if abs_path.exists() and abs_path.is_file():
                                try:
                                    file_hash = hashlib.sha256(abs_path.read_bytes()).hexdigest()
                                    combined_hash.update(file_hash.encode())
                                    files_hashed += 1
                                except (OSError, IOError):
                                    pass

                        current_hash = combined_hash.hexdigest()[:16]

                        # Gespeicherten Hash aus instance_identity lesen
                        stored = conn.execute(
                            "SELECT kernel_hash, seal_status FROM instance_identity LIMIT 1"
                        ).fetchone()

                        if stored and stored[0]:
                            stored_hash = stored[0][:16]
                            seal_status = stored[1] or 'unknown'
                            if stored_hash != current_hash:
                                results.append("")
                                results.append("[SIEGEL]")
                                results.append(f" [!] Kernel-Hash geaendert ({files_hashed} CORE-Dateien)")
                                results.append(f"     Gespeichert: {stored_hash}...")
                                results.append(f"     Aktuell:     {current_hash}...")
                                results.append(" --> bach seal check fuer Details")
                                # Seal als broken markieren (nur Warnung, keine Sperre)
                                if not dry_run:
                                    conn.execute(
                                        "UPDATE instance_identity SET seal_status = 'changed', kernel_hash = ?",
                                        (current_hash,)
                                    )
                                    conn.commit()
                        else:
                            # Erster Start: Hash speichern
                            if not dry_run and files_hashed > 0:
                                conn.execute(
                                    "UPDATE instance_identity SET kernel_hash = ?, seal_status = 'intact'",
                                    (current_hash,)
                                )
                                conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass  # Silent fail - Siegel ist nicht kritisch

        # ══════════════════════════════════════════════════════════════
        # 1. LETZTE SESSION - Kontinuitaet herstellen
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[LETZTE SESSION]")
        try:
            conn = self._get_conn()
            last_session = conn.execute("""
                SELECT session_id, started_at, ended_at, summary, 
                       tasks_created, tasks_completed, continuation_context
                FROM memory_sessions 
                WHERE ended_at IS NOT NULL
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            
            if last_session:
                sid, started, ended, summary, created, completed, continuation = last_session
                
                # Datum formatieren
                date = ended[:10] if ended else "?"
                time_end = ended[11:16] if ended and len(ended) > 11 else "?"
                
                results.append(f" Session: {sid}")
                results.append(f" Beendet: {date} {time_end}")
                results.append(f" Tasks: +{created or 0} erstellt, {completed or 0} erledigt")
                
                # Summary (erste Zeile)
                if summary:
                    first_line = summary.split('\n')[0][:50]
                    results.append(f" Thema: {first_line}...")
                
                # WICHTIG: continuation_context = was als naechstes kommt
                if continuation:
                    results.append("")
                    results.append(" *** NAECHSTE SCHRITTE ***")
                    for line in continuation.split('\n')[:3]:
                        if line.strip():
                            results.append(f"   {line.strip()[:50]}")
            else:
                results.append(" Keine vorherige Session gefunden")
            
            conn.close()
        except Exception as e:
            results.append(f" [ERROR] {e}")
        
        # ══════════════════════════════════════════════════════════════
        # 1.5 SNAPSHOT CHECK - Letzten Snapshot anzeigen
        # ══════════════════════════════════════════════════════════════
        try:
            conn = self._get_conn()
            import json
            snapshot = conn.execute("""
                SELECT id, name, snapshot_data, created_at FROM session_snapshots 
                ORDER BY created_at DESC LIMIT 1
            """).fetchone()
            
            if snapshot:
                snap_id, snap_name, snap_data, snap_time = snapshot
                # Nur anzeigen wenn Snapshot heute oder gestern erstellt wurde
                snap_date = snap_time[:10] if snap_time else ""
                today = datetime.now().strftime('%Y-%m-%d')
                
                if snap_date == today:
                    results.append("")
                    results.append("[SNAPSHOT VERFUEGBAR]")
                    results.append(f" Letzter: {snap_name} ({snap_time[11:16]})")
                    
                    # Offene Tasks aus Snapshot
                    try:
                        data = json.loads(snap_data) if snap_data else {}
                        tasks = data.get("open_tasks", [])
                        if tasks:
                            results.append(f" Tasks im Snapshot: {len(tasks)}")
                    except (json.JSONDecodeError, TypeError, KeyError, AttributeError):
                        pass
                    
                    results.append(" --> bach snapshot load zum Fortsetzen")
            
            conn.close()
        except Exception as e:
            pass  # Silent fail - nicht kritisch
        
        # ══════════════════════════════════════════════════════════════
        # 2. MEMORY CHECK - Aktuelle Notizen und Fakten
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[MEMORY CHECK]")
        try:
            conn = self._get_conn()
            working = conn.execute("SELECT COUNT(*) FROM memory_working WHERE is_active=1").fetchone()[0]
            facts = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
            lessons = conn.execute("SELECT COUNT(*) FROM memory_lessons WHERE is_active=1").fetchone()[0]
            
            results.append(f" Working: {working} | Facts: {facts} | Lessons: {lessons}")
            
            # Letzte Notiz anzeigen
            last_note = conn.execute("""
                SELECT content, created_at FROM memory_working 
                WHERE is_active=1 ORDER BY created_at DESC LIMIT 1
            """).fetchone()
            if last_note:
                time = last_note[1][11:16] if last_note[1] else "?"
                results.append(f" Letzte Notiz [{time}]: {last_note[0][:40]}...")
            
            conn.close()
        except Exception as e:
            results.append(f" [ERROR] {e}")

        # ══════════════════════════════════════════════════════════════
        # 2.5 RESSOURCEN-UEBERSICHT - Was steht zur Verfuegung? (v1.1.82)
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[RESSOURCEN]")
        try:
            counts = self._count_startup_resources()
            results.append(
                f" Agents: {counts['agents']} | Workflows: {counts['workflows']} | Skills: {counts['skills']}"
            )
            results.append(f" Tools: {counts['tools']} | Help: {counts['help']}")
            results.append(" --> bach tools list, --help agents, --help workflows")
        except Exception as e:
            results.append(f" [SKIP] Ressourcen-Check: {e}")

        # ══════════════════════════════════════════════════════════════
        # 2.6 MORGEN-BRIEFING (nur 5-12 Uhr) - v1.1.85
        # ══════════════════════════════════════════════════════════════
        hour = now.hour
        if 5 <= hour < 12:
            results.append("")
            results.append("[MORGEN-BRIEFING]")
            try:
                conn = self._get_conn()

                # Termine des Tages
                today = now.strftime('%Y-%m-%d')
                try:
                    appointments = conn.execute("""
                        SELECT TIME(start_datetime) as time, title FROM assistant_calendar
                        WHERE DATE(start_datetime) = ? AND status != 'cancelled'
                        ORDER BY start_datetime
                    """, (today,)).fetchall()
                    if appointments:
                        results.append(" Termine heute:")
                        for apt in appointments[:3]:
                            time_str = apt[0][:5] if apt[0] else "??:??"
                            results.append(f"   {time_str} {apt[1][:40]}")
                        if len(appointments) > 3:
                            results.append(f"   ... und {len(appointments) - 3} weitere")
                except sqlite3.OperationalError:
                    pass  # Tabelle existiert evtl. nicht

                # Faellige Routinen
                try:
                    routines = conn.execute("""
                        SELECT name, due_date FROM household_routines
                        WHERE is_active = 1 AND due_date <= ?
                        ORDER BY due_date
                        LIMIT 5
                    """, (today,)).fetchall()
                    if routines:
                        results.append(f" Faellige Routinen: {len(routines)}")
                        for r in routines[:3]:
                            results.append(f"   - {r[0][:40]}")
                except sqlite3.OperationalError:
                    pass

                # Wichtige Tasks (P1/P2)
                try:
                    tasks = conn.execute("""
                        SELECT id, title, priority FROM tasks
                        WHERE status = 'pending' AND priority IN ('P1', 'P2')
                        ORDER BY priority, id
                        LIMIT 5
                    """).fetchall()
                    if tasks:
                        results.append(f" Wichtige Tasks: {len(tasks)}")
                        for t in tasks[:3]:
                            results.append(f"   [{t[0]}] {t[2]} {t[1][:35]}")
                except sqlite3.OperationalError:
                    pass

                conn.close()
                results.append(" --> bach haushalt today | bach task list")
            except Exception as e:
                results.append(f" [SKIP] Morgen-Briefing: {e}")

        # ══════════════════════════════════════════════════════════════
        # 2.7 GESUNDHEIT REMINDERS - Termine + Faellige Vorsorge
        # ══════════════════════════════════════════════════════════════
        conn_health = None
        try:
            conn_health = self._get_conn()
            conn_health.row_factory = sqlite3.Row
            health_lines = []

            # Termine in den naechsten 7 Tagen
            from datetime import timedelta
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            in_7_days = (now + timedelta(days=7)).strftime("%Y-%m-%d 23:59:59")
            try:
                upcoming = conn_health.execute("""
                    SELECT ha.appointment_date, ha.title, hc.name as doctor_name
                    FROM health_appointments ha
                    LEFT JOIN health_contacts hc ON ha.doctor_id = hc.id
                    WHERE ha.appointment_date >= ? AND ha.appointment_date <= ?
                      AND ha.status IN ('geplant', 'bestaetigt')
                    ORDER BY ha.appointment_date ASC
                """, (now_str, in_7_days)).fetchall()

                if upcoming:
                    health_lines.append(f"[GESUNDHEIT] {len(upcoming)} Termin(e) in den naechsten 7 Tagen:")
                    for apt in upcoming:
                        apt_date = apt["appointment_date"] or ""
                        day_str = apt_date[8:10] + "." + apt_date[5:7] if len(apt_date) >= 10 else "??"
                        time_str = apt_date[11:16] if len(apt_date) >= 16 else ""
                        doctor = f" bei {apt['doctor_name']}" if apt["doctor_name"] else ""
                        time_info = f" ({time_str})" if time_str else ""
                        health_lines.append(f"  - {day_str}: {apt['title']}{doctor}{time_info}")
            except Exception:
                pass  # Tabelle existiert evtl. nicht

            # Faellige Vorsorgeuntersuchungen
            try:
                today_str = now.strftime("%Y-%m-%d")
                overdue = conn_health.execute("""
                    SELECT untersuchung, naechster_termin, kategorie
                    FROM vorsorge_checks
                    WHERE is_active = 1
                      AND (naechster_termin IS NULL OR naechster_termin <= ?)
                    ORDER BY naechster_termin ASC NULLS FIRST
                    LIMIT 5
                """, (today_str,)).fetchall()

                if overdue:
                    health_lines.append(f"[VORSORGE] {len(overdue)} faellige Untersuchung(en):")
                    for v in overdue:
                        kat = f" [{v['kategorie']}]" if v["kategorie"] else ""
                        faellig = (v["naechster_termin"] or "noch nie")[:10]
                        health_lines.append(f"  - {v['untersuchung']}{kat} (faellig: {faellig})")
            except Exception:
                pass  # Tabelle existiert evtl. nicht

            if health_lines:
                results.append("")
                for hl in health_lines:
                    results.append(f" {hl}")

        except Exception:
            pass  # Silent fail - nicht kritisch
        finally:
            if conn_health:
                try:
                    conn_health.close()
                except Exception:
                    pass

        # ══════════════════════════════════════════════════════════════
        # 3. NEUE SESSION REGISTRIEREN
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            conn = None
            try:
                conn = self._get_conn()
                session_id = f"session_{now.strftime('%Y%m%d_%H%M%S')}"
                conn.execute("""
                    INSERT INTO memory_sessions (session_id, started_at, tasks_created, tasks_completed, partner_id)
                    VALUES (?, ?, 0, 0, ?)
                """, (session_id, now.isoformat(), partner_id))

                # SQ022: session_id auch in system_activity speichern für ActivityTracker
                conn.execute("""
                    UPDATE system_activity
                    SET session_id = ?, last_activity = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (session_id, now.isoformat()))

                conn.commit()
                results.append("")
                results.append(f"[SESSION] {session_id} gestartet (Partner: {partner_id})")
            except Exception as e:
                pass  # Nicht kritisch
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
        
        # ══════════════════════════════════════════════════════════════
        # 4. NACHRICHTEN CHECK + DIREKTE INJEKTION (v1.1.72)
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[NACHRICHTEN]")
        try:
            # v1.1.84: Alle Daten jetzt in bach.db
            import sqlite3
            conn_user = self._get_conn()
            conn_user.row_factory = sqlite3.Row
            unread_row = conn_user.execute(
                "SELECT COUNT(*) FROM messages WHERE status = 'unread'"
            ).fetchone()
            unread = unread_row[0] if unread_row else 0
            
            total_row = conn_user.execute("SELECT COUNT(*) FROM messages").fetchone()
            total = total_row[0] if total_row else 0

            if unread > 0:
                results.append(f" *** {unread} UNGELESENE NACHRICHT(EN) ***")
                
                # v1.1.72: Bei Partner-Session VOLLSTAENDIGE Nachrichten injizieren
                if partner_id and partner_id != "user":
                    # Nachrichten AN diesen Partner holen
                    msgs_for_me = conn_user.execute("""
                        SELECT id, sender, body, created_at FROM messages
                        WHERE status = 'unread' AND recipient = ?
                        ORDER BY created_at DESC LIMIT 5
                    """, (partner_id,)).fetchall()
                    
                    if msgs_for_me:
                        results.append("")
                        results.append(" *** DIREKTE NACHRICHTEN AN DICH ***")
                        for msg in msgs_for_me:
                            results.append(f"   [{msg['id']}] VON {msg['sender'].upper()} ({msg['created_at'][11:16]}):")
                            # Body in Zeilen aufteilen, max 3 Zeilen
                            body_lines = (msg['body'] or '').split('\n')[:3]
                            for line in body_lines:
                                results.append(f"      > {line[:70]}")
                            if len((msg['body'] or '').split('\n')) > 3:
                                results.append(f"      > ...")
                        results.append(" --> bach msg read <id> --ack zum Bestaetigen")
                    else:
                        # Allgemeine ungelesene
                        recent = conn_user.execute("""
                            SELECT sender, subject, created_at FROM messages
                            WHERE status = 'unread' ORDER BY created_at DESC LIMIT 3
                        """).fetchall()
                        for row in recent:
                            subj = (row['subject'] or "(kein Betreff)")[:30]
                            results.append(f"   Von: {row['sender']} - {subj}")
                else:
                    # Normale Anzeige fuer User
                    recent = conn_user.execute("""
                        SELECT sender, subject, created_at FROM messages
                        WHERE status = 'unread' ORDER BY created_at DESC LIMIT 3
                    """).fetchall()
                    for row in recent:
                        subj = (row['subject'] or "(kein Betreff)")[:30]
                        results.append(f"   Von: {row['sender']} - {subj}")
                results.append(" --> bach msg unread fuer Details")
            else:
                results.append(f" {total} Nachrichten, keine ungelesen")
            conn_user.close()
        except Exception as e:
            results.append(f" [ERROR] Nachrichten-Check: {e}")

        # ══════════════════════════════════════════════════════════════
        # 4.3 PARTNER PRESENCE - Andere aktive Partner erkennen (v1.1.71)
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[PARTNER-AWARENESS]")
        try:
            online_partners = self._get_online_partners(timeout_minutes=5)
            other_partners = [p for p in online_partners if p['partner'] != partner_id]
            
            if other_partners:
                results.append(f" *** {len(other_partners)} ANDERE PARTNER ONLINE ***")
                for p in other_partners:
                    task = p.get('task') or 'aktiv'
                    results.append(f"   {p['partner'].upper()}: {task[:40]}")
                results.append(" --> Protokoll V3 verwenden! (bach --help multi_llm)")
            else:
                results.append(f" Du arbeitest alleine ({partner_id.upper()})")
        except Exception as e:
            results.append(f" [SKIP] {e}")

        # ══════════════════════════════════════════════════════════════
        # 4.5 RECURRING TASKS CHECK - Faellige periodische Tasks
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[PERIODISCHE TASKS]")
        try:
            import sys
            recurring_path = self.base_path / "hub" / "_services" / "recurring"
            sys.path.insert(0, str(recurring_path))
            from recurring_tasks import list_recurring_tasks
            
            tasks = list_recurring_tasks()
            due_tasks = [(tid, info) for tid, info in tasks.items() 
                        if info.get('is_due') and info.get('enabled')]
            
            if due_tasks:
                results.append(f" *** {len(due_tasks)} TASK(S) FAELLIG ***")
                for tid, info in due_tasks[:3]:
                    target = "ATI" if info.get('target') == 'ati_tasks' else "BACH"
                    results.append(f"   [{tid}] {info.get('task_text', '')[:40]} -> {target}")
                if len(due_tasks) > 3:
                    results.append(f"   ... und {len(due_tasks) - 3} weitere")
                results.append(" --> bach --recurring check zum Erstellen")
            else:
                active = sum(1 for t in tasks.values() if t.get('enabled'))
                results.append(f" {len(tasks)} Tasks konfiguriert, {active} aktiv, keine faellig")
        except Exception as e:
            results.append(f" [SKIP] Recurring: {e}")

        # ══════════════════════════════════════════════════════════════
        # 5. BACH SYSTEM-TASKS
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[BACH SYSTEM-TASKS]")
        conn = None
        try:
            conn = self._get_conn()

            # System-Tasks aus bach.db/tasks
            open_tasks = conn.execute("""
                SELECT COUNT(*) FROM tasks WHERE status IN ('pending', 'open', 'in_progress')
            """).fetchone()[0]
            done_tasks = conn.execute("""
                SELECT COUNT(*) FROM tasks WHERE status = 'done'
            """).fetchone()[0]

            results.append(f" {open_tasks} offen, {done_tasks} erledigt")

            # Top 3 nach Prioritaet
            top_tasks = conn.execute("""
                SELECT id, title FROM tasks
                WHERE status IN ('pending', 'open', 'in_progress')
                ORDER BY
                    CASE WHEN title LIKE 'P1%' THEN 1
                         WHEN title LIKE 'P2%' THEN 2
                         WHEN title LIKE 'P3%' THEN 3
                         ELSE 4 END,
                    id
                LIMIT 3
            """).fetchall()

            if top_tasks:
                results.append(" Top-Aufgaben:")
                for tid, title in top_tasks:
                    results.append(f"   [{tid}] {title[:45]}")
                results.append("")
                results.append(" --> bach task list fuer alle")
        except Exception as e:
            results.append(f" [ERROR] {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        
        # ══════════════════════════════════════════════════════════════
        # 5.5 DELEGATION-VORSCHLAEGE - Tasks mit Partner-Keywords matchen
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[DELEGATION-VORSCHLAEGE]")
        conn = None
        try:
            conn = self._get_conn()

            # Keyword -> Partner Mapping (aus partner_registry.json abgeleitet)
            delegation_keywords = {
                "ollama": ["embed", "draft", "bulk", "zusammenfass", "embedding", "vektor"],
                "gemini": ["research", "analyse", "recherche", "dokument", "lang", "deep"],
                "copilot": ["code", "review", "refactor", "implement", "debug", "fix"],
                "perplexity": ["quelle", "source", "web", "aktuell", "news", "search"]
            }

            # Offene Tasks holen
            tasks = conn.execute("""
                SELECT id, title FROM tasks
                WHERE status IN ('pending', 'open', 'in_progress')
                ORDER BY id
            """).fetchall()

            suggestions = []
            for task_id, title in tasks:
                title_lower = title.lower()
                for partner, keywords in delegation_keywords.items():
                    for kw in keywords:
                        if kw in title_lower:
                            suggestions.append((task_id, title[:35], partner))
                            break
                    else:
                        continue
                    break

            if suggestions:
                results.append(f" {len(suggestions)} Task(s) mit Delegations-Potenzial:")
                for task_id, title, partner in suggestions[:3]:
                    results.append(f"   [{task_id}] {title}... -> {partner.upper()}")
                if len(suggestions) > 3:
                    results.append(f"   ... +{len(suggestions)-3} weitere")
                results.append(" --> bach partner delegate \"task\" --to=PARTNER")
            else:
                results.append(" Keine passenden Keywords in offenen Tasks")
        except Exception as e:
            results.append(f" [SKIP] {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        
        # ══════════════════════════════════════════════════════════════
        # 5.6 PARTNER-AUSLASTUNG WARNUNG - Doppelbearbeitung verhindern
        # ══════════════════════════════════════════════════════════════
        conn = None
        try:
            conn = self._get_conn()

            # Tasks nach Partner-Zuweisung (category-Feld) gruppieren
            partner_tasks = conn.execute("""
                SELECT LOWER(category) as cat, COUNT(*) as cnt
                FROM tasks
                WHERE status IN ('pending', 'open', 'in_progress')
                AND LOWER(category) NOT IN ('user', 'bach', 'system', 'gui', 'wiki', 'agents', 'core', 'mail', 'integ', 'ollama', 'task', 'deprecate')
                AND category IS NOT NULL
                AND category != ''
                GROUP BY LOWER(category)
                HAVING cnt > 1
                ORDER BY cnt DESC
            """).fetchall()

            if partner_tasks:
                results.append("")
                results.append("[PARTNER-AUSLASTUNG WARNUNG]")
                results.append(" *** PARTNER MIT MEHREREN OFFENEN TASKS ***")
                for partner, count in partner_tasks:
                    results.append(f"   {partner.upper()}: {count} offene Tasks")
                results.append(" HINWEIS: Doppelbearbeitung vermeiden!")
                results.append(" --> bach task list --filter PARTNER fuer Details")
        except Exception as e:
            pass  # Silent fail - nicht kritisch
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        
        # ══════════════════════════════════════════════════════════════
        # 6. ATI-HINWEIS (Software-Entwickler-Agent)
        # ══════════════════════════════════════════════════════════════
        # Der Scanner fuer AUFGABEN.txt gehoert zu ATI, nicht zu BACH!
        # Wenn ATI implementiert ist: bach ati status
        results.extend(self._ati_status_lines())
        
        # ══════════════════════════════════════════════════════════════
        # 7. LESSONS LEARNED
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[LESSONS LEARNED]")
        conn = None
        try:
            conn = self._get_conn()
            count = conn.execute("SELECT COUNT(*) FROM memory_lessons WHERE is_active=1").fetchone()[0]
            if count > 0:
                results.append(f" {count} Lessons gespeichert")
                lessons = conn.execute("""
                    SELECT category, title FROM memory_lessons
                    WHERE is_active=1 ORDER BY created_at DESC LIMIT 3
                """).fetchall()
                for cat, title in lessons:
                    results.append(f"   [{cat}] {title[:40]}")
                results.append(" --> bach lesson last fuer Details")
            else:
                results.append(" Keine Lessons vorhanden")
        except Exception as e:
            results.append(f" [ERROR] {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        
        # ══════════════════════════════════════════════════════════════
        # 8. AUTOLOG (.txt - bleibt Datei-basiert!)
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[AUTOLOG]")
        autolog = self.base_path / "data" / "logs" / "auto_log.txt"
        if autolog.exists():
            try:
                content = autolog.read_text(encoding="utf-8")
                lines = content.strip().split("\n")
                results.append(f" {len(lines)} Eintraege")
                # Letzte 3 Befehle
                cmd_lines = [l for l in lines if "CMD:" in l][-3:]
                if cmd_lines:
                    results.append(" Letzte Befehle:")
                    for line in cmd_lines:
                        parts = line.split("CMD:")
                        if len(parts) > 1:
                            results.append(f"   {parts[1].strip()[:40]}")
                results.append(" --> bach logs tail 20 fuer mehr")
            except (OSError, UnicodeDecodeError):
                results.append(" [?] Nicht lesbar")
        else:
            results.append(" Kein Autolog vorhanden")
        
        # ══════════════════════════════════════════════════════════════
        # 9. INJEKTOREN
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[INJEKTOREN]")
        try:
            from tools.injectors import InjectorConfig
            config = InjectorConfig(self.base_path / "config.json")
            active = [k.replace("_injector", "") for k, v in config.config.items() 
                     if k.endswith("_injector") and v]
            if active:
                results.append(f" Aktiv: {', '.join(active)}")
            else:
                results.append(" Alle deaktiviert")
        except Exception:
            results.append(" [SKIP] Injektoren nicht verfuegbar")
        
        # ══════════════════════════════════════════════════════════════
        # 10. HOUSEKEEPING-CHECK (alte Analysen in user/)
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[HOUSEKEEPING]")
        try:
            user_dir = self.base_path / "user"
            archive_patterns = ["*_ANALYSE_*", "ANALYSE_*", "*_synopse*", "*_vergleich*", 
                              "*_MAPPING*", "*_Landkarte*", "*_INTEGRATION_*"]
            old_docs = []
            for pattern in archive_patterns:
                for f in user_dir.glob(pattern):
                    if f.is_file() and "_archive" not in str(f):
                        old_docs.append(f.name)
            if old_docs:
                results.append(f" *** {len(old_docs)} ALTE ANALYSE-DOCS in user/ ***")
                for doc in old_docs[:3]:
                    results.append(f"   -> {doc}")
                if len(old_docs) > 3:
                    results.append(f"   ... +{len(old_docs)-3} weitere")
                results.append(" HINWEIS: Nach Bearbeitung in user/_archive verschieben")
            else:
                results.append(" [OK] Keine alten Analysen in user/")
        except Exception as e:
            results.append(f" [SKIP] Housekeeping: {e}")

        # ══════════════════════════════════════════════════════════════
        # 11. GUI/KONSOLE START (abhaengig vom Modus)
        # ══════════════════════════════════════════════════════════════
        config = self._load_user_config()
        mode_config = config.get("startup_modes", {}).get(startup_mode, {})
        start_gui = mode_config.get("gui", True)
        start_console = mode_config.get("console", False)

        results.append("")
        results.append(f"[STARTUP MODUS: {startup_mode.upper()}]")

        if startup_mode == "silent":
            results.append(" [SILENT] Kein automatischer Start")
        elif not dry_run:
            if start_gui:
                gui_started = self._start_gui_background()
                if gui_started:
                    results.append(" [OK] GUI Server gestartet (http://127.0.0.1:8000)")
                else:
                    results.append(" [SKIP] GUI bereits aktiv oder Fehler")
            else:
                results.append(" [SKIP] GUI deaktiviert (Modus: {})".format(startup_mode))

            if start_console:
                console_started = self._start_console_background()
                if console_started:
                    results.append(" [OK] Konsole gestartet")
                else:
                    results.append(" [SKIP] Konsole nicht gestartet")
        else:
            results.append(" [DRY-RUN] GUI/Konsole wuerde gestartet")
        
        # ══════════════════════════════════════════════════════════════
        # 11b. TOOL REMINDER (v1.1.73 - Tool-Reflektion #628)
        # ══════════════════════════════════════════════════════════════
        try:
            from tools.injectors import ToolInjector
            # Nur im Mode 'dual' oder 'text' anzeigen, nicht im reinen GUI mode (da scrollt es weg)
            if startup_mode in ["text", "dual"] or not start_gui:
                reminder = ToolInjector.get_startup_reminder(self.base_path)
                if reminder:
                    results.append("")
                    results.append(reminder)
        except Exception as e:
            pass # Silent fail

        # ══════════════════════════════════════════════════════════════
        # 12. TOKEN-ZONE CHECK (NEU v1.1.34)
        # ══════════════════════════════════════════════════════════════
        results.append("")
        results.append("[TOKEN-ZONE]")
        try:
            from tools.token_monitor import get_token_zone, format_zone_status, check_emergency_shutdown
            zone, desc, details = get_token_zone()
            results.append(format_zone_status(zone, desc, details))
            
            # TOKEN_001: Emergency Check bei 95%+
            should_stop, emergency_msg = check_emergency_shutdown(details.get('budget_percent'))
            if should_stop:
                results.append(emergency_msg)
        except Exception as e:
            results.append(f" [SKIP] Token-Monitor nicht verfuegbar: {e}")
        
        # ══════════════════════════════════════════════════════════════
        # 13. SYNC CHECK (SYNC_004b - Optional bei auto_sync_enabled)
        # ══════════════════════════════════════════════════════════════
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_config WHERE key = 'auto_sync_enabled'")
            row = cursor.fetchone()
            auto_sync = row and row[0] == 'true'
            
            if auto_sync:
                results.append("")
                results.append("[AUTO-SYNC]")
                from .sync import SyncHandler
                sync = SyncHandler(self.base_path)
                
                # Tatsaechlichen Sync ausfuehren (Batch #9 / SYNC_004)
                success_s, msg_s = sync._sync_skills(dry_run=dry_run)
                success_t, msg_t = sync._sync_tools(dry_run=dry_run)
                
                # Nur Zusammenfassung loggen
                s_log = msg_s.split('\n')[-1] if '\n' in msg_s else msg_s
                t_log = msg_t.split('\n')[-1] if '\n' in msg_t else msg_t
                results.append(f" Skills: {s_log}")
                results.append(f" Tools:  {t_log}")
                if not dry_run:
                    results.append(" [OK] Datenbank konsistent mit Dateisystem")
        except Exception as e:
            pass  # Silent fail - nicht kritisch
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        # Footer
        results.append("")
        results.append("=" * 55)
        results.append(" READY - Session gestartet")
        results.append("")
        results.append(" HINWEIS: Bei Shutdown -> bach --memory session \"...\"")
        
        # v1.1.73: Watch-Modus Hinweis für Multi-LLM
        if partner_id and partner_id != "user":
            results.append("")
            results.append(f" [CHAT] Fuer Live-Nachrichten: bach msg watch --from {partner_id}")
        
        results.append("=" * 55)
        
        return True, "\n".join(results)
    
    def _start_gui_background(self) -> bool:
        """Startet GUI-Server im Hintergrund und oeffnet Browser."""
        import os
        import socket
        import sys
        import subprocess

        if os.environ.get("BACH_NO_BROWSER", "").strip() in ("1", "true", "yes"):
            return False

        port = 8000
        server_script = self.base_path / "gui" / "server.py"

        if not server_script.exists():
            return False

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()

        already_running = (result == 0)

        if not already_running:
            try:
                if sys.platform == "win32":
                    subprocess.Popen(
                        [sys.executable, str(server_script), "--port", str(port)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    subprocess.Popen(
                        [sys.executable, str(server_script), "--port", str(port)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )

                import time
                time.sleep(1.5)

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()

                if result != 0:
                    return False

            except Exception:
                return False

        # Browser nur oeffnen wenn Server tatsaechlich erreichbar ist
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_reachable = sock.connect_ex(('127.0.0.1', port)) == 0
        sock.close()

        if server_reachable:
            try:
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{port}")
            except Exception:
                pass

        return server_reachable

    def _start_console_background(self) -> bool:
        """Startet eine neue Konsole mit bach.py im Text-Modus."""
        import sys
        import subprocess

        bach_py = self.base_path / "bach.py"
        if not bach_py.exists():
            return False

        try:
            if sys.platform == "win32":
                import os
                # Neues CMD-Fenster oeffnen mit bach.py
                bat_content = f'@echo off\ncd /d "{self.base_path}"\n"{sys.executable}" bach.py --help\nif not defined BACH_AUTO pause\n'
                import tempfile
                bat_file = Path(tempfile.gettempdir()) / "bach_terminal.bat"
                bat_file.write_text(bat_content, encoding="utf-8")
                subprocess.Popen(
                        [str(bat_file)],
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                    )
            else:
                # Linux/Mac: xterm oder gnome-terminal
                shell_cmd = f'cd "{self.base_path}" && "{sys.executable}" bach.py --help'
                if sys.platform == "darwin":
                    subprocess.Popen(
                        ["open", "-a", "Terminal", str(self.base_path / "bach.py")],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    import shutil
                    term = (
                        shutil.which("x-terminal-emulator")
                        or shutil.which("gnome-terminal")
                        or shutil.which("xterm")
                    )
                    if term and "gnome-terminal" in term:
                        subprocess.Popen(
                            [term, "--", "bash", "-c", shell_cmd],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                    elif term:
                        subprocess.Popen(
                            [term, "-e", "bash", "-c", shell_cmd],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                    else:
                        return False
            return True
        except Exception:
            return False
