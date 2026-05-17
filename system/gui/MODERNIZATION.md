# GUI Modernisierung - Strategie

Stand: 2026-05-17

## Interface-Hierarchie

| Interface | Status | Zielgruppe | Priorität |
|-----------|--------|------------|------------|
| **Claude Code CLI** | AKTIV | LLM-Sessions, Entwickler | Hoch |
| **BACH Chat Service** | AKTIV | Mobil, Remote, Chat | Hoch |
| **Zeitgesteuerte Agents** | AKTIV | Autonome Loop-/Tages-Sessions | Mittel |
| **REST API (headless)** | AKTIV | Scripts, Integrationen | Mittel |
| **Web-Dashboard** | AKTIV | Monitoring, Status, 29 Module | Mittel |
| **Prompt-Manager (PyQt6)** | LEGACY | Desktop-Power-User | Niedrig |

## Legacy: Prompt-Manager (gui/prompt_manager.py)

- Weiterhin nutzbar, keine aktive Weiterentwicklung
- PyQt6-Abhängigkeit bleibt optional
- Nicht entfernt, da bestehende Nutzer ihn verwenden könnten
- Bei Start: Hinweis auf moderne Alternativen

## Primär-Interfaces

### 1. Claude Code CLI (bach.py)
- Vollzugriff auf alle Handler via `bach` Befehle
- Library-API für LLMs (`bach_api`)
- Session-Management mit Startup/Shutdown
- Empfohlen für alle LLM-Interaktionen

### 2. BACH Chat Service (hub/_services/chat/)
- Nachfolger der Claude Bridge (claude_bridge/ ist deprecated)
- Multi-Backend: Ollama, Claude CLI, Codex CLI, Claude API, OpenAI API
- Telegram-Bot (@bach_assistant_bot) mit Tool-Use, Voice/OCR
- Web-Dashboard (:8081) mit Backend/Modus-Steuerung
- System Tray (chat_tray.py, cross-platform)
- CLI Chat (buddha_cli.py)
- Permission-System (safe/full Modi)

### 3. Zeitgesteuerte Agents
- Loop-Skripte (15min/30min/1h) für automatische Sessions
- Tages-Agent (hub/daily_agent.py) für tägliche Routinen
- Wartungs-Session (claude_maintenance.bat)
- Agent-Starter mit Modell- und Modus-Auswahl
- Siehe: start/_internal/claude_loop_*.bat, agent_start.bat
