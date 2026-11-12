# Gemeinsame Agenten-Trigger-API

Stand: 04.11.2026. Nur Quelllieferung, keine produktive Installation.

## SOLL und IST

SOLL: Eine gemeinsame Triggerverwaltung für Agentenansicht, Routinen und Kalender
mit nativen Ausführungs-, Autoritäts- und Ergebnisbelegen.

IST: Dünne Projektion von `ellmos_scheduler.AgentTriggers`, ohne Legacy-
`scheduler_jobs` oder Life-Datenbank. Store: `BACH_EXTERNAL_SCHEDULER_DB`, sonst
`system/data/scheduler_external/state.db`. Initialisierung/Migration gehört zum
Deployment und erfolgt weder bei GET noch bei einem Schreibversuch. Alter oder
fehlender Provider, Rollback und fehlendes Schema ergeben HTTP 503.

`requirements.txt` pinnt den Scheduler auf den geprüften Merge-Commit
`29065fe5aade28cad457b4bf935309d1079c39e2` (Trigger, Kalender und nativer
Ausführungskontext). Eine isolierte Paketinstallation aus diesem Git-Commit
ist geprüft; das aktualisiert keine bestehende produktive Installation.

Alle Routen benötigen gültige Geräte- oder Browsersitzungsanmeldung; Origin-Gate
und explizite Middleware-Präfixgrenze bleiben erhalten. Credentialfelder und der
Anmeldetoken sind im Body verboten. Keine Providerstarts oder Executoraufrufe.

## JSON-Vertrag

Erfolg: `schema=bach.agent-triggers.v1`, `provider=ellmos-scheduler`,
`source=external_scheduler`, `state=available`.

- `GET /api/agent-triggers?agent_id=worker@host`: `triggers` mit Snapshots.
- `GET /api/agent-triggers/{id}`: `trigger`, einschließlich Tombstone.
- `POST /api/agent-triggers`: `id`, `expected_version:0`, `agent_id`, `schedule`,
  registrierte `executor`-ID; optional `payload`, `enabled` (false), `authorities`,
  `lease_seconds`, `timeout_seconds`.
- `PUT /api/agent-triggers/{id}`: `expected_version` und `changes` mit vollständigen
  Ersatzwerten einzelner nativer Konfigurationsfelder oder `enabled`.
- `DELETE /api/agent-triggers/{id}`: Body `expected_version`; ID bleibt Tombstone.
- `POST /api/agent-triggers/{id}/deliver`: explizite authentifizierte Aktion mit
  `expected_version`, `event_id`, `event_type`, `source`, optional `lineage`.
  Herkunft ist kein Vertrauensbeleg und keine bestätigte `task.accepted`-Ingestion.
  Kein Ereignisauslöseknopf in der GUI aus diesem Endpunkt ableiten.

IDs/Filter: höchstens 128 Zeichen, führend alphanumerisch, danach alphanumerisch
oder `_.:@/-` wie im nativen Scheduler. Slash-IDs werden als gesamter URL-Wert
mit `encodeURIComponent(id)` codiert. IDs werden niemals als Dateipfade verwendet.
Unbekannte Bodyfelder werden abgelehnt.
Snapshot: `id`, `version`, `revision`, `agent_id`, `schedule`, `executor`, `payload`,
`enabled`, `deleted`, `authorities`, `lease_seconds`, `timeout_seconds`.

Konfigurations-ACK: `configuration_saved:true`, `readback_verified:true`,
`worker_started:false`, erst nach unabhängigem `get` mit unveränderter Version.
Widersprüche ergeben keine Erfolgsmeldung und keinen automatischen Retry.
Lieferung: `delivery={job_id,duplicate,state:materialized}` plus unabhängig
zurückgelesene Definition und Materialisierungsbeleg. Der Definition-Versionswert
bleibt bei `deliver` unverändert. Deduplizierte Events können Jobs einer älteren
Revision behalten; deren Payload wird nicht als aktuelle Konfiguration ausgegeben.
Materialisierung ist kein Start, erfolgreicher Run oder Ergebnisabnahme.

Fehler: `detail={schema:bach.agent-triggers.error.v1,state,reason_code}`;
400 invalid, 404 not_found, 409 conflict, 503 unavailable. Auth verwendet das
bestehende Fehlerformat. Keine rohen Exceptiontexte oder lokalen Pfade ausgeben.

## Verifikation und offene Grenzen

Synthetische native Stores prüfen CRUD/CAS/Tombstones, Schemafehler ohne Mutation,
Readback-Rennen und Event-Deduplizierung. Auth/Origin/Präfix werden getrennt geprüft.
Die isoliert installierte Pin-Fassung bestand zunächst 110 Tests ohne Skip:
56 API-, zwei Provider-, 28 Windows-Wiring- und 24 Guardfälle. Der echte
Adapter-Tick läuft mit aktivem Testschutz; der frühere Windows-Guard-Blocker
ist durch den engen Testbootstrap behoben. Dessen geprüfter Gate-Hash,
Startinterpreter und native Prozessbesitzform werden vor der Ausführung geprüft;
die Kindprozess-Guards werden vor dem Lesen eines Auftragsframes installiert.
Das ist keine Betriebssystem-Sandbox. Die bestehende allgemeine Kindprozesslücke
bei POSIX `os.killpg` bleibt davon getrennt und wird hier nicht geschlossen.

Die nachfolgende Identitätsbindung besteht zusätzlich drei native HTTP-Fälle
mit echter synthetischer Geräteauthentifizierung (59 API-Tests insgesamt):
Trigger-ID vor und nach `deliver` sowie Agenten-ID jedes gefilterten Snapshots
müssen zur Anfrage passen. Ein widersprüchlicher Readback ergibt 503 ohne
positiven ACK; ein Fehler erst nach Materialisierung rollt den bereits erstellten
Job nicht zurück. Die CI verlangt außerdem die Guardtests ohne Skip, Fehler oder
Fehlschlag. Zwei weitere sichere Regressionen prüfen die frühe Interpreterbindung
auch bei nachträglich verändertem `sys.executable`, ohne einen fremden Interpreter
zu starten. Der aktuelle isolierte Windows-Lauf besteht 115 Tests ohne Skip:
59 API-, zwei Provider-, 28 Wiring- und 26 Guardfälle. Eine zusätzliche native
Linux-Gegenprobe bestätigt Startup-Guard, eigene Session/Prozessgruppe,
Frame-Blockaden sowie Timeout-Aufräumen eigener Nachkommen bei weiterlaufendem
Kontrollprozess. Diese synthetischen Belege sind keine produktive Laufzeitabnahme.

Provider-Deployment, gemeinsame GUI, tatsächliche Aufgabenausführung und Kalender
bleiben getrennte Liefer- und Abnahmeschritte. Kein Produktivstart durch diese API.
