# Help-Forensik-Doku-Routine – Differenz-Bericht

**Auftrag:** #2230 – begrenzte empirische Dokuprüfung/Analyse für `help_forensic`, konkrete Differenz mit Korrekturvorschlag.
**Prüfmodus:** Nur Lese-Analyse, keine Quelldateien verändert.
**Kanonische Wahrheit:** `system/hub/bach_paths.py` + tatsächliche Verzeichnisstruktur im Task-Worktree.

## 1. Kanonische Referenz (geprüfte Fakten)

| # | Quelle | Beleg | Kanonischer Pfad / Fakt |
|---|--------|-------|--------------------------|
| 1 | `system/hub/bach_paths.py:107/108` | `HELP_DIR = SYSTEM_ROOT / "docs" / "help"` | `system/docs/help/` |
| 2 | `system/hub/bach_paths.py:119` | `SERVICES_DIR = SKILLS_DIR / "_services"` | `system/skills/_services/` |
| 3 | `system/hub/bach_paths.py:122` | `LOGS_DIR = DATA_DIR / "logs"` | `system/data/logs/` |
| 4 | `system/hub/bach_paths.py:330` | `get_path("help")` → `HELP_DIR` | `system/docs/help/` |
| 5 | `system/hub/bach_paths.py:343` | `get_path("logs")` → `LOGS_DIR` | `system/data/logs/` |
| 6 | Verzeichnis-Listing | `system/hub/` flach | Handler liegen direkt unter `system/hub/*.py`, nicht `system/hub/handlers/` |
| 7 | Verzeichnis-Listing | `system/hub/_services/help/SKILL.md` | Help-Service-Doku liegt unter `system/hub/_services/help/`, nicht unter `skills/_services/...` |

## 2. Geprüfte Dokumente

- `system/skills/workflows/help-forensic.md` (Zeilen 1–371)
- `system/skills/workflows/help-expert-review.md` (Zeilen 1–671)
- `system/skills/workflows/root-docs-review.md` (Zeilen 1–303)
- `system/skills/workflows/docs-analyse.md` (Zeilen 1–253)
- `system/hub/_services/help/SKILL.md` (Zeilen 1–190)

## 3. Konkrete Differenzen und Korrekturvorschläge

### 3.1 `system/skills/workflows/help-forensic.md`

| Zeile | Falsch (aktueller Wortlaut) | Korrekt | Schwere | Begründung / Quelle |
|-------|----------------------------|---------|---------|---------------------|
| 5 | `skills/_services/skills/docs/help/SKILL.md` | `system/hub/_services/help/SKILL.md` | hoch | Service-Doku liegt unter `system/hub/_services/help/` (verifiziert); doppeltes `skills/` ist weder im Code noch im Baum vorhanden. |
| 16, 35, 38, 41, 55, 67, 233, 301 | `skills/docs/help/` | `system/docs/help/` | hoch | `bach_paths.py:107/108` setzt `HELP_DIR = SYSTEM_ROOT / "docs" / "help"`. Kein `skills/docs/help/`-Pfad existiert. |
| 118, 121 | `hub/handlers/` | `system/hub/` | hoch | Handler liegen flach in `system/hub/`; kein `handlers/`-Unterordner existiert. |
| 292 | `logs/help_forensic/` (relativ) | `system/data/logs/` bzw. `get_path("logs")` | mittel | `bach_paths.py:122` definiert `LOGS_DIR = DATA_DIR / "logs"`. Kein `help_forensic/`-Subpfad ist als Konstante definiert; relativer Bezug ist unklar. |
| 368 | `skills/_services/skills/docs/help/SKILL.md` | `system/hub/_services/help/SKILL.md` | hoch | Wiederholung von Zeile 5, selber Fehler. |

### 3.2 `system/hub/_services/help/SKILL.md`

| Zeile | Falsch (aktueller Wortlaut) | Korrekt | Schwere | Begründung / Quelle |
|-------|----------------------------|---------|---------|---------------------|
| 142 | `hub/_services/docs/help/` | `system/hub/_services/help/` | hoch | Service-Doku liegt tatsächlich unter `system/hub/_services/help/`; `docs/help/` ist hier fehl am Platz. |
| 144 | `help_forensic.py (TODO)` | Service-Skript existiert noch nicht | Info | Vermerk deutet darauf hin, dass der zugehörige Python-Service noch nicht implementiert ist. |
| 160–162 | `docs/help/*.txt` (relativ) | `system/docs/help/*.txt` | mittel | Relativ aus Sicht der Workflow-Beschreibung; kanonisch ist `system/docs/help/*.txt` (`HELP_DIR`). |

### 3.3 `system/skills/workflows/root-docs-review.md`

