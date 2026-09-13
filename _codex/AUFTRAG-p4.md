# Auftrag — Startseite (index.html) bereinigen, Punkt 4 (T-20260913-660268706)

Du arbeitest im Worktree `C:/_Local_DEV/wt/bach-660268706-p4` (Branch
`fix/T-20260913-660268706-p4-startseite-cleanup`, Basis `origin/main`,
aktuell `9497b4c`). Committe auf DIESEM Branch. **NICHT pushen.**

## Kontext (bereits geklärt, nicht neu recherchieren)

Der Nutzer nennt `system/gui/templates/index.html` (Route `/`, `<title>BACH
Dashboard`) „Dashboard/Startseite". Sie hat aktuell EINEN Tab-Umschalter mit
drei Reitern: **Startseite** (`id="tab-overview"`), **🔋 Tokens**
(`id="tab-tokens"`), **📂 Dateien** (`id="tab-files"`, mit drei weiteren
Unterreitern: Eingang/Scanner, Quarantäne, Verbindungen).

Nutzer-Vorgabe (Ticket-Originaltext, Punkt 4): „'Dateien' weicht ab vom
Übermenü 'Dateien' — hat sinnvolle zusätzliche Funktionen wie Verbindungen
anlegen. -> kein Bereich mehr im Dashboard sondern alle Dateifunktionen
unter dem Hauptmenü 'Dateien'. -> selbes für Token — Dashboard/Startseite
ist nur noch eine Seite ohne Untertabs -> Dashboard/Startseite mit
sinnvollen Übersichten ausstatten, zum Beispiel aktive Agenten. ->
Chatfenster auf Startseite war wahrscheinlich bisher nur Aufgabenqueue oder?
-> entfernen. -> Ausbaustufen gehört nicht auf Startseite eher unter
'System'."

## Fünf Teilaufgaben

### 1) Chatfeld ("AI Console") entfernen

In `system/gui/templates/index.html`, `id="tab-overview"`: entferne den
gesamten `<div class="bg-[#111420] border border-[#1e2236] rounded-xl p-4
mb-6 shadow-lg">`-Block direkt nach `<div x-show="activeTab === 'overview'"
...>` — das ist die Partner-Auswahl (Claude/Gemini/Ollama/Planner) +
Textarea `#headless-prompt` + Senden-Button + "Buddha Chat öffnen"-Link.
Grund (bereits per Funktionstest belegt,
`system/docs/FUNKTIONSTEST_1157_Startseite_Chatfeld.md`): die Antwort
erscheint nie im Feld selbst, es ist faktisch nur eine Aufgabenqueue.
**Nicht anfassen:** die dahinterliegenden JS-Funktionen
`sendHeadlessPrompt`/`selectPartner` in `system/gui/static/js/app.js` —
lass sie stehen (toter Code stört hier nicht, andere Seiten könnten sie
später nutzen; keine Umbenennungen/Löschungen dort).

### 2) Tab-Leiste + Tokens-Tab + Dateien-Tab entfernen, Verbindungen-Feature migrieren

Der `<div class="flex gap-2 border-b-2 ...">`-Tab-Leisten-Block (die drei
Buttons Startseite/Tokens/Dateien) entfällt komplett — es gibt nur noch
EINE Ansicht (den bisherigen Inhalt von `tab-overview`, ohne das
`x-show`-Attribut und ohne die `id="tab-overview"`-Hülle, einfach als
normalen Seiteninhalt). Alpine-`x-data`-Attribut am `<body>` kannst du auf
das entfernen, was nicht mehr gebraucht wird (`activeTab`, `activeSubTab`),
`selectedPartner` bleibt nur falls noch von anderem Code referenziert (prüfe
per grep, ob `selectedPartner` sonst irgendwo genutzt wird — falls nicht,
darf es mit raus).

