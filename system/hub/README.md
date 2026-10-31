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

## Ausnahmen-Register: Hub-Services ohne SKILL.md

Ordner unter `system/hub/_services/` ohne agenten-/nutzerrelevante
Oberflaeche erhalten bewusst keine SKILL.md (skill_health_monitor erzeugt
fuer fehlende SKILL.md in _services keine Issues).

| Ordner | Grund |
| --- | --- |
| chat | Chat-Engine-Bibliothek (compatibility seam `ellmos-chat`, BACH injiziert Tools/Transcripts/System-Prompt); Erreichbarkeit via telegram_chat und GUI/chat ueber Control-API :8081 |
| cloud | Internes Sync-Schreibschutz-Utility (providerneutraler Cloud-Manager, `get_cloud_manager()`, `cloud_pause(timeout=180)`) |
| connector | Internes Nachrichten-Routing (smart_router: Command-Parsing + Launcher-Ausfuehrung + Response-Routing, queue_processor) |
| daemon | DEPRECATED 2026-05-17 (pyautogui-Zombie-Prompts, config enabled=false); Ersatz: GUI-Daemon-Tab :8000, Buddha Control API :8081/api/chat, Claude /loop//schedule |
| docs | 7 interne maintenance_*-Skripte, kein Agenten-/Nutzer-Interface |
| literatur | Zitat-Formatter-Bibliothek INT01 (APA 7, MLA 9, Chicago, DIN 1505-2, Harvard + BibTeX, portiert aus LitZentrum) |
| profile | Profil-Layer-Bibliothek (user/profile.json + DB-Overrides assistant_user_profile -> Prompt-Kontext) |
| prompt_generator | Eigene Doku im README.md des Ordners (Status 'In Entwicklung', PROMPT_GEN_001-007) – keine Parallel-Doku |
| trithon | Trithon Phase 4/5 Multiagent-Infrastruktur (fencing.py: Leader-Fencing fail-closed; muschelgrund.py: Receipt->Facts-Projektion, Task #1448) |

Mit SKILL.md: `claude_bridge`, `newspaper`, `watcher`, `recurring`.

---
*73 Handler, registriert in bach.db (tools-Tabelle)*
*Letzte Aktualisierung: 2026-10-30*
