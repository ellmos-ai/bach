# NoteSpace (BACH On-Board) — Provenance

**Vendored aus:** internem NoteSpaceLLM-Quellstand
**Vendored am:** 2026-05-30
**Quell-Version:** NoteSpaceLLM v1.0.0 (PySide6-Desktop, RAG via LangChain + ChromaDB + Ollama)

## Was ist das?

Ein festes, mitgeliefertes BACH-Modul: die BACH-eigene Instanz von NoteSpaceLLM
(privater NotebookLM-Klon für Dokument-Analyse und Report-Generierung).
Eigenständige Kopie — **unabhängig** vom internen Quellprojekt. `bach notespace`
öffnet diese BACH-Version.

## Unterschiede zur internen Quelle (bewusste BACH-Anpassungen)

Alle Anpassungen sind über die Umgebungsvariable `BACH_NOTESPACE_HOME` gesteuert,
die der Handler (`hub/notespace.py`) beim Start setzt. Ohne diese Variable verhält
sich die App wie das Original (Fallback auf `~/.notespacellm` / `~/NoteSpaceLLM`).

| Aspekt | Interne Quelle | BACH On-Board |
|---|---|---|
| Config | `~/.notespacellm/config.json` | `data/notespace/config/config.json` |
| Projekte | `~/NoteSpaceLLM/projects` | `data/notespace/projects` |
| Vektor-DB | `~/NoteSpaceLLM/storage/chroma_db` | `data/notespace/storage/chroma_db` |
| LLM-Backend | wählbares Profil-System | **fest** an BACHs `data/ollama_config.json` gebunden |

Gepatchte Dateien (Suche nach `BACH_NOTESPACE_HOME`):
- `src/core/app_config.py`  — Config-Verzeichnis
- `src/gui/main_window.py`  — Projekt- und Storage-Verzeichnis (+ `import os`)

## Ollama-Bindung

Der Handler synchronisiert bei jedem GUI-Start die NoteSpace-`config.json` aus
BACHs globaler `data/ollama_config.json` (Provider=ollama, Modell, URL, Embedding).
**Eine Quelle der Wahrheit.** Backend ändern → `data/ollama_config.json` editieren.
`data/ollama_config.json` ist gitignored (user-spezifisch) → keine Mac-/Server-
Adresse landet im öffentlichen Repo.

## Re-Sync bei Updates der Quelle

Bei Änderungen an der internen Quelle: `src/` neu kopieren und die zwei oben
genannten Patch-Stellen erneut anwenden. Daten unter `data/notespace/` bleiben
unberührt.

## Sync-Historie

- 2026-06-25: `translator.py` nachgezogen; `_is_german()` nutzt german_hints
  tokenbasiert statt per Teilstring-Matching, damit englische Scan-Texte mit
  Wörtern wie `important` oder `filtering` keine falschen Übersetzungseinträge
  erzeugen.
