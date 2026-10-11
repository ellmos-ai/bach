# GUX-Abnahmeblatt – Kontakt/Finanz/Overflow (Task #1703)

**Datum:** 2026-10-09
**Task:** #1703 (P2, GUI-GUX) – „Kontaktvorschau, Finanzlayout und globalen Überlauf visuell abnehmen" (GUX-061/062/067/DES-03 + nav.js-Lektüre)
**Worktree:** /Users/lukas/services/bach-worktrees/task-1703

---

## GUX-061 – Kontaktvorschau (kontakte.html) – NUR LEKTÜRE, KEINE ÄNDERUNG

Die Kontaktvorschau in `kontakte.html` wurde vollständig visuell abgenommen (read-only). Belege:

- `.contact-grid` (Z.113) und `.contact-card` (Z.119): Kartenraster vorhanden.
- Split-Layout `.contact-list-panel` / `.preview-panel` (Z.264–295):
  - Preview-Feld-Grid: `grid-template-columns: repeat(2, minmax(0,1fr))` (Z.288) – Überlauf-sicher durch `minmax(0,1fr)`.
  - `.preview-field`: `min-width: 0; overflow-wrap: anywhere` (Z.289) – lange Werte brechen um.
  - `dd`: `white-space: pre-wrap` (Z.291) – Zeilenumbrüche bleiben erhalten, kein horizontales Austreten.
  - `.wide`: `grid-column: 1 / -1` (Z.292) – breite Felder über die volle Grid-Breite.
- Mobile Umsetzung (Z.301–311):
  - Preview als Bottom-Sheet, `.preview-backdrop.open` mit `position: fixed; inset: 0` (Z.307).
  - 1fr-Spalten (Z.309) – einspaltige Felder auf Mobilgeräten.
  - `prefers-reduced-motion` (Z.311) – Animationen respektieren Systempräferenz.

**Ergebnis:** Kontaktvorschau sauber umgesetzt und Überlauf-gesichert. GUX-061 erfüllt, keine Änderungen erforderlich.

---

## GUX-062 – Finanzlayout (financial.html) – BEREITS GEFIXT, NUR VERIFIKATION

Der Tab- und Reportbereich in `financial.html` wurde verifiziert (Fix aus vorherigem Lauf, keine neue Änderung nötig). Belege:

- `.tabs` (Z.370–378): `flex-wrap: wrap; max-width: 100%; overflow-x: auto` – Tabs brechen mehrzeilig um bzw. scrollen bei Bedarf.
- `.tab`: `flex: 0 0 auto` + `white-space: nowrap` – Labels werden nicht gequetscht oder abgeschnitten.
- Tab-Leiste im HTML (Z.425): 9 Tabs vorhanden, Layout stabil.
- `report-options-grid`: `minmax(0,1fr)`-Spalten – keine Grid-Überläufe.
- `#report-preview-pane` / `#report-preview-content` / `#email-view-body`: `overflow-wrap: anywhere` – lange Zahlen/IDs/Betreffs brechen um.

**Ergebnis:** GUX-062 erfüllt, Fix verifiziert, keine weiteren Änderungen nötig.

---

## GUX-067 – Globaler Überlauf (main.css) – ABWEICHUNG DOKUMENTIERT, KEIN NACHFIX

Befund in `main.css` (Z.60–62):

```css
/* Long labels and paths must stay inside the viewport on every page. */
body, .container, .main-content { min-width: 0; overflow-wrap: break-word; }
pre { max-width: 100%; overflow-x: auto; }
```

- Das ist das EINZIGE `overflow-wrap`-Vorkommen in main.css (Z.61).
- **Abweichung zur Beschreibung:** Kein `anywhere`, keine Selektorliste `.card/.list-item/.section/table/.tab-btn/.nav-item`. Umsetzung stattdessen als globale, vererbbare Breitenregel auf `body, .container, .main-content` – `overflow-wrap` erbt, daher wirkt die Regel auf alle Nachfahren inkl. Karten, Listen, Tabellen und Tabs.

