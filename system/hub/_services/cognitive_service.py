"""
cognitive_service.py
====================
Kanonischer Service für den Kognitiven Schaltplan, Prozess-Topologie,
die 8 Prozessblöcke, USMC-Schema-Sicherheit und Denkarium-Archivierung
gemäß GUX-032 bis GUX-043 (Register GUX-94-2026-10-04-v1.1, Task #1700).

Architektur & Prinzipien:
-------------------------
1. GUX-032: Architekturansicht rendert die kanonische Mermaid-Quelle selbst.
2. GUX-033: Diagrammfarben zeigen die Prozesszugehörigkeit und besitzen eine Legende.
3. GUX-034 bis GUX-041: Die 8 kognitiven Prozessblöcke als Soll-Modell mit separat gemessenen Tabellenständen:
   - 1. kontextfenster (Baddeley Working Memory / Phonologische Schleife)
   - 2. zentrale_exekutive (Norman & Shallice SAS, Miller TOTE, Circuit Breaker)
   - 3. sensoren_messtechnik (Context-Reader, Token-Monitor, Stress-Detektor)
   - 4. guards (Deterministische Skript-Guards & Lebendige LLM-Guards)
   - 5. berechtigung_hooker (Prüfung und Zustellung als Teilprozesse)
   - 6. startprompt (Synthese aus Agent + System + Aufgabe mit Boot-Bus)
   - 7. lernen_rueckfluss (NemoFold / Hermes / Lessons learned)
   - 8. langzeit_gedaechtnis (SSoT-Trennung BACH vs. USMC vs. Gardener)
4. GUX-041 / GUX-042 Follow-up: Robuster legacy-kompatibler USMC-Lessons-Reader
   (kein Absturz bei fehlender 'source_kind'-Spalte, kein spontanes ALTER TABLE).
5. GUX-043: Denkarium als menschliches Notizbuch mit reversibler Archivierung
   technischer Fehleinträge (Agent-Dumps).
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from hub.bach_paths import BACH_DB
except ImportError:
    try:
        from system.hub.bach_paths import BACH_DB
    except ImportError:
        BACH_DB = Path.home() / ".bach" / "bach.db"


def _resolve_connection(
    conn: sqlite3.Connection | None = None, *, readonly: bool = False
) -> tuple[sqlite3.Connection, bool]:
    """Liefert eine SQLite-Verbindung und ein Flag, ob sie geschlossen werden muss."""
    if conn is not None:
        return conn, False
    c = (sqlite3.connect(BACH_DB.resolve().as_uri() + "?mode=ro", uri=True)
         if readonly else sqlite3.connect(str(BACH_DB)))
    c.row_factory = sqlite3.Row
    return c, True


CANONICAL_MERMAID_DIAGRAM = """flowchart TD
    subgraph ZE ["1. Zentrale Exekutive & Messtechnik"]
        EXEC["Zentrale Exekutive (Soll-Prozess: Aufsicht / SAS)"]
        SENS["Sensoren & Messtechnik (Context-Reader, Token-Monitor, Stress-Detektor)"]
        EXEC -->|"Aufsichts-Auftrag"| SENS
    end

    subgraph SK ["2. Teilprozesse: Regeln und Grenzen prüfen"]
        DG["Deterministische Skript-Guards (P-001 Git-Sperre, Pfad-Locks, Regex-Filter)"]
        LG["Lebendige LLM-Guards (/goal Evaluator, Disambiguierung, Konsistenz)"]
        SENS -->|"Messdaten & Limits"| DG
        SENS -->|"CoT-Auszüge & Drift"| LG
    end

    subgraph GATE ["3. Berechtigungskontrolle (Decision Gate)"]
        DEC{"Injektion freigegeben?"}
        DG -->|"Skript-Check OK"| DEC
        LG -->|"Guard-Freigabe"| DEC
    end

    subgraph HOOK ["4. Teilprozess: Kontext zustellen"]
        HK["Payload und Providerformat (kann im selben Hooker liegen)"]
        DEC -->|"Autorisierter Payload (Gedanke / Faktenanker)"| HK
    end

    subgraph BOOT ["5. Startprompt-Synthese (Einmaliger Start)"]
        SP["Startprompt: Agent (Rolle + Persona + Skills + Governance) + System + Aufgabe"]
    end

    subgraph CTX ["6. Zentrum: Aktives Kontextfenster"]
        KW["Aktives Kontextfenster (Phonologische Schleife & CoT)"]
        SP -->|"Einmaliger Boot-Bus"| KW
        HK -->|"Zusatzkontext; Anschluss separat nachweisen"| KW
    end

    subgraph MEM ["7. Langzeitgedächtnis (SSoT: bach.db, usmc, gardener)"]
        LTM[("Langzeitgedächtnis (Fakten, Sessions, Lessons)")]
        LTM -.->|"Pfad A: Boot-Kontext"| SP
        KW -->|"Pfad B: Aktiver Tool-Pull (z.B. bach mem query)"| LTM
        LTM -.->|"Pfad C: Reaktiv über Guards"| SK
    end

    subgraph LEARN ["8. Lern- & Konsolidierungssystem"]
        CL["Kognitives Lernen (Soll-Prozess; separat prüfen)"]
        KW -->|"Rohdaten-Strom"| CL
        CL -->|"Destilliertes Wissen"| LTM
    end
    NOTE["Prozessgrenzen sind keine Modulgrenzen. Hooker können Prüfung und Zustellung enthalten."]
    NOTE -.-> HK
    classDef control fill:#27364a,stroke:#8c9fbc,color:#eef2f6
    classDef context fill:#233b3c,stroke:#86aaa8,color:#eef2f6
    classDef storage fill:#393630,stroke:#aba292,color:#eef2f6
    classDef annotation fill:#292e36,stroke:#8a929e,color:#eef2f6
    class EXEC,SENS,DG,LG,DEC,HK control
    class SP,KW context
    class LTM,CL storage
    class NOTE annotation
    linkStyle 0,1,2,3,4,5,7,10 stroke:#8c9fbc
    linkStyle 6,8 stroke:#86aaa8
    linkStyle 9,11,12 stroke:#aba292
    linkStyle 13 stroke:#8a929e
    style ZE fill:transparent,stroke:#8a929e
    style SK fill:transparent,stroke:#8a929e
    style GATE fill:transparent,stroke:#8a929e
    style HOOK fill:transparent,stroke:#8a929e
    style BOOT fill:transparent,stroke:#8a929e
    style CTX fill:transparent,stroke:#8a929e
    style MEM fill:transparent,stroke:#8a929e
    style LEARN fill:transparent,stroke:#8a929e"""

