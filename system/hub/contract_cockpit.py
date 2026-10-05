# SPDX-License-Identifier: MIT
"""hub/contract_cockpit.py - Vertrags- & Kündigungscockpit.

Vereinheitlicht Abonnements (hub/abo.py) und Versicherungen (hub/versicherung.py)
in einem generischen Datenmodell mit gemeinsamer Fristen-Engine, Erinnerungen,
Kostenübersicht und Export.

Operationen:
- init:      Initialisiert das Cockpit (Tabellen + Defaults).
- migrate:   Migriert Abo- und Versicherungsdaten in contract_* Tabellen.
- list:      Listet Verträge auf (optional type=..., status=...).
- fristen:   Berechnet Kündigungsfristen und aktualisiert Erinnerungen.
- costs:     Berechnet monatliche/jährliche Kosten (optional type=...).
- export:    Exportiert Verträge als CSV/JSON (fmt=csv|json).
- scan:      Scannt einen Text nach bekannten Vertragsmustern (text=...).
- reminders: Zeigt ausstehende Erinnerungen an.
"""

import csv
import hashlib
import io
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hub.base import BaseHandler
from hub._services.contract_dates import (
    _add_months,
    _format_date,
    _parse_date,
    calc_monthly,
    calc_next_cancellation,
    calc_yearly,
)
from hub._services.contract_reminders import (
    get_due_reminders,
    get_pending_reminders,
    mark_reminder,
    sync_contract_reminders,
)


CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL DEFAULT 'abo',
    status TEXT NOT NULL DEFAULT 'erkannt',
    name TEXT,
    anbieter TEXT,
    vertragsnummer TEXT,
    beginn_datum TEXT,
    ablauf_datum TEXT,
    kuendigungsfrist_monate INTEGER DEFAULT 1,
    verlaengerung_monate INTEGER DEFAULT 12,
    naechste_kuendigung TEXT,
    kuendigungslink TEXT,
    betrag_monatlich REAL,
    zahlungsintervall TEXT DEFAULT 'monatlich',
    steuer_relevant_typ TEXT,
    ordner_pfad TEXT,
    notizen TEXT,
    source_type TEXT,
    source_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contract_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL REFERENCES contracts(id),
    reminder_type TEXT NOT NULL,
    trigger_date TEXT NOT NULL,
    subject TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contract_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER REFERENCES contracts(id),
    posten_id INTEGER,
    betrag REAL,
    datum TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contract_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER REFERENCES contracts(id),
    schadensdatum TEXT,
    beschreibung TEXT,
    status TEXT DEFAULT 'offen',
    betrag_gefordert REAL,
    betrag_gezahlt REAL,
    aktenzeichen_versicherung TEXT,
    source_insurance_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contract_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER REFERENCES contracts(id),
    filename TEXT,
    document_path TEXT,
    document_type TEXT,
    hash TEXT,
    uploaded_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contract_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT,
    description TEXT,
    when_useful TEXT,
    priority INTEGER DEFAULT 3,
    legal_requirement TEXT,
    typical_cost_range TEXT,
    applies_to TEXT DEFAULT 'all',
    dist_type INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contract_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    anbieter TEXT NOT NULL,
    kategorie TEXT,
    kuendigungslink TEXT,
    applies_to TEXT DEFAULT 'abo',
    dist_type INTEGER DEFAULT 2,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contracts_type ON contracts(type);
CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);
CREATE INDEX IF NOT EXISTS idx_contracts_naechste_kuendigung ON contracts(naechste_kuendigung);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contracts_source ON contracts(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON contract_reminders(trigger_date, status);
CREATE INDEX IF NOT EXISTS idx_payments_contract ON contract_payments(contract_id);
CREATE INDEX IF NOT EXISTS idx_claims_contract ON contract_claims(contract_id);
"""

DEFAULT_CONTRACT_TYPES = [
    (1, "Kfz-Versicherung", "versicherung", "Kraftfahrzeug", "Immer nötig", 1,
     "gesetzlich (Haftpflicht)", "300-1200 EUR/Jahr", "versicherung", 1),
    (2, "Haftpflicht", "versicherung", "Private Haftpflicht", "Sinnvoll für jeden Haushalt", 1,
     "freiwillig", "50-150 EUR/Jahr", "versicherung", 1),
    (3, "Rechtsschutz", "versicherung", "Rechtsschutzversicherung", "Bei höherem Rechtsrisiko", 3,
     "freiwillig", "150-400 EUR/Jahr", "versicherung", 1),
    (4, "Hausrat", "versicherung", "Hausratversicherung", "Bei Miete/Eigentum", 2,
     "freiwillig", "100-300 EUR/Jahr", "versicherung", 1),
    (5, "Wohngebäude", "versicherung", "Wohngebäudeversicherung", "Nur für Eigentümer", 2,
     "freiwillig", "200-600 EUR/Jahr", "versicherung", 1),
    (6, "Streaming / Medien", "abo", "Abo-Dienst", "Nur bei regelmäßiger Nutzung", 3,
     "freiwillig", "5-20 EUR/Monat", "abo", 2),
    (7, "Software / Cloud", "abo", "SaaS-Abo", "Wenn regelmäßig genutzt", 3,
     "freiwillig", "5-50 EUR/Monat", "abo", 2),
]

DEFAULT_PATTERNS = [
    # Feste, hohe IDs vermeiden Kollisionen mit Legacy-Daten (z.B. abo_patterns.id=1).
    (9001, "Netflix", "Netflix", "Streaming / Medien", None, "abo", 2),
    (9002, "Spotify", "Spotify", "Streaming / Medien", None, "abo", 2),
    (9003, "Adobe", "Adobe", "Software / Cloud", None, "abo", 2),
    (9004, "Microsoft 365", "Microsoft", "Software / Cloud", None, "abo", 2),
    (9005, "Allianz", "Allianz", "Versicherung", None, "versicherung", 1),
    (9006, "HUK-COBURG", "HUK-COBURG", "Versicherung", None, "versicherung", 1),
]


class ContractCockpitHandler(BaseHandler):
    """Einheitlicher Handler für Abos und Versicherungen."""

    @property
    def profile_name(self) -> str:
        return "contract_cockpit"

    @property
    def target_file(self) -> Path:
        return Path(self._canonical_db)

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._canonical_db))
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return cur.fetchone() is not None

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(CREATE_TABLES)
            conn.executemany(
                """INSERT OR IGNORE INTO contract_types
                (id, name, category, description, when_useful, priority,
                 legal_requirement, typical_cost_range, applies_to, dist_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                DEFAULT_CONTRACT_TYPES,
            )
            conn.executemany(
                """INSERT OR IGNORE INTO contract_patterns
                (id, pattern, anbieter, kategorie, kuendigungslink, applies_to, dist_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                DEFAULT_PATTERNS,
            )
            conn.commit()

    def _get_arg(self, args: List[str], name: str, default: Any = None) -> Any:
        for arg in args:
            if arg.startswith(f"{name}="):
                value = arg[len(name) + 1 :]
                if value.lower() in ("true", "false"):
                    return value.lower() == "true"
                return value
        return default

    def _migrate_legacy(self) -> Dict[str, int]:
        self._init_db()
        stats = {
            "contracts_from_abo": 0,
            "contracts_from_insurance": 0,
            "payments": 0,
            "claims": 0,
            "types": 0,
            "patterns": 0,
        }
        with self._connection() as conn:
            # Abo-Abonnements
            if self._table_exists(conn, "abo_subscriptions"):
                rows = conn.execute(
                    """SELECT id, name, anbieter, kategorie, betrag_monatlich,
                    zahlungsintervall, kuendigungslink, erkannt_am,
                    bestaetigt, aktiv, created_at, updated_at FROM abo_subscriptions"""
                ).fetchall()
                for row in rows:
                    status = "aktiv"
                    if not row["aktiv"]:
                        status = "gekuendigt"
                    elif row["bestaetigt"]:
                        status = "aktiv"
                    else:
                        status = "erkannt"
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO contracts
                        (type, status, name, anbieter, vertragsnummer,
                         beginn_datum, ablauf_datum, kuendigungsfrist_monate,
                         verlaengerung_monate, naechste_kuendigung, kuendigungslink,
                         betrag_monatlich, zahlungsintervall, source_type, source_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            "abo",
                            status,
                            row["name"],
                            row["anbieter"],
                            None,
                            row["erkannt_am"],
                            None,
                            1,
                            12,
                            None,
                            row["kuendigungslink"],
                            row["betrag_monatlich"],
                            row["zahlungsintervall"] or "monatlich",
                            "abo_subscriptions",
                            row["id"],
                        ),
                    )
                    if cur.rowcount:
                        stats["contracts_from_abo"] += 1
                        new_id = cur.lastrowid
                        if row["betrag_monatlich"]:
                            conn.execute(
                                """INSERT INTO contract_payments
                                (contract_id, betrag, datum, posten_id)
                                VALUES (?, ?, ?, ?)""",
                                (new_id, row["betrag_monatlich"], row["erkannt_am"], None),
                            )
                            stats["payments"] += 1

            # Versicherungen
            if self._table_exists(conn, "fin_insurances"):
                rows = conn.execute(
                    """SELECT id, anbieter, tarif_name, police_nr, sparte, status,
                    beginn_datum, ablauf_datum, kuendigungsfrist_monate,
                    verlaengerung_monate, naechste_kuendigung, beitrag, zahlweise,
                    steuer_relevant_typ, ordner_pfad, notizen, created_at, updated_at
                    FROM fin_insurances"""
                ).fetchall()
                for row in rows:
                    status = (row["status"] or "aktiv").lower()
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO contracts
                        (type, status, name, anbieter, vertragsnummer,
                         beginn_datum, ablauf_datum, kuendigungsfrist_monate,
                         verlaengerung_monate, naechste_kuendigung, kuendigungslink,
                         betrag_monatlich, zahlungsintervall, steuer_relevant_typ,
                         ordner_pfad, notizen, source_type, source_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            "versicherung",
                            status,
                            row["tarif_name"],
                            row["anbieter"],
                            row["police_nr"],
                            row["beginn_datum"],
                            row["ablauf_datum"],
                            row["kuendigungsfrist_monate"] or 3,
                            row["verlaengerung_monate"] or 12,
                            row["naechste_kuendigung"],
                            None,
                            row["beitrag"],
                            row["zahlweise"] or "jährlich",
                            row["steuer_relevant_typ"],
                            row["ordner_pfad"],
                            row["notizen"],
                            "fin_insurances",
                            row["id"],
                        ),
                    )
                    if cur.rowcount:
                        stats["contracts_from_insurance"] += 1
                        new_id = cur.lastrowid
                        if row["beitrag"]:
                            conn.execute(
                                """INSERT INTO contract_payments
                                (contract_id, betrag, datum, posten_id)
                                VALUES (?, ?, ?, ?)""",
                                (new_id, row["beitrag"], row["beginn_datum"], None),
                            )
                            stats["payments"] += 1

            # Zahlungshistorie Abos
            if self._table_exists(conn, "abo_payments"):
                mapping = {
                    r["id"]: r["contract_id"]
                    for r in conn.execute(
                        """SELECT c.id, c.contract_id FROM (
                            SELECT id,
                                (SELECT id FROM contracts
                                 WHERE source_type='abo_subscriptions'
                                   AND source_id=abo_subscriptions.id) AS contract_id
                            FROM abo_subscriptions
                        ) c WHERE c.contract_id IS NOT NULL"""
                    ).fetchall()
                }
                for row in conn.execute(
                    "SELECT subscription_id, posten_id, betrag, datum FROM abo_payments"
                ).fetchall():
                    cid = mapping.get(row["subscription_id"])
                    if cid:
                        conn.execute(
                            """INSERT OR IGNORE INTO contract_payments
                            (contract_id, posten_id, betrag, datum)
                            VALUES (?, ?, ?, ?)""",
                            (cid, row["posten_id"], row["betrag"], row["datum"]),
                        )
                        if conn.total_changes:
                            stats["payments"] += 1

            # Schadensfälle
            if self._table_exists(conn, "fin_insurance_claims"):
                mapping = {
                    r["id"]: r["contract_id"]
                    for r in conn.execute(
                        """SELECT c.id, c.contract_id FROM (
                            SELECT id,
                                (SELECT id FROM contracts
                                 WHERE source_type='fin_insurances'
                                   AND source_id=fin_insurances.id) AS contract_id
                            FROM fin_insurances
                        ) c WHERE c.contract_id IS NOT NULL"""
                    ).fetchall()
                }
                for row in conn.execute(
                    """SELECT insurance_id, schadensdatum, beschreibung, status,
                    betrag_gefordert, betrag_gezahlt, aktenzeichen_versicherung
                    FROM fin_insurance_claims"""
                ).fetchall():
                    cid = mapping.get(row["insurance_id"])
                    if cid:
                        conn.execute(
                            """INSERT INTO contract_claims
                            (contract_id, schadensdatum, beschreibung, status,
                             betrag_gefordert, betrag_gezahlt,
                             aktenzeichen_versicherung, source_insurance_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                cid,
                                row["schadensdatum"],
                                row["beschreibung"],
                                row["status"],
                                row["betrag_gefordert"],
                                row["betrag_gezahlt"],
                                row["aktenzeichen_versicherung"],
                                row["insurance_id"],
                            ),
                        )
                        stats["claims"] += 1

            # Versicherungstypen
            if self._table_exists(conn, "insurance_types"):
                for row in conn.execute(
                    """SELECT id, name, category, description, when_useful, priority,
                    legal_requirement, typical_cost_range, dist_type, created_at
                    FROM insurance_types"""
                ).fetchall():
                    conn.execute(
                        """INSERT OR IGNORE INTO contract_types
                        (id, name, category, description, when_useful, priority,
                         legal_requirement, typical_cost_range, applies_to, dist_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["id"],
                            row["name"],
                            row["category"],
                            row["beschreibung"],
                            row["when_useful"],
                            row["priority"] or 3,
                            row["legal_requirement"],
                            row["typical_cost_range"],
                            "versicherung",
                            row["dist_type"] or 1,
                        ),
                    )
                    if conn.total_changes:
                        stats["types"] += 1

            # Finanz-Versicherungstypen
            if self._table_exists(conn, "fin_insurance_types"):
                for row in conn.execute(
                    """SELECT id, name, muster, typical_cost_range, dist_type
                    FROM fin_insurance_types"""
                ).fetchall():
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO contract_types
                        (id, name, typical_cost_range, applies_to, dist_type)
                        VALUES (?, ?, ?, ?, ?)""",
                        (
                            row["id"],
                            row["name"],
                            row["typical_cost_range"],
                            "versicherung",
                            row["dist_type"] or 1,
                        ),
                    )
                    if cur.rowcount:
                        stats["types"] += 1
                    if row["muster"]:
                        conn.execute(
                            """INSERT OR IGNORE INTO contract_patterns
                            (pattern, anbieter, applies_to, dist_type)
                            VALUES (?, ?, ?, ?)""",
                            (
                                row["muster"],
                                "",
                                "versicherung",
                                row["dist_type"] or 1,
                            ),
                        )
                        if conn.total_changes:
                            stats["patterns"] += 1

            # Abo-Muster
            if self._table_exists(conn, "abo_patterns"):
                for row in conn.execute(
                    """SELECT id, pattern, anbieter, kategorie,
                    kuendigungslink, dist_type FROM abo_patterns"""
                ).fetchall():
                    conn.execute(
                        """INSERT OR IGNORE INTO contract_patterns
                        (id, pattern, anbieter, kategorie, kuendigungslink,
                         applies_to, dist_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["id"],
                            row["pattern"],
                            row["anbieter"],
                            row["kategorie"],
                            row["kuendigungslink"],
                            "abo",
                            row["dist_type"] or 2,
                        ),
                    )
                    if conn.total_changes:
                        stats["patterns"] += 1

            conn.commit()
        return stats

    def _check_reminders(self, lookahead_days: int = 730) -> List[Dict[str, Any]]:
        heute = date.today()
        reminders: List[Dict[str, Any]] = []
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT id, name, anbieter, naechste_kuendigung, ablauf_datum,
                   beginn_datum, kuendigungsfrist_monate, verlaengerung_monate
                   FROM contracts
                   WHERE status IN ('aktiv', 'erkannt')"""
            ).fetchall()
            for row in rows:
                db_nk = row["naechste_kuendigung"]
                if db_nk:
                    effective_nk = db_nk
                    ablauf = row["ablauf_datum"]
                else:
                    effective_nk = _format_date(
                        calc_next_cancellation(
                            _parse_date(row["beginn_datum"]),
                            _parse_date(row["ablauf_datum"]),
                            row["kuendigungsfrist_monate"],
                            row["verlaengerung_monate"],
                            heute,
                        )
                    )
                    ablauf = None
                contract = {
                    "id": row["id"],
                    "name": row["name"],
                    "anbieter": row["anbieter"],
                    "naechste_kuendigung": effective_nk,
                    "ablauf_datum": ablauf,
                }
                reminders.extend(
                    sync_contract_reminders(
                        conn, contract, today=heute, lookahead_days=lookahead_days
                    )
                )
            conn.commit()
        return reminders

    def _recalc_cancellations(self) -> int:
        today = date.today()
        updated = 0
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT id, beginn_datum, ablauf_datum, kuendigungsfrist_monate,
                   verlaengerung_monate, naechste_kuendigung, status
                   FROM contracts
                   WHERE status IN ('aktiv', 'erkannt')"""
            ).fetchall()
            for row in rows:
                beginn = _parse_date(row["beginn_datum"])
                ablauf = _parse_date(row["ablauf_datum"])
                frist = row["kuendigungsfrist_monate"]
                verlaengerung = row["verlaengerung_monate"]
                calc = calc_next_cancellation(
                    beginn, ablauf, frist, verlaengerung, today
                )
                calc_str = _format_date(calc)
                if calc_str != row["naechste_kuendigung"]:
                    conn.execute(
                        """UPDATE contracts SET naechste_kuendigung=?, updated_at=?
                        WHERE id=?""",
                        (calc_str, _format_date(today), row["id"]),
                    )
                    updated += 1
            conn.commit()
        return updated

    def _list_contracts(
        self,
        contract_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM contracts WHERE 1=1"
        params: List[Any] = []
        if contract_type:
            query += " AND type=?"
            params.append(contract_type)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY naechste_kuendigung, name"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def _costs(self, contract_type: Optional[str] = None) -> Dict[str, Any]:
        query = """SELECT type, betrag_monatlich, zahlungsintervall,
                   status FROM contracts WHERE status='aktiv'"""
        params: List[Any] = []
        if contract_type:
            query += " AND type=?"
            params.append(contract_type)
        totals: Dict[str, float] = {}
        total_monthly = 0.0
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            for row in rows:
                monthly = calc_monthly(row["betrag_monatlich"], row["zahlungsintervall"])
                if monthly is None:
                    continue
                t = row["type"]
                totals[t] = totals.get(t, 0.0) + monthly
                total_monthly += monthly
        return {
            "monthly_by_type": totals,
            "total_monthly": round(total_monthly, 2),
            "total_yearly": round(total_monthly * 12.0, 2),
            "filter_type": contract_type,
        }

    def _export(self, fmt: str = "csv") -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = self.base_path / "data"
        out_dir.mkdir(parents=True, exist_ok=True)
        contracts = self._list_contracts()
        if fmt.lower() == "json":
            path = out_dir / f"contract_cockpit_{timestamp}.json"
            path.write_text(json.dumps(contracts, indent=2, default=str), encoding="utf-8")
        else:
            path = out_dir / f"contract_cockpit_{timestamp}.csv"
            if contracts:
                fieldnames = list(contracts[0].keys())
            else:
                fieldnames = [
                    "id", "type", "status", "name", "anbieter",
                    "beginn_datum", "naechste_kuendigung", "betrag_monatlich",
                ]
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(contracts)
        return path

    def _scan(self, text: Optional[str] = None) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        if text is None:
            return found
        with self._connection() as conn:
            patterns = conn.execute(
                "SELECT pattern, anbieter, kategorie, kuendigungslink, applies_to FROM contract_patterns"
            ).fetchall()
            for row in patterns:
                if re.search(row["pattern"], text, re.IGNORECASE):
                    contract_type = row["applies_to"] or "abo"
                    existing = conn.execute(
                        "SELECT id FROM contracts WHERE anbieter=? AND type=?",
                        (row["anbieter"], contract_type),
                    ).fetchone()
                    if existing:
                        continue
                    conn.execute(
                        """INSERT OR IGNORE INTO contracts
                        (type, status, name, anbieter, kuendigungslink,
                         kuendigungsfrist_monate, verlaengerung_monate)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            contract_type,
                            "erkannt",
                            row["kategorie"] or row["anbieter"],
                            row["anbieter"],
                            row["kuendigungslink"],
                            1 if contract_type == "abo" else 3,
                            12,
                        ),
                    )
                    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    found.append(
                        {
                            "id": new_id,
                            "type": contract_type,
                            "anbieter": row["anbieter"],
                            "pattern": row["pattern"],
                        }
                    )
            conn.commit()
        return found

    def _pending_reminders(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            return get_pending_reminders(conn)

    def get_operations(self) -> Dict[str, str]:
        return {
            "init": "Initialisiert das Cockpit (Tabellen + Defaults).",
            "migrate": "Migriert Abo- und Versicherungsdaten in contract_* Tabellen.",
            "list": "Listet Verträge auf (optional type=..., status=...).",
            "fristen": "Berechnet Kündigungsfristen und aktualisiert Erinnerungen.",
            "costs": "Berechnet monatliche/jährliche Kosten (optional type=...).",
            "export": "Exportiert Verträge als CSV/JSON (fmt=csv|json).",
            "scan": "Scannt einen Text nach bekannten Vertragsmustern (text=...).",
            "reminders": "Zeigt ausstehende Erinnerungen an.",
        }

    def handle(
        self, operation: str, args: List[str], dry_run: bool = False
    ) -> Tuple[bool, str]:
        try:
            if operation == "init":
                self._init_db()
                return True, json.dumps({"status": "initialized"}, ensure_ascii=False)

            if operation == "migrate":
                if dry_run:
                    return True, json.dumps({"dry_run": True}, ensure_ascii=False)
                stats = self._migrate_legacy()
                return True, json.dumps(stats, ensure_ascii=False)

            if operation == "list":
                ctype = self._get_arg(args, "type")
                status = self._get_arg(args, "status")
                data = self._list_contracts(ctype, status)
                return True, json.dumps(data, ensure_ascii=False, default=str)

            if operation == "fristen":
                reminders = self._check_reminders()
                updated = self._recalc_cancellations()
                return True, json.dumps(
                    {"updated": updated, "reminders_added": len(reminders)},
                    ensure_ascii=False,
                )

            if operation == "costs":
                ctype = self._get_arg(args, "type")
                return True, json.dumps(self._costs(ctype), ensure_ascii=False)

            if operation == "export":
                fmt = self._get_arg(args, "fmt", "csv")
                path = self._export(fmt)
                return True, json.dumps({"path": str(path)}, ensure_ascii=False)

            if operation == "scan":
                text = self._get_arg(args, "text", "")
                found = self._scan(text)
                return True, json.dumps({"found": found}, ensure_ascii=False)

            if operation == "reminders":
                data = self._pending_reminders()
                return True, json.dumps(data, ensure_ascii=False, default=str)

            return False, json.dumps(
                {"error": f"Unbekannte Operation: {operation}"},
                ensure_ascii=False,
            )
        except Exception as exc:  # pragma: no cover
            return False, json.dumps(
                {"error": str(exc), "operation": operation},
                ensure_ascii=False,
            )


# Convenience-Funktion für direkte Aufrufe.
def main() -> None:  # pragma: no cover
    import sys

    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "Keine Operation angegeben"}))
        return
    operation = args[0]
    handler_args = args[1:]
    # Einfache Heuristik: erster positionaler Parameter als base_path,
    # alles danach als handler-args, wenn es ein Pfad ist.
    base = Path.cwd()
    if handler_args and not handler_args[0].startswith("type="):
        candidate = Path(handler_args[0])
        if candidate.exists():
            base = candidate
            handler_args = handler_args[1:]
    handler = ContractCockpitHandler(base)
    success, message = handler.handle(operation, handler_args)
    print(message)
    if not success:
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
