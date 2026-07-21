#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fahrtenbuch Metriken - Erweiterte Delegation-Metriken
=====================================================

Erfasst erweiterte Metriken pro Delegation:
- Latenz (Dauer der Delegation)
- Erfolgsrate (pro Provider und StreckenTyp)
- Gang-Wahl (welches Modell für welche Strecke)
- Gas-Stellung (Reasoning-Level)
- Strecken-Typ (aus StreckenAnalyse)

Speicherung: Separates clutch_fahrtenbuch in bach.db
(eigene Tabelle, JOIN per View möglich).

Einhängepunkte: tokens.py, meta_feedback_injector.py

Teil der clutch-bridge (BACH Task [1079]).
"""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FahrtenbuchEintrag:
    """Ein einzelner Eintrag im Fahrtenbuch."""
    timestamp: float
    task_text: str
    provider: str
    model: str
    strecken_typ: str
    strecken_typ_code: int
    schwierigkeit: int
    etappen: int
    gas_level: int
    gas_strategie: str
    token_budget_faktor: float
    tokens_input: int
    tokens_output: int
    latenz_sekunden: float
    erfolg: bool
    zone: int
    kosten_eur: float


class Fahrtenbuch:
    """Erweiterte Delegation-Metriken für clutch-bridge."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path
        self._entries: List[FahrtenbuchEintrag] = []
        if db_path:
            self._init_db()

    def _init_db(self) -> None:
        """Erstellt Fahrtenbuch-Tabelle falls nicht vorhanden."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clutch_fahrtenbuch (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    task_text TEXT,
                    provider TEXT,
                    model TEXT,
                    strecken_typ TEXT,
                    strecken_typ_code INTEGER,
                    schwierigkeit INTEGER,
                    etappen INTEGER,
                    gas_level INTEGER,
                    gas_strategie TEXT,
                    token_budget_faktor REAL,
                    tokens_input INTEGER DEFAULT 0,
                    tokens_output INTEGER DEFAULT 0,
                    latenz_sekunden REAL DEFAULT 0,
                    erfolg INTEGER DEFAULT 1,
                    zone INTEGER DEFAULT 1,
                    kosten_eur REAL DEFAULT 0
                )
            """)
            # Index für häufige Abfragen
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fahrtenbuch_provider
                ON clutch_fahrtenbuch(provider)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fahrtenbuch_strecke
                ON clutch_fahrtenbuch(strecken_typ_code)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fahrtenbuch_time
                ON clutch_fahrtenbuch(timestamp)
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ─── Einträge schreiben ─────────────────────────────────────

    def eintrag(
        self,
        task_text: str,
        provider: str,
        model: str = "",
        strecken_typ: str = "",
        strecken_typ_code: int = 0,
        schwierigkeit: int = 0,
        etappen: int = 0,
        gas_level: int = 50,
        gas_strategie: str = "ausgewogen",
        token_budget_faktor: float = 1.0,
        tokens_input: int = 0,
        tokens_output: int = 0,
        latenz_sekunden: float = 0.0,
        erfolg: bool = True,
        zone: int = 1,
        kosten_eur: float = 0.0,
    ) -> FahrtenbuchEintrag:
        """Schreibt einen neuen Eintrag ins Fahrtenbuch."""
        entry = FahrtenbuchEintrag(
            timestamp=time.time(),
            task_text=task_text[:200],  # Auf 200 Zeichen begrenzen
            provider=provider,
            model=model,
            strecken_typ=strecken_typ,
            strecken_typ_code=strecken_typ_code,
            schwierigkeit=schwierigkeit,
            etappen=etappen,
            gas_level=gas_level,
            gas_strategie=gas_strategie,
            token_budget_faktor=token_budget_faktor,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latenz_sekunden=latenz_sekunden,
            erfolg=erfolg,
            zone=zone,
            kosten_eur=kosten_eur,
        )

        self._entries.append(entry)

        if self._db_path:
            self._persist(entry)

        return entry

    def _persist(self, entry: FahrtenbuchEintrag) -> None:
        """Speichert Eintrag in DB."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("""
                INSERT INTO clutch_fahrtenbuch
                    (timestamp, task_text, provider, model,
                     strecken_typ, strecken_typ_code, schwierigkeit, etappen,
                     gas_level, gas_strategie, token_budget_faktor,
                     tokens_input, tokens_output, latenz_sekunden,
                     erfolg, zone, kosten_eur)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.timestamp, entry.task_text, entry.provider, entry.model,
                entry.strecken_typ, entry.strecken_typ_code,
                entry.schwierigkeit, entry.etappen,
                entry.gas_level, entry.gas_strategie, entry.token_budget_faktor,
                entry.tokens_input, entry.tokens_output, entry.latenz_sekunden,
                1 if entry.erfolg else 0, entry.zone, entry.kosten_eur,
            ))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ─── Abfragen ───────────────────────────────────────────────

    def metriken(self, tage: int = 7) -> dict:
        """Gibt aggregierte Metriken der letzten N Tage zurück."""
        if self._db_path and self._db_path.exists():
            return self._metriken_from_db(tage)
        return self._metriken_from_memory(tage)

    def _metriken_from_db(self, tage: int) -> dict:
        """Metriken aus DB."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            since = time.time() - (tage * 86400)

            # Gesamt
            row = conn.execute("""
                SELECT COUNT(*), SUM(erfolg), AVG(latenz_sekunden),
                       SUM(tokens_input + tokens_output), SUM(kosten_eur)
                FROM clutch_fahrtenbuch WHERE timestamp > ?
            """, (since,)).fetchone()

            total = row[0] or 0
            successful = row[1] or 0
            avg_latenz = row[2] or 0
            total_tokens = row[3] or 0
            total_kosten = row[4] or 0

            # Pro Provider
            provider_rows = conn.execute("""
                SELECT provider, COUNT(*), SUM(erfolg), AVG(latenz_sekunden)
                FROM clutch_fahrtenbuch WHERE timestamp > ?
                GROUP BY provider ORDER BY COUNT(*) DESC
            """, (since,)).fetchall()

            # Pro Streckentyp
            strecken_rows = conn.execute("""
                SELECT strecken_typ, strecken_typ_code, COUNT(*),
                       SUM(erfolg), AVG(gas_level)
                FROM clutch_fahrtenbuch WHERE timestamp > ?
                GROUP BY strecken_typ_code ORDER BY COUNT(*) DESC
            """, (since,)).fetchall()

            # Gas-Verteilung
            gas_rows = conn.execute("""
                SELECT gas_strategie, COUNT(*)
                FROM clutch_fahrtenbuch WHERE timestamp > ?
                GROUP BY gas_strategie
            """, (since,)).fetchall()

            conn.close()

            return {
                "zeitraum_tage": tage,
                "total_delegations": total,
                "erfolgsrate": round(successful / max(1, total) * 100, 1),
                "avg_latenz": round(avg_latenz, 2),
                "total_tokens": total_tokens,
                "total_kosten_eur": round(total_kosten, 2),
                "provider": [
                    {
                        "name": r[0],
                        "delegations": r[1],
                        "erfolgsrate": round((r[2] or 0) / max(1, r[1]) * 100, 1),
                        "avg_latenz": round(r[3] or 0, 2),
                    }
                    for r in provider_rows
                ],
                "streckentypen": [
                    {
                        "typ": r[0],
                        "code": r[1],
                        "delegations": r[2],
                        "erfolgsrate": round((r[3] or 0) / max(1, r[2]) * 100, 1),
                        "avg_gas": round(r[4] or 0, 0),
                    }
                    for r in strecken_rows
                ],
                "gas_verteilung": {r[0]: r[1] for r in gas_rows},
            }
        except Exception:
            return {"error": "DB-Abfrage fehlgeschlagen"}

    def _metriken_from_memory(self, tage: int) -> dict:
        """Metriken aus In-Memory-Einträgen."""
        since = time.time() - (tage * 86400)
        recent = [e for e in self._entries if e.timestamp > since]

        total = len(recent)
        successful = sum(1 for e in recent if e.erfolg)

        return {
            "zeitraum_tage": tage,
            "total_delegations": total,
            "erfolgsrate": round(successful / max(1, total) * 100, 1),
            "source": "memory",
        }

    def format_metriken(self, tage: int = 7) -> str:
        """Gibt formatierten Metriken-String zurück."""
        m = self.metriken(tage)
        lines = [
            f"[FAHRTENBUCH] Metriken (letzte {tage} Tage)",
            "=" * 50,
            f"  Delegations: {m['total_delegations']}",
            f"  Erfolgsrate: {m['erfolgsrate']}%",
        ]

        if "avg_latenz" in m:
            lines.append(f"  Ø Latenz: {m['avg_latenz']}s")
            lines.append(f"  Tokens gesamt: {m.get('total_tokens', 0):,}")
            lines.append(f"  Kosten: {m.get('total_kosten_eur', 0):.2f} EUR")

        if "provider" in m and m["provider"]:
            lines.append("\n  Provider:")
            for p in m["provider"]:
                lines.append(
                    f"    {p['name']}: {p['delegations']}x, "
                    f"{p['erfolgsrate']}% Erfolg, "
                    f"Ø {p['avg_latenz']}s"
                )

        if "streckentypen" in m and m["streckentypen"]:
            lines.append("\n  Streckentypen:")
            for s in m["streckentypen"]:
                lines.append(
                    f"    {s['typ']} (Typ {s['code']}): {s['delegations']}x, "
                    f"{s['erfolgsrate']}% Erfolg, "
                    f"Ø Gas {s['avg_gas']}%"
                )

        if "gas_verteilung" in m and m["gas_verteilung"]:
            lines.append("\n  Gas-Verteilung:")
            for strategie, count in m["gas_verteilung"].items():
                lines.append(f"    {strategie}: {count}x")

        return "\n".join(lines)


# ─── Singleton ──────────────────────────────────────────────────────

_instance: Optional[Fahrtenbuch] = None


def get_fahrtenbuch(db_path: Optional[Path] = None) -> Fahrtenbuch:
    """Gibt Singleton-Instanz zurück."""
    global _instance
    if _instance is None:
        _instance = Fahrtenbuch(db_path=db_path)
    return _instance
