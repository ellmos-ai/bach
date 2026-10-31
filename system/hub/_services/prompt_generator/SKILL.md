# BACH Prompt-Generator Service

## Zweck
Der Prompt-Generator ist ein systemweites Service für Prompt-Management und automatisierte Claude-Sessions. Er ersetzt das ATI-spezifische Session-System durch ein einheitliches Prompt-Management mit folgenden Features:

1. **Texteditor** für Startprompt (mit Reset-Funktion)
2. **Vorlagen-Auswahl** (System/Agenten/Eigene)
3. **Vier Sendeoptionen** (ALS TASK, DIREKT SESSION, TEXT KOPIEREN, DAEMON-STEUERUNG)
4. **Daemon-Steuerung** (Zeitplanung)

## Endpunkte/API
- **Lokale CLI** (kein REST-API, lokale Dienst)
- **Prompt-Editor** (interaktive Text-Editor-Funktion)
- **Konfiguration** (config.json) - Intervall, Sperrzeiten, etc.
- **Template-System** (prompts/ directory) - System-, Agenten- und User-Vorlagen

## Abhängigkeiten
- `config.json` (Konfiguration der Task-Intervalle und Sperrzeiten)
- `prompts/` (Template-Dateien für System-, Agenten- und User-Vorlagen)
- `hub/_services/chat/chat_runtime.py` (Lazy-Import des Chat-Runtimes)
- `hub/_services/daemon_api.py` (Daemon-Steuerung)

## Dateien
- `prompt_generator.py` — Hauptlogik (Prompt bauen, Session triggern)
- `config.json` — Konfiguration (Intervall, Sperrzeiten, etc.)
- `templates/` — HTML-Vorlagen für Berichte (system/, agents/, custom/)
- `profiles/` — Daemon-Profile (ati.json, wartung.json)

## Nutzung
```bash
# Hauptlogik (Prompt bauen, Session triggern)
python prompt_generator.py

# Konfiguration (Intervall, Sperrzeiten)
python prompt_generator.py config
```

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

## Migration von ATI
Die ATI-Session-Dateien wurden bereits als DEPRECATED markiert:
- `agents/ati/session/` → DEPRECATED.md verweist hierher
- Prompt-Templates: Von `agents/ati/prompt_templates/` hierher verschoben

## GUI
Geplant unter `/prompt-generator` - siehe `skills/docs/help/prompt-generator.txt`

## Status
In Entwicklung - Tasks PROMPT_GEN_001-007 in ROADMAP.md
