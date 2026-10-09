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