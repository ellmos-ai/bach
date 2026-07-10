#!/usr/bin/env python3
# coding: utf-8
# SPDX-License-Identifier: MIT
"""
Multi-LLM Protocol Handler - Koordination paralleler Agenten
=============================================================

Protokoll V3 fuer sichere parallele Arbeit mehrerer LLMs:
1. PRESENCE - Anwesenheitserkennung via .<agent>_presence Dateien
2. LOCKING - Exklusiver Dateizugriff via <datei>.lock.<agent>
3. BACKUP - Automatische Sicherung vor Aenderungen
4. HANDSHAKE - Automatische Erkennung anderer Agenten

Entwickelt: 2026-01-28 durch Claude + Gemini Experiment
Lesson: #62, #63

CLI:
  bach llm presence          # Eigene Presence erstellen/aktualisieren
  bach llm check             # Andere Agenten erkennen
  bach llm lock <datei>      # Lock erwerben
  bach llm unlock <datei>    # Lock freigeben
  bach llm handshake         # Handshake-Protokoll starten
"""
import os
import glob
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple


class MultiLLMProtocol:
    """Handler fuer Multi-LLM Koordination."""
    
    # Bekannte Partner
    KNOWN_AGENTS = ['claude', 'gemini', 'copilot', 'ollama', 'perplexity', 'mistral-watcher']
    
    # Timeouts
    HEARTBEAT_INTERVAL = 30  # Sekunden
    PRESENCE_TIMEOUT = 120   # Sekunden bis "inaktiv"
    LOCK_TIMEOUT = 300       # Sekunden bis Lock als "stale" gilt
    BACKOFF_INTERVAL = 5     # Sekunden zwischen Lock-Checks
    
    def __init__(self, base_path: Path, agent_name: str = 'claude'):
        self.base_path = Path(base_path)
        self.agent_name = agent_name.lower()
        self.presence_file = None
        self.active_locks: List[Path] = []
    
    # =========================================================
    # PRESENCE SYSTEM
    # =========================================================
    
    def create_presence(self, working_dir: Path, working_on: str = 'idle') -> Path:
        """Erstellt/aktualisiert Presence-Datei im Arbeitsverzeichnis."""
        presence_file = working_dir / f'.{self.agent_name}_presence'
        
        content = f"""# {self.agent_name.upper()} PRESENCE
agent: {self.agent_name}
status: ACTIVE
started: {datetime.now().isoformat()}
heartbeat: {datetime.now().isoformat()}
working_on: {working_on}
current_file: none
lock_status: FREE
"""
        presence_file.write_text(content, encoding='utf-8')
        self.presence_file = presence_file
        return presence_file
    
    def update_heartbeat(self, working_on: str = None, 
                         current_file: str = None,
                         lock_status: str = None) -> bool:
        """Aktualisiert Heartbeat in Presence-Datei."""
        if not self.presence_file or not self.presence_file.exists():
            return False
        
        content = self.presence_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        
        new_lines = []
        for line in lines:
            if line.startswith('heartbeat:'):
                new_lines.append(f'heartbeat: {datetime.now().isoformat()}')
            elif line.startswith('working_on:') and working_on:
                new_lines.append(f'working_on: {working_on}')
            elif line.startswith('current_file:') and current_file:
                new_lines.append(f'current_file: {current_file}')
            elif line.startswith('lock_status:') and lock_status:
                new_lines.append(f'lock_status: {lock_status}')
            else:
                new_lines.append(line)
        
        self.presence_file.write_text('\n'.join(new_lines), encoding='utf-8')
        return True
    
    def set_finished(self, result: str = 'completed') -> bool:
        """Markiert Presence als beendet."""
        if not self.presence_file or not self.presence_file.exists():
            return False
        
        content = self.presence_file.read_text(encoding='utf-8')
        content = content.replace('status: ACTIVE', 'status: FINISHED')
        content += f'\nresult: {result}'
        self.presence_file.write_text(content, encoding='utf-8')
        return True
    
    def detect_other_agents(self, working_dir: Path) -> List[Dict]:
        """Erkennt andere aktive Agenten im Verzeichnis."""
        other_agents = []
        
        for agent in self.KNOWN_AGENTS:
            if agent == self.agent_name:
                continue
            
            # Verschiedene Presence-Formate pruefen
            patterns = [
                working_dir / f'.{agent}_presence',
                working_dir / f'{agent.upper()}.active',
                working_dir / f'.{agent}.active'
            ]
            
            for presence_path in patterns:
                if presence_path.exists():
                    info = self._parse_presence(presence_path, agent)
                    if info and info.get('is_active'):
                        other_agents.append(info)
                    break
        
        return other_agents
    
    def _parse_presence(self, filepath: Path, agent_name: str) -> Optional[Dict]:
        """Parst Presence-Datei und prueft Aktivitaet."""
        try:
            content = filepath.read_text(encoding='utf-8')
            info = {'agent': agent_name, 'file': filepath, 'is_active': False}
            
            for line in content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip().lower()] = value.strip()
            
            # Aktivitaet pruefen
            if 'heartbeat' in info:
                try:
                    heartbeat = datetime.fromisoformat(info['heartbeat'])
                    age = (datetime.now() - heartbeat).total_seconds()
                    info['is_active'] = age < self.PRESENCE_TIMEOUT
                    info['age_seconds'] = age
                except (ValueError, TypeError):
                    pass
            
            # Status pruefen
            if info.get('status', '').upper() == 'FINISHED':
                info['is_active'] = False
            
            return info
        except Exception as e:
            return None
    
    # =========================================================
    # LOCKING SYSTEM (Dateien + Ordner)
    # =========================================================
    
    def acquire_lock(self, filepath: Path, timeout: int = 60) -> Tuple[bool, Optional[Path]]:
        """
        Versucht Lock fuer Datei ODER Ordner zu erwerben.
        
        Datei-Lock: <datei>.lock.<agent>
        Ordner-Lock: <ordner>/.dirlock.<agent>
        
        Returns:
            (success, lock_path) - True + Pfad wenn erfolgreich
        """
        filepath = Path(filepath)
        
        # Ordner oder Datei?
        if filepath.is_dir():
            return self._acquire_dir_lock(filepath, timeout)
        else:
            return self._acquire_file_lock(filepath, timeout)
    
    def _acquire_file_lock(self, filepath: Path, timeout: int) -> Tuple[bool, Optional[Path]]:
        """Lock fuer einzelne Datei."""
        lock_file = filepath.parent / f"{filepath.name}.lock.{self.agent_name}"
        
        start_time = time.time()
        
        while True:
            # Pruefen ob fremder Lock existiert
            existing_locks = list(filepath.parent.glob(f"{filepath.name}.lock.*"))
            foreign_locks = [l for l in existing_locks 
                           if not l.name.endswith(f'.{self.agent_name}')]
            
            if not foreign_locks:
                # Kein fremder Lock - eigenen erstellen
                lock_content = f"""agent: {self.agent_name}
locked_at: {datetime.now().isoformat()}
type: file
target: {filepath.name}
"""
                lock_file.write_text(lock_content, encoding='utf-8')
                self.active_locks.append(lock_file)
                
                self.update_heartbeat(lock_status='LOCKED', current_file=filepath.name)
                self._update_db_current_task(f"FILE: {filepath.name}")
                
                return True, lock_file
            
            if time.time() - start_time > timeout:
                return False, None
            
            for foreign_lock in foreign_locks:
                if self._is_stale_lock(foreign_lock):
                    foreign_lock.unlink()
            
            time.sleep(self.BACKOFF_INTERVAL)
    
    def _acquire_dir_lock(self, dirpath: Path, timeout: int) -> Tuple[bool, Optional[Path]]:
        """Lock fuer ganzen Ordner."""
        lock_file = dirpath / f".dirlock.{self.agent_name}"
        
        start_time = time.time()
        
        while True:
            # Pruefen ob fremder Dir-Lock existiert
            existing_locks = list(dirpath.glob(".dirlock.*"))
            foreign_locks = [l for l in existing_locks 
                           if not l.name.endswith(f'.{self.agent_name}')]
            
            if not foreign_locks:
                lock_content = f"""agent: {self.agent_name}
locked_at: {datetime.now().isoformat()}
type: directory
target: {dirpath.name}
"""
                lock_file.write_text(lock_content, encoding='utf-8')
                self.active_locks.append(lock_file)
                
                self.update_heartbeat(lock_status='LOCKED', current_file=f"DIR:{dirpath.name}")
                self._update_db_current_task(f"DIR: {dirpath.name}")
                
                return True, lock_file
            
            if time.time() - start_time > timeout:
                return False, None
            
            for foreign_lock in foreign_locks:
                if self._is_stale_lock(foreign_lock):
                    foreign_lock.unlink()
            
            time.sleep(self.BACKOFF_INTERVAL)
    
    def release_lock(self, lock_file: Path = None) -> bool:
        """Gibt Lock frei."""
        if lock_file is None:
            # Alle eigenen Locks freigeben
            for lf in self.active_locks:
                if lf.exists():
                    lf.unlink()
            self.active_locks = []
        else:
            lock_file = Path(lock_file)
            if lock_file.exists():
                lock_file.unlink()
            if lock_file in self.active_locks:
                self.active_locks.remove(lock_file)
        
        self.update_heartbeat(lock_status='FREE', current_file='none')
        
        # DB-Update: current_task leeren (v1.1.71 Live-Status)
        self._update_db_current_task(None)
        
        return True
    
    def _is_stale_lock(self, lock_file: Path) -> bool:
        """Prueft ob Lock veraltet ist."""
        try:
            content = lock_file.read_text(encoding='utf-8')
            for line in content.split('\n'):
                if line.startswith('locked_at:'):
                    lock_time = datetime.fromisoformat(line.split(':', 1)[1].strip())
                    age = (datetime.now() - lock_time).total_seconds()
                    return age > self.LOCK_TIMEOUT
        except (OSError, ValueError):
            pass
        return False
    
    def _update_db_current_task(self, task: str = None) -> bool:
        """Aktualisiert current_task in partner_presence DB (v1.1.71 Live-Status)."""
        try:
            import sqlite3
            db_path = self.base_path / "data" / "bach.db"
            conn = sqlite3.connect(str(db_path))
            now = datetime.now().isoformat()
            
            conn.execute("""
                UPDATE partner_presence 
                SET current_task = ?, last_heartbeat = ?, updated_at = ?
                WHERE partner_name = ? AND status = 'online'
            """, (task, now, now, self.agent_name))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False
    
    def check_lock(self, filepath: Path) -> Optional[str]:
        """Prueft wer Lock auf Datei hat. Returns agent name oder None."""
        filepath = Path(filepath)
        locks = list(filepath.parent.glob(f"{filepath.name}.lock.*"))
        
        for lock in locks:
            # Agent aus Dateiname extrahieren
            agent = lock.name.split('.lock.')[-1]
            if not self._is_stale_lock(lock):
                return agent
        return None
    
    # =========================================================
    # BACKUP SYSTEM
    # =========================================================
    
    def create_backup(self, filepath: Path) -> Path:
        """Erstellt Backup einer Datei vor Aenderung."""
        filepath = Path(filepath)
        backup_path = filepath.parent / f"{filepath.name}.bak"
        
        if filepath.exists():
            import shutil
            shutil.copy2(filepath, backup_path)
        
        return backup_path
    
    # =========================================================
    # HANDSHAKE PROTOCOL
    # =========================================================
    
    def initiate_handshake(self, working_dir: Path) -> Dict:
        """
        Startet Handshake-Protokoll zur Auto-Detection.
        
        1. Presence erstellen
        2. Andere Agenten erkennen
        3. Handshake-Signal senden
        4. Auf Bestaetigung warten
        """
        result = {
            'status': 'initiated',
            'my_agent': self.agent_name,
            'detected_agents': [],
            'handshake_complete': False
        }
        
        # 1. Presence erstellen
        self.create_presence(working_dir, 'HANDSHAKE_INITIATED')
        
        # 2. Andere Agenten erkennen
        others = self.detect_other_agents(working_dir)
        result['detected_agents'] = [a['agent'] for a in others]
        
        if not others:
            result['status'] = 'alone'
            return result
        
        # 3. Handshake-Signal erstellen
        handshake_file = working_dir / f'.handshake_{self.agent_name}'
        handshake_content = f"""# HANDSHAKE REQUEST
from: {self.agent_name}
to: {', '.join(result['detected_agents'])}
time: {datetime.now().isoformat()}
protocol: V3
message: Requesting coordination protocol activation
"""
        handshake_file.write_text(handshake_content, encoding='utf-8')
        
        # 4. Auf Bestaetigung warten (max 30 Sek)
        start = time.time()
        while time.time() - start < 30:
            for agent in result['detected_agents']:
                response_file = working_dir / f'.handshake_{agent}'
                if response_file.exists():
                    content = response_file.read_text(encoding='utf-8')
                    if self.agent_name in content and 'ACCEPTED' in content:
                        result['handshake_complete'] = True
                        result['status'] = 'connected'
                        return result
            time.sleep(2)
        
        result['status'] = 'timeout'
        return result
    
    def respond_to_handshake(self, working_dir: Path, 
                             from_agent: str) -> bool:
        """Antwortet auf Handshake-Anfrage."""
        response_file = working_dir / f'.handshake_{self.agent_name}'
        
        content = f"""# HANDSHAKE RESPONSE
from: {self.agent_name}
to: {from_agent}
time: {datetime.now().isoformat()}
status: ACCEPTED
protocol: V3
message: Protocol V3 activated. Ready for coordination.
"""
        response_file.write_text(content, encoding='utf-8')
        
        self.update_heartbeat(working_on=f'COORDINATING_WITH_{from_agent}')
        return True
    
    # =========================================================
    # SAFE FILE OPERATIONS
    # =========================================================
    
    def safe_write(self, filepath: Path, content: str, 
                   timeout: int = 60) -> Tuple[bool, str]:
        """
        Sichere Schreiboperation mit Lock + Backup.
        
        Returns:
            (success, message)
        """
        filepath = Path(filepath)
        
        # 1. Lock erwerben
        success, lock_file = self.acquire_lock(filepath, timeout)
        if not success:
            return False, f"Could not acquire lock (timeout {timeout}s)"
        
        try:
            # 2. Backup erstellen
            if filepath.exists():
                self.create_backup(filepath)
            
            # 3. Schreiben
            filepath.write_text(content, encoding='utf-8')
            
            return True, "Write successful"
        except Exception as e:
            return False, f"Write failed: {e}"
        finally:
            # 4. Lock freigeben
            self.release_lock(lock_file)
    
    def safe_append(self, filepath: Path, content: str,
                    timeout: int = 60) -> Tuple[bool, str]:
        """Sicheres Anhaengen mit Lock."""
        filepath = Path(filepath)
        
        success, lock_file = self.acquire_lock(filepath, timeout)
        if not success:
            return False, f"Could not acquire lock"
        
        try:
            if filepath.exists():
                self.create_backup(filepath)
                existing = filepath.read_text(encoding='utf-8')
            else:
                existing = ""
            
            filepath.write_text(existing + content, encoding='utf-8')
            return True, "Append successful"
        except Exception as e:
            return False, f"Append failed: {e}"
        finally:
            self.release_lock(lock_file)


