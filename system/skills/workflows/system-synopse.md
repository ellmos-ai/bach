# System-Synopse: Vergleichende Analyse

> Vergleichende Analyse mehrerer LLM-OS oder Skills.

**Version:** 1.0  
**Stand:** 2026-01-18  
**Quelle:** Konsolidiert aus BACH_STREAM

---

## Übersicht

Dieser Workflow beschreibt die vergleichende Analyse mehrerer LLM-OS oder Skills.

```
┌─────────────────────────────────────────────────────────┐
│              SYNOPSE-WORKFLOW (4 Schritte)              │
├─────────────────────────────────────────────────────────┤
│  1. Daten sammeln                                       │
│  2. Feature-Vergleich                                   │
│  3. Bewertung (7 Dimensionen)                           │
│  4. Synopse-Dokument schreiben                          │
└─────────────────────────────────────────────────────────┘
```

**Dauer:** 2-4 Stunden

---

## Schritt 1: Daten sammeln

**Voraussetzungen:**

- [ ] Alle Systeme kartographiert (system-mapping.md)
- [ ] Feature-Datenbank befüllt
- [ ] Testergebnisse vorhanden (optional)

---

## Schritt 2: Feature-Vergleich

**Format Feature-Matrix:**

```
Feature              Sys1      Sys2      Sys3
─────────────────────────────────────────────
CLI                  ✓         ✓         ✗
Auto-Logging         ✗         ✓         ✗
Task-Manager         JSON      SQLite    JSON
Memory-System        TXT       SQLite    MD
```

---

## Schritt 3: Bewertung

### 7 Dimensionen

| Dim | Name | Beschreibung |
|-----|------|--------------|
| D1 | Onboarding | Wie schnell ist man produktiv? |
| D2 | Navigation | Wie leicht findet man sich zurecht? |
| D3 | Memory | Wie gut funktioniert Persistenz? |
| D4 | Tasks | Wie gut ist Task-Management? |
| D5 | Kommunikation | Wie klar ist die Ausgabe? |
| D6 | Tools | Wie nützlich sind die Tools? |
| D7 | Fehlertoleranz | Wie robust bei Fehlern? |

### Skala

| Wert | Bedeutung |
|------|-----------|
| 1 | Mangelhaft |
| 2 | Ausreichend |
| 3 | Befriedigend |
| 4 | Gut |
| 5 | Sehr gut |

### Berechnung

```
Gesamtnote = (D1 + D2 + D3 + D4 + D5 + D6 + D7) / 7
```

---

## Schritt 4: Synopse schreiben

### Struktur

1. Gesamtergebnis (Ranking)
2. Klassifizierung (SKILL/AGENT/OS)
3. Dimensionsvergleich
4. Stärken-Schwächen-Matrix
5. Feature-Vergleich
6. Best-of Extraktion
7. Empfehlungen
8. Fazit

### Template

```markdown
# SYNOPSE: <Thema>

Datum: <Datum>
Systeme: <Liste>
Methodik: B/O/E-Tests + Feature-Mapping

## 1. Gesamtergebnis

| Rang | System | Note | Charakter |
|------|--------|------|-----------|
| 1 | Sys1 | 4.2 | Production-ready |
| 2 | Sys2 | 3.8 | Experimentell |

## 2. Best-of Extraktion

| Feature | Bestes System | Grund |
|---------|---------------|-------|
| Memory | Sys1 | SQLite-basiert |
| CLI | Sys2 | Elegante Syntax |
```

---

## Integration mit builder.md

Dieser Workflow ist in `skills/_service/builder.md` als **COMPARE** Funktion integriert:

```yaml
builder.compare:
  systems: [system1, system2, ...]
  output: synopse.md
```

### Tool

```bash
python skills/tools/testing/compare_systems.py --systems "sys1,sys2" --output synopse.md
```

---

## Schnell-Checkliste

```
□ Alle Systeme kartographiert
□ Feature-Matrix erstellt
□ Dimensionen bewertet
□ Stärken-Schwächen dokumentiert
□ Best-of identifiziert
□ Synopse geschrieben
```

---

*Konsolidiert aus BACH_STREAM: 2026-01-18*