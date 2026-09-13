# Review-Auftrag — Startseite bereinigen (T-20260913-660268706, P4)

Du bist Reviewer für den Branch `fix/T-20260913-660268706-p4-startseite-cleanup`
(BACH-Repo) gegen `origin/main`. Lies
`git diff origin/main..HEAD -- system/gui/templates/index.html system/gui/templates/inbox.html system/gui/templates/settings.html system/gui/static/js/app.js system/tests/test_startseite_cleanup.py`
vollständig, sowie `_codex/AUFTRAG-p4.md` (Auftrag) und `_codex/BERICHT-p4.md`
(Autorenbericht).

Kontext: `index.html` (Route `/`, "BACH Dashboard") hatte drei Tabs
(Startseite/Tokens/Dateien). Ziel: nur noch eine Ansicht ohne Untertabs,
Chatfeld entfernt (war laut Funktionstest nur Aufgabenqueue), Tokens-Tab
entfernt (Duplikat von `/tokens`), Dateien-Tab entfernt — aber die
"Verbindungen"-Funktion (Mounts) MUSS vorher nach `inbox.html` (Route
`/inbox`, dort bisher nur "Eingang/Scanner" + "Quarantäne") migriert
werden, sonst geht Funktionalität verloren. Ausbaustufen-Sektion wandert
nach `settings.html`. Neu: eine "Aktive Agenten"-Übersichtskachel.

Prüfe gezielt:
1. Ist die Chatfeld-Entfernung vollständig (kein `id="headless-prompt"`
   mehr, aber die JS-Funktionen `sendHeadlessPrompt`/`selectPartner` in
   `app.js` dürfen unverändert/tot bleiben — das ist kein Fehler)?
2. Ist die Verbindungen-Migration nach `inbox.html` FUNKTIONAL vollständig:
   Tab-Button, Tab-Content, Mounts-Tabelle, "Neuen Ordner anbinden"-Formular,
   UND die JS-Funktionen `loadMounts`/`addMount`/`removeMount`/
   `restoreMounts` korrekt übertragen und in `showTab()` verdrahtet (wird
   `loadMounts()` beim Öffnen des Tabs aufgerufen)? Fehlt eine der vier
   Funktionen oder ist sie nur teilweise übertragen?
3. Ist `/api/mounts` (Backend, `system/gui/server.py`) unverändert
   geblieben (kein Backend-Zugriff nötig laut Auftrag)?
4. Ist die neue "Aktive Agenten"-Kachel an ein bereits vorhandenes,
   gleichen-Origin `:8000`-Endpunkt angebunden (kein neuer Cross-Port-Zugriff
   auf `:8081`)? Prüfe den tatsächlich verwendeten Endpunkt gegen
   `system/gui/server.py`.
5. Ist die Ausbaustufen-Sektion in `settings.html` inhaltlich vollständig
   (alle drei Badges: USMC, Rinnsal, BACH) und stilistisch an das dortige
   native CSS angepasst (nicht einfach Tailwind-Klassen aus `index.html`
   hineinkopiert, die dort mangels Tailwind-CDN nicht wirken würden)?
6. Führe `pytest system/tests/test_startseite_cleanup.py -q` und
   `pytest system/tests/test_gui_server_smoke.py -q` selbst aus, berichte
   Ergebnis. Führe `node -c system/gui/static/js/app.js` aus.
7. Wurde NICHTS außerhalb des Scopes verändert (kein Zugriff auf
   `system/gui/server.py`, keine anderen Templates)?

Urteil als APPROVE oder CHANGES-NEEDED, kurze Liste. Schreibe dein Ergebnis
nach `_codex/REVIEW-p4.md`. Nenne am Ende exakt dein Modell.
