# Workflow: Root-Docs-Review (Zwei-Experten-Pipeline)

**Version:** 1.0.0
**Erstellt:** 2026-03-04
**Vorgaenger:** help-expert-review.md (Variante B adaptiert)
**Modell:** Opus 4.6 (zwei Instanzen)
**Recurring:** Nein (manuell nach Help-Review)

---

## Zweck

Validiert die oeffentlichen Markdown-Dokumente im Repository-Root (`BACH/`)
und eine Ebene tiefer (`BACH/system/`) gegen den tatsaechlichen Systemzustand.
Diese Dokumente sind die erste Anlaufstelle fuer neue User und LLMs.

**Kernprinzip:** Help-Dateien sind die validierte Wahrheitsquelle. Code ist
die hoechste Wahrheit. Root-Docs muessen mit beidem konsistent sein.

**Vorbedingung:** Der help-expert-review Workflow MUSS vorher gelaufen sein,
damit die Help-Dateien als verlaesstliche Referenz dienen koennen.

---

## Scope: Zu pruefende Dateien

### Ebene 1: Repository-Root (`BACH/`)

| Datei | Typ | Beschreibung |
|-------|-----|-------------|
| README.md | User-Doku | Haupteinstieg, Features, Quickstart |
| SKILL.md | LLM-Doku | Skill-Definition fuer Claude/Gemini |
| QUICKSTART.md | User-Doku | Schnelleinstieg |
| BACH_USER_MANUAL.md | User-Doku | Ausfuehrliches Handbuch |
| BACH_HELP_REFERENCE.md | Referenz | Help-System Uebersicht |
| ROADMAP.md | Planung | Phasen, Vision |
| CHANGELOG.md | Historie | Versionsaenderungen |
| ARCHITECTURE.md* | Technik | Architektur (falls vorhanden) |
| CONTRIBUTING.md | Community | Beitragsrichtlinien |
| CODE_OF_CONDUCT.md | Community | Verhaltensregeln |
| SECURITY.md | Sicherheit | Sicherheitsrichtlinien |
| CLAUDE.md | LLM-Config | Claude-spezifische Konfiguration |
| GEMINI.md | LLM-Config | Gemini-spezifische Konfiguration |
| OLLAMA.md | LLM-Config | Ollama-spezifische Konfiguration |
| USER.md | User-Config | User-spezifische Daten |
| MEMORY.md | LLM-Memory | Episodisches Memory |

**Generierte Dateien (Konsistenz mit DB pruefen):**

| Datei | Generator | DB-Quelle |
|-------|-----------|-----------|
| AGENTS.md | tools/agents_export.py | agents, agent_synergies |
| CHAINS.md | tools/chains_export.py | toolchains |
| PARTNERS.md | tools/partners_export.py | delegation_rules |
| SKILLS.md | (manuell?) | skills |
| USECASES.md | tools/usecases_export.py | usecases |
| WORKFLOWS.md | tools/workflows_export.py | skills/workflows/ |

### Ebene 2: System-Verzeichnis (`BACH/system/`)

| Datei | Typ | Beschreibung |
|-------|-----|-------------|
| ARCHITECTURE.md | Technik | System-Architektur |
| CHANGELOG.md | Historie | System-Aenderungen |
| FEATURES.md | Referenz | Feature-Matrix |
| ROADMAP.md | Planung | System-Roadmap |

---

## Guete-Hierarchie (hoechste gewinnt bei Widerspruch)

```
GUETE 4 (HOECHSTE):  Code lesen (bach_paths.py, registry.py, schema.sql)
                      Was der Code JETZT macht
                      → Ueberschreibt alles darunter

GUETE 3 (HOCH):      Dateisystem (ls, Glob) + Directory Scan
                      Was JETZT existiert
                      → Ueberschreibt Help-Dateien und Root-Docs

GUETE 2 (MITTEL):    Validierte Help-Dateien (docs/help/*.txt)
                      Durch help-expert-review geprueft
                      → Verlaessliche Referenz fuer Befehle/Features

GUETE 1 (NIEDRIGSTE): Root-Docs selbst (README.md, SKILL.md, etc.)
                       Koennen veraltet sein
                       → DAS was wir pruefen und korrigieren
```

---

## Phase 1: Wissensaufbau (beide Experten parallel, ~10 Min)

Identisch zum help-expert-review, aber ZUSAETZLICH die Help-Dateien als
Referenz laden.