**Tokens-Tab (`id="tab-tokens"`):** Kompletter Block entfällt ersatzlos —
`system/gui/templates/tokens.html` (eigene, vollständige Seite unter
`/tokens`, bereits in der Navigation unter "Agenten" verlinkt) deckt
denselben Funktionsumfang bereits ab (Preistabelle, Kostenrechner,
Wechselkurs). Vergewissere dich per kurzem Diff/Blick in `tokens.html`,
dass die IDs dort NICHT mit denen in `index.html` kollidieren (sie leben ja
eh auf unterschiedlichen Seiten, das ist nur eine Plausibilitätsprüfung).
Die zugehörigen inline `<script>`-Funktionen in `index.html`
(`loadTokenData`, `calculateCost` und alles, was NUR von diesen beiden
aufgerufen wird — prüfe per grep, ob sie sonst noch gebraucht werden)
kannst du ebenfalls entfernen.

**Dateien-Tab (`id="tab-files"`):** Die drei Unterreiter sind Eingang/
Scanner, Quarantäne, Verbindungen.
- Eingang/Scanner und Quarantäne/Anonymisierung existieren inhaltlich
  bereits identisch im Hauptmenü "Dateien" (`system/gui/templates/inbox.html`,
  Route `/inbox`, Tabs `Eingang / Scanner` und `Quarantäne / Anonymisierung`)
  — diese beiden Unterreiter aus `index.html` daher ersatzlos entfernen.
- **Verbindungen (Mounts) fehlt in `inbox.html` — das ist die "sinnvolle
  zusätzliche Funktion", die laut Ticket erhalten bleiben muss.** Migriere
  sie:
  1. Füge in `system/gui/templates/inbox.html` einen DRITTEN Tab hinzu,
     analog zum bestehenden Muster dort (`.tab-btn`/`.tab-content`-Klassen,
     `showTab(event, '...')`-Funktion — lies die Datei, das Muster ist an
     den beiden vorhandenen Tabs klar erkennbar). Tab-Label z. B.
     "Verbindungen" (🔗), Tab-Inhalt = die komplette Mounts-Tabelle +
     "Neuen Ordner anbinden"-Formular aus `index.html`s
     `id="subtab-connections"` (Zeilen ca. 415-470 in `index.html`,
     `git grep -n "subtab-connections" system/gui/templates/index.html`
     zum genauen Auffinden) — HTML-Struktur darf sich an `inbox.html`s
     eigenes CSS/Klassenschema anpassen (`inbox.html` nutzt eigenes CSS,
     nicht Tailwind wie `index.html` — baue die Tabelle/das Formular mit
     `inbox.html`s vorhandenen CSS-Klassen/Stil nach, nicht mit
     Tailwind-Klassen aus `index.html` kopieren).
  2. Übertrage die zugehörigen JS-Funktionen `loadMounts()`, `addMount()`,
     `removeMount(alias)`, `restoreMounts()` aus `index.html`s inline
     `<script>`-Block (Zeilen ca. 578-670) 1:1 in `inbox.html`s eigenen
     inline `<script>`-Block (analog zu dessen vorhandenem `loadQuarantine()`
     -Muster). Rufe `loadMounts()` beim Öffnen des neuen Tabs auf (analog zu
     `if (tabId === 'quarantine') loadQuarantine();` in `inbox.html`s
     `showTab`-Funktion — ergänze dort `if (tabId === 'verbindungen')
     loadMounts();` bzw. den von dir gewählten Tab-Namen).
  3. Backend unverändert lassen — `/api/mounts` (GET/POST) existiert bereits
     in `system/gui/server.py`, nicht anfassen.
  4. Danach den gesamten `id="tab-files"`-Block samt der zugehörigen
     JS-Funktionen aus `index.html` entfernen.

### 3) "Sinnvolle Übersicht": aktive Agenten/Worker ergänzen

