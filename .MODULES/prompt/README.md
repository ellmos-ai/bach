# Standalone Module: prompt

Autarkes Modul zur Verwaltung von Prompt-Vorlagen, Versionierung und Zwei-Wege-Synchronisation mit PromptBoard.

## Funktionen
- **Prompt-Templates**: Anlegen, Auslesen, Suchen und Versionieren von Prompts.
- **Tag-Serialisierung**: Robuste bidirektionale JSON- und CSV-Tag-Formatierung.
- **PromptBoard-Sync**: Vollständiger Zwei-Wege-Abgleich (Reconciliation) mit `library.json`.
- **Standalone**: Funktioniert autark sowohl im Speicher (`:memory:`) als auch mit file-basierten SQLite-Datenbanken.