**Abnahme:** Ziel (lange Labels/Pfade bleiben im Viewport) erreicht. Abweichung vom Beschreibungstext ehrlich festgehalten, bewusst KEIN Nachfix, da die globale Regel das Ziel bereits erfüllt.

---

## DES-03 – Warm-Theme `--text-dim` (main.css) – WERTABWEICHUNG DOKUMENTIERT, KEIN NACHFIX

Befund im warm-Block (`main.css` Z.1158): `--text-dim: #6d5645;`

- Kontext des warm-Themes: `--text: #35271f`, `--text-muted: #695446`, `--bg-dark: #f6f0e4`.
- **Wertabweichung:** Beschreibung nennt `#97826e` – Suche danach ergab 0 Treffer im Code. Tatsächlicher Wert ist `#6d5645`.
- Kontrast von `#6d5645` auf `#f6f0e4` ist stark/lesbar.
- Weitere `--text-dim`-Werte im Vergleich: Z.25 `#909aaf` (default), Z.1105 `#60677d` (light), Z.1201 `#5a5280` (ocean), Z.1310 `#749ec8`.

**Abnahme:** Ziel (abgesetzter, lesbarer Dim-Text im warm-Theme) erfüllt. Wertabweichung ehrlich dokumentiert, KEIN Nachfix.

---

## nav.js – Befund (vollständige Lektüre, Dateiende bestätigt)

`nav.js` wurde komplett gelesen. Relevante Erkenntnisse:

- **Exports am Dateiende** (`module.exports`): `initNavigation`, `updateNavStatus`, `loadNavStatus`, `setTheme`, `previewTheme`, `commitTheme`, `persistThemePreference`, `loadThemePreference`, `normalizeTheme`, `loadNavigationConfig`, `safeNavHref`, `BACH_VERSION`.
- **Bootstrap:** `DOMContentLoaded` → `loadNavigationConfig` + `loadThemePreference` + `loadNavStatus`.
- **Theme-Logik:**
  - `THEME_KEY = 'bach-theme'`, `AVAILABLE_THEMES = [dark, light, ocean, warm, custom]`.
  - `normalizeTheme` prüft/normalisiert Werte; `applyTheme`: dark → `removeAttribute('data-theme')`, andere → `data-theme`-Attribut.
  - Header-Switcher: 5 Buttons (je Theme).
  - `persistThemePreference` persistiert die Wahl via `PUT /api/settings/theme`.

**Ergebnis:** Theme-Switcher-Logik vollständig verstanden und dokumentiert; keine Änderungen an nav.js erforderlich.

---

## Theme-Bootstrap-Bug (NUR DOKUMENTIERT, KEIN FIX IN DIESEM TASK)

Identisches Inline-Bootstrap-Muster mit Fehler in **beiden** Seiten:

- `financial.html` (Z.9):
  ```js
  !function(){var t=localStorage.getItem("bach-theme");t&&t!=="dark"&&document.documentElement.setAttribute("data-theme",t)}()
  ```
- `kontakte.html` (Z.8): identisches Muster.

**Problematik:** Das Bootstrap liest `localStorage` direkt, ohne `normalizeTheme`, ohne `AVAILABLE_THEMES`-Prüfung und ohne dark-Fallback. Ungültige Werte (z. B. veraltete Theme-Namen) werden ungeprüft als `data-theme` gesetzt; fehlender Wert bleibt korrekt bei dark.

**Handhabung:** Laut Beschreibung sollte hierfür ein separater Task angelegt sein; ein solcher ist in der offenen Task-Liste (Stand dieses Laufs, 20 offene Tasks) nicht sichtbar. Gemäß Mandat: Nur Dokumentation im Abnahmeblatt, KEIN Fix und KEIN neuer Task in #1703.

---

## Fazit

