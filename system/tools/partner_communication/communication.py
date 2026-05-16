#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Communication Executor v1.1.0

Automatisches Kommunikations-Routing und Partner-Management.
Implementiert Auto-Detection, Health-Checks und Message-Dispatching.

Portiert von: RecludOS Communication Executor v1.0.0

Features:
- Partner-Erkennung basierend auf Input-Patterns
- Health-Checks für alle aktiven Partner
- Message-Routing zu korrektem Kanal
- Logging aller Kommunikation

Usage:
  python communication.py detect "search for genes"
  python communication.py health
  python communication.py route --partner ollama --message "Draft email"
  python communication.py status
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import argparse
import urllib.request
import urllib.error

# Windows Console UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# ============================================================================
# BACH-PFADE (angepasst von RecludOS)
# ============================================================================
SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parent.parent  # tools/partner_communication -> BACH
DATA_DIR = BACH_ROOT / "data"
DB_PATH = DATA_DIR / "bach.db"
LOGS_DIR = BACH_ROOT / "logs"
MESSAGES_DIR = BACH_ROOT / "messages"  # Ersetzt RecludOS MessageBox


class PartnerStatus(Enum):
    """Partner-Verfügbarkeitsstatus"""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class PartnerInfo:
    """Partner-Informationen"""
    id: str
    name: str
    type: str
    category: str
    status: PartnerStatus
    priority: str
    channels: List[str]
    health_endpoint: Optional[str] = None
    last_check: Optional[str] = None
    response_time_ms: Optional[int] = None


@dataclass
class DetectionResult:
    """Ergebnis der Partner-Erkennung"""
    detected_partner: str
    confidence: float
    matched_patterns: List[str]
    alternative_partners: List[str]
    reasoning: str


@dataclass 
class RouteResult:
    """Ergebnis des Message-Routings"""
    success: bool
    partner: str
    channel: str
    message_id: Optional[str] = None
    response: Optional[str] = None
    error: Optional[str] = None


