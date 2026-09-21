# CLI-Änderungs-Checkliste

> **Zweck:** Alle Schritte zum Einfügen oder Ändern eines CLI-Befehls unter der
> Registry-Architektur v2.0 (Handler implementieren, Alias, Help-Datei, Test).
> Auto-Discovery macht manuelle Registrierung in bach.py überflüssig.

**Version:** 2.0
**Stand:** 2026-09-16
**Kategorie:** Wartung, Entwicklung

---

## Übersicht

Dieser Workflow beschreibt alle Schritte, die nötig sind, wenn ein neuer CLI-Befehl
eingeführt oder ein bestehender geändert wird.

**Wichtig seit bach.py v2.0 (Registry-Architektur):**
Befehle werden NICHT mehr manuell in bach.py registriert. Die `HandlerRegistry`
(core/registry.py) entdeckt Handler automatisch (Auto-Discovery). Der klassische
Registrierungsschritt entfällt damit komplett.

```
┌─────────────────────────────────────────────────────────┐
│  NEUER CLI-BEFEHL: CHECKLISTE (5 Schritte)              │
├─────────────────────────────────────────────────────────┤
│  1. Handler implementieren (hub/<name>.py)              │
│  2. Alias festlegen (optional, core/aliases.py)         │
│  3. Help-Datei erstellen (docs/help/<name>.txt)         │
│  4. Verwandte Doku prüfen                               │
│  5. Test: Discovery + Operationen + Did-you-mean        │
└─────────────────────────────────────────────────────────┘
```

**Dauer:** 10-30 Minuten je nach Komplexität

### Architektur-Kontext (Dispatch-Kette)

```
bach.py (CLI)
  → core/app.py (App-Container)
    → core/registry.py (HandlerRegistry, Auto-Discovery)
      → hub/<name>.py (Handler, BaseHandler-Subklasse)
        → hub/_services/* (Service-Layer, optional)
```

---

## Schritt 1: Handler implementieren

**Ort:** `hub/<name>.py`

Die Registry scannt `hub/*.py` (Dateien mit `_`-Präfix werden ignoriert) und
lädt automatisch alle BaseHandler-Subklassen. Die Datei muss NICHT importiert
oder registriert werden.

### Vorlage

```python
"""Handler für <name> Funktionen."""
from pathlib import Path
from typing import List, Tuple

from hub.base import BaseHandler


class <Name>Handler(BaseHandler):
    """<Kurzbeschreibung>."""

    @property
    def profile_name(self) -> str:
        return "<name>"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / "<name>.json"

    def get_operations(self) -> dict:
        return {
            "list": "Einträge auflisten",
            "add": "Eintrag hinzufügen",
            "status": "Status anzeigen",
        }

    def handle(self, operation: str, args: List[str],
               dry_run: bool = False) -> Tuple[bool, str]:
        if operation in (None, "", "help"):
            return True, self._usage()
        ops = self.get_operations()
        if operation not in ops:
            return False, (f"Unbekannte Operation: {operation}. "
                           f"Verfügbar: {', '.join(ops)}")
        # ... Implementierung, Rückgabe: (success, message)
        return True, "OK"

    def _usage(self) -> str:
        ops = self.get_operations()
        lines = [f"<name> - Nutzung:", ""]
        lines += [f"  bach <name> {op:<12} {desc}" for op, desc in ops.items()]
        return "\n".join(lines)
```

### Registry-Regeln (core/registry.py)

Der `profile_name` wird in dieser Reihenfolge ermittelt:
1. `profile_name`-Property direkt an der Klasse (empfohlen, siehe Vorlage)
2. Klassen-Attribut `_profile_name`
3. Heuristik: `TaskHandler` → `task` (Klassenname ohne `Handler`, lowercase)
4. Fallback: Dateiname ohne Endung

**Wichtige Randbedingungen:**

```
□ Klasse von BaseHandler ableiten (hub/base.py)
□ Alle 4 abstrakten Member implementiert:
    profile_name, target_file, get_operations(), handle()
□ handle() erhält die Operation DIREKT (nicht args[0] parsen!)
□ Dateiname OHNE _-Präfix (sonst wird sie vom Discovery ignoriert)
□ Multi-Handler-Dateien erlaubt (mehrere Handler-Klassen in einer
  Datei, z.B. hub/time.py mit clock/timer/countdown/between/beat)
□ NIEMALS als <name>-HOST.py speichern (Host-Conflict-Kopien
  werden vom Registry-Discovery mit [WARN] ignoriert)
□ BaseHandler dual-init-kompatibel: __init__ NICHT überschreiben
  ohne super().__init__(base_path_or_app) aufzurufen
```

