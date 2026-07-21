#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fahrschule Lern-Loop - Fitness-Scoring für Model x Task
========================================================

Lernt über Zeit welche Modell-Kombinationen für welche Tasks
am besten funktionieren:
- Fitness-Scoring für Model x Task-Typ Kombinationen
- Epsilon-Greedy Exploration (10% alternative Kombination testen)
- Policy-Updates nach N Delegations

Einhängepunkte: partner.py, consolidation.py, monitor_success

Teil der clutch-bridge (BACH Task [1076]).
"""

import json
import random
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class FitnessRecord:
    """Fitness-Wert für eine Model x StreckenTyp Kombination."""
    model: str
    strecken_typ: int
    fitness: float          # 0.0 - 1.0
    total_delegations: int
    successful: int
    avg_tokens: float
    avg_latency: float      # Sekunden
    last_updated: float

    def success_rate(self) -> float:
        if self.total_delegations == 0:
            return 0.0
        return self.successful / self.total_delegations


@dataclass
class PolicyRecommendation:
    """Empfehlung der Fahrschule für eine Delegation."""
    recommended_model: str
    fitness: float
    is_exploration: bool    # True = Epsilon-Greedy Exploration
    reason: str
    alternatives: List[Dict]


class FahrschuleLernLoop:
    """Lern-Loop für Model x Task-Typ Optimierung."""

    EPSILON = 0.10          # 10% Exploration-Rate
    POLICY_UPDATE_INTERVAL = 10  # Policy-Update nach N Delegations
    INITIAL_FITNESS = 0.5   # Startwert für unbekannte Kombinationen
    LEARNING_RATE = 0.1     # Wie schnell sich Fitness ändert

    def __init__(self, db_path: Optional[Path] = None):
        self._fitness_table: Dict[str, FitnessRecord] = {}
        self._delegation_count = 0
        self._db_path = db_path

        # Aus DB laden falls verfügbar
        if db_path and db_path.exists():
            self._load_from_db()

    def _key(self, model: str, strecken_typ: int) -> str:
        return f"{model}:{strecken_typ}"

    # ─── Kernlogik ──────────────────────────────────────────────

    def empfehle(
        self,
        strecken_typ: int,
        verfuegbare_modelle: List[str],
        default_model: str = "sonnet",
    ) -> PolicyRecommendation:
        """
        Empfiehlt ein Modell für einen Streckentyp.
        Nutzt Epsilon-Greedy: 90% bestes Modell, 10% zufällig.

        Args:
            strecken_typ: StreckenAnalyse Typ-Code (1-10)
            verfuegbare_modelle: Liste verfügbarer Modelle
            default_model: Fallback wenn keine Daten vorhanden

        Returns:
            PolicyRecommendation
        """
        if not verfuegbare_modelle:
            return PolicyRecommendation(
                recommended_model=default_model,
                fitness=self.INITIAL_FITNESS,
                is_exploration=False,
                reason="Keine verfügbaren Modelle",
                alternatives=[],
            )

        # Fitness für alle verfügbaren Modelle laden
        model_fitness = []
        for model in verfuegbare_modelle:
            key = self._key(model, strecken_typ)
            record = self._fitness_table.get(key)
            if record:
                model_fitness.append((model, record.fitness))
            else:
                model_fitness.append((model, self.INITIAL_FITNESS))

        # Sortieren nach Fitness (höchste zuerst)
        model_fitness.sort(key=lambda x: x[1], reverse=True)

        # Epsilon-Greedy
        is_exploration = random.random() < self.EPSILON
        if is_exploration and len(model_fitness) > 1:
            # Zufälliges nicht-bestes Modell wählen
            alternatives = model_fitness[1:]
            chosen = random.choice(alternatives)
            reason = f"Exploration (ε={self.EPSILON}): Teste Alternative"
        else:
            chosen = model_fitness[0]
            is_exploration = False
            reason = f"Beste Fitness: {chosen[1]:.2f}"

        return PolicyRecommendation(
            recommended_model=chosen[0],
            fitness=chosen[1],
            is_exploration=is_exploration,
            reason=reason,
            alternatives=[
                {"model": m, "fitness": round(f, 3)}
                for m, f in model_fitness if m != chosen[0]
            ],
        )

    def record_ergebnis(
        self,
        model: str,
        strecken_typ: int,
        erfolg: bool,
        tokens_used: int = 0,
        latency: float = 0.0,
    ) -> float:
        """
        Registriert das Ergebnis einer Delegation und aktualisiert Fitness.

        Args:
            model: Verwendetes Modell
            strecken_typ: StreckenAnalyse Typ-Code
            erfolg: True wenn Task erfolgreich
            tokens_used: Verbrauchte Tokens
            latency: Dauer in Sekunden

        Returns:
            Neue Fitness nach Update
        """
        key = self._key(model, strecken_typ)

        if key not in self._fitness_table:
            self._fitness_table[key] = FitnessRecord(
                model=model,
                strecken_typ=strecken_typ,
                fitness=self.INITIAL_FITNESS,
                total_delegations=0,
                successful=0,
                avg_tokens=0.0,
                avg_latency=0.0,
                last_updated=time.time(),
            )

        record = self._fitness_table[key]
        record.total_delegations += 1
        if erfolg:
            record.successful += 1

        # Exponential Moving Average für Fitness
        reward = 1.0 if erfolg else 0.0
        record.fitness = (
            record.fitness * (1 - self.LEARNING_RATE)
            + reward * self.LEARNING_RATE
        )

        # Token/Latenz-Tracking (EMA)
        if tokens_used > 0:
            if record.avg_tokens == 0:
                record.avg_tokens = float(tokens_used)
            else:
                record.avg_tokens = record.avg_tokens * 0.8 + tokens_used * 0.2

        if latency > 0:
            if record.avg_latency == 0:
                record.avg_latency = latency
            else:
                record.avg_latency = record.avg_latency * 0.8 + latency * 0.2

        record.last_updated = time.time()

        # Policy-Update prüfen
        self._delegation_count += 1
        if self._delegation_count % self.POLICY_UPDATE_INTERVAL == 0:
            self._policy_update()

        # In DB persistieren
        if self._db_path:
            self._save_record(record)

        return record.fitness

    def _policy_update(self) -> None:
        """Periodisches Policy-Update: Alte Einträge abwerten."""
        now = time.time()
        for key, record in self._fitness_table.items():
            age_days = (now - record.last_updated) / 86400
            if age_days > 7:
                # Fitness leicht Richtung Initial driften lassen
                record.fitness = (
                    record.fitness * 0.95 + self.INITIAL_FITNESS * 0.05
                )

    # ─── Persistenz ─────────────────────────────────────────────

    def _load_from_db(self) -> None:
        """Lädt Fitness-Daten aus der DB."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clutch_fitness (
                    model TEXT,
                    strecken_typ INTEGER,
                    fitness REAL DEFAULT 0.5,
                    total_delegations INTEGER DEFAULT 0,
                    successful INTEGER DEFAULT 0,
                    avg_tokens REAL DEFAULT 0,
                    avg_latency REAL DEFAULT 0,
                    last_updated REAL,
                    PRIMARY KEY (model, strecken_typ)
                )
            """)
            cursor = conn.execute("SELECT * FROM clutch_fitness")
            for row in cursor:
                record = FitnessRecord(
                    model=row[0],
                    strecken_typ=row[1],
                    fitness=row[2],
                    total_delegations=row[3],
                    successful=row[4],
                    avg_tokens=row[5],
                    avg_latency=row[6],
                    last_updated=row[7] or time.time(),
                )
                self._fitness_table[self._key(record.model, record.strecken_typ)] = record
            conn.close()
        except Exception:
            pass

    def _save_record(self, record: FitnessRecord) -> None:
        """Speichert einzelnen Record in die DB."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clutch_fitness (
                    model TEXT,
                    strecken_typ INTEGER,
                    fitness REAL DEFAULT 0.5,
                    total_delegations INTEGER DEFAULT 0,
                    successful INTEGER DEFAULT 0,
                    avg_tokens REAL DEFAULT 0,
                    avg_latency REAL DEFAULT 0,
                    last_updated REAL,
                    PRIMARY KEY (model, strecken_typ)
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO clutch_fitness
                    (model, strecken_typ, fitness, total_delegations,
                     successful, avg_tokens, avg_latency, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.model, record.strecken_typ, record.fitness,
                record.total_delegations, record.successful,
                record.avg_tokens, record.avg_latency, record.last_updated,
            ))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ─── Status ─────────────────────────────────────────────────

    def status(self) -> dict:
        """Gibt Fahrschule-Status zurück."""
        records = sorted(
            self._fitness_table.values(),
            key=lambda r: r.fitness,
            reverse=True,
        )
        return {
            "total_kombinationen": len(records),
            "total_delegations": self._delegation_count,
            "epsilon": self.EPSILON,
            "policy_update_interval": self.POLICY_UPDATE_INTERVAL,
            "top_5": [
                {
                    "model": r.model,
                    "strecken_typ": r.strecken_typ,
                    "fitness": round(r.fitness, 3),
                    "success_rate": round(r.success_rate() * 100, 1),
                    "delegations": r.total_delegations,
                }
                for r in records[:5]
            ],
            "bottom_5": [
                {
                    "model": r.model,
                    "strecken_typ": r.strecken_typ,
                    "fitness": round(r.fitness, 3),
                    "success_rate": round(r.success_rate() * 100, 1),
                    "delegations": r.total_delegations,
                }
                for r in records[-5:] if records
            ],
        }

    def format_status(self) -> str:
        """Gibt formatierten Status zurück."""
        s = self.status()
        lines = [
            "[FAHRSCHULE] Lern-Loop Status",
            "=" * 50,
            f"  Kombinationen: {s['total_kombinationen']}",
            f"  Delegations: {s['total_delegations']}",
            f"  Epsilon: {s['epsilon']}",
        ]
        if s["top_5"]:
            lines.append("\n  Top-Kombinationen:")
            for r in s["top_5"]:
                lines.append(
                    f"    {r['model']}×Typ{r['strecken_typ']}: "
                    f"Fitness {r['fitness']}, "
                    f"Erfolg {r['success_rate']}% "
                    f"({r['delegations']} Runs)"
                )
        return "\n".join(lines)


# ─── Singleton ──────────────────────────────────────────────────────

_instance: Optional[FahrschuleLernLoop] = None


def get_fahrschule(db_path: Optional[Path] = None) -> FahrschuleLernLoop:
    """Gibt Singleton-Instanz zurück."""
    global _instance
    if _instance is None:
        _instance = FahrschuleLernLoop(db_path=db_path)
    return _instance
