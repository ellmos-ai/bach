# MAC-ZWISCHENDEPLOY UND DEPLOY-GATE

Design-Dokumentation. Definiert (a) einen Mechanismus für **regelmäßige, sichere Mac-Zwischendeploys** und (b) das **Deploy-Gate**, das vor jedem Deploy/Release verpflichtend ist. Stand: Mechanismen definiert (Design); Code-/Workflow-Umsetzung folgt in eigenen Aufgaben.

Arbeitsbaum: `~/services/bach-worktrees/task-3752` · Task: BACH/Ocean #3752.

## 0. Befund: Warum dieses Dokument

- `docs/GUI_SOFTWARE_OCEAN_CATALOG.md` Z.52-97 verzeichnet Release-Pins (Commit, ZIP, SHA-256; Kit-Manifest 197 Dateien / 26 HTML-Seiten). Diese Pins sind **Quell-/Kit-Pins** und belegen **keine** Installation, keine LaunchAgent-Bindung und keine Live-Auslieferung auf dem Mac.
- `docs/operations/` enthält derzeit nur `BACH-3.15.0-MILESTONE.md`, `MAC-CHAT-LAUNCHAGENTS.md`, `MAC-WORKER-HARVESTER.md`, `RELEASE-AUDIT-2026-10-07.md` und `watchdog-inference-unload.md` – **keine** Deploy-, Installer-, Ocean- oder Scheduler-Workflows; `.github/` existiert als CI-Ort.
- Folge: Der regelmäßige, sichere Zwischendeploy auf dem Mac und das Gate davor waren nicht definiert. Diese Lücke schließt dieses Dokument (Kernaufgabe 7 der Task).

## 1. Mechanismus A: Regelmäßige, sichere Mac-Zwischendeploys

### 1.1 Pin-Tripel je Zwischendeploy
- Pro Release/Zwischendeploy wird ein Tripel **Commit-Pin + ZIP + SHA-256** fixiert, im Muster der Catalog-Pins. Der Pin wird je Deploy versioniert abgelegt (Deploy-Eintrag).

### 1.2 Versionsgebundene, unveränderliche Dist-Verzeichnisse
- Das Dist-Kit wird in ein **unveränderliches, versionsgebundenes Verzeichnis** ausgelegt (Namensschema als Vorschlag: `~/services/bach-dist/<version>-<sha>/`; verbindlich ist das Prinzip: Versionskennung + Commit-Bezug, nach Erstdist inhaltlich unverändert).
- Ein vorhandenes Auslieferungsverzeichnis wird **nicht überschrieben**. Umstellen des aktiven Bestands über Konfig-/Pin-Wechsel bzw. Atomtausch (z. B. Symlink-Swap), nie durch Inplace-Ersetzen.

### 1.3 LaunchAgent-Auslieferung
- Auslieferung über LaunchAgent analog dem bestehenden Muster `docs/operations/MAC-CHAT-LAUNCHAGENTS.md`; die Agent-Konfiguration zeigt auf das versionsgebundene Dist-Verzeichnis und wird **pro Release versioniert** mitgeführt.

### 1.4 Rollback-Satz
- Jede Auslieferung erhält einen abgestimmten Rollback-Satz: **Pin + LaunchAgent-Konfiguration + vorherige Dist**. Rollback = Zurücksetzen des Pins/Symlinks auf die Vorversion, ohne neue Erzeugung.

### 1.5 Periodischer Scheduler statt manueller Aktion
- Ein periodischer Scheduler prüft auf einen neuen, gate-freigegebenen Pin: bevorzugt GitHub Actions unter `.github/` (CI-Ort existiert dort schon), alternativ cron/launchd auf dem Mac.
- Der Scheduler führt nur Prüfung und Vorbereitung aus; die Installation/Auslieferung erfolgt **nur nach bestandenem Deploy-Gate (Abschnitt 2)** und nie als unkontrollierte manuelle Aktion.

## 2. Mechanismus B: Deploy-Gate (Pflicht vor jedem Deploy/Release)

### 2.1 Dist-Manifest-Check (technisch)
1. **Separate Prüfung des Dist-Verzeichnisses**: vollständige Dateiliste + Datei-Hashes gegen das Kit-Manifest (197 Dateien / 26 HTML-Seiten). Commit- und ZIP-Pins allein genügen nicht.
2. Bestätigung erst nach `GET /api/gui/kit-manifest` **und** `GET /api/gui/capabilities`: Commit passt, Verifikation erfolgreich, 26 HTML-Seiten erkannt.
3. **Abweichung** (Datei fehlt, Hash weicht ab, falscher Commit, Seitenzahl abweichend) → die API meldet den Dist als **unverifiziert**; eine unverifizierte Dist ist install-verboten (Gate „rot“).
- Der Live-Beleg der laufenden Auslieferung (system-explorer-Start im gebundenen Lauf) war nur alternativ prüfbar; er bleibt offener Punkt (Abschnitt 4).

