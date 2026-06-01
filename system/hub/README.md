# hub/ - BACH Handler Registry

Das Herzstuck von BACH. Jede `.py`-Datei hier ist ein **Handler** - ein CLI-Befehl, den man mit `bach <name> <operation>` aufruft.

## Wichtigste Dateien

| Datei | Zweck | Beispiel |
|-------|-------|---------|
| `bach_paths.py` | Single Source of Truth fuer alle Pfade | `from hub.bach_paths import DATA_DIR` |
| `base.py` | BaseHandler - Basisklasse aller Handler | Jeder Handler erbt von BaseHandler |
| `__init__.py` | Package-Init, exportiert BaseHandler | |

## Wie Handler funktionieren

Jeder Handler hat Operationen. Beispiel `task.py`:

```bash
bach task add "Neuen Task erstellen"
bach task list
bach task done 42
bach task help
```

## Handler-Uebersicht (73 Handler)

**Kern-System:**
- `task.py` - Task-Verwaltung (add/list/done/priority)
- `memory.py` - Working Memory (add/search/list)
- `lesson.py` - Lessons Learned (add/list)
- `logs.py` - Log-Verwaltung (tail/search)
- `session.py` - Session-Management (startup/shutdown)
- `status.py` - System-Status
- `backup.py` - Backup-System
- `tools.py` - Tool-Registry (list/search/suggest)
- `help.py` - Hilfe-System

**Kommunikation:**
- `messages.py` - Nachrichten (send/unread/inbox)
- `email.py` - E-Mail-Versand
- `connector.py` - Externe Services (Telegram, Discord)
- `partner.py` - Multi-LLM Partner

**Domain-Handler:**
- `steuer.py` - Steuerverwaltung (beleg/posten/export)
- `haushalt.py` - Haushalt (fixkosten/routinen/einkauf)
- `gesundheit.py` - Gesundheit (diagnosen/medikamente/labor)
- `mediplaner.py` - Austausch zwischen BACH-Gesundheit und MediPlaner
- `contact.py` - Kontakte (list/search/add)
- `abo.py` - Abo-Verwaltung

**Erweitert:**
- `skills.py` - Skill-Management (create/reload)
- `wiki.py` - Wiki-System
- `plugins.py` - Plugin-System
- `hooks.py` - Hook-Verwaltung
- `recurring.py` - Periodische Tasks

## API-Zugriff (statt CLI)

```python
# Fuer LLMs: Immer ueber bach_api zugreifen!
from bach_api import task, memory, lesson, logs, tools, msg

task('add', 'Mein neuer Task')
task('list')
memory('add', 'Wichtige Info')
tools('search', 'ocr')
msg('unread')

# NICHT direkt auf bach.db zugreifen!
```

## Neuen Handler erstellen

```bash
bach skills create mein_handler --type handler
```

---
*73 Handler, registriert in bach.db (tools-Tabelle)*
*Letzte Aktualisierung: 2026-02-15*
