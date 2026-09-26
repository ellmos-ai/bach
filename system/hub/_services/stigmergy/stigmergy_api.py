"""
stigmergy_api.py — Pheromon-basierte Schwarm-Koordination

Stigmergy: Agenten kommunizieren indirekt ueber Markierungen in der Umgebung,
aehnlich wie Ameisen Pheromone hinterlassen.

BACH-Implementierung: memory_working (ab Migration 043, sonst shared_memory_working) als Pheromon-Traeger
Namespace: 'stigmergy' (gespeichert via tags + related_to)

Mapping auf memory_working-Spalten:
    type      = 'note'
    content   = JSON: {namespace, path_id, strength, metadata, agent_id, timestamp}
    tags      = '["stigmergy"]'
    related_to = path_id (fuer schnelles Filtern)
    priority  = int(strength * 10)  (0-10 Skala)
    agent_id  = Agent der das Pheromon hinterlassen hat

Stand: 2026-02-22 | Bezug: MASTERPLAN SQ051
Implementierung: 2026-03-01
"""
from __future__ import annotations
from typing import Optional
import sqlite3
import json
from datetime import datetime


class StigmergyAPI:
    """
    Pheromon-basierte Koordination fuer BACH-Schwarm-Agenten.

    Agenten hinterlassen 'Pheromone' (Markierungen) in memory_working (vor Migration 043: shared_memory_working).
    Andere Agenten lesen diese und waehlen vielversprechende Pfade.

    Konzept aus vernunft_kantian.txt (V009: Self-Extension, Autonomie):
    Ein System das sich selbst koordinieren kann, braucht keine zentrale Steuerung.

    Tabellen-Mapping (memory_working):
        type       = 'note'
        content    = JSON mit {namespace, path_id, strength, metadata, agent_id, timestamp}
        tags       = '["stigmergy"]'
        related_to = path_id
        priority   = int(strength * 10)
    """

    NAMESPACE = 'stigmergy'
    LEGACY_TABLE = 'shared_memory_working'

    def __init__(self, db_path: str, agent_id: str = 'anonymous'):
        self.db_path = db_path
        self.agent_id = agent_id
        self.TABLE = self._resolve_table()

    def _resolve_table(self) -> str:
        """memory_working traegt ab BACH-Migration 043 (gemeinsames Gedaechtnis,
        T-20260920-823767362) agent_id/session_id/related_to; davor bleibt es
        bei der eingefrorenen Gen-2-Tabelle."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_working)")}
            finally:
                conn.close()
        except sqlite3.Error:
            return self.LEGACY_TABLE
        return 'memory_working' if {'agent_id', 'session_id', 'related_to'} <= cols else self.LEGACY_TABLE

    def _connect(self) -> sqlite3.Connection:
        """Erstelle eine DB-Verbindung mit Row-Factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _make_content(self, path_id: str, strength: float,
                      metadata: dict | None) -> str:
        """Baue den JSON-Content-String fuer ein Pheromon."""
        return json.dumps({
            'namespace': self.NAMESPACE,
            'path_id': path_id,
            'strength': strength,
            'metadata': metadata or {},
            'agent_id': self.agent_id,
            'timestamp': datetime.now().isoformat(),
        }, ensure_ascii=False)

    def _parse_content(self, content_str: str) -> dict | None:
        """Parse den JSON-Content eines Pheromons. None bei Fehler."""
        try:
            data = json.loads(content_str)
            if data.get('namespace') == self.NAMESPACE:
                return data
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return None

    def deposit(self, path_id: str, strength: float = 1.0, metadata: dict = None) -> bool:
        """
        Hinterlasse ein Pheromon auf einem Pfad.

        Args:
            path_id: Identifier des Pfads/der Aufgabe (z.B. 'approach_A', 'module_xyz')
            strength: Pheromon-Staerke (0.0 - 1.0), hoeher = vielversprechender
            metadata: Zusaetzliche Infos (Ergebnis, Bewertung, Kontext)

        Returns:
            True bei Erfolg, False bei Fehler

        SQL-Strategie:
            Pruefen ob bereits ein aktives Pheromon fuer diesen path_id existiert.
            Falls ja: UPDATE (Staerke + Metadata aktualisieren)
            Falls nein: INSERT neuen Eintrag
        """
        try:
            strength = max(0.0, min(1.0, strength))
            content_json = self._make_content(path_id, strength, metadata)
            priority = int(strength * 10)
            now = datetime.now().isoformat()
            tags_json = json.dumps([self.NAMESPACE])

            conn = self._connect()
            try:
                # Pruefen ob schon ein aktives Stigmergy-Pheromon fuer diesen path_id existiert
                cursor = conn.execute(f"""
                    SELECT id FROM {self.TABLE}
                    WHERE type = 'note'
                      AND is_active = 1
                      AND tags = ?
                      AND related_to = ?
                """, (tags_json, path_id))
                existing = cursor.fetchone()

                if existing:
                    # Update: Staerke und Metadata aktualisieren
                    conn.execute(f"""
                        UPDATE {self.TABLE}
                        SET content = ?, priority = ?, agent_id = ?, updated_at = ?
                        WHERE id = ?
                    """, (content_json, priority, self.agent_id, now, existing['id']))
                else:
                    # Insert: Neues Pheromon anlegen
                    conn.execute(f"""
                        INSERT INTO {self.TABLE}
                        (agent_id, session_id, type, content, priority,
                         is_active, created_at, updated_at, tags, related_to)
                        VALUES (?, NULL, 'note', ?, ?, 1, ?, ?, ?, ?)
                    """, (self.agent_id, content_json, priority,
                          now, now, tags_json, path_id))

                conn.commit()
                return True
            finally:
                conn.close()

        except Exception:
            return False

    def sense(self, path_prefix: str = '') -> list[dict]:
        """
        Lese alle Pheromone (welche Pfade sind vielversprechend?).

        Args:
            path_prefix: Optional Filter fuer Pfad-IDs (z.B. 'approach_')

        Returns:
            Liste von {path_id, strength, agent_id, metadata, timestamp},
            sortiert nach strength DESC

        SQL:
            SELECT content, created_at FROM memory_working
            WHERE type='note' AND is_active=1 AND tags='["stigmergy"]'
              AND related_to LIKE path_prefix || '%'
            ORDER BY priority DESC, updated_at DESC
        """
        try:
            tags_json = json.dumps([self.NAMESPACE])
            like_pattern = f"{path_prefix}%"

            conn = self._connect()
            try:
                cursor = conn.execute(f"""
                    SELECT content, created_at, updated_at
                    FROM {self.TABLE}
                    WHERE type = 'note'
                      AND is_active = 1
                      AND tags = ?
                      AND related_to LIKE ?
                    ORDER BY priority DESC, updated_at DESC
                """, (tags_json, like_pattern))

                results = []
                for row in cursor.fetchall():
                    data = self._parse_content(row['content'])
                    if data:
                        results.append({
                            'path_id': data['path_id'],
                            'strength': data['strength'],
                            'agent_id': data['agent_id'],
                            'metadata': data.get('metadata', {}),
                            'timestamp': data.get('timestamp', row['created_at']),
                        })
                return results
            finally:
                conn.close()

        except Exception:
            return []

    def evaporate(self, decay_rate: float = 0.1) -> int:
        """
        Verdunste schwache Pheromone (Aufraeumen).

        Inspiriert von Ameisen-Algorithmen: Pheromone verdunsten mit der Zeit,
        nur regelmaessig genutzte Pfade bleiben stark.

        Args:
            decay_rate: Anteil der zu loeschenden schwachen Pheromone (0.0 - 1.0)
                        0.1 = loeschung der schwachsten 10% der Pheromone

        Returns:
            Anzahl geloeschter Pheromone (deaktiviert via is_active=0)

        Strategie:
            1. Alle Stigmergy-Eintraege zaehlen
            2. Unterste X% nach priority ermitteln
            3. Diese via is_active=0 deaktivieren
        """
        try:
            decay_rate = max(0.0, min(1.0, decay_rate))
            tags_json = json.dumps([self.NAMESPACE])
            now = datetime.now().isoformat()

            conn = self._connect()
            try:
                # Gesamtzahl aktiver Stigmergy-Pheromone
                cursor = conn.execute(f"""
                    SELECT COUNT(*) as cnt FROM {self.TABLE}
                    WHERE type = 'note' AND is_active = 1 AND tags = ?
                """, (tags_json,))
                total = cursor.fetchone()['cnt']

                if total == 0:
                    return 0

                # Anzahl zu loeschender Eintraege (mindestens 1 wenn decay_rate > 0)
                to_delete = max(1, int(total * decay_rate))

                # IDs der schwachsten Pheromone ermitteln (niedrigste priority zuerst)
                cursor = conn.execute(f"""
                    SELECT id FROM {self.TABLE}
                    WHERE type = 'note' AND is_active = 1 AND tags = ?
                    ORDER BY priority ASC, updated_at ASC
                    LIMIT ?
                """, (tags_json, to_delete))
                ids_to_deactivate = [row['id'] for row in cursor.fetchall()]

                if not ids_to_deactivate:
                    return 0

                # Deaktivieren statt Loeschen (sichereres Pattern)
                placeholders = ','.join('?' for _ in ids_to_deactivate)
                conn.execute(f"""
                    UPDATE {self.TABLE}
                    SET is_active = 0, updated_at = ?
                    WHERE id IN ({placeholders})
                """, [now] + ids_to_deactivate)
                conn.commit()

                return len(ids_to_deactivate)
            finally:
                conn.close()

        except Exception:
            return 0

    def get_best_path(self, path_prefix: str = '') -> Optional[str]:
        """
        Gibt den Pfad mit dem staerksten Pheromon zurueck.

        Kurzform fuer: sense()[0]['path_id'] falls Pheromone vorhanden.

        Args:
            path_prefix: Optional Filter

        Returns:
            path_id des besten Pfads, oder None wenn keine Pheromone
        """
        try:
            results = self.sense(path_prefix)
            if results:
                return results[0]['path_id']
            return None
        except Exception:
            return None

    def dump(self) -> dict:
        """
        Debug: Zeige alle Pheromone als dict.

        Returns:
            {path_id: {strength, agent_id, metadata, timestamp}, ...}
        """
        try:
            all_pheromones = self.sense()
            return {
                p['path_id']: {
                    'strength': p['strength'],
                    'agent_id': p['agent_id'],
                    'metadata': p.get('metadata', {}),
                    'timestamp': p['timestamp'],
                }
                for p in all_pheromones
            }
        except Exception:
            return {}


