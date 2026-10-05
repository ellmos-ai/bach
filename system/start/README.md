# BACH Claude Bridge – manueller Start/Stop

Dieser Ordner enthält pfadfeste Start-/Stop-Skripte für die Claude Bridge
(Fackelträger-System, #1583). Die Skripte funktionieren unabhängig vom
aktuellen Arbeitsverzeichnis – sie ermitteln den Repo-Pfad selbst
(`SCRIPT_DIR`) und rufen intern `bach.py claude-bridge ...` auf.

## Bridge manuell starten

```bash
./start/bridge.sh
```

oder von überall:

```bash
/Users/lukas/services/bach/system/start/bridge.sh
```

Die Bridge ist **auch ohne hinterlegte Connectoren startbar**
(Konzept #1583: manueller Start ohne Connectoren). Gesteuert wird das über
`hub/_services/claude_bridge/config.json`:

- `bridge.start_without_connectors: true` – Start ohne aktiven Connector erlaubt
- `bridge.autostart: true` – Bridge wird beim BACH-Systemstart automatisch
  mitgestartet (sofern ein Connector konfiguriert ist)

## Bridge stoppen

```bash
./start/stop.sh
```

## Weitere Befehle

Alle Bridge-Operationen laufen über den CLI-Handler:

```bash
python3 bach.py claude-bridge --help
```

Wichtige Operationen: `start`, `stop`, `status`, `mode`, `logs`, `workers`,
`setup`, `challenge`, `verify`.

## Hintergrund

- Die 24h-Bridge ist das Herz des Fackelträger-Systems (#1583): ein
  langlebiger Daemon (`hub/_services/claude_bridge/bridge_daemon.py`),
  der die Claude-Session über Tages- und Kontextgrenzen hinweg hält.
- Fackelübergabe (Kontextweitergabe an die nächste Instanz): `fackel.py`
  im selben Ordner; Übergabedokumente/Konzept siehe `TESTPLAN_1583.md`
  und `DEPLOYMENT.md` dort.
- Autostart-Verhalten: siehe #1590 (Auswertung von `bridge.autostart`
  in der Boot-Sequenz von `bach.py`).