# =========================================================
# CLI HANDLER INTERFACE
# =========================================================

class MultiLLMHandler:
    """CLI Handler fuer bach llm Befehle."""
    
    def __init__(self, base_path: Path, agent_name: str = 'claude'):
        self.base_path = Path(base_path)
        self.protocol = MultiLLMProtocol(base_path, agent_name)
    
    def handle(self, operation: str, args: list) -> Tuple[bool, str]:
        """Haupteinstiegspunkt fuer CLI."""
        
        if operation == 'presence':
            return self._cmd_presence(args)
        elif operation == 'check':
            return self._cmd_check(args)
        elif operation == 'lock':
            return self._cmd_lock(args)
        elif operation == 'unlock':
            return self._cmd_unlock(args)
        elif operation == 'handshake':
            return self._cmd_handshake(args)
        elif operation == 'status':
            return self._cmd_status(args)
        else:
            return self._cmd_help()
    
    def _cmd_presence(self, args: list) -> Tuple[bool, str]:
        """Erstellt Presence im aktuellen oder angegebenen Verzeichnis."""
        working_dir = Path(args[0]) if args else Path.cwd()
        working_on = args[1] if len(args) > 1 else 'active'
        
        presence = self.protocol.create_presence(working_dir, working_on)
        return True, f"[OK] Presence erstellt: {presence}"
    
    def _cmd_check(self, args: list) -> Tuple[bool, str]:
        """Prueft auf andere Agenten."""
        working_dir = Path(args[0]) if args else Path.cwd()
        others = self.protocol.detect_other_agents(working_dir)
        
        if not others:
            return True, "Keine anderen Agenten erkannt."
        
        lines = ["Erkannte Agenten:"]
        for agent in others:
            status = "AKTIV" if agent.get('is_active') else "INAKTIV"
            age = int(agent.get('age_seconds', 0))
            lines.append(f"  - {agent['agent']}: {status} (Heartbeat vor {age}s)")
        
        return True, "\n".join(lines)
    
    def _cmd_lock(self, args: list) -> Tuple[bool, str]:
        """Erwirbt Lock fuer Datei."""
        if not args:
            return False, "Usage: bach llm lock <datei>"
        
        filepath = Path(args[0])
        success, lock = self.protocol.acquire_lock(filepath)
        
        if success:
            return True, f"[OK] Lock erworben: {lock}"
        else:
            holder = self.protocol.check_lock(filepath)
            return False, f"Lock fehlgeschlagen. Gehalten von: {holder}"
    
    def _cmd_unlock(self, args: list) -> Tuple[bool, str]:
        """Gibt Lock frei."""
        if args:
            filepath = Path(args[0])
            lock_file = filepath.parent / f"{filepath.name}.lock.{self.protocol.agent_name}"
            self.protocol.release_lock(lock_file)
        else:
            self.protocol.release_lock()
        
        return True, "[OK] Lock(s) freigegeben"
    
    def _cmd_handshake(self, args: list) -> Tuple[bool, str]:
        """Startet Handshake-Protokoll."""
        working_dir = Path(args[0]) if args else Path.cwd()
        result = self.protocol.initiate_handshake(working_dir)
        
        lines = [
            f"Handshake Status: {result['status']}",
            f"Erkannte Agenten: {', '.join(result['detected_agents']) or 'keine'}",
            f"Verbindung: {'OK' if result['handshake_complete'] else 'ausstehend'}"
        ]
        
        return True, "\n".join(lines)
    
    def _cmd_status(self, args: list) -> Tuple[bool, str]:
        """Zeigt Multi-LLM Status inkl. DB Live-Status (v1.1.71)."""
        working_dir = Path(args[0]) if args else Path.cwd()
        
        # Eigene Presence pruefen
        own_presence = working_dir / f'.{self.protocol.agent_name}_presence'
        own_status = "AKTIV" if own_presence.exists() else "KEINE PRESENCE"
        
        # Andere Agenten (Datei-basiert)
        others = self.protocol.detect_other_agents(working_dir)
        
        # Locks im Verzeichnis
        locks = list(working_dir.glob('*.lock.*'))
        
        # DB-basierter Live-Status (v1.1.71)
        db_partners = self._get_db_live_status()
        
        lines = [
            "=== MULTI-LLM STATUS ===",
            f"Eigener Agent: {self.protocol.agent_name} ({own_status})",
            f"Andere Agenten: {len(others)}",
            f"Aktive Locks: {len(locks)}",
        ]
        
        # DB Live-Status
        if db_partners:
            lines.append("\n[LIVE-STATUS] (partner_presence DB):")
            for p in db_partners:
                task = p.get('current_task') or 'idle'
                hb = p.get('heartbeat', '')[:19] if p.get('heartbeat') else '?'
                lines.append(f"  {p['partner'].upper()}: {task} (HB: {hb[11:]})")
        
        if others:
            lines.append("\nErkannte Partner (Dateien):")
            for a in others:
                lines.append(f"  - {a['agent']}")
        
        if locks:
            lines.append("\nAktive Locks:")
            for l in locks:
                lines.append(f"  - {l.name}")
        
        return True, "\n".join(lines)
    
    def _get_db_live_status(self) -> list:
        """Holt Live-Status aus partner_presence DB."""
        try:
            import sqlite3
            db_path = self.base_path / "data" / "bach.db"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            
            rows = conn.execute("""
                SELECT partner_name, status, current_task, last_heartbeat
                FROM partner_presence 
                WHERE status = 'online'
                ORDER BY last_heartbeat DESC
            """).fetchall()
            conn.close()
            
            return [{'partner': r['partner_name'], 'status': r['status'],
                    'current_task': r['current_task'], 'heartbeat': r['last_heartbeat']}
                   for r in rows]
        except Exception:
            return []
    
    def _cmd_help(self) -> Tuple[bool, str]:
        """Zeigt Hilfe."""
        return True, """Multi-LLM Protocol - Koordination paralleler Agenten

Befehle:
  bach llm presence [dir] [task]  Presence erstellen/aktualisieren
  bach llm check [dir]            Andere Agenten erkennen
  bach llm lock <datei>           Lock erwerben
  bach llm unlock [datei]         Lock freigeben
  bach llm handshake [dir]        Handshake-Protokoll starten
  bach llm status [dir]           Status anzeigen

Protokoll V3:
  1. Presence-Dateien: .<agent>_presence
  2. Lock-Dateien: <datei>.lock.<agent>
  3. Backup vor Aenderung: <datei>.bak
  4. Handshake: .handshake_<agent>

Siehe: bach --help multi_llm"""


