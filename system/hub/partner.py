# SPDX-License-Identifier: MIT
"""
Partner Handler - Partner-Verwaltung
====================================

--partner list            Alle Partner auflisten
--partner status          Status aller Partner
--partner info <n>        Partner-Details
--partner active          Nur aktive Partner
--partner delegate <task> Task an Partner delegieren (Token + Complexity-aware)
    --to=NAME             Spezifischer Partner
    --zone=N              Zone erzwingen (1-4)
    --fallback-local, --fal  Bei Offline-Status auf lokale AI (Ollama) ausweichen
    --score               Zeige Komplexitäts-Score an
"""
import json
import sys
from pathlib import Path
from .base import BaseHandler

# Complexity Scorer Import
sys.path.insert(0, str(Path(__file__).parent / "_services" / "delegation"))
try:
    from complexity_scorer import get_scorer
    HAS_COMPLEXITY_SCORER = True
except ImportError:
    HAS_COMPLEXITY_SCORER = False

# clutch-bridge Imports (Tasks [1075]-[1079])
try:
    from strecken_analyse import get_analyser as get_strecken_analyser
    from gas_bremse import get_gas_bremse, berechne_gas
    from bordcomputer import get_bordcomputer
    from fahrschule import get_fahrschule
    from fahrtenbuch import get_fahrtenbuch
    HAS_CLUTCH_BRIDGE = True
except ImportError:
    HAS_CLUTCH_BRIDGE = False