Behalte die bestehenden Übersichts-Karten in `tab-overview` (System-Status
mit `stat-tasks`/`stat-messages`/`stat-deadlines`, Favoriten, Aktuelle
Tasks, Scanner Monitor) — die erfüllen den Zweck bereits größtenteils.
Ergänze EINE zusätzliche kleine Karte/Kachel "Aktive Agenten" bzw. "Aktive
Worker", die eine Kennzahl aus einem bereits vorhandenen, gleichen-Origin
Endpunkt zieht (`/api/agents`, `/api/bach-agents` oder `/api/daemon/status`
— prüfe per `grep -n "@app.get(\"/api/agents\|@app.get(\"/api/bach-agents\|@app.get(\"/api/daemon/status"
system/gui/server.py`, welcher Endpunkt eine sinnvolle Zahl liefert, z. B.
Anzahl konfigurierter/aktiver Agenten oder laufender Daemon-Jobs). Baue KEINE
neue Cross-Port-Anbindung an Port 8081 — nutze ausschließlich bereits
vorhandene :8000-Endpunkte. Halte dich an das bestehende Muster der anderen
Stat-Karten (gleiche CSS-Klassen, gleicher Lade-Mechanismus per
`fetch`/`API.get` wie die anderen `stat-*`-Felder — suche in `app.js` nach
der Funktion, die `stat-tasks`/`stat-messages` befüllt, und folge demselben
Muster für die neue Karte).

### 4) Ausbaustufen-Sektion nach "System" verschieben

Der `<!-- Ausbaustufen Badges -->`-Abschnitt (`<section
class="bg-[#0b0d14] border-t border-[#1e2236] py-8">...</section>`, kurz vor
`<footer>`) wird aus `index.html` entfernt und an das Ende von
`system/gui/templates/settings.html` eingefügt (vor dem schließenden
`</main>` bzw. an passender Stelle — `settings.html` nutzt kein Tailwind,
baue die drei Badges mit `settings.html`s eigenem CSS-Stil nach, nicht mit
den Tailwind-Klassen aus `index.html`). `settings.html` ist unter "System" >
"Einstellungen" in der Navigation bereits verlinkt.

### 5) Verifikation

- `python -c "from bs4 import BeautifulSoup" 2>&1 || true` (nur informativ,
  falls verfügbar für einen HTML-Parse-Sanity-Check; falls nicht installiert,
  überspringen).
- Nutze den bestehenden Testaufbau: `system/tests/test_gui_server_smoke.py`
  hat eine `client`-Fixture (FastAPI TestClient). Schreibe darauf aufbauend
  EINEN neuen Test `system/tests/test_startseite_cleanup.py`, der:
  - `GET /` lädt (Status 200) und per Text-Suche im HTML bestätigt:
    KEIN `id="tab-tokens"`, KEIN `id="tab-files"`, KEIN `id="headless-prompt"`,
    KEIN `Ausbaustufen` mehr enthalten.
  - `GET /inbox` lädt (Status 200) und enthält jetzt die Verbindungen-Tab-
    Kennung (z. B. den von dir gewählten Tab-Button-Text/`id`) sowie
    weiterhin `mounts-list-body` bzw. das äquivalente Element-ID, das du
    dort verwendest.
  - `GET /settings` lädt (Status 200) und enthält jetzt `Ausbaustufen`.
  - Führe `pytest system/tests/test_startseite_cleanup.py -q` aus und
    berichte das Ergebnis.
- `node -c system/gui/static/js/app.js` (falls du dort etwas geändert hast)
  bzw. keine Node-Datei geändert, wenn du alles inline gelassen hast — in
  jedem Fall: keine Syntaxfehler in den geänderten `<script>`-Blöcken
  (informell durch sorgfältiges Lesen sicherstellen, da inline JS in HTML
  nicht per `node -c` prüfbar ist).

## Selbstauskunft

Nenne am Ende deines Berichts EXAKT dein Modell.

## Bericht

Schreibe nach `_codex/BERICHT-p4.md`: geänderte Dateien, was wohin verschoben
wurde, Testergebnis, `git diff --stat`, dein Modell. Committe alles auf dem
aktuellen Branch (Conventional Commits, z. B. `refactor(gui): Startseite
bereinigen, Verbindungen nach Dateien, Ausbaustufen nach System
(T-20260913-660268706, P4)`). NICHT pushen.