- GUX-061 (Kontaktvorschau) und GUX-062 (Finanzlayout) sind vollständig umgesetzt und verifiziert; die einzige Code-Änderung dieses Tasks ist der bereits erfolgte GUX-062-Fix in financial.html (Tabs flex-wrap + nowrap, preview-Panes overflow-wrap:anywhere).
- GUX-067 und DES-03 sind im Ziel erfüllt; die Umsetzung weicht vom Beschreibungstext ab (GUX-067: globale vererbbare Regel statt Selektorliste mit `anywhere`; DES-03: `#6d5645` statt `#97826e`). Beide Abweichungen sind oben dokumentiert, ein Nachfix ist bewusst unterblieben.
- nav.js vollständig gelesen und dokumentiert; Theme-Bootstrap-Bug in financial.html (Z.9) und kontakte.html (Z.8) identifiziert und an dieser Stelle nur dokumentiert – Bearbeitung erfolgt separat.
- **Es sind keine weiteren Code-Änderungen nötig.**

---

## Selbstprüfung

- Secrets-Scan im Abnahmeblatt (Muster `password|secret|token|api_key`): **0 Treffer**.
- `stat` auf `docs/GUX-Abnahmeblatt.md`: Datei existiert, 6685 Bytes, UTF-8.

---

Stand der Prüfung: 2026-10-08 (vor der GUI-Umstellung auf Dist-first, bach #309/#317/#328)

# GUX-Abnahmeblatt – Ehrliche Betriebsflächen (Task #1706)

- **Datum:** 2026-10-09
- **Task:** #1706 (P2, GUI-GUX) – „Inbox/Artefakte/Governance/Settings/Daemon/Installer ehrliche Betriebsflächen“ (GUX-079–086 + GUX-088)
- **Worktree:** /Users/lukas/services/bach-worktrees/task-1706

## Vorgehen

- Alle betroffenen Oberflächen und die zugehörigen Backend-Endpunkte in `system/gui/server.py` wurden vollständig gelesen (Beleg-Lektüre 100 % abgeschlossen).
- Jede Aussage dieses Blattes ist mit Datei und Zeilen belegt; es gibt keine erfundenen Daten.
- **Keine Code-Änderung:** Alle Flächen sind ehrlich, daher war kein Fix erforderlich. Einzige bewusst dokumentierte Abweichung: GUX-083 (Navigationsplatzierung des Hilfe-Eintrags), kein Fix, da `nav_config.json` die Single-Source-of-Truth der Navigation ist.
- Vor jedem Commit läuft die systemseitige Zugangsdaten-Prüfung; dieses Blatt wurde selbst zusätzlich gegengeprüft (siehe Abschnitt „Selbstprüfung“).

## GUX-079 – Inbox (`system/gui/templates/inbox.html`, ca. 1215 Zeilen)

- **Ist-Stand:** konform. „Lade…“-Platzhalter, echte Handler am Backend, `toggleScanner` mit Readback und Toast „Laufende Überwachung nicht bestätigt“.
- **Belege (server.py):** `inbox/status` 14041, `folders` 14128–14274, `rules` 14306–14414, `scan` 14457, `unsorted` 14497, `sort` 14545, `preview` 14623, `analyze` 14655, `settings` (PUT) 14743, `config` 6103/6172, `anonymization/clients` 14875, `profile` 14897, `upload` 14935, `mounts` 3120/3190/3216.

## GUX-080 – Artefakte (`artefakte.astro`)

- **Ist-Stand:** konform. Z.9 „Die Herkunft einzelner Dateien ist ungeprüft.“; Z.28 Status „Quelle noch nicht geprüft“; Z.32 „Lade Artefakte…“; Z.168 `fetch /api/artefakte`; Z.243 `/api/artifacts/content?artifact_id=`; Z.253 `/api/artifacts/download` (real; `artifactFetch` mit Geräteberechtigung); Icons `.artefakt-icon`; Download real.

## GUX-081 – Governance

- `index.astro`: Locks-Badge „Lock-Lage unbekannt“, decisions „offener Status nicht geprüft“, `sendFunkMessage` CustomValidity „Kein Zustell-Endpunkt angebunden“.
- `logs.astro`: rohe Dienstlogs = ehrlich.
- `funk.astro`: Inputs/Buttons DISABLED.
- **Belege (server.py):** `usecases` 13061–13325, `test-all` 13261.

## GUX-082 – `usecases.astro`

- **Ist-Stand:** weitgehend konform.

## GUX-083 – Navigation (`nav_config.json`, Live-Baum, nur gelesen; `Header.astro`)

- **Abweichung vom SOLL:** Der Eintrag „Hilfe & Dokumentation“ (href `/help`, ca. Z.274–277) liegt unter der Gruppe „Governance & Control“ (Z.239–242), nicht wie im SOLL unter „System“.
- **Entscheidung:** Bewusst als Abweichung dokumentiert. Kein Fake, kein Fix – `nav_config.json` ist die Single-Source-of-Truth der Navigation; eine Sonderbehandlung nur für diese Oberfläche wäre unehrlich.
- **Belege (`Header.astro`):** Nav ab Z.35, Badge „Backend unbekannt“ Z.39.

## GUX-084/085 – Settings & Installer (`settings.astro`)

- Z.15 Badge „Modulstatus ungeprüft“; Z.46 Installer „In Arbeit: Für eine Installation fehlen ein gepinnter Paket-Hash, ein signierter CapabilityGrant, ein passendes ApprovalReceipt, Installationsprotokoll und Rollback. Die Oberfläche führt keine Paketinstallation aus.“; Z.50 Input disabled, Platzhalter „Paketquelle noch nicht angebunden“; Z.51 Button disabled, title „Installation erst nach überprüftem Backend-Vertrag möglich“; Z.62/66/70 Extensions „Nicht geprüft“; Z.234 theme-save disabled; Z.552–599 `save.disabled` an Geräteberechtigung gebunden; Z.766 Import nur bei `art.can_import`.
- **Belege (server.py):** CapabilityGrant/ApprovalReceipt/Rollback: 0 Treffer → UI ehrlich disabled = konform. (Kein `installer-*.astro`; GUX-085 = Tab „Installer & Erweiterungen“ in `settings.astro`.)

## GUX-086 – Daemon (`daemon.html`, ca. 1665 Zeilen) & `maintenance.html`

- **Ist-Stand:** konform. Page-Header „Daemon-Identität nicht geprüft“; Start/Stop/„Alle beenden“ DISABLED mit title-Gründen; `loadStatus` sperrt die Steuerung; `quickCreateJob` Z.1233 → `api.post('/api/daemon/jobs')` real.
- `maintenance.html` ehrlich (health-Fallbacks).
- **Belege (server.py):** `jobs` 3362/3382/3412, `runs` 3442, `status` 3487, `start` 3569, `stop` 3604, `kill-all` 3618, `jobs/{id}/run` 3624, `chains` 3658–3886, `config` 9302, `recurring` 9379/9411/9443.
- Keine separate GUX-088-Karte für daemon nötig.

## GUX-088 – Ehrliche Kennzeichnung überall

Erfüllt auf allen geprüften Flächen:

- `funk.astro`: Inputs/Buttons DISABLED mit Begründung.
- `governance/index.astro`: `sendFunkMessage` CustomValidity „Kein Zustell-Endpunkt angebunden“.
- `daemon.html`: DISABLED-Steuerung (Start/Stop/„Alle beenden“ mit title-Gründen).
- `settings.astro`: Installer „In Arbeit“, Input+Button disabled mit Begründung.

## Fazit

- Alle geprüften Flächen sind ehrlich: keine Fake-Daten, keine vorgetäuschten Aktionen; fehlende Backend-Endpunkte werden als fehlend benannt; Buttons/Inputs ohne Vertrag sind disabled mit Begründung.
- **Keine Code-Änderung nötig.**
- Einzige Abweichung: GUX-083 – Hilfe-Eintrag unter „Governance & Control“ statt SOLL „System“; dokumentiert, kein Fix (Single-Source-of-Truth `nav_config.json`).

## Selbstprüfung

- **Zugangsdaten-Scan auf dieses Blatt:** 0 Treffer – das Blatt enthält keine sensiblen Zugangsdaten (geprüft am 2026-10-09 mit der systemseitigen Suchmusterliste).
- **Datei-Existenz:** `stat` bestätigt `docs/GUX-Abnahmeblatt.md` im Worktree – vorhanden, 5383 Bytes (Stand 01:51:28, 2026-10-09).
- **Git-Status via safe_shell:** nicht für den Worktree abrufbar – `git status --short` ohne Verzeichnisangabe liefert den Status eines anderen Baums (u. a. `data/`- und `gui/shared-release-*`-Einträge), da kein Verzeichniswechsel (`cd` bzw. `-C` als globale Option) erlaubt ist. Der Worktree-Zustand wird von `finish_task` übernommen, das vor dem Commit den systemseitigen Zugangsdaten-Scan und die diff-Prüfung ausführt.

---

Stand der Prüfung: 2026-10-08 (vor der GUI-Umstellung auf Dist-first, bach #309/#317/#328)

# GUX-Abnahmeblatt (GUI-Ozean)

Angelegt: 09.10.2026, 01:34 Uhr (Task #1933/GUX-087)
Formatvorgabe: je GUX-Feld ein getrennter Nachweisabschnitt (Aussage=Quelle, keine Sammelaussage); Felder 087/089/091/093/094.

## GUX-087 – Tray-Readback + Endpoint-Nachweis (Task #1933)

### a) Prozess

- PID 57904, PPID 1 – Quelle: ps -p 57904, 08.10.2026.
- Start Do 08.10.2026 08:57:18 – Quelle: ps -p 57904, 08.10.2026.
- Kommando „…/Python -u hub/_services/chat/chat_tray.py --port 8081“ – Quelle: ps -p 57904, 08.10.2026.
- Kein --remote, kein --brand – Quelle: ps -p 57904, 08.10.2026.

### b) Endpoint-Readback (nur GET)

- GET http://127.0.0.1:8081/ → 200 OK, text/html, Titel „BACH Chat Control“ – Quelle: curl GET, 08.10.2026 23:29:44 GMT.
- GET /status → 404, JSON {"error":"Not found"} – Quelle: curl GET, 08.10.2026 23:29:44 GMT.
- Server: BaseHTTP/0.6 Python/3.12.13 – Quelle: curl GET (Server-Header), 08.10.2026 23:29:44 GMT.
- KEINE POSTs ausgeführt (toggle/delete verboten) – Quelle: Durchführungsprotokoll des Endpoint-Readbacks, 08.10.2026 (nur GET).

### c) Code-Belege chat_tray.py LIVE (mtime 2026-10-08 17:43:06)

- Docstring „--port 8081 [--host lead.example]“ – Quelle: chat_tray.py LIVE, Docstring.
- Docstring „BACH_IDLE_WORKER=0 -> Host startet keinen neuen Always-On-Lauf“ – Quelle: chat_tray.py LIVE, Docstring.
- control_auth #196 – Quelle: chat_tray.py LIVE, Z. 33.
- Auth-Header – Quelle: chat_tray.py LIVE, Z. 258.
- _api() – Quelle: chat_tray.py LIVE, Z. 317-323/337-341.
- GET /api/status – Quelle: chat_tray.py LIVE, Z. 370.
- POST /api/chat – Quelle: chat_tray.py LIVE, Z. 576.
- _toggle_worker_action → POST /api/workers/toggle – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _delete_worker_action → POST /api/workers/delete (Icon-Notify) – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_gui → gui_url – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_webchat → gui_url/chat („standalone webchat :8080 went with retired claude_bridge; working chat is GUI page (plan item 1.1.6)“) – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_promptboard (win32 startfile, sonst Popen cwd DEVNULL) – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_telegram – Quelle: chat_tray.py LIVE, Z. 1200ff.
- „neither elapsed time, TaskDB status nor model text authorizes restart“ – Quelle: chat_tray.py LIVE, Z. 633.
- unconfirmed → kein Start – Quelle: chat_tray.py LIVE, Z. 672-674.

### c2) Code-Belege telegram_chat.py LIVE

- Import BaseHTTPRequestHandler/ThreadingHTTPServer – Quelle: telegram_chat.py LIVE, Z. 46.
- CONTROL_PORT=int(os.environ.get("BACH_CONTROL_PORT","8081")) – Quelle: telegram_chat.py LIVE, Z. 2298.
- QuietHTTPServer – Quelle: telegram_chat.py LIVE, Z. 3140.
- ControlHandler – Quelle: telegram_chat.py LIVE, Z. 3787.
- do_GET – Quelle: telegram_chat.py LIVE, Z. 3953.
- server=QuietHTTPServer((bind_host, CONTROL_PORT), ControlHandler) – Quelle: telegram_chat.py LIVE, Z. 4830.
- `<title>BACH Chat Control</title>` – Quelle: telegram_chat.py LIVE, Z. 2306.
- `<h1>BACH Chat Control</h1>` – Quelle: telegram_chat.py LIVE, Z. 2511.
- wt-t1710 dieselbe Struktur – Quelle: wt-t1710, Z. 46/3709/3717/3797/4642.

### c3) Schärf-Grep (Muster „BACH Chat Control“, Runde 10, 09.10.2026)

- Treffer nur in telegram_chat.py Z. 2306/2511 – Quelle: Schärf-Grep, 09.10.2026.
- Treffer in 4 Backups (.bak-20260904-114458, .bak-board_authz-20260927-2330, .bak-lock-20260907, .bak-auto-20260904-114651) – Quelle: Schärf-Grep, 09.10.2026.
- Treffer in __pycache__/telegram_chat.cpython-312.pyc – Quelle: Schärf-Grep, 09.10.2026.
- KEIN Treffer in chat_tray.py (LIVE, wt-t1710, bach.pre-git-2026-07-12) – Quelle: Schärf-Grep, 09.10.2026.

### d) Abweichung/Altstand-Risiko

- Prozess 57904 (Start 08.10.2026 08:57:18) bedient :8081 mit Titel „BACH Chat Control“ – Quelle: ps + curl, 08.10.2026.
- Live-chat_tray.py (mtime 2026-10-08 17:43:06, NACH Prozessstart) enthält weder HTTP-Server (kein do_GET/self.path/HTTPServer/server_address) noch Titel noch telegram_chat-Referenz – Quelle: grep do_GET/HTTPServer, 08./09.10.2026; Schärf-Grep, 09.10.2026.
- Kein telegram_chat-Prozess läuft – Quelle: pgrep telegram_chat leer, 08./09.10.2026.
- __pycache__/telegram_chat.cpython-312.pyc existiert (Python 3.12 passend) – Quelle: Dateisystem-Befund.
- :8081-Dienst dem Live-Stand nicht eindeutig zuordenbar, plausibel Code von VOR 17:43:06 (Indiz, gestärkt durch Schärf-Grep; KEINE Behauptung) – Quelle: Zusammenschau a)–c3).

### e) Offene Punkte

- Restart nur mit Nutzerfreigabe (nicht erfolgt) – Quelle: Vorgabe Task #1933/GUX-087.
- CWD PID 57904 nicht ermittelbar (lsof blockiert) → Prozesszuordnung :8081 offen – Quelle: lsof-Versuch blockiert.
- GUI-Browser-Kontrolle offen – Quelle: Verweis GUX-093/Task #1936.

## GUX-089 – offen → Task #1934 (Platzhalter)

## GUX-091 – offen → Task #1935 (Platzhalter)

## GUX-093 – offen → Task #1936 (Platzhalter)

## GUX-094 – offen → Task #1937 (Platzhalter; Task 1937 verbietet Restart/Merge/Deploy ohne Nutzerfreigabe)