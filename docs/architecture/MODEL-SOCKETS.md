# Lokale Modellsteckplätze und Agentenslots

## Vertrag und Stand

Ein **Steckplatz** bezeichnet ein angebotenes lokales Modell auf einem bestimmten
Host. Ein **Slot** ist die Zuordnung einer stabilen Agenteninstanz zu diesem
Modell. Mehrere Agenten können demselben Modell zugeordnet sein. Konfigurierte
Zuordnungen sind keine gleichzeitig laufenden Inferenzen.

Der Quellvertrag `bach.model-sockets.v1` ergänzt `model_sockets` in der bestehenden
`slots_config.json`. Agentenprofile bleiben unter dem historischen Schlüssel
`slots`; ihre IDs, Aufgaben, Rollen, Prompts und bisherigen Caller bleiben
erhalten. Dynamische Worker bleiben in `dynamic_workers`. Es entsteht kein
zweiter Aufgaben-, Konfigurations- oder Inferenzcontroller.

Dieses Paket enthält Konfiguration, explizite Migration, native Bindungsprüfung
am lokalen Modellaufruf und den Modellzielnachweis im bestehenden Host-Gate.
Es ist noch keine Abnahme der vollständigen Anforderungen aus Task #2011:
Katalogübernahme aller angebotenen Modelle, gemeinsamer Steckplatzeditor,
Connector-Caller und die vollständige Haupt-/Fallbacksteuerung müssen folgen.
Task #2012/#1949 führt die Ressourcenhierarchie, Messung und Kapazitätsregeln fort;
#2027/#2028 ergänzen Fallbacks und die Running-/Leuchtpunktansicht. Die normative
Nutzeranforderung bleibt vollständig bestehen.

## Speicher und Versionsvertrag

Steckplatz-IDs werden aus Anbieter, exakt angebotenem Modellnamen und Host-ID
abgeleitet. Bindungs-IDs werden aus Agenten-ID und Steckplatz-ID abgeleitet.
Dieselbe Agenteninstanz kann an mehrere Modelle gebunden werden, etwa für ein
später tatsächlich benutztes lokales Fallback. Eine Bindung lädt kein Modell,
claimt keine Task und startet keinen Worker.

Alle Änderungen benutzen das vorhandene `_serialized_mutation`, dessen
prozessübergreifenden Dateilock, `check_write_locks` und dieselbe
`configuration_version` wie die Core-Agenten. Eine Änderung über die bisherigen
Agentenendpunkte macht einen älteren Steckplatz-Write ungültig und umgekehrt.
Unbekannte Felder des äußeren Konfigurationsdokuments bleiben erhalten.
Unbekannte beziehungsweise beschädigte Felder des neuen Steckplatzschemas
werden abgelehnt. Fehlende Werte erzeugen keine erfundenen Kapazitäten.

Legacy-Reads projizieren die aktuell konfigurierten lokalen Primärmodelle und
deren Agentenbindungen im Speicher. Sie schreiben nichts und kennzeichnen
`migration_required=true`. Erst die ausdrückliche, versionierte Migration legt
das Schema ab und hebt die äußere Version auf mindestens 4.
Ab Formatversion 4 ist die Registry verbindlich: Fehlt `model_sockets`, werden
Ansicht, erneute Migration und lokale Aufrufzulassung abgelehnt. Eine ungültige
Formatversion erlaubt ebenfalls keinen Legacy-Rückweg.

Externe Primärziele
und explizite `:cloud`-Modelle werden dabei ausgeschlossen. Ein nicht mit `:cloud`
bezeichneter Ollama-Alias ist damit noch kein empirisch nachgewiesenes lokales
Modell: Die Ressourcenprobe bestimmt weiterhin das tatsächliche Laufziel.

## Native APIs

| Methode | Pfad | Wirkung |
|---|---|---|
| GET | `/api/system/model-sockets` | Konfiguration beziehungsweise Legacy-Projektion lesen |
| POST | `/api/system/model-sockets/migrate` | Aktuelle lokale Primärzuordnungen ausdrücklich migrieren |
| PUT | `/api/system/model-sockets` | Lokales Modell anbieten oder Steckplatzeinstellungen ändern |
| PUT | `/api/system/model-sockets/bindings/{agent_id}/{socket_id}` | Bestehenden Agenten einem Modell zuordnen |
| DELETE | `/api/system/model-sockets/bindings/{binding_id}` | Bindung entfernen, Agentenprofil erhalten |