# =========================================================
# STEMPELKARTEN-SYSTEM (DB-basiert)
# =========================================================

class PartnerPresenceDB:
    """DB-basiertes Stempelkarten-System fuer Partner-Awareness."""
    
    def __init__(self, db_path: Path, agent_name: str = 'claude'):
        self.db_path = Path(db_path)
        self.agent_name = agent_name.lower()
    
    def _get_conn(self):
        import sqlite3
        return sqlite3.connect(self.db_path)
    
    def clock_in(self, task: str = None, working_dir: str = None, 
                 session_id: str = None) -> bool:
        """Einstempeln beim Startup."""
        now = datetime.now().isoformat()
        
        with self._get_conn() as conn:
            # Pruefen ob bereits eingestempelt (crashed session?)
            existing = conn.execute(
                "SELECT id, status FROM partner_presence WHERE partner_name = ? AND status = 'online'",
                (self.agent_name,)
            ).fetchone()
            
            if existing:
                # Vorherige Session war nicht sauber beendet
                conn.execute(
                    "UPDATE partner_presence SET status = 'crashed', clocked_out = ? WHERE id = ?",
                    (now, existing[0])
                )
            
            # Neu einstempeln
            conn.execute("""
                INSERT INTO partner_presence 
                (partner_name, status, clocked_in, last_heartbeat, current_task, working_dir, session_id)
                VALUES (?, 'online', ?, ?, ?, ?, ?)
            """, (self.agent_name, now, now, task, working_dir, session_id))
            conn.commit()
        
        return True
    
    def clock_out(self) -> bool:
        """Ausstempeln beim Shutdown."""
        now = datetime.now().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE partner_presence 
                SET status = 'offline', clocked_out = ?, updated_at = ?
                WHERE partner_name = ? AND status = 'online'
            """, (now, now, self.agent_name))
            conn.commit()
        
        return True
    
    def heartbeat(self, task: str = None) -> bool:
        """Heartbeat aktualisieren."""
        now = datetime.now().isoformat()
        
        with self._get_conn() as conn:
            if task:
                conn.execute("""
                    UPDATE partner_presence 
                    SET last_heartbeat = ?, current_task = ?, updated_at = ?
                    WHERE partner_name = ? AND status = 'online'
                """, (now, task, now, self.agent_name))
            else:
                conn.execute("""
                    UPDATE partner_presence 
                    SET last_heartbeat = ?, updated_at = ?
                    WHERE partner_name = ? AND status = 'online'
                """, (now, now, self.agent_name))
            conn.commit()
        
        return True
    
    def get_online_partners(self, timeout_minutes: int = 5) -> List[Dict]:
        """Hole alle online Partner (mit Heartbeat-Timeout-Check)."""
        cutoff = (datetime.now() - timedelta(minutes=timeout_minutes)).isoformat()
        
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT partner_name, clocked_in, last_heartbeat, current_task, working_dir
                FROM partner_presence 
                WHERE status = 'online' AND last_heartbeat > ?
            """, (cutoff,)).fetchall()
        
        return [dict(r) for r in rows]
    
    def get_partner_count(self, include_self: bool = False, 
                         timeout_minutes: int = 5) -> int:
        """Anzahl online Partner."""
        partners = self.get_online_partners(timeout_minutes)
        if not include_self:
            partners = [p for p in partners if p['partner_name'] != self.agent_name]
        return len(partners)
    
    def get_presence_status(self) -> str:
        """Generiert Injektor-Text fuer Partner-Awareness."""
        partners = self.get_online_partners()
        count = len(partners)
        
        if count == 0:
            return "[SOLO] Du arbeitest alleine."
        elif count == 1 and partners[0]['partner_name'] == self.agent_name:
            return "[SOLO] Du arbeitest alleine."
        else:
            other_partners = [p for p in partners if p['partner_name'] != self.agent_name]
            if not other_partners:
                return "[SOLO] Du arbeitest alleine."
            
            names = [p['partner_name'].capitalize() for p in other_partners]
            tasks = [p.get('current_task', '?') for p in other_partners]
            
            lines = [f"[MULTI-LLM] {len(other_partners)+1} Partner online:"]
            for name, task in zip(names, tasks):
                lines.append(f"  - {name}: {task or 'aktiv'}")
            lines.append("  -> Protokoll V3 verwenden!")
            
            return "\n".join(lines)


# Erweitere MultiLLMHandler um DB-Funktionen
def _extend_handler():
    """Patch fuer CLI-Integration."""
    pass  # Wird beim Import ausgefuehrt
