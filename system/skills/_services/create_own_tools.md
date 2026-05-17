---
name: create_own_tools
metadata:
  version: 1.0.0
  last_updated: 2025-12-19
description: >
  Erstellt eigene Claude-Tools basierend auf gefundenen Snippets oder
  Nutzeranfragen. Integriert mit search_for_useful_snippets und coding-tools.
  Kann automatisch bei neuen Tool-Kandidaten oder manuell aktiviert werden.
---

# Create Own Tools

**Automatisierte Erstellung von Claude-kompatiblen Tools.**

## Zweck

- Wandelt Code-Snippets in vollwertige c_ Tools um
- Erstellt neue Tools nach Nutzeranfragen
- Standardisiert Tool-Struktur und Dokumentation
- Integriert neue Tools in coding-tools Registry

## Aktivierung

### Automatisch (bedingt)
Wird von skill-administration-system aktiviert wenn:
```
1. search_for_useful_snippets neue Tool-Kandidaten findet
2. User bestätigt: "Ja, erstelle Tools daraus"
```

### Manuell
User sagt:
- "Erstelle ein Tool für X"
- "Mach daraus ein Claude-Tool"
- "Konvertiere zu c_ Tool"

## Workflow

### A) Aus Snippet (automatisch)

```
[search_for_useful_snippets findet Tool-Kandidat]
    ↓
[User bestätigt Erstellung]
    ↓
create_own_tools:
    1. Snippet-Details aus snippet_index.json laden
    2. Quellcode analysieren
    3. c_ Tool generieren:
       - GUI entfernen (falls vorhanden)
       - CLI-Interface hinzufügen
       - Docstring erstellen
       - JSON-Output Option
    4. In coding-skills/tools/python/ speichern
    5. Registry aktualisieren
    6. integration_log.txt erweitern
```

### B) Nach Nutzeranfrage (manuell)

```
User: "Erstelle ein Tool das CSV zu JSON konvertiert"
    ↓
create_own_tools:
    1. Anforderungen klären (Interaktiv falls nötig)
    2. Tool-Struktur planen
    3. Code generieren nach c_ Standard
    4. Testen (Syntax-Check)
    5. Speichern und registrieren
```

## Tool-Standard (c_ Format)

### Struktur
```python
"""
c_<tool_name>.py - <Kurzbeschreibung>

Zweck: <Ausführliche Beschreibung>
Autor: Claude
Abhängigkeiten: <Liste>

Usage:
    python c_<tool_name>.py <args> [--json]
    
Beispiele:
    python c_<tool_name>.py input.txt
    python c_<tool_name>.py input.txt --output out.txt
"""

import argparse
import json
from typing import Dict, Any

def main_function(input_path: str, **options) -> Dict[str, Any]:
    """Hauptlogik - Returns Dict für Weiterverarbeitung."""
    result = {"success": False, "error": None}
    # ... Implementierung ...
    return result

def print_report(result: Dict[str, Any]) -> None:
    """Human-readable Output."""
    # ... Formatierte Ausgabe ...

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("input", help="...")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    
    result = main_function(args.input)
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)
```

### Pflicht-Elemente
- Docstring mit Usage und Beispielen
- `main_function()` mit Dict-Return
- `print_report()` für lesbare Ausgabe
- argparse CLI mit --json Option
- Type Hints
- Error Handling mit result["error"]

## Erstellungs-Checkliste

```
□ Dateiname: c_<snake_case>.py
□ Docstring vollständig (Zweck, Autor, Dependencies, Usage, Beispiele)
□ Hauptfunktion gibt Dict zurück
□ CLI mit argparse
□ --json Flag für Maschinenausgabe
□ Keine GUI-Abhängigkeiten
□ Keine hardcodierten Pfade
□ Syntax-Check bestanden
□ In Registry eingetragen
□ In integration_log dokumentiert
```

## Integration mit anderen Skills

### ← search_for_useful_snippets
```
Empfängt: Tool-Kandidaten mit Metadaten
- snippet_id
- source_file
- category
- dependencies
- recommendation
```

### → coding-tools
```
Liefert: Fertige c_ Tools
- Tool in python/ Ordner
- Registry-Eintrag
- Log-Eintrag
```

## Beispiel-Session

```
[Nach Snippet-Scan]
Claude: "3 neue Tool-Kandidaten gefunden:
         1. json_merger (data_processing) ⭐⭐⭐
         2. file_renamer (file_operations) ⭐⭐
         3. log_parser (text_processing) ⭐⭐⭐
         
         Soll ich daraus c_ Tools erstellen?"

User: "Ja, 1 und 3"

Claude: 
1. Lädt Snippets aus Index
2. Analysiert Quellcode
3. Erstellt c_json_merger.py
4. Erstellt c_log_parser.py
5. Aktualisiert Registry

"Fertig! 2 neue Tools erstellt:
 - c_json_merger.py (merged mehrere JSON-Dateien)
 - c_log_parser.py (extrahiert Einträge aus Log-Dateien)
 
 Tools sind unter coding-skills/tools/python/ verfügbar."
```

## Fehlerbehandlung

| Situation | Aktion |
|-----------|--------|
| Snippet nicht mehr vorhanden | User informieren, aus Index entfernen |
| Syntax-Fehler im Original | Versuch zu reparieren, sonst überspringen |
| Komplexe GUI-Abhängigkeit | Warnen, manuelle Prüfung empfehlen |
| Externe API-Abhängigkeit | Dokumentieren, ggf. Mock-Mode einbauen |

## Speicherorte

```
Generierte Tools:  %ONEDRIVE_AI_ROOT%\BACH\User\Tools\coding-tools\python\
Registry:          %ONEDRIVE_AI_ROOT%\BACH\User\Tools\coding-tools\_registry\
Log:               %ONEDRIVE_AI_ROOT%\BACH\User\Tools\coding-tools\_registry\integration_log.txt
```