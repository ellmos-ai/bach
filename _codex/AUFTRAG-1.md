# Auftrag 1 — BACH GUI Nav-Umbau + Denkarium-Klarstellung (T-20260913-660268706)

Du arbeitest im Worktree `C:/_Local_DEV/wt/bach-660268706-a` (Branch
`fix/T-20260913-660268706-nav-denkarium`, Basis `origin/main`). Committe deine
Änderungen auf DIESEM Branch. **NICHT pushen** — das übernimmt der Driver.

## Kontext (damit du nicht neu recherchieren musst)

- Zentrale Navigation für die BACH-GUI (Port 8000) liegt NICHT pro Template,
  sondern zentral in `system/gui/static/js/nav.js`, Array `NAV_ITEMS`
  (ca. Zeile 63-104). Jedes Template lädt dieses eine Skript.
- Aktueller Stand des Arrays (Auszug, damit du die Ist-Struktur kennst):
  ```js
  const NAV_ITEMS = [
      { href: "/", label: "Dashboard" },
      { label: "Aufgaben", children: [
          { href: "/tasks-board", label: "Tasks" },
          { href: "/routinen?tab=bach", label: "BACH-Routinen" },
      ]},
      { label: "Persönlicher Assistent", children: [
          { href: "/chat", label: "Buddha Chat" },
          { href: "/prompt-library", label: "Deine Prompts" },
          { href: "/routinen?tab=personal", label: "Deine Routinen" },
          { href: "/kontakte", label: "Kontakte" },
          { href: "/denkarium", label: "Denkarium", external: true },
          { href: "/wiki", label: "Wiki" },
      ]},
      { label: "Agenten", children: [
          { href: "/chat", label: "Chats" },
          { href: "/agents-board", label: "Agents Board" },
          { href: "/reports", label: "📑 Berichte" },
          { href: "/memory", label: "Memory" },
          { href: "/tokens", label: "Tokens" },
      ]},
      { label: "Models", children: [
          { href: "#", portRel: 8081, path: "/activity", label: "Einstellungen", external: true },
          { href: "/tools", label: "Tools" },
      ]},
      { label: "Meine Domänen", children: [
          { href: "/financial", label: "Finanzen" },
          { href: "/ati", label: "🛠️ ATI Entwickler" },
          { href: "/steuer", label: "⚖️ Theodor Steuer" },
          { href: "/gesundheit", label: "🩺 Gesundheit" },
          { href: "/persoenlich", label: "🏠 Persönlicher Assistent" },
      ]},
      { href: "/inbox", label: "Dateien" },
      { label: "System", children: [
          { href: "/settings", label: "Einstellungen" },
          { href: "#", portRel: 8081, path: "/activity", label: "📊 Worker & Aktivität", external: true },
          { href: "/usecases", label: "Use Cases" },
          { href: "/daemon", label: "Automation" },
          { href: "/control/", label: "Unified GUI", external: true },
          { href: "/maintenance", label: "Wartung" },
          { href: "/logs", label: "Logs" },
          { href: "/help", label: "Help" },
      ]},
  ];
  ```
- `portRel` + `path` ist ein bestehender Mechanismus: die Nav baut daraus
  `http://<host>:<portRel><path>` (Zeilen ~142-158 in `initNavigation`). Damit
  wird bereits heute nach `:8081/activity` verlinkt — nichts Neues bauen, nur
  Einträge verschieben/umbenennen.
- `/persoenlich` (Route in `system/gui/server.py`) rendert
  `system/gui/templates/persoenlich.html` und leitet von dort per
  `RedirectResponse` auf `/agents/persoenlich` weiter (bzw. umgekehrt, prüfe
  im Code welche der beiden Routen die "echte" ist — beide existieren, nutze
  den bestehenden `href`-Wert `/persoenlich` unverändert, nur Label/Position
  ändern).
- **GESPERRT, NICHT ANFASSEN** (aktives `LOCK.oceanbach.txt`, anderer Agent
  arbeitet dort parallel): `system/hub/routine.py`, die
  Routinen-Endpunkte-Abschnitte in `system/gui/server.py`, und der komplette
  Ordner `system/tests/` (auch keine neuen Dateien dort anlegen). Wenn du in
  `server.py` etwas suchst: nur lesen/grep, nicht die Routinen-Routen ändern.
- Baseline-Testlauf vorher/nachher gleich halten: **19 failed / ~5000 passed**
  in der Gesamtsuite (`pytest system/tests` aus dem Repo-Root). Diese Zahl ist
  der bekannte Ist-Zustand, keine Regression durch dich einführen. Da du
  `system/tests/` nicht ändern darfst, ist das ein reiner Lesevergleich.

## Die vier Teilaufgaben

### 1) Nav-Umbau (`system/gui/static/js/nav.js`)

Ziel-Struktur für `NAV_ITEMS` (nur diese vier Gruppen ändern sich, alle
anderen Einträge/Gruppen unverändert lassen):