---

## Schritt 2: Alias festlegen (optional)

**Ort:** `core/aliases.py`

Ein neuer Befehl ist nach dem Erstellen von `hub/<name>.py` sofort
verfügbar (`bach <name>` UND `bach --<name>`). Manuelle Registrierung
in bach.py ist NICHT mehr nötig.

Nur wenn eine **Kurzform** gewünscht ist (wie `mem` → `memory`):

```python
# core/aliases.py, COMMAND_ALIASES:
COMMAND_ALIASES = {
    # ... bestehende ...
    "<kurz>": "<name>",  # NEU HINZUFÜGEN
}
```

Optional Default-Operation (falls `bach <name>` ohne Argument eine
sinnvolle Standard-Aktion haben soll):

```python
# core/aliases.py, DEFAULT_OPERATIONS:
DEFAULT_OPERATIONS = {
    # ... bestehende ...
    "<name>": "list",  # NEU HINZUFÜGEN
}
```

### Checkliste

```
□ Alias nur bei Bedarf (Vollname ist automatisch verfügbar)
□ Alias in COMMAND_ALIASES eingetragen (kein Duplikat-Ziel)
□ DEFAULT_OPERATIONS ergänzt, falls sinnvoll
□ Keine Änderung an bach.py erforderlich!
```

---

## Schritt 3: Help-Datei erstellen

**Ort:** `docs/help/<name>.txt`

Sprachvarianten optional: `<name>_en.txt`, `<name>_es.txt`,
`<name>_ja.txt`, `<name>_ru.txt`, `<name>_zh.txt`.

### Vorlage

```
<NAME> - <Kurzbeschreibung>
============================

BESCHREIBUNG
------------
<Was macht dieser Befehl?>

BEFEHLE
-------
  bach <name> list          <Beschreibung>
  bach <name> add <args>    <Beschreibung>
  bach <name> status        <Beschreibung>

BEISPIELE
---------
  # Beispiel 1
  bach <name> list

  # Beispiel 2
  bach <name> add "Etwas"

TECHNISCHE DETAILS
------------------
  Handler: hub/<name>.py
  DB-Tabelle: (falls relevant)
  Config: (falls relevant)

SIEHE AUCH
----------
  bach --help <verwandt>
  bach --help tasks
```

### Checkliste

```
□ Datei in docs/help/<name>.txt erstellt (NICHT skills/docs/help/!)
□ Alle Operationen aus get_operations() dokumentiert
□ Beispiele vorhanden
□ SIEHE AUCH verweist auf relevante Themen
□ Optional: Sprachvarianten (_en etc.) angelegt
```

---

## Schritt 4: Verwandte Doku prüfen

**Hinweis:** Eine zentrale SKILL.md-Befehlsübersicht existiert nicht mehr
(obsolet seit dem Umstieg auf skills/). Stattdessen:

```
□ skills/workflows/ durchsuchen: Referenziert ein Workflow diesen
  Befehl oder eine veraltete Konvention? → ggf. aktualisieren
□ Bei Namens-/Pfad-Konflikten: docs/help/cli.txt und
  docs/help/naming.txt konsultieren
□ Recurring-Tasks (hub/_services/recurring/config.json) prüfen,
  falls ein Task den Befehl automatisiert verwenden soll
```

Verwandte Workflows in `skills/workflows/` (z.B.
`system-anschlussanalyse.md`, `cli-aenderung-checkliste.md` selbst)
konsolidieren statt duplizieren.

---

## Schritt 5: Test

### Manuelle Tests

```bash
# 1. Discovery: Wird der Handler gefunden?
bach --maintain registry          # Registry-Watcher (Konsistenz)

# 2. Help funktioniert?
bach --help <name>

# 3. Beide Varianten?
bach <name> list
bach --<name> list

# 4. Did-you-mean bei Tippfehler?
bach <nam> list                   # Sollte "<name>" vorschlagen
                                  # (Registry.suggest() übernimmt das)

# 5. Operationen funktionieren?
bach <name> add "Test"
bach <name> status

# 6. Unbekannte Operation abgefangen?
bach <name> unsinn                # → "Unbekannte Operation: ..."
```

