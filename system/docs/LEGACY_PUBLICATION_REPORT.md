# Legacy Publication Report (ENT-25)

**Datum:** 2026-03-02
**Status:** Vorbereitung abgeschlossen -- manuelle GitHub-Aktionen erforderlich

---

## 1. Gefundene Legacy-Projekte

### CHIAH (Claude Human Inter Action Hub)
- **Pfad:** `%ONEDRIVE_AI_ROOT%\_ARCHIV\_CHIAH\`
- **Dateien:** 322
- **Git-Repo:** Nein (muss initialisiert werden)
- **Version:** 3.2 (final)
- **Beschreibung:** CLI-first System fuer Claude AI mit Injektoren, Context Sources, Auto-Logging

### recludOS (Reclusive OS)
- **Pfad:** `%ONEDRIVE_AI_ROOT%\_ARCHIV\recludOS\`
- **Dateien:** 5296
- **Git-Repo:** Nein (muss initialisiert werden)
- **Version:** 3.3.0 (final)
- **Beschreibung:** Text-basiertes OS/Framework fuer LLM AI mit Agent-Framework, Distribution-System, Self-Healing

### recludos-filecommander-mcp (Bonus)
- **Pfad:** `%ONEDRIVE_AI_ROOT%\_ARCHIV\recludos-filecommander-mcp\`
- **Git-Repo:** Nein
- **Beschreibung:** MCP-Server (TypeScript/Node.js) urspruenglich fuer recludOS entwickelt
- **Hinweis:** Existiert bereits als separates Projekt, evtl. schon auf GitHub?

---

## 2. RECLUDOS_ROOT Cleanup Verifikation

- **RECLUDOS_ROOT in .py Dateien:** 0 Treffer -- vollstaendig bereinigt (Task #2)
- **RECLUDOS_BASE in dictionary_builder.py:** 3 Stellen (Zeile 59, 201, 420) -- dies ist ein Legacy-Tool, nicht die Environment-Variable RECLUDOS_ROOT
- **"recludos" (case-insensitive) in BACH:** 80 Dateien -- fast ausschliesslich Dokumentation, Wiki, Changelogs und historische Referenzen. Dies ist korrekt und sollte erhalten bleiben.

---

## 3. Sensible Daten

### CHIAH
- **Keine echten Credentials gefunden.** FritzBox-Tool nutzt `os.getenv()` (sicher).
- **Potentiell sensibel:** `DATA/memory/archive/` enthaelt Session-Berichte mit "api-key", "token" Erwaenungen -- Kontextuelle Erwaenungen, keine echten Keys. Trotzdem via `.gitignore` ausgeschlossen.
- **`.gitignore` erstellt:** Schliesst `DATA/memory/archive/`, `_sandbox/`, `__pycache__/` aus.

### recludOS
- **Keine echten Credentials gefunden.** "token" Erwaenungen sind kontextuell (Token-Counting, Dokumentation).
- **Potentiell sensibel:** `Workspace/Mail_Downloads/`, PDFs im Workspace.
- **`.gitignore` erstellt:** Schliesst `Workspace/Mail_Downloads/`, `Workspace/Papierkorb/`, `node_modules/`, `*.pdf` im Workspace aus.

---

## 4. Erstellte Dateien

| Datei | Projekt | Beschreibung |
|-------|---------|-------------|
| `_CHIAH/README.md` | CHIAH | Projektbeschreibung, Archiv-Hinweis, BACH-Link |
| `_CHIAH/.gitignore` | CHIAH | Standard-Ausschluss + Session-Daten |
| `recludOS/README.md` | recludOS | Projektbeschreibung, Archiv-Hinweis, BACH-Link |
| `recludOS/.gitignore` | recludOS | Standard-Ausschluss + Workspace-Daten |

---

## 5. Manuelle Aktionen (User erforderlich)

### GitHub Repos erstellen

**Repo 1: chiah**
```
Name: chiah
Description: CHIAH (Claude Human Inter Action Hub) - CLI-first predecessor to BACH. Archived.
Topics: claude-ai, cli, llm-framework, archived
Visibility: Public
```

**Repo 2: recludos**
```
Name: recludos
Description: RecludOS - Text-based OS/Framework for LLM AI. Predecessor to BACH. Archived.
Topics: claude-ai, llm-os, agent-framework, archived
Visibility: Public
```

### Git initialisieren und pushen

Fuer jedes Projekt:
```bash
cd <projekt-pfad>
git init
git add .
git commit -m "Initial commit: archived legacy project"
git remote add origin https://github.com/lukisch/<repo-name>.git
git branch -M main
git push -u origin main
```

### GitHub-Repos archivieren

Nach dem Push in den Repository-Settings:
- Settings -> General -> Danger Zone -> "Archive this repository"

### Optional: recludos-filecommander-mcp

Falls noch nicht auf GitHub: Gleiches Verfahren. Pruefen ob bereits unter `github.com/lukisch` vorhanden.

---

## 6. Verbleibende RECLUDOS-Referenzen in BACH

Die folgenden Referenzen in BACH sind **beabsichtigt** und sollten **nicht** entfernt werden:
- Wiki-Eintraege (`wiki/recludos.txt`, `wiki/chiah.txt`, `wiki/batch.txt`)
- CHANGELOG/ROADMAP historische Eintraege
- Architektur-Dokumentation
- `dictionary_builder.py` Variable `RECLUDOS_BASE` (Legacy-Tool, funktional unabhaengig)
