# BACH Startmenü

## Launcher

**`bach.bat`** — Windows Boot-Menü. Doppelklick zum Starten.
**`bach.sh`** — macOS/Linux (`bach.sh chat|gui|status|stop`).

## Hauptmenü

```
  --- SCHNELLSTART --------------------------------
  [D]  Default Start (GUI + System Tray)

  --- KONSOLEN ------------------------------------
  [1]  Claude Code (lokal, volle Rechte)
  [2]  Claude Code (remote, volle Rechte)
  [3]  Codex Konsole
  [4]  Agent beauftragen

  --- DIENSTE -------------------------------------
  [B]  Chat Service (Telegram Bot + Tray)
  [W]  Buddha Connect (Server-Modus)
  [G]  Web-GUI starten (Port 8000)
  [S]  Status anzeigen
  [X]  Chat Service stoppen

  --- ERWEITERT -----------------------------------
  [E]  Erweiterte Optionen
```

### Bewertung der Modi

| Modus | Notwendig | Begründung |
|-------|-----------|------------|
| Default Start | Ja | Standard-Workflow: GUI + Tray |
| Claude Code lokal | Ja | Hauptentwicklungs-Modus |
| Claude Code remote | Ja | Mobile-Steuerung |
| Codex Konsole | Ja | Alternative zu Claude |
| Agent beauftragen | Ja | Direkte Agenten-Delegation |
| Chat Service | Ja | Telegram Bot + Control API |
| Server-Modus | Ja | Verbindung zum Mac Studio |
| Web-GUI | Ja | Dashboard standalone |
| Status/Stop | Ja | Betriebsübersicht |

## Erweitertes Menü

```
  [1]  Auto-Session (Zeitlimit + Scope waehlbar)
  [2]  Endlos-Loop (Intervall waehlbar)
  [M]  Maintenance (Recurring/Backup/Docs)
  [A]  Advanced Console (bach.py direkt)
  [C]  Autostart einrichten
  [R]  Autostart entfernen
```

Konsolidiert: Statt 9 separater Claude-Varianten (15/30/60 Min × alle/zugewiesene Tasks + 3 Loops)
jetzt 2 interaktive Optionen mit wählbarem Zeitlimit und Scope.

## Task-Empfänger: Wer kann Tasks ausführen?

| Assignee | Kann ausführen? | Mechanismus |
|----------|----------------|-------------|
| `user` (342 Tasks) | Ja — manuell | Benutzer erledigt Tasks selbst |
| `OLLAMA` | Ja — automatisch | Idle Worker im System Tray (bei Leerlauf) |
| `BUDDHA` | Ja — automatisch | Idle Worker (Fallback nach OLLAMA) |
| `bach` (102 Tasks) | Nein — nur Tracking | Kein Ausführungsmechanismus |
| `claude` / `CLAUDE` (25 Tasks) | Teilweise — via Auto-Session | Nur wenn Claude-Session aktiv |
| `gemini` / `GEMINI` (28 Tasks) | Nein — nur Tracking | Gemini hat keinen Task-Executor |
| `persoenlicher-assistent` (1 Task) | Nein — nur Tracking | Agent ohne autonome Ausführung |

**Empfehlung:** Für automatische Ausführung im Leerlauf: `OLLAMA` oder `BUDDHA` zuweisen.
Für manuelle Bearbeitung: `user`. Andere Assignees dienen nur der Organisation.

## Legacy-Dateien

Einzelne .bat-Dateien in `_archive/`. Werden nicht mehr direkt aufgerufen.
Referenzierte Hilfsskripte in `_internal/` (z.B. `claude_remote_control.py`).

## Server-Modus

Option `[W]` verbindet zum Mac Studio (oder anderem BACH-Server):
1. Prüft Control API (:8081)
2. Startet System Tray mit `--host`
3. Öffnet GUI Dashboard

Standard-Host: `macstudvonlukas` (Tailscale). Eigener: `SET BACH_HOST=mein-server`