### Hilfreiche Wartungs-Befehle

```bash
bach --maintain docs              # Docs-Check (Pfad-Referenzen)
bach --maintain skills            # Skill-Health-Monitor
bach --maintain skill-help <name> # Help-Datei aus SKILL-Doku generieren
bach --maintain workflows         # Workflow-Validator
```

**Veraltet (nicht mehr verwenden):** `--maintain heal` (ersetzt durch
`--maintain health` bzw. `--maintain registry`), `--maintain integration`
(wurde nie implementiert – Konsistenzprüfung läuft jetzt über
`--maintain registry` und den Recurring-Task `integration_check`, 30 Tage).

---

## Schnell-Checkliste (Kopiervorlage)

```
NEUER CLI-BEFEHL: <name>
========================

□ hub/<name>.py erstellt (BaseHandler-Subklasse)
□ profile_name + target_file + get_operations() + handle() implementiert
□ KEINE Registrierung in bach.py nötig (Auto-Discovery)
□ Alias in core/aliases.py ergänzt (nur falls Kurzform gewünscht)
□ DEFAULT_OPERATIONS ergänzt (falls Default-Aktion sinnvoll)
□ docs/help/<name>.txt erstellt
□ Verwandte skills/workflows/ geprüft/ggf. aktualisiert
□ Test: bach --maintain registry
□ Test: bach --help <name>
□ Test: bach <name> [operation] UND bach --<name> [operation]
□ Test: Tippfehler -> Did-you-mean (Registry.suggest())
```

---

## Automatisierung

### Verfügbare Werkzeuge

1. **Skill-Generator** (Skill-Strukturen, NICHT Handler-Boilerplate):
   ```bash
   bach --maintain generate <name> [PROFIL] [zielordner]
   # Profile: MICRO, LIGHT, STANDARD, EXTENDED
   # Siehe: tools/skill_generator.py
   ```

2. **Konsistenz-Check (Registry-Watcher):**
   ```bash
   bach --maintain registry
   ```
   → Prüft Handler-Registry und Discovery-Konsistenz

3. **Help-Datei-Generator:**
   ```bash
   bach --maintain skill-help <name>
   ```
   → Generiert docs/help/*.txt aus Skill-Doku

4. **Recurring-Task `integration_check`** (30 Tage):
   → Führt `skills/workflows/system-anschlussanalyse.md` aus;
   deckt veraltete Referenzen auf (wie diese Checkliste).

### Mögliche Verbesserungen

- Pre-Commit Hook: Warnt, wenn Handler ohne Help-Datei committet wird
- `--maintain registry --strict`: Fail wenn Discovery-Warnungen auftreten

---

## Siehe auch

- `skills/workflows/system-anschlussanalyse.md` - Allgemeine Konsistenz
- `docs/help/cli.txt` - CLI-Konventionen
- `docs/help/coding.txt` - Coding-Standards
- `docs/help/naming.txt` - Namenskonventionen
- `core/registry.py` - HandlerRegistry (Auto-Discovery, Quellcode)
- `core/aliases.py` - COMMAND_ALIASES und DEFAULT_OPERATIONS
- `hub/base.py` - BaseHandler-Interface

---

## Historie

| Version | Datum | Änderung |
|---------|-------|----------|
| 1.0 | 2026-01-22 | Erstellt (elif-basierte Architektur, hub/handlers/, KNOWN_COMMANDS, SKILL.md) |
| 2.0 | 2026-09-16 | Umgestellt auf Registry-Architektur v2.0: Auto-Discovery statt bach.py-Registrierung, hub/<name>.py statt hub/handlers/, Help-Pfad docs/help/ statt skills/docs/help/, SKILL.md- und KNOWN_COMMANDS-Schritte entfernt, --maintain integration (nie implementiert) durch --maintain registry ersetzt (Task 1310, Anschluss an Task 1309) |

---

*Erstellt: 2026-01-22 | Update: 2026-09-16 (Task 1310) | Anlass: Umstieg auf Registry-Architektur v2.0*