class PartnerHandler(BaseHandler):
    """Handler fuer --partner Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        super().__init__(base_path)
        # self.registry_path entfernt (Task #302)
        self.db_path = self._canonical_db
    
    def _load_partners_from_db(self) -> dict:
        """Laedt Partner aus der partner_recognition DB-Tabelle.
        
        Returns:
            dict im gleichen Format wie partner_registry.json:
            {
                "partners": [...],
                "delegation_zones": {...}
            }
        """
        import sqlite3
        import json as json_lib
        
        result = {
            "partners": [],
            "delegation_zones": {
                "zone_1": {"range": "0-30%", "description": "Alles erlaubt, keine Einschraenkungen"},
                "zone_2": {"range": "30-60%", "description": "Nur kostengünstige Partner"},
                "zone_3": {"range": "60-80%", "description": "Nur lokale AI, kein API"},
                "zone_4": {"range": "80-100%", "description": "Nur Human, keine AI"}
            }
        }
        
        if not self.db_path.exists():
            return result
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, partner_name, partner_type, api_endpoint,
                       capabilities, cost_tier, token_zone, priority,
                       status, success_rate, notes
                FROM partner_recognition
            """)
            
            # Cost-Tier zu Token-Cost Mapping
            cost_mapping = {1: "low", 2: "medium", 3: "high", 0: "none"}
            
            # Type Mapping (DB -> JSON Format)
            type_mapping = {"api": "external_ai", "local": "local_ai", "human": "human"}
            
            for row in cursor.fetchall():
                # Capabilities parsen
                caps = []
                if row["capabilities"]:
                    try:
                        caps = json_lib.loads(row["capabilities"])
                    except (json.JSONDecodeError, ValueError, TypeError):
                        caps = []

                # Zone extrahieren (z.B. "zone_1" -> [1])
                zone_num = 1
                if row["token_zone"]:
                    try:
                        zone_num = int(row["token_zone"].replace("zone_", ""))
                    except (ValueError, AttributeError):
                        zone_num = 1
                
                # Alle Zonen bis zur aktuellen Zone erlauben (typisches Muster)
                delegation_zones = list(range(zone_num, 5))
                
                partner = {
                    "id": str(row["id"]),
                    "name": row["partner_name"],
                    "type": type_mapping.get(row["partner_type"], row["partner_type"]),
                    "status": row["status"] or "active",
                    "role": row["notes"] or f"{row['partner_type'].capitalize()} Partner",
                    "token_cost": cost_mapping.get(row["cost_tier"], "medium"),
                    "capabilities": caps,
                    "delegation_zones": delegation_zones,
                    "priority": row["priority"] or 50,
                    "success_rate": row["success_rate"] or 1.0,
                    "config": {"api_endpoint": row["api_endpoint"]} if row["api_endpoint"] else {}
                }
                result["partners"].append(partner)
            
            conn.close()
            
        except Exception as e:
            # Bei DB-Fehler leeres Ergebnis
            pass
        
        return result
    
    @property
    def profile_name(self) -> str:
        return "partner"
    
    @property
    def target_file(self) -> Path:
        return self.registry_path
    
    def get_operations(self) -> dict:
        return {
            "list": "Alle Partner auflisten",
            "status": "Status aller Partner",
            "info": "Partner-Details anzeigen",
            "active": "Nur aktive Partner",
            "delegate": "Task an Partner delegieren (Token-aware)"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        # Primaer aus DB laden (JSON_001 Migration)
        data = self._load_partners_from_db()
        
        # Fallback auf JSON entfernt (Task #302)
        if not data.get("partners"):
            return False, "Keine Partner in DB gefunden. Bitte 'registry_watcher' prüfen oder 'bach.db' wiederherstellen."
        
        if operation == "info" and args:
            return self._info(data, args[0])
        elif operation == "status":
            return self._status(data)
        elif operation == "active":
            return self._list(data, active_only=True)
        elif operation == "delegate":
            return self._delegate(data, args, dry_run)
        else:
            return self._list(data, active_only=False)
    
    def _list(self, data: dict, active_only: bool = False) -> tuple:
        """Partner auflisten."""
        results = []
        results.append("")
        results.append("[PARTNER] Partner-Netzwerk")
        results.append("=" * 50)
        
        partners = data.get("partners", [])
        if active_only:
            partners = [p for p in partners if p.get("status") == "active"]
        
        for p in partners:
            status_icon = "[x]" if p.get("status") == "active" else "[ ]"
            type_icon = self._get_type_icon(p.get("type", ""))
            zones = p.get("delegation_zones", [])
            zones_str = ",".join(str(z) for z in zones)
            
            results.append(f"  {status_icon} {type_icon} {p.get('name', 'Unknown')}")
            results.append(f"      Rolle: {p.get('role', '-')}")
            results.append(f"      Kosten: {p.get('token_cost', '-')} | Zonen: {zones_str}")
        
        results.append("")
        results.append(f"  Gesamt: {len(data.get('partners', []))} Partner, "
                      f"{len([p for p in data.get('partners', []) if p.get('status') == 'active'])} aktiv")
        
        return True, "\n".join(results)
    
    def _status(self, data: dict) -> tuple:
        """Status-Uebersicht."""
        results = []
        results.append("")
        results.append("[STATUS] Partner-Status")
        results.append("=" * 50)
        
        # Zaehler
        active = 0
        inactive = 0
        humans = 0
        local_ai = 0
        external_ai = 0
        
        for p in data.get("partners", []):
            if p.get("status") == "active":
                active += 1
            else:
                inactive += 1
            
            ptype = p.get("type", "")
            if ptype == "human":
                humans += 1
            elif ptype == "local_ai":
                local_ai += 1
            elif ptype == "external_ai":
                external_ai += 1
        
        results.append(f"  Aktiv:    {active}")
        results.append(f"  Inaktiv:  {inactive}")
        results.append("")
        results.append("  Nach Typ:")
        results.append(f"    Human:       {humans}")
        results.append(f"    Lokal AI:    {local_ai}")
        results.append(f"    Extern AI:   {external_ai}")
        
        # Delegation Zones
        results.append("")
        results.append("  Delegation-Zonen:")
        zones = data.get("delegation_zones", {})
        for zone_name, zone_data in zones.items():
            results.append(f"    {zone_name}: {zone_data.get('range', '?')} - {zone_data.get('description', '')}")
        
        return True, "\n".join(results)
    
    def _info(self, data: dict, identifier: str) -> tuple:
        """Partner-Details."""
        partners = data.get("partners", [])
        
        # Suche nach ID oder Name
        found = None
        for p in partners:
            if p.get("id") == identifier or p.get("name", "").lower() == identifier.lower():
                found = p
                break
        
        if not found:
            return False, f"Partner nicht gefunden: {identifier}"
        
        results = []
        results.append("")
        results.append(f"[PARTNER] {found.get('name')}")
        results.append("=" * 50)
        results.append(f"  ID:       {found.get('id')}")
        results.append(f"  Typ:      {found.get('type')}")
        results.append(f"  Status:   {found.get('status')}")
        results.append(f"  Rolle:    {found.get('role')}")
        results.append(f"  Kosten:   {found.get('token_cost')}")
        results.append("")
        results.append(f"  Capabilities: {', '.join(found.get('capabilities', []))}")
        results.append(f"  Zonen:        {found.get('delegation_zones')}")
        
        if found.get("config"):
            results.append(f"  Config:       {found.get('config')}")
        
        return True, "\n".join(results)
    
    def _delegate(self, data: dict, args: list, dry_run: bool = False) -> tuple:
        """Task an Partner delegieren (Token-aware + clutch-bridge).

        Args:
            args: Liste mit Task-Text und optionalen Flags
                  --to=NAME: Spezifischer Partner
                  --zone=N: Zone erzwingen (1-4)
                  --gas=N: Reasoning-Level 0-100 (clutch-bridge)
        """
        # Parse args
        task_text = ""
        target_partner = None
        forced_zone = None
        gas_level = None
        results = []
        fallback_local = "--fallback-local" in args or "--fal" in args

        args = [a for a in args if a not in ["--fallback-local", "--fal", "--dry-run"]]

        for arg in args:
            if arg.startswith("--to="):
                target_partner = arg.split("=", 1)[1]
            elif arg.startswith("--zone="):
                try:
                    forced_zone = int(arg.split("=", 1)[1])
                except ValueError:
                    return False, f"Ungueltige Zone: {arg}"
            elif arg.startswith("--gas="):
                try:
                    gas_level = int(arg.split("=", 1)[1])
                except ValueError:
                    return False, f"Ungueltige Gas-Stellung: {arg}"
            else:
                task_text = arg if not task_text else f"{task_text} {arg}"

        if not task_text:
            return False, "Kein Task angegeben. Nutzung: bach partner delegate 'Task-Beschreibung' [--to=NAME] [--zone=N] [--gas=N]"

        # clutch-bridge: StreckenAnalyse + Gas/Bremse
        strecken_profil = None
        gas_stellung = None
        if HAS_CLUTCH_BRIDGE:
            strecken_profil = get_strecken_analyser().analysiere(task_text)
            gas_stellung = berechne_gas(
                gas_level=gas_level,
                strecken_schwierigkeit=strecken_profil.schwierigkeit,
                strecken_typ_code=strecken_profil.typ_code,
            )

        # Aktuelle Zone ermitteln (vereinfacht: Zone 1 als Default)
        current_zone = forced_zone if forced_zone else self._get_current_zone()
        
        # Partner fuer Zone filtern
        partners = data.get("partners", [])
        available = []
        
        for p in partners:
            if p.get("status") != "active":
                continue
            if current_zone in p.get("delegation_zones", []):
                available.append(p)
        
        # Spezifischer Partner gewuenscht?
        selected = None
        if target_partner:
            # Erst DB-basierte Zone-Pruefung
            allowed, reason = self._is_partner_allowed_in_zone(target_partner, current_zone)
            if not allowed:
                return False, reason
            
            for p in available:
                if p.get("name", "").lower() == target_partner.lower():
                    selected = p
                    break
            if not selected:
                # Pruefen ob Partner existiert aber nicht in Zone
                for p in partners:
                    if p.get("name", "").lower() == target_partner.lower():
                        return False, f"Partner '{target_partner}' nicht in Zone {current_zone} verfuegbar. Zonen: {p.get('delegation_zones')}"
                return False, f"Partner nicht gefunden: {target_partner}"
        else:
            # Auto-Auswahl: Token-sparsamsten Partner waehlen
            cost_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
            available.sort(key=lambda p: cost_order.get(p.get("token_cost", "high"), 3))
            if available:
                # Nicht an sich selbst delegieren (Claude)
                for p in available:
                    if p.get("name") != "Claude":
                        selected = p
                        break
                if not selected:
                    selected = available[0]
        
        if not selected:
            return False, f"Kein Partner fuer Zone {current_zone} verfuegbar."
        
        # Offline-Fallback Logik (OLLAMA_005)
        if selected.get('type') == 'external_ai' and fallback_local:
            if not self._is_network_available():
                fallback_partner = None
                # Suche nach lokalem AI-Partner (Ollama bevorzugt)
                for p in partners:
                    if p.get('status') == 'active' and p.get('type') == 'local_ai':
                        fallback_partner = p
                        if p.get('name').lower() == "ollama":
                            break
                
                if fallback_partner:
                    results = ["[PARTNER] Offline-Fallback aktiviert"]
                    results.append(f"  [WARN] Netzwerk offline! Wechsel von {selected.get('name')} zu {fallback_partner.get('name')}.")
                    selected = fallback_partner
                else:
                    return False, f"Netzwerk offline und kein lokaler AI-Partner gefunden."

        # clutch-bridge: Bordcomputer Circuit-Breaker prüfen
        if HAS_CLUTCH_BRIDGE and selected:
            bordcomputer = get_bordcomputer()
            provider_name = selected.get('name', '')
            if not bordcomputer.is_available(provider_name):
                # Provider gesperrt, Alternative suchen
                for p in available:
                    if p != selected and bordcomputer.is_available(p.get('name', '')):
                        results.append(f"  [BORDCOMPUTER] {provider_name} gesperrt (Circuit-Breaker OPEN)")
                        results.append(f"  [BORDCOMPUTER] Fallback: {p.get('name')}")
                        selected = p
                        break
                else:
                    results.append(f"  [BORDCOMPUTER] WARNUNG: {provider_name} gesperrt, kein Fallback verfügbar")

            # Overkill-Check
            if strecken_profil:
                overkill = bordcomputer.check_overkill(
                    task_beschreibung=task_text,
                    gewaehltes_modell=selected.get('name', '').lower(),
                    strecken_typ=strecken_profil.typ,
                    strecken_schwierigkeit=strecken_profil.schwierigkeit,
                    empfohlener_gang=strecken_profil.empfohlener_gang,
                )
                if overkill:
                    results.append(f"  [BORDCOMPUTER] Overkill: {overkill.gewaehltes_modell} für {overkill.strecken_typ} (empfohlen: {overkill.empfohlenes_modell})")

        # Delegation vorbereiten
        if not results:
            results = []
        results.append("")
        results.append("[DELEGATION] Task-Delegation")
        results.append("=" * 50)
        results.append(f"  Zone:     {current_zone} ({self._get_zone_desc(data, current_zone)})")
        results.append(f"  Partner:  {selected.get('name')}")
        results.append(f"  Typ:      {selected.get('type')}")
        results.append(f"  Kosten:   {selected.get('token_cost')}")

        # clutch-bridge Details
        if strecken_profil:
            results.append(f"  Strecke:  {strecken_profil.typ} (Schw. {strecken_profil.schwierigkeit}/5, Etappen: {strecken_profil.etappen})")
        if gas_stellung:
            results.append(f"  Gas:      {gas_stellung.level}% ({gas_stellung.strategie.value}), Token-Multi: {gas_stellung.token_multiplikator}x")

        results.append("")
        results.append(f"  Task:     {task_text}")
        results.append("")

        if dry_run:
            results.append("  [DRY-RUN] Keine Aktion ausgefuehrt.")
        else:
            # Nachricht in MessageBox speichern
            msg_path = self.base_path / "data" / "messages" / "message_box.md"
            msg_path.parent.mkdir(parents=True, exist_ok=True)

            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

            # clutch-bridge Kontext in Delegation-Nachricht
            clutch_info = ""
            if strecken_profil:
                clutch_info += f"\n- Strecke: {strecken_profil.typ} (Code {strecken_profil.typ_code})"
                clutch_info += f"\n- Schwierigkeit: {strecken_profil.schwierigkeit}/5, Etappen: {strecken_profil.etappen}"
            if gas_stellung:
                clutch_info += f"\n- Gas-Stellung: {gas_stellung.level}% ({gas_stellung.strategie.value})"
                clutch_info += f"\n- Token-Multiplikator: {gas_stellung.token_multiplikator}x"

            # Prompt-Modifikation durch Gas/Bremse
            task_for_delegation = task_text
            if gas_stellung and gas_stellung.prompt_prefix:
                task_for_delegation = f"{gas_stellung.prompt_prefix}\n\n{task_text}"
            if gas_stellung and gas_stellung.prompt_suffix:
                task_for_delegation = f"{task_for_delegation}\n\n{gas_stellung.prompt_suffix}"

            delegation_msg = f"""
## Delegation an {selected.get('name')} ({timestamp})

**Task:** {task_for_delegation}

**Kontext:**
- Zone: {current_zone}
- Capabilities: {', '.join(selected.get('capabilities', []))}
- Rolle: {selected.get('role')}{clutch_info}

---
"""
            with open(msg_path, 'a', encoding='utf-8') as f:
                f.write(delegation_msg)

            results.append(f"  [OK] Delegation in MessageBox gespeichert.")
            results.append(f"       -> {msg_path}")

            # clutch-bridge: Fahrtenbuch-Eintrag schreiben
            if HAS_CLUTCH_BRIDGE:
                try:
                    fb = get_fahrtenbuch(db_path=self.base_path / "data" / "bach.db")
                    fb.eintrag(
                        task_text=task_text,
                        provider=selected.get('name', ''),
                        model=strecken_profil.empfohlener_gang if strecken_profil else '',
                        strecken_typ=strecken_profil.typ if strecken_profil else '',
                        strecken_typ_code=strecken_profil.typ_code if strecken_profil else 0,
                        schwierigkeit=strecken_profil.schwierigkeit if strecken_profil else 0,
                        etappen=strecken_profil.etappen if strecken_profil else 0,
                        gas_level=gas_stellung.level if gas_stellung else 50,
                        gas_strategie=gas_stellung.strategie.value if gas_stellung else 'ausgewogen',
                        token_budget_faktor=gas_stellung.token_multiplikator if gas_stellung else 1.0,
                        zone=current_zone,
                    )
                except Exception:
                    pass  # Fahrtenbuch-Fehler sollen Delegation nicht blockieren

        return True, "\n".join(results)
    
    def _get_current_zone(self) -> int:
        """Ermittelt aktuelle Zone basierend auf Token-Verbrauch aus DB.
        
        Liest budget_percent aus monitor_tokens und mappt auf Zone:
        - Zone 1: 0-30%
        - Zone 2: 30-60%
        - Zone 3: 60-80%
        - Zone 4: 80-100%
        """
        import sqlite3
        
        db_path = self.base_path / "data" / "bach.db"
        if not db_path.exists():
            return 1  # Default
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Neuesten Token-Eintrag holen
            cursor.execute("""
                SELECT budget_percent FROM monitor_tokens 
                ORDER BY timestamp DESC LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()
            
            if not row or row[0] is None:
                return 1  # Kein Eintrag = Zone 1
            
            budget_pct = float(row[0])
            
            # Zone basierend auf delegation_rules Ranges
            if budget_pct < 30:
                return 1
            elif budget_pct < 60:
                return 2
            elif budget_pct < 80:
                return 3
            else:
                return 4
                
        except Exception:
            return 1  # Fallback
    
    def _get_zone_desc(self, data: dict, zone: int) -> str:
        """Zone-Beschreibung holen."""
        zones = data.get("delegation_zones", {})
        zone_key = f"zone_{zone}"
        if zone_key in zones:
            return zones[zone_key].get("description", "")
        return "Unbekannte Zone"
    
    def _get_type_icon(self, ptype: str) -> str:
        """Icon fuer Partner-Typ."""
        icons = {
            "human": "[H]",
            "local_ai": "[L]",
            "external_ai": "[E]"
        }
        return icons.get(ptype, "[?]")
    
    def _get_allowed_partners_from_db(self, zone: int) -> list:
        """Liest erlaubte Partner fuer Zone aus delegation_rules Tabelle.
        
        Returns:
            Liste der erlaubten Partner-Namen oder leere Liste bei Fehler.
        """
        import sqlite3
        import json as json_lib
        
        db_path = self.base_path / "data" / "bach.db"
        if not db_path.exists():
            return []
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT allowed_partners FROM delegation_rules 
                WHERE zone = ? AND status = 'active'
            """, (f"zone_{zone}",))
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0]:
                return json_lib.loads(row[0])
            return []
        except Exception:
            return []
    
    def _is_partner_allowed_in_zone(self, partner_name: str, zone: int) -> tuple:
        """Prueft ob ein Partner in der aktuellen Zone erlaubt ist.
        
        Returns:
            (True, "") wenn erlaubt
            (False, "Fehlergrund") wenn nicht erlaubt
        """
        allowed = self._get_allowed_partners_from_db(zone)
        
        if not allowed:
            # Fallback: JSON-Zonen pruefen
            return True, ""
        
        if partner_name in allowed:
            return True, ""
        
        return False, f"Partner '{partner_name}' nicht in Zone {zone} erlaubt. Erlaubt: {', '.join(allowed)}"

    def _is_network_available(self, timeout=2) -> bool:
        """Prueft die Internetverbindung (DNS-Check)."""
        import socket
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
            return True
        except socket.error:
            return False
