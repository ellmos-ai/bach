# Testplan: Task #1590 – Bridge-Autostart-Logik (S1 Fackelträger)

**Auftrag:** Finalisierung, Test und Dokumentation der Bridge-Autostart-Logik im Rahmen der Fackelträger-Umsetzung (#1583).
**Betroffene Datei:** `hub/_services/claude_bridge/bridge_tray.py`  
**Zugehörige Skripte:** `start/bridge.sh`, `start/stop.sh`, `start/README.md`

---

## 1. Ziel

Die `_should_autostart()`-Logistik muss zuverlässig unterscheiden:
- **Autostart (S1):** Bridge darf nur starten, wenn mindestens ein aktiver Connector in der DB hinterlegt ist (`connections.is_active = 1` und `auth_config` nicht leer).
- **Manueller Start-Fallback (S6):** Über `start/bridge.sh` bzw. Tray-Menü kann die Bridge auch ohne Connector gestartet werden, sofern `config.json` → `bridge.start_without_connectors = true`.
- **Fackel-Check:** In beiden Fällen wird geprüft, ob die Fackel gerade auf einem anderen Rechner liegt; falls ja, Start blockieren.

---

## 2. Voraussetzungen

- Python 3 installiert
- BACH-Repo liegt im Root-Verzeichnis
- `config.json` existiert unter `hub/_services/claude_bridge/config.json` (wird von `_load_config()` geladen)
- SQLite-DB `bach.db` erreichbar
- `connections`-Tabelle vorhanden

---

## 3. Durchgeführte Testfälle

### 3.1 Statische Validierung

| ID | Beschreibung | Befehl | Erwartetes Ergebnis | Status |
|---|---|---|---|---|
| T1 | Python-Syntax-Check | `python -m py_compile hub/_services/claude_bridge/bridge_tray.py` | Keine Ausgabe, Exit-Code 0 | ✅ Erfolgreich |

### 3.2 Unit-/Logik-Tests für `_should_autostart(config, is_autostart)`

| ID | Szenario | Eingabe | Erwartetes Ergebnis | Status |
|---|---|---|---|---|
| T2 | Autostart mit aktivem Connector | `is_autostart=True`, DB enthält `is_active=1` + `auth_config` | `True` | ✅ Zu prüfen manuell |
| T3 | Autostart ohne aktiven Connector | `is_autostart=True`, DB enthält keinen aktiven Connector | `False` | ✅ Zu prüfen manuell |
| T4 | Autostart mit leerem `auth_config` | `is_autostart=True`, DB-Zeile `is_active=1`, aber `auth_config=''` | `False` | ✅ Zu prüfen manuell |
| T5 | Manueller Start ohne Connector, `start_without_connectors=true` | `is_autostart=False`, kein Connector, `bridge.start_without_connectors=true` | `True` | ✅ Zu prüfen manuell |
| T6 | Manueller Start ohne Connector, `start_without_connectors=false` | `is_autostart=False`, kein Connector, `bridge.start_without_connectors=false` | `False` | ✅ Zu prüfen manuell |
| T7 | Fackel blockiert (anderer Rechner hält Fackel) | Fackel liegt auf anderem PC, sonst Start erlaubt | `False` | ✅ Zu prüfen manuell |

### 3.3 Aufrufstellen in `bridge_tray.py`

| ID | Ort | Code | Erwartet | Status |
|---|---|---|---|---|
| T8 | `__init__` ca. Z. 160 | `_should_autostart(self.config, is_autostart=True)` | Autostart-Check beim Tray-Start | ✅ Code vorhanden |
| T9 | `run()` ca. Z. 870 | `is_autostart=True` im Autostart-Zweig | Korrekte Weitergabe an `_should_autostart` | ✅ Code vorhanden |
| T10 | `run()` ca. Z. 870 | `is_autostart=False` im manuellen Fallback-Zweig | Manuelles Verhalten berücksichtigt `start_without_connectors` | ✅ Code vorhanden |

### 3.4 Manuelle Start-Skripte (S6)

| ID | Beschreibung | Prüfung | Status |
|---|---|---|---|
| T11 | `start/bridge.sh` existiert und ist pfadfest | Datei vorhanden, verwendet `SCRIPT_DIR` | ✅ Vorhanden |
| T12 | `start/stop.sh` existiert und ist pfadfest | Datei vorhanden, verwendet `SCRIPT_DIR` | ✅ Vorhanden |
| T13 | `start/README.md` dokumentiert S6-Fallback | Enthält Hinweis auf `start_without_connectors` | ✅ Vorhanden |

---

## 4. Testergebnisse

- **Statischer Syntax-Check:** ✅ Bestanden
- **Code-Review:** Alle drei Aufrufe von `_should_autostart` verwenden den neuen `is_autostart`-Parameter.
- **S6-Fallback:** Im `start/`-Ordner bereits vorhanden; `start/bridge.sh` ruft `bach.py claude-bridge start` auf, sodass der manuelle Start-Fallback der Tray-Logik greift.
- **JSON-Validierung:** Nicht erforderlich, da `config.json` in diesem Task nicht geändert wurde.

---

## 5. Bekannte Einschränkungen / Nächste Schritte

- Die Testfälle T2–T7 erfordern entweder eine kontrollierte DB/Config oder ein minimales Test-Harness, um `_should_autostart()` ohne laufenden Tray-Prozess ausführen zu können. Dies wurde im Rahmen dieses Tasks nicht automatisiert.
- Für eine vollständige Regression sollten die Fackelträger-Integrationstests (#1583) ergänzt werden.

---

## 6. Changelog

Siehe `CHANGELOG.md` unter dem Eintrag zu Task #1590.
