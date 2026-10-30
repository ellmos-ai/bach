---
name: newspaper
version: 1.0.0
type: service
author: BACH Team
created: 2026-10-30
updated: 2026-10-30
last_updated: 2026-10-30
anthropic_compatible: true
status: active
dependencies: []
description: >
  Erzeugt Berichte aus ungelesenen news_items der BACH-DB: gruppiert nach
  Kategorie, rendert HTML aus templates/ und schreibt daraus ein PDF via
  Edge Headless; Konfiguration in config.json.
---

# Newspaper Generator

**Kategorie:** Systemdienst (Berichte)

## Zweck
Der Newspaper Generator liest ungelesene `news_items` aus der BACH-DB,
gruppiert sie nach Kategorie, rendert HTML aus `templates/` und erzeugt
daraus ein PDF via Edge Headless. Die Konfiguration (Quellen, Layout,
Ausgabepfade) erfolgt ueber config.json.

## Nutzung
Einsatz als Service-Modul:
```bash
python newspaper_generator.py
```

## Dateien
- `newspaper_generator.py` — Generator (DB-Lese, Gruppierung, Render, PDF)
- `config.json` — Konfiguration
- `templates/` — HTML-Vorlagen fuer die Berichte