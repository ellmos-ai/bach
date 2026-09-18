# BACH Services

Dieses Verzeichnis enthält Service-Skills für BACH.

## Service vs. Handler

- **Handler** (in `hub/`): CLI-Kommandos, die über `bach --handler` aufgerufen werden
- **Services** (hier): Langlebige Dienste, die im Hintergrund laufen oder als Wrapper dienen

## Struktur

```
_services/
  service_name/
    SKILL.md        # Service-Definition mit YAML-Header
    service.py      # Hauptimplementierung
    config.json     # Konfiguration (optional)
```

## Beispiel-Services

Services können z.B. sein:
- Daemon-Prozesse
- API-Wrapper
- Scheduler
- Notification-Services

## Siehe auch

- `hub/_services/`: Handler-bezogene Service-Beschreibungen
- `ARCHITECTURE.md`: Skill-System Architektur (Bereich Arbeitsablaeufe/Registry)
