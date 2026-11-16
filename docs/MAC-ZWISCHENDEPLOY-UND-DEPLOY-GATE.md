# MAC-ZWISCHENDEPLOY UND DEPLOY-GATE

Verbindliche Betriebsdefinition für (a) **regelmäßige, sichere Mac-Zwischendeploys** und (b) das **Deploy-Gate**, das vor jedem Deploy/Release verpflichtend ist. Historischer Erstellungsbezug: Worktree `task-3752` (BACH/Ocean #3752); Abgleich auf den real gemessenen Release-/Pin-Mechanismus (`D-20261107-004`, GUI-Kit `0.2.40` mit `51` HTML-Seiten).

## 0. Ausgangslage & Einordnung

- Quell-/Kit-Pins in `system/gui/gui-consumer.v1.json` und `system/gui/kit_manifest.json` fixieren zwar die Soll-Identität des geteilten `ellmos-system-gui`-Release (`version`, 40-stelligem Quell-Commit, ZIP-Archivname und `release_archive_sha256`), belegen für sich allein jedoch **keine** erfolgte Installation oder LaunchAgent-Bindung auf dem Mac. *(Historischer Vorstand zur Task-Anlage: `26` HTML-Seiten / `197` Dateien; aktueller verifizierter `0.2.40`-Stand: `51` HTML-Seiten / `413` gehashte `dist`-Dateien).*
- Die operative Deploy-/Rollback-Grenze ist technisch über `system/tools/deploy_rollback_preflight.py`, `system/hub/_services/gui_contract_service.py` (`resolve_gui_distribution`, `get_pinned_kit_manifest`, `verify_installed_dist`) sowie das Live-Endpoint-Paar `GET /api/gui/kit-manifest` und `GET /api/gui/capabilities` verankert.

## 1. Mechanismus A: Regelmäßige, sichere Mac-Zwischendeploys

### 1.1 Pin-Tripel je Zwischendeploy
- Pro Release/Zwischendeploy wird ein verbindliches Pin-Tripel (**Quell-Commit + Release-ZIP + `release_archive_sha256`**) synchron in `system/gui/gui-consumer.v1.json`, `system/gui/kit_manifest.json` und `system/tests/test_gui_release_integrity.py` geführt (geprüft durch `verify_pin_parity()` in `system/tools/deploy_rollback_preflight.py`).

### 1.2 Versionsgebundene, unveränderliche Dist-Verzeichnisse
- Das entpackte Dist-Kit (`dist/` + `dist-manifest.json` nach Schema `ellmos-system-gui.dist.v1`) wird in ein **unveränderliches, versionsgebundenes Verzeichnis** ausgelegt: `shared-release-<version>-<sha12>/dist` (kein `~/services/bach-dist/`, kein Inplace-Überschreiben bestehender Stände).
- Der aktive Bestand wird ausschließlich durch Umstellen der Umgebungsvariable `ELLMOS_SYSTEM_GUI_DIST` im zuständigen LaunchAgent auf das neue unveränderliche Release-Verzeichnis aktiviert (`resolve_gui_distribution()` bevorzugt diesen expliziten Pfad vor dem Legacy-Fallback `system/gui/web/dist`).

### 1.3 LaunchAgent-Auslieferung (`com.bach.gui-server`)
- Die Auslieferung auf dem Mac Studio erfolgt ausschließlich über `~/Library/LaunchAgents/com.bach.gui-server.plist` (`ELLMOS_SYSTEM_GUI_DIST=.../shared-release-<version>-<sha12>/dist`, danach `plutil -lint` und gezieltes `launchctl kickstart`/`bootstrap` nur für `com.bach.gui-server`).
- **Harte Schutzgrenze:** `com.bach.telegram-bot`, `buddha_always_on` und `ollama` werden im GUI-Zwischendeploy **nicht** neu gestartet.

### 1.4 Rollback-Satz (ohne TaskDB-/Nutzerdaten-Berührung)
- Vor jedem Mac-Rollout wird unter `~/compute/rollback-<YYYYMMDD>/` ein vollständiger Rollback-Satz gesichert: **vorheriger `bach`-HEAD, Kopie von `com.bach.gui-server.plist`, bisheriger `ELLMOS_SYSTEM_GUI_DIST`-Pfad/Release**.
- Gemäß `RESTORABLE_PATHS_ALLOWLIST` in `system/tools/deploy_rollback_preflight.py` bleiben `~/.bach/bach.db`, `data/`, `user/`, `secrets/`, `.env` und `task_history` strikt vom Rollback ausgeschlossen. Rollback bedeutet lediglich Zurückschalten von `ELLMOS_SYSTEM_GUI_DIST` auf die vorherige unveränderliche Release-Dist und Neustart nur von `com.bach.gui-server`.

### 1.5 Periodische Gate-Prüfung vor Auslieferung
- Vor jeder Aktualisierung prüfen `deploy_rollback_preflight.py` (CI bzw. Host-Run) sowie `test_gui_release_integrity.py` die Pin-Parität zwischen `gui-consumer.v1.json` und `kit_manifest.json`. Eine Installation erfolgt erst nach bestandenem Deploy-Gate (Abschnitt 2).

## 2. Mechanismus B: Deploy-Gate (Pflicht vor jedem Deploy/Release)

### 2.1 Dist-Manifest-Check (technisch)
1. **Separate Byte- und Hash-Prüfung des Dist-Verzeichnisses**: `verify_installed_dist()` prüft alle Dateien in `dist/` und `dist-manifest.json` (`source_commit`, Schema `ellmos-system-gui.dist.v1`, 413 gehashte Dateien bei `0.2.40`, alle `51` HTML-Seiten) per SHA-256-Abgleich und Pfad-Sanitizing (keine Symlinks, keine unregistrierten Dateien).
2. **Live-Readback nach LaunchAgent-Start**: Bestätigung erst nach `GET /api/health` (`ok`), `GET /api/gui/kit-manifest` und `GET /api/gui/capabilities`: `verified == true`, `installed_files_verified == true`, `dist_page_count == 51` und exakter `revision`-Match gegen den gepinnten `source_commit`.
3. **Abweichung** (fehlende Datei, Hash-Abweichung, Symlink, falscher Commit oder Seitenzahl ≠ `51`) → die API meldet den Dist fail-closed als `unverified`; ein unverifizierter Dist führt zum sofortigen Abbruch und Rollback aus `~/compute/rollback-<YYYYMMDD>/`.

### 2.2 Unabhängige Freigabe (prozessual)
- Laut `docs/operations/RELEASE-AUDIT-2026-10-07.md` Z. 27–32 prüfen PR-Review, Integration und GitHub-Checks den **tatsächlich gepushten Commit**; **lokale Tests ersetzen die unabhängige Freigabe nicht**.
- **Kein öffentliches Release-Tag/Upload (`gh release create`) ohne bestandene Gates und explizite Nutzerfreigabe.**

### 2.3 Sicherheits-Gates
- `BACH-SEC-DEPS-01`: Dependabot-/Abhängigkeits-Checks vor öffentlicher Freigabe prüfen.
- `BACH-SEC-ROTATE-01`: Token-/Credential-Rotation und Geheimnis-Scan einhalten.

### 2.4 Gate-Checkliste (operativ)
Ein Zwischendeploy ist erst freigegeben, wenn alle Punkte erfüllt sind:
1. Pin-Tripel (`source_commit`, `release_archive`, `release_archive_sha256`) konsistent in `gui-consumer.v1.json` und `kit_manifest.json` fixiert (1.1).
2. Zielverzeichnis unveränderlich als `shared-release-<version>-<sha12>/dist` entpackt; kein Überschreiben alter Releases (1.2).
3. Vollständige Dateilisten- und SHA-256-Prüfung per `verify_installed_dist()` / `dist-manifest.json` bestanden (2.1.1).
4. Live-Readback `/api/health`, `/api/gui/kit-manifest` und `/api/gui/capabilities` bestätigt Commit, `verified: true`, `installed_files_verified: true` und `dist_page_count: 51`; andernfalls Abbruch & Rollback (2.1.2 / 2.1.3).
5. Unabhängige Zweitreview-Freigabe des gepushten Commits + grüne GitHub-Checks vorliegend (2.2).
6. `BACH-SEC-DEPS-01` und `BACH-SEC-ROTATE-01` beachtet (2.3).
7. Rollback-Satz unter `~/compute/rollback-<YYYYMMDD>/` ohne Berührung von `bach.db`/Nutzerdaten gesichert (1.4).

## 3. Code- und Prüfbelege (Ist-Stand)

- `system/hub/_services/gui_contract_service.py`: `resolve_gui_distribution()`, `get_pinned_kit_manifest()`, `verify_installed_dist()` (Vollhash-Prüfung, Symlink-/Traversal-Verbot).
- `system/tools/deploy_rollback_preflight.py`: `verify_pin_parity()`, `validate_rollback_paths()` (schützt `bach.db`, `data/`, `user/`, `secrets/`).
- `system/tests/test_gui_release_integrity.py` & `system/tests/test_deploy_rollback_preflight_3717.py`: Verifizieren Pin-Parität (`51` Seiten), Manifest-Schutz und Rollback-Grenzen.
- Historischer Worker-Vorlauf (`task-3752`, `2026-11-10`): `python -m pytest -q system/tests/test_explorer_provider_wiring.py` (31 passed, `bd250b1a`-Inventarbeleg).

## 4. Geltung

Diese Datei dokumentiert den verbindlichen Mechanismus für sichere Mac-Zwischendeploys von `ellmos-system-gui` / BACH und das vorgeschaltete Deploy-Gate. Öffentliche Releases/Tags bleiben bis zum Bestehen aller öffentlichen Release-Gates (`RELEASE-AUDIT-2026-10-07.md`) separat gesperrt.
