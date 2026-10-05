# Synthese-Workflow: Neues System aus Best-of

> Entwicklung eines neuen LLM-OS/Skills aus Best-of-Elementen mehrerer Quellsysteme.

**Version:** 1.0  
**Stand:** 2026-01-18  
**Quelle:** Konsolidiert aus BACH_STREAM

---

## Übersicht

Dieser Workflow beschreibt die Entwicklung eines neuen LLM-OS/Skills aus Best-of-Elementen mehrerer Quellsysteme.

```
┌─────────────────────────────────────────────────────────┐
│              SYNTHESE-WORKFLOW (9 Phasen)               │
├─────────────────────────────────────────────────────────┤
│  1. Datensammlung (Mapping, Synopse, Tests)             │
│  2. Architektur ableiten                                │
│  3. Dossier erstellen                                   │
│  4. Anpassungen nach Feedback                           │
│  5. Wiedervostellung                                    │
│  GATE: Endabnahme                                       │
│  6. Umsetzungsphase                                     │
│  7. Ausführung                                          │
│  8. Report                                              │
│  9. Nutzer-Feedback                                     │
└─────────────────────────────────────────────────────────┘
```

**Dauer:** 8-15 Stunden (ohne Iterationen)

---

## Phase 1: Datensammlung

**Zweck:** Alle relevanten Informationen zusammentragen

### Aktivitäten

- [ ] Directory-Scans der Quellsysteme
- [ ] Feature-Analysen erstellen
- [ ] Synopsen schreiben
- [ ] Stärken-Schwächen dokumentieren
- [ ] Best-of Kandidaten identifizieren

### Werkzeuge

| Workflow | Zweck |
|----------|-------|
| `system-mapping.md` | Kartographie |
| `system-synopse.md` | Vergleich |
| `system-testverfahren.md` | Bewertung |

### Abschlusskriterium

- Alle Quellsysteme kartographiert
- Feature-Datenbank befüllt
- Mindestens eine Synopse erstellt

---

## Phase 2: Architektur ableiten

**Zweck:** Struktur des neuen Systems definieren

### Aktivitäten

- [ ] Benennungsregeln festlegen
- [ ] Formatregeln definieren (JSON, MD, TXT)
- [ ] Templates erstellen
- [ ] Ordnerstruktur entwerfen
- [ ] Generator-Vorlagen erstellen

### Abschlusskriterium

- Vollständige Ordnerstruktur dokumentiert
- Alle Regeln definiert
- Mindestens 1 Generator-Vorlage

---

## Phase 3: Dossier erstellen

**Zweck:** Konzept und Architektur dem Nutzer präsentieren

### Dossier-Format

1. Executive Summary (1 Seite)
2. Problemstellung
3. Lösungsansatz
4. Architektur-Übersicht
5. Detailentscheidungen
6. Nächste Schritte
7. Offene Fragen an Nutzer

---

## Phase 4-5: Anpassung & Wiedervostellung

**Zweck:** Iterative Verfeinerung basierend auf Feedback

### Loop-Bedingung

- Nutzer wünscht Änderungen → zurück zu Phase 4
- Nutzer zufrieden → weiter zu Gate

---

## Gate: Endabnahme

**Prüfpunkte:**

- [ ] Architektur vollständig?
- [ ] Alle Regeln definiert?
- [ ] Nutzer hat zugestimmt?
- [ ] Ressourcen verfügbar?
- [ ] Keine offenen Blocker?

| Entscheidung | Aktion |
|--------------|--------|
| FREIGABE | Weiter zu Phase 6 |
| ABLEHNUNG | Zurück zu Phase 4 |

---

## Phase 6: Umsetzungsphase

**Zweck:** Vorbereitung für Ausführung

### Aktivitäten

- [ ] Benötigte Elemente einsammeln
- [ ] Generatoren erstellen/anpassen
- [ ] Skripte vorbereiten
- [ ] Checkliste erstellen

---

## Phase 7: Ausführung

**Zweck:** Neues System erstellen

### Aktivitäten

- [ ] Ordnerstruktur anlegen
- [ ] Generatoren ausführen
- [ ] Templates befüllen
- [ ] Konfiguration setzen
- [ ] Validierung durchführen

---

## Phase 8: Report

**Zweck:** Nutzer über Ergebnis informieren

### Report-Format

1. Status: ERFOLGREICH / TEILWEISE / FEHLGESCHLAGEN
2. Was wurde erstellt
3. Abweichungen vom Plan
4. Bekannte Einschränkungen
5. Empfohlene nächste Schritte

---

## Phase 9: Nutzer-Feedback

**Zweck:** Feedback für zukünftige Iterationen

### Feedback-Kategorien

| Kategorie | Symbol |
|-----------|--------|
| Bugs | BUG |
| Verbesserungen | FEAT |
| Unklarheiten | FRAGE |
| Positives | OK |

### Loop-Bedingung

- Kritische Bugs → zurück zu Phase 6/7
- Größere Änderungen → zurück zu Phase 4
- Akzeptiert → WORKFLOW ABGESCHLOSSEN

---

## Integration mit builder.md

Dieser Workflow ist in `skills/_service/builder.md` als **SYNTHESIZE** Funktion integriert:

```yaml
builder.synthesize:
  sources: [system1, system2, ...]
  target_name: <name>
  target_path: <pfad>
```

---

## Schnell-Checkliste

```
□ Phase 1: Quellsysteme analysiert
□ Phase 2: Architektur definiert
□ Phase 3: Dossier präsentiert
□ Gate: Freigabe erhalten
□ Phase 6-7: System erstellt
□ Phase 8: Report geliefert
□ Phase 9: Feedback eingeholt
```

---

*Konsolidiert aus BACH_STREAM: 2026-01-18*
