#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Interaction Protocol System v1.0.0 (migrated from RecludOS)

Vollständiges Protokoll für Instanz-zu-Instanz-Kommunikation:
- Handshake (gegenseitige Erkennung)
- Compare (was kann ich lernen)
- Request/Transfer (Daten austauschen)
- Receipt (Bestätigung)
- DNA-Tracking (woher kommen meine Teile)

Migriert: 2026-01-22
Original: RecludOS interaction_protocol.py
Status: COMPLETE MIGRATION - 100% fertig (Sektionen 1-8)

Changelog:
- 2026-01-22 15:49: Sektion 7 (Receipt) + Sektion 8 (Mutation) migriert
- 2026-01-22 15:33: Sektion 6 (Import) migriert
- 2026-01-22 15:00: Sektionen 1-5 migriert
"""

import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# =========================================================================
# BACH PFAD-DEFINITIONEN (MIGRIERT)
# =========================================================================

SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parents[1]  # tools/ -> BACH_ROOT

# Kommunikationsverzeichnisse in BACH
COMMUNICATE_DIR = SCRIPT_DIR  # tools/partner_communication/
PROTOCOLS_DIR = COMMUNICATE_DIR / "protocols"
INBOX_DIR = COMMUNICATE_DIR / "inbox"
OUTBOX_DIR = COMMUNICATE_DIR / "outbox"

# Identity: BACH verwendet bach.db statt identity.json
# TODO: Umstellung auf DB-basierte Identity
IDENTITY_FILE = BACH_ROOT / "data" / "identity.json"  # Fallback bis DB-Integration
PENDING_APPROVALS_FILE = BACH_ROOT / "data" / "pending_approvals.json"
BACH_DB = BACH_ROOT / "data" / "bach.db"

# Signatur-Dateien für BACH-Erkennung
SIGNATURE_FILES = [
    "SKILL.md",
    "bach.py"
]

# Komponenten die gelernt werden können (BACH-Äquivalente)
LEARNABLE_COMPONENTS = [
    "lessons",          # memory_lessons in bach.db
    "facts",            # memory_facts in bach.db
    "skills",           # skills/ Verzeichnis
    "templates"         # templates/ Verzeichnis
]


class InteractionProtocol:
    """
    Vollständiges Interaction Protocol für BACH Instanzen.
    
    Implementiert:
    - Ich kenne mich (get_identity_card)
    - Ich erkenne soetwas wie ich (discover)
    - Ich identifiziere dich (handshake)
    - Ich prüfe was ich lernen kann (compare_with)
    - Ich frage ob ich lernen soll (request_user_approval)
    - Ich lerne von dir (import_from)
    - Du weißt dass ich gelernt habe (send_receipt)
    - Ich bin anders als vorher (_record_mutation)
    """
    
    def __init__(self, root_path: Path = None):
        self.root = root_path or BACH_ROOT
        self.identity_file = self.root / "data" / "identity.json"
        self.db_path = self.root / "data" / "bach.db"
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """Erstellt notwendige Verzeichnisse."""
        for d in [PROTOCOLS_DIR, INBOX_DIR, OUTBOX_DIR]:
            d.mkdir(parents=True, exist_ok=True)
        for subdir in ["handshakes", "requests", "transfers", "receipts"]:
            (INBOX_DIR / subdir).mkdir(exist_ok=True)
            (OUTBOX_DIR / subdir).mkdir(exist_ok=True)
    
    # =========================================================================
    # 1. ICH KENNE MICH
    # =========================================================================
    
    def get_identity_card(self) -> Dict:
        """
        Erstellt kompakte Identity-Card für Handshake.
        
        Returns:
            Dict mit Kurzform der Identität
        """
        identity = self._load_identity()
        if not identity:
            # Fallback: Aus system_identity in bach.db
            identity = self._load_identity_from_db()
            if not identity:
                return {"error": "Keine Identität gefunden"}
        
        # DNA-Zusammenfassung
        dna_summary = {}
        for source, info in identity.get("dna", {}).get("composition", {}).items():
            dna_summary[source] = info.get("percentage", 0)
        
        return {
            "instance_id": identity.get("instance", {}).get("id", "bach-" + os.urandom(4).hex()),
            "instance_name": identity.get("instance", {}).get("name", "BACH Instance"),
            "distribution": identity.get("lineage", {}).get("base_distribution", "BACH"),
            "distribution_version": identity.get("seal", {}).get("current", {}).get("kernel_version", "1.1.x"),
            "seal_type": identity.get("seal", {}).get("current", {}).get("type", "personal"),
            "seal_status": identity.get("seal", {}).get("current", {}).get("status", "active"),
            "generation": identity.get("lineage", {}).get("generation", 1),
            "dna_summary": dna_summary,
            "mutations_count": len(identity.get("mutations", [])),
            "created": identity.get("instance", {}).get("created", datetime.now().isoformat())
        }
    
    def _load_identity(self) -> Optional[Dict]:
        """Lädt Identity aus JSON."""
        if not self.identity_file.exists():
            return None
        try:
            return json.loads(self.identity_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return None
    
    def _load_identity_from_db(self) -> Optional[Dict]:
        """Lädt Identity aus bach.db (system_identity Tabelle)."""
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM system_identity")
            rows = cursor.fetchall()
            conn.close()
            
            if rows:
                identity = {
                    "instance": {
                        "id": "bach-instance",
                        "name": "BACH"
                    },
                    "lineage": {"base_distribution": "BACH"},
                    "dna": {"composition": {}},
                    "mutations": []
                }
                for key, value in rows:
                    if key == "instance_id":
                        identity["instance"]["id"] = value
                    elif key == "instance_name":
                        identity["instance"]["name"] = value
                return identity
        except (sqlite3.Error, OSError):
            pass
        return None
    
    def _save_identity(self, identity: Dict):
        """Speichert Identity in JSON."""
        self.identity_file.parent.mkdir(parents=True, exist_ok=True)
        self.identity_file.write_text(
            json.dumps(identity, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    
    # =========================================================================
    # 2. ICH ERKENNE SOETWAS WIE ICH
    # =========================================================================
    
    def discover(self, path: Path) -> Optional[Dict]:
        """
        Erkennt BACH-Instanz am Pfad via Signatur-Dateien.
        
        Args:
            path: Zu prüfender Pfad
            
        Returns:
            Instanz-Info oder None
        """
        path = Path(path)
        
        # Signatur-Dateien prüfen
        for sig in SIGNATURE_FILES:
            if not (path / sig).exists():
                return None
        
        # Identity laden
        try:
            # Versuche identity.json
            other_identity_file = path / "data" / "identity.json"
            if other_identity_file.exists():
                other_identity = json.loads(other_identity_file.read_text(encoding='utf-8'))
            else:
                # Fallback: Generiere aus Pfad
                other_identity = {
                    "instance": {
                        "id": f"bach-{path.name}",
                        "name": f"BACH @ {path.name}"
                    },
                    "lineage": {"base_distribution": "BACH"},
                    "seal": {"current": {"kernel_version": "unknown", "type": "personal", "status": "active"}},
                    "dna": {"composition": {}},
                    "mutations": []
                }
            
            return {
                "path": str(path),
                "instance_id": other_identity.get("instance", {}).get("id", "unknown"),
                "instance_name": other_identity.get("instance", {}).get("name", "Unknown"),
                "distribution": other_identity.get("lineage", {}).get("base_distribution", "BACH"),
                "version": other_identity.get("seal", {}).get("current", {}).get("kernel_version"),
                "seal_type": other_identity.get("seal", {}).get("current", {}).get("type"),
                "seal_status": other_identity.get("seal", {}).get("current", {}).get("status"),
                "generation": other_identity.get("lineage", {}).get("generation", 0),
                "forked_from": other_identity.get("instance", {}).get("forked_from")
            }
        except Exception as e:
            print(f"[WARN] Fehler beim Lesen von {path}: {e}")
            return None
    
    def scan_for_instances(self, paths: List[str] = None) -> List[Dict]:
        """
        Scannt nach BACH-Instanzen in angegebenen Pfaden.
        
        Args:
            paths: Zu durchsuchende Pfade (None = Standard-Orte)
            
        Returns:
            Liste gefundener Instanzen
        """
        if paths is None:
            paths = self._get_default_scan_paths()
        
        instances = []
        my_id = self.get_identity_card().get("instance_id")
        
        for base_path in paths:
            base = Path(base_path)
            if not base.exists():
                continue
            
            # Direkt prüfen
            result = self.discover(base)
            if result and result["instance_id"] != my_id:
                result["relationship"] = self._determine_relationship(result)
                instances.append(result)
                continue
            
            # Unterordner durchsuchen (max 1 Ebene)
            try:
                for subdir in base.iterdir():
                    if subdir.is_dir():
                        result = self.discover(subdir)
                        if result and result["instance_id"] != my_id:
                            result["relationship"] = self._determine_relationship(result)
                            instances.append(result)
            except PermissionError:
                pass
        
        return instances
    
    def _get_default_scan_paths(self) -> List[str]:
        """Gibt Standard-Scan-Pfade für BACH zurück."""
        paths = []
        if sys.platform == 'win32':
            # Standard BACH-Orte auf Windows
            paths = [
                r"C:\Users\User\OneDrive\.AI",
                r"C:\DEV_local",
                r"D:\.AI",
                r"E:\.AI"
            ]
        else:
            paths = ["/home", "/mnt", "/opt/bach", "~"]
        return paths
    
    def _determine_relationship(self, other: Dict) -> str:
        """Bestimmt Beziehung zu anderer Instanz."""
        my_identity = self._load_identity()
        if not my_identity:
            return "peer"
        
        my_id = my_identity.get("instance", {}).get("id", "")
        other_id = other.get("instance_id", "")
        my_forked_from = my_identity.get("instance", {}).get("forked_from")
        other_forked_from = other.get("forked_from")
        
        # Beziehungstypen
        if other_forked_from == my_id:
            return "child"  # Andere ist Fork von mir
        elif my_forked_from == other_id:
            return "parent"  # Ich bin Fork von anderer
        elif my_forked_from and other_forked_from and my_forked_from == other_forked_from:
            return "sibling"  # Beide vom gleichen Parent
        elif other.get("seal_type") == "official":
            return "official"  # Offizielle Distribution
        else:
            return "peer"  # Gleichgestellte Instanz


    # =========================================================================
    # 3. ICH IDENTIFIZIERE DICH (Handshake) - MIGRIERT 2026-01-22
    # =========================================================================
    
    def handshake(self, other_path: Path) -> Optional[Dict]:
        """
        Führt Handshake mit anderer BACH-Instanz durch.
        Austausch der Identity-Cards.
        
        Args:
            other_path: Pfad zur anderen Instanz
            
        Returns:
            Handshake-Ergebnis oder None
        """
        # Meine Identity-Card
        my_card = self.get_identity_card()
        if "error" in my_card:
            return None
        
        # Andere Instanz erkennen
        other = self.discover(other_path)
        if not other:
            print(f"[ERROR] Keine BACH-Instanz gefunden in: {other_path}")
            return None
        
        # Handshake-Nachricht erstellen
        msg_id = f"hs-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
        handshake_msg = {
            "protocol": "handshake",
            "version": "1.0",
            "message_id": msg_id,
            "timestamp": datetime.now().isoformat(),
            "sender": my_card,
            "capabilities": {
                "can_export": LEARNABLE_COMPONENTS,
                "can_import": LEARNABLE_COMPONENTS,
                "protocols_supported": ["handshake", "compare", "request", "transfer", "receipt"]
            },
            "purpose": "discovery"
        }
        
        # In deren Inbox schreiben
        self._write_to_inbox(other_path, "handshakes", handshake_msg)
        
        # In eigene Outbox speichern
        self._write_to_outbox("handshakes", handshake_msg)
        
        # Deren vollständige Identity laden
        other_identity = self._load_other_identity(other_path)
        
        return {
            "success": True,
            "message_id": msg_id,
            "my_card": my_card,
            "their_card": other,
            "their_full_identity": other_identity,
            "relationship": self._determine_relationship(other),
            "timestamp": datetime.now().isoformat()
        }
    
    def _write_to_inbox(self, target_path: Path, category: str, message: Dict):
        """Schreibt Nachricht in Inbox der Ziel-BACH-Instanz."""
        # BACH-Pfad statt RecludOS
        target_inbox = Path(target_path) / "tools" / "partner_communication" / "inbox" / category
        target_inbox.mkdir(parents=True, exist_ok=True)
        
        filename = f"{message['message_id']}.json"
        (target_inbox / filename).write_text(
            json.dumps(message, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    
    def _write_to_outbox(self, category: str, message: Dict):
        """Schreibt Nachricht in eigene Outbox."""
        outbox = OUTBOX_DIR / category
        outbox.mkdir(parents=True, exist_ok=True)
        
        filename = f"{message['message_id']}.json"
        (outbox / filename).write_text(
            json.dumps(message, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    
    def _load_other_identity(self, other_path: Path) -> Optional[Dict]:
        """Lädt vollständige Identity einer anderen BACH-Instanz."""
        # BACH-Pfad: data/identity.json statt main/system/identity.json
        identity_file = Path(other_path) / "data" / "identity.json"
        if identity_file.exists():
            return json.loads(identity_file.read_text(encoding='utf-8'))
        return None
    
    # =========================================================================
    # 4. ICH PRÜFE WAS ICH VON DIR LERNEN KANN
    # =========================================================================
    
    def compare_with(self, other_path: Path) -> Dict:
        """
        Vergleicht mit anderer BACH-Instanz - was kann ich lernen?
        
        Args:
            other_path: Pfad zur anderen Instanz
            
        Returns:
            Vergleichsergebnis mit Empfehlungen
        """
        other_path = Path(other_path)
        other_identity = self._load_other_identity(other_path)
        my_identity = self._load_identity()
        
        if not other_identity:
            other_identity = {"instance": {"id": f"bach-{other_path.name}"}}
        if not my_identity:
            my_identity = self._load_identity_from_db() or {"instance": {"id": "bach-local"}}
        
        result = {
            "compared_with": other_identity.get("instance", {}).get("id", "unknown"),
            "timestamp": datetime.now().isoformat(),
            "learnable": [],
            "not_recommended": [],
            "incompatible": [],
            "i_could_teach": []
        }
        
        # Komponenten vergleichen
        my_versions = self._get_component_versions(self.root)
        other_versions = self._get_component_versions(other_path)
        
        for component in LEARNABLE_COMPONENTS:
            my_info = my_versions.get(component, {})
            other_info = other_versions.get(component, {})
            
            if not other_info.get("exists"):
                continue
            
            comparison = self._compare_component(component, my_info, other_info, other_path)
            
            if comparison["recommendation"] == "strong":
                result["learnable"].append(comparison)
            elif comparison["recommendation"] == "optional":
                result["learnable"].append(comparison)
            elif comparison["recommendation"] == "not_recommended":
                result["not_recommended"].append(comparison)
            elif comparison["recommendation"] == "i_am_better":
                result["i_could_teach"].append(comparison)
        
        return result
    
    def _get_component_versions(self, root: Path) -> Dict:
        """
        Ermittelt Versionen aller lernbaren Komponenten (BACH-Struktur).
        
        BACH-Pfade:
        - lessons → memory_lessons in bach.db
        - facts → memory_facts in bach.db
        - skills → skills/ Verzeichnis
        - templates → templates/ Verzeichnis (falls vorhanden)
        """
        versions = {}
        db_path = root / "data" / "bach.db"
        
        # 1. Lessons aus DB
        lessons_info = {"exists": False, "version": "1.0.0", "entries": 0, "source": "bach.db"}
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM memory_lessons")
                count = cursor.fetchone()[0]
                conn.close()
                lessons_info["exists"] = True
                lessons_info["entries"] = count
            except (sqlite3.Error, OSError):
                pass
        versions["lessons"] = lessons_info
        
        # 2. Facts aus DB
        facts_info = {"exists": False, "version": "1.0.0", "entries": 0, "source": "bach.db"}
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM memory_facts")
                count = cursor.fetchone()[0]
                conn.close()
                facts_info["exists"] = True
                facts_info["entries"] = count
            except (sqlite3.Error, OSError):
                pass
        versions["facts"] = facts_info
        
        # 3. Skills Verzeichnis
        skills_dir = root / "skills"
        skills_info = {"exists": False, "entries": 0, "source": "skills/"}
        if skills_dir.exists():
            skill_count = len(list(skills_dir.glob("**/*.md")))
            skills_info["exists"] = True
            skills_info["entries"] = skill_count
        versions["skills"] = skills_info
        
        # 4. Templates (optional)
        templates_dir = root / "templates"
        templates_info = {"exists": False, "entries": 0, "source": "templates/"}
        if templates_dir.exists():
            template_count = len(list(templates_dir.glob("**/*")))
            templates_info["exists"] = True
            templates_info["entries"] = template_count
        versions["templates"] = templates_info
        
        return versions
    
    def _compare_component(self, component: str, my_info: Dict, other_info: Dict, other_path: Path) -> Dict:
        """Vergleicht einzelne Komponente."""
        comparison = {
            "component": component,
            "my_version": my_info.get("version"),
            "my_entries": my_info.get("entries", 0),
            "their_version": other_info.get("version"),
            "their_entries": other_info.get("entries", 0),
            "recommendation": "not_recommended",
            "reason": ""
        }
        
        # Vergleichslogik
        if not my_info.get("exists") and other_info.get("exists"):
            comparison["recommendation"] = "strong"
            comparison["reason"] = "Ich habe diese Komponente nicht"
        elif other_info.get("entries", 0) > my_info.get("entries", 0) * 1.5:
            comparison["recommendation"] = "strong"
            comparison["reason"] = f"Andere hat {other_info['entries']} vs meine {my_info['entries']} Einträge"
        elif other_info.get("entries", 0) > my_info.get("entries", 0):
            comparison["recommendation"] = "optional"
            comparison["reason"] = "Andere hat mehr Einträge"
        elif my_info.get("entries", 0) > other_info.get("entries", 0):
            comparison["recommendation"] = "i_am_better"
            comparison["reason"] = "Ich habe mehr Einträge"
        else:
            comparison["recommendation"] = "not_recommended"
            comparison["reason"] = "Gleichwertig oder älter"
        
        return comparison
    
    # =========================================================================
    # 5. ICH FRAGE OB ICH VON DIR LERNEN SOLL (Approval) - MIGRIERT 2026-01-22
    # =========================================================================
    
    def request_user_approval(self, comparison_result: Dict, source_instance_id: str) -> Dict:
        """
        Erstellt Approval-Request für User.
        
        Args:
            comparison_result: Ergebnis von compare_with()
            source_instance_id: ID der Quell-Instanz
            
        Returns:
            Approval-Request
        """
        approval_id = f"apr-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
        
        approval_request = {
            "id": approval_id,
            "created": datetime.now().isoformat(),
            "status": "pending",
            "source_instance": source_instance_id,
            "learnable_components": comparison_result.get("learnable", []),
            "user_decision": None,
            "selected_components": [],
            "decided_at": None
        }
        
        # In pending_approvals speichern
        approvals = self._load_pending_approvals()
        approvals.append(approval_request)
        self._save_pending_approvals(approvals)
        
        print(f"[INFO] Approval-Request erstellt: {approval_id}")
        print(f"       {len(approval_request['learnable_components'])} Komponenten zum Lernen verfügbar")
        
        return approval_request
    
    def _load_pending_approvals(self) -> List[Dict]:
        """Lädt pending approvals."""
        if PENDING_APPROVALS_FILE.exists():
            return json.loads(PENDING_APPROVALS_FILE.read_text(encoding='utf-8'))
        return []
    
    def _save_pending_approvals(self, approvals: List[Dict]):
        """Speichert pending approvals."""
        PENDING_APPROVALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_APPROVALS_FILE.write_text(
            json.dumps(approvals, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    
    def user_approves(self, approval_id: str, selected_components: List[str]) -> Dict:
        """
        User genehmigt Import bestimmter Komponenten.
        
        Args:
            approval_id: ID des Approval-Requests
            selected_components: Welche Komponenten importieren
            
        Returns:
            Aktualisierter Approval-Request
        """
        approvals = self._load_pending_approvals()
        
        for approval in approvals:
            if approval["id"] == approval_id:
                approval["status"] = "approved"
                approval["user_decision"] = "approve"
                approval["selected_components"] = selected_components
                approval["decided_at"] = datetime.now().isoformat()
                break
        
        self._save_pending_approvals(approvals)
        return approval
    
    def user_rejects(self, approval_id: str, reason: str = "") -> Dict:
        """User lehnt Import ab."""
        approvals = self._load_pending_approvals()
        
        for approval in approvals:
            if approval["id"] == approval_id:
                approval["status"] = "rejected"
                approval["user_decision"] = "reject"
                approval["rejection_reason"] = reason
                approval["decided_at"] = datetime.now().isoformat()
                break
        
        self._save_pending_approvals(approvals)
        return approval
    
    def list_pending_approvals(self) -> List[Dict]:
        """Listet alle ausstehenden Approvals."""
        approvals = self._load_pending_approvals()
        return [a for a in approvals if a["status"] == "pending"]
    
    # =========================================================================
    # 6. ICH LERNE VON DIR (MIGRIERT 2026-01-22)
    # =========================================================================
    
    def import_from(self, other_path: Path, components: List[str], 
                    approved_by: str = "user") -> Dict:
        """
        Importiert Komponenten von anderer BACH-Instanz.
        
        Args:
            other_path: Pfad zur Quell-Instanz
            components: Welche Komponenten importieren (lessons, facts, skills, templates)
            approved_by: Wer hat genehmigt
            
        Returns:
            Import-Ergebnis
        """
        other_path = Path(other_path)
        other_identity = self._load_other_identity(other_path)
        
        if not other_identity:
            return {"success": False, "error": "Quell-Identität nicht ladbar"}
        
        source_id = other_identity.get("instance", {}).get("id", "unknown")
        source_dist = other_identity.get("lineage", {}).get("base_distribution", "unknown")
        
        result = {
            "success": True,
            "from_instance": source_id,
            "components_imported": [],
            "components_failed": [],
            "timestamp": datetime.now().isoformat()
        }
        
        # Request erstellen und in deren Inbox schreiben
        request = self._create_import_request(other_path, components, approved_by)
        self._write_to_inbox(other_path, "requests", request)
        
        # Komponenten importieren
        for component in components:
            try:
                self._import_component(other_path, component, source_id)
                result["components_imported"].append(component)
            except Exception as e:
                result["components_failed"].append({
                    "component": component, 
                    "error": str(e)
                })
        
        # Nur wenn mindestens eine Komponente erfolgreich
        if result["components_imported"]:
            # DNA aktualisieren (wenn Methode existiert)
            if hasattr(self, '_update_dna_after_import'):
                self._update_dna_after_import(other_identity, result["components_imported"])
            
            # Mutation dokumentieren (wenn Methode existiert)
            if hasattr(self, '_record_mutation'):
                self._record_mutation("import", {
                    "from_instance": source_id,
                    "from_distribution": source_dist,
                    "components": result["components_imported"],
                    "approved_by": approved_by
                })
            
            # Receipt senden (wenn Methode existiert)
            if hasattr(self, 'send_receipt'):
                self.send_receipt(other_path, result["components_imported"])
        
        return result
    
    def _create_import_request(self, target_path: Path, components: List[str], approved_by: str) -> Dict:
        """Erstellt Import-Request."""
        my_card = self.get_identity_card()
        msg_id = f"req-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
        
        return {
            "protocol": "request",
            "version": "1.0",
            "message_id": msg_id,
            "timestamp": datetime.now().isoformat(),
            "requester": {
                "instance_id": my_card.get("instance_id"),
                "approved_by": approved_by,
                "approval_timestamp": datetime.now().isoformat()
            },
            "requested_components": components,
            "transfer_format": "db_merge",  # BACH: DB-basiert
            "include_lineage": True
        }
    
    def _import_component(self, source_path: Path, component: str, source_id: str):
        """
        Importiert einzelne Komponente von anderer BACH-Instanz.
        
        BACH-Mapping:
        - lessons: memory_lessons (bach.db) → memory_lessons (bach.db)
        - facts: memory_facts (bach.db) → memory_facts (bach.db)
        - skills: skills/ Verzeichnis → skills/ Verzeichnis
        - templates: templates/ Verzeichnis → templates/ Verzeichnis
        """
        source_db = source_path / "data" / "bach.db"
        
        if component == "lessons":
            self._import_lessons_from_db(source_db, source_id)
        elif component == "facts":
            self._import_facts_from_db(source_db, source_id)
        elif component == "skills":
            self._import_skills_directory(source_path, source_id)
        elif component == "templates":
            self._import_templates_directory(source_path, source_id)
        else:
            raise ValueError(f"Unbekannte Komponente: {component}")
    
    def _import_lessons_from_db(self, source_db: Path, source_id: str):
        """Importiert Lessons aus anderer BACH-Datenbank (Merge, keine Duplikate)."""
        if not source_db.exists():
            raise FileNotFoundError(f"Quell-Datenbank nicht gefunden: {source_db}")
        
        # Quell-Lessons laden
        source_conn = sqlite3.connect(source_db)
        source_conn.row_factory = sqlite3.Row
        source_lessons = source_conn.execute("""
            SELECT category, title, content, created_at 
            FROM memory_lessons
        """).fetchall()
        source_conn.close()
        
        if not source_lessons:
            print(f"[INFO] Keine Lessons in Quell-Instanz")
            return
        
        # Ziel-Datenbank
        target_conn = sqlite3.connect(BACH_DB)
        target_conn.row_factory = sqlite3.Row
        
        # Bestehende Titel sammeln (Duplikat-Check)
        existing = {row['title'] for row in target_conn.execute(
            "SELECT title FROM memory_lessons"
        ).fetchall()}
        
        # Neue Lessons einfügen
        added = 0
        for lesson in source_lessons:
            title = lesson['title']
            if title not in existing:
                target_conn.execute("""
                    INSERT INTO memory_lessons (category, title, content, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    lesson['category'],
                    f"[imported:{source_id}] {title}",
                    lesson['content'],
                    datetime.now().isoformat()
                ))
                added += 1
        
        target_conn.commit()
        target_conn.close()
        print(f"[OK] {added} neue Lessons importiert von {source_id}")
    
    def _import_facts_from_db(self, source_db: Path, source_id: str):
        """Importiert Facts aus anderer BACH-Datenbank."""
        if not source_db.exists():
            raise FileNotFoundError(f"Quell-Datenbank nicht gefunden: {source_db}")
        
        source_conn = sqlite3.connect(source_db)
        source_conn.row_factory = sqlite3.Row
        source_facts = source_conn.execute("""
            SELECT key, value, created_at FROM memory_facts
        """).fetchall()
        source_conn.close()
        
        if not source_facts:
            print(f"[INFO] Keine Facts in Quell-Instanz")
            return
        
        target_conn = sqlite3.connect(BACH_DB)
        target_conn.row_factory = sqlite3.Row
        
        existing = {row['key'] for row in target_conn.execute(
            "SELECT key FROM memory_facts"
        ).fetchall()}
        
        added = 0
        for fact in source_facts:
            key = fact['key']
            if key not in existing:
                target_conn.execute("""
                    INSERT INTO memory_facts (key, value, created_at)
                    VALUES (?, ?, ?)
                """, (
                    f"imported:{source_id}:{key}",
                    fact['value'],
                    datetime.now().isoformat()
                ))
                added += 1
        
        target_conn.commit()
        target_conn.close()
        print(f"[OK] {added} neue Facts importiert von {source_id}")
    
    def _import_skills_directory(self, source_path: Path, source_id: str):
        """Importiert Skills-Verzeichnis (kopiert neue Skills)."""
        source_skills = source_path / "skills"
        target_skills = BACH_ROOT / "skills"
        
        if not source_skills.exists():
            raise FileNotFoundError(f"Quell-Skills nicht gefunden: {source_skills}")
        
        imported = 0
        for skill_file in source_skills.glob("**/*.md"):
            rel_path = skill_file.relative_to(source_skills)
            target_file = target_skills / rel_path
            
            if not target_file.exists():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(skill_file, target_file)
                imported += 1
        
        print(f"[OK] {imported} neue Skills importiert von {source_id}")
    
    def _import_templates_directory(self, source_path: Path, source_id: str):
        """Importiert Templates-Verzeichnis."""
        source_templates = source_path / "templates"
        target_templates = BACH_ROOT / "templates"
        
        if not source_templates.exists():
            print(f"[INFO] Keine Templates in Quell-Instanz")
            return
        
        imported = 0
        for template_file in source_templates.glob("**/*"):
            if template_file.is_file():
                rel_path = template_file.relative_to(source_templates)
                target_file = target_templates / rel_path
                
                if not target_file.exists():
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(template_file, target_file)
                    imported += 1
        
        print(f"[OK] {imported} neue Templates importiert von {source_id}")
    
    # =========================================================================
    # SEKTION 7: DU WEISST DASS ICH VON DIR GELERNT HABE
    # =========================================================================
    
    def send_receipt(self, other_path: Path, imported_components: List[str]):
        """
        Sendet Empfangsbestätigung an Quelle.
        Die Quelle weiß dann, dass wir von ihr gelernt haben.
        
        Args:
            other_path: Pfad zur Quell-Instanz
            imported_components: Was wurde importiert
        """
        my_card = self.get_identity_card()
        my_identity = self._load_identity()
        
        msg_id = f"rcp-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
        
        receipt = {
            "protocol": "receipt",
            "version": "1.0",
            "message_id": msg_id,
            "timestamp": datetime.now().isoformat(),
            "recipient": my_card.get("instance_id", "unknown"),
            "recipient_name": my_card.get("instance_name", "BACH"),
            "received_components": imported_components,
            "status": "accepted",
            "recipient_state_after": {
                "dna_composition": my_identity.get("dna", {}).get("composition", {}),
                "mutations_count": len(my_identity.get("mutations", []))
            }
        }
        
        # In deren Inbox schreiben
        self._write_to_inbox(other_path, "receipts", receipt)
        
        # In eigene Outbox speichern
        self._write_to_outbox("receipts", receipt)
        
        print(f"[OK] Receipt gesendet an: {other_path}")
    
    def process_incoming_receipts(self) -> List[Dict]:
        """
        Verarbeitet eingehende Receipts.
        Aktualisiert dna.exports[] wenn jemand von uns gelernt hat.
        
        Returns:
            Liste verarbeiteter Receipts
        """
        receipts_dir = INBOX_DIR / "receipts"
        if not receipts_dir.exists():
            return []
        
        processed = []
        identity = self._load_identity()
        
        for receipt_file in receipts_dir.glob("*.json"):
            try:
                receipt = json.loads(receipt_file.read_text(encoding='utf-8'))
                
                # Export dokumentieren
                export_record = {
                    "date": receipt["timestamp"],
                    "to_instance": receipt["recipient"],
                    "to_instance_name": receipt.get("recipient_name"),
                    "components": receipt["received_components"],
                    "receipt_id": receipt["message_id"]
                }
                
                # Prüfen ob schon dokumentiert
                if "dna" not in identity:
                    identity["dna"] = {"exports": [], "imports": [], "composition": {}}
                existing_exports = identity.get("dna", {}).get("exports", [])
                already_recorded = any(
                    e.get("receipt_id") == receipt["message_id"] 
                    for e in existing_exports
                )
                
                if not already_recorded:
                    identity["dna"]["exports"].append(export_record)
                    print(f"[INFO] {receipt['recipient']} hat {receipt['received_components']} von uns übernommen")
                
                processed.append(receipt)
                
                # Receipt in "processed" verschieben
                processed_dir = INBOX_DIR / "receipts" / "processed"
                processed_dir.mkdir(exist_ok=True)
                shutil.move(str(receipt_file), str(processed_dir / receipt_file.name))
                
            except Exception as e:
                print(f"[WARN] Fehler bei Receipt {receipt_file}: {e}")
        
        if processed:
            self._save_identity(identity)
        
        return processed
    
    # =========================================================================
    # SEKTION 8: ICH BIN ETWAS ANDERS ALS VORHER
    # =========================================================================
    
    def _record_mutation(self, mutation_type: str, details: Dict):
        """
        Dokumentiert Mutation in identity.json.
        Jede signifikante Änderung wird festgehalten.
        
        Args:
            mutation_type: Art der Mutation (import, evolution, fork, upgrade, etc.)
            details: Details zur Mutation
        """
        identity = self._load_identity()
        
        if "mutations" not in identity:
            identity["mutations"] = []
        
        mutation_id = f"mut-{len(identity.get('mutations', [])) + 1:03d}"
        
        mutation = {
            "id": mutation_id,
            "type": mutation_type,
            "date": datetime.now().isoformat(),
            **details
        }
        
        identity["mutations"].append(mutation)
        
        # Seal-Chain aktualisieren (falls vorhanden)
        if "seal" in identity:
            current_seal = identity.get("seal", {}).get("current", {})
            new_chain_entry = {
                "type": current_seal.get("type", "personal"),
                "distribution": current_seal.get("distribution", "BACH"),
                "version": f"{current_seal.get('kernel_version', '1.1')}-mut.{len(identity['mutations'])}",
                "hash": self._calculate_simple_hash(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "action": mutation_type,
                "details": details.get("components", []) if isinstance(details.get("components"), list) else []
            }
            
            if "chain" not in identity["seal"]:
                identity["seal"]["chain"] = []
            identity["seal"]["chain"].append(new_chain_entry)
        
        self._save_identity(identity)
        print(f"[OK] Mutation dokumentiert: {mutation_id} ({mutation_type})")
    
    def _calculate_simple_hash(self) -> str:
        """Berechnet einfachen Hash für Seal-Chain."""
        identity = self._load_identity()
        content = json.dumps(identity.get("mutations", []), sort_keys=True)
        return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"
    
    def _update_dna_after_import(self, source_identity: Dict, components: List[str]):
        """
        Aktualisiert DNA-Composition nach Import.
        
        Args:
            source_identity: Identity der Quell-Instanz
            components: Importierte Komponenten
        """
        identity = self._load_identity()
        
        # Sicherstellen dass DNA-Struktur existiert
        if "dna" not in identity:
            identity["dna"] = {"composition": {}, "imports": [], "exports": []}
        
        source_id = source_identity.get("instance", {}).get("id", "unknown")
        source_dist = source_identity.get("lineage", {}).get("base_distribution", "unknown")
        
        # Import dokumentieren
        import_record = {
            "date": datetime.now().isoformat(),
            "from_instance": source_id,
            "from_distribution": source_dist,
            "components": components
        }
        identity["dna"]["imports"].append(import_record)
        
        # Composition aktualisieren
        if source_dist not in identity["dna"]["composition"]:
            identity["dna"]["composition"][source_dist] = {
                "percentage": 0,
                "components": []
            }
        
        # Komponenten hinzufügen (keine Duplikate)
        existing_components = set(identity["dna"]["composition"][source_dist]["components"])
        for comp in components:
            if comp not in existing_components:
                identity["dna"]["composition"][source_dist]["components"].append(comp)
        
        # Prozentanteile neu berechnen
        self._recalculate_dna_percentages(identity)
        
        self._save_identity(identity)
    
    def _recalculate_dna_percentages(self, identity: Dict):
        """
        Berechnet DNA-Prozentanteile basierend auf Komponenten.
        Vereinfachte Logik: Jede Komponente = 5%, Rest = self_developed/base
        """
        composition = identity.get("dna", {}).get("composition", {})
        if not composition:
            return
        
        # Alle Komponenten zählen (außer self_developed)
        total_imported_components = 0
        for source, info in composition.items():
            if source not in ["self_developed", "self_evolved"]:
                total_imported_components += len(info.get("components", []))
        
        # Prozent berechnen (max 5% pro Komponente, max 50% fremd)
        imported_percent = min(total_imported_components * 5, 50)
        self_percent = 100 - imported_percent
        
        # Self-Anteil setzen
        if "self_developed" in composition:
            composition["self_developed"]["percentage"] = self_percent
        elif "self_evolved" in composition:
            composition["self_evolved"]["percentage"] = self_percent
        else:
            # Basis-Distribution hat den Rest
            for source, info in composition.items():
                if source not in ["self_developed", "self_evolved"] and info.get("components"):
                    if "kernel" in info["components"] or "core" in info["components"]:
                        info["percentage"] = self_percent
                        break
        
        # Importierte Anteile verteilen
        if total_imported_components > 0:
            per_component = imported_percent / total_imported_components
            for source, info in composition.items():
                if source not in ["self_developed", "self_evolved"]:
                    comp_count = len(info.get("components", []))
                    if "kernel" not in info.get("components", []) and "core" not in info.get("components", []):
                        info["percentage"] = round(comp_count * per_component, 1)
    
    # =========================================================================
    # HILFSFUNKTIONEN
    # =========================================================================
    
    def get_dna_summary(self) -> Dict:
        """Gibt DNA-Zusammenfassung zurück."""
        identity = self._load_identity()
        if not identity:
            return {}
        
        return {
            "composition": identity.get("dna", {}).get("composition", {}),
            "total_imports": len(identity.get("dna", {}).get("imports", [])),
            "total_exports": len(identity.get("dna", {}).get("exports", [])),
            "mutations_count": len(identity.get("mutations", []))
        }
    
    def get_lineage(self) -> Dict:
        """Gibt Abstammungsinformationen zurück."""
        identity = self._load_identity()
        if not identity:
            return {}
        
        return {
            "lineage": identity.get("lineage", {}),
            "seal_chain": identity.get("seal", {}).get("chain", []),
            "mutations": identity.get("mutations", [])
        }
    
    def get_full_status(self) -> Dict:
        """Gibt vollständigen Status zurück."""
        identity = self._load_identity()
        pending = self.list_pending_approvals() if hasattr(self, 'list_pending_approvals') else []
        
        return {
            "identity_card": self.get_identity_card(),
            "dna_summary": self.get_dna_summary(),
            "pending_approvals": len(pending),
            "inbox_counts": self._count_inbox_messages(),
            "last_mutation": identity.get("mutations", [{}])[-1] if identity.get("mutations") else None
        }
    
    def _count_inbox_messages(self) -> Dict:
        """Zählt Nachrichten in Inbox."""
        counts = {}
        for category in ["handshakes", "requests", "transfers", "receipts"]:
            cat_dir = INBOX_DIR / category
            if cat_dir.exists():
                counts[category] = len(list(cat_dir.glob("*.json")))
            else:
                counts[category] = 0
        return counts


# =============================================================================
# STUB CLI (minimal für Tests)
# =============================================================================

def print_help():
    """Zeigt Hilfe an."""
    print("""
BACH Interaction Protocol v1.0.0 (COMPLETE MIGRATION)
======================================================

VERFÜGBARE BEFEHLE:

  Status & Info
  -------------
  status              Zeigt vollständigen Status
  identity            Zeigt eigene Identity-Card
  dna                 Zeigt DNA-Zusammenfassung
  lineage             Zeigt Abstammungsinformationen
  inbox               Zeigt Inbox-Status

  Discovery
  ---------
  scan                Scannt nach anderen BACH-Instanzen
  discover <pfad>     Prüft ob Pfad eine BACH-Instanz ist

  Interaktion
  -----------
  handshake <pfad>    Führt Handshake mit anderer BACH-Instanz durch
  compare <pfad>      Vergleicht: Was kann ich von dir lernen?
  
  Import/Export
  -------------
  import <pfad> <komponenten>   Importiert Komponenten (komma-separiert)
  approvals                     Zeigt ausstehende Approvals
  process-receipts              Verarbeitet eingehende Receipts

BEISPIELE:

  python interaction_protocol.py status
  python interaction_protocol.py scan
  python interaction_protocol.py discover C:\\other-bach
  python interaction_protocol.py handshake C:\\other-bach
  python interaction_protocol.py compare C:\\other-bach
  python interaction_protocol.py import C:\\other-bach lessons,facts
""")


def main():
    """CLI Entry Point - Vollständige Version."""
    if len(sys.argv) < 2:
        print_help()
        return
    
    cmd = sys.argv[1].lower()
    protocol = InteractionProtocol()
    
    # === Status & Info ===
    if cmd == "status":
        status = protocol.get_full_status()
        print("\n=== BACH Interaction Status ===\n")
        card = status["identity_card"]
        print(f"Instance: {card.get('instance_id')}")
        print(f"Name: {card.get('instance_name')}")
        print(f"Distribution: {card.get('distribution')} v{card.get('distribution_version')}")
        print(f"Seal: {card.get('seal_type')} ({card.get('seal_status')})")
        print(f"Generation: {card.get('generation')}")
        print(f"\nDNA Composition:")
        for source, info in status["dna_summary"].get("composition", {}).items():
            pct = info.get("percentage", 0)
            comps = info.get("components", [])
            print(f"  {source}: {pct}% ({', '.join(comps) if comps else 'base'})")
        print(f"\nImports: {status['dna_summary'].get('total_imports', 0)}")
        print(f"Exports: {status['dna_summary'].get('total_exports', 0)}")
        print(f"Mutations: {status['dna_summary'].get('mutations_count', 0)}")
        print(f"Pending Approvals: {status['pending_approvals']}")
        print(f"\nInbox: {status['inbox_counts']}")
    
    elif cmd == "identity":
        card = protocol.get_identity_card()
        print(json.dumps(card, indent=2, ensure_ascii=False))
    
    elif cmd == "dna":
        dna = protocol.get_dna_summary()
        print("\n=== DNA Summary ===\n")
        print(json.dumps(dna, indent=2, ensure_ascii=False))
    
    elif cmd == "lineage":
        lineage = protocol.get_lineage()
        print("\n=== Lineage ===\n")
        print(json.dumps(lineage, indent=2, ensure_ascii=False))
    
    elif cmd == "inbox":
        counts = protocol._count_inbox_messages()
        print("\n=== Inbox Status ===\n")
        for cat, count in counts.items():
            print(f"  {cat}: {count}")
    
    # === Discovery ===
    elif cmd == "scan":
        print("\n=== Scanning for BACH instances ===\n")
        instances = protocol.scan_for_instances()
        if instances:
            for inst in instances:
                print(f"Found: {inst['instance_id']}")
                print(f"  Path: {inst['path']}")
                print(f"  Distribution: {inst['distribution']}")
                print(f"  Relationship: {inst['relationship']}")
                print()
        else:
            print("Keine anderen BACH-Instanzen gefunden.")
    
    elif cmd == "discover":
        if len(sys.argv) < 3:
            print("Verwendung: discover <pfad>")
            return
        path = sys.argv[2]
        result = protocol.discover(Path(path))
        if result:
            print(f"\n✅ BACH-Instanz gefunden!\n")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"\n❌ Keine BACH-Instanz in: {path}")
    
    # === Interaktion ===
    elif cmd == "handshake":
        if len(sys.argv) < 3:
            print("Verwendung: handshake <pfad>")
            return
        path = sys.argv[2]
        result = protocol.handshake(Path(path))
        if result and result.get("success"):
            print(f"\n✅ Handshake erfolgreich!\n")
            print(f"Message-ID: {result['message_id']}")
            print(f"Beziehung: {result['relationship']}")
            print(f"\nIhre Identity:")
            print(json.dumps(result['their_card'], indent=2, ensure_ascii=False))
        else:
            print(f"\n❌ Handshake fehlgeschlagen mit: {path}")
    
    elif cmd == "compare":
        if len(sys.argv) < 3:
            print("Verwendung: compare <pfad>")
            return
        path = sys.argv[2]
        result = protocol.compare_with(Path(path))
        if "error" in result:
            print(f"\n❌ Vergleich fehlgeschlagen: {result['error']}")
        else:
            print(f"\n=== Vergleich mit {result['compared_with']} ===\n")
            if result['learnable']:
                print("📚 LERNBAR (empfohlen):")
                for comp in result['learnable']:
                    print(f"  • {comp['component']}: {comp['reason']}")
                    print(f"    Meine: {comp['my_entries']} | Ihre: {comp['their_entries']}")
                print()
            if result['i_could_teach']:
                print("🎓 ICH KÖNNTE LEHREN:")
                for comp in result['i_could_teach']:
                    print(f"  • {comp['component']}: {comp['reason']}")
                print()
            if result['not_recommended']:
                print("⏸️ NICHT EMPFOHLEN:")
                for comp in result['not_recommended']:
                    print(f"  • {comp['component']}: {comp['reason']}")
    
    # === Import/Export ===
    elif cmd == "import":
        if len(sys.argv) < 4:
            print("Verwendung: import <pfad> <komponenten>")
            print("  komponenten: Komma-separiert, z.B. lessons,facts,skills")
            return
        path = sys.argv[2]
        components = [c.strip() for c in sys.argv[3].split(",")]
        result = protocol.import_from(Path(path), components, approved_by="cli-user")
        print(f"\n=== Import Result ===\n")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif cmd == "approvals":
        if hasattr(protocol, 'list_pending_approvals'):
            approvals = protocol.list_pending_approvals()
            print(f"\n=== Pending Approvals ({len(approvals)}) ===\n")
            for a in approvals:
                print(json.dumps(a, indent=2, ensure_ascii=False))
        else:
            print("[INFO] list_pending_approvals nicht implementiert")
    
    elif cmd == "process-receipts":
        processed = protocol.process_incoming_receipts()
        print(f"\n=== Receipts verarbeitet: {len(processed)} ===\n")
        for r in processed:
            print(f"  - {r.get('recipient')}: {r.get('received_components')}")
    
    elif cmd == "help":
        print_help()
    
    else:
        print(f"[!] Unbekannter Befehl: {cmd}")
        print("    Verfügbar: status, identity, dna, lineage, inbox, scan, discover,")
        print("               handshake, compare, import, approvals, process-receipts")
        print("    -> help für Details")


if __name__ == "__main__":
    main()
