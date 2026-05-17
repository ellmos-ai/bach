# Workflow: Help-Expert-Review

**Version:** 1.4.0
**Erstellt:** 2026-02-09
**Vorgaenger:** help-forensic.md (90-Agenten Ansatz)
**Modell:** Opus 4.6 (eine Instanz)
**Recurring:** Nein (manuell bei Bedarf)

---

## Zweck

Alle Help-Dateien in einem Durchlauf durch EINEN Experten-Agenten pruefen und
korrigieren. Unterschied zur Help-Forensik: Statt 90 paralleler Agenten mit
je minimaler Systemkenntnis arbeitet EIN Agent mit maximalem Systemkontext.

**Kernprinzip:** Erst Experte werden, dann korrekturlesen.

**Vorteile gegenueber Help-Forensik:**
- Agent kennt das GESAMTE System (keine isolierten Fehlurteile)
- Konsistenz: Ein Agent, eine Stimme, ein Wissensstand
- ~2.5x schneller (35 Min vs 90 Min gemessen)
- ~20x weniger Compute (35 Agent-Min vs 720 Agent-Min)
- Keine widerspruechtlichen Korrekturen zwischen Agenten
- Kreuzreferenzen zwischen Help-Dateien werden erkannt

**Nachteile:**
- Context Window Limit: ~200k Tokens muessen reichen
- Bei Abbruch muss man wissen wo man war

---

## Gemessene Zeiten (2026-02-09)

20 Help-Dateien parallel gelesen + analysiert: **34 Sekunden**

| Phase | Dauer | Methode |
|-------|-------|---------|
| Reines Lesen (93 Dateien) | ~3 Min | 5 Batches a 20 parallel |
| Analyse + Fehler erkennen | ~12 Min | Im selben Turn, mental |
| Korrekturen anwenden | ~5 Min | Edit-Calls / Sub-Agenten |
| **Phase 2 gesamt** | **~20 Min** | |
| Phase 1 (Kontext-Aufbau) | **~15 Min** | Exploration-Heuristik |
| **GESAMT** | **~35 Min** | |

---

## Umfang

| Kategorie | Pfad | Dateien | Prioritaet |
|-----------|------|---------|------------|
| **Core** | `docs/help/*.txt` | ~93 | HOCH (immer pruefen) |
| **Tools** | `docs/help/tools/*.txt` | ~81 | MITTEL (bei Bedarf) |
| **Wiki** | `wiki/**/*.txt` | ~258 | NIEDRIG (nur Stichproben) |

**Regelmaessiger Durchlauf:** Nur Core (~93 Dateien)
**Vollstaendiger Durchlauf:** Core + Tools (~174 Dateien)
**Wiki** wird separat behandelt (eigener Workflow, andere Regeln)

---

## Phase 1: Dreistufiger Wissensaufbau (KRITISCH)

### Guete-Hierarchie (hoechste Guete gewinnt bei Widerspruch)

```
GUETE 3 (HOECHSTE):  Echte Exploration + Directory Scan
                      Was das Dateisystem JETZT zeigt
                      → Ueberschreibt alles darunter

GUETE 2 (MITTEL):    Code-Dateien lesen
                      bach_paths.py, registry.py, schema.sql, bach.py
                      → Ueberschreibt SKILL.md bei Abweichung

GUETE 1 (NIEDRIGSTE): SKILL.md / ROADMAP.md / Help-Dateien
                       Dokumentation die veraltet sein kann
                       → Nur als Ausgangshypothese nutzen
```

**Kernregel:** Wenn Exploration etwas anderes zeigt als SKILL.md behauptet,
gilt die Exploration. Abweichungen zaehlen STAERKER und ueberschreiben
das Vorwissen aus SKILL.md in der mentalen Repraesentation.

---

### 1.1 Stufe I: SKILL.md lesen (Vorwissen, Guete 1)

Alle verfuegbaren SKILL.md-Dateien lesen um eine ERSTE mentale Karte
des Systems zu bilden. Dieses Wissen ist eine Hypothese, kein Fakt.

