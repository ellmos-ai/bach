# Requestgebundener HTTP-Abbruch (#4212)

## Vertrag

Die GUI erzeugt nach authentisierter Geräteanmeldung eine private, einmalig verwendbare
Control-Bindung. Sie umfasst Dienstinstanz, Gerätekennung, Chatkennung, den nativ
aufgelösten Steckplatzstand und zwei zufällige Request-/Cancel-Werte. Der Browser
erhält diese Werte nicht und darf keine eigene `_http_request`-Bindung einspeisen.

`POST /api/chat/request` ist nur am bestehenden authentisierten internen Control-Port
verfügbar. `inspect` liefert die Protokollversion und Dienstinstanz; `prepare` erzeugt
die Bindung. `cancel` und `status` benötigen die vollständige unveränderte Bindung.
Die Route gehört nicht zur öffentlichen GUI-Proxy-Allowlist. Unicode wird kontrolliert
verglichen; ungültige oder fremde Bindungen liefern HTTP 409.

Ein markiertes `POST /api/chat` verbraucht die Bindung einmalig. Der Steckplatz wird
vor dem Dispatch erneut geprüft. Alte Dienstinstanzen, wiederholter Versand und
geänderte Steckplätze können damit keine neue Modelloperation beginnen.
Abbruchrechte für eine bereits laufende eigene Anfrage bleiben auch nach einer
Steckplatzänderung verwendbar.

Nach vollständig gelesenem Body besitzt genau eine Coroutine das ASGI-Receive.
Nur das bestätigte `http.disconnect` löst den privaten Cancel-RPC aus. Ein TCP-EOF,
`SHUT_WR` oder das bloße Schließen der GUI-Verbindung zum Control-Port sind keine
Abbruchautorität. Direkte, unmarkierte Control-Clients behalten ihren bisherigen Vertrag.

## Wirkung und Nachweis

| Phase | Verhalten |
| --- | --- |
| Vor dem Control-Dispatch | Die private Bindung wird beendet; ein verspäteter POST wird abgewiesen. |
| Eigener Warteplatz vor Promptannahme | Der eigene Waiter endet, ohne eine Benutzernachricht anzunehmen oder einen fremden Turn zu verändern. |
| Control-Vorbereitung | Der eigene GUI-Transport endet; ein Modell-POST wird nicht mehr gestartet. |
| Ollama-Anfrage | Das eigene asyncio-Stoppsignal unterbricht Header-, Stream-, Fehlerbody- und instrumentierte Liveness-Warte. Nur die eigenen Response-/Client-Kontexte werden geschlossen. |
| Eigener Warmup | Das vorhandene native Stoppsignal und dessen Bereinigungsverfahren bleiben zuständig. Ein negativer oder fehlender Cleanup-Beleg wird nicht zu Erfolg aufgewertet. |
| Laufendes synchrones Werkzeug | Der aktuelle Aufruf wird nicht gewaltsam unterbrochen. Vor dem nächsten Werkzeug oder Modellaufruf wird erneut geprüft. |
| Andere Backendarten | Es gibt keine erfundene Interruptfähigkeit. Der tatsächliche Aufruf muss enden; bis dahin bleibt die Bereinigung unbestätigt. |

Der Cancel-RPC hat ein Gesamtbudget von zwei Sekunden für die Antwort. Dieses Budget
ist **keine** Zusage, dass Modelltransport, native Ressourcenfreigabe oder eine synchrone
Operation physisch beendet sind. `cleanup_complete=true` setzt einen terminalen
Requestzustand, das Ende des eigenen Runtime-Aufrufs und den passenden Transport-
bzw. nativen Warmup-Beleg voraus.

Geht der Cancel-RPC verloren, wird er abgelehnt oder läuft sein Zeitbudget ab, bleibt
`cleanup_complete=false`: **cleanup unconfirmed / unknown**. Die neue HTTP-Schicht
gibt deshalb keine nativen Besitzer vorzeitig frei. Es gibt keinen zusätzlichen
Foreground-Heartbeat, globalen Modell-Stop, Prozess-Kill oder gemeinsamen Client-Close.

## Persistenz und Talk

Bei einer angenommenen Anfrage werden Benutzertext und erhaltene Teilantwort über
den vorhandenen `SQLiteChatSessionStore` genau einmal als fehlgeschlagener Abschluss
mit `reason_code=http_disconnect` geschrieben. Die Normalisierung erlaubt dieses
Metadatum ausschließlich bei fehlgeschlagenen Assistant-Nachrichten. Fehlt der Store
oder scheitert die Speicherung, wird keine bestätigte Persistenz gemeldet.

Abbruch und regulärer Abschluss werden an derselben privaten Bindung um die dauerhafte
Antwortablage serialisiert. Ein verspäteter Cancel kann einen abgeschlossenen Turn
nicht umschreiben und keinen neueren Turn desselben Chats stoppen.

Talk verwendet weiterhin seinen geräte- und steckplatzgebundenen Chatkontext. Der
bestehende synchron arbeitende Talk-Thread ruft die private async HTTP-Operation über
die GUI-Eventloop auf. Der Handler beobachtet das wirkliche Threadende; er behandelt
die Cancellation eines `to_thread`-Awaiters nicht als Thread- oder Providerende.
Nach bestätigtem Disconnect wird kein später Erfolg oder veralteter visueller Zustand
veröffentlicht. Die externe Talk-Domänenlogik wird nicht verändert.

Aktive und noch abbrechende Bindungen werden nie zugunsten neuer Bindungen verdrängt.
Die Registry ist auf 1024 Einträge begrenzt; vorbereitete und terminale Einträge haben
eine Aufbewahrungszeit von 15 Minuten. Nach einem Dienstneustart gelten alte Bindungen
nicht mehr. Sie verleihen keine TaskLease-, Worker- oder Ressourcenautorität.

## Prüfung und Rollout

Die neuen Regressionen liegen direkt in den bereits von CI ausgewählten Dateien
`system/tests/test_model_backend.py` und `system/tests/test_gui_server.py`.
Die GUI-Suite prüft echte Loopback-Verbindungen zwischen Browser-Socket, Uvicorn,
authentisiertem Control, ChatRuntime, privater SQLite-Datenbank und einem gestallten
Ollama-Testserver. Für Talk bildet diese portable CI-Fixture ausschließlich den externen
Talk-Domänenaufruf nach; sie verwendet den echten BACH-Responder und echten Thread.
Die benachbarte lokale Talk-Kontinuitätssuite prüft zusätzlich das installierte Talk-Modul.

Weitere gezielte Gates decken bestehende Warmup-, Sessionstore-, Worker-Backendfehler-
und Trace-Verträge ab. Es werden keine Produktivmodelle, Produktivdatenbanken oder
Produktivdienste als Testfixture verwendet.

Diese Änderung ist eine Source-Implementierung. Eine erfolgreiche Test- oder CI-Prüfung
ist keine Produktionsaktivierung. Der Gesamtrollout benötigt weiterhin den vollständigen
nativen Start-/Lock-Gate und den konkreten Abgleich alter Worker-Generationen und
Trace-Checkpoints. `ChatRuntime._process_turn` und `_tool_loop_impl` ändern bewusst den
bestehenden Runtime-Trace-Fingerprint; alte Checkpoints werden nicht still umgeschrieben.
Der separate physische LOAD_PENDING-Vertrag und dessen deaktivierte Capability bleiben
unverändert.