class CommunicationExecutor:
    """Zentraler Kommunikations-Executor für BACH"""
    
    VERSION = "1.1.0"
    
    # Recognition Patterns pro Partner
    RECOGNITION_PATTERNS = {
        "user": {
            "keywords": [],
            "patterns": [r"MessageBox", r"outbox.*\.txt", r"messages/"],
            "priority": 100
        },
        "ollama": {
            "keywords": ["bulk", "embedding", "token-free", "draft email", "ollama", 
                        "local ai", "generate text", "batch process"],
            "patterns": [r"queue.*ollama", r"localhost:11434"],
            "priority": 80
        },
        "pubmed": {
            "keywords": ["gene", "protein", "disease", "clinical", "biomedical",
                        "pubmed", "medical research", "scientific paper", "mutation",
                        "therapy", "drug", "patient", "diagnosis", "symptoms"],
            "patterns": [r"PMID:\d+", r"doi:10\.\d+"],
            "priority": 70
        },
        "google_drive": {
            "keywords": ["google drive", "find document", "search drive", "my files",
                        "shared document", "drive folder"],
            "patterns": [r"docs\.google\.com", r"drive\.google\.com"],
            "priority": 60
        },
        "canva": {
            "keywords": ["design", "presentation", "poster", "canva", "infographic",
                        "social media post", "flyer", "logo"],
            "patterns": [r"canva\.com"],
            "priority": 50
        },
        "gemini": {
            "keywords": ["gemini", "deep research", "long document", "concept analysis",
                        "google ai", "40+ pages"],
            "patterns": [],
            "priority": 40
        },
        "gpt": {
            "keywords": ["openai", "gpt", "chatgpt"],
            "patterns": [],
            "priority": 30
        }
    }
    
    # Health-Check Konfiguration
    HEALTH_CHECKS = {
        "ollama": {
            "type": "http",
            "url": "http:/localhost:11434/api/tags",
            "timeout": 5,
            "success_codes": [200]
        },
        "pubmed": {
            "type": "mcp",
            "server": "pubmed.mcp.claude.com",
            "check": "connection_test"
        },
        "google_drive": {
            "type": "api",
            "check": "token_valid"
        },
        "canva": {
            "type": "mcp",
            "server": "mcp.canva.com",
            "check": "connection_test"
        }
    }
    
    def __init__(self):
        self.partners: Dict[str, PartnerInfo] = {}
        self.master_registry: Dict = {}
        self._load_registries()
        LOGS_DIR.mkdir(exist_ok=True)
    
    def _load_registries(self):
        """Lädt Partner-Registry aus BACH-Datenbank oder JSON"""
        # Versuche zuerst partner_registry.json
        registry_path = DATA_DIR / "partners" / "partner_registry.json"
        
        if registry_path.exists():
            with open(registry_path, 'r', encoding='utf-8') as f:
                self.master_registry = json.load(f)
            
            # Partner-Infos extrahieren
            for partner_id, data in self.master_registry.get("partners", {}).items():
                self.partners[partner_id] = PartnerInfo(
                    id=data.get("id", partner_id),
                    name=data.get("name", partner_id),
                    type=data.get("type", "unknown"),
                    category=data.get("category", "unknown"),
                    status=PartnerStatus.UNKNOWN,
                    priority=data.get("priority", "low"),
                    channels=data.get("communication_channels", [])
                )
        else:
            # Fallback: lokale Registry
            local_registry = SCRIPT_DIR / "master_communication_registry.json"
            if local_registry.exists():
                with open(local_registry, 'r', encoding='utf-8') as f:
                    self.master_registry = json.load(f)
                
                for partner_id, data in self.master_registry.get("partners", {}).items():
                    self.partners[partner_id] = PartnerInfo(
                        id=data.get("id", partner_id),
                        name=data.get("name", partner_id),
                        type=data.get("type", "unknown"),
                        category=data.get("category", "unknown"),
                        status=PartnerStatus.UNKNOWN,
                        priority=data.get("priority", "low"),
                        channels=data.get("communication_channels", [])
                    )
    
    # ========== PARTNER DETECTION ==========
    
    def detect_partner(self, input_text: str) -> DetectionResult:
        """
        Erkennt den optimalen Partner für einen Input.
        
        Args:
            input_text: User-Input oder Task-Beschreibung
            
        Returns:
            DetectionResult mit erkanntem Partner und Confidence
        """
        input_lower = input_text.lower()
        scores: Dict[str, Tuple[float, List[str]]] = {}
        
        for partner, config in self.RECOGNITION_PATTERNS.items():
            score = 0.0
            matched = []
            
            # Keyword-Matching
            keywords = config.get("keywords", [])
            for kw in keywords:
                if kw.lower() in input_lower:
                    score += 10.0
                    matched.append(f"keyword:{kw}")
            
            # Pattern-Matching
            patterns = config.get("patterns", [])
            for pattern in patterns:
                if re.search(pattern, input_text, re.IGNORECASE):
                    score += 15.0
                    matched.append(f"pattern:{pattern}")
            
            # Priority-Bonus
            priority_bonus = config.get("priority", 0) / 100.0
            score += priority_bonus
            
            if score > 0:
                scores[partner] = (score, matched)
        
        # Sortiere nach Score
        sorted_partners = sorted(scores.items(), key=lambda x: x[1][0], reverse=True)
        
        if not sorted_partners:
            return DetectionResult(
                detected_partner="claude",
                confidence=1.0,
                matched_patterns=[],
                alternative_partners=[],
                reasoning="Kein spezifischer Partner erkannt - Claude ist Standard"
            )
        
        best_partner, (best_score, best_matches) = sorted_partners[0]
        max_possible = len(self.RECOGNITION_PATTERNS[best_partner].get("keywords", [])) * 10
        max_possible += len(self.RECOGNITION_PATTERNS[best_partner].get("patterns", [])) * 15
        max_possible = max(max_possible, 1)
        
        confidence = min(best_score / max_possible, 1.0)
        
        alternatives = [p for p, _ in sorted_partners[1:4]]
        
        return DetectionResult(
            detected_partner=best_partner,
            confidence=round(confidence, 2),
            matched_patterns=best_matches,
            alternative_partners=alternatives,
            reasoning=f"Score {best_score:.1f} basierend auf {len(best_matches)} Matches"
        )
    
    # ========== HEALTH CHECKS ==========
    
    def check_partner_health(self, partner_id: str) -> Tuple[PartnerStatus, Optional[int]]:
        """
        Prüft die Verfügbarkeit eines Partners.
        
        Returns:
            Tuple aus (Status, Response-Zeit in ms)
        """
        if partner_id not in self.HEALTH_CHECKS:
            return PartnerStatus.UNKNOWN, None
        
        config = self.HEALTH_CHECKS[partner_id]
        check_type = config.get("type")
        
        try:
            if check_type == "http":
                return self._check_http(config)
            elif check_type == "mcp":
                return self._check_mcp(config)
            elif check_type == "api":
                return self._check_api(config)
            else:
                return PartnerStatus.UNKNOWN, None
        except Exception as e:
            self._log(f"Health-Check Fehler für {partner_id}: {e}")
            return PartnerStatus.OFFLINE, None
    
    def _check_http(self, config: Dict) -> Tuple[PartnerStatus, Optional[int]]:
        """HTTP Health-Check"""
        url = config.get("url")
        timeout = config.get("timeout", 5)
        success_codes = config.get("success_codes", [200])
        
        start = datetime.now()
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                elapsed = int((datetime.now() - start).total_seconds() * 1000)
                
                if response.status in success_codes:
                    return PartnerStatus.ONLINE, elapsed
                else:
                    return PartnerStatus.DEGRADED, elapsed
        except urllib.error.URLError:
            return PartnerStatus.OFFLINE, None
        except Exception:
            return PartnerStatus.OFFLINE, None
    
    def _check_mcp(self, config: Dict) -> Tuple[PartnerStatus, Optional[int]]:
        """MCP Server Check (simplified - prüft nur ob konfiguriert)"""
        server = config.get("server")
        if server:
            # MCP-Server sind über Claude verfügbar, daher ONLINE wenn konfiguriert
            return PartnerStatus.ONLINE, None
        return PartnerStatus.UNKNOWN, None
    
    def _check_api(self, config: Dict) -> Tuple[PartnerStatus, Optional[int]]:
        """API Check (simplified)"""
        # API-Verfügbarkeit kann ohne Credentials nicht geprüft werden
        return PartnerStatus.UNKNOWN, None
    
    def check_all_health(self) -> Dict[str, Dict]:
        """Prüft alle Partner und gibt Status-Report zurück"""
        results = {}
        
        for partner_id in self.partners:
            status, response_time = self.check_partner_health(partner_id)
            
            results[partner_id] = {
                "name": self.partners[partner_id].name,
                "status": status.value,
                "response_time_ms": response_time,
                "checked_at": datetime.now().isoformat()
            }
            
            # Update Partner-Info
            self.partners[partner_id].status = status
            self.partners[partner_id].response_time_ms = response_time
            self.partners[partner_id].last_check = datetime.now().isoformat()
        
        return results
    
    # ========== MESSAGE ROUTING ==========
    
    def route_message(self, partner_id: str, message: str, 
                      channel: Optional[str] = None) -> RouteResult:
        """
        Routet eine Nachricht zum angegebenen Partner.
        
        Args:
            partner_id: Ziel-Partner
            message: Nachricht/Task
            channel: Optional spezifischer Kanal
            
        Returns:
            RouteResult mit Status
        """
        if partner_id not in self.partners:
            return RouteResult(
                success=False,
                partner=partner_id,
                channel="none",
                error=f"Partner '{partner_id}' nicht gefunden"
            )
        
        partner = self.partners[partner_id]
        
        # Kanal auswählen
        if channel:
            selected_channel = channel
        elif partner.channels:
            selected_channel = partner.channels[0] if isinstance(partner.channels[0], str) else partner.channels[0].get("name", "default")
        else:
            selected_channel = "default"
        
        # Routing basierend auf Partner
        try:
            if partner_id == "ollama":
                return self._route_to_ollama(message, selected_channel)
            elif partner_id == "user":
                return self._route_to_user(message)
            elif partner_id in ["pubmed", "canva", "google_drive"]:
                return self._route_to_mcp(partner_id, message)
            elif partner_id in ["gemini", "gpt"]:
                return self._route_to_external_ai(partner_id, message)
            else:
                return RouteResult(
                    success=False,
                    partner=partner_id,
                    channel=selected_channel,
                    error=f"Kein Routing für Partner '{partner_id}' implementiert"
                )
        except Exception as e:
            return RouteResult(
                success=False,
                partner=partner_id,
                channel=selected_channel,
                error=str(e)
            )
    
    def _route_to_ollama(self, message: str, channel: str) -> RouteResult:
        """Routing zu Ollama (Queue oder Direct API)"""
        if "queue" in channel.lower():
            # Queue-basiertes Routing - BACH-Pfad
            queue_dir = BACH_ROOT / "user" / "ollama" / "queue" / "pending"
            queue_dir.mkdir(parents=True, exist_ok=True)
            
            job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            job_file = queue_dir / f"job_{job_id}.json"
            
            job = {
                "id": job_id,
                "created": datetime.now().isoformat(),
                "task": message,
                "model": "mistral:7b",
                "status": "pending"
            }
            
            with open(job_file, 'w', encoding='utf-8') as f:
                json.dump(job, f, indent=2, ensure_ascii=False)
            
            self._log(f"Ollama Queue Job erstellt: {job_id}")
            
            return RouteResult(
                success=True,
                partner="ollama",
                channel="queue",
                message_id=job_id,
                response=f"Job {job_id} in Queue eingereiht"
            )
        else:
            # Direct API (nur Info, nicht wirklich aufrufen)
            return RouteResult(
                success=True,
                partner="ollama",
                channel="direct_api",
                response="Direct API Call vorbereitet - Ausführung durch externen Prozess"
            )
    
    def _route_to_user(self, message: str) -> RouteResult:
        """Routing zum User (BACH messages/)"""
        inbox_dir = MESSAGES_DIR / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        
        msg_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        msg_file = inbox_dir / f"msg_{msg_id}.txt"
        
        msg_file.write_text(message, encoding='utf-8')
        
        self._log(f"Nachricht an User: {msg_id}")
        
        return RouteResult(
            success=True,
            partner="user",
            channel="messages",
            message_id=msg_id,
            response=f"Nachricht in messages/inbox abgelegt"
        )
    
    def _route_to_mcp(self, partner_id: str, message: str) -> RouteResult:
        """Routing zu MCP-Servern (PubMed, Canva, Google Drive)"""
        # MCP-Server werden direkt von Claude aufgerufen
        return RouteResult(
            success=True,
            partner=partner_id,
            channel="mcp",
            response=f"MCP-Aufruf für {partner_id} vorbereitet - Ausführung durch Claude"
        )
    
    def _route_to_external_ai(self, partner_id: str, message: str) -> RouteResult:
        """Routing zu externen AIs (Gemini, GPT)"""
        if partner_id == "gemini":
            # Gemini via BACH partner-Ordner
            delegation_dir = BACH_ROOT / "user" / "partners" / "gemini" / "inbox"
            delegation_dir.mkdir(parents=True, exist_ok=True)
            
            task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            task_file = delegation_dir / f"task_{task_id}.md"
            
            task_content = f"""# Delegation Task {task_id}

**Created:** {datetime.now().isoformat()}
**Target:** Gemini

## Task

{message}

## Instructions

Bitte bearbeite diese Aufgabe und speichere das Ergebnis im outbox-Ordner.
"""
            task_file.write_text(task_content, encoding='utf-8')
            
            self._log(f"Gemini Delegation erstellt: {task_id}")
            
            return RouteResult(
                success=True,
                partner="gemini",
                channel="file_delegation",
                message_id=task_id,
                response=f"Delegation-Task {task_id} erstellt"
            )
        else:
            return RouteResult(
                success=False,
                partner=partner_id,
                channel="none",
                error=f"Routing für {partner_id} nicht implementiert"
            )
    
    # ========== STATUS & LOGGING ==========
    
    def get_status(self) -> Dict:
        """Gibt aktuellen System-Status zurück"""
        health = self.check_all_health()
        
        online = sum(1 for p in health.values() if p["status"] == "online")
        offline = sum(1 for p in health.values() if p["status"] == "offline")
        unknown = sum(1 for p in health.values() if p["status"] == "unknown")
        
        return {
            "version": self.VERSION,
            "timestamp": datetime.now().isoformat(),
            "partners": {
                "total": len(self.partners),
                "online": online,
                "offline": offline,
                "unknown": unknown
            },
            "health": health,
            "recognition_patterns": len(self.RECOGNITION_PATTERNS)
        }
    
    def _log(self, message: str, level: str = "INFO"):
        """Loggt Nachricht"""
        log_file = LOGS_DIR / "communication_log.txt"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_line = f"[{timestamp}] [{level}] {message}\n"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)