### 1.1 Code-Wahrheit (Guete 4)

```
Lesen:
  system/hub/bach_paths.py          → Kanonische Pfade
  system/core/registry.py           → Welche Handler existieren
  system/db/schema.sql              → DB-Tabellen
  system/bach.py                    → CLI-Routing
```

### 1.2 Dateisystem-Wahrheit (Guete 3)

```
Exploration:
  ls BACH/                          → Root-Dateien
  ls BACH/system/                   → System-Dateien
  ls BACH/system/hub/               → Alle Handler
  ls BACH/system/agents/            → Agenten
  ls BACH/system/tools/             → Tools
  ls BACH/system/skills/            → Skills-Struktur
  ls BACH/system/docs/help/         → Help-Dateien zaehlen
```

### 1.3 Help-Dateien als Referenz (Guete 2)

```
Schluesseldateien lesen:
  docs/help/cli.txt                 → Alle CLI-Befehle
  docs/help/architecture.txt        → Architektur-Referenz
  docs/help/features.txt            → Feature-Liste
  docs/help/tools.txt               → Tool-Uebersicht
  docs/help/skills.txt              → Skill-System
  docs/help/agents.txt (falls existent)
  docs/help/startup.txt             → Startup-Prozedur
  docs/help/help.txt                → Help-Themen-Index
  docs/README.md                    → Doku-Index
```

---

## Phase 2: Zwei-Experten Review

### LESER (Opus 4.6) - Liest Root-Docs, bewertet, Queue-Eintraege

Liest jede Root-Datei einzeln und prueft gegen das Wissensmodell:

```
PRUEFRASTER pro Datei:

[ ] HANDLER:     Stimmen referenzierte CLI-Befehle mit cli.txt/registry.py ueberein?
[ ] FEATURES:    Stimmt Feature-Status (implementiert/geplant) mit features.txt ueberein?
[ ] PFADE:       Existieren referenzierte Pfade? Stimmen sie mit bach_paths.py ueberein?
[ ] ARCHITEKTUR: Stimmt Architektur-Beschreibung mit architecture.txt ueberein?
[ ] ZAHLEN:      Handler-Anzahl, Tabellen-Anzahl, Skill-Anzahl korrekt?
[ ] LINKS:       Interne Verweise zu anderen .md-Dateien korrekt?
[ ] KONSISTENZ:  Keine Widersprueche zwischen Root-Docs untereinander?
[ ] AKTUALITAET: Keine offensichtlich veralteten Informationen?
[ ] GENERIERTE:  AGENTS.md/CHAINS.md/etc. konsistent mit Generator-Output?
```

### FIXER (Opus 4.6) - Prueft Queue, korrigiert oder delegiert

```
Sicher + Klein → Haiku-Helfer:
  "In README.md Zeile 45: Aendere '64 Handler' zu '67 Handler' (registry.py zeigt 67)"

Unsicher → Fixer prueft selbst:
  "ROADMAP.md Zeile 120 sagt 'Phase 16'. Help sagt 'Phase 17'. Was stimmt?"
  → Fixer liest ROADMAP.md + CHANGELOG.md und entscheidet

Gross/Strukturell → Fixer mit Sonnet-Hilfe:
  "SKILL.md Sektion 'Verfuegbare Handler' ist komplett veraltet"
  → Fixer erstellt neue Version basierend auf cli.txt + registry.py
```

### Spezial-Pruefungen fuer generierte Dateien

```
AGENTS.md:
  → python tools/agents_export.py erzeugt Referenz-Version
  → Diff mit vorhandener AGENTS.md
  → Bei grossen Abweichungen: Regenerieren empfehlen

WORKFLOWS.md:
  → python tools/workflows_export.py erzeugt Referenz-Version
  → Diff vergleichen

PARTNERS.md, CHAINS.md, USECASES.md:
  → Analog
```

---

## Phase 3: Abschluss-Bericht

Datei: `data/logs/root_docs_review_YYYY-MM-DD.md`

