# Modell-Fallbacks

## Vertrag

Die Profile der nativen Systemsteckplätze und dynamischen Worker können über ihren bestehenden versionsgebundenen CAS-Endpunkt eine geordnete Liste `model_fallbacks` speichern. Jedes Element enthält ausschließlich `backend` und `model`; der Worker-Konfigurationsadapter projiziert die Liste erneut mit demselben strikten Validator. Vor dem Schreiben prüft der CAS zusätzlich die zusammengeführte Konfiguration: das Primärziel darf nicht erneut in der Kette stehen, und ein `openrouter/free`-Primärmodell darf keine kostenpflichtige externe Alternative erhalten. Die vorhandene Konfigurationsgröße und die API-Körpergrenzen gelten weiter; dieser Vertrag fügt keine zusätzliche Kettenlängenregel ein. Der Runtimepfad liest die Liste nur über den vorhandenen nativen Profilreader. Prompt-, Task-, Persona- und Anfragefelder erteilen keine Fallbackberechtigung.

Ein Ziel wird über denselben konfigurierten Backendresolver erzeugt wie der normale Chat. Der Resolver darf nur bereits geladene BACH-Runtimecodepfade verwenden; er startet weder Connector noch Dienst. Nicht unterstützte oder nicht eindeutig passende Ziele enden sichtbar und geschlossen.

## Ressourcenbindung

`ollama` und `lmstudio` sind lokale Ziele, wenn der tatsächliche Endpoint lokal ist. Ein tatsächlich ausgewähltes lokales Fallback muss die bestehende Modellsteckplatzbindung, Fackel-/Ressourcenprüfung und `HostInferenceGate` bestehen. Nach einer Steckplatzmigration kann eine lokale Fallbackbindung aus dem aktuellen nativen Profil abgeleitet werden, wenn genau dieses Ziel aufgerufen wird; dabei wird kein Steckplatz dauerhaft ergänzt und keine gesamte Kette vorab reserviert. Eine vorhandene deaktivierte oder widersprüchliche Binding bleibt gesperrt.

`ollama-cloud` mit einem expliziten Modellnamen mit `:cloud` ist extern, auch wenn BACH es über einen lokalen Ollama-Proxy erreicht. OpenRouter, Hermes, OpenAI und Claude API sind externe Ziele und benötigen keinen lokalen Modellsteckplatz. CLI-Backends `claude` und `codex` sind für Fallbacks nicht freigegeben, weil deren eigene Werkzeugausführung einen separaten Vertrag braucht.

Ein `openrouter/free`-Primärziel darf nicht still auf einen kostenpflichtigen externen Anbieter wechseln. Eine explizit konfigurierte lokale Alternative oder ein weiteres ausgewiesenes Free-Ziel bleibt möglich.

## Fehlerschranke und Werkzeugwirkung

Die nächste Stufe wird nur nach einem typisierten Vorabfehler ohne Antworttext, Thinking-Inhalt oder Werkzeugaufruf versucht: sichere Verbindungsfehler, vom Provider strukturierte und normalisierte HTTP-Überlast-/Dienststatus oder die vorhandenen lokalen Ressourcenstatus `budget_exceeds_host` und `reserve_wait_expired`. Ein nackter `HTTPStatusError`-Statuscode allein reicht nicht, weil er Rate-Limit und Kontingent nicht unterscheidet. Ein self-managed CLI-Backend darf nach einer Ausnahme oder Fehlantwort nicht automatisch fortgesetzt werden: sein Chat-Boundary kann Werkzeuge bereits ausgeführt haben, und ein typischer No-Tool-Beleg ist derzeit nicht vorhanden. Quotenfehler, unbekannte Providerfehler, Lesetimeouts, Teilantworten und Werkzeugaufrufe starten keinen weiteren Anbieter. Jeder Versuch verwendet den aktuellen Nachrichtenverlauf; kein Werkzeugaufruf wird wiederholt.

Tasks mit `required_model` bleiben an dieses Modell gebunden und wechseln nicht auf eine andere Modellversion. Ein erfolgreiches Fallback ändert keine Taskzuweisung, Fähigkeiten oder Werkzeugrechte.

## Abnahmegrenze

Die fokussierten Tests prüfen CAS/Validierung, den echten Backendresolver mit bereits geladenem Factory-Zugriff und echten Backendklassen, Provider-/Modell-/Endpoint-Identität, Projektion lokaler und externer Ziele, Bindungsableitung aus dem echten Legacy-Projektionsformat für ein ausgewähltes lokales Fallback, den normalen Toolloop sowie Teilantwort-, Quoten-, self-managed-CLI- und Taskbindungsgrenzen. Sie rufen keine echten Modellanbieter auf. Damit ist weder ein konkreter Modelllauf noch eine Kapazitätsmessung, ein Fackel-Livezustand oder ein Produktivdeploy nachgewiesen.


## OpenRouter-Free-Katalog

Der Katalogdienst hält Modell- und Preisnachweise höchstens 300 Sekunden im Prozesscache. Ein nicht aus dem Cache bedienter Katalogabruf kann höchstens zwei HTTP-GETs ausführen. Jeder GET verwendet die bestehende HTTPX-Timeoutgrenze von sechs Sekunden. Das ist eine Phasengrenze pro Request und keine garantierte Gesamtzeit für DNS, Verbindungsaufbau, Lesen und beide Versuche zusammen.

Nur HTTPX-Timeouts, Netzwerkfehler und die festen temporären HTTP-Statuscodes 408, 425, 429, 500, 502, 503 und 504 dürfen einen zweiten Katalogabruf auslösen. 401/403, andere HTTP-Fehler und ungültige Katalogantworten werden nicht wiederholt. Die öffentliche Projektion verwendet feste `failure_code`-Werte wie `catalog_timeout`, `catalog_transport_error`, `catalog_http_transient`, `catalog_auth_rejected`, `catalog_http_error` und `catalog_invalid_schema`; ein `status_code` erscheint nur für die erlaubte Statusliste. Providertexte, Antwortkörper, URLs, Header und Zugangsdaten werden nicht übernommen.

Der Router `openrouter/free` bleibt ein unveränderter Anbieter-Selektor. Eine einzelne Modell-ID wird nur zugelassen, wenn sie auf `:free` endet, die Preisfelder `prompt` und `completion` vorliegen und alle veröffentlichten Preisfelder endliche numerische Nullen enthalten. Ein fehlender Katalogeintrag bedeutet nur „nicht aufgeführt“; er beweist keinen Preis. Ein vorhandener Eintrag mit fehlenden oder ungültigen Preisfeldern wird getrennt von einem tatsächlich beobachteten Nichtnullpreis abgelehnt. Mehrdeutige Doppeleinträge bleiben ebenfalls gesperrt.

Nach einem fehlgeschlagenen Refresh werden zuvor gecachte individuelle IDs nicht weiter zugelassen. Die öffentliche Katalogliste enthält dann nur den Router und eine feste Fehlerklasse. Ein erfolgreicher Wiederholungsabruf kann die nachfolgende normale Anfrage einmal freigeben; der Katalogdienst wiederholt weder Inferenz noch Werkzeugaufrufe.
