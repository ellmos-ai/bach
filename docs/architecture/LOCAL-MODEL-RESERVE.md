# Lokale Modellreserve

## Stand und Zuständigkeit

Task #1981 ergänzt das vorhandene HostInferenceGate um eine optionale
Reservensperre am nächsten Modellaufruf. Die Source implementiert weder einen
zweiten Scheduler noch einen Modellrouter. Installation, aktivierte Konfiguration
und tatsächliche große Modellinferenz sind gesondert nachzuweisen.

Ein wartender Modellaufruf hält keine Inferenzfackel. Sein Task-/Chatkontext bleibt
im bestehenden Lauf; bereits ausgeführte Tools werden nicht erneut ausgeführt.
Nach Ablauf des begrenzten Wartens wird der Aufruf als Fehler zurückgegeben.
Unbekannte ältere Fehlerzustände werden dadurch nicht automatisch neu gestartet.
Manuelles Aus/Pause, Konfigurationsänderungen und Leaseverlust bleiben die
vorhandenen Abbruchgates. Ein ausgefallener Schreibaufruf wird nicht wiederholt.

## Explizite Konfiguration

Die private Datei liegt unter dem tatsächlichen `BACH_RUNTIME_DIR`, sonst unter
`~/.bach/runtime`, in `local-inference/resource-reserve.json`. Ohne Datei gilt das
vorherige Verhalten; `not_configured` ist kein Nachweis gesicherter Reserve.
Eine vorhandene ungültige Datei blockiert. Es gibt keine implizite Migration oder
Schreibwirkung beim Lesen. Die Datei wird nach regulärer Sourceintegration anhand
der nativen Modell-/Hostmessung vorbereitet, mit Locks und bestehenden Rechten.

Vertrag `bach.local-resource-reserve.v1`, ausschließlich folgende Felder:

| Feld | Bedeutung |
|---|---|
| `enabled` | ausdrückliche Aktivierung der Reservensperre |
| `memory_reserve_bytes` | freie zusätzliche OS-/BACH-Reserve, mindestens 512 MiB |
| `disk_reserve_bytes` | Reserve auf den tatsächlichen TaskDB-/Slot-/Runtime-Dateisystemen |
| `wait_seconds` | gesamtes begrenztes Warten, 1–3600 Sekunden |
| `poll_seconds` | Ressourcenabfrageintervall, 1–60 Sekunden |
| `models` | Budgets je exakt angebotenem Ollama-Modellnamen |

Ein Modellbudget enthält genau `digest`, `weight_budget_bytes`,
`kv_headroom_bytes`, `overhead_bytes`, `num_ctx`. Digest und Gewichtsuntergrenze
kommen aus der nativen `/api/tags`-Antwort, die Lokalität aus `/api/show`.
Die Gewichtsuntergrenze ist keine gesamte RAM-Messung. KV-/Overheadwerte sind
explizite konservative Budgets; sie dürfen nicht als gemessene Nutzung ausgegeben
werden. Kontext muss zum tatsächlich gesendeten `num_ctx` passen. Keine
automatische Kontextverkleinerung, Modellladung/-entladung oder bezahlte Umleitung.

Eine verifizierte `/api/ps`-Residenz mit exakt gleichem Digest und ausreichendem
`context_length` verhindert eine zweite Gewichtsreservierung. KV-/Overheadreserve
wird weiterhin konservativ verlangt. Fehlende Kontextmetadaten erlauben keinen
Residenzkredit. Präfixgleichheit unterschiedlicher Modell-Tags reicht nicht.

HTTP-Leseantworten und Wartedauer sind begrenzt. Fehlende/beschädigte Messungen
werden als unbekannt behandelt. Ein unmögliches oder widersprüchliches Budget
wartet nicht unbegrenzt. Ausdrückliche `:cloud`-Ziele sowie nativ bestätigte
`remote_host`-/`remote_model`-Ziele erhalten keine lokale Inferenzfackel. Ein
aktiviertes Policyprofil für einen derzeit nicht unterstützten lokalen Provider
bleibt blockiert; dieses Paket implementiert Ollama, keinen geratenen LM-Studio-
Speichervertrag.

## Empirie und weitere Abnahme

Die Messung auf Mac Studio am 10.10.2026 um 05:14 UTC ergab 32 GiB physischen RAM,
etwa 14,4 GiB verfügbaren RAM und weniger als 1 GiB freien Plattenplatz. Das ist
eine Momentaufnahme und keine Abnahme des 27B-Modells. Die drei aktuellen eigenen
Prüfkandidaten belegten zusammen ungefähr 196 MiB; größere fremde Forschungs- und
Entwicklungsbestände wurden nicht verändert.

Das große Hauptmodell bleibt das gewünschte Ziel. 4B ist kein abschließend
akzeptierter Ersatz. #1994 führt die gesonderte Eigentums-/Speicherentscheidung;
#2011/#1949 führen Modellsteckplätze, Slotparallelität, KV-/Residenzbudgets und
Vordergrund-Pull mit Hintergrundrückgabe. Dieser Reservencheck belegt nicht deren
vollständige Integration. Residenzkredit ist keine prozentuale Fackelaufteilung.

Bestehender `compute_turn_status` enthält beim Warten `resource_waiters` mit
Prüfzeit, Zustandsenum, Policyversion und Budget-/Messwerten; `active` bleibt
ausschließlich der tatsächliche HostInferenceGate-Besitz. Keine Prompts,
Credentials, Taskresultate oder privaten Pfade in dieser Projektion.

Vor Betrieb: regulärer Merge, gültiges natives Policyprofil, native Lesemessung,
isolierte Low-Disk-/Low-RAM-/Timeout-/Abbruch-/Wiederaufnahmeprüfungen, danach
ausdrücklich gestartete tatsächliche Aufgabe mit Tool-/Ergebnis-/Leasebeleg.
Rückweg: laufenden Versuch an sicherer Grenze beenden, Policy ausdrücklich
deaktivieren oder den vorherigen integrierten Stand einsetzen. Das alte Verhalten
ohne Reservensperre wird dadurch nicht zu einer Kapazitätsfreigabe.
