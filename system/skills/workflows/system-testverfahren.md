# System-Testverfahren: B/O/E-Tests

> Systematisches Testen von LLM-OS und Skills aus drei Perspektiven: Beobachtung, Ausgabe, Erfahrung (B/O/E).

**Version:** 1.0  
**Stand:** 2026-01-18  
**Quelle:** Konsolidiert aus BACH_STREAM

---

## Übersicht

Dieses Verfahren beschreibt das systematische Testen von LLM-OS und Skills aus drei Perspektiven.

```
┌─────────────────────────────────────────────────────────┐
│              DREI TESTPERSPEKTIVEN                      │
├─────────────────────────────────────────────────────────┤
│  B-Tests: BEOBACHTUNG (Extern, Automatisiert)           │
│  O-Tests: AUSGABE (Funktional, Input→Output)            │
│  E-Tests: ERFAHRUNG (Intern, Subjektiv)                 │
└─────────────────────────────────────────────────────────┘
```

**Dauer:** 10-40 Minuten pro System (je nach Profil)

---

## Phase 1: B-Tests (Beobachtung)

**Konzept:** Externe Skripte inventarisieren System

### Tests

| ID | Name | Prüft |
|----|------|-------|
| B001 | Datei-Inventar | Anzahl, Typen, Größen |
| B002 | Code-Metriken | LOC, Komplexität |
| B003 | Doku-Abdeckung | README, Comments |
| B004 | Dependency-Check | Imports, Requires |
| B005 | Struktur-Validierung | Pflichtdateien |

### Tool

```bash
python skills/tools/testing/run_external.py --system "<pfad>" --b-tests
```

---

## Phase 2: O-Tests (Ausgabe)

**Konzept:** Input → System → Output validieren

### Tests

| ID | Name | Prüft |
|----|------|-------|
| O001 | CLI-Befehle | Kommandos funktionieren |
| O002 | Task-CRUD | Erstellen/Lesen/Update/Delete |
| O003 | Memory-Operationen | Speichern/Laden |
| O004 | File-Handling | Dateizugriff |
| O005 | Error-Handling | Fehlerbehandlung |

### Format

```
Input: <Befehl/Aktion>
Erwartung: <Ergebnis>
Tatsächlich: <Ergebnis>
Status: PASS/FAIL
```

---

## Phase 3: E-Tests (Erfahrung)

**Konzept:** Claude testet System aus eigener Perspektive

### Tests

| ID | Name | Fokus |
|----|------|-------|
| E001 | SKILL.md Lesbarkeit | Verständlichkeit |
| E002 | Navigation | Orientierung |
| E003 | Task erstellen | Funktionalität |
| E004 | Task finden | Auffindbarkeit |
| E005 | Memory schreiben | Persistenz |
| E006 | Memory lesen | Retrieval |
| E007 | Tool nutzen | Usability |
| E008 | Hilfe finden | Dokumentation |
| E009 | Session starten | Onboarding |
| E010 | Gesamteindruck | Holistische Bewertung |

### Profile

| Profil | Dauer | Tests |
|--------|-------|-------|
| QUICK | 10 Min | E001, E002, E010 |
| STANDARD | 25 Min | Alle außer E008 |
| FULL | 40 Min | Alle 10 Tests |

---

## 10-Minuten-Regel

> **Wichtig:** Max 10 Minuten pro Testdurchgang
> - STANDARD in 3 Teile zerlegen
> - Persistenz zwischen Teilen nutzen
> - fc_get_time() zur Zeitmessung

---

## Klassenspezifische Tests

| Klasse | Fokus | Tests |
|--------|-------|-------|
| SKILL | Lesbarkeit | E001, E002, E010 |
| AGENT/HUB | Navigation, Tools | E001-E007, E009, E010 |
| TEXT-OS | Lifecycle, Memory | Alle E001-E010 |

---

## Ergebnis-Format

```json
{
  "meta": { 
    "system": "...", 
    "profile": "STANDARD", 
    "date": "2026-01-18"
  },
  "tests": { 
    "B001": { "status": "PASS", "score": 4 },
    "O001": { "status": "PASS", "score": 5 },
    "E001": { "status": "PASS", "score": 4, "notes": "..." }
  },
  "dimensions": { 
    "d1_onboarding": 4,
    "d2_navigation": 3
  },
  "overall_rating": 4.2,
  "summary": { 
    "strengths": ["Memory-System", "Dokumentation"],
    "weaknesses": ["CLI fehlt"],
    "recommendations": ["CLI hinzufügen"]
  }
}
```

---

## Integration mit builder.md

Dieser Workflow ist in `skills/_service/builder.md` als **TEST** Funktion integriert:

```yaml
builder.test:
  system: <pfad>
  profile: QUICK | STANDARD | FULL
```

### Tool

```bash
python skills/tools/testing/run_external.py --system "<pfad>" --profile STANDARD
```

---

## Schnell-Checkliste

```
□ Profil gewählt
□ B-Tests ausgeführt
□ O-Tests ausgeführt
□ E-Tests durchgeführt
□ Ergebnis als JSON gespeichert
□ In Synopse integriert (falls mehrere Systeme)
```

---

*Konsolidiert aus BACH_STREAM: 2026-01-18*