```markdown
# Root-Docs-Review Bericht

**Datum:** YYYY-MM-DD
**Agent:** Opus 4.6 (Zwei-Experten-Pipeline v1.0)
**Scope:** BACH/*.md (22 Dateien) + system/*.md (4 Dateien)
**Vorbedingung:** help-expert-review vom YYYY-MM-DD

## Statistik

| Metrik | Wert |
|--------|------|
| Dateien geprueft | NN |
| Dateien korrigiert | NN |
| Einzelne Fixes | NN |
| Generierte Dateien veraltet | NN |
| Offene Entscheidungen | NN |

## Korrigierte Dateien

| Datei | Fixes | Details |
|-------|-------|---------|
| [name].md | N | [Kurzbeschreibung] |

## Regenerierungs-Empfehlungen

| Datei | Generator | Letzter Export | Empfehlung |
|-------|-----------|---------------|------------|
| AGENTS.md | agents_export.py | YYYY-MM-DD | Regenerieren |

## Offene Punkte (Nutzer-Entscheidung)

- [ ] [Punkt 1]
```

---

## Ausfuehrung

### Manueller Start (Claude Code)

```
Prompt an Opus 4.6:

"Du bist der Root-Docs-Review Agent fuer BACH.
Repository: %ONEDRIVE_AI_ROOT%\BACH
System: %ONEDRIVE_AI_ROOT%\BACH\system
Workflow: skills/workflows/root-docs-review.md

VORBEDINGUNG: help-expert-review muss gelaufen sein.
Die Help-Dateien (docs/help/*.txt) gelten als validierte Referenz.

PHASE 1 - WISSENSAUFBAU (~10 Min):
Code-Wahrheit: bach_paths.py, registry.py, schema.sql, bach.py lesen.
Dateisystem: Jeden relevanten Ordner erkunden.
Help-Referenz: cli.txt, architecture.txt, features.txt, tools.txt,
skills.txt, startup.txt, help.txt, docs/README.md lesen.

PHASE 2 - ZWEI-EXPERTEN-REVIEW:
Lies BACH/*.md und BACH/system/*.md einzeln.
Pruefe gegen Code (Guete 4) > Dateisystem (Guete 3) > Help (Guete 2).
DU SELBST KORRIGIERST NICHTS - Queue-Eintraege fuer den Fixer.
Sicherer Fix → Haiku. Unsicher → Fixer prueft. Gross → Fixer + Sonnet.

Spezial: AGENTS.md, CHAINS.md, PARTNERS.md, USECASES.md, WORKFLOWS.md
sind generiert. Pruefe ob sie veraltet sind (Generator-Datum vs. DB).

PHASE 3 - BERICHT:
Erstelle data/logs/root_docs_review_YYYY-MM-DD.md"
```

### Geschaetzte Zeiten

| Phase | Dauer | Details |
|-------|-------|---------|
| Phase 1 (Wissensaufbau) | ~10 Min | Code + Dateisystem + Help-Referenz |
| Phase 2 (Review 26 Dateien) | ~15 Min | Leser + Fixer parallel |
| Phase 3 (Bericht) | ~5 Min | Zusammenfassung |
| **Gesamt** | **~20 Min** | |

### Context-Window Budget

- Phase 1: ~50k Tokens (Code + Help-Referenz)
- 26 Root-Docs: ~100k Tokens (einige Dateien sind gross)
- Reserve: ~50k Tokens
- **Gesamt: ~200k Tokens** (passt in ein Context Window)

---

## Abgrenzung zum help-expert-review

| Aspekt | help-expert-review | root-docs-review |
|--------|-------------------|------------------|
| **Scope** | docs/help/*.txt (~174 Dateien) | BACH/*.md + system/*.md (~26 Dateien) |
| **Zweck** | Help-Dateien validieren | Root-Docs gegen Help + Code validieren |
| **Reihenfolge** | ZUERST | DANACH (braucht validierte Help als Referenz) |
| **Wahrheitsquelle** | Code + Dateisystem | Code + Dateisystem + Help-Dateien |
| **Generierte Dateien** | Nein | Ja (AGENTS.md, CHAINS.md, etc.) |
| **Haeufigkeit** | Bei Bedarf | Nach jedem help-expert-review |

---

## Siehe auch

- `skills/workflows/help-expert-review.md` - Vorgaenger-Workflow (MUSS zuerst laufen)
- `docs/help/cli.txt` - CLI-Referenz (Guete 2)
- `docs/help/features.txt` - Feature-Matrix (Guete 2)
- `docs/README.md` - Doku-Index
- `tools/agents_export.py` - AGENTS.md Generator
- `tools/workflows_export.py` - WORKFLOWS.md Generator
