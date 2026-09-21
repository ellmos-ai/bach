---
name: stigmergy-service
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
    - shared_memory_working (User-DB) als Pheromon-Traeger
  workflows: []

description: >
  Pheromon-basierte Schwarm-Koordination (MASTERPLAN SQ051).
  Agenten kommunizieren indirekt ueber Markierungen in der Umgebung —
  wie Ameisen Pheromone hinterlassen. BACH-Implementierung: Eintraege
  im Namespace 'stigmergy' der shared_memory_working-Tabelle mit
  Staerke-Metadaten, Verfall und Pfad-Auswahl.
---

# Stigmergy Service

**Kategorie:** Schwarm-Koordination
**Integration:** `tools/schwarm/stigmergy_pattern.py` (Wrapper,
CLI: `python -m tools.schwarm.stigmergy_pattern "Aufgabe" --agents 3 --rounds 2`)
**Handler:** keiner eigenstaendig — Nutzung ueber Schwarm-Tools

---

## Zweck

Indirekte Koordination von Schwarm-Agenten ohne zentrale Steuerung
(Konzept: vernunft_kantian.txt, V009 Self-Extension/Autonomie).
Agenten hinterlassen Pheromone (Markierungen), andere Agenten lesen
diese und waehlen vielversprechende Pfade.

Tabellen-Mapping auf `shared_memory_working`:
- `type` = 'note'
- `content` = JSON: {namespace, path_id, strength, metadata, agent_id, timestamp}
- `tags` = '["stigmergy"]'
- `related_to` = path_id (schnelles Filtern)
- `priority` = int(strength * 10) (Skala 0-10)

---

## API

Klasse: `StigmergyAPI(db_path, agent_id='anonymous')`

| Methode | Wirkung |
|---|---|
| `deposit(path_id, strength=1.0, metadata=None)` | Pheromon hinterlassen |
| `sense(path_prefix='')` | Pheromone lesen (Liste von Dicts) |
| `evaporate(decay_rate=0.1)` | Staerke aller Pheromone verringern (Verfall), liefert Anzahl betroffener Zeilen |
| `get_best_path(path_prefix='')` | Staerksten Pfad ermitteln |
| `dump()` | Gesamten Namespace ausgeben |

Modul-Funktionen (Convenience):
`deposit_pheromone(...)`, `sense_pheromones(db_path, path_prefix='')`,
`get_best_pheromone_path(db_path, path_prefix='')`

---

## Abhaengigkeiten

- sqlite3 (User-DB)
- Tabelle `shared_memory_working` in User-DB
- keine externen Dienste