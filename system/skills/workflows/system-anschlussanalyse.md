# System-Anschlussanalyse: Integration & Konsistenz

**Version:** 2.0  
**Stand:** 2026-09-16  
**Kategorie:** Wartung, Qualitätssicherung

---

## Übersicht

Dieser Workflow prüft BACH auf unverbundene Systembereiche, Inkonsistenzen und Integrationslücken. Ziel ist es, parallele/doppelte Strukturen zu erkennen und zu konsolidieren.

```
┌─────────────────────────────────────────────────────────┐
│         ANSCHLUSSANALYSE (5 Schritte)                   │
├─────────────────────────────────────────────────────────┤
│  1. Dokumentations-Scan (Help vs. Handler vs. Services) │
│  2. Registry-Vollständigkeit prüfen (Auto-Discovery)    │
│  3. Cross-Referenzen validieren                         │
│  4. Doppelstrukturen identifizieren                     │
│  5. Integrations-Tasks erstellen                        │
└─────────────────────────────────────────────────────────┘
```

**Dauer:** 15-30 Minuten  
**Empfohlene Häufigkeit:** Monatlich oder nach größeren Änderungen  
**Recurring-Task:** `integration_check` (30 Tage) in `hub/_services/recurring/config.json`

---

## Architektur-Kontext (Stand 2026-09)

Seit BACH v2.0 ist das CLI **registry-basiert** – es gibt KEINE statische Handler-Map mehr:

```
bach.py (CLI-Entry)
   └─> core/app.py (App.get_handler)
         └─> core/registry.py (HandlerRegistry)
               ├─ Auto-Discovery: hub/*.py  → BaseHandler-Subklassen
               ├─ COMMAND_ALIASES: core/aliases.py (mem → memory, etc.)
               └─ Handler-Instanzen
                     └─> Logik in hub/_services/* (Service-Layer)
```

**Wichtige Punkte:**
- **Handler-Layer:** `hub/*.py` – jede Datei mit `BaseHandler`-Subklasse (aus `hub/base.py`) wird automatisch registriert.
- **Service-Layer:** `hub/_services/*` – Service-Implementierungen (chat, llm, newspaper, recurring, scheduling, weather, wiki, ...), von Handlern importiert. Viele Services haben ein eigenes `SKILL.md`.
- **Kein `elif`-Command-Routing, kein `_import_handler`, kein `KNOWN_COMMANDS`** – diese Patterns existieren nur noch im Archiv: `hub/_archive/DEPRECATED_hub.py`. Legacy-Backup des alten CLIs: `bach_legacy.py`.
- **Did-you-mean:** Bei unbekannten Befehlen schlägt `registry.suggest()` Alternativen vor.
- **Hot-Reload:** `registry.reload()` erlaubt Handler-Neuerkennung ohne Neustart.
- **Help-Doku:** `docs/help/*.txt` (plus Sprachvarianten `_en`, `_es`, `_ja`, `_ru`, `_zh`).

---

## Schritt 1: Dokumentations-Scan

**Zweck:** Prüfen ob Help-Texte, Handler und Services konsistent sind

### Prüfpunkte

| Quelle | Prüfung | Wie |
|--------|---------|-----|
| `docs/help/*.txt` | Alle Handler dokumentiert? | Verzeichnis-Listing vs. Registry |
| `hub/*.py` | Alle Handler haben eine Help-Datei? | BaseHandler-Subklassen zählen |
| `hub/_services/*/SKILL.md` | Services beschrieben? | Service-Verzeichnisse prüfen |
| `docs/help/practices.txt` | REGELWERK-INDEX vollständig? | `bach --help practices` |
| `core/aliases.py` | Aliase dokumentiert (z.B. `mem` → `memory`)? | Alias-Tabelle prüfen |

### Checkliste

```
□ Jeder Handler in hub/*.py hat eine docs/help/*.txt Datei
□ Jeder Service in hub/_services/* hat ein SKILL.md (oder bewusst nicht)
□ REGELWERK-INDEX verweist auf alle relevanten Themen
□ Keine verwaisten Help-Dateien ohne Handler
□ COMMAND_ALIASES mit CLI-Doku abgeglichen
```

---

## Schritt 2: Registry-Vollständigkeit

**Zweck:** Auto-Discovery auf Lücken prüfen

