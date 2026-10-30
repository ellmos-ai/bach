# Watchdog: racefreier Modell-Unload (Inference)

Status: In Umsetzung (Task #2419; Grundlage Subtask #2960)

[PLANABGLEICH-20261024C-BAUORT] Finaler Bauort ist `modul:ocean-resources`.
Das Modul existiert im Repo (Stand 2026-10-24) noch nicht (kein `ocean.py`,
keine OCEAN/MODUL-ZUORDNUNG). Bis dahin bleiben Wächter und Gate an den
unten genannten Orten — dokumentierter Zwischenstand, keine endgültige
Anbindung.
Bauort: `system/tools/maintenance/memory_pressure_unload_guard.py`
Adapter: `system/hub/_services/chat/host_inference_gate.py` (nur Adapter, keine Fachlogik)
Gate-Status-Vertrag: Statuswechsel über lokalen Call, abgesichert per
`_exclusive_lock` (Dateilock) genau in diesem Call; Tickets sind
prozessgebunden (Release durch den besitzenden Prozess).

## 1. Zweck und Abgrenzung

Der Wächter entlädt ein Ollama-Modell aus dem Host-Speicher, sobald der
Inference-Gate seinen exklusiven Slot freigibt, und **bestätigt** den Unload,
bevor der nächste Turn Speicher erwartet. Er ist bewusst **kein** Memory-Broker
und **keine** Policy-Engine:

- **Fachlogik** (wann ist Speicher knapp, welches Modell zuerst, welche
  Priorität) liegt ausserhalb. Der Wächter kennt nur: Modellname rein,
  Quittung raus.
- **Keine Kenntnis** von BACH-Tasks, Chat-Sessions, Agenten oder Prioritäten.
- **stdlib-only**: `urllib.request`, `json`, `argparse`, `time`. Keine
  Fremdabhängigkeiten, kein `requests`, kein `psutil`.
- Wird der Dienst nicht erreicht, wirft der Wächter nicht in den Aufrufer;
  der Adapter protokolliert eine Warnung und arbeitet weiter.

## 2. Sensor / Aktor

Der Wächter ist strikt in Sensor- und Aktorflächen getrennt. Beide sprechen
ausschliesslich die lokale Ollama-HTTP-API.

### Sensoren (lesend, jederzeit idempotent)

| Funktion | Wirkung |
|---|---|
| `list_running()` | `GET /api/ps` → Liste der aktuell im Speicher gehaltenen Modelle (Rohobjekte). |
| `loaded_entries(model)` | Filtert `list_running()` auf Einträge, die `model` entsprechen (Name **oder** Digest). |
| `is_unloaded(model)` | `True`, wenn kein Eintrag mehr passt. Einziger belastbarer Unload-Beweis. |
| `wait_until_unloaded(model, ...)` | Poll auf `is_unloaded()` bis Erfolg oder `timeout`. |

Die Zuordnung ist bewusst konservativ: Ein Namens-Treffer gilt auch dann als
Treffer, wenn der erwartete Digest abweicht. `is_unloaded()` meldet damit nie
vorschnell «entladen», solange noch ein Modell unter demselben Namen läuft.

Sensoren sind ohne Nebenwirkung: Sie lösen keinen Ladevorgang aus und
verändern den Ollama-Zustand nicht.

### Aktor (schreibend, genau eine Wirkung)

| Funktion | Wirkung |
|---|---|
| `unload(model)` | `POST /api/generate` mit `{"model": model, "keep_alive": 0}`; danach Sensor-Verifikation. |

`unload()` liefert einen Report und **keine Exception** bei blossem
Nicht-Erreichen des Ziels:

```
{
  "model":       str,        # angefragter Modellname
  "digest":      str | None, # normalisierter Digest des Zielmodells, falls bekannt
  "done_reason": str | None, # aus der Ollama-Antwort (erwartet "unload")
  "unloaded":    bool,       # Ergebnis der Sensor-Verifikation, nicht der ACK
  "elapsed_s":   float,      # Dauer bis Verifikation oder Timeout
  "warning":     str | None  # Klartextgrund, falls unloaded False
}
```

Fehlerklassen: `OllamaUnavailable` (Dienst/Verbindung) und
`OllamaResponseError` (HTTP-Status ungleich 200, kaputtes JSON). Beide werden
nur bei **harten** Transportfehlern geworfen, nicht beim Verfehlen des
Unload-Ziels — dort bleibt es bei `unloaded: false` plus `warning`.

## 3. API und Konstanten

```python
__version__                 = "1.0.0"
DEFAULT_BASE_URL            = "http://127.0.0.1:11434"
DEFAULT_REQUEST_TIMEOUT_S   = 10.0
DEFAULT_POLL_S              = 0.25
DEFAULT_UNLOAD_TIMEOUT_S    = 30.0
```

Intern, aber testbar: `_base_url()` (ENV-Override `OLLAMA_HOST`/Basis-URL,
sauberes Trimmen von Schema und Port), `_normalize_digest()` (Kürzt und
vereinheitlicht `sha256:`-Präfixe, damit `ps`-Digest und Modell-Digest
vergleichbar sind), `_request()` (ein HTTP-Aufruf mit Timeout und
JSON-Dekodierung), `_matches()` (Namens- und Digest-Vergleich).

Modellnamen werden **exakt** verglichen, zusätzlich tag-tolerant: `foo` passt
auf `foo:latest`. Ein `foo:7b` passt nicht auf `foo:13b` — bewusst, um fremde
Modelle nicht zu entladen.

## 4. CLI

`python -m tools.maintenance.memory_pressure_unload_guard` (bzw. direkt
ausgeführt) mit drei Unterbefehlen:

```bash
# Sensoren: was hält aktuell Speicher?
... ps [--base-url URL] [--model NAME] [--json]

# Aktor + Verifikation: entladen und warten
... unload --model NAME [--base-url URL] [--timeout S] [--poll S]

# Nur warten (kein Schreibzugriff)
... wait --model NAME [--base-url URL] [--timeout S] [--poll S]
```

Exit-Codes: `0` Ziel erreicht bzw. Liste erfolgreich gelesen; `1` Ziel nicht
erreicht (Timeout, `unloaded: false`); `2` Dienst nicht erreichbar oder
fehlerhafte Antwort. `ps` und `wait` sind damit gefahrlos in Monitoring und
Diagnose einsetzbar, `unload` ist der einzige schreibende Aufruf.

## 5. Warum Polling? (`done_reason=unload` ist ein Vorab-ACK)

Ollama (beobachtet mit 0.33.3) beantwortet `POST /api/generate` mit
`keep_alive: 0` und meldet in der Antwort `done_reason: "unload"`. Diese
Quittung wird **vor** der tatsächlichen Freigabe des Speichers gesendet: Der
Server hat die Anweisung angenommen, das Modell kann aber für kurze Zeit
weiterhin in `GET /api/ps` auftauchen. Der ACK allein ist deshalb **kein**
Beweis für freien Speicher.

Konsequenz für den Wächter: `unload()` behandelt die HTTP-Antwort nur als
„Auftrag angenommen" und entscheidet erst über `is_unloaded()` — also durch
wiederholtes Lesen von `/api/ps` im Abstand `poll` (Standard 0.25 s) bis
`timeout` (Standard 30 s). Nur ein leeres Sensor-Ergebnis setzt
`unloaded: true`.

Damit ist die Zusage „racefrei" konkret: Der Adapter gibt den Slot erst frei
bzw. meldet Erfolg erst, wenn der Sensor ihn bestätigt hat. Ein Wettlauf
zwischen „Unload quittiert" und „nächster Turn reserviert Speicher" ist
ausgeschlossen, weil der zweite Schritt auf dem Sensor-Resultat aufsetzt und
nicht auf dem ACK.

Das Poll-Intervall ist ein bewusster Kompromiss: 0.25 s ist kurz genug, um
die typische Unload-Latenz im Sub-Sekunden-Bereich ohne spürbare
Verzögerung abzubilden, und lang genug, um `/api/ps` nicht zu fluten (maximal
vier Abfragen pro Sekunde, rein lokal über Loopback).

## 6. Einbindung im Inference-Gate (Adapter)

`host_inference_gate.py` enthält **keine** Unload-Fachlogik. Es gibt genau
drei Berührungspunkte:

1. `_load_unload_guard()` — Import des Wächter-Moduls. Regulärer Import über
   `tools.maintenance.memory_pressure_unload_guard`, Fallback über
   `importlib.util.spec_from_file_location` relativ zu `parents[3]`, damit das
   Gate auch ohne installiertes `system`-Paket auf `PYTHONPATH` funktioniert;
   `sys.modules.setdefault` verhindert Doppelladungen.
2. `_release_model_locked(model)` — ruft `guard.unload(model)`, prüft
   `report["unloaded"]` und protokolliert andernfalls `_LOG.warning`. Die
   Funktion **wirft nie**, damit ein Unload-Problem keinen Chat-Turn
   verliert.
3. `turn(..., release_model: bool = False)` — nach dem Schreiben von
   `owner.json` und **vor** dem `yield`, ausgeführt via
   `asyncio.to_thread(...)` innerhalb des gehaltenen
   `_exclusive_lock(self.root / "inference")`.

Der Unload läuft also im gehaltenen Gate-Lock und blockiert damit bewusst den
nächsten Reservierungsversuch, bis der Sensor bestätigt hat. `release_model`
ist standardmässig `False`: Ohne Opt-in bleibt das Modell geladen
(Warmstart), das Verhalten ändert sich für bestehende Aufrufer nicht.

## 7. Betriebsgrenzen und offene Punkte

- **Live-Pfad gesperrt**: Die Alt-Logik
  `~/compute/abc_hct/compute_queue/memory_pressure_watchdog.sh` wird in
  diesem Task ausschliesslich dokumentiert, nicht verändert (Subtask #2962);
  die verbindliche Stilllegungsanleitung steht in Abschnitt 8.
- **Konfiguration** `~/.memwatchdog/config.json` mit
  `free_emergency_pages` ist nicht Teil des Wächter-Moduls; der empfohlene
  Umgang ist ein eigener Schritt (#2963) und steht in Abschnitt 9.
- Der Wächter kennt nur **ein** Modell pro Aufruf. Mehrere Modelle müssen vom
  Aufrufer sequenziert werden.
- Es gibt keine Persistenz: Kein Log, keine Metriken, kein Zustand über den
  Prozess hinaus. Beobachtbarkeit entsteht über den Report und den
  CLI-Exit-Code.
- Der Testnachweis für das Modul (`system/tests/test_memory_pressure_unload_guard.py`)
  deckt Import, API-Symbole, Defaults und die Digest-/Namenszuordnung ab.
- Die Gate-Hunks in `system/hub/_services/chat/host_inference_gate.py`
  (`release_model_now` und der Adapter `_release_model_locked`) sind in
  `system/tests/test_host_inference_gate.py` durch drei Tests abgedeckt:
  Erfolgspfad unter dem exklusiven Lock inklusive Lock-Freigabe, ungueltiges
  `model_target` ohne Exception (`ok=False`, gesetzter `error`) sowie die
  Rueckgabe `False` bei fehlendem, werfendem oder nicht bestaetigendem Waechter.
  Ein bestaetigter Gesamtlauf der Suite bleibt dem regulaeren CI-Lauf des Pull
  Requests vorbehalten.

## 8. Stilllegung der Alt-Logik (#2962)

Diese Anleitung beschreibt, wie die alte, pollende Unload-Logik
`~/compute/abc_hct/compute_queue/memory_pressure_watchdog.sh` ausser Betrieb
genommen wird, nachdem der Sensor/Aktor-Wächter übernommen hat.

**Status in diesem Task: nicht ausgeführt.** Alle Pfade unter `~/compute` und
`~/Library/LaunchAgents` liegen ausserhalb des Worktrees und sind im gebundenen
Lauf gesperrt. Die Schritte sind als Reihenfolge für einen berechtigten Lauf
dokumentiert; sie sind kein Bestandteil des ausgelieferten Codes.

### 8.1 Vorprüfung

1. Wächter-Modul erreichbar prüfen:

   ```
   python3 system/tools/maintenance/memory_pressure_unload_guard.py ps
   ```

   Erwartung: JSON-Liste der aktuell geladenen Modelle, Exit-Code `0`.
2. Über den BACH-Adapter derselbe Sensor:

   ```
   bach --ollama ps
   ```

   Erwartung: identische Modellliste. Weicht das Ergebnis ab, ist der Adapter
   (`system/hub/ollama.py`, `_ps()`) nicht auf dem Stand des Wächter-Moduls.
3. Aktor gegen ein Testmodell prüfen (nur wenn ein entbehrliches Modell geladen
   ist):

   ```
   bach --ollama unload <MODELLNAME>
   ```

   Erwartung: Report mit `"unloaded": true`; ein unmittelbar folgendes `ps`
   enthält das Modell nicht mehr.

Erst wenn alle drei Schritte erfolgreich sind, wird die Alt-Logik deaktiviert.

### 8.2 Deaktivieren der Alt-Logik

1. **LaunchAgent prüfen**: Unter `~/Library/LaunchAgents` nach einem Label
   suchen, das auf `memory_pressure_watchdog` verweist, z. B.

   ```
   grep -l memory_pressure_watchdog ~/Library/LaunchAgents/*.plist
   ```

2. **LaunchAgent deaktivieren** (Label aus Schritt 1 einsetzen):

   ```
   launchctl bootout gui/$(id -u)/<LABEL>
   launchctl disable gui/$(id -u)/<LABEL>
   ```

   Die `.plist` bleibt zunächst liegen; sie wird erst in 8.3 verschoben.
3. **Cron-Eintrag entfernen**: `crontab -l` auf Zeilen mit
   `memory_pressure_watchdog` prüfen und diese über `crontab -e` löschen.
   `crontab -l` erneut ausführen und belegen, dass kein Treffer mehr vorhanden
   ist.
4. **Bestätigen, dass kein Prozess mehr läuft**:

   ```
   pgrep -fl memory_pressure_watchdog
   ```

   Erwartung: keine Ausgabe.

### 8.3 Archivieren

1. Verzeichnis anlegen, falls nicht vorhanden:
   `~/compute/abc_hct/compute_queue/archive/`
2. Skript verschieben (nicht löschen, damit die Historie nachvollziehbar
   bleibt):
   `mv ~/compute/abc_hct/compute_queue/memory_pressure_watchdog.sh ~/compute/abc_hct/compute_queue/archive/`
3. Sofern vorhanden, zugehörige Logdateien und `.plist` in dasselbe Archiv
   verschieben.
4. Im Archiv eine kurze `README.md` ablegen mit Datum, Grund („ersetzt durch
   `system/tools/maintenance/memory_pressure_unload_guard.py`", Verweis auf
   dieses Dokument) und dem letzten bekannten Commit der Alt-Logik.

### 8.4 Verifikation nach der Stilllegung

1. `bach --ollama ps` liefert weiterhin die Modellliste — der Adapter hängt
   nicht an der Alt-Logik.
2. Ein vollständiger Chat-Turn mit gesetztem `release_model=True` entlädt das
   Modell; `ps` bestätigt es anschliessend.
3. Über einen Beobachtungszeitraum (mindestens ein Arbeitstag) prüfen, dass
   kein Speicherdruck-Ereignis ohne Reaktion bleibt. Findet sich ein solches
   Ereignis, wird der Wächter aus 8.1 wiederholt geprüft, bevor die Alt-Logik
   reaktiviert wird.
4. Rückweg: `launchctl enable`/`bootstrap` mit der archivierten `.plist` und
   Zurückverschieben des Skripts. Die Deaktivierung ist damit umkehrbar.

## 9. Speicher-Konfiguration (#2963)

Die Alt-Logik wurde über `~/.memwatchdog/config.json` gesteuert; der
maßgebliche Wert ist `free_emergency_pages` (Schwellwert in 4-KiB-Seiten, ab
dem ein Notfall-Unload ausgelöst wurde). Der neue Wächter liest diese Datei
**nicht**: Er kennt nur Modell-Identität und Unload-Zustand, keine
Speichermetriken. Die Datei bleibt damit ausschliesslich Sache der Alt-Logik
und wird mit deren Stilllegung (Abschnitt 8) obsolet.

Empfohlener Umgang:

- **Wert dokumentieren, nicht übernehmen**: `free_emergency_pages` vor der
  Stilllegung auslesen und im Archiv-`README.md` (8.3) notieren, damit der
  historische Schwellwert nachvollziehbar bleibt.
- **Kein Import in das Wächter-Modul**: Eine Speicherdruck-Erkennung im Modul
  würde die Sensor/Aktor-Trennung verwässern. Wer weiterhin druckabhängig
  entladen will, ruft `unload()` aus einem eigenen, separaten Auslöser auf.
- **`~/.memwatchdog/config.json` nicht löschen**, solange die Alt-Logik nur
  deaktiviert und nicht endgültig entfernt ist (Rückweg aus 8.4).
- **Status in diesem Task**: Die Live-Konfiguration ist gesperrt und wurde
  nicht gelesen oder verändert. Dieser Abschnitt ist reine Dokumentation.
