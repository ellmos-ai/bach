# Auftrag 2 — :8081 Control-API "/activity"-Design ins BACH-GUI-Design überführen (T-20260913-660268706, Punkt 7)

Du arbeitest im Worktree `C:/_Local_DEV/wt/bach-660268706-b` (Branch
`fix/T-20260913-660268706-activity-design`, Basis `origin/main`). Committe
auf DIESEM Branch. **NICHT pushen** — das übernimmt der Driver.

## Kontext

- Nutzer-Vorgabe (wörtlich): "http://macstudvonlukas:8081/activity -> Design
  in das bach gui design ueberfuehren." Ergänzender Hinweis des Nutzers:
  "/activity funktioniert und ist gute Basis -> nur Design angleichen,
  Funktion 1:1 erhalten."
- **Das heißt: NUR CSS/visuelle Änderungen. Keine Änderung an HTML-Struktur
  (IDs, Klassenamen, die von JavaScript referenziert werden), keine Änderung
  an `<script>`-Logik, keine Änderung an Fetch-URLs/Endpunkten.**
- Die Seite wird von `system/hub/_services/chat/telegram_chat.py` als
  Python-Docstring-Variable `WEB_DASHBOARD` (Zeilen 1306-1511) über einen
  eigenen minimalen `BaseHTTPRequestHandler` (Klasse `ControlHandler`,
  `do_GET` bei `path == "/"`) auf Port 8081 ausgeliefert — NICHT über die
  FastAPI-App von `system/gui/server.py` (Port 8000). Es gibt **keinen**
  Zugriff auf `/static/css/main.css` von dort aus (anderer Prozess/Port) —
  die Ziel-Farben/Tokens müssen als eigenes `<style>` in `WEB_DASHBOARD`
  eingebettet werden, nicht per `<link>` verlinkt.

## Ist-Zustand: `<style>`-Block in `WEB_DASHBOARD` (Zeilen 1312-1330)

```css
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}
h1{color:#00d4ff;margin-bottom:20px;font-size:1.4em}
.card{background:#16213e;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #0f3460}
.card h2{color:#00d4ff;font-size:1em;margin-bottom:12px}
.status-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #0f3460}
.status-row:last-child{border:none}
.label{color:#888}
.value{color:#00d4ff;font-weight:600}
.btn-group{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.btn{background:#0f3460;color:#e0e0e0;border:1px solid #00d4ff;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:.9em;transition:all .2s}
.btn:hover{background:#00d4ff;color:#1a1a2e}
.btn.active{background:#00d4ff;color:#1a1a2e;font-weight:700}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.dot.green{background:#00ff88}
.dot.red{background:#ff4444}
.dot.yellow{background:#ffcc00}
#toast{position:fixed;bottom:20px;right:20px;background:#00d4ff;color:#1a1a2e;padding:12px 20px;border-radius:8px;display:none;font-weight:600;z-index:99}
```

Das ist die alte "Cyan auf Navy"-Palette — passt NICHT zum Rest der BACH-GUI.

## Ziel: Design-Tokens aus `system/gui/static/css/main.css` (Zeilen 8-40, 295-421)

Das ist die kanonische BACH-GUI-Palette (Dark-Theme-Default), Schriftart
Plus Jakarta Sans:

```css
:root {
    --bg-dark: #0b0d14;
    --bg-panel: #111420;
    --bg-card: #171b28;
    --bg-elevated: #1c2033;
    --accent: #d4485a;
    --accent-light: #e06b7e;
    --accent-blue: #5b8def;
    --accent-glow: rgba(212, 72, 90, 0.12);
    --text: #e2ded8;
    --text-muted: #6e7386;
    --text-dim: #454a5c;
    --border: #1e2236;
    --border-hover: #2a3048;
    --success: #4ade80;
    --warning: #f5c542;
    --error: #ef5350;
    --radius-sm: 8px;
    --radius-md: 14px;
    --radius-lg: 18px;
    --ease: cubic-bezier(0.4, 0, 0.2, 1);
    --duration: 200ms;
}
```

Referenz-Klassen aus `main.css` (`.card`, `.card h2`, `.btn`, `.btn-primary`,
`.btn-secondary`, `.btn-danger`, `.btn-sm`) — lies sie selbst im Worktree
unter `system/gui/static/css/main.css` (Zeilen ~295-421) für die genauen
Werte (border-radius, padding, hover-Effekte, Schriftgewicht).

## Aufgabe

