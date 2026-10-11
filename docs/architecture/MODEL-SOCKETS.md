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
Native Aktivierung, Katalogübernahme aller angebotenen Modelle und die
vollständige Haupt-/Fallbacksteuerung müssen folgen. Der gemeinsame
Steckplatzeditor ist als Source veröffentlicht; sein nativer Anschluss bleibt
ein eigener Installations- und Laufzeitnachweis.
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

Legacy-Reads projizieren die aktuell konfigurierten lokalen Primärmodelle,
die konfigurierten Telegram-/WhatsApp-/Signal-Ziele und deren Agentenbindungen
im Speicher. Ziele desselben Agenten und Modells werden dedupliziert.
Connector-Overrides ändern nur Anbieter, Modell und Rundenbudget; Agenten-ID,
Aktivierung und Werkzeugrechte bleiben beim Profil. Sie schreiben nichts und kennzeichnen
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
Der native Telegram-Eingang und seine bestätigte Compute-Fortsetzung binden
vor dem Modellaufruf das bestehende Connector-Profil, auch bei wiederhergestellten
Dialogen und negativen Gruppen-IDs. Native Control-/API-Dialoge erhalten am
bisherigen Dispatchpfad die interaktive Profilidentität; gewähltes Backend,
Modell und Gesprächskontext bleiben erhalten. Profilchats und dynamische Worker
behalten ihre vorhandenen separaten Bindungsverträge. Der standalone Legacyworker
übernimmt die Always-On-Identität ausschließlich in seinem expliziten Kontext.

Connectorziele verwenden dieselbe validierte Anbieterprojektion in Migration
und Dispatch. Nur numerische Telegram-IDs, bekannte Kanalaliasse und explizite
Kanalpräfixe mit nicht leerer Kanal-ID sind zugeordnet. Unbekannte
Connectorpräfixe werden abgelehnt. Änderungen am effektiven Profil oder
Connectorziel während eines Wartens verhindern den alten Backendaufruf.
Der eigenständige ChatRuntime rät keine Zuordnung aus solchen Präfixen.

Eine gewählte dedizierte Route fällt bei einem Zulassungsfehler nicht auf das
globale Backend zurück. Telegram prüft vor einer Compute-Pause denselben
Runtime-Vertrag `prepare_inference_call` wie der spätere Modellaufruf. Die
Metadatenprobe verändert keine Modelle und nimmt keinen Host-Besitz. Bekannte
RAM-/Datenträgerwartefälle benötigen bereits eine aktive Modellbindung;
unbekannte Ziel- oder Ressourcenbeobachtungen erlauben noch keine Compute-Pause.
Ein anhand der Metadaten bestätigtes externes Ziel benötigt keine lokale
Bindung, pausiert keine lokalen Compute-Jobs und setzt kein Inferenzsignal.
Auch das native Compute-Gate prüft diesen tatsächlichen Zieltyp erneut.
Probe, Profil und Modellbindung werden nach Warteschritten erneut geprüft;
eine frühe Zulassung ersetzt keine Ressourcenfreigabe für die Inferenz.

Diese Source-Verträge sind keine Prüfung externer Connectorprozesse und kein
Nachweis einer großen lokalen Inferenz. Deshalb erst alle betroffenen
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

## Modellkatalog und CLI

`GET /api/system/model-sockets/catalog` liest Metadaten des konfigurierten
nativen Ollama-Anbieters. Chat, lokale Backend-Presets und Katalog teilen die
Anbieterkonfiguration; explizite Einstellungen und Umgebungsvariablen gehen
den bisherigen Standardwerten vor. Der Katalog initialisiert weder den
Telegram-Controller noch Sessions oder Datenbanken. Er führt nur
`GET /api/tags` und `POST /api/show` aus, ohne Pull, Modellstart oder Inferenz.
Nur Loopback-Adressen aus der nativen Konfiguration sind zulässig, keine
Adresse aus dem GUI-Aufruf. Weiterleitungen und Umgebungsproxies sind aus.
Metadatenbudget: zehn Sekunden, maximal 64 Einträge und 2 MB pro Antwort.

Lokale Herkunft und Fähigkeiten werden anhand der Metadaten geprüft.
Cloud-Suffixe und remote_host/remote_model sind ausgeschlossen; fehlende
Nachweise bleiben unbekannt. Embeddingmodelle stehen im Katalog, aber
`chat_eligible=false` kennzeichnet sie zum Ausschluss aus normalen Chatangeboten.
Artefaktgröße ist kein RAM-Gewicht. Modellresidenz und Fackelanteile bleiben
unbekannt; Katalogpräsenz startet oder registriert nichts. Die eigenständige
LM-Studio-Capabilityprojektion ist noch offen und wird ausdrücklich als
`capability_adapter_pending` gemeldet.

Die native CLI verwendet denselben Store mit CAS und Schreibsperren:

```text
bach model-sockets list --json
bach model-sockets catalog --json
bach model-sockets migrate --version <configuration_version>
bach model-sockets configure --version <configuration_version> --backend ollama --model <name>
bach model-sockets bind --version <configuration_version> --agent <agent_id> --socket <socket_id>
bach model-sockets unbind --version <configuration_version> --binding <binding_id>
```

Jeder Schreibaufruf benötigt die Version aus dem letzten Read. Bindungen
können enabled, priority und context_tokens konfigurieren; Steckplätze
enabled, max_active_slots und residency_policy. ACK bestätigt nur die
Konfigurationsspeicherung. Eine konfigurierte Wunschidentität ist keine
bestätigte Modellverfügbarkeit; die tatsächliche Inferenzprüfung bleibt
verbindlich. CLI und Katalog gehören auf den nativen Enginehost. Ein
weitergeleiteter Loopback-Port ist kein zusätzlicher physischer Modellhost.
GUI-Katalogauswahl, sämtliche Callerbindungen und native Migration müssen
vor Aktivierung weiter abgenommen werden.

## Rückweg

Die bisherige Konfiguration bleibt vor Aktivierung unverändert. Eine operative
Migration braucht einen gesicherten nativen Vorzustand und einen abgenommenen
Callerpfad. Bindung entfernen löscht weder Agent, Session noch Aufgabe.
Rücknahme einer Migration erfordert die versionierte Wiederherstellung des
gesicherten Konfigurationsdokuments und eines dazu kompatiblen Quellstands an
einer sicheren Laufgrenze. Der neue native Caller akzeptiert eine schemafreie
Datei auch mit alter Formatversion nicht. Kein
stilles Entfernen des Schemas bei einem Parser- oder Laufzeitfehler.