| Zeile | Falsch (aktueller Wortlaut) | Korrekt | Schwere | Begründung / Quelle |
|-------|----------------------------|---------|---------|---------------------|
| 192 | `data/logs/root_docs_review_YYYY-MM-DD.md` | `system/data/logs/root_docs_review_YYYY-MM-DD.md` | mittel | `LOGS_DIR = DATA_DIR / "logs"`; Berichtspfad sollte `system/data/logs/...` lauten oder auf `get_path("logs")` verweisen. |
| 239–241 | Repository-Pfade mit `%ONEDRIVE_AI_ROOT%\BACH`; Workflow-Pfad `skills/workflows/root-docs-review.md` | Für BACH-interne Referenzen `system/...` verwenden, z. B. `system/skills/workflows/root-docs-review.md` | niedrig-mittel | `%ONEDRIVE_AI_ROOT%\BACH` beschreibt den externen Repo-Root; innerhalb des Workflows fehlt das `system/`-Präfix für kanonische Pfade. |
| 244 | `docs/help/*.txt` | `system/docs/help/*.txt` | mittel | Kanonisch `system/docs/help/*.txt`. |
| 287 | Scope `docs/help/*.txt` | `system/docs/help/*.txt` | mittel | Selbe relative Pfadangabe wie Zeile 244. |

### 3.4 `system/skills/workflows/docs-analyse.md`

| Zeile | Falsch (aktueller Wortlaut) | Korrekt | Schwere | Begründung / Quelle |
|-------|----------------------------|---------|---------|---------------------|
| 216 | `hub/handlers/handlername.py` | `system/hub/<handlername>.py` | hoch | Handler liegen flach in `system/hub/`, nicht in einem `handlers/`-Unterordner. |

### 3.5 `system/skills/workflows/help-expert-review.md`

| Zeile | Falsch (aktueller Wortlaut) | Korrekt | Schwere | Begründung / Quelle |
|-------|----------------------------|---------|---------|---------------------|
| 283 | Pfadprüfung fordert: "Existieren alle referenzierten Pfade? Kanonisch?" | – | Meta | Die Workflow-Datei selbst enthält nicht-kanonische Pfade (siehe unten) und verstößt damit gegen ihre eigene Prüfanforderung. |
| 284 | "Existiert der Handler in hub/? Korrekte Syntax?" | `system/hub/` ist korrekt, aber ohne `system/`-Präfix | niedrig | Richtige Ebene (`hub/`), aber in kanonischer Schreibweise `system/hub/` angeben. |
| 620 | `data/logs/help_review_queue_YYYY-MM-DD.json` | `system/data/logs/help_review_queue_YYYY-MM-DD.json` | mittel | `LOGS_DIR = DATA_DIR / "logs"`; kanonisch `system/data/logs/`. |
| 666 | `skills/workflows/help-forensic.md` | `system/skills/workflows/help-forensic.md` | niedrig | Relativ aus Workflow-Sicht; kanonisch mit `system/`-Präfix. |
| 667 | `skills/docs/help/practices.txt` | `system/docs/help/practices.txt` | hoch | `HELP_DIR = system/docs/help`; es gibt kein `skills/docs/help/`. |
| 668 | `docs/help/*.txt` | `system/docs/help/*.txt` | mittel | Selber relativer Pfad wie in den anderen Workflows. |

## 4. Zusammenfassung der Fehlerkategorien

| Kategorie | Anzahl Vorkommen | Hauptbetroffene Dateien |
|-----------|------------------|--------------------------|
| Falsches `skills/docs/help/` statt `system/docs/help/` | 11+ | `help-forensic.md`, `help-expert-review.md` |
| Falscher Service-Pfad (`skills/_services/...`) | 2 | `help-forensic.md` |
| Falscher Handler-Ordner (`hub/handlers/`) | 2 | `help-forensic.md`, `docs-analyse.md` |
| Fehlendes `system/`-Präfix bei Logs/Datenpfaden | 5 | `help-forensic.md`, `root-docs-review.md`, `help-expert-review.md` |
| Falscher Help-Service-Ordner in `SKILL.md` | 1 | `SKILL.md` |
| Relativ/kontextlose Pfadangaben (Scope, Prompts) | 6 | alle fünf Dokumente |
| Nicht existierendes Service-Skript `help_forensic.py` | 1 | `SKILL.md` (Vermerk) |

## 5. Empfohlene Korrekturstrategie

1. **Hochprior:** In `help-forensic.md` und `help-expert-review.md` alle `skills/docs/help/` → `system/docs/help/` ersetzen.
2. **Hochprior:** Service-Pfad in `help-forensic.md` (Zeilen 5, 368) auf `system/hub/_services/help/SKILL.md` korrigieren.
3. **Hochprior:** Handler-Referenzen `hub/handlers/` → `system/hub/` (flach) in `help-forensic.md` und `docs-analyse.md`.
4. **Mittel:** Log-/Queue-Pfade mit `system/data/logs/` bzw. `get_path("logs")` vereinheitlichen.
5. **Mittel:** `SKILL.md:142` auf `system/hub/_services/help/` korrigieren; `help_forensic.py`-TODO prüfen/umsetzen.
6. **Niedrig:** In allen Workflows Pfadangaben konsistent mit `system/`-Präfix versehen, um die eigene Anforderung "Kanonisch?" zu erfüllen.

## 6. Nicht geprüft / offene Punkte

- Dieser Bericht erhebt keinen Anspruch auf Vollständigkeit der inhaltlichen Fehler (z. B. Befehls-Syntax, Parameter).
- Die Kosten-/Zeitschätzungen in `help-expert-review.md` wurden nicht auf Plausibilität geprüft.
- Ob `help_forensic.py` tatsächlich implementiert werden soll oder ob der TODO-Eintrag obsolet ist, wurde nicht entschieden.

---
*Erstellt im Task-Worktree #2230, ausschließlich auf Basis gelesener Quellen ohne Modifikation der Originaldateien.*
