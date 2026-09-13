# Review-Auftrag — Persönlicher-Assistent-Dashboard (T-20260913-660268706, P3)

Du bist Reviewer für den Branch `fix/T-20260913-660268706-p3-persoenlich-dashboard`
(BACH-Repo) gegen `origin/main`. Lies
`git diff origin/main..HEAD -- system/gui/templates/persoenlich.html system/tests/test_persoenlich_dashboard.py`
vollständig, sowie `_codex/AUFTRAG-p3.md` (Auftrag) und `_codex/BERICHT-p3.md`
(Autorenbericht).

Kontext: `persoenlich.html` war ein reiner Platzhalter-Stub (Fantasie-Feature-
Grid, "-"-Kennzahlen). Ziel: echte Hub-Seite mit Links zu Chat/Prompts/
Routinen/Kontakte/Denkarium/Wiki und echten Kennzahlen aus vorhandenen APIs
(`/api/tasks`, `/api/routines`).

Prüfe:
1. Sind alle 6 Schnellzugriff-Links (`/chat`, `/prompt-library`,
   `/routinen?tab=personal`, `/kontakte`, `/denkarium`, `/wiki`) korrekt und
   entsprechen sie exakt den Hrefs in `system/gui/static/js/nav.js`
   (Gruppe "Persönlicher Assistent")?
2. Sind die 3 "Verlinkte Agenten"-Links (`/financial`, `/agents/gesundheit`,
   `/agents/foerderplaner`) tatsächlich noch gültige Routen in
   `system/gui/server.py`?
3. Ist das JS am Dateiende (`loadDashboardStats`) robust (try/catch pro
   Fetch, kein Absturz bei fehlender `API`-Globalvariable, sinnvolle
   Fallback-Werte)?
4. Wurde NICHTS außerhalb des Ticket-Scopes verändert (kein Zugriff auf
   `system/gui/server.py`, keine anderen Templates)?
5. Führe `pytest system/tests/test_persoenlich_dashboard.py -q` und
   `pytest system/tests/test_gui_server_smoke.py -q` selbst aus, berichte
   Ergebnis.
6. Ist die Denkarium-Beschreibung ("Dein persönliches Notizbuch") konsistent
   mit der Klarstellung aus Ticket-Punkt 5 (PR #51) — NICHT als
   Agenten-Board beschrieben?

Urteil als APPROVE oder CHANGES-NEEDED, kurze Liste. Schreibe dein Ergebnis
nach `_codex/REVIEW-p3.md`. Nenne am Ende exakt dein Modell.