```
Lesen (als Ausgangsbasis):
  1. system/ROADMAP.md                    → Vision, Phasen, Architektur-Diagramm
  2. system/CHANGELOG.md                  → Was hat sich geaendert
  3. system/BUGLOG.md                     → Bekannte Probleme
  4. system/docs/help/practices.txt            → Architektur-Prinzipien
  5. system/docs/help/strategic.txt            → Metakognition

Optional (bei Bedarf fuer Kontext):
  6. agents/*/SKILL.md            → Agent-Definitionen
  7. agents/_experts/*/SKILL.md           → Experten-Definitionen
```

**Ergebnis:** Erste mentale Karte. Markiert als "HYPOTHESE - noch nicht verifiziert".

---

### 1.2 Stufe II: Echte Exploration (Realitaet, Guete 2-3)

Jetzt das System WIRKLICH erkunden. Wie ein neuer Mitarbeiter:
Jeden Raum betreten, schauen was da ist, README lesen falls vorhanden.

**Abweichungen von Stufe I zaehlen STAERKER und ueberschreiben das
Vorwissen in der mentalen Repraesentation.**

**Exploration-Heuristik ("Jeden Raum betreten"):**

```
FUER jeden Ordner in system/:
  1. ls [ordner]/                    → Was liegt hier WIRKLICH?
  2. Falls README.md vorhanden:      → Lesen (Ordner-Wegweiser)
  3. Falls SKILL.md vorhanden:       → Lesen, mit Stufe-I-Wissen vergleichen
  4. Falls *.py vorhanden:           → Dateinamen merken (was existiert?)
  5. Falls Unterordner vorhanden:    → Rekursiv (max Tiefe 2)
  6. ABWEICHUNG NOTIEREN:           → "SKILL.md sagt X, Realitaet zeigt Y"
```

**Konkrete Exploration (in dieser Reihenfolge):**

```
RUNDE 1 - System-Kern (Guete 3: Dateisystem-Wahrheit):
  ls system/                         → Ueberblick
  ls system/core/                    → Registry, App, DB
  ls system/hub/                     → ALLE Handler (= alle CLI-Befehle!)
  ls system/hub/_services/           → Hintergrund-Services
  ls system/data/                    → Datenbanken, Logs
  ls system/db/                      → Schema

RUNDE 2 - Skills & Tools (Guete 3):
  ls system/skills/                  → Ueberblick
  ls system/agents/          → Agenten (+ jedes README.md/SKILL.md)
  ls system/agents/_experts/         → Experten
  ls system/skills/_services/        → Services
  ls system/partners/        → LLM-Partner
  ls system/connectors/      → Runtime-Adapter
  ls system/skills/workflows/        → Workflow-Definitionen
  ls system/skills/_templates/       → Templates
  ls system/tools/                   → Standalone Tools

RUNDE 3 - Peripherie (Guete 3):
  ls system/gui/                     → Dashboard
  ls system/gui/api/                 → REST-APIs
  ls system/docs/help/                    → Help-Dateien selbst (Bestand zaehlen)
  ls ../user/                        → User-Daten Struktur
  ls ../docs/                        → Konzepte und Dokumentation
```

**Schluessel-Code-Dateien lesen (Guete 2: Code-Wahrheit):**

```
  system/hub/bach_paths.py           → Kanonische Pfade (was ist wo?)
  system/core/registry.py            → Welche Handler existieren wirklich?
  system/db/schema.sql               → Welche DB-Tabellen existieren?
  system/bach.py                     → CLI-Routing (was wird wie aufgerufen?)
```

---

### 1.3 Stufe III: Directory Scan lesen (hoechste Guete)

Den aktuellen Directory-Scan als Gesamtbild laden.
Dies ist die hoechste Wahrheitsquelle: Ein vollstaendiger Snapshot
des Dateisystems mit Hashes und Zeitstempeln.

