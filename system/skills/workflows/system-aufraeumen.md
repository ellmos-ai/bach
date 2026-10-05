# System-Aufräumen: Wartung und Archivierung

> Wartung, Bereinigung und Archivierung von BACH und zugehörigen Systemen.

**Version:** 1.0  
**Stand:** 2026-01-18  
**Quelle:** Konsolidiert aus BACH_STREAM

---

## Übersicht

Dieser Workflow beschreibt die Wartung, Bereinigung und Archivierung von BACH und zugehörigen Systemen.

```
┌─────────────────────────────────────────────────────────┐
│              AUFRÄUM-TYPEN                              │
├─────────────────────────────────────────────────────────┤
│  QUICK    (5 Min)  - Temp-Dateien, leere Ordner         │
│  STANDARD (15 Min) - + Memory, Transfer                 │
│  FULL     (30 Min) - Alle Bereiche + DB-Optimierung     │
└─────────────────────────────────────────────────────────┘
```

---

## Wann aufräumen?

| Trigger | Empfohlener Typ |
|---------|-----------------|
| Nach Synthese-Projekt | STANDARD |
| Nach größeren Änderungen | QUICK |
| Wöchentlich | STANDARD |
| Bei Platzmangel | FULL |
| Vor Backup/Export | FULL |

---

## Aufräum-Bereiche

### 1. Temp-Dateien

```
Muster: *.tmp, *_old.*, *_backup*, *_temp_*
Aktion: Löschen
```

### 2. Memory

```
SESSION_MEMORY > 50 Zeilen → Archivieren
Alte Sessions → _memory/archiv/
```

### 3. Datenbank

```
SQLite → VACUUM ausführen
Alte Test-Ergebnisse (>30 Tage) → Archivieren
```

### 4. Docs

```
Veraltete Synopsen → Archivieren
Entwürfe mit finaler Version → Löschen
```

---

## Archivierungs-Regeln

### Was archivieren

- Abgeschlossene Projekte
- Alte Testergebnisse (>30 Tage)
- Session-Memories (>50 Zeilen)
- Veraltete Synopsen

### Was löschen

- Temp-Dateien
- Backup-Duplikate
- Leere Ordner
- Abgebrochene Entwürfe

### NIEMALS löschen

- Workflows (skills/workflows/)
- Templates
- Datenbanken (nur Backup)
- SKILL.md, AUFGABEN.txt, CHANGELOG.txt

### Archiv-Ziel

```
_ARCHIV/<Jahr>/<Monat>/
```

---

## Befehle

### Temp-Dateien finden

```python
fc_search_files(directory, "*.tmp")
fc_search_files(directory, "*_old.*")
fc_search_files(directory, "*_backup*")
```

### Leere Ordner finden

```python
fc_list_directory(path, depth=2)
# Prüfen auf "(Verzeichnis ist leer)"
```

### Datenbank optimieren

```python
import sqlite3
c = sqlite3.connect('bach.db')
c.execute('VACUUM')
c.close()
```

---

## Checkliste FULL CLEANUP

```
□ Temp-Dateien gelöscht
□ Leere Ordner entfernt
□ Memory archiviert
□ Tests archiviert
□ Docs konsolidiert
□ Datenbanken optimiert
□ _ARCHIV organisiert
□ Backup erstellt
```

---

*Konsolidiert aus BACH_STREAM: 2026-01-18*