### Aktuelles Routing (v2.0, registry-basiert)

```python
# bach.py: beide Wege laufen über die Registry (core/registry.py)
# 1. Mit --:   bach --memory facts read
# 2. Ohne --:  bach mem facts read   (Alias via core/aliases.py)
handler = app.get_handler(name)   # App aus core/app.py
```

Es gibt KEINE manuelle Registrierung mehr: Ein neuer Handler wird allein durch
eine `BaseHandler`-Subklasse in `hub/*.py` sichtbar.

### Registry-Regeln (core/registry.py)

| Regel | Details |
|-------|---------|
| Discovery | Scannt `hub/*.py` (top-level, ohne `_`-Präfix) |
| profile_name | 1. `profile_name`-Property → 2. `_profile_name`-Attribut → 3. Klassennamen (`XxxHandler` → `xxx`) → 4. Dateiname |
| Multi-Handler-Dateien | Mehrere Handler pro Datei möglich (z.B. `time.py` mit 5 Handlern) |
| Host-Conflict-Kopien | `name-HOST.py`-Kopien werden ignoriert (kanonische Datei gewinnt) |
| Aliase | `COMMAND_ALIASES` aus `core/aliases.py`, nach Discovery angewendet |

### Prüfung

```bash
# Registry lädt alle Handler ohne Fehler/Warnungen?
python bach.py --startup            # Registry wird beim Start discoveriert

# Handler-Anzahl plausibel?
# → Registry-Watcher: bach --maintain registry

# Defekte Handler-Dateien finden (WARN-Zeilen im Startup-Log)
# Registry loggt: "[WARN] Handler <datei>: <fehler>" bei Import-Fehlern
```

### Ziel

- Jede Handler-Datei in `hub/*.py` importiert sauber (keine `[WARN]`-Zeilen).
- Jeder Befehl ist über BEIDE Wege erreichbar: `bach --<handler>` und `bach <handler>` (bzw. Alias).
- Bei unbekanntem Befehl erscheint eine Did-you-mean-Ausgabe (`registry.suggest()`).

---

## Schritt 3: Cross-Referenzen validieren

**Zweck:** Verweise zwischen Systemen prüfen

### Typische Inkonsistenzen

| Problem | Beispiel | Lösung |
|---------|----------|--------|
| Alter Pfad | `skills/docs/help/*` statt `docs/help/*` | Referenz korrigieren |
| Obsoleter Befehl | `--maintain heal`, `--maintain integration` | Ersetzt/entfernt – Doku aktualisieren |
| Fehlende Referenz | Help-Datei erwähnt nicht existierende Datei | Korrigieren |
| Doppelte Doku | Info in `docs/help/*.txt` UND in DB | Konsolidieren |
| Veraltete Patterns | `elif command ==`, `_import_handler` | Nur noch in `hub/_archive/` – Doku umschreiben |

### Befehle

```bash
# Registry-Konsistenz (tools/maintenance/registry_watcher.py)
bach --maintain registry

# Skill-Health (tools/maintenance/skill_health_monitor.py)
bach --maintain skills

# BACH-Gesamtstatus
bach --maintain health

# Registry-Health-Reports (automatisch, JSON)
# → logs/registry_health_*.json (Registry vs. Dateisystem-Abgleich)

# HINWEIS: 'bach --maintain heal' ist VERALTET.
# Pfade werden zentral über hub/bach_paths.py aufgelöst,
# Path-Healer separat: bach --help tools/path_healer
```

---

## Schritt 4: Doppelstrukturen identifizieren

**Zweck:** Parallele Systeme erkennen und zusammenführen

### Bekannte Doppelstrukturen (bewusst gepflegt)

| Bereich | Struktur A | Struktur B | Empfehlung |
|---------|------------|------------|------------|
| Lessons | `docs/help/lessons.txt` (statisch) | memory_lessons DB (dynamisch) | Help verweist auf DB |
| Facts | memory_facts DB | config.json | DB für dynamisch, JSON für statisch |
| Befehle | `bach mem` (Alias) | `bach --memory` (Handler) | Beide behalten, Aliase in `core/aliases.py` dokumentieren |
| CLI-Layer | `bach.py` (v2.0) | `bach_legacy.py` (Backup) | Legacy nur als Referenz, nicht erweitern |

