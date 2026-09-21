---
name: household
version: 1.0.0
type: service
author: BACH Team
created: 2026-01-23
updated: 2026-09-18
anthropic_compatible: true
status: concept

dependencies:
  tools: []
  services: []
  workflows: []

description: >
  Household Service für Lagerhaltung und Medikamentenmanagement. Kombiniert
  'HausLagerist' und 'MediPlaner'.
---
# Household Service

**Haushalts-Organisation, Vorräte und Gesundheit**

> **HINWEIS:** Dieser Service ist eine Konsolidierung von `HausLagerist` (Vorräte) und `MediPlaner` (Gesundheit).

## Übersicht

Der Household Service bietet Funktionen zur Verwaltung von physischen Beständen (Vorratsschrank) und medizinischen Bedürfnissen (Medikamente, Einnahmepläne, Rezeptbestellungen).

## Module

### 1. Inventory (HausLagerist)

* Verwaltung von Vorräten
* Scan-In / Scan-Out Logik (Barcode)
* Automatische Einkaufslisten
* Order-Engine mit Pull-Faktoren

### 2. Health (MediPlaner)

* Klienten-Verwaltung
* Medikamentenpläne
* Bestandsberechnung basierend auf Verbrauch
* Erinnerungen und Warnungen (Ampel-System)

## Ordnerstruktur

```text
household/
├── SKILL.md            # Diese Datei
└── stubs/              # Extrahierter Code (Stubs)
    ├── inventory.py    # HausLagerist Logik
    ├── health.py       # MediPlaner Logik
    └── models.py       # Gemeinsame Datenmodelle
```

## Status

* [x] Struktur angelegt
* [x] DB-Schema konsolidiert (schema_household.sql) - 2026-01-25
* [ ] Hardware-Integration (Barcode-Scanner) prüfen
* [ ] API definieren
