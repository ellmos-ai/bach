# Standalone Module: message_delivery

Autarkes Modul für Nachrichtenzustellung, Inbox/Outbox-Routing und Partner-Dispatch (Claude, Codex, Gemini, Ollama, User).

## Funktionen
- **Nachrichtenzustellung**: `send_message` mit atomarer Speicherung und Sender/Recipient-Validierung.
- **Routing**: Trennung von Inbox, Outbox, unread und Archiv.
- **Multi-Partner-Support**: Partner-Presence- und Ack-Unterstützung.
- **Standalone**: Funktioniert im Speicher (`:memory:`) und auf SQLite-Dateien.