Writes benötigen den vorhandenen verifizierten Gerätetoken und eine aktuelle
`configuration_version`. Änderungen stehen in `changes`; der Steckplatz wird
über `backend` und `model` identifiziert. Die Host-ID wird vom ausführenden
nativen Host abgeleitet und ist keine frei überschreibbare Nutzereingabe.
Eine Bestätigung bestätigt ausschließlich die gespeicherte Konfiguration:
`worker_started=false`, `runtime_verified=false`.

Der Writer für die zusätzlichen Routerzeilen in `server.py` ist Task #2011 im
Hauptworker. Der Partner baut keinen zweiten Router oder parallelen Speicher.
Ein Ocean-Konsument muss denselben Vertrag über seinen tatsächlichen nativen
Adapter anbieten; dieser BACH-Endpunkt beweist keine Ocean-Anbindung.

## Lokaler Aufruf und tatsächliches Laufziel

Die Bindungsprüfung erfolgt nach der Feststellung des lokalen Laufziels und
wird während des Gate-Wartens sowie unter dem bestehenden Host-Besitz erneut
ausgeführt. Agent, Modell, Host, aktivierter Steckplatz und aktivierter Slot
müssen zusammenpassen. Nachträgliche Änderung oder Entzug verhindert den
Backendaufruf. Alias, Ziel und Bindung werden aus einem einzigen Dateiabbild
gelesen. Eine externe Inferenz hält keinen lokalen Modellsteckplatz.

Native BACH setzt `require_model_socket_config=true`: Ein fehlender nativer
Konfigurationsspeicher oder fehlendes Registry-Schema erlaubt keine ungebundene
lokale Inferenz, auch bei einer auf Version 1–3 zurückgesetzten Datei. Der separat
nutzbare `ChatRuntime` behält seinen bisherigen Betrieb ohne BACH-Registry.
Ein vorhandenes beschädigtes Dokument wird auch dort nicht als Legacy gelesen.

Bekannte persistierte Chat-Aliasse und explizite Agenten-IDs sind zulässig.
Unbekannte Connectorpräfixe werden nicht geraten. Deshalb erst alle betroffenen
Caller und Dialoge anbinden, dann die Migration im jeweiligen Konsumenten
aktivieren. Dieser Quellstand darf deshalb erst nach dieser Prüfung und der
ausdrücklichen Migration im nativen Control-Dienst aktiviert werden. Das reine
Bereitstellen dieser Dateien ist keine kompatible Aktivierung einer bisherigen
schemafreien v3-Konfiguration. In diesem Paket findet keine native Migration
oder Aktivierung statt.

`HostInferenceGate.owner.json` enthält während eines bestätigten gebundenen
lokalen Aufrufs zusätzlich `model_target`: Steckplatz-, Bindungs-, Agenten-ID,
Anbieter und Modell. PID und Prozessstart bleiben der Halternachweis. Nach
Freigabe verschwindet der aktive Zielnachweis. Das belegt Besitz am Gate, keine
gemessene RAM-Nutzung oder prozentuale Fackelverteilung.

## Kapazität und verbleibende Gates

Der vorhandene Host-Controller serialisiert weiterhin lokale Inferenz.
`host_inference_limit=1` und `effective_max_active_slots=1` beschreiben diese
Grenze. Ein konfigurierter höherer Wert aktiviert keine neue Parallelität.
`residency_policy` und Slot-`context_tokens` sind Konfigurationswünsche; sie
belegen noch keine durchgesetzte Residenz oder eingestellte KV-/Kontextgröße.
Diese Anschlussarbeit gehört zur vollständigen Kapazitätsabnahme.

Gewichtsbudget, KV-Reserve, Kontext und Speicherfreigabe werden weiterhin durch
den eigenen bestehenden Reservevertrag `LOCAL-MODEL-RESERVE.md` geprüft.
Steckplatzansichten kopieren diese Budgets nicht in eine zweite Autorität.
Residenz, Gewicht, Leuchtanteil und Slotaktivität bleiben in einem reinen
Konfigurationsread `unknown` beziehungsweise `null`; `capacity_verified=false`.
Das große Hauptmodell gilt dadurch weiterhin nicht als betriebsabgenommen.

## Rückweg

Die bisherige Konfiguration bleibt vor Aktivierung unverändert. Eine operative
Migration braucht einen gesicherten nativen Vorzustand und einen abgenommenen
Callerpfad. Bindung entfernen löscht weder Agent, Session noch Aufgabe.
Rücknahme einer Migration erfordert die versionierte Wiederherstellung des
gesicherten Konfigurationsdokuments und eines dazu kompatiblen Quellstands an
einer sicheren Laufgrenze. Der neue native Caller akzeptiert eine schemafreie
Datei auch mit alter Formatversion nicht. Kein
stilles Entfernen des Schemas bei einem Parser- oder Laufzeitfehler.