### 2.2 Unabhängige Freigabe (prozessual)
- Laut `docs/operations/RELEASE-AUDIT-2026-10-07.md` Z.27-32: PR-Review, Integration und GitHub-Checks müssen den **tatsächlich gepushten Commit** prüfen; **lokale Tests ersetzen die unabhängige Freigabe nicht**.
- **Kein Release-Tag/Upload ohne bestandene Gates.**

### 2.3 Sicherheits-Gates
- `BACH-SEC-DEPS-01`: Dependabot-Ergebnisse nach Integration prüfen (ausstehend, Audit Z.27-32).
- `BACH-SEC-ROTATE-01`: Token-Rotation als Gate-Baustein einplanen (ausstehend, Audit Z.27-32).

### 2.4 Gate-Checkliste (operativ)
Ein Deploy ist freigegeben, wenn alle Punkte erfüllt sind:
1. Pin-Tripel (Commit, ZIP, SHA-256) fixiert (1.1).
2. Dist unverändert in versionsgebundenem Verzeichnis; nichts überschrieben (1.2).
3. Dist-Check: Dateiliste + Hashes vollständig gegen Kit-Manifest (2.1.1).
4. `kit-manifest` + `capabilities` bestätigt Commit, Verifikation und 26 Seiten; sonst unverifiziert → Abbruch (2.1.2./2.1.3).
5. Unabhängige Freigabe des gepushten Commits (Review/Integration/Checks) vorliegend (2.2).
6. `BACH-SEC-DEPS-01` und `BACH-SEC-ROTATE-01` geprüft bzw. beachtet (2.3).
7. Rollback-Satz gesichert: Pin + LaunchAgent-Konfiguration + Vorversion-Dist (1.4).

## 3. Pin- und Commit-Belege (Ist-Stand)

- `docs/architecture/BACH20-01-INVENTAR.md` Z.30: system-explorer Pin `bd250b1a` = Soll, `hub/explorer_provider.py` + `system_audit.py` nativ, `BACH_USE_EXTERNAL_EXPLORER=0`, Status ✅.
- `docs/architecture/MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12.md` Z.31: system-explorer `bd250b1a = bd250b1` ✅; offener Punkt verweist auf Plan 4.3.
- `docs/architecture/BACH20-02-SYSTEMMANIFEST.md` Z.278-279: `pin_commit_soll = pin_commit_ist = bd250b1a` (Soll/Ist im Systemmanifest).

Methodische Notiz zum Beleg: Im gebundenen Task-Lauf ist `git log` nicht ausführbar (`execute_command` erlaubt nur Prüfungen). Der Commit-Pin-Beleg wird daher alternativ geführt über das Systemmanifest (`pin_commit_soll = pin_commit_ist = bd250b1a`, Z.278-279) plus den nachstehenden Testlauf. Diese Doku dokumentiert genau das.

## 4. Prüf-/Abnahmebeleg dieses Laufes

- Test: `python -m pytest -q system/tests/test_explorer_provider_wiring.py` im Arbeitsbaum task-3752 → **Exitcode 0, 31 passed** (1 unkritische pytest-Warnung zu `confcutdir`). Bestätigt den Verdrahtungs-/Manifest-Bezug `bd250b1a`.
- Blockaden dieses Laufes (dokumentiert, nicht versteckt):
  - `git log` als Prüfung nicht erlaubt → alternativer Manifest-Beleg gemäß Abschnitt 3.
  - Start des system-explorer im gebundenen Lauf nur alternativ möglich → Live-Sichtprüfung der Auslieferung bleibt offener Punkt.
  - Original-Punkt 6 der Task (Lesezugriff auf Task 2052) nicht lesbar: `task_manage(action='detail', task_id=2052)` weist gebundene Läufe auf die eigene ID; der Punkt gilt als dokumentiert blockiert.
- Folgearbeiten nach dieser Design-Doku (Umsetzung, je eigene Tasks): Implementierung des Manifest-/Hash-Checks samt „unverifiziert“-Meldung; Scheduler-Workflow unter `.github/` (bzw. launchd); versionierte LaunchAgent-Verwaltung; Rollback-Prozedur nach 1.4.

## 5. Geltung

Diese Datei ist die verbindliche Definition der Mechanismen für Mac-Zwischendeploys und das Deploy-Gate. Die Umsetzung (Code/Workflow) darf erst aktiviert werden, wenn alle Punkte der Gate-Checkliste (Abschnitt 2.4) operativ erfüllbar sind; bis dahin gilt: kein Deploy/Tag/Upload.
