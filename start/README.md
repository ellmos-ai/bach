# BACH Startmenü und Startspine

## Einstiegspunkte

- `bach.bat`: Windows-Bootmenü per Doppelklick.
- `bach.sh`: macOS/Linux mit `start|chat|gui|status|stop`.
- `startspine.py`: gemeinsame Prozess-, Port- und Readiness-Steuerung.

Die Shell-Dateien sind dünne Adapter. Alle Dienststarts und Stopps laufen über
die pfadunabhängige Startspine.

## Sicherheits- und Betriebsvertrag

Die Startspine:

- beendet niemals einen Prozess nur aufgrund eines Ports oder Namens;
- ordnet eigene Prozesse über PID und Erstellungszeit zu;
- stoppt ausschließlich diese registrierten Prozesse;
- verwendet bei einem fremd belegten Wunschport automatisch den nächsten
  freien Port und veröffentlicht den tatsächlich verwendeten Port;
- meldet Erfolg für erforderliche Dienste erst nach Readiness und
  Port-Ownership-Readback;
- startet den Tray auch bei fehlender Chat/Control API. Der rote Tray versucht
  die Verbindung danach alle fünf Sekunden erneut;
- deaktiviert im Offline-Tray alle Aktionen, die ein nicht erreichbares
  Backend oder Frontend benötigen;
- zeigt Chat/Control und lokales Ollama getrennt an. Ollama ist optional und
  standardmäßig offline zulässig;
- verhindert konkurrierende Start-/Stop-Operationen mit einer kurzlebigen
  Startspine-Lease;
- erfasst Supervisor-PID, Kind-PID, Host, Wunschport, tatsächlichen Port,
  Readiness und Exit-Code in Runtime-Belegen.

Chat/Control gilt erst als bereit, wenn der gestartete Prozess den Port besitzt,
sich als BACH Chat Control ausweist und der Telegram-Bot gegenüber Telegram
verifiziert wurde. Die Startspine verlangt anschließend eine stabile
Readiness-Phase.

Die Runtime-Dateien sind keine fachliche Datenbank. Sie liegen standardmäßig
unter `%LOCALAPPDATA%\BACH\runtime` (Windows) oder
`$XDG_STATE_HOME/bach/runtime` beziehungsweise
`~/.local/state/bach/runtime` (macOS/Linux):

- `startspine.json`: registrierte eigene Prozesse;
- `discovery.json`: aktueller Discovery-/Readiness-Readback;
- `receipts/*.json`: Supervisor- und Exit-Code-Belege;
- `logs/*.log`: Dienstlogs.

Für isolierte Tests kann `BACH_RUNTIME_DIR` gesetzt werden.

## Ports

| Dienst | Wunschport | Konfiguration | Verhalten bei Fremdbelegung |
|---|---:|---|---|
| GUI | 8000 | `BACH_GUI_PORT` oder `--gui-port` | freier Folgeport |
| Chat/Control | 8081 | `BACH_CONTROL_PORT` oder `--control-port` | freier Folgeport |
| Ollama | 11434 | Ollama-Konfiguration | optional/offline |

Konsumenten erhalten den aufgelösten Port über `discovery.json`. Der lokal
gestartete Tray bekommt GUI- und Control-Port direkt von der Startspine.

## Befehle

```text
python start/startspine.py start                    # GUI + Tray
python start/startspine.py start --chat --tray      # Chat/Control + Tray
python start/startspine.py start --gui --tray       # expliziter Default
python start/startspine.py status
python start/startspine.py status --json
python start/startspine.py stop --services chat,tray
python start/startspine.py stop --services all
python start/startspine.py autostart-install       # Windows
python start/startspine.py autostart-remove        # Windows
```

Ein Remote-Tray wird ohne lokalen Backend-Start erzeugt:

```text
python start/startspine.py start --tray --host macstudvonlukas
```

Wenn der Remote-Server andere Ports veröffentlicht, müssen sie über
`--gui-port` und `--control-port` mitgegeben werden.

## Windows-Hauptmenü

```text
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
  [G]  Web-GUI starten
  [S]  Status anzeigen
  [X]  Chat Service stoppen
```

## Task-Empfänger

| Assignee | Kann ausführen? | Mechanismus |
|---|---|---|
| `user` | Ja, manuell | Benutzer erledigt Tasks selbst |
| `OLLAMA` | Ja, automatisch | Idle Worker im System Tray |
| `BUDDHA` | Ja, automatisch | Idle Worker als Fallback |
| `bach` | Nein, nur Tracking | kein Ausführungsmechanismus |
| `claude` / `CLAUDE` | Teilweise | nur bei aktiver Claude-Session |
| `gemini` / `GEMINI` | Nein, nur Tracking | kein Task-Executor |
| `persönlicher-assistent` | Nein, nur Tracking | Agent ohne autonome Ausführung |

## Rollback

Die Migration ändert keine fachliche Source of Truth. Ein Code-Rollback erfolgt
über den zugehörigen Git-Commit. Vor dem Wechsel auf einen älteren Launcher
müssen die aktuell registrierten Prozesse mit
`startspine.py stop --services all` beendet werden. Runtime-Belege dürfen
erst danach archiviert werden.

## Legacy-Dateien

Dateien unter `start/_archive/` sind nicht aktive Einstiegspunkte. Sie dürfen
nicht für den produktiven Start verwendet werden.
