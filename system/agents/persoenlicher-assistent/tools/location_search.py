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
Tool: location_search
Version: 1.1.0
Author: Claude
Created: 2026-02-04
Updated: 2026-03-02
Anthropic-Compatible: True

Description:
    Sucht Locations (Restaurants, Hotels, POIs) via OpenStreetMap.
    - Kategorie-Suche (restaurant, cafe, hotel etc.) via Overpass API
    - Adress-/Namensuche via Nominatim API
    Keine API-Keys erforderlich, respektiert Rate-Limits.

Usage:
    python location_search.py search "Restaurant" --near "Berlin"
    python location_search.py search "Hotel" --near "Muenchen" --limit 5
    python location_search.py nearby restaurant --lat 52.52 --lon 13.405 --radius 3000
    python location_search.py geocode "Alexanderplatz, Berlin"
    python location_search.py save "Lieblingsrestaurant" --address "..."
"""

__version__ = "1.1.0"
__author__ = "Claude"

import sqlite3
import json
import sys
import argparse
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.parse import quote_plus, urlencode
from urllib.error import URLError


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

# Nominatim API (OpenStreetMap)
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = "BACH-PersonalAssistant/3.3"

# Overpass API (OpenStreetMap POI-Suche)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bekannte POI-Kategorien fuer Overpass-Suche
OVERPASS_CATEGORIES = {
    "restaurant", "cafe", "hotel", "supermarket", "pharmacy",
    "hospital", "bank", "fuel", "parking", "school",
    "bar", "fast_food", "bakery", "butcher", "dentist",
    "doctors", "atm", "post_office", "library", "cinema",
}


class LocationSearch:
    """Sucht und verwaltet Locations."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._last_request = 0

    def _get_db(self):
        """Datenbankverbindung holen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self, conn):
        """Stellt sicher dass Location-Tabelle existiert."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assistant_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT,
                address TEXT,
                city TEXT,
                postal_code TEXT,
                country TEXT DEFAULT 'Deutschland',
                latitude REAL,
                longitude REAL,
                phone TEXT,
                website TEXT,
                opening_hours TEXT,
                notes TEXT,
                is_favorite INTEGER DEFAULT 0,
                last_visit DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    def _rate_limit(self):
        """Respektiert Nominatim Rate-Limit (1 request/sec)."""
        elapsed = time.time() - self._last_request
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_request = time.time()

    def _nominatim_request(self, endpoint: str, params: dict) -> Optional[dict]:
        """Fuehrt Nominatim API Request durch."""
        self._rate_limit()

        param_str = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
        url = f"{NOMINATIM_BASE}/{endpoint}?{param_str}&format=json"

        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except (URLError, json.JSONDecodeError) as e:
            print(f"[WARN] API-Fehler: {e}")
            return None

    def search_nearby(self, lat: float, lon: float, category: str = "restaurant",
                      radius: int = 2000, limit: int = 10) -> list:
        """POI-Suche via Overpass API (OpenStreetMap).

        Kategorien: restaurant, cafe, hotel, supermarket, pharmacy, hospital,
        bank, fuel, parking, school, bar, fast_food, bakery, butcher,
        dentist, doctors, atm, post_office, library, cinema
        """
        self._rate_limit()

        query = f"""[out:json][timeout:10];
(
  node["amenity"="{category}"](around:{radius},{lat},{lon});
  way["amenity"="{category}"](around:{radius},{lat},{lon});
);
out center body {limit};"""

        data = urlencode({"data": query}).encode()
        req = Request(OVERPASS_URL, data=data)
        req.add_header("User-Agent", USER_AGENT)

        try:
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[WARN] Overpass API-Fehler: {e}")
            return []

        pois = []
        for elem in result.get("elements", []):
            tags = elem.get("tags", {})
            lat_e = elem.get("lat") or elem.get("center", {}).get("lat")
            lon_e = elem.get("lon") or elem.get("center", {}).get("lon")

            pois.append({
                "name": tags.get("name", "Unbekannt"),
                "category": category,
                "lat": lat_e,
                "lon": lon_e,
                "address": (tags.get("addr:street", "") + " " + tags.get("addr:housenumber", "")).strip(),
                "city": tags.get("addr:city", ""),
                "phone": tags.get("phone", ""),
                "website": tags.get("website", ""),
                "opening_hours": tags.get("opening_hours", ""),
                "cuisine": tags.get("cuisine", ""),
            })

        return pois

    def _is_category_query(self, query: str) -> Optional[str]:
        """Prueft ob die Query eine bekannte POI-Kategorie ist."""
        q_lower = query.lower().strip()
        # Direkte Uebereinstimmung
        if q_lower in OVERPASS_CATEGORIES:
            return q_lower
        # Deutsche Begriffe mappen
        de_mapping = {
            "restaurant": "restaurant", "restaurants": "restaurant",
            "cafe": "cafe", "cafes": "cafe", "kaffee": "cafe",
            "hotel": "hotel", "hotels": "hotel",
            "supermarkt": "supermarket", "supermarket": "supermarket",
            "apotheke": "pharmacy", "pharmacy": "pharmacy",
            "krankenhaus": "hospital", "hospital": "hospital",
            "bank": "bank", "banken": "bank",
            "tankstelle": "fuel", "fuel": "fuel",
            "parkplatz": "parking", "parking": "parking",
            "schule": "school", "school": "school",
            "bar": "bar", "bars": "bar", "kneipe": "bar",
            "baeckerei": "bakery", "bakery": "bakery",
            "metzgerei": "butcher", "butcher": "butcher",
            "zahnarzt": "dentist", "dentist": "dentist",
            "arzt": "doctors", "doctors": "doctors",
            "geldautomat": "atm", "atm": "atm",
            "post": "post_office", "postamt": "post_office",
            "bibliothek": "library", "library": "library",
            "kino": "cinema", "cinema": "cinema",
            "imbiss": "fast_food", "fast_food": "fast_food",
        }
        return de_mapping.get(q_lower)

    def search(self, query: str, near: str = None, limit: int = 5) -> Tuple[bool, str]:
        """Sucht nach Locations.

        Automatische Erkennung:
        - Wenn Query eine Kategorie ist (restaurant, cafe, hotel etc.) -> Overpass API
        - Wenn Query eine Adresse/Name ist -> Nominatim API
        """
        category = self._is_category_query(query)

        # === Kategorie-Suche via Overpass ===
        if category and near:
            # Zuerst: Koordinaten des "near"-Orts per Nominatim ermitteln
            geo_params = {"q": near, "limit": 1, "addressdetails": 1}
            geo_result = self._nominatim_request("search", geo_params)

            if geo_result:
                lat = float(geo_result[0].get("lat", 0))
                lon = float(geo_result[0].get("lon", 0))

                pois = self.search_nearby(lat, lon, category=category, radius=3000, limit=limit)

                if pois:
                    output = [f"\n[LOCATIONS] {category.title()} in der Naehe von {near}", ""]

                    for i, poi in enumerate(pois[:limit], 1):
                        output.append(f"  [{i}] {poi['name']}")
                        if poi['address']:
                            addr_line = poi['address']
                            if poi['city']:
                                addr_line += f", {poi['city']}"
                            output.append(f"      Adresse: {addr_line}")
                        if poi['cuisine']:
                            output.append(f"      Kueche: {poi['cuisine']}")
                        if poi['opening_hours']:
                            output.append(f"      Oeffnungszeiten: {poi['opening_hours']}")
                        if poi['phone']:
                            output.append(f"      Telefon: {poi['phone']}")
                        if poi['website']:
                            output.append(f"      Web: {poi['website']}")
                        if poi['lat'] and poi['lon']:
                            output.append(f"      Koordinaten: {poi['lat']}, {poi['lon']}")
                        output.append("")

                    return True, "\n".join(output)

            # Fallback: Nominatim wenn Overpass fehlschlaegt
            return self._search_nominatim(f"{query}, {near}", near, limit)

        # === Adress-/Namensuche via Nominatim (bisheriges Verhalten) ===
        search_query = f"{query}, {near}" if near else query
        return self._search_nominatim(search_query, near, limit, original_query=query)

    def _search_nominatim(self, query: str, near: str = None, limit: int = 5,
                          original_query: str = None) -> Tuple[bool, str]:
        """Nominatim-Suche (bisheriges Verhalten)."""
        params = {"q": query, "limit": limit, "addressdetails": 1}

        results = self._nominatim_request("search", params)

        if not results:
            display_query = original_query or query
            return False, f"Keine Ergebnisse fuer '{display_query}'"

        display_query = original_query or query
        output = [f"\n[LOCATIONS] Suche: {display_query}" + (f" (bei {near})" if near else ""), ""]

        for i, r in enumerate(results[:limit], 1):
            name = r.get("display_name", "Unbekannt")
            lat = r.get("lat", "?")
            lon = r.get("lon", "?")
            loc_type = r.get("type", "")
            category = r.get("category", "")

            # Adresse extrahieren
            addr = r.get("address", {})
            city = addr.get("city") or addr.get("town") or addr.get("village", "")
            road = addr.get("road", "")
            house = addr.get("house_number", "")

            output.append(f"  [{i}] {name[:60]}")
            if road:
                output.append(f"      Adresse: {road} {house}, {city}")
            output.append(f"      Typ: {category}/{loc_type}")
            output.append(f"      Koordinaten: {lat}, {lon}")
            output.append("")

        return True, "\n".join(output)

    def geocode(self, address: str) -> Tuple[bool, str]:
        """Ermittelt Koordinaten zu einer Adresse."""
        params = {"q": address, "limit": 1, "addressdetails": 1}
        results = self._nominatim_request("search", params)

        if not results:
            return False, f"Adresse nicht gefunden: {address}"

        r = results[0]
        lat = r.get("lat", "?")
        lon = r.get("lon", "?")
        display = r.get("display_name", address)

        output = [
            f"\n[GEOCODE] {address}",
            f"  Gefunden: {display}",
            f"  Latitude:  {lat}",
            f"  Longitude: {lon}",
            f"  Maps-Link: https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=17"
        ]

        return True, "\n".join(output)

    def save_location(self, name: str, address: str = None, category: str = None,
                     notes: str = None, favorite: bool = False) -> Tuple[bool, str]:
        """Speichert eine Location in der DB."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            # Geocoding wenn Adresse angegeben
            lat, lon, city = None, None, None
            if address:
                params = {"q": address, "limit": 1, "addressdetails": 1}
                results = self._nominatim_request("search", params)
                if results:
                    r = results[0]
                    lat = float(r.get("lat", 0))
                    lon = float(r.get("lon", 0))
                    addr_parts = r.get("address", {})
                    city = addr_parts.get("city") or addr_parts.get("town", "")

            conn.execute("""
                INSERT INTO assistant_locations
                (name, category, address, city, latitude, longitude, notes, is_favorite)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, category, address, city, lat, lon, notes, 1 if favorite else 0))
            conn.commit()

            return True, f"[OK] Location gespeichert: {name}"

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def list_locations(self, category: str = None, favorites_only: bool = False) -> Tuple[bool, str]:
        """Listet gespeicherte Locations."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            query = "SELECT id, name, category, city, is_favorite FROM assistant_locations WHERE 1=1"
            params = []

            if category:
                query += " AND category = ?"
                params.append(category)

            if favorites_only:
                query += " AND is_favorite = 1"

            query += " ORDER BY name"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "Keine gespeicherten Locations."

            output = [f"\n[LOCATIONS] {len(rows)} gespeichert:\n"]
            for r in rows:
                star = "* " if r['is_favorite'] else "  "
                cat = f"[{r['category']}]" if r['category'] else ""
                city = f"in {r['city']}" if r['city'] else ""
                output.append(f"  {star}[{r['id']}] {r['name']} {cat} {city}")

            return True, "\n".join(output)

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="BACH Location Search")
    subparsers = parser.add_subparsers(dest="command", help="Verfuegbare Befehle")

    # search
    search_p = subparsers.add_parser("search", help="Nach Locations suchen")
    search_p.add_argument("query", help="Suchbegriff (z.B. 'Restaurant italienisch')")
    search_p.add_argument("--near", "-n", help="In der Naehe von (Stadt/Ort)")
    search_p.add_argument("--limit", "-l", type=int, default=5, help="Max. Ergebnisse")

    # geocode
    geo_p = subparsers.add_parser("geocode", help="Adresse zu Koordinaten")
    geo_p.add_argument("address", help="Adresse")

    # save
    save_p = subparsers.add_parser("save", help="Location speichern")
    save_p.add_argument("name", help="Name der Location")
    save_p.add_argument("--address", "-a", help="Adresse")
    save_p.add_argument("--category", "-c", help="Kategorie (Restaurant, Hotel, etc.)")
    save_p.add_argument("--notes", "-n", help="Notizen")
    save_p.add_argument("--favorite", "-f", action="store_true", help="Als Favorit markieren")

    # nearby (Overpass POI-Suche)
    nearby_p = subparsers.add_parser("nearby", help="POIs in der Naehe suchen (Overpass API)")
    nearby_p.add_argument("category", help="Kategorie (restaurant, cafe, hotel, ...)")
    nearby_p.add_argument("--lat", type=float, required=True, help="Latitude")
    nearby_p.add_argument("--lon", type=float, required=True, help="Longitude")
    nearby_p.add_argument("--radius", "-r", type=int, default=2000, help="Radius in Metern (default: 2000)")
    nearby_p.add_argument("--limit", "-l", type=int, default=10, help="Max. Ergebnisse")

    # list
    list_p = subparsers.add_parser("list", help="Gespeicherte Locations")
    list_p.add_argument("--category", "-c", help="Nach Kategorie filtern")
    list_p.add_argument("--favorites", "-f", action="store_true", help="Nur Favoriten")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    loc = LocationSearch()

    if args.command == "search":
        success, msg = loc.search(args.query, args.near, args.limit)
    elif args.command == "nearby":
        pois = loc.search_nearby(args.lat, args.lon, args.category, args.radius, args.limit)
        if pois:
            lines = [f"\n[NEARBY] {len(pois)} {args.category} im Umkreis von {args.radius}m:\n"]
            for i, poi in enumerate(pois, 1):
                lines.append(f"  [{i}] {poi['name']}")
                if poi['address']:
                    lines.append(f"      Adresse: {poi['address']}")
                if poi['lat'] and poi['lon']:
                    lines.append(f"      Koordinaten: {poi['lat']}, {poi['lon']}")
                lines.append("")
            success, msg = True, "\n".join(lines)
        else:
            success, msg = False, f"Keine {args.category} im Umkreis gefunden."
    elif args.command == "geocode":
        success, msg = loc.geocode(args.address)
    elif args.command == "save":
        success, msg = loc.save_location(
            args.name, args.address, args.category, args.notes, args.favorite
        )
    elif args.command == "list":
        success, msg = loc.list_locations(args.category, args.favorites)
    else:
        parser.print_help()
        return 1

    print(msg)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
