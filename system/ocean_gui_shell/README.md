# OCEAN GUI Shell — erste Extraktion

session: 01a0f189-21d6-7851-a075-0aab0e3ebe77 | codex-gui-program@ASUS-GEI | 2026-09-30

Dieses unabhängige Python-Paket enthält die aus BACH herausgelöste
Aktivitätsfläche mit Slots, Hintergrundworkern und System-/Rollenprompts.
HTML, CSS und JavaScript liegen gemeinsam in genau einer Template-Ressource.
Es importiert ausschließlich die Standardbibliothek und hält keine Backenddaten.
Dies ist die erste Paketgrenze der Vollschale; weitere Boards und Chat/Settings
sind noch nicht extrahiert.

```python
from ocean_gui_shell import render_activity_dashboard
html = render_activity_dashboard({"brand_name": "OCEAN"}, api_base="/control-api/api")
```

Das Paket lässt sich unabhängig aus diesem Verzeichnis bauen/installieren.
Der BACH-Quellbetrieb findet es neben `gui` auf dem vorhandenen `system`-Pfad.
`gui.activity_dashboard` ist ausschließlich der BACH-Branding-Consumer.
Die Lite-GUI benötigt dieses Paket nur bei einem ausdrücklich aufgerufenen
`create_control_shell_app()` oder `mount_control_shell()`; ihre bisherige
`create_app()`-Factory bleibt unabhängig.

## Backend-Vertrag

`api_base` bezeichnet die bestehende Control-API und nicht die GUI-REST-API.
Eine Basis mit abschließendem `/api` wird unverändert verwendet, ansonsten
ergänzt der Client `/api`. BACHs bisherige leere Basis bleibt same-origin.
Die gemeinsame Oberfläche liest `/slots`, `/activity`, `/models`, `/prompts`
und `/chat/history`; Schreibaktionen verwenden die bereits vorhandenen
`/slots`, `/fackel`, `/prompts`, `/prompts/reset` und `/workers*`-Routen.
Slot-IDs und `service=bach-chat-control` bleiben Protokollbezeichner und werden
durch Branding nicht umbenannt. Es gibt keinen direkten DB-/CLI-Zugriff.

Der neutrale Standard ist **nur lesen**. `read_only=False` ermöglicht die
ausdrückliche Prüfung eines vom Nutzer eingegebenen Tokens. Erst ein erfolgreicher
GET `/auth/check` mit `authenticated=true` und dem passenden Service aktiviert
Schaltflächen. Vor jedem Befehl wird dieser nebenwirkungsfreie Nachweis erneut
eingeholt; anschließend autorisiert das Backend den Befehl selbst erneut.
Der Nachweis beglaubigt den Token, nicht jeden Worker-/Zuweisungsbefehl.
Die bestehenden Befehls-, Claim-, Domain- und Origin-Gates bleiben im Backend.

Browseraufrufe folgen keinen Redirects. Fremde Browser-Ursprünge müssen von der
bestehenden Backend-Origin-/CORS-Policy zugelassen sein; weder Paket noch Consumer
öffnen diese Policy. Tokens werden nicht serverseitig hinterlegt. Das bestehende
Browser-Caching verwendet einen konfigurierbaren Storage-Key.
HTTP-/Schemafehler und Ausfälle werden als Fehler angezeigt; fehlende oder
ungültige Auth-Nachweise sperren den Schreibpfad. Offline-Transport sperrt zuvor
freigegebene Schaltflächen. Ein fehlendes Backend im Lite-Consumer verwendet
keine zufällig auf dem Host vorhandene `/api`-Route.

Brandingtexte werden für HTML maskiert, Clientkonfiguration wird als für
Script-Kontexte maskiertes JSON eingesetzt. Navigation erlaubt nur lokale
Pfade oder explizite HTTP(S)-URLs. Theme-Variablen und Farben werden validiert.
Worker-IDs für Inline-Handler müssen dem Bezeichnervertrag entsprechen;
dynamische Metadaten werden maskiert.
