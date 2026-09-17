---
name: routing
version: 1.0.0
type: service
description: Routing-Service - Routen zwischen GPS-Koordinaten via OSRM/Nominatim (Auto, Fahrrad, zu Fuss)
author: BACH System
updated: 2026-02-18
status: active
---

# BACH Routing Service

**Version:** 1.0
**Autor:** BACH System
**Datum:** 2026-02-18
**API-Key:** Nicht erforderlich (OSRM public, Nominatim)

## Beschreibung
Berechnet Routen zwischen GPS-Koordinaten (Auto, Fahrrad, zu Fuss).
Datenquelle: OSRM oeffentliche Instanz (router.project-osrm.org).
Geocoding: Nominatim / OpenStreetMap.

## Nutzung (Library)
```python
import sys
sys.path.insert(0, str(BACH_DIR))
from hub._services.routing.routing_service import get_route, get_route_text, geocode_place

# Lesbarer String
text = get_route_text(
    start=(53.551, 9.994),
    end=(52.520, 13.405),
    mode="car",
    start_name="Hamburg",
    end_name="Berlin"
)

# Strukturiertes Dict
result = get_route(start=(53.551, 9.994), end=(52.520, 13.405), mode="car")
# -> {"distance_km": 64.2, "duration_str": "1h 1min", ...}

# Ortsname -> Koordinaten
coords = geocode_place("Freiburg im Breisgau")
# -> (47.9957839, 7.8493949)
```

## Nutzung (CLI)
```
python routing_service.py <start_lat> <start_lon> <end_lat> <end_lon> [mode]
python routing_service.py 47.761 8.079 47.994 7.849 car
python routing_service.py 47.761 8.079 47.994 7.849 bike
```

## Routing-Modi
| Modus | Bedeutung |
|-------|-----------|
| `car`  | Auto (Standard) |
| `bike` | Fahrrad |
| `foot` | Zu Fuss |

## Rueckgabefelder (get_route)
- `distance_km` – Distanz in km
- `duration_min` – Fahrzeit in Minuten
- `duration_str` – Lesbare Fahrzeit (z.B. "1h 5min")
- `mode_label` – Modus auf Deutsch ("Auto", "Fahrrad", ...)
- `mode_icon` – Emoji (🚗, 🚲, 🚶)

## Integration
- **Telegram Bridge:** Nutzer sendet GPS-Pin, dann z.B. "Route nach Freiburg"
- Claude ermittelt Ziel-Koordinaten via `geocode_place()` und ruft routing_service.py auf
- Empfohlene Nutzung in Claude: via Bash-Tool als Subprocess
