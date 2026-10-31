# BACH Projekt-Anweisungen

<!-- BACH:START - Automatisch generiert, nicht manuell bearbeiten -->

*Generiert: (wird beim ersten Start automatisch befuellt)*

## System-Einstellungen

**SECURITY**
- `secrets_file_path`: ~/.bach/bach_secrets.json

**BEHAVIOR**
- `auto_backup_days`: 30
- `default_retention_days`: 30
- `timeout_checkpoint_minutes`: 10

**INTEGRATION**
- `integration.claude-code.claude_md_path`: (wird automatisch gesetzt)

## BACH Lessons (Top-10)

*Noch keine Lessons gespeichert. BACH lernt aus deinen Sessions.*

<!-- BACH:END -->

## Modulregel & Bauort (Bach-Grenze)

**Verweis:** [system/AGENTS.md](./AGENTS.md)

Dieses Dokument definiert die Bauort-Klassen und die Modulgrenzen von BACH:

| Bauort | Bedeutung | Pfad |
|--------|-----------|------|
| `kern` / `core` | BACH-Kern (bach.py, Lead-HTTP, bach.db-Speicher, dünne Adapter) | `system/core/` |
| `module-gate` | Modul-Gate-CI-Prüfung | `.github/workflows/module_gate.yml` |
| `adapter:<id>` | Dünne Adapter für Ocean-Module | `system/hub/_services/adapters/<id>/` |
| `ausnahme:<Task>` | Ausnahmen von der Regelbasierung | Label + Task-ID erforderlich |
| `gui` | GUI- und Client-Komponenten | `system/gui/` (ohne `/web/`) |
| `ocean` | Ocean-Kernmodule | `open-ocean/`, `ellmos-*` |

**Regel:** Jeder PR benötigt mindestens ein `bauort:`-Tag im Titel oder der Beschreibung. PRs ohne Bauort-Tag werden von GitHubBot als HOLD eingestuft.

## Entwicklungs-Workflow (Single Installation Model, ab v3.3.0)

### Code aendern
```bash
# Direkt im Git-Repo entwickeln
cd /pfad/zu/BACH
# CORE-Aenderungen: git add + commit + push
git add system/hub/neuer_handler.py
git commit -m "feat: neuer Handler"
git push origin main
```

### User-Daten sind geschuetzt

Die `.gitignore` schuetzt:
- `bach.db` und alle Laufzeitdaten
- `user/` Verzeichnis (persoenliche Daten)
- Credentials und API-Keys
- Generierte Dokumentation (MEMORY.md, USER.md, SKILLS.md, etc.)

<!--
  HINWEIS: Diese Datei ist ein Template.
  BACH ueberschreibt den BACH:START/END-Block automatisch mit echten Daten.
  Varianten: OLLAMA.md, GEMINI.md (gleiche Struktur, andere LLM-Anweisungen)
-->

---
🇬🇧 [English version](CLAUDE.template.md)