# CONCEPT: Tool Naming Convention Validator

**Status:** KONZEPT
**Ziel:** skills/tools/_policies/naming_convention.py
**Prioritaet:** P3

## Zweck

Automatische Pruefung und Migration von Tool-Dateinamen nach der
etablierten Praefix-Konvention.

## Praefix-System

| Praefix | Bedeutung | Beispiel |
|---------|-----------|----------|
| b_ | BACH-Kern (System) | b_backup.py |
| a_ | Agent-Runner | a_entwickler.py |
| t_ | Test-Tools | t_runner.py |
| m_ | Maintain/Wartung | m_cleanup.py |
| g_ | Generator-Tools | g_skill.py |
| (ohne) | Utility/Domain | dirscan.py |

## Funktionen

```python
class NamingConventionValidator:
    """Prueft und migriert Tool-Namen nach Konvention."""

    PREFIXES = {
        'b_': 'BACH-Kern',
        'a_': 'Agent-Runner',
        't_': 'Test-Tools',
        'm_': 'Maintain/Wartung',
        'g_': 'Generator-Tools',
    }

    LEGACY_MAPPING = {
        'agent_framework.py': 'a_framework.py',
        'entwickler_agent.py': 'a_entwickler.py',
        'research_agent.py': 'a_research.py',
        'production_agent.py': 'a_production.py',
        'backup_manager.py': 'b_backup.py',
        'cleanup.py': 'm_cleanup.py',
        'duplicate_detector.py': 'm_duplicate_detector.py',
        # ... weitere Mappings
    }

    def scan_tools(self, path: str) -> dict:
        """Scannt skills/tools/ und kategorisiert nach Konvention."""
        # Returns: {compliant: [], legacy: [], unknown: []}

    def suggest_migration(self, filename: str) -> str | None:
        """Schlaegt neuen Namen vor falls Legacy."""

    def check_new_tool(self, filename: str) -> bool:
        """Prueft ob neues Tool der Konvention folgt."""

    def generate_report(self) -> str:
        """Erstellt Migrations-Report."""
```

## CLI-Integration

```bash
# Pruefung
python naming_convention.py --scan
python naming_convention.py --check new_tool.py

# Report
python naming_convention.py --report

# Migration (mit Bestaetigung)
python naming_convention.py --migrate entwickler_agent.py
```

## Ausgabe --scan

```
TOOL NAMING CONVENTION SCAN
===========================

Konform (16):
  encoding_fixer.py     CLI-optimiert
  json_repair.py        CLI-optimiert
  ...

Legacy (8):
  entwickler_agent.py  -> a_entwickler.py
  backup_manager.py    -> b_backup.py
  ...

Domain/Utility (12):
  dirscan.py              (OK - kein Praefix)
  injectors.py            (OK - kein Praefix)
  ...
```

## Integration mit Wartungsagent

Der Naming-Validator kann vom Wartungsagent genutzt werden:

1. **Bei Startup:** Scan auf neue Legacy-Tools
2. **Bei Tool-Erstellung:** Automatische Pruefung
3. **Woechentlich:** Migrations-Report generieren

## Migration-Strategie

- **Evolutionaer:** Keine harten Brueche
- **Neue Tools:** Muessen Konvention folgen
- **Alte Tools:** Nach und nach migrieren
- **Referenzen:** Bei Umbenennung alle Imports aktualisieren

## Abhaengigkeiten

- skills/tools/tool_scanner.py (fuer DB-Updates nach Rename)
- bach.db.tools (Pfad-Updates)

## Naechste Schritte

1. [ ] Basis-Validator implementieren
2. [ ] --scan und --report Funktionen
3. [ ] Integration mit tool_scanner.py
4. [ ] Wartungsagent-Hook