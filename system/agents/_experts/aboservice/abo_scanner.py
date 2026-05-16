# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Abo-Scanner - Erkennt wiederkehrende Zahlungen aus Steuer-Posten
================================================================

Analysiert steuer_posten und identifiziert potenzielle Abonnements
basierend auf:
- Wiederholte Zahlungen an gleichen Anbieter
- Konstante Betraege
- Bekannte Abo-Anbieter-Patterns
"""
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from statistics import stdev, mean, StatisticsError


class AboScanner:
    """Scannt Steuer-Posten nach Abonnements."""

    # Mindest-Score fuer Abo-Erkennung
    SCORE_THRESHOLD = 50

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def scan(self, username: str, steuerjahr: int, dry_run: bool = False) -> Dict:
        """
        Hauptmethode: Scannt Posten und erkennt Abos.

        Returns:
            Dict mit Statistiken und Erkennungen
        """
        result = {
            "posten_analysiert": 0,
            "abos_erkannt": 0,
            "abos_neu": 0,
            "abos_aktualisiert": 0,
            "erkennungen": []
        }

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. Posten gruppiert nach Rechnungssteller laden
        cursor.execute("""
            SELECT
                rechnungssteller,
                COUNT(*) as anzahl,
                AVG(brutto) as durchschnitt,
                SUM(brutto) as gesamt,
                MIN(datum) as erste_zahlung,
                MAX(datum) as letzte_zahlung,
                GROUP_CONCAT(brutto) as betraege,
                GROUP_CONCAT(id) as posten_ids
            FROM steuer_posten
            WHERE username = ? AND steuerjahr = ?
              AND rechnungssteller IS NOT NULL
              AND rechnungssteller != ''
            GROUP BY rechnungssteller
            HAVING anzahl >= 2
            ORDER BY anzahl DESC
        """, (username, steuerjahr))

        gruppen = cursor.fetchall()
        result["posten_analysiert"] = sum(g['anzahl'] for g in gruppen)

        # 2. Patterns laden
        patterns = self._load_patterns(cursor)

        # 3. Jede Gruppe analysieren
        for gruppe in gruppen:
            score = self._calculate_score(gruppe, patterns)

            if score >= self.SCORE_THRESHOLD:
                erkennung = {
                    "anbieter": gruppe['rechnungssteller'],
                    "anzahl": gruppe['anzahl'],
                    "durchschnitt": gruppe['durchschnitt'],
                    "gesamt": gruppe['gesamt'],
                    "score": score,
                    "neu": False
                }

                # Pattern-Match fuer Kategorie und Link
                match = self._match_pattern(gruppe['rechnungssteller'], patterns)
                if match:
                    erkennung["kategorie"] = match.get('kategorie')
                    erkennung["kuendigungslink"] = match.get('kuendigungslink')
                    erkennung["pattern_name"] = match.get('anbieter')

                if not dry_run:
                    # In DB speichern/aktualisieren
                    is_new = self._save_subscription(cursor, erkennung, gruppe)
                    erkennung["neu"] = is_new
                    if is_new:
                        result["abos_neu"] += 1
                    else:
                        result["abos_aktualisiert"] += 1

                result["erkennungen"].append(erkennung)
                result["abos_erkannt"] += 1

        if not dry_run:
            conn.commit()
        conn.close()

        return result

    def _load_patterns(self, cursor) -> List[Dict]:
        """Laedt bekannte Abo-Patterns aus der DB."""
        try:
            cursor.execute("SELECT * FROM abo_patterns")
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []

    def _calculate_score(self, gruppe: sqlite3.Row, patterns: List[Dict]) -> int:
        """
        Berechnet Score fuer Abo-Wahrscheinlichkeit.

        Faktoren:
        - Anzahl Zahlungen (>= 12 = monatlich)
        - Konstanz der Betraege
        - Pattern-Match
        """
        score = 0

        # Anzahl Zahlungen
        anzahl = gruppe['anzahl']
        if anzahl >= 12:
            score += 40  # Monatlich
        elif anzahl >= 6:
            score += 30  # Zweimonatlich
        elif anzahl >= 4:
            score += 20  # Quartalsweise
        elif anzahl >= 2:
            score += 10  # Mindestens 2x

        # Konstanz der Betraege
        try:
            betraege = [float(b) for b in gruppe['betraege'].split(',') if b]
            if len(betraege) >= 2:
                varianz = stdev(betraege) if len(betraege) > 1 else 0
                avg = mean(betraege)
                # Variationskoeffizient (CV)
                cv = varianz / avg if avg > 0 else 0
                if cv < 0.05:  # Weniger als 5% Abweichung
                    score += 30
                elif cv < 0.1:
                    score += 20
                elif cv < 0.2:
                    score += 10
        except (ValueError, StatisticsError):
            pass

        # Pattern-Match
        if self._match_pattern(gruppe['rechnungssteller'], patterns):
            score += 30

        return score

    def _match_pattern(self, rechnungssteller: str, patterns: List[Dict]) -> Optional[Dict]:
        """Prueft ob Rechnungssteller zu bekanntem Pattern passt."""
        if not rechnungssteller:
            return None

        rs_lower = rechnungssteller.lower()

        for p in patterns:
            pattern = p.get('pattern', '').lower()
            if pattern and pattern in rs_lower:
                return p

        return None

    def _save_subscription(self, cursor, erkennung: Dict, gruppe: sqlite3.Row) -> bool:
        """
        Speichert oder aktualisiert Abo in der DB.

        Returns:
            True wenn neu, False wenn aktualisiert
        """
        anbieter = erkennung.get('pattern_name') or erkennung['anbieter']

        # Pruefen ob bereits vorhanden
        cursor.execute(
            "SELECT id FROM abo_subscriptions WHERE anbieter = ?",
            (anbieter,)
        )
        existing = cursor.fetchone()

        now = datetime.now().isoformat()

        if existing:
            # Aktualisieren
            cursor.execute("""
                UPDATE abo_subscriptions SET
                    betrag_monatlich = ?,
                    updated_at = ?
                WHERE id = ?
            """, (erkennung['durchschnitt'], now, existing['id']))
            return False
        else:
            # Neu anlegen
            cursor.execute("""
                INSERT INTO abo_subscriptions
                (name, anbieter, kategorie, betrag_monatlich, kuendigungslink, erkannt_am, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                anbieter,
                anbieter,
                erkennung.get('kategorie'),
                erkennung['durchschnitt'],
                erkennung.get('kuendigungslink'),
                now,
                now
            ))
            return True


