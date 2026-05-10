# SPDX-License-Identifier: MIT
"""
Sync Handler - Dateisystem zu DB Synchronisation
=================================================

--sync skills           Skills-Inhalte von Dateien in DB laden
--sync tools            Tools-Inhalte von Dateien in DB laden
--sync all              Beides synchronisieren
--sync status           Sync-Status anzeigen (Hash-Vergleich)

Optionen:
  --dry-run             Aenderungen nur anzeigen, nicht ausfuehren
  --force               Hash ignorieren, alles neu laden

Konflikt-Regel (SQ044):
  Dateisystem ist autoritativ fuer Editing, DB ist autoritativ fuer Suche/Distribution.
  Bei Konflikt gewinnt das Dateisystem (neuerer Timestamp).
  Lazy Auto-Sync bei Startup prueft Ordner-mtime und synchronisiert nur Aenderungen.
"""
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class SyncHandler(BaseHandler):
    """Handler fuer --sync Operationen (Phase 7 DB-Content-Sync)"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.skills_dir = base_path / "skills"
        self.tools_dir = base_path / "tools"
        self.base_path = base_path
        self.db_path = self._canonical_db
    
    def _get_connection(self):
        """SQLite-Verbindung zur BACH-Datenbank."""
        return sqlite3.connect(self.db_path)
    
    @property
    def profile_name(self) -> str:
        return "sync"
    
    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / "bach.db"
    
    def get_operations(self) -> dict:
        return {
            "skills": "Skills-Inhalte von Dateien in DB laden",
            "tools": "Tools-Inhalte von Dateien in DB laden",
            "all": "Beides synchronisieren",
            "status": "Sync-Status anzeigen (Hash-Vergleich)"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        # Flags extrahieren
        dry_run = dry_run or '--dry-run' in args
        force = '--force' in args
        args = [a for a in args if not a.startswith('--')]
        
        if operation == "skills":
            return self._sync_skills(dry_run, force)
        elif operation == "tools":
            return self._sync_tools(dry_run, force)
        elif operation == "all":
            # Beide synchronisieren
            result_skills, msg_skills = self._sync_skills(dry_run, force)
            result_tools, msg_tools = self._sync_tools(dry_run, force)
            combined_msg = f"{msg_skills}\n\n{msg_tools}"
            return result_skills and result_tools, combined_msg
        elif operation == "status":
            return self._status()
        else:
            return self._status()
    
    def _extract_description(self, content: str) -> str:
        """Extrahiert die erste Zeile des Docstrings oder Kommentars."""
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith('"""') or line.startswith("'''"):
                clean = line.replace('"""', '').replace("'''", '').strip()
                if clean: return clean
                continue
            if line.startswith('#'):
                return line.replace('#', '').strip()
            if not line.startswith('import') and not line.startswith('from'):
                return line[:100]
        return ""

    def _compute_hash(self, content: str) -> str:
        """Berechnet SHA256 Hash fuer Content-String."""
        return hashlib.sha256(content.encode('utf-8', errors='replace')).hexdigest()

    def _sync_skills(self, dry_run: bool = False, force: bool = False) -> tuple:
        """Skills von Dateisystem in DB synchronisieren (inkl. Discovery)."""
        results = ["[SYNC SKILLS]", "=" * 50]
        
        stats = {"synced": 0, "unchanged": 0, "new": 0, "missing": 0, "errors": 0}
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Alle .md und .txt Dateien in skills/ (rekursiv)
            skill_files = []
            for ext in ["*.md", "*.txt", "*.py"]:
                skill_files.extend(list(self.skills_dir.rglob(ext)))
            
            results.append(f"Gefunden: {len(skill_files)} potenzielle Skills in skills/\n")
            
            for full_path in skill_files:
                if full_path.name.startswith(("_", ".")) and full_path.suffix != ".py":
                    continue # Überspringe interne Dateien außer Python-Services
                
                rel_path = str(full_path.relative_to(self.base_path)).replace("\\", "/")
                name = full_path.stem
                
                try:
                    content = full_path.read_text(encoding='utf-8', errors='replace')
                    file_hash = self._compute_hash(content)
                    description = self._extract_description(content)
                    
                    cursor.execute("SELECT id, content_hash FROM skills WHERE name = ? OR path = ?", (name, rel_path))
                    row = cursor.fetchone()
                    
                    if row:
                        skill_id, db_hash = row
                        if db_hash == file_hash and not force:
                            stats["unchanged"] += 1
                            continue
                        
                        if not dry_run:
                            cursor.execute("""
                                UPDATE skills 
                                SET content = ?, content_hash = ?, path = ?, description = CASE WHEN description IS NULL OR description = '' THEN ? ELSE description END, updated_at = ?
                                WHERE id = ?
                            """, (content, file_hash, rel_path, description, datetime.now().isoformat(), skill_id))
                        stats["synced"] += 1
                        results.append(f"  [SYNC] {name}")
                    else:
                        if not dry_run:
                            cursor.execute("""
                                INSERT INTO skills (name, type, category, path, content, content_hash, description, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (name, "file", "general", rel_path, content, file_hash, description, datetime.now().isoformat()))
                        stats["new"] += 1
                        results.append(f"  [NEU] {name}")
                        
                except Exception as e:
                    stats["errors"] += 1
                    results.append(f"  [ERROR] {name}: {str(e)}")
            
            if not dry_run:
                conn.commit()
            conn.close()
            
        except Exception as e:
            return False, f"DB-Fehler: {str(e)}"
        
        results.append(f"\nStatus: {stats['synced']} aktualisiert, {stats['new']} neu, {stats['unchanged']} OK")
        return True, "\n".join(results)
    
    def _sync_tools(self, dry_run: bool = False, force: bool = False) -> tuple:
        """Tools von Dateisystem in DB synchronisieren."""
        results = ["[SYNC TOOLS]", "=" * 50]
        
        stats = {"synced": 0, "unchanged": 0, "new": 0, "errors": 0}
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Alle Python-Dateien in tools/ (rekursiv)
            tool_files = list(self.tools_dir.rglob("*.py"))
            results.append(f"Gefunden: {len(tool_files)} Python-Dateien in tools/\n")
            
            for tool_path in tool_files:
                if tool_path.name.startswith(("_", ".")): continue
                
                tool_name = tool_path.stem
                rel_path = str(tool_path.relative_to(self.base_path)).replace("\\", "/")
                
                try:
                    content = tool_path.read_text(encoding='utf-8', errors='replace')
                    file_hash = self._compute_hash(content)
                    description = self._extract_description(content)
                    
                    cursor.execute("SELECT id, content_hash FROM tools WHERE name = ?", (tool_name,))
                    row = cursor.fetchone()
                    
                    if row:
                        tool_id, db_hash = row
                        if db_hash == file_hash and not force:
                            stats["unchanged"] += 1
                            continue
                        
                        if not dry_run:
                            cursor.execute("""
                                UPDATE tools 
                                SET content = ?, content_hash = ?, path = ?, description = CASE WHEN description IS NULL OR description = '' THEN ? ELSE description END, updated_at = ?
                                WHERE id = ?
                            """, (content, file_hash, rel_path, description, datetime.now().isoformat(), tool_id))
                        stats["synced"] += 1
                        results.append(f"  [SYNC] {tool_name}")
                    else:
                        if not dry_run:
                            cursor.execute("""
                                INSERT INTO tools (name, type, category, path, content, content_hash, template_content, description, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (tool_name, "python", "general", rel_path, content, file_hash, content, description, datetime.now().isoformat()))
                        stats["new"] += 1
                        results.append(f"  [NEU] {tool_name}")
                        
                except Exception as e:
                    stats["errors"] += 1
                    results.append(f"  [ERROR] {tool_name}: {str(e)}")
            
            if not dry_run:
                conn.commit()
            conn.close()
            
        except Exception as e:
            return False, f"DB-Fehler: {str(e)}"
        
        results.append(f"\nStatus: {stats['synced']} aktualisiert, {stats['new']} neu, {stats['unchanged']} OK")
        return True, "\n".join(results)
    
    def _status(self) -> tuple:
        """Sync-Status anzeigen - welche Dateien haben sich geaendert."""
        results = ["[SYNC STATUS]", "=" * 50]
        
        stats = {"skills_changed": 0, "skills_ok": 0, "tools_changed": 0, "tools_ok": 0}
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Skills pruefen
            results.append("\n[SKILLS]")
            cursor.execute("SELECT name, path, content_hash FROM skills WHERE path IS NOT NULL AND path != ''")
            skills = cursor.fetchall()
            
            for name, rel_path, db_hash in skills:
                full_path = self.base_path / rel_path
                if full_path.exists():
                    content = full_path.read_text(encoding='utf-8')
                    file_hash = self._compute_hash(content)
                    if db_hash != file_hash:
                        results.append(f"  [GEAENDERT] {name}")
                        stats["skills_changed"] += 1
                    else:
                        stats["skills_ok"] += 1
                else:
                    results.append(f"  [FEHLT] {name}")
            
            # Tools pruefen
            results.append("\n[TOOLS]")
            tool_files = list(self.tools_dir.glob("*.py"))
            
            for tool_path in tool_files:
                tool_name = tool_path.stem
                content = tool_path.read_text(encoding='utf-8')
                file_hash = self._compute_hash(content)
                
                cursor.execute("SELECT content_hash FROM tools WHERE name = ?", (tool_name,))
                row = cursor.fetchone()
                
                if row:
                    if row[0] != file_hash:
                        results.append(f"  [GEAENDERT] {tool_name}")
                        stats["tools_changed"] += 1
                    else:
                        stats["tools_ok"] += 1
                else:
                    results.append(f"  [NEU] {tool_name}")
                    stats["tools_changed"] += 1
            
            conn.close()
            
        except Exception as e:
            return False, f"DB-Fehler: {str(e)}"
        
        # Zusammenfassung
        results.append("")
        results.append("ZUSAMMENFASSUNG:")
        results.append(f"  Skills: {stats['skills_changed']} geaendert, {stats['skills_ok']} OK")
        results.append(f"  Tools:  {stats['tools_changed']} geaendert, {stats['tools_ok']} OK")
        
        if stats['skills_changed'] + stats['tools_changed'] > 0:
            results.append("\n--> bach --sync all zum Synchronisieren")
        else:
            results.append("\n[OK] Alles synchron")
        
        return True, "\n".join(results)