```
Lesen:
  system/data/directory_truth.json   → Kompletter Filesystem-Snapshot
                                       (233 KB, ~1500+ Dateien mit Hashes)

Erzeugt von: system/tools/c_dirscan.py (DirectoryScanner)
Aktualisiert bei: Startup (IST-Vergleich) und Shutdown (SOLL-Update)
```

**Aus dem Directory Scan extrahieren:**
- Welche Dateien existieren WIRKLICH (nicht nur laut Doku)
- Welche Ordner existieren (Doppelstrukturen erkennen!)
- Zeitstempel: Was wurde zuletzt geaendert?
- Geloeschte Dateien: Was fehlt das erwartet wird?

---

### 1.4 Mentale Repraesentation bilden

Nach den drei Stufen hat der Agent ein geschichtetes Wissensmodell:

```
┌─────────────────────────────────────────────────────────┐
│ MENTALE REPRAESENTATION                                  │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Guete 3 (Directory Scan + Exploration):                 │
│  "hub/ hat 47 .py Dateien → 47 moegliche Handler"       │
│  "data/ enthaelt bach.db, registry.db, archive.db"       │
│  "partners/ hat claude/, gemini/, ollama/"        │
│                                                          │
│  Guete 2 (Code gelesen):                                 │
│  "bach_paths.py definiert 62 Pfade"                      │
│  "schema.sql hat 123 Tabellen"                           │
│  "registry.py entdeckt Handler via Classname-Convention"  │
│                                                          │
│  Guete 1 (SKILL.md/ROADMAP - NUR wo nicht widerlegt):    │
│  "ROADMAP sagt Phase 16 abgeschlossen"                   │
│  "BUGLOG listet 5 offene Bugs"                           │
│                                                          │
│  ABWEICHUNGEN (Guete 3 > Guete 1):                       │
│  "SKILL.md sagt 11 Agenten, ls zeigt 10 → 10 ist korrekt"│
│  "Help sagt system/logs/, ls zeigt nur data/logs/"       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Selbsttest:** Agent fasst sein Verstaendnis in 10 Saetzen zusammen.
Explizit benennen welche Abweichungen gefunden wurden.
Wenn Luecken → weitere Dateien lesen bevor Phase 2 beginnt.

---

## Phase 2: Streaming-Review (Lesen → Sofort Reagieren → Weiter)

### 2.1 Sequentielles Lesen mit sofortigem Dispatch

Der Agent liest EINE Help-Datei nach der anderen. Nach JEDER Datei wird
sofort reagiert - nicht erst alle lesen und dann korrigieren.

```
FUER jede Help-Datei (alphabetisch oder nach Prioritaet):

  1. LESEN:     Datei komplett lesen
  2. VERSTEHEN: Gegen internes Wissensmodell abgleichen
  3. BEWERTEN:  Fehler? → Schweregrad bestimmen
  4. DISPATCH:  Sofort passenden Sub-Agenten losschicken
  5. WEITER:    Naechste Datei lesen (nicht auf Sub-Agent warten!)