### Prüffragen

```
□ Gibt es zwei Orte für die gleiche Information?
□ Welcher ist die "Single Source of Truth"?
□ Kann einer auf den anderen verweisen statt duplizieren?
□ Gibt es Archiv-/Backup-Kopien, die fälschlich weitergepflegt werden?
  (→ nur hub/_archive/ und *.bak-* zählen als Archiv)
```

---

## Schritt 5: Integrations-Tasks erstellen

**Zweck:** Gefundene Lücken als Tasks erfassen

### Task-Kategorien

| Kategorie | Präfix | Beispiel |
|-----------|--------|----------|
| Dokumentation | DOC | DOC: Help-Datei für Handler X fehlt |
| Integration | INTEG | INTEG: Service Y nicht mit Handler verknüpft |
| Migration | MIG | MIG: Alte Pfade in Doku korrigieren |

### Befehl

```bash
bach task add "DOC: Help-Datei für Handler X fehlt" --priority P3 --category DOC
bach task add "INTEG: Service Y in _services ohne SKILL.md" --priority P3
```

---

## Automatisierung

### Option A: Als Recurring Task (AKTIV)

Der Recurring-Task `integration_check` existiert bereits in
`hub/_services/recurring/config.json` (alle 30 Tage, P3):

```json
"integration_check": {
    "enabled": true,
    "interval_days": 30,
    "target": "tasks",
    "task_text": "Anschlussanalyse: bach --maintain registry + skills. Workflow: skills/workflows/system-anschlussanalyse.md"
}
```

### Option B: In Startup integriert (Quick-Check)

Bereits implementiert in `bach --startup`:
- Directory Scan ✅
- Registry-Watcher ✅
- Skill Health ✅

### Option C: Registry-Health-Report (automatisch)

`bach --maintain registry` bzw. der Startup-Check erzeugt JSON-Reports:
`logs/registry_health_*.json` – Registry-Einträge vs. Dateisystem
(erwartete Pfade vs. tatsächliche Pfade, inkl. Skill-Workflows).

---

## Historie

### 2026-09-16 (Update, v2.0)

- Workflow auf registry-basierte Architektur (BACH v2.0) umgeschrieben.
- Obsolete Patterns entfernt: `hub/handlers/*.py`, `elif command ==`,
  `_import_handler`, `KNOWN_COMMANDS` (nur noch in `hub/_archive/DEPRECATED_hub.py`).
- Help-Pfade korrigiert: `skills/docs/help/*` → `docs/help/*`.
- `--maintain heal` als VERALTET markiert, `--maintain integration`
  (war nie implementiert) entfernt.
- Recurring-Task `integration_check` dokumentiert.
- **Offene Fundstellen außerhalb dieses Workflows:**
  `skills/workflows/cli-aenderung-checkliste.md` referenziert noch
  `bach --maintain integration` und `skills/docs/help/cli.txt` → nachpflegen.

### 2026-01-22 (Erstfassung, v1.0)

Gefunden und gelöst: CLI-Syntax `partner` (elif-Block), Did-you-mean
(`_suggest_command()`), `docs/help/cli.txt` erstellt, REGELWERK-INDEX ergänzt.

---

## Schnell-Checkliste

```
□ docs/help/*.txt ↔ hub/*.py Handler-Abgleich
□ hub/_services/* Services: SKILL.md vorhanden oder bewusst verzichtet
□ core/aliases.py Aliase dokumentiert
□ bach --startup ohne [WARN]-Zeilen
□ bach --maintain registry OK (logs/registry_health_*.json fehlerfrei)
□ bach --maintain skills OK
□ Keine Doppelstrukturen oder dokumentiert
□ Keine Doku-Verweise auf obsolete Patterns (_archive, bach_legacy)
□ Integrations-Tasks erstellt
```

---

## Siehe auch

- `skills/workflows/system-mapping.md` - Feature-Erfassung
- `skills/workflows/system-synopse.md` - System-Übersicht
- `docs/help/maintain.txt` - Wartungs-Tools
- `docs/help/practices.txt` - Regelwerk-Index
- `docs/help/cli.txt` - CLI-Konventionen
- `core/registry.py` - Handler-Registry (Auto-Discovery)
- `core/aliases.py` - Command-Aliase