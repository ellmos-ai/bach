# Gemeinsame lokale Modellretention

Stand: 2026-11-17. Umsetzung: BACH #4214.

## Verhalten

Ein Worker mit leerer oder derzeit unpassender Aufgabenqueue besitzt das lokale
Modell nicht exklusiv. Er darf es deshalb weder entladen noch durch wiederholte
Leerabfragen künstlich geladen halten. Dasselbe gilt für eine Abkühlpause eines
einzelnen Workers. Chat, Connector und weitere Worker können dieselben
Modellgewichte verwenden.

Die bestehende Ollama-Request-Policy bleibt die Autorität für gewöhnliche
Leerlauffreigabe: `hub.compute_lock.get_effective_keep_alive()` liefert fünf
Minuten bei erkannten laufenden oder vom Bot pausierten Compute-Jobs und
ansonsten dreißig Minuten. `OllamaBackend.chat()` sendet diesen endlichen Wert
bei jedem tatsächlichen Request, einschließlich eines leeren Warmup-Requests.
Weitere Modellnutzung aktualisiert die native Retention; Worker-Queue-Polls und
Cooldown-Polls senden dafür keinen Request.

Diese Zeiten beschreiben die angeforderte native Retention nach Modellnutzung,
keine physische RAM-Reservierung und keine zugesicherte Entladezeit. Andere
Modellaufrufer und gesonderte Speicherdruckmechanismen bleiben eigenständige
Einflüsse. Ein Queue-Wartezustand oder ein abgelaufener Cooldown ist kein
Nachweis, dass ein Modell tatsächlich entladen wurde.

## Änderung

`telegram_chat._observe_idle_model_retention()` protokolliert einmal pro
verifiziertem Leerlauf den bestehenden Retentionvertrag. Die Beobachtung führt
keinen Provideraufruf aus. Ungeprüfte Queuezustände und externe Modelle erzeugen
diese Beobachtung nicht.

`telegram_chat._wait_run_cooldown()` behält die Zulassungsentscheidung aus
`ocean-resources`: Mindestpause, Swap- und Temperaturprüfung sowie sichtbaren
Wartegrund. Die frühere direkte Entladung nach `unload_after_seconds` entfällt
für diesen gemeinsam genutzten Modellpfad. Der Status behauptet keine
unbestätigte Entladung. Die Abkühlpause endet weiterhin nur nach Zulassung oder
beim Stoppen des Workers.

Eine spätere vorzeitige Freigabe muss mit dem bestehenden Host-Inferenzlock
atomar koordiniert werden und den tatsächlichen Abschluss bestätigen. Ein
vorgeschalteter Statuscheck allein schließt das Rennen mit einem neuen Chat
nicht aus.

## Grenze des derzeitigen Always-On-Warmups

Der bestehende Coldstartvertrag lädt vor dem ersten Task-Claim. Er verweigert
gebundene Tasks und `require_task_binding`; der leere Modellrequest darf keine
Task-Ausführung oder deren Privilegien übernehmen. Dieser Vertrag wird hier
nicht geändert.

Folgearbeit für bedarfsgesteuertes Warmup ist entweder ein nativer
Kandidaten-Preflight ohne Claim-Autorität oder ein ausdrücklich geleaster
Warmup-Lifecycle. Letzterer benötigt begrenzte Lade-/Leasebudgets, Verlängerung
beziehungsweise Rückgabe bei Stop, Timeout oder Bindungswechsel und eine klare
Trennung zwischen Coldstartzulassung und eigentlicher Task-Ausführung. Ein
bloßes Verschieben des vorhandenen Warmup-Aufrufs hinter die Taskakquisition
würde dessen `task_bound`-Schutz auslösen.

## Verifikation

- `system/tests/test_pb26_idle_unload.py`: echte Worker-Leerqueue und
  Queue-Abfluss ohne Unload, wiederholte Polls ohne Retention-Refresh,
  aktiver Vordergrundturn sowie endliche 5-/30-Minuten-Requestwerte für
  Chat und leeren Warmup.
- `system/tests/test_pb26_run_cooldown.py`: Stresswartezeit und Fortsetzung
  bleiben wirksam, auch lange Abkühlpausen lösen keinen gemeinsamen Unload
  aus und melden keine ungeprüfte Entladung.
- Bestehende Warmup-Grenzen bleiben in
  `test_local_resource_reserve.py` und `test_worker_start_admission.py`
  ausdrücklich geprüft.

Die Verifikation verwendet isolierte Testdaten und HTTP-Mocks; keine realen
Modellstarts, Entladungen oder Prozesspausen sind dafür erforderlich.