```

### 2.2 Dreistufiges Dispatch-Modell

Sofort nach Erkennung eines Fehlers wird der passende Agent losgeschickt:

```
┌─────────────────────────────────────────────────────────────────┐
│  FEHLER ERKANNT                                                  │
│                                                                  │
│  Sicher + Klein?          → HAIKU losschicken                   │
│  "Zeile 60: *.txt statt *.md"   Praezise Edit-Anweisung        │
│  Kosten: ~20K Tokens, ~10 Sek                                  │
│                                                                  │
│  Unsicher / Koennte Fehler sein?  → SONNET losschicken          │
│  "Zeile 41: 114 Tabellen -       Auftrag: Pruefe ob dist_type  │
│   stimmt das wirklich?"           in allen Tabellen vorkommt,   │
│                                   korrigiere NUR wenn Verdacht  │
│                                   bestaetigt.                   │
│  Kosten: ~40K Tokens, ~20 Sek                                  │
│                                                                  │
│  Grosses Problem / Strukturell?   → OPUS losschicken            │
│  "Ganze Sektion veraltet,         Kontext mitgeben,             │
│   muss neu geschrieben werden"    Spielraum fuer Entscheidungen │
│  Kosten: ~80K Tokens, ~45 Sek                                  │
│                                                                  │
│  Kein Fehler?             → Nichts tun, weiter lesen            │
└─────────────────────────────────────────────────────────────────┘
```

**KRITISCHE REGEL:** Der Expert-Agent (Opus) macht KEINE eigenen Fixes!
Er liest NUR, versteht, bewertet, delegiert und liest weiter.
ALLE Korrekturen gehen an Sub-Agenten (Haiku/Sonnet/Opus).
Der Hauptthread bleibt ein reiner Lese- und Bewertungs-Strom.

### 2.3 Pruefraster pro Datei

Gegen das Wissensmodell pruefen:

```
[ ] PFADE:     Existieren alle referenzierten Pfade? Kanonisch?
[ ] BEFEHLE:   Existiert der Handler in hub/? Korrekte Syntax?
[ ] TABELLEN:  Existieren referenzierte DB-Tabellen in schema.sql?
[ ] URLs:      Korrekt formatiert? (http:// nicht http:/)
[ ] FEATURES:  Stimmt Status (implementiert/geplant)?
[ ] QUERVERWEISE: Stimmen Verweise auf andere Help-Dateien?
[ ] HEADER:    Portabilitaet, Version, Validierungsdatum korrekt?
```

### 2.4 Korrektur-Regeln

**WICHTIG: Das Hauptmodell korrigiert NICHTS selbst. Alles wird delegiert.**

**AN HAIKU DELEGIEREN (sicher + klein):**
- Falsche Pfade → praezise Edit-Anweisung
- URL-Fehler (z.B. `http:/` statt `http://`)
- Falsche Zahlen/Versionen wenn klar
- Veraltete Optionen/Flags
- Validierungsdatum aktualisieren

**AN SONNET DELEGIEREN (unsicher, Pruefauftrag):**
- "Stimmt diese Zahl?" → Sonnet soll pruefen + ggf. korrigieren
- "Existiert dieser Pfad noch?" → Sonnet soll nachschauen
- Falsche DB-Referenzen → Sonnet soll schema.sql pruefen

**AN OPUS DELEGIEREN (gross, strukturell):**
- Ganze Sektion veraltet → Opus soll neu schreiben
- Konzeptionelle Fehler → Opus mit Systemkontext
- Mehrere zusammenhaengende Fehler in einer Datei

**NICHT KORRIGIEREN (nur dokumentieren):**
- Geplante Features die noch nicht existieren
- Konzeptionelle Aenderungen → als Task erstellen
- Unklare Faelle → Liste fuer Nutzer-Entscheidung

### 2.5 Streaming-Ablauf (Beispiel)

```
Expert liest abo.txt        → OK, kein Fehler → weiter
Expert liest actors.txt     → OK → weiter
Expert liest agents.txt     → URL-Bug Zeile 132! Sicher → Haiku losschicken
                               ↓ (Haiku arbeitet im Hintergrund)
Expert liest anbieter.txt   → "114 Tabellen" - stimmt das? → Sonnet losschicken
                               ↓ (Sonnet prueft im Hintergrund)
Expert liest architecture.txt → Ganze Sektion veraltet → Opus losschicken
                               ↓ (Opus schreibt im Hintergrund)
Expert liest arrow.txt      → OK → weiter
...
```

**Sub-Agent Anweisungen nach Modell:**

Haiku (sicher, klein):
```
"In docs/help/agents.txt Zeile 132: Aendere http:/127.0.0.1 zu http://127.0.0.1
 Dasselbe in Zeile 133 und 134. Read file first, then Edit."
```

Sonnet (unsicher, Pruefauftrag):
```
"In docs/help/distribution.txt Zeile 41 steht '114 Tabellen nutzen dist_type'.
 Pruefe in db/schema.sql wie viele CREATE TABLE dist_type enthalten.
 Korrigiere die Zahl NUR wenn der Verdacht stimmt."
```

Opus (gross, strukturell):
```
"In docs/help/architecture.txt ist die Sektion 'Handler-Map' (Zeile 45-80) veraltet.
 Seit v2.0 gibt es Auto-Discovery via core/registry.py. Schreibe die Sektion
 komplett neu basierend auf dem aktuellen System."
```

### 2.6 Fortschritts-Tracking

Bei Context-Window-Knappheit: Fortschritt als Datei speichern:
```
data/logs/help_expert_review_YYYY-MM-DD_progress.txt
```

Format:
```
[x] abo.txt           - OK
[x] actors.txt        - 1 Fix (CLI-Befehl veraltet)
[x] agents.txt        - 3 Fixes (URLs, Pfad)
[ ] architecture.txt  - (noch nicht geprueft)
```

---

## Phase 3: Abschluss-Bericht

Datei: `data/logs/help_expert_review_YYYY-MM-DD.md`

```markdown
# Help-Expert-Review Bericht

**Datum:** YYYY-MM-DD
**Agent:** Opus 4.6 (Expert-Review Workflow v1.1)
**Scope:** Core (93 Dateien)
**Dauer:** NN Minuten

## Statistik

| Metrik | Wert |
|--------|------|
| Dateien geprueft | NN |
| Dateien korrigiert | NN |
| Einzelne Fixes | NN |
| Sub-Agenten gestartet | NN |
| Neue Tasks erstellt | NN |
| Offene Entscheidungen | NN |

## Haeufigste Fehlertypen

1. [Typ]: NN Vorkommen
2. [Typ]: NN Vorkommen

## Korrigierte Dateien

| Datei | Fixes | Details |
|-------|-------|---------|
| [name].txt | N | [Kurzbeschreibung] |

## Offene Punkte (Nutzer-Entscheidung)

- [ ] [Punkt 1]
- [ ] [Punkt 2]
```

---

## Ausfuehrung

### Manueller Start (Claude Code)

```
Prompt an Opus 4.6:

"Du bist der Help-Expert-Review Agent fuer BACH.
Arbeitsverzeichnis: %ONEDRIVE_AI_ROOT%\BACH\system
Workflow-Definition: skills/workflows/help-expert-review.md

PHASE 1 - DREISTUFIGER WISSENSAUFBAU (~15 Min):

Stufe I (Vorwissen, Guete 1):
Lies ROADMAP.md, CHANGELOG.md, BUGLOG.md, docs/help/practices.txt,
docs/help/strategic.txt. Das ist deine Ausgangshypothese.

Stufe II (Echte Exploration, Guete 2-3):
Erkunde JEDEN Ordner unter system/ (ls, README lesen).
Lies bach_paths.py, registry.py, schema.sql, bach.py.
ABWEICHUNGEN zu Stufe I notieren - sie UEBERSCHREIBEN dein Vorwissen!

Stufe III (Directory Scan, hoechste Guete):
Lies data/directory_truth.json fuer den kompletten Filesystem-Snapshot.

Bilde deine mentale Repraesentation. Beschreibe in 10 Saetzen
dein Systemverstaendnis inkl. gefundener Abweichungen (Selbsttest).

PHASE 2 - STREAMING-REVIEW (~20 Min):
Lies docs/help/*.txt EINZELN, eine nach der anderen.
Pruefe jede gegen dein Wissensmodell (Guete-Hierarchie beachten!).
DU SELBST KORRIGIERST NICHTS - du liest NUR und delegierst:
- Sicherer kleiner Fehler → Haiku Sub-Agent losschicken (Task Tool, model=haiku)
- Unsicher ob Fehler → Sonnet Sub-Agent mit Pruefauftrag (Task Tool, model=sonnet)
- Grosses strukturelles Problem → Opus Sub-Agent (Task Tool, model=opus)
Sub-Agenten laufen im Hintergrund. Du liest ohne Pause weiter.

PHASE 3 - BERICHT (~5 Min):
Erstelle Abschluss-Bericht unter data/logs/."
```

### Geschaetzte Zeiten

| Phase | Dauer | Details |
|-------|-------|---------|
| Phase 1 (Exploration) | ~15 Min | Ordner + Schluessel-Dateien |
| Phase 2 (Review Core) | ~20 Min | 93 Dateien in 5 Batches |
| Phase 2 (Review Tools) | ~15 Min | +81 Dateien in 4 Batches |
| Phase 3 (Bericht) | ~5 Min | Zusammenfassung |
| **Gesamt (Core)** | **~40 Min** | |
| **Gesamt (Core+Tools)** | **~55 Min** | |

### Context-Window Budget

- Phase 1 Exploration: ~40k-60k Tokens
- Pro Help-Datei: ~500-2000 Tokens
- 93 Core-Dateien: ~90k Tokens (kumulativ, mit Komprimierung)
- Reserve fuer Edits/Outputs: ~30k Tokens

**Strategie bei Knappheit:**
1. Core in 2-3 Batches aufteilen (A-L, M-S, T-Z)
2. Progress-Datei nach jedem Batch speichern
3. Neuen Agent mit Progress-Datei + Phase 1 Kontext starten

---

## Variante B: Zwei-Experten-Pipeline (v1.4, EMPFOHLEN)

### Problem mit Variante A (1 Experte + kontextlose Sub-Agenten)

Gemessene Erfahrung (2026-02-09, 30 Help-Dateien):
- Haiku-Fixes (sicher, klein): **~10 Sek, 2-3 Tool-Calls** → perfekt
- Sonnet-Pruefungen (unsicher): **~40-165 Sek, 5-31 Tool-Calls** → LANGSAM

**Ursache:** Sonnet-Agenten haben KEINEN Systemkontext. Sie muessen Code-Dateien
(registry.py, hub/dist.py, schema.sql) selbst lesen um den Fehler zu verifizieren.
Der Expert-Agent HAT diesen Kontext bereits, kann ihn aber nicht weitergeben.

### Loesung: Zwei geschulte Experten + Helfer-Pool

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                    │
│  PHASE 1: Beide Experten durchlaufen Wissensaufbau (parallel)    │
│  (Stufe I → II → III, gleicher Prozess wie oben)                  │
│                                                                    │
│  PHASE 2: Pipeline                                                │
│                                                                    │
│  LESER (Opus)                    FIXER (Sonnet)                   │
│  ┌──────────────┐                ┌──────────────┐                 │
│  │ Liest Datei  │   ──Queue──>   │ Nimmt Eintrag│                 │
│  │ Bewertet     │                │ Prueft/Fixt  │                 │
│  │ Queue-Eintrag│                │ Dispatcht    │                 │
│  │ Liest weiter │                │ Haikus       │                 │
│  └──────────────┘                └──────────────┘                 │
│       │                               │                           │
│       │ (max 5 Haiku)                 │ (max 5 Haiku + 1 Sonnet) │
│       ▼                               ▼                           │
│  ┌─────────┐                    ┌─────────┐                       │
│  │ Helfer  │                    │ Helfer  │                       │
│  │ (Haiku) │                    │ (Haiku) │                       │
│  └─────────┘                    └─────────┘                       │
│                                                                    │
│  PHASE 3: Leser fertig → hilft Fixer ODER startet QA             │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### Rollen und Kapazitaeten

```
┌──────────────────────────────────────────────────────────────────┐
│  KAPAZITAETSPLAN (max 10 gleichzeitige Agenten)                  │
│                                                                    │
│  LESER (Opus 4.6)              FIXER (Opus 4.6)                  │
│  ════════════════              ════════════════                   │
│  Liest. Bewertet. Queue.       Queue abarbeiten. Pruefen. Fixen. │
│  Korrigiert NICHTS selbst.     Korrigiert ODER delegiert.         │
│                                                                    │
│  Helfer-Pool:                  Helfer-Pool:                       │
│  ├── 3x Haiku (parallel)      ├── 3x Haiku (parallel)            │
│  └── 1x Sonnet (parallel)     └── 1x Sonnet (parallel)           │
│                                                                    │
│  SUMME: 2 Opus + 6 Haiku + 2 Sonnet = 10 Agenten max            │
│                                                                    │
│  Haiku-Slot frei nach ~10s → schneller Durchsatz                 │
│  Sonnet-Slot frei nach ~30s → fuer Recherche-Aufgaben            │
└──────────────────────────────────────────────────────────────────┘
```

**LESER (Opus 4.6) - Nur lesen, nie fixen:**
- Liest ALLE Help-Dateien sequentiell
- Korrigiert NICHTS selbst - schreibt NUR Queue-Eintraege:
  ```json
  {"datei": "features.txt", "zeile": 60,
   "sicherheit": "sicher|unsicher|gross",
   "fehler": "daemon list statt daemon jobs",
   "kontext": "hub/daemon.py:60 definiert 'jobs' nicht 'list'",
   "fix": "Aendere 'bach daemon list' zu 'bach daemon jobs'"}
  ```
- Sichere triviale Fixes → direkt an eigene Haiku-Helfer (max 3 gleichzeitig)
- Unsichere/grosse Faelle → in Queue fuer Fixer (der hat Kontext zum Pruefen)
- 1 Sonnet-Slot fuer klar definierte Recherche (z.B. "zaehle CREATE TABLE in schema.sql")
- Nach Lesen aller Dateien: QA-Phase (stichprobenartig korrigierte Dateien pruefen)

**FIXER (Opus 4.6) - Pruefen und korrigieren:**
- Hat VOLLEN Systemkontext (gleiche Phase 1 durchlaufen wie Leser)
- Arbeitet Queue ab, startet sobald erster Eintrag vorliegt
- Sichere Queue-Eintraege → an Haiku-Helfer delegieren (max 3)
- Unsichere Queue-Eintraege → SELBST pruefen und fixen (hat Kontext!)
  (Kein kontextloser Sonnet der 31 Tool-Calls braucht wie beim dist-Bug)
- Grosse Probleme → selbst loesen oder an Sonnet mit Kontext-Briefing
- 1 Sonnet-Slot fuer parallelisierbare Pruefungen

**Warum beide Opus (nicht Opus + Sonnet als Fixer):**
- Fixer braucht GLEICHES Urteilsvermoegen wie Leser
- Unsichere Faelle erfordern Opus-Reasoning (dist-Bug: kontextloser Sonnet
  brauchte 165 Sek und 31 Tool-Calls; geschulter Opus schaetzt ~20 Sek)
- Kostenunterschied (~$0.10 mehr) wird durch 10x schnellere Pruefungen kompensiert

### Kapazitaets-Rechnung

```
Haiku-Agent:  ~10 Sek, ~20K Tokens, ~$0.005 pro Aufruf
Sonnet-Agent: ~30 Sek, ~40K Tokens, ~$0.03 pro Aufruf (MIT Kontext-Briefing)
Opus-Haupt:   ~25 Min Laufzeit, ~150K Tokens

Geschaetzt bei 93 Help-Dateien, ~40% Fehlerrate = ~37 Fehler:
  ~25 sichere kleine Fehler  → 25 Haiku-Agents      = $0.13
  ~10 unsichere Faelle       → Fixer prueft selbst   = $0 extra
  ~2 grosse Probleme         → Fixer + 2 Sonnet      = $0.06
  HELFER GESAMT: ~27 Agents, ~$0.19
  HAUPT-AGENTEN: 2 Opus, ~$3.00 (je ~$1.50)
```

### Warum das schneller ist (Gemessene Daten)

| Aspekt | Variante A (1 Experte) | Variante B (2 Opus) |
|--------|----------------------|------------------------|
| Leser blockiert | Ja (wartet auf Agenten) | **Nein (Fixer uebernimmt)** |
| Unsichere Pruefung | Kontextloser Sonnet: 40-165s | **Fixer mit Kontext: ~20s** |
| Max parallele Helfer | 3 Haiku + 1 Sonnet | **6 Haiku + 2 Sonnet** |
| Qualitaetspruefung | Keine | **Leser macht QA am Ende** |
| Grosse Probleme | Kontextloser Opus: teuer | **Fixer hat Kontext: schnell** |

Gemessen (Batch 3, identity.txt dist-Bug):
- Kontextloser Sonnet: **165 Sek, 31 Tool-Calls** (musste Code erkunden)
- Geschulter Opus haette: **~20 Sek, ~5 Tool-Calls** (kennt System bereits)

### Geschaetzte Zeiten (Variante B)

| Phase | Dauer | Details |
|-------|-------|---------|
| Phase 1 (beide parallel) | ~15 Min | Identischer Wissensaufbau, laeuft gleichzeitig |
| Phase 2 Leser (93 Dateien) | ~15 Min | Nur lesen + Queue schreiben |
| Phase 2 Fixer (Queue) | ~15 Min | Parallel zum Leser, startet ab Eintrag 1 |
| Phase 2 Helfer (~27 Agents) | ~5 Min | Verteilt ueber Phase 2, je 3+1 parallel |
| Phase 3 QA (Stichproben) | ~5 Min | Leser prueft ~10 korrigierte Dateien |
| **Gesamt (Wallclock)** | **~25 Min** | Phase 2 laeuft parallel |
| **Compute (Agent-Min)** | **~55 Min** | 2x25 Min Opus + ~5 Min Helfer |
| **Kosten** | **~$3.20** | 2 Opus + 27 Helfer |

### Queue-Mechanismus

Die Queue ist eine einfache JSON-Datei:
```
data/logs/help_review_queue_YYYY-MM-DD.json

[
  {
    "id": 1,
    "datei": "features.txt",
    "zeile": 60,
    "sicherheit": "sicher",
    "fehler": "daemon list statt daemon jobs",
    "fix": "Aendere 'bach daemon list' zu 'bach daemon jobs'",
    "status": "pending"
  },
  {
    "id": 2,
    "datei": "identity.txt",
    "zeile": 5,
    "sicherheit": "unsicher",
    "fehler": "HANDLER DEFEKT - gilt das noch seit v2.0?",
    "kontext": "Auto-Discovery koennte Bug gefixt haben",
    "fix": "Pruefe ob dist-Routing in registry.py funktioniert",
    "status": "pending"
  }
]
```

Fixer liest die Queue, setzt Status auf "in_progress", dann "done" oder "wontfix".

---

## Vergleich aller drei Ansaetze

| Aspekt | Help-Forensik | Expert-Review A | Expert-Review B |
|--------|--------------|-----------------|-----------------|
| Agenten | 90 parallel | 1 Opus + Helfer | **2 Experten + Helfer** |
| Systemkontext | Minimal | 1x Maximal | **2x Maximal** |
| Qualitaet | Inkonsistent | Konsistent | **Konsistent + QA** |
| Wallclock-Zeit | ~90 Min | ~35-40 Min | **~25 Min** |
| Compute | ~720 Agent-Min | ~35 Agent-Min | **~60 Agent-Min** |
| Fehleranfaelligkeit | Hoch | Niedrig | **Niedrigste** |
| Kontextlose Agenten | Alle 90 | Sonnet-Pruefungen | **Nur Haiku-Edits** |
| QA-Phase | Keine | Keine | **Leser prueft** |

---

## Siehe auch

- `skills/workflows/help-forensic.md` - Alter 90-Agenten Ansatz
- `skills/docs/help/practices.txt` - Best Practices (#7: HELP ALS WAHRHEIT)
- `docs/help/*.txt` - Zu pruefende Dateien
- `system/ROADMAP.md` - Aktuelle Phase
- `system/CHANGELOG.md` - Aenderungshistorie
- `system/BUGLOG.md` - Bekannte Bugs
