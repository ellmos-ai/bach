# Wiki-Author Report

**Datum:** 2026-09-16
**Modus:** B (Artikel aktualisieren)
**Task:** wiki_author (recurring, 18.09.2026 - vorgezogen am 16.09.)

## Artikel-Auswahl

- **Artikel:** wiki/claude_code_memory.txt
- **Letzte Validierung:** 2026-02-16 (Claude Code Opus)
- **Naechste Pruefung laut Metadaten:** 2026-06-01 -> SEIT 3,5 MONATEN UEBERFAELLIG (aeltester fälliger Artikel von 15)
- **Rotation:** Letzter Lauf 12.09. Modus A -> heute Modus B (Protokoll-Rotation A/B/C)

## Pruefung

### Quellen geprueft
- docs.anthropic.com/en/docs/claude-code/memory: Vollstaendig neu strukturiert -
  "Auto Memory" ist jetzt offizielles Feature mit eigener Doku-Sektion
- Lokale Verzeichnisanalyse ~/.claude/projects/: Struktur geprueft
- /Users/lukas/services/bach/.git: Bestaetigt (Git-Root fuer Scope-Ableitung)

### Fakten geprueft (Auszug)

| # | Fakt (Artikel Feb) | Ergebnis |
|---|---------------------|----------|
| 1 | "MEMORY.md = Haupt-Memory, wird voll geladen" | ✗ Veraltet - MEMORY.md ist jetzt INDEX (1 Zeile pro Memory) |
| 2 | "Truncation nach 200 Zeilen" | ⚠ Praezisiert - 200 Zeilen ODER 25KB, je nachdem was zuerst |
| 3 | "Unterverzeichnisse erben NICHT die Memory" | ✗ Veraendert - Subdirs im gleichen Git-Repo TEILEN sich einen Ordner |
| 4 | "~42 Projektverzeichnisse (Windows)" | ✗ System-spezifisch - auf diesem Mac: 4 Ordner |
| 5 | "Verzeichnisname aus Arbeitsverzeichnis abgeleitet" | ⚠ Praezisiert - Ableitung aus GIT-REPOSITORY-Root |
| 6 | "Detail-Dateien nicht automatisch geladen" | ✓ Bestaetigt (on demand per Read-Tool) |
| 7 | "Session-Wissen geht verloren" | ✓ Bestaetigt (Memory-Dateien aber von Retention-Sweep ausgenommen) |
| 8 | "CLAUDE.md vererbt an Unterverzeichnisse" | ⚠ Praezisiert - Parent: beim Launch; Subdirs: on demand; neu: .claude/rules/, AGENTS.md |

### Neue Fakten ergaenzt (fehlten komplett)
- Auto Memory on/off: autoMemoryEnabled (settings.json), CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
- Custom-Pfad: autoMemoryDirectory; Eigenname: CLAUDE_CODE_PROJECT_DIR_NAME (v2.1.234+)
- modified-Frontmatter-Timestamp (v2.1.214+)
- CLAUDE.md: bis 4 MiB voll geladen, groessere uebersprungen
- Subagent-Memory: eigene Verzeichnisse, kein Load in Subagents (Ausnahme fork)
- /memory und /context Befehle
- CLAUDE.md-Lade-Ordnung: Managed Policy -> User -> Projekt -> Lokal

## Ergebnis

**Status:** AKTUALISIERT (UMFANGREICHE UEBERARBEITUNG)

Der Artikel vom Feb 2026 beschrieb eine VOR-offizieller-Doku-Architektur
(vermutlich beobachtetes Verhalten einer Beta/aelteren Version). Die
Kernarchitektur hat sich geaendert: MEMORY.md ist Index, Scope ist
Git-Repository-basiert, Auto Memory ist offizielles Feature.

### Aenderungen
- Vollstaendige Neufassung mit HISTORIE-Sektion
- Neue Sektionen: EINSTELLUNGEN & STEUERUNG, LOKALE BEOBACHTUNG
- BACH-KONTEXT aktualisiert: Silo-Problem durch Git-Root-Ableitung geloest
- QUELLEN aktualisiert: offizielle Doku statt System-Prompt-Analyse
- Metadaten: validiert 2026-09-16, naechste Pruefung 2027-03-16
  (6 Monate - schnelllebiges Thema, Claude Code Versioniert schnell)

### Offene Beobachtung (fuer naechste Pruefung)
- LOKALE ABWEICHUNG: MEMORY.md-Index liegt direkt im Projektordner
  (-Users-lukas/MEMORY.md), Doku erwartet memory/MEMORY.md. Bei naechster
  Pruefung klären, ob Migration stattgefunden hat (aeltere lokale Version
  oder manuell verschoben, Stand 28.05.)
- Legacy-Ordner -Users-lukas-services-bach-system/ existiert parallel
  (historische Arbeitsverzeichnis-Ableitung)

## Weitere faellige Artikel (fuer kommende Modus-B-Laeufe)

14 weitere Artikel mit ueberfaelliger Pruefung, aelteste zuerst:
- 2026-07-28: finanzen_versicherungen/bach_versicherungs_modul.txt, skills_board.txt
- 2026-07-30: informatik/ki_ml/biomimetisches_lernen.txt
- 2026-08-14: mcp.txt, zapier_mcp.txt
- 2026-08-15: agentic_workflows.txt, mcp_patterns.txt, mcp_toolstack.txt,
  selbstheilung.txt, speicher_architektur.txt, teaching_hooks.txt,
  trampelpfadanalyse.txt, informatik/ki_ml/tokens_kontextfenster.txt
- 2026-09-12: lobehub.txt

**Status:** FERTIG