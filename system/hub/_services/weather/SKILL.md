---
name: weather
version: 1.0.0
type: service
description: Wetter-Service - aktuelle Wetterdaten fuer beliebige GPS-Koordinaten via wttr.in (kostenlos, kein API-Key)
author: BACH System
updated: 2026-02-18
status: active
---

# BACH Weather Service

**Version:** 1.0
**Autor:** BACH System
**Datum:** 2026-02-18
**API-Key:** Nicht erforderlich (wttr.in)

## Beschreibung
Ruft aktuelles Wetter fuer beliebige GPS-Koordinaten ab.
Datenquelle: wttr.in (kostenlos, kein API-Key, JSON-API).

## Nutzung (Library)
```python
import sys
sys.path.insert(0, str(BACH_DIR))
from hub._services.weather.weather_service import get_weather, get_weather_text

# Lesbarer String (fuer Prompts)
text = get_weather_text(lat=47.761, lon=8.079)

# Strukturiertes Dict
data = get_weather(lat=47.761, lon=8.079)
# -> {"temp_c": 0, "feels_like_c": -3, "humidity": 100, ...}
```

## Nutzung (CLI)
```
python weather_service.py <lat> <lon>
python weather_service.py 47.761 8.079
```

## Rueckgabefelder (get_weather)
- `temp_c` – Temperatur in Grad Celsius
- `feels_like_c` – Gefuehlte Temperatur
- `humidity` – Luftfeuchtigkeit in %
- `windspeed_kmph` – Windgeschwindigkeit km/h
- `winddir` – Windrichtung (N, NE, E, ...)
- `wind_arrow` – Pfeilsymbol fuer Windrichtung
- `description_de` – Deutsche Wetterbeschreibung
- `icon` – Wetter-Emoji (☀️, ⛅, 🌧️, ❄️, ...)
- `location_name` – Naechster Ortsname (Nominatim)
- `country` – Land
- `uv_index` – UV-Index

## Integration
- **Telegram Bridge:** GPS-Pin → Wetter wird automatisch abgerufen
- **bridge_daemon.py:** `_fetch_weather(lat, lng)` → injiziert Wetter in Prompt
