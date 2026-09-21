---
name: reflection-agent
version: 1.0.0
type: agent
author: BACH Team
created: 2026-02-08
updated: 2026-09-18
anthropic_compatible: true
status: active

dependencies:
  tools: [reflection_analyzer.py]
  services: []
  workflows: []

metadata:
  inputs: "session-logs, task-results, error-logs"
  outputs: "performance-report, improvement-suggestions, gap-analysis"

description: >
  Selbstreflexions-Agent fuer BACH. Analysiert Session-Performance,
  identifiziert Schwachstellen und schlaegt Verbesserungen vor.
  Portiert aus BachForelle/skills/reflection.
---

# Reflection Agent

## Uebersicht

Der Reflection-Agent analysiert die eigene Performance und identifiziert
Verbesserungspotentiale. Er arbeitet meta-kognitiv und hilft dabei,
systematische Fehler zu erkennen und Lernprozesse zu optimieren.

## Verwendung

```bash
bach reflection status        # Performance-Zusammenfassung
bach reflection gaps          # Schwachstellen identifizieren
bach reflection review        # Letzte Session analysieren
bach reflection log           # Metriken anzeigen
```

## Funktionen

1. **Performance-Tracking**: Erfolgsrate, Latenz, Fehleranalyse
2. **Gap-Analyse**: Identifiziert Bereiche mit niedriger Erfolgsrate
3. **Session-Review**: Analysiert abgeschlossene Sessions
4. **Verbesserungs-Vorschlaege**: Konkrete Handlungsempfehlungen
