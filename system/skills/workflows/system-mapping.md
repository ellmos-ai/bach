# System-Mapping: Kartographie und Feature-Erfassung

> Systematische Erfassung und Dokumentation eines LLM-OS oder Skills.

**Version:** 1.0  
**Stand:** 2026-01-18  
**Quelle:** Konsolidiert aus BACH_STREAM

---

## Übersicht

Dieser Workflow beschreibt die systematische Erfassung und Dokumentation eines LLM-OS oder Skills.

```
┌─────────────────────────────────────────────────────────┐
│              MAPPING-WORKFLOW (4 Schritte)              │
├─────────────────────────────────────────────────────────┤
│  1. Directory-Scan                                      │
│  2. Feature-Analyse                                     │
│  3. Datenbank befüllen                                  │
│  4. Diff erstellen (bei Updates)                        │
└─────────────────────────────────────────────────────────┘
```

**Dauer:** 1-2 Stunden pro System

---

## Schritt 1: Directory-Scan

**Zweck:** Vollständige Ordnerstruktur erfassen

### Befehl

```python
fc_list_directory(<system_root>, depth=3)
```

### Tipps

| Tiefe | Verwendung |
|-------|------------|
| depth=2 | Schnelle Übersicht |
| depth=3 | Detailanalyse |
| Separat | Ordner >50 Dateien |

---

## Schritt 2: Feature-Analyse

**Zweck:** Funktionen und Konzepte identifizieren

### Aktivitäten

- [ ] SKILL.md / Entry Point lesen
- [ ] Kern-Konzepte extrahieren
- [ ] Tools/Befehle dokumentieren
- [ ] Registries auflisten
- [ ] Workflows verstehen

### Format Features.txt

```
SYSTEM: <name>

KERN-KONZEPTE:
1. Konzept A - Beschreibung
2. Konzept B - Beschreibung

TOOLS:
- tool1: Funktion
- tool2: Funktion

WORKFLOWS:
- Startup: ...
- Shutdown: ...
```

---

## Schritt 3: Datenbank befüllen

**Zweck:** Features strukturiert speichern

### Tabellen

| Tabelle | Felder |
|---------|--------|
| features | id, name, category, description |
| implementations | id, feature_id, system, status, location |
| test_results | id, system, test_date, profile, rating |

---

## Schritt 4: Diff erstellen

**Zweck:** Änderungen seit letztem Scan erkennen

### Format

```
ÄNDERUNGEN seit <datum>:

+ NEU:
  - /ordner/neue_datei.txt

- GELÖSCHT:
  - /ordner/alte_datei.txt

~ GEÄNDERT:
  - /ordner/datei.txt (Größe: 1KB → 2KB)
```

---

## Integration mit builder.md

Mapping ist Teil der **COMPARE** Funktion in `skills/_service/builder.md`:

```yaml
builder.compare:
  systems: [system1, system2]
  # Nutzt Mapping intern
```

---

## Schnell-Checkliste

```
□ Directory-Scan durchgeführt
□ Features.txt vollständig
□ Datenbank-Einträge vorhanden
□ Diff erstellt (falls Update)
```

---

*Konsolidiert aus BACH_STREAM: 2026-01-18*
