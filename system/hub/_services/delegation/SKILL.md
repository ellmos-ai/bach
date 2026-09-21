---
name: delegation-compat-layer
version: 1.0.0
type: service
author: BACH Team
created: 2026-09-17
updated: 2026-09-17
anthropic_compatible: true
status: active

dependencies:
  tools: []
  services:
    - externer clutch-Scorer (optional, via BACH_CLUTCH_PATH)
    - hub/_archive/delegation_legacy (Notfall-Fallback)
  workflows: []

description: >
  Compat-Layer fuer die Delegations-Bausteine. BACH importiert alle
  Delegations-Funktionalitaet ueber genau diesen Einstiegspunkt.
  Der externe clutch-Scorer wird bevorzugt (provider-neutrale Quelle
  der Wahrheit); der ehemalige BACH-Fork liegt nur noch als archivierter
  Notfall-Fallback unter hub/_archive/delegation_legacy.
---

# Delegation Service (Compat-Layer)

**Kategorie:** Partner- & Delegationslogik
**Integration:** `hub/clutch.py`, `hub/partner.py`
**Handler:** keiner eigenstaendig — Nutzung ueber Clutch-/Partner-Handler

---

## Zweck

Einziger Import-Einstiegspunkt fuer Delegations-Bausteine (Scorer,
Gas/Bremse, Fahrtenbuch, Strecken-Analyse, Alerts). Haelt die Koppelung
an den externen clutch-Scorer hermetisch: BACH-Code kennt nur dieses
Paket, nicht die clutch-Interna.

Scorer-Quelle (Modul-Konstante `SCORER_SOURCE`): bevorzugt externer
clutch-Scorer, sonst Legacy-Fallback aus `hub/_archive/delegation_legacy`.

---

## API

Exportierte Symbole (via `from hub._services.delegation import ...`):
- `OverkillAlert`, `TokenExplosionAlert`
- `GasStellung`, `PromptStrategie`, `berechne_gas`, `get_gas_bremse`
- `FahrtenbuchEintrag`, `get_fahrtenbuch`
- `StreckenProfil`, `analysiere_task`, `get_analyser`
- `get_bordcomputer`, `get_fahrschule`

Partner-Zonen-Regeln (`_PARTNER_ZONE_RULES`):
- Zone 1: external_ai / local_ai / human, Kosten low-medium-high-free
- Zone 2: wie Zone 1, ohne high
- Zone 3: local_ai / human, low/free
- Zone 4: nur human, free

Environment:
- `BACH_CLUTCH_PATH` — Pfad zum externen clutch-Scorer
- `BACH_DISABLE_EXTERNAL_CLUTCH` — erzwingt Legacy-Fallback

---

## Abhaengigkeiten

- externer clutch-Scorer (optional; fehlt → Legacy-Fallback)
- `hub/_archive/delegation_legacy` (Fork, nur Notfall-Fallback)
- sqlite3 (Delegations-Statistiken/Fahrtenbuch in User-DB)