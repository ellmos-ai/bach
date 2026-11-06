# Standalone Module: conversation_store

Autarkes Modul für Chat-Transkriptspeicherung, Session-Snapshot-Hashing und Kontext-Begrenzung.

## Funktionen
- **Transkript-Persistenz**: Atomare Speicherung in `session_snapshots` via SHA256-gehashte Session-IDs.
- **Privacy-by-Design**: Transport-Identifier (Telegram-Chat-ID, Web-Session-ID) werden vor der Persistenz gehasht.
- **Kontext-Grenzen**: Erzwingt `max_messages` und `max_content_chars`, um Token-Überläufe zu verhindern.
- **Standalone**: Funktioniert im Speicher (`:memory:`) und auf bestehenden SQLite-Datenbanken.