# CLI fuer direkten Aufruf
if __name__ == "__main__":
    import sys

    # Pfade
    script_dir = Path(__file__).parent
    bach_dir = script_dir.parent.parent
    db_path = bach_dir / "data" / "bach.db"  # Unified DB seit v1.1.84

    if not db_path.exists():
        print(f"[ERROR] bach.db nicht gefunden: {db_path}")
        sys.exit(1)

    username = "user"
    steuerjahr = datetime.now().year

    # Args parsen
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    for i, arg in enumerate(sys.argv):
        if arg == "--jahr" and i + 1 < len(sys.argv):
            steuerjahr = int(sys.argv[i + 1])

    print(f"=== ABO-SCANNER ===")
    print(f"User:       {username}")
    print(f"Steuerjahr: {steuerjahr}")
    print(f"Dry-Run:    {dry_run}")
    print()

    scanner = AboScanner(db_path)
    result = scanner.scan(username, steuerjahr, dry_run=dry_run)

    print(f"Posten analysiert:  {result['posten_analysiert']}")
    print(f"Abos erkannt:       {result['abos_erkannt']}")
    print(f"Davon neu:          {result['abos_neu']}")
    print(f"Aktualisiert:       {result['abos_aktualisiert']}")
    print()

    if result['erkennungen']:
        print("--- Erkennungen ---")
        for e in result['erkennungen']:
            status = "[NEU]" if e.get('neu') else "[UPD]"
            print(f"  {status} {e['anbieter']}: {e['anzahl']}x, ~{e['durchschnitt']:.2f} EUR (Score: {e['score']})")
