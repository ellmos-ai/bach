# BACH Startmodi

## Einheitlicher Bootscreen

**`bach.bat`** - Zentrales Boot-Menü mit allen Modi. Doppelklick zum Starten.

**`bach.sh`** - Cross-Platform-Launcher für macOS/Linux (`chat`, `gui`, `status`, `stop`).

```
  --- SCHNELLSTART --------------------------------
  [D]  Default Start (GUI + Tray + PromptBoard)

  --- VERBINDEN ----------------------------------
  [W]  Buddha Connect (Server-Modus)

  --- BACH CHAT SERVICE --------------------------
  [B]  Chat Service starten    [S]  Status    [X]  Stop

  --- INTERAKTIV ---------------------------------
  [1]  User-Konsole        [2]  Advanced Console
  [3]  Web-Dashboard       [5]  Gemini-Partner Menü

  --- CLAUDE AUTO-SESSIONS -----------------------
  [6]  Alle Tasks 15min    [7]  Alle Tasks 30min
  [8]  Alle Tasks 1h       [9]  Zugewiesen 15min
  [0]  Zugewiesen unbegrenzt

  --- CLAUDE SPEZIAL ----------------------------
  [F]  Full Access         [P]  Remote Control
  [M]  Maintenance

  --- CLAUDE LOOP (Endlos) ----------------------
  [L]  Loop 15min  [N]  Loop 30min  [H]  Loop 1h

  --- AGENTEN -----------------------------------
  [G]  Agent starten (Menü)

  --- AUTOMATISIERUNG ----------------------------
  [C]  Neue Kette  [R]  MarbleRun  [U]  llmauto  [T]  Status
```

## Server-Modus

Option `[W]` verbindet zu einem BACH-Server (z.B. Mac Studio):

1. Prüft Erreichbarkeit des Servers via Control API (:8081)
2. Startet System Tray mit `--host` (Remote-Steuerung)
3. Öffnet GUI Dashboard im Browser

Standard-Host: `macstudvonlukas` (Tailscale). Eigener Host via ENV:
```
SET BACH_HOST=mein-server
bach.bat
```

Falls Server nicht erreichbar: Angebot für lokalen Start.

## Einzelne Startdateien (Legacy)

Die einzelnen .bat-Dateien liegen in `start/_internal/` und werden von `bach.bat` aufgerufen.

| Datei | Beschreibung |
|-------|-------------|
| `start_always_on.bat` | Mistral Watcher + Telegram/Discord |
| `start_console.bat` | User-Konsole (einfaches CLI) |
| `start_console_advanced.bat` | Advanced Console (bach.py direkt) |
| `start_gui.bat` | Web-Dashboard auf http://127.0.0.1:8000 |
| `start_gemini.bat` | Gemini-Partner Menü |
| `claude_all_15min.bat` | Alle Tasks, 15 Min, 50 Turns |
| `claude_all_30min.bat` | Alle Tasks, 30 Min, 100 Turns |
| `claude_all_1h.bat` | Alle Tasks, 1h, 200 Turns |
| `claude_assigned_15min.bat` | Zugewiesene Tasks, 15 Min |
| `claude_assigned_nolimit.bat` | Zugewiesene Tasks, unbegrenzt |
| `claude_full_access.bat` | Volle Rechte (--dangerously-skip-permissions) |
| `claude_remote_control.bat` | Remote Control Session |
| `claude_maintenance.bat` | Wartung (recurring, backup, docs) |
| `claude_loop_15min.bat` | Endlos alle 15 Min |
| `claude_loop_30min.bat` | Endlos alle 30 Min |
| `claude_loop_1h.bat` | Endlos jede Stunde |

## Ablauf einer Auto-Session

```
1. SKILL.md laden (System-Kontext)
2. bach --startup ausfuehren
3. Tasks aus 'bach task list' laden
4. Tasks bearbeiten (P1 zuerst)
5. Session-Zusammenfassung speichern (bach --memory session)
6. System herunterfahren (bach --shutdown)
```
