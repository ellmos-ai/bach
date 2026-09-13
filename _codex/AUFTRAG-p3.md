# Auftrag — Persönlicher-Assistent-Dashboard fertigstellen, Punkt 3 (T-20260913-660268706)

Du arbeitest im Worktree `C:/_Local_DEV/wt/bach-660268706-p3` (Branch
`fix/T-20260913-660268706-p3-persoenlich-dashboard`, Basis `origin/main`,
aktuell `9497b4c`). Committe auf DIESEM Branch. **NICHT pushen.**

## Kontext (bereits geklärt, nicht neu recherchieren)

`system/gui/templates/persoenlich.html` (Route `/agents/persoenlich`, 225
Zeilen) ist ein reiner Platzhalter: "In Entwicklung"-Hinweis, ein
Fantasie-Feature-Grid (Kalender, Erinnerungen, To-Do, Routinen, Übersicht,
Delegation — alles nur Text, nichts verlinkt, nichts implementiert), statische
"-"-Stat-Karten, eine "Nächste Schritte"-TODO-Liste. Nutzer-Vorgabe (Ticket
Punkt 1+3): diese Seite wird in der Navigation als "Dashboard" unter
"Persönlicher Assistent" geführt (bereits erledigt in `nav.js`, PR #51) und
soll jetzt inhaltlich fertiggestellt werden — **kein Bestand zu übernehmen,
das ist ein Neubau nach Zielbild:** Routinen/Kontakte/Denkarium/Wiki/Prompts/
Chat des Bereichs verlinken, echte Kennzahlen statt Platzhalter-Strichen.

Die Ziel-Unterseiten existieren bereits real und sind unter "Persönlicher
Assistent" in `system/gui/static/js/nav.js` (Zeilen ca. 69-76) bereits
verlinkt:
```js
{ label: "Persönlicher Assistent", children: [
    { href: "/persoenlich", label: "Dashboard" },   // <- diese Seite
    { href: "/chat", label: "Buddha Chat" },
    { href: "/prompt-library", label: "Deine Prompts" },
    { href: "/routinen?tab=personal", label: "Deine Routinen" },
    { href: "/kontakte", label: "Kontakte" },
    { href: "/denkarium", label: "Denkarium", external: true },
    { href: "/wiki", label: "Wiki" },
]},
```

## Aufgabe

Baue `system/gui/templates/persoenlich.html` als echte Hub-/Dashboard-Seite:

1. **Entferne:** den "In Entwicklung"-Hinweis (`.draft-notice`), das
   Fantasie-`.feature-grid` (Kalender/Erinnerungen/To-Do/...), den
   "Nächste Schritte"-Block. Der `<h1>`-Titel darf von "Persoenlicher
   Assistent" auf "Dashboard" umbenannt werden (Untertitel z. B. "Deine
   Werkzeuge auf einen Blick" o. ä. — passe sinngemäß an, keine Vorschrift).

2. **Neuer Schnellzugriff-Grid:** ersetze das alte Feature-Grid durch echte
   Link-Kacheln zu den fünf anderen Seiten des Bereichs (wiederverwende die
   vorhandenen CSS-Klassen `.feature-grid`/`.feature-card`/`.feature-icon`/
   `.feature-title`/`.feature-desc` aus derselben Datei — nur den Inhalt
   austauschen, jede Kachel wird zu einem klickbaren `<a href="...">`):
   - 💬 Buddha Chat → `/chat`
   - 📝 Deine Prompts → `/prompt-library`
   - 🔄 Deine Routinen → `/routinen?tab=personal`
   - 👥 Kontakte → `/kontakte`
   - 📓 Denkarium → `/denkarium`
   - 📚 Wiki → `/wiki`
   Kurze, echte Beschreibungstexte statt der bisherigen Fantasietexte (z. B.
   bei Denkarium: "Dein persönliches Notizbuch" — konsistent mit der
   Klarstellung aus PR #51/T-20260913-660268706 Punkt 5, NICHT "Board für
   Agenten" o. ä. schreiben).

3. **"Verlinkte Agenten"-Karte:** bleibt inhaltlich sinnvoll, aber prüfe die
   drei Links (`/financial`, `/agents/gesundheit`, `/agents/foerderplaner`)
   per `grep -n "@app.get(\"/financial\|@app.get(\"/agents/gesundheit\|@app.get(\"/agents/foerderplaner"
   system/gui/server.py` — existieren sie noch unter denselben Pfaden? Wenn
   ja, unverändert lassen. Wenn eine Route sich geändert hat, korrigiere nur
   diesen einen Link.

4. **Echte Kennzahlen statt "-"-Platzhalter:** die vier `.stat-card`-Kacheln
   (Termine heute / Offene Aufgaben / Verlinkte Agenten / Aktive Routinen)
   sollen, soweit mit vertretbarem Aufwand möglich, echte Werte aus
   vorhandenen Endpunkten ziehen:
   - "Aktive Routinen": `/api/routines` (existiert bereits, siehe
     `system/gui/server.py` — filtere client- oder serverseitig auf
     `tab=personal`/persönliche Routinen, falls das API das hergibt, sonst
     Gesamtzahl anzeigen).
   - "Verlinkte Agenten": bleibt statisch `3` (das ist korrekt, keine
     API nötig).
   - "Termine heute" / "Offene Aufgaben": wenn kein dediziertes
     Kalender-Backend existiert (prüfen: `grep -rn "api/calendar\|/api/tasks"
     system/gui/server.py`), nutze für "Offene Aufgaben" den bereits
     vorhandenen `/api/tasks`-Endpunkt (analog zu `stat-tasks` in
     `index.html`, dort kannst du das Lade-Muster per `grep -n "stat-tasks"
     system/gui/static/js/app.js` nachschlagen und 1:1 übernehmen). Für
     "Termine heute" gibt es kein Backend — lass den Platzhalter "-" stehen,
     baue KEIN neues Kalender-Feature (außerhalb des Ticket-Scopes).
   - Implementiere das Laden per neuem, kleinem inline `<script>`-Block am
     Ende der Datei (analog zum Muster in `index.html`/`app.js`: `fetch`
     bzw. das globale `API`-Objekt aus `api.js`, das die Seite bereits lädt).

5. **NICHT anfassen:** `system/gui/server.py` (Route `/agents/persoenlich`
   bleibt unverändert, sie rendert weiterhin dieselbe Datei), alle anderen
   Templates außer `persoenlich.html`.

## Verifikation

- Neuer Test `system/tests/test_persoenlich_dashboard.py` (nutze die
  `client`-Fixture aus `system/tests/test_gui_server_smoke.py` als Vorbild):
  `GET /agents/persoenlich` → Status 200, HTML enthält Links auf `/chat`,
  `/prompt-library`, `/routinen?tab=personal`, `/kontakte`, `/denkarium`,
  `/wiki`, enthält NICHT mehr "In Entwicklung" bzw. "Geplante Features".
  `pytest system/tests/test_persoenlich_dashboard.py -q` ausführen, Ergebnis
  berichten.
- Falls du `/api/routines` oder `/api/tasks` für die Kennzahlen anbindest:
  kurz curl/TestClient-Beleg, dass der Endpunkt tatsächlich JSON im
  erwarteten Format liefert (`client.get("/api/routines").json()` in einem
  Python-Einzeiler reicht, kein Browser nötig).

## Selbstauskunft

Nenne am Ende deines Berichts EXAKT dein Modell.

## Bericht

Schreibe nach `_codex/BERICHT-p3.md`: was geändert wurde, welche Kennzahlen
jetzt echt sind vs. Platzhalter geblieben, Testergebnis, `git diff --stat`,
dein Modell. Committe alles auf dem aktuellen Branch (Conventional Commits,
z. B. `feat(gui): Persoenlicher-Assistent-Dashboard fertigstellen
(T-20260913-660268706, P3)`). NICHT pushen.