PROCESS_MODEL = {
    "state": "conceptual",
    "scope": "processes_and_subprocesses",
    "module_boundaries": "not_implied",
    "runtime_verified": False,
    "description": "Soll-Modell: Mehrere Teilprozesse dürfen im selben Hooker implementiert sein."
}

DIAGRAM_LEGEND = [
    {
        "id": "boot_bus",
        "name": "Einmaliger Boot-Bus",
        "color": "#86aaa8",
        "style": "solid",
        "description": "Initialer Startflash (Agent + System + Aufgabe) direkt ins leere Kontextfenster beim Start"
    },
    {
        "id": "injection_path",
        "name": "Autorisierter Injektions-Kanal",
        "color": "#8c9fbc",
        "style": "solid",
        "description": "Freigegebene Injektion über den Hooker ins laufende Kontextfenster nach bestandenem Decision Gate"
    },
    {
        "id": "supervision_sensors",
        "name": "Aufsicht & Messtechnik",
        "color": "#8c9fbc",
        "style": "solid",
        "description": "Messwerte, Token-Überwachung, Limits und CoT-Drift an die Selbstkontroll-Guards"
    },
    {
        "id": "active_tool_pull",
        "name": "Aktiver Tool-Pull",
        "color": "#aba292",
        "style": "solid",
        "description": "Explizite Abfragen des aktiven Modells via Tools (z. B. bach mem query, hb_kb_search)"
    },
    {
        "id": "reactive_guard",
        "name": "Reaktive Schutzschranke",
        "color": "#8c9fbc",
        "style": "dotted",
        "description": "Reaktiver Fakten- und Konsistenzabgleich aus dem Langzeitgedächtnis gegen Konfabulation"
    }
]


