# BACH Prompt-Generator Service

System-Service für Prompt-Management und automatisierte Claude-Sessions.

## Status

**In Entwicklung** - Tasks PROMPT_GEN_001-007 in ROADMAP.md

## Konzept

Der Prompt-Generator ersetzt das ATI-spezifische Session-System durch ein
systemweites Prompt-Management mit folgenden Features:

1. **Texteditor** für Startprompt (mit Reset-Funktion)
2. **Vorlagen-Auswahl** (System/Agenten/Eigene)
3. **Vier Sendeoptionen**
4. **Daemon-Steuerung** (Zeitplanung)

## Architektur

```
hub/_services/prompt_generator/
├── README.md              # Diese Datei
├── config.json            # Konfiguration (Intervall, Sperrzeiten, etc.)
├── prompt_generator.py    # Hauptlogik (Prompt bauen, Session triggern)
├── templates/
│   ├── system/            # System-Vorlagen (nicht editierbar)
│   │   ├── minimal.txt
│   │   ├── task.txt
│   │   └── review.txt
│   ├── agents/            # Agenten-Vorlagen
│   │   ├── ati.txt
│   │   ├── steuer.txt
│   │   └── wartung.txt
│   └── custom/            # User-Vorlagen (aus DB)
└── profiles/              # Daemon-Profile (wie bisher)
    ├── ati.json
    └── wartung.json
```

## Sendeoptionen

1. **ALS TASK** - Prompt als Task in Warteschlange
2. **DIREKT SESSION** - Sofort Claude-Session starten (Ctrl+Alt+Space)
3. **TEXT KOPIEREN** - In Zwischenablage
4. **DAEMON-STEUERUNG** - Automatisierte Ausfuehrung

## Abgrenzung

| Komponente | Zweck | Verwendet |
|------------|-------|-----------|
| **Prompt-Generator** | Prompts erstellen/senden | Diesen Service |
| **Daemon (Wartung)** | Shell-Jobs ausfuehren | gui/api/daemon_api.py |
| **Recurring** | Task-Erinnerungen | hub/_services/recurring/ |

## Migration von ATI

Die ATI-Session-Dateien wurden bereits als DEPRECATED markiert:
- `agents/ati/session/` → DEPRECATED.md verweist hierher
- Prompt-Templates: Von `agents/ati/prompt_templates/` hierher verschoben

## GUI

Geplant unter `/prompt-generator` - siehe `skills/docs/help/prompt-generator.txt`

## Siehe auch

- `help prompt-generator` - Benutzer-Dokumentation
- `help daemon` - Wartungs-Daemon (Jobs)
- `help recurring` - Task-Erinnerungen