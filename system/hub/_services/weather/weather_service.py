#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
BACH Weather Service v1.0
==========================
Ruft Wetterdaten via wttr.in ab (kein API-Key erforderlich).

Quellen:
  - wttr.in  – kostenlos, kein Key, JSON-API

Nutzung (Library):
    from hub._services.weather.weather_service import get_weather, get_weather_text
    data  = get_weather(lat=53.551, lon=9.994)   # dict
    text  = get_weather_text(lat=53.551, lon=9.994)  # lesbarer String

Nutzung (CLI):
    python weather_service.py 53.551 9.994
    python weather_service.py "Hamburg"

Autor: BACH System
Datum: 2026-02-18
"""

import json
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional

# ============ WETTER-ICONS ============

WTTR_CODE_ICONS = {
    "113": "☀️",   # Klar/Sonnig
    "116": "⛅",   # Teilweise bewoelkt
    "119": "☁️",   # Bewoelkt
    "122": "☁️",   # Bedeckt
    "143": "🌫️",  # Dunst/Nebel
    "176": "🌦️",  # Moeglicher Regen
    "179": "🌨️",  # Moeglicher Schnee
    "182": "🌧️",  # Regen/Schneeregen
    "185": "🌧️",  # Schneeregen
    "200": "⛈️",  # Gewitter
    "227": "❄️",  # Schneetreiben
    "230": "❄️",  # Blizzard
    "248": "🌫️",  # Nebel
    "260": "🌫️",  # Gefrierender Nebel
    "263": "🌦️",  # Leichter Nieselregen
    "266": "🌦️",  # Nieselregen
    "281": "🌧️",  # Gefrierender Nieselregen
    "284": "🌧️",  # Starker gefrierender Nieselregen
    "293": "🌦️",  # Leichter Regen
    "296": "🌧️",  # Regen
    "299": "🌧️",  # Maessiger Regen
    "302": "🌧️",  # Starker Regen
    "305": "🌧️",  # Starker Regen
    "308": "🌧️",  # Heftiger Regen
    "311": "🌧️",  # Schneeregen
    "314": "🌧️",  # Starker Schneeregen
    "317": "🌧️",  # Schneeregen
    "320": "🌨️",  # Leichter Schnee
    "323": "🌨️",  # Moeglicher leichter Schnee
    "326": "🌨️",  # Leichter Schnee
    "329": "❄️",  # Maessiger Schnee
    "332": "❄️",  # Maessiger Schnee
    "335": "❄️",  # Starker Schnee
    "338": "❄️",  # Starker Schnee
    "350": "🌧️",  # Eisregen
    "353": "🌦️",  # Leichter Regenschauer
    "356": "🌧️",  # Regenschauer
    "359": "🌧️",  # Starker Regenschauer
    "362": "🌧️",  # Schneeregenschauer
    "365": "🌧️",  # Schneeregenschauer
    "368": "🌨️",  # Schneeschauer
    "371": "❄️",  # Starker Schneeschauer
    "374": "🌧️",  # Eisregenkoerner
    "377": "🌧️",  # Starker Eisregen
    "386": "⛈️",  # Gewitter
    "389": "⛈️",  # Starkes Gewitter
    "392": "⛈️",  # Schneegewitter
    "395": "⛈️",  # Starkes Schneegewitter
}

WIND_DIRECTIONS = {
    "N": "↓", "NNE": "↙", "NE": "↙", "ENE": "←",
    "E": "←", "ESE": "↖", "SE": "↖", "SSE": "↑",
    "S": "↑", "SSW": "↗", "SW": "↗", "WSW": "→",
    "W": "→", "WNW": "↘", "NW": "↘", "NNW": "↓",
}


def get_weather(lat: float, lon: float, lang: str = "de") -> Optional[dict]:
    """
    Ruft Wetterdaten von wttr.in ab.

    Returns:
        dict mit: temp_c, feels_like_c, humidity, windspeed_kmph, winddir,
                  description, description_de, icon, location_name, country
        oder None bei Fehler.
    """
    url = f"https://wttr.in/{lat:.4f},{lon:.4f}?format=j1&lang={lang}"

    last_err = None
    for attempt in range(2):  # max 2 Versuche (SSL-Kaltstart)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "BACH-Weather-Service/1.0 (github.com/ellmos-ai/bach)"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            last_err = None
            break
        except urllib.error.URLError as e:
            last_err = {"error": f"Netzwerkfehler: {e}"}
        except Exception as e:
            last_err = {"error": f"Fehler: {e}"}
    if last_err:
        return last_err

    return _fetch_json(url, lang)


def _parse_daily_day(day: dict) -> dict:
    """
    Wandelt einen wttr.in "weather"-Tag in ein normiertes Dict um.

    Parameters:
        day – Ein Eintrag aus data["weather"][i]

    Returns:
        dict mit: date, day_name, min_c, max_c, midday_c, midday_hour,
                  icon, weather_code, description, sunrise, sunset,
                  max_chance_of_rain_pct, hourly (Liste)
        oder None bei fehlenden Daten.
    """
    if not day:
        return None
    try:
        date = day.get("date", "?")
        # maxChanceOfRain wird meist im "hourly"-Array geliefert
        hourly_raw = day.get("hourly", [])
        hourly = []
        max_chance = 0
        midday_hour = "12"
        midday = None
        for h in hourly_raw:
            hour = h.get("hour", "0")
            try:
                h_int = int(hour)
            except (ValueError, TypeError):
                h_int = 0
            chance = int(h.get("chanceofrain", 0) or 0)
            if chance > max_chance:
                max_chance = chance
            if h_int == 12:
                midday = h
            entry = {
                "hour": hour,
                "temp_c": int(h.get("tempC", 0)),
                "feels_like_c": int(h.get("FeelsLikeC", 0)),
                "weather_code": h.get("weatherCode", "113"),
                "icon": WTTR_CODE_ICONS.get(str(h.get("weatherCode", "113")), "🌡️"),
                "chanceofrain_pct": chance,
                "humidity_pct": int(h.get("humidity", 0)),
            }
            hourly.append(entry)
        if midday is None and hourly:
            midday = hourly[len(hourly) // 2]

        weather_code = midday.get("weather_code", "113") if midday else "113"
        desc = midday.get("description", "?") if midday else "?"
        icon = midday.get("icon", "🌡️") if midday else "🌡️"

        return {
            "date": date,
            "day_name": day.get("weekdayName", [{}])[0].get("value", "") if isinstance(day.get("weekdayName"), list) else day.get("weekdayName", ""),
            "min_c": int(day.get("mintempC", 0)),
            "max_c": int(day.get("maxtempC", 0)),
            "midday_c": int(midday.get("temp_c", 0)) if midday else int(day.get("maxtempC", 0)),
            "midday_hour": midday_hour,
            "icon": icon,
            "weather_code": weather_code,
            "description": desc,
            "sunrise": day.get("astronomy", [{}])[0].get("sunrise", "?") if isinstance(day.get("astronomy"), list) else "?",
            "sunset": day.get("astronomy", [{}])[0].get("sunset", "?") if isinstance(day.get("astronomy"), list) else "?",
            "max_chance_of_rain_pct": max_chance,
            "hourly": hourly,
        }
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return {"error": f"Parse-Fehler (daily): {e}"}


def get_weather(lat: float, lon: float, lang: str = "de",
                include_forecast: bool = False) -> Optional[dict]:
        area = data.get("nearest_area", [{}])[0]

        area_name = area.get("areaName", [{}])[0].get("value", "?")
        country = area.get("country", [{}])[0].get("value", "?")

        weather_code = cc.get("weatherCode", "113")
        desc_en = cc.get("weatherDesc", [{}])[0].get("value", "?")
        # Versuche deutsche Beschreibung
        desc_de = desc_en
        for lang_entry in cc.get("lang_de", []):
            if lang_entry.get("value"):
                desc_de = lang_entry["value"]
                break

        icon = WTTR_CODE_ICONS.get(str(weather_code), "🌡️")
        winddir = cc.get("winddir16Point", "?")
        wind_arrow = WIND_DIRECTIONS.get(winddir, "")

        return {
            "temp_c": int(cc.get("temp_C", 0)),
            "feels_like_c": int(cc.get("FeelsLikeC", 0)),
            "humidity": int(cc.get("humidity", 0)),
            "windspeed_kmph": int(cc.get("windspeedKmph", 0)),
            "winddir": winddir,
            "wind_arrow": wind_arrow,
            "description": desc_en,
            "description_de": desc_de,
            "icon": icon,
            "weather_code": weather_code,
            "location_name": area_name,
            "country": country,
            "uv_index": int(cc.get("uvIndex", 0)),
            "visibility_km": int(cc.get("visibility", 0)),
        }
    except (KeyError, IndexError, ValueError) as e:
        return {"error": f"Parse-Fehler: {e}", "raw": str(data)[:200]}


def _build_day_summary(day: dict, index: int) -> dict:
    """
    Baut aus einem Eintrag des wttr.in 'weather'-Arrays eine Tages-Zusammenfassung.

    wttr.in liefert 3 Tage (0=today, 1=morgen, 2=uebermorgen).
    Fuer Icon/Beschreibung wird der Mittags-Eintrag (Index 4, ~12:00) genutzt.

    Returns:
        dict mit: day_index, tag_label, date, maxtemp_c, mintemp_c,
                  icon, description, description_de, weather_code, sunrise, sunset
        oder None bei Fehler.
    """
    try:
        hourlies = day.get("hourly", [])
        # Mittagswert (Index 4 = 12:00) als repraesentativen Wert des Tages
        mid = hourlies[4] if len(hourlies) > 4 else (hourlies[0] if hourlies else {})
        weather_code = mid.get("weatherCode", "113")
        desc_en = mid.get("weatherDesc", [{}])[0].get("value", "?")
        desc_de = desc_en
        for lang_entry in mid.get("lang_de", []):
            if lang_entry.get("value"):
                desc_de = lang_entry["value"]
                break

        labels = ["Heute", "Morgen", "Uebermorgen"]
        return {
            "day_index": index,
            "tag_label": labels[index] if index < len(labels) else f"Tag {index + 1}",
            "date": day.get("date", "?"),
            "maxtemp_c": int(day.get("maxtempC", 0)),
            "mintemp_c": int(day.get("mintempC", 0)),
            "icon": WTTR_CODE_ICONS.get(str(weather_code), "🌡️"),
            "description": desc_en,
            "description_de": desc_de,
            "weather_code": weather_code,
            "sunrise": day.get("astronomy", [{}])[0].get("sunrise", "?") if day.get("astronomy") else "?",
            "sunset": day.get("astronomy", [{}])[0].get("sunset", "?") if day.get("astronomy") else "?",
        }
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return {"error": f"Tages-Parse-Fehler: {e}"}


def get_forecast(lat: float, lon: float, lang: str = "de") -> list:
    """
    Ruft die Mehr-Tage-Vorhersage (3 Tage: heute, morgen, uebermorgen) ab.

    wttr.in liefert im j1-Format standardmaessig 3 Tage. Dies dient als
    Basis fuer "Wochen-Uebersicht" (kurze Vorhersage) sowie den
    Einzel-Zugriffen get_tomorrow_weather / get_day_after_tomorrow_weather.

    Returns:
        Liste von 3 Tages-Dicts (siehe _build_day_summary) oder
        ein Fehler-Dict als einziges Element bei Netz/Parse-Fehler.
    """
    url = f"https://wttr.in/{lat:.4f},{lon:.4f}?format=j1&lang={lang}"

    last_err = None
    for attempt in range(2):   # max 2 Versuche (SSL-Kaltstart)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "BACH-Weather-Service/1.0 (github.com/ellmos-ai/bach)"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            last_err = None
            break
        except urllib.error.URLError as e:
            last_err = f"Netzwerkfehler: {e}"
        except Exception as e:
            last_err = f"Fehler: {e}"
    if last_err:
        return [{"error": last_err}]

    days = data.get("weather", [])
    if not days:
        return [{"error": "Keine Vorhersagedaten in Antwort"}]

    return [_build_day_summary(day, i) for i, day in enumerate(days)]


def get_tomorrow_weather(lat: float, lon: float, lang: str = "de") -> Optional[dict]:
    """Gibt die Vorhersage fuer morgen (Tag 1) als dict zurueck, None bei Fehler."""
    fc = get_forecast(lat, lon, lang)
    if not fc or "error" in fc[0]:
        return fc[0] if fc else None
    # fc[1] = morgen, sofern vorhanden
    return fc[1] if len(fc) > 1 else {"error": "Kein Morgen-Tag in Antwort"}


def get_day_after_tomorrow_weather(lat: float, lon: float, lang: str = "de") -> Optional[dict]:
    """Gibt die Vorhersage fuer uebermorgen (Tag 2) als dict zurueck, None bei Fehler."""
    fc = get_forecast(lat, lon, lang)
    if not fc or "error" in fc[0]:
        return fc[0] if fc else None
    return fc[2] if len(fc) > 2 else {"error": "Kein Uebermorgen-Tag in Antwort"}


def get_week_weather(lat: float, lon: float, lang: str = "de") -> list:
    """
    Gibt die Wochen-Vorhersage (aktuell 3 Tage durch wttr.in) als Liste zurueck.

    Hinweis: wttr.in liefert im kostenlosen j1-Format 3 Tage. Fuer eine echte
    7-Tage-Vorhersage waere eine bezahlte API (OpenWeather) benoetigt.
    """
    return get_forecast(lat, lon, lang)


def get_forecast_text(lat: float, lon: float, label: str = "Wochenaussicht") -> str:
    """
    Gibt eine lesbare Mehr-Tage-Vorhersage als String zurueck (fuer Prompts).

    Beispiel:
        🌤️ Wochenaussicht fuer Hamburg, Germany:
        Heute   2026-02-18: ☀️ +5°/+1°C Klar
        Morgen  2026-02-19: ⛅ +4°/+2°C Teilweise bewoelkt
        Uebermorgen 2026-02-20: 🌧️ +3°/0°C Regen
     """
    fc = get_forecast(lat, lon)
    if not fc or "error" in fc[0]:
        err = fc[0].get("error", "unbekannt") if fc else "Timeout"
        return f"[Vorhersage: nicht verfuegbar – {err}]"

    # Naechsten Ortsnamen aus dem aktuellen Wetter nachschlagen (nur falls noetig)
    w = get_weather(lat, lon)
    loc = w.get("location_name") if w and "error" not in w else None
    loc = loc if loc and loc != "?" else f"{lat:.4f}°N, {lon:.4f}°E"

    lines = [f"{fc[0].get('icon', '🌡️')} {label} fuer {loc}:"]
    for day in fc:
        if "error" in day:
            continue
        temp = f"{day['maxtemp_c']:+d}°/{day['mintemp_c']:+d}°C"
        desc = day.get("description_de") or day.get("description", "?")
        lines.append(
            f"{day['tag_label']:<12} {day['date']}: {day['icon']} {temp} {desc}"
        )
    return "\n".join(lines)


def get_weather_text(lat: float, lon: float) -> str:
    """
    Gibt einen lesbaren Wetter-String zurueck (fuer Claude-Prompt-Injektion).

    Beispiel:
        🌤️ Wetter bei 53.5511°N, 9.9937°E (Hamburg, Germany):
        Temperatur: +3°C (gefuehlt: +1°C) | Bewoelkt
        Wind: ↙ 12 km/h | Luftfeuchtigkeit: 85% | UV-Index: 0
    """
    w = get_weather(lat, lon)
    if not w or "error" in w:
        err = w.get("error", "unbekannt") if w else "Timeout"
        return f"[Wetter: nicht verfuegbar – {err}]"

    loc = f"{w['location_name']}, {w['country']}" if w.get("location_name") != "?" else f"{lat:.4f}°N, {lon:.4f}°E"
    wind = f"{w['wind_arrow']} {w['windspeed_kmph']} km/h" if w.get("wind_arrow") else f"{w['windspeed_kmph']} km/h"
    desc = w.get("description_de") or w.get("description", "?")

    lines = [
        f"{w['icon']} Aktuelles Wetter bei {w['location_name']}, {w['country']}:",
        f"Temperatur: {w['temp_c']:+d}°C (gefuehlt: {w['feels_like_c']:+d}°C) | {desc}",
        f"Wind: {wind} | Luftfeuchtigkeit: {w['humidity']}% | UV-Index: {w['uv_index']}",
    ]
    return "\n".join(lines)


def main():
    """CLI-Aufruf: python weather_service.py <lat> <lon>"""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    if len(sys.argv) < 2:
        print("Nutzung: python weather_service.py <lat> <lon>")
        print("         python weather_service.py 47.761 8.079")
        sys.exit(1)

    if len(sys.argv) == 3:
        try:
            lat = float(sys.argv[1])
            lon = float(sys.argv[2])
        except ValueError:
            print(f"Ungueltige Koordinaten: {sys.argv[1]}, {sys.argv[2]}")
            sys.exit(1)
    else:
        # Ortsname -> wttr.in unterstuetzt das auch, aber wir brauchen Koordinaten
        print("Nur Koordinaten werden unterstuetzt: lat lon")
        sys.exit(1)

    text = get_weather_text(lat, lon)
    print(text)

    # Auch rohes Dict ausgeben
    data = get_weather(lat, lon)
    if data and "error" not in data:
        print(f"\nRohdaten: {json.dumps(data, ensure_ascii=False)}")


if __name__ == "__main__":
    import os
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