# ============================================================
# Convenience-Funktionen (Kurz-API fuer haeufige Use-Cases)
# ============================================================

def deposit_pheromone(
    db_path: str,
    agent_id: str,
    path_id: str,
    strength: float = 1.0,
    metadata: dict = None
) -> bool:
    """
    Kurz-API: Pheromon hinterlassen ohne Instanz zu erstellen.

    Beispiel:
        deposit_pheromone('data/bach.db', 'agent_A', 'approach_refactor', 0.9,
                          {'result': 'success', 'time_ms': 450})
    """
    api = StigmergyAPI(db_path, agent_id)
    return api.deposit(path_id, strength, metadata)


def sense_pheromones(db_path: str, path_prefix: str = '') -> list[dict]:
    """
    Kurz-API: Alle Pheromone lesen ohne Instanz zu erstellen.

    Beispiel:
        paths = sense_pheromones('data/bach.db', 'approach_')
        best = paths[0] if paths else None
    """
    api = StigmergyAPI(db_path)
    return api.sense(path_prefix)


def get_best_pheromone_path(db_path: str, path_prefix: str = '') -> Optional[str]:
    """
    Kurz-API: Besten Pfad bestimmen.

    Typischer Schwarm-Workflow:
        1. Agent A: deposit_pheromone(db, 'A', 'approach_1', 0.8)
        2. Agent B: deposit_pheromone(db, 'B', 'approach_2', 0.6)
        3. Agent C: best = get_best_pheromone_path(db)  # -> 'approach_1'
        4. Agent C: folgt approach_1
    """
    api = StigmergyAPI(db_path)
    return api.get_best_path(path_prefix)