a) **"Persönlicher Assistent"**-Dropdown bekommt einen neuen, ERSTEN
   Kind-Eintrag: `{ href: "/persoenlich", label: "Dashboard" }` (kein
   `external: true` — das ist eine interne BACH-Route, kein Fremdlink).

b) **"Meine Domänen"**-Dropdown: den Eintrag
   `{ href: "/persoenlich", label: "🏠 Persönlicher Assistent" }` ENTFERNEN
   (er lebt jetzt nur noch unter "Persönlicher Assistent" → "Dashboard",
   siehe a). Die übrigen Domänen-Einträge (Finanzen, ATI, Steuer, Gesundheit)
   bleiben unverändert stehen.

c) **"Models"**-Dropdown als eigene Top-Level-Gruppe AUFLÖSEN. Seine beiden
   Kinder wandern als neue Einträge in die **"Agenten"**-Gruppe:
   - `{ href: "#", portRel: 8081, path: "/activity", label: "Models", external: true }`
     (der bisherige Eintrag hieß "Einstellungen" — er heißt jetzt "Models"
     und ist ein direkter Link, KEIN weiteres Untermenü)
   - `{ href: "/tools", label: "Tools" }`
   Füge beide ans Ende der `children`-Liste von "Agenten" an (nach "Tokens").

d) Ergebnis: `NAV_ITEMS` hat danach KEINE Top-Level-Gruppe mehr namens
   "Models". Die Gruppe "System" mit ihrem eigenen
   `{ ..., path: "/activity", label: "📊 Worker & Aktivität", ... }`-Eintrag
   bleibt UNVERÄNDERT (das ist ein bewusst zweiter Zugang zur selben Seite,
   nicht Teil dieses Auftrags).

Nach der Änderung: `node -c system/gui/static/js/nav.js` (Syntax-Check, node
ist auf diesem System installiert) muss ohne Fehler durchlaufen.

### 2) Denkarium — Klarstellung "Notizbuch des Users, kein Agenten-Board"

Befund: `system/hub/denkarium.py` (Klasse `DenkariumHandler`, CLI-Befehle
`bach denkarium write/read/search/brainstorm/promote`) hat aktuell KEINE
Beschriftung, die klarstellt, dass dieses Feature dem MENSCHLICHEN Nutzer
gehört. Agenten lesen die CLI-Hilfe und interpretieren es fälschlich als
eigenes Board/Scratchpad.

Aufgaben:
- In `system/hub/denkarium.py`: Docstring am Dateikopf (aktuell
  "Denkarium Handler - Logbuch + Gedanken-Sammler") um EINEN klarstellenden
  Satz ergänzen, z. B. sinngemäß: "Dies ist das persönliche Notizbuch des
  Users — NICHT als Board/Scratchpad für Agenten nutzen. Agenten nutzen
  stattdessen `bach memory` (Fakten/Lektionen) und Session-Berichte." Halte
  dich an bestehenden Stil/Sprache der Datei (Deutsch, knapp).
- Durchsuche `BACH_USER_MANUAL.md`, `BACH_USER_MANUAL.en.md`,
  `system/docs/BACH-FEATURES-SKILLS-USECASES.md` und `system/docs/README.md`
  nach "Denkarium" (`grep -rn -i denkarium <datei>`) und ergänze an JEDER
  Fundstelle, die das Feature Agenten als Werkzeug beschreibt (nicht dort, wo
  es bereits klar als User-Feature dasteht), denselben Klarstellungssatz oder
  einen sprachlich passenden Verweis auf `bach memory`/Session-Berichte als
  Agenten-Alternative. Deutsche Datei deutsch ergänzen, englische Datei (.en)
  auf Englisch.
- In `system/gui/templates/denkarium.html`: der Seiten-Untertitel steht in
  Zeile ~404 (`<p class="page-subtitle">Gedanken &middot; Logbuch &middot;
  Ideen</p>`). Lass ihn wie er ist (er ist bereits eindeutig an den
  menschlichen Nutzer gerichtet, das Bedienoberfläche-Design ist bewusst
  Notizbuch-artig) — hier ist NICHTS zu ändern, das ist nur zur Info, damit
  du nicht versehentlich das Layout anfasst.
- **NICHT ändern:** `system/tests/test_denkarium_handler.py` — liegt im
  gesperrten `system/tests/`.

### 3) Selbstauskunft

Nenne am Ende deines Berichts EXAKT dein Modell (z. B. per Selbstauskunft
"Ich bin Modell X").

### 4) Bericht

Schreibe deinen Bericht nach `_codex/BERICHT-1.md`: was geändert wurde (Datei
+ kurze Beschreibung), Ergebnis von `node -c system/gui/static/js/nav.js`,
Ergebnis von `git status`/`git diff --stat`, und dein exaktes Modell (Punkt 3).
Committe am Ende alle Änderungen auf dem aktuellen Branch mit einer
aussagekräftigen Commit-Message (Conventional Commits, z. B.
`refactor(gui): Nav-Umbau Models/Domänen + Denkarium-Klarstellung
(T-20260913-660268706)`). NICHT pushen.