1. Ersetze den `<style>`-Block in `WEB_DASHBOARD`
   (`system/hub/_services/chat/telegram_chat.py`) durch eine Neufassung, die:
   - die obigen `:root`-Variablen einbettet (identische Werte wie
     `main.css`, damit ein Nutzer, der zwischen `:8000` und `:8081`
     wechselt, dieselbe Optik sieht),
   - `body` auf `--bg-dark`/`--text`/Plus-Jakarta-Sans umstellt (Google-Fonts
     `@import` wie in `main.css` Zeile 6, oder `<link>` im `<head>` — deine
     Wahl, Hauptsache es lädt),
   - `.card`, `.card h2` an `main.css`s `.card`/`.card h2` angleicht
     (`--bg-panel`-Hintergrund, `--radius-md`, `--border`, Hover-Effekt),
   - `.btn` an `main.css`s `.btn` + `.btn-secondary` angleicht (Basiszustand
     wie `.btn-secondary`: `--bg-card`-Hintergrund, `--border`), `.btn:hover`
     wie `.btn-secondary:hover`, `.btn.active` wie `.btn-primary`
     (`--accent`-Hintergrund, dunkler Text) — **die Selektoren `.btn`,
     `.btn:hover`, `.btn.active` MÜSSEN erhalten bleiben**, das JS setzt/liest
     nur diese Klassen, keine neuen `btn-primary`/`btn-secondary`-Klassennamen
     im HTML verteilen (nur die CSS-WERTE übernehmen, nicht die Klassennamen
     umbenennen),
   - `.status-row`, `.label`, `.value` farblich an `--border`/`--text-muted`/
     `--text` bzw. `--accent` angleicht,
   - `.dot.green/red/yellow` auf `--success`/`--error`/`--warning` umstellt,
   - `#toast` an `--accent`/`--bg-dark` angleicht,
   - `h1` auf `--text` mit `--accent`-Akzent umstellt (z. B. wie
     `main.css`s Logo-Bereich: Text in `--text`, ein Wortteil oder Icon in
     `--accent` — halte es einfach, ein reiner Farbwechsel reicht).
2. **NICHT ändern:** jegliches HTML außerhalb von `<style>` (IDs, Klassen im
   `class="..."`-Attribut, `onclick`-Handler, `<script>`-Inhalt, Fetch-URLs).
   Wenn ein Element inline `style="..."` trägt (z. B. der Link "Zur
   Aktivitätsanzeige..."), darfst du dessen Farben ebenfalls an die neuen
   Tokens angleichen (`background:#0f3460` -> `var(--bg-card)` etc.), aber
   NICHT dessen `href`, Text oder Struktur.
3. **NICHT anfassen:** alles außerhalb der `WEB_DASHBOARD`-Variable in dieser
   Datei, sowie `system/gui/server.py`, `system/hub/routine.py` und
   `system/tests/` (keine aktiven Locks mehr, aber außerhalb des Scopes
   dieses Auftrags).
4. **Verifikation:**
   - `python -c "import ast; ast.parse(open('system/hub/_services/chat/telegram_chat.py', encoding='utf-8').read())"`
     muss fehlerfrei durchlaufen (Python-Syntax-Check reicht, da die Datei
     ein reiner String-Literal-Body ist).
   - Führe `pytest system/tests -k telegram_chat -q` aus (falls Tests dazu
     existieren) und `pytest system/tests -k control_api -q`; berichte das
     Ergebnis. Falls keine passenden Tests existieren, vermerke das statt
     nichts zu berichten.
   - Baue dir selbst eine kleine Sichtprüfung: extrahiere den neuen
     `WEB_DASHBOARD`-String in eine temporäre `.html`-Datei (z. B. per
     kurzem Python-Einzeiler) und beschreibe in Worten, ob er plausibel
     aussieht (Farbwerte, keine offensichtlichen CSS-Syntaxfehler). Lösche
     die temporäre Datei danach wieder.

## Selbstauskunft

Nenne am Ende deines Berichts EXAKT dein Modell.

## Bericht

Schreibe deinen Bericht nach `_codex/BERICHT-2.md`: geänderte Datei(en),
Vorher/Nachher-Kurzbeschreibung der Farbpalette, Ergebnis der
Verifikationsschritte, `git diff --stat`, dein exaktes Modell. Committe alle
Änderungen auf dem aktuellen Branch (Conventional Commits, z. B.
`style(control-api): /activity-Design an BACH-GUI-Palette angleichen
(T-20260913-660268706)`). NICHT pushen.
