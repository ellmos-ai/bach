# Testplan Fackelträger-Bridge Bereinigung (Task #1583)

## Ziel
Sicherstellen, dass die Fackel-Wrapper-Zwischenschicht vollständig entfernt wurde und `bridge_tray.py` sowie `setup_wizard.py` direkt mit `bridge_daemon.py` arbeiten.

## Durchgeführte Prüfungen

| # | Prüfung | Methode | Erwartet | Ergebnis |
|---|---------|---------|----------|----------|
| 1 | Keine Wrapper-Referenzen im Bridge-Ordner | `search_text` nach `use_fackel_wrapper`, `fackel_wrapper`, `WRAPPER_SCRIPT`, `wrapper_script` in `hub/_services/claude_bridge` | keine Treffer | ✅ keine Treffer |
| 2 | `config.json` ist gültiges JSON | `python3 -c "import json; json.load(open('config.json'))"` | keine Fehler | ✅ OK |
| 3 | Python-Syntax aller beteiligten Module | `python3 -m py_compile bridge_tray.py setup_wizard.py bridge_daemon.py fackel.py` | keine Fehler | ✅ OK |
| 4 | `bridge_tray.py` startet Daemon direkt | Code-Review: `DAEMON_SCRIPT = BRIDGE_DIR / "bridge_daemon.py"` (Zeile 60) und `subprocess.Popen([sys.executable, str(DAEMON_SCRIPT)], ...)` (Zeile 676) | direkter Start | ✅ OK |
| 5 | `bridge_tray.py` stoppt Daemon direkt | Code-Review: `subprocess.run([sys.executable, str(DAEMON_SCRIPT), "--stop"], ...)` (Zeile 701) | direkter Stopp | ✅ OK |
| 6 | `setup_wizard.py` erzeugt keine Wrapper-Config | Code-Review der Default-Config (Zeilen 130–141) | kein `use_fackel_wrapper` Schlüssel | ✅ OK |
| 7 | `config.json` enthält keinen Wrapper-Schlüssel | Inhalt von `config.json` geprüft | kein `use_fackel_wrapper` | ✅ OK |

## Zusammenfassung

Alle Prüfungen bestanden. Die Fackel-Wrapper-Bereinigung ist vollständig und konsistent:
- `bridge_tray.py` startet und stoppt `bridge_daemon.py` direkt.
- `setup_wizard.py` generiert eine saubere Default-Config ohne `use_fackel_wrapper`.
- `config.json` enthält keinen veralteten Wrapper-Schlüssel.
- Syntax- und JSON-Validierung erfolgreich.

## Sign-off

- Durchgeführt: manueller Code-Review und Validierung
- Status: **BESTANDEN**
- Task: #1583.4 (Testplan) und #1583.5 (Dokumentation/Changelog) abgeschlossen