def main():
    parser = argparse.ArgumentParser(description="BACH Communication Executor")
    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")
    
    # Detect
    detect_parser = subparsers.add_parser("detect", help="Partner für Input erkennen")
    detect_parser.add_argument("input", help="Input-Text zur Analyse")
    
    # Health
    subparsers.add_parser("health", help="Health-Check aller Partner")
    
    # Route
    route_parser = subparsers.add_parser("route", help="Nachricht routen")
    route_parser.add_argument("--partner", "-p", required=True, help="Ziel-Partner")
    route_parser.add_argument("--message", "-m", required=True, help="Nachricht")
    route_parser.add_argument("--channel", "-c", help="Spezifischer Kanal")
    
    # Status
    subparsers.add_parser("status", help="System-Status anzeigen")
    
    # Test
    subparsers.add_parser("test", help="Selbsttest durchführen")
    
    args = parser.parse_args()
    executor = CommunicationExecutor()
    
    # === DETECT ===
    if args.command == "detect":
        result = executor.detect_partner(args.input)
        
        print(f"\n{'='*60}")
        print(f"  PARTNER-ERKENNUNG")
        print(f"{'='*60}")
        print(f"  Input: \"{args.input[:50]}{'...' if len(args.input) > 50 else ''}\"")
        print(f"\n  Erkannter Partner: {result.detected_partner.upper()}")
        print(f"  Confidence: {result.confidence:.0%}")
        print(f"  Reasoning: {result.reasoning}")
        
        if result.matched_patterns:
            print(f"\n  Matches:")
            for m in result.matched_patterns[:5]:
                print(f"    • {m}")
        
        if result.alternative_partners:
            print(f"\n  Alternativen: {', '.join(result.alternative_partners)}")
    
    # === HEALTH ===
    elif args.command == "health":
        print(f"\n{'='*60}")
        print(f"  PARTNER HEALTH-CHECKS")
        print(f"{'='*60}\n")
        
        results = executor.check_all_health()
        
        for partner_id, data in results.items():
            status = data["status"]
            emoji = "✅" if status == "online" else ("⚠️" if status == "degraded" else ("❌" if status == "offline" else "❔"))
            time_str = f" ({data['response_time_ms']}ms)" if data['response_time_ms'] else ""
            
            print(f"  {emoji} {data['name']:<25} {status.upper()}{time_str}")
    
    # === ROUTE ===
    elif args.command == "route":
        result = executor.route_message(
            args.partner,
            args.message,
            args.channel
        )
        
        if result.success:
            print(f"\n✅ Nachricht geroutet")
            print(f"   Partner: {result.partner}")
            print(f"   Kanal: {result.channel}")
            if result.message_id:
                print(f"   Message-ID: {result.message_id}")
            if result.response:
                print(f"   Response: {result.response}")
        else:
            print(f"\n❌ Routing fehlgeschlagen")
            print(f"   Error: {result.error}")
    
    # === STATUS ===
    elif args.command == "status":
        status = executor.get_status()
        
        print(f"\n{'='*60}")
        print(f"  BACH COMMUNICATION EXECUTOR v{status['version']}")
        print(f"{'='*60}")
        print(f"\n  Partner:")
        print(f"    Total:   {status['partners']['total']}")
        print(f"    Online:  {status['partners']['online']}")
        print(f"    Offline: {status['partners']['offline']}")
        print(f"    Unknown: {status['partners']['unknown']}")
        print(f"\n  Recognition Patterns: {status['recognition_patterns']}")
        print(f"  Timestamp: {status['timestamp']}")
    
    # === TEST ===
    elif args.command == "test":
        print(f"\n{'='*60}")
        print(f"  SELBSTTEST")
        print(f"{'='*60}\n")
        
        # Test 1: Partner-Erkennung
        test_inputs = [
            "Search for BRCA1 gene mutations",
            "Draft 10 emails for customers",
            "Create a presentation about AI",
            "Find my budget document in Drive"
        ]
        
        print("  1. Partner-Erkennung:")
        for inp in test_inputs:
            result = executor.detect_partner(inp)
            print(f"     \"{inp[:35]}...\" → {result.detected_partner} ({result.confidence:.0%})")
        
        # Test 2: Health-Checks
        print(f"\n  2. Health-Checks:")
        health = executor.check_all_health()
        online = sum(1 for p in health.values() if p["status"] == "online")
        print(f"     {online}/{len(health)} Partner online")
        
        print(f"\n✅ Selbsttest abgeschlossen")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
