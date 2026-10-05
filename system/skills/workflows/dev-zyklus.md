# BACH Entwicklungszyklus (Dev-Zyklus)

**Version:** 1.0.0

> **Ziel:** Strukturierter Ablauf von Feature-Wunsch bis validiertem System.
> Jede Entwicklung durchlaeuft diese 8 Phasen.

---

## Uebersicht

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                    BACH ENTWICKLUNGSZYKLUS                       │
  ├──────────────────────────────────────────────────────────────────┤
  │                                                                  │
  │  Phase 1   Feature-Wuensche (Anforderungen funktional)           │
  │     │                                                            │
  │     ▼                                                            │
  │  Phase 2   Ist-Stand pruefen (Was gibt es schon?)                │
  │     │                                                            │
  │     ▼                                                            │
  │  Phase 3   Funktionale Planung                                   │
  │            (Workflows, Agenten, Experten, Skills, Services)      │
  │     │                                                            │
  │     ▼                                                            │
  │  Phase 4   Functional Frontend implementieren                    │
  │            (Skill-Dateien, Workflow-Markdown, Agent-Profile)      │
  │     │                                                            │
  │     ▼                                                            │
  │  Phase 5   Backend planen und ausrichten                         │
  │            (CLI-Handler, DB-Schema, API-Endpoints)               │
  │     │                                                            │
  │     ▼                                                            │
  │  Phase 6   Backend-Aufgaben umsetzen                             │
  │            (Python-Code, Tools, DB-Migrationen)                  │
  │     │                                                            │
  │     ▼                                                            │
  │  Phase 7   Technische Tests und Bugfixes                         │
  │            (B/O/E-Tests, Bugfix-Protokoll)                       │
  │     │                                                            │
  │     ▼                                                            │
  │  Phase 8   Funktions- und Featuretest: USECASES                  │
  │            (End-to-End Validierung aus Nutzersicht)               │
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘

  Grundprinzipien durchgaengig:
  - Systemisch First (../docs/WICHTIG_SYSTEMISCH_FIRST.md)
  - CLI First (alles ueber Terminal steuerbar)
  - dist_type Isolation (User-Daten getrennt)
```

---

## Phase 1: Feature-Wuensche (Anforderungen funktional)

**Was:** Funktionale Anforderungen sammeln und formulieren.

**Eingabe:**
- User-Wuensche, Ideen, Probleme
- Partner-Vorschlaege (Gemini, Claude)
- Erkenntnisse aus Usecases (Rueckkopplung!)

**Ergebnis:**
- Tasks im Task-System: `bach task add "Feature: ..." --prio P2`
- Anforderung beschreibt WAS gewuenscht ist, nicht WIE

**Regeln:**
- Anforderungen immer funktional formulieren ("User kann X tun")
- Nicht technisch ("Implementiere REST-Endpoint fuer X")
- Usecases als Anforderungsquelle nutzen (Phase 8 -> Phase 1)

---

## Phase 2: Ist-Stand pruefen

**Was:** Vorhandene Funktionalitaet inventarisieren.

**Checkliste:**
```
  [ ] bach tools search <begriff>       Gibt es schon ein Tool?
  [ ] bach --help <thema>               Gibt es schon Help dazu?
  [ ] skills/ Ordner pruefen            Gibt es Agents/Experten/Services?
  [ ] DB-Schema pruefen                 Gibt es schon Tabellen?
  [ ] Usecases pruefen                  Wurde etwas Aehnliches getestet?
```

**Ergebnis:**
- Dokumentation was existiert, was fehlt, was erweitert werden muss
- Vermeidung von Duplikaten (Tools sind die Haende der LLMs!)

---

## Phase 3: Funktionale Planung

**Was:** Auf der funktionalen Ebene planen - NICHT sofort Code schreiben.

**Planungs-Ebenen:**

| Ebene | Frage | Artefakt |
|-------|-------|----------|
| Workflow | WANN/WIE wird koordiniert? | skills/workflows/*.md |
| Agent | WER fuehrt aus? | agents/*.txt |
| Experte | WER hat Fachwissen? | agents/_experts/*/ |
| Skill | WAS wird getan? | hub/_services/*.md |
| Service | WIE wird es technisch getan? | hub/_services/*/ |

**Regeln:**
- Erst funktional denken, dann technisch
- Workflows beschreiben Ablaeufe, keine Implementierungsdetails
- Jeder Agent braucht ein klares Profil
- Services muessen ohne User-Daten funktionieren (Systemisch First)

---

## Phase 4: Functional Frontend implementieren

**Was:** Skill-Dateien, Workflow-Markdown, Agent-Profile erstellen.

Das "Frontend" ist hier die funktionale Beschreibungsebene:
- Workflow-Dateien (.md) in skills/workflows/
- Agent-Profile (.txt) in agents/
- Experten-Wissen in agents/_experts/
- Service-Beschreibungen in hub/_services/
- Help-Dateien in skills/docs/help/

**Ergebnis:**
- Alle funktionalen Beschreibungen existieren
- Ein LLM-Partner koennte den Workflow lesen und verstehen
- Die funktionale Ebene ist komplett dokumentiert

---

## Phase 5: Backend planen und ausrichten

**Was:** Technische Architektur auf das funktionale Frontend ausrichten.

**Planungs-Bereiche:**

| Bereich | Frage | Ort |
|---------|-------|-----|
| CLI-Handler | Welche bach-Befehle? | hub/*.py |
| DB-Schema | Welche Tabellen/Spalten? | data/schema_*.sql |
| API-Endpoints | Welche GUI-Endpunkte? | gui/server.py |
| Tools | Welche Python-Scripts? | skills/tools/*.py |
| Injektoren | Welche Keywords triggern? | skills/tools/injectors.py |

**Ergebnis:**
- Technischer Plan der sich am funktionalen Frontend orientiert
- DB-Schema-Entwurf
- CLI-Befehlsstruktur

---

## Phase 6: Backend-Aufgaben umsetzen

**Was:** Python-Code schreiben, DB-Migrationen, CLI-Handler.

**Checkliste (pro Aufgabe):**
```
  [ ] Funktioniert ohne User-Daten (leere DB)?
  [ ] CLI-Befehl vorhanden?
  [ ] Input kann aus Dateien/Ordnern kommen?
  [ ] Output geht in strukturierte DB?
  [ ] dist_type wird automatisch gesetzt?
  [ ] Scan/Import ist wiederholbar (idempotent)?
  [ ] Kein Hardcoded-Pfad?
  [ ] Tool registriert: bach tools register
  [ ] Help-Datei erstellt: skills/docs/help/skills/tools/<name>.txt