def ensure_denkarium_schema(conn: sqlite3.Connection | None = None) -> None:
    """Stellt sicher, dass denkarium_entries die Archivierungsspalten für GUX-043 besitzt."""
    actual_conn, should_close = _resolve_connection(conn)
    try:
        actual_conn.execute("""
            CREATE TABLE IF NOT EXISTS denkarium_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT DEFAULT 'denkarium',
                title TEXT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'Gedanke',
                source TEXT DEFAULT 'mensch',
                mood INTEGER DEFAULT 0,
                promoted_to TEXT,
                promoted_id INTEGER,
                is_archived INTEGER DEFAULT 0,
                archived_reason TEXT,
                archived_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        # Spalten pruefen und bei Bedarf additiv ergaenzen
        cols = {row[1] for row in actual_conn.execute("PRAGMA table_info(denkarium_entries)").fetchall()}
        if "is_archived" not in cols:
            actual_conn.execute("ALTER TABLE denkarium_entries ADD COLUMN is_archived INTEGER DEFAULT 0")
        if "archived_reason" not in cols:
            actual_conn.execute("ALTER TABLE denkarium_entries ADD COLUMN archived_reason TEXT")
        if "archived_at" not in cols:
            actual_conn.execute("ALTER TABLE denkarium_entries ADD COLUMN archived_at TEXT")
        actual_conn.commit()
    finally:
        if should_close:
            actual_conn.close()


def get_cognitive_topology(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Liefert die vollständige kognitive Topologie mit 8 Prozessblöcken, Mermaid und Legende (GUX-032..041)."""
    actual_conn, should_close = _resolve_connection(conn, readonly=True)
    try:
        # Nur Tabellenstände messen; fehlende Quellen sind keine leeren Tabellen.
        counts = dict.fromkeys(("facts", "lessons", "sessions", "working"))
        try:
            counts["facts"] = actual_conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
        except (sqlite3.Error, OSError) as e:
            logger.debug("memory_facts count nicht verfügbar: %s", e)
        try:
            counts["lessons"] = actual_conn.execute("SELECT COUNT(*) FROM memory_lessons WHERE is_active = 1").fetchone()[0]
        except (sqlite3.Error, OSError) as e:
            logger.debug("memory_lessons count nicht verfügbar: %s", e)
        try:
            counts["sessions"] = actual_conn.execute("SELECT COUNT(*) FROM memory_sessions").fetchone()[0]
        except (sqlite3.Error, OSError) as e:
            logger.debug("memory_sessions count nicht verfügbar: %s", e)
        try:
            counts["working"] = actual_conn.execute("SELECT COUNT(*) FROM memory_working WHERE is_active = 1").fetchone()[0]
        except (sqlite3.Error, OSError) as e:
            logger.debug("memory_working count nicht verfügbar: %s", e)

        now = datetime.now(timezone.utc).isoformat()

        blocks = {
            "kontextfenster": {
                "id": "kontextfenster",
                "number": 6,
                "title": "Aktives Kontextfenster",
                "sub": "Phonologische Schleife & CoT-Arbeitsgedächtnis (Baddeley)",
                "status": "not_verified",
                "data_source": "memory_working",
                "active_items_count": counts["working"],
                "role": "Soll-Prozess des aktiven Kontextfensters. Gespeicherte Working-Einträge belegen keine aktuelle Kontextbelegung.",
                "evidence_kind": "database_snapshot"
            },
            "zentrale_exekutive": {
                "id": "zentrale_exekutive",
                "number": 1,
                "title": "Zentrale Exekutive & Messtechnik",
                "sub": "Norman & Shallice (SAS) • Miller TOTE (/plan, /goal) • Notfall-Circuit-Breaker",
                "status": "not_verified",
                "data_source": None,
                "role": "Führung und Aufsicht: Greift bei neuartigen Aufgaben, Konflikten und Risiken regulierend ein.",
                "evidence_kind": "conceptual_model"
            },
            "sensoren_messtechnik": {
                "id": "sensoren_messtechnik",
                "number": 1.2,
                "title": "Sensoren & Messtechnik",
                "sub": "Context-Reader • Token-Monitor • Loop- & Drift-Detektor",
                "status": "not_verified",
                "data_source": None,
                "role": "Soll-Prozess für Messwerte und Bedarfserkennung; kein angeschlossener Laufzeitnachweis.",
                "evidence_kind": "conceptual_model"
            },
            "guards": {
                "id": "guards",
                "number": 2,
                "title": "Selbstkontroll-Guards",
                "sub": "Deterministische Skript-Guards (P-001, Locks) & Lebendige LLM-Guards (/goal, Disambiguierung)",
                "status": "not_verified",
                "data_source": None,
                "role": "Soll-Prozess: Regeln und Rechte vor Aktionen oder Kontextzustellung prüfen; Durchsetzung separat nachweisen.",
                "evidence_kind": "conceptual_model"
            },
            "berechtigung_hooker": {
                "id": "berechtigung_hooker",
                "number": 3,
                "title": "Berechtigungskontrolle & Hooker",
                "sub": "Kontext auswählen ➔ Grenzen prüfen ➔ Payload zustellen",
                "status": "not_verified",
                "data_source": None,
                "role": "Diese Teilprozesse und Aktionsguards dürfen im selben Hooker liegen. Ausführung hängt vom Laufzeitanschluss ab.",
                "evidence_kind": "conceptual_model"
            },
            "startprompt": {
                "id": "startprompt",
                "number": 5,
                "title": "Startprompt-Synthese",
                "sub": "Einmaliger Boot-Bus [Boot:Agent] + [Boot:System] + [Boot:Aufgabe]",
                "status": "not_verified",
                "data_source": None,
                "role": "Soll-Prozess der Promptzusammenstellung; hier wird kein konkreter Lauf geprüft.",
                "evidence_kind": "conceptual_model"
            },
            "lernen_rueckfluss": {
                "id": "lernen_rueckfluss",
                "number": 8,
                "title": "Kognitives Lernen & Konsolidierung",
                "sub": "NemoFold (Workflow-Ketten) & Hermes (Skill-Destillation) & Lessons Learned",
                "status": "not_verified",
                "data_source": "memory_lessons",
                "active_lessons_count": counts["lessons"],
                "role": "Rückfluss aus Beobachtung und Dialog: Vorschlag ➔ Review ➔ append-only Übernahme.",
                "evidence_kind": "database_snapshot"
            },
            "langzeit_gedaechtnis": {
                "id": "langzeit_gedaechtnis",
                "number": 7,
                "title": "Langzeitgedächtnis (SSoT)",
                "sub": "Faktenwissen, Sessions, Lessons (SSoT-Trennung: BACH vs. USMC vs. Gardener)",
                "status": ("available" if all(counts[key] is not None for key in ("facts", "sessions", "lessons"))
                           else "unavailable"),
                "data_source": "memory_facts / memory_sessions / memory_lessons",
                "facts_count": counts["facts"],
                "sessions_count": counts["sessions"],
                "lessons_count": counts["lessons"],
                "role": "Dauerhaftes Gedächtnis mit Datenschutz-Grenzen und robuster Abwärtskompatibilität.",
                "evidence_kind": "database_snapshot"
            }
        }

        for block in blocks.values():
            block["runtime_verified"] = False
            block["architecture_model"] = dict(PROCESS_MODEL)

        return {
            "success": True,
            "observed_at": now,
            "architecture_model": dict(PROCESS_MODEL),
            "measurement_scope": "bach_memory_table_counts",
            "source_availability": {key: "available" if count is not None else "unavailable"
                                    for key, count in counts.items()},
            "mermaid_code": CANONICAL_MERMAID_DIAGRAM,
            "legend": DIAGRAM_LEGEND,
            "counts": counts,
            "blocks": blocks,
            "block_keys": list(blocks.keys())
        }
    finally:
        if should_close:
            actual_conn.close()


def get_process_block(
    block_id_or_conn: Any,
    block_id: str | None = None,
    conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """Liefert tiefe Inspektionsdaten zu einem der 8 kognitiven Prozessblöcke (GUX-034..041)."""
    if isinstance(block_id_or_conn, sqlite3.Connection):
        actual_conn = block_id_or_conn
        actual_block_id = block_id
    elif isinstance(block_id_or_conn, str):
        actual_block_id = block_id_or_conn
        actual_conn = conn
    else:
        actual_block_id = block_id
        actual_conn = conn or block_id_or_conn

    if not actual_block_id:
        raise ValueError("block_id ist erforderlich")

    actual_conn, should_close = _resolve_connection(actual_conn, readonly=True)
    try:
        topology = get_cognitive_topology(actual_conn)
        blocks = topology["blocks"]
        if actual_block_id not in blocks:
            raise ValueError(f"Unbekannter Prozessblock '{actual_block_id}'. Gültig: {', '.join(blocks.keys())}")

        block = dict(blocks[actual_block_id])
        now = datetime.now(timezone.utc).isoformat()

        # Gespeicherte Daten und ausdrücklich fehlende Laufzeitnachweise.
        if actual_block_id == "kontextfenster":
            try:
                working_rows = actual_conn.execute("SELECT id, type, content, priority, created_at FROM memory_working WHERE is_active = 1 ORDER BY priority DESC, id DESC LIMIT 10").fetchall()
                block["working_items"] = [dict(r) if isinstance(r, sqlite3.Row) else {"id": r[0], "type": r[1], "content": r[2], "priority": r[3], "created_at": r[4]} for r in working_rows]
                block["working_items_availability"] = "available"
            except (sqlite3.Error, OSError):
                block["working_items"] = []
                block["working_items_availability"] = "unavailable"
        elif actual_block_id == "sensoren_messtechnik":
            block["sensor_receipt"] = {
                "receipt_id": None,
                "timestamp": None,
                "context_usage_percent": None,
                "cot_loop_detected": None,
                "stress_index": None,
                "status": "not_verified"
            }
        elif actual_block_id == "guards":
            block["guard_receipt"] = {
                "receipt_id": None,
                "timestamp": None,
                "deterministic_git_guard": None,
                "lock_master_guard": None,
                "anti_confabulation_guard": None,
                "decision": None,
                "status": "not_verified"
            }
        elif actual_block_id == "berechtigung_hooker":
            block["injection_gate"] = {
                "authorized": None,
                "target": "active_context",
                "executor": None,
                "has_control_logic": None,
                "delivery_receipt": None,
                "status": "not_verified",
                "module_boundaries": "not_implied"
            }
        elif actual_block_id == "langzeit_gedaechtnis":
            block["ssot_architecture"] = {
                "bach_db": "Kanonische lokale SQLite-Datenbank (User Scope)",
                "usmc_db": "USMC Memory Fassade (~/.usmc/usmc_memory.db)",
                "gardener_db": "Gardener Wissensindex & Deep Search (~/.gardener)",
                "schema_contract": "memory_union v2 (additive Parität)"
            }

        return {
            "success": True,
            "block": block,
            "observed_at": now
        }
    finally:
        if should_close:
            actual_conn.close()


def read_usmc_lessons_safe(
    db_or_conn: sqlite3.Connection | str | Path | None = None,
    limit: int = 50,
    category: str | None = None
) -> dict[str, Any]:
    """Liest Lessons Learned schema-agnostisch und robust (GUX-041/GUX-042 Follow-up).

    Fängt 'no such column: source_kind' fail-closed ab, ohne ALTER TABLE oder DB-Mutationen.
    Unterstützt sowohl 'memory_lessons' als auch 'usmc_lessons'.
    """
    if db_or_conn is None:
        usmc_cand = Path.home() / ".usmc" / "usmc_memory.db"
        if usmc_cand.is_file():
            db_or_conn = usmc_cand
        else:
            db_or_conn = BACH_DB

    is_path = isinstance(db_or_conn, (str, Path))
    if is_path:
        path = Path(db_or_conn)
        if not path.is_file():
            return {
                "success": False,
                "availability": "unavailable",
                "error": "database_missing",
                "lessons": [],
                "count": 0
            }
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    else:
        conn = db_or_conn

    try:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        table_name = None
        if "memory_lessons" in tables:
            table_name = "memory_lessons"
        elif "usmc_lessons" in tables:
            table_name = "usmc_lessons"

        if not table_name:
            return {
                "success": False,
                "availability": "unavailable",
                "error": "no_lessons_table_found",
                "lessons": [],
                "count": 0
            }

        # Spalten untersuchen
        col_info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        col_names = {row["name"] for row in col_info}

        has_source_kind = "source_kind" in col_names
        has_is_active = "is_active" in col_names
        has_category = "category" in col_names
        has_editorial_status = "editorial_status" in col_names

        # Dynamisches sicheres Select
        select_cols = ["id", "title", "solution"]
        if has_category:
            select_cols.append("category")
        if has_is_active:
            select_cols.append("is_active")
        if has_source_kind:
            select_cols.append("source_kind")
        if has_editorial_status:
            select_cols.append("editorial_status")
        if "created_at" in col_names:
            select_cols.append("created_at")

        query = f"SELECT {', '.join(select_cols)} FROM {table_name} WHERE 1=1"
        params: list[Any] = []

        if has_is_active:
            query += " AND is_active = 1"
        if category and has_category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        lessons = []
        for r in rows:
            row_dict = dict(r)
            # Legacy-Mapping für fehlende Spalten
            if not has_source_kind:
                row_dict["source_kind"] = "legacy"
            if not has_editorial_status:
                row_dict["editorial_status"] = "legacy"
            if not has_category:
                row_dict["category"] = "general"

            row_dict["provenance_status"] = "native_v2" if has_source_kind else "legacy_mapped"
            lessons.append(row_dict)

        return {
            "success": True,
            "availability": "available",
            "table_used": table_name,
            "has_source_kind": has_source_kind,
            "lessons": lessons,
            "count": len(lessons),
            "error": None
        }
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
        logger.warning("Fehler beim Lesen der USMC Lessons: %s", exc)
        return {
            "success": False,
            "availability": "unavailable",
            "error": "read_error",
            "lessons": [],
            "count": 0
        }
    finally:
        if is_path:
            conn.close()


def archive_denkarium_entry(
    entry_id: Any,
    reason: str = "wrong_agent_dump",
    conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """Archiviert einen Denkarium-Eintrag reversibel (GUX-043)."""
    if isinstance(entry_id, sqlite3.Connection):
        actual_conn = entry_id
        actual_entry_id = int(reason)
        actual_reason = "wrong_agent_dump" if conn is None else str(conn)
    else:
        actual_entry_id = int(entry_id)
        actual_reason = str(reason)
        actual_conn = conn

    actual_conn, should_close = _resolve_connection(actual_conn)
    try:
        ensure_denkarium_schema(actual_conn)
        row = actual_conn.execute("SELECT id, title, content, is_archived FROM denkarium_entries WHERE id = ?", (actual_entry_id,)).fetchone()
        if not row:
            raise ValueError(f"Denkarium-Eintrag #{actual_entry_id} nicht gefunden")

        now = datetime.now(timezone.utc).isoformat()
        undo_token = f"undo-{actual_entry_id}-{uuid.uuid4().hex[:8]}"

        actual_conn.execute("""
            UPDATE denkarium_entries
            SET is_archived = 1, archived_reason = ?, archived_at = ?, updated_at = ?
            WHERE id = ?
        """, (actual_reason, now, now, actual_entry_id))
        actual_conn.commit()

        return {
            "success": True,
            "entry_id": actual_entry_id,
            "action": "archived",
            "reason": actual_reason,
            "archived_at": now,
            "undo_token": undo_token,
            "message": f"Eintrag #{actual_entry_id} reversibel archiviert ({actual_reason}). Kann jederzeit wiederhergestellt werden."
        }
    finally:
        if should_close:
            actual_conn.close()


def unarchive_denkarium_entry(
    entry_id: Any,
    conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """Stellt einen archivierten Denkarium-Eintrag wieder her (GUX-043 Reversibilität)."""
    if isinstance(entry_id, sqlite3.Connection):
        actual_conn = entry_id
        actual_entry_id = int(conn)
    else:
        actual_entry_id = int(entry_id)
        actual_conn = conn

    actual_conn, should_close = _resolve_connection(actual_conn)
    try:
        ensure_denkarium_schema(actual_conn)
        row = actual_conn.execute("SELECT id, title, is_archived FROM denkarium_entries WHERE id = ?", (actual_entry_id,)).fetchone()
        if not row:
            raise ValueError(f"Denkarium-Eintrag #{actual_entry_id} nicht gefunden")

        now = datetime.now(timezone.utc).isoformat()
        actual_conn.execute("""
            UPDATE denkarium_entries
            SET is_archived = 0, archived_reason = NULL, archived_at = NULL, updated_at = ?
            WHERE id = ?
        """, (now, actual_entry_id))
        actual_conn.commit()

        return {
            "success": True,
            "entry_id": actual_entry_id,
            "action": "unarchived",
            "restored_at": now,
            "message": f"Eintrag #{actual_entry_id} erfolgreich im aktiven Notizbuch wiederhergestellt."
        }
    finally:
        if should_close:
            actual_conn.close()


def list_denkarium_entries(
    conn: sqlite3.Connection | None = None,
    exclude_archived: bool = True,
    entry_type: str | None = None,
    category: str | None = None,
    limit: int = 50,
    search: str | None = None
) -> dict[str, Any]:
    """Listet Denkarium-Einträge mit Filterung archivierter Dumps (GUX-043)."""
    actual_conn, should_close = _resolve_connection(conn)
    try:
        ensure_denkarium_schema(actual_conn)
        actual_conn.row_factory = sqlite3.Row

        query = "SELECT * FROM denkarium_entries WHERE 1=1"
        params: list[Any] = []

        if exclude_archived:
            query += " AND (is_archived = 0 OR is_archived IS NULL)"

        if entry_type:
            query += " AND entry_type = ?"
            params.append(entry_type)

        if category:
            query += " AND category = ?"
            params.append(category)

        if search:
            query += " AND (title LIKE ? OR content LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s])

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = actual_conn.execute(query, params).fetchall()
        entries = [dict(r) for r in rows]

        # Stats
        stats_row = actual_conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_archived = 1 THEN 1 ELSE 0 END) as archived_count,
                SUM(CASE WHEN (is_archived = 0 OR is_archived IS NULL) AND entry_type = 'logbuch' THEN 1 ELSE 0 END) as logbuch,
                SUM(CASE WHEN (is_archived = 0 OR is_archived IS NULL) AND (entry_type = 'denkarium' OR entry_type IS NULL) THEN 1 ELSE 0 END) as denkarium
            FROM denkarium_entries
        """).fetchone()

        stats = {
            "total": stats_row["total"] if stats_row else 0,
            "archived": stats_row["archived_count"] or 0 if stats_row else 0,
            "logbuch": stats_row["logbuch"] or 0 if stats_row else 0,
            "denkarium": stats_row["denkarium"] or 0 if stats_row else 0
        }

        return {
            "success": True,
            "entries": entries,
            "count": len(entries),
            "stats": stats
        }
    finally:
        if should_close:
            actual_conn.close()
