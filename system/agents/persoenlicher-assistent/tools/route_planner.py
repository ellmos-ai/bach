#!/usr/bin/env python3
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
Tool: route_planner
Version: 1.1.0
Author: Claude
Created: 2026-02-04
Updated: 2026-03-02
Anthropic-Compatible: True

Description:
    Plant Reiserouten fuer Zug und Auto.
    - Echte Distanz-/Zeitberechnung via OSRM (routing_service)
    - Zug: Nutzt DB Navigator Deep-Links
    - Auto: Nutzt OSRM-Routing + Google Maps Deep-Links
    - Speichert haeufige Routen

Usage:
    python route_planner.py plan "Berlin" "Muenchen" --mode zug
    python route_planner.py plan "Hamburg" "Koeln" --mode auto
    python route_planner.py plan "Frankfurt" "Stuttgart" --date 2026-02-15 --time 09:00
    python route_planner.py save "Arbeit" --from "Zuhause" --to "Buero"
    python route_planner.py list
"""

__version__ = "1.1.0"
__author__ = "Claude"

import sqlite3
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple  # noqa: F401
from urllib.parse import quote_plus


# BACH Root ermitteln
BACH_ROOT = Path(__file__).parent.parent.parent.parent.parent

# Den DB-Pfad zentral erfragen, nicht selbst bauen: BACH_ROOT/data/bach.db ist
# die veraltete Kopie im OneDrive-Ordner, nicht die kanonische Datenbank.
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB as DB_PATH


class RoutePlanner:
    """Plant und verwaltet Reiserouten."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def _get_db(self):
        """Datenbankverbindung holen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self, conn):
        """Stellt sicher dass Routen-Tabelle existiert."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assistant_routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                from_location TEXT NOT NULL,
                to_location TEXT NOT NULL,
                default_mode TEXT DEFAULT 'zug',
                notes TEXT,
                use_count INTEGER DEFAULT 0,
                last_used DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    # Mapping von Route-Planner-Modi zu OSRM-Modi
    _MODE_TO_OSRM = {
        "auto": "car", "car": "car", "pkw": "car", "fahren": "car",
        "fahrrad": "bike", "bike": "bike", "rad": "bike",
        "fuss": "foot", "foot": "foot", "walk": "foot", "laufen": "foot",
    }

    def plan_route(self, from_loc: str, to_loc: str, mode: str = "zug",
                  date: str = None, time: str = None) -> Tuple[bool, str]:
        """Plant eine Route mit echten Distanz-/Zeitdaten (OSRM) und Links."""

        # Datum/Zeit defaults
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        if not time:
            time = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")

        # Datum in verschiedene Formate
        try:
            dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            db_date = dt.strftime("%d.%m.%Y")
            db_time = dt.strftime("%H:%M")
        except ValueError:
            db_date = date
            db_time = time

        output = [
            f"\n=== ROUTE: {from_loc} -> {to_loc} ===",
            f"Modus: {mode.upper()}",
            f"Datum: {date}",
            f"Zeit:  {time}",
            "",
        ]

        # === Echte Routendaten via OSRM (wenn Modus unterstuetzt) ===
        osrm_mode = self._MODE_TO_OSRM.get(mode.lower())
        route_data = None
        if osrm_mode:
            route_data = self._get_osrm_route(from_loc, to_loc, osrm_mode)

        if route_data:
            output.extend([
                f"Entfernung: {route_data['distance_km']} km",
                f"Fahrzeit:   ~{route_data['duration_str']}",
                "",
            ])

        # === Links generieren (wie bisher) ===
        if mode.lower() in ["zug", "bahn", "train", "db"]:
            db_link = self._get_db_link(from_loc, to_loc, db_date, db_time)
            output.extend([
                "Bahn-Verbindung:",
                f"  DB Navigator: {db_link}",
                "",
                "Alternativ:",
                f"  bahn.de: https://www.bahn.de/buchung/fahrplan/suche#sts=true&so={quote_plus(from_loc)}&zo={quote_plus(to_loc)}&kl=2&r=13:16:KLASSENLOS:1&soid=O&zoid=O",
            ])

        elif mode.lower() in ["auto", "car", "pkw", "fahren"]:
            maps_link = self._get_maps_link(from_loc, to_loc, "driving")
            output.extend([
                "Auto-Route:",
                f"  Google Maps: {maps_link}",
                "",
                "Alternativ:",
                f"  OpenStreetMap: https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={quote_plus(from_loc)}%3B{quote_plus(to_loc)}",
            ])

        elif mode.lower() in ["fahrrad", "bike", "rad"]:
            maps_link = self._get_maps_link(from_loc, to_loc, "bicycling")
            output.extend([
                "Fahrrad-Route:",
                f"  Google Maps: {maps_link}",
                "",
                "Alternativ:",
                f"  OpenStreetMap: https://www.openstreetmap.org/directions?engine=fossgis_osrm_bike&route={quote_plus(from_loc)}%3B{quote_plus(to_loc)}",
            ])

        elif mode.lower() in ["fuss", "foot", "walk", "laufen"]:
            maps_link = self._get_maps_link(from_loc, to_loc, "walking")
            output.extend([
                "Fuss-Route:",
                f"  Google Maps: {maps_link}",
            ])

        else:
            output.extend([
                "Route (alle Modi):",
                f"  Google Maps: {self._get_maps_link(from_loc, to_loc, 'transit')}",
                f"  DB Navigator: {self._get_db_link(from_loc, to_loc, db_date, db_time)}",
            ])

        output.extend([
            "",
            "Tipps:",
            "  - Fruehzeitig buchen fuer Sparpreise (Bahn)",
            "  - Stau-Info pruefen (Auto)",
            "  - BahnCard/ADAC beachten",
        ])

        return True, "\n".join(output)

    def _get_osrm_route(self, from_loc: str, to_loc: str, osrm_mode: str) -> Optional[dict]:
        """Berechnet Route via routing_service (OSRM). Gibt dict oder None zurueck."""
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
            from hub._services.routing.routing_service import get_route, geocode_place

            start = geocode_place(from_loc)
            end = geocode_place(to_loc)

            if start and end:
                result = get_route(start, end, mode=osrm_mode)
                if result and "error" not in result:
                    return result
        except Exception:
            pass
        return None

    def _get_db_link(self, from_loc: str, to_loc: str, date: str, time: str) -> str:
        """Generiert DB Navigator Deep-Link."""
        # DB Navigator URL Format
        base = "https://reiseauskunft.bahn.de/bin/query.exe/dn"
        params = [
            f"S={quote_plus(from_loc)}",
            f"Z={quote_plus(to_loc)}",
            f"date={quote_plus(date)}",
            f"time={quote_plus(time)}",
            "start=1",
        ]
        return f"{base}?{'&'.join(params)}"

    def _get_maps_link(self, from_loc: str, to_loc: str, mode: str = "driving") -> str:
        """Generiert Google Maps Link."""
        # Google Maps Directions URL
        mode_map = {
            "driving": "driving",
            "transit": "transit",
            "walking": "walking",
            "bicycling": "bicycling",
        }
        gm_mode = mode_map.get(mode, "driving")
        return f"https://www.google.com/maps/dir/{quote_plus(from_loc)}/{quote_plus(to_loc)}/data=!4m2!4m1!3e{0 if gm_mode == 'driving' else 3}"

    def save_route(self, name: str, from_loc: str, to_loc: str,
                  mode: str = "zug", notes: str = None) -> Tuple[bool, str]:
        """Speichert eine haeufige Route."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            # Pruefen ob bereits existiert
            existing = conn.execute(
                "SELECT id FROM assistant_routes WHERE LOWER(name) = LOWER(?)",
                (name,)
            ).fetchone()

            if existing:
                # Update
                conn.execute("""
                    UPDATE assistant_routes
                    SET from_location = ?, to_location = ?, default_mode = ?, notes = ?
                    WHERE id = ?
                """, (from_loc, to_loc, mode, notes, existing['id']))
                msg = f"[OK] Route aktualisiert: {name}"
            else:
                # Insert
                conn.execute("""
                    INSERT INTO assistant_routes (name, from_location, to_location, default_mode, notes)
                    VALUES (?, ?, ?, ?, ?)
                """, (name, from_loc, to_loc, mode, notes))
                msg = f"[OK] Route gespeichert: {name}"

            conn.commit()
            return True, msg

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def list_routes(self) -> Tuple[bool, str]:
        """Listet gespeicherte Routen."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            rows = conn.execute("""
                SELECT id, name, from_location, to_location, default_mode, use_count
                FROM assistant_routes
                ORDER BY use_count DESC, name
            """).fetchall()

            if not rows:
                return True, "Keine gespeicherten Routen."

            output = [f"\n[ROUTEN] {len(rows)} gespeichert:\n"]
            for r in rows:
                uses = f"({r['use_count']}x)" if r['use_count'] > 0 else ""
                output.append(
                    f"  [{r['id']}] {r['name']}: {r['from_location']} -> {r['to_location']} "
                    f"[{r['default_mode']}] {uses}"
                )

            output.extend([
                "",
                "Nutzung: python route_planner.py use <name>"
            ])

            return True, "\n".join(output)

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def use_route(self, name: str, date: str = None, time: str = None) -> Tuple[bool, str]:
        """Nutzt eine gespeicherte Route."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            row = conn.execute(
                "SELECT * FROM assistant_routes WHERE LOWER(name) LIKE LOWER(?)",
                (f"%{name}%",)
            ).fetchone()

            if not row:
                return False, f"Route '{name}' nicht gefunden"

            # Use-Count erhoehen
            conn.execute("""
                UPDATE assistant_routes
                SET use_count = use_count + 1, last_used = date('now')
                WHERE id = ?
            """, (row['id'],))
            conn.commit()

            # Route planen
            return self.plan_route(
                row['from_location'],
                row['to_location'],
                row['default_mode'],
                date,
                time
            )

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="BACH Route Planner")
    subparsers = parser.add_subparsers(dest="command", help="Verfuegbare Befehle")

    # plan
    plan_p = subparsers.add_parser("plan", help="Route planen")
    plan_p.add_argument("from_loc", help="Startort")
    plan_p.add_argument("to_loc", help="Zielort")
    plan_p.add_argument("--mode", "-m", default="zug",
                       help="Modus: zug, auto (default: zug)")
    plan_p.add_argument("--date", "-d", help="Datum (YYYY-MM-DD)")
    plan_p.add_argument("--time", "-t", help="Uhrzeit (HH:MM)")

    # save
    save_p = subparsers.add_parser("save", help="Route speichern")
    save_p.add_argument("name", help="Name der Route")
    save_p.add_argument("--from", dest="from_loc", required=True, help="Startort")
    save_p.add_argument("--to", dest="to_loc", required=True, help="Zielort")
    save_p.add_argument("--mode", "-m", default="zug", help="Standard-Modus")
    save_p.add_argument("--notes", "-n", help="Notizen")

    # list
    list_p = subparsers.add_parser("list", help="Gespeicherte Routen")

    # use
    use_p = subparsers.add_parser("use", help="Gespeicherte Route nutzen")
    use_p.add_argument("name", help="Name der Route")
    use_p.add_argument("--date", "-d", help="Datum")
    use_p.add_argument("--time", "-t", help="Uhrzeit")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    planner = RoutePlanner()

    if args.command == "plan":
        success, msg = planner.plan_route(
            args.from_loc, args.to_loc, args.mode, args.date, args.time
        )
    elif args.command == "save":
        success, msg = planner.save_route(
            args.name, args.from_loc, args.to_loc, args.mode, args.notes
        )
    elif args.command == "list":
        success, msg = planner.list_routes()
    elif args.command == "use":
        success, msg = planner.use_route(args.name, args.date, args.time)
    else:
        parser.print_help()
        return 1

    print(msg)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