```

Ref: ../docs/WICHTIG_SYSTEMISCH_FIRST.md

---

## Phase 7: Technische Tests und Bugfixes

**Was:** Technische Korrektheit sicherstellen.

**Test-Typen (B/O/E):**

| Typ | Perspektive | Workflow |
|-----|-------------|----------|
| B-Tests | Extern/Automatisiert | system-testverfahren.md |
| O-Tests | Funktional (Input->Output) | system-testverfahren.md |
| E-Tests | Subjektiv/Erfahrung | system-testverfahren.md |

**Bei Bugs:**
- Bugfix-Protokoll anwenden: skills/workflows/bugfix-protokoll.md
- 20-Minuten-Regel beachten
- Lessons Learned dokumentieren: `bach lesson add "..."`

---

## Phase 8: Funktions- und Featuretest - USECASES

**Was:** End-to-End Validierung aus Nutzersicht.

**Usecases sind BEIDES:**
1. **Feature-Hinweisgeber** - Was ist gewuenscht? Was soll moeglich sein?
2. **Test-Szenarien** - Funktioniert es wirklich von A bis Z?

**Usecase-Format:**
```
  USECASE_NNN: Kurztitel

  VORBEDINGUNG: Was muss vorhanden sein?
  EINGABE:      Was gibt der User ein / welche Daten?
  ERWARTUNG:    Was soll herauskommen?
  PRUEFT:       Welche Komponenten werden getestet?
```

**Bestehende Usecases (Stand 2026-01-28):**

| ID | Titel | Status | Prueft |
|----|-------|--------|--------|
| USECASE_001 | Lebenslauf-Agent | done | CV-Generator, Ordner-Scan |
| USECASE_002 | Office Lens Scanner | pending | OCR, Kategorisierung |
| USECASE_003 | Dokumenten-Suche | done | doc_search, Steuernummer |
| USECASE_004 | Arzt-Berichte | done | OCR, Gesundheit, Zusammenfassung |
| USECASE_005 | Haushalts-Routinen | done | household_routines, Kalender |
| USECASE_006 | Versicherungs-Beratung | done | Versicherungs-Check, Empfehlung |

**Rueckkopplung:**
- Fehlgeschlagene Usecases -> neue Tasks in Phase 1
- Erfolgreiche Usecases -> validierte Features
- Neue Usecase-Ideen -> Task erstellen: `bach task add "USECASE_NNN ..."`

---

## Zusammenfassung: Der Kreislauf

```
  Phase 8 (Usecases)
       │
       │ Neue Anforderungen / Bugs
       ▼
  Phase 1 (Feature-Wuensche)  ──►  Phase 2 (Ist-Stand)
       ▲                                    │
       │                                    ▼
  Phase 7 (Tests/Bugs)         Phase 3 (Funktionale Planung)
       ▲                                    │
       │                                    ▼
  Phase 6 (Backend Code)       Phase 4 (Functional Frontend)
       ▲                                    │
       │                                    ▼
       └──────────────────── Phase 5 (Backend Planung)
```

Der Zyklus ist ein Kreislauf: Usecases validieren Features und
generieren gleichzeitig neue Anforderungen.

---

## Siehe auch

- ../docs/WICHTIG_SYSTEMISCH_FIRST.md - Kernprinzip
- skills/workflows/system-testverfahren.md - B/O/E-Tests
- skills/workflows/bugfix-protokoll.md - Fehlerkorrektur
- skills/docs/help/dev.txt - Kurzreferenz Entwicklungsmodus
- skills/docs/help/usecase.txt - Usecase-Dokumentation

---

*Erstellt: 2026-01-28 | BACH Entwicklungszyklus v1.0*