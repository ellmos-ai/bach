# BELEG 2021 — Dashboardkonsolidierung: Inventur der fünf Quellen

- Task: #2021 (P2, claim_fence 821, correction_request_id 76)
- Stand: 2026-11-14
- Art: **getrennter Analyse-/Taskaufnahmebeleg** (Teilstand, **kein Abschluss**)
- Arbeitsbaum: `/Users/lukas/services/bach-worktrees/task-2021`

## 0. Statusaussage (verbindlich)

- **Kein DONE.** Task #2021 ist mit diesem Beleg nicht abgeschlossen; die Konsolidierung
  der Generatoren/Pages/Verweise ist nur inventarisiert, nicht umgesetzt.
- **#2153 ist unaccepted/stale.** Die dort behauptete SACKGASSE („`ki-center.html`
  fehlt/unklar“) wird durch die Inventur widerlegt (siehe Abschnitt 5) und darf nicht
  als Abnahmegrundlage dienen.
- Folgeschritte bleiben offen und sind an #2153 als unaccepted/stale Folgearbeit gemeldet.

## 1. Quelle A — CI-Workflow `gui-web`

Datei: `.github/workflows/gui-web.yml`

- Z. 3–5: `system/gui/web` ist eine **veraltete Kopie**; einzige GUI-Quelle ist
  `ellmos-system-gui`.

## 2. Quelle B — Kit-Manifest (Pin)

Datei: `system/gui/kit_manifest.json` (Größe 496 B)

- Z. 2–10: schema `ellmos-system-gui.kit-manifest.v1`,
  repo `ellmos-ai/ellmos-system-gui`,
  pinned commit `eb0251ac4b85574087ad934611d19dc3df1f9c4c`,
  version `0.2.30`, dist schema `…dist.v1`,
  `expected_page_count: 39`,
  archive `ellmos-system-gui-0.2.30-eb0251ac4b85.zip`,
  sha256 `ff07b55656349da60cb18b5ead867da3f03d43d81e6964bc6448212d7412b188`,
  `pinned_at: 2026-10-31T12:52:00Z`.

## 3. Quelle C — Consumer-Vertrag

Datei: `system/gui/gui-consumer.v1.json`

- Z. 2–18: `status: pinned_release`, identischer Commit und identischer SHA wie Quelle B.
- `required_backend_routes`: `/api/gui/brand`, `/api/gui/backend-origin`,
  `/api/gui/capabilities`.
- Z. 17 (wörtlich sinngemäß): „A pin alone does not prove a live installation.“
  → Ein Pin ist **kein** Installationsnachweis.

## 4. Quelle D — Deployment-Receipt

Datei: `system/gui/GUI_DEPLOYMENT_RECEIPT_2026-10-03.md`

- Z. 7–9: Squash `407e45cb`, veröffentlicht `3827251a259d4cb765877820c7c6e6e48a297460`
  auf `origin/main`, Build 16/16 Astro-Seiten.
- Sessions-HTML sha256 `f43c6698caf8dd4dce8f50000ff7c1165bb6d4487d60bb65a3e6f9978d9682cd`.
- Z. 13–16: Overlays `bach-ocean-profiles-20261003-8b918030` und
  `bach-ocean-final-wave-20261003-3827251a` in `~/private-deploy-backups/`.

**Divergenz (dokumentiert, nicht bewertet):** Receipt datiert 2026-10-03, Kit-Pin datiert
2026-10-31 (`pinned_at`). Der Receipt beschreibt damit einen **älteren** Stand als der
aktuelle Pin (0.2.30 / `eb0251ac…`). Receipt-Belege dürfen deshalb nicht als Nachweis für
den gepinnten Release gelten; ein Folgebeleg für den Pin-Stand fehlt.

## 5. Quelle E — Audit-/Integrationsbeleg

Datei: `system/gui/GUI_AUDIT_INTEGRATION_2026-10-03.md`

- Z. 3: Ausgangscommit `c2055a7c`; Ports aus `88171f50`; keine Produktionsinstallation geändert.
- Z. 11: Erfolgsbadges im Dashboard → `unknown`/`configured`.
- Z. 17–25 Vertragstabelle: Tasks `server.py:1648`, Blueprints
  `api/unified_api.py:340/382/487/525`, Cluster-Cockpit `:2567`,
  Device-Auth `server.py:1303` und `:5155`.

## 6. Seiten-/Generatorinventur im Arbeitsbaum

- `system/gui/templates`: **39 HTML-Pages** — deckt sich mit `expected_page_count: 39`
  aus Quelle B.
- `system/gui/static/`: ausschließlich `css/`, `js/`, `favicon.ico` (keine HTML-Quelle).
- Verweise auf `/token-dashboard`: `system/gui/static/js/device-fetch.js:40`,
  `chat.html:797`, `daemon.html:781`, `inbox.html:574`, `kontakte.html:544`,
  `unified_dashboard.html:734`, `web/src/pages/artefakte.astro:153`,
  `web/src/pages/governance/logs.astro:94`.
- Server-Routen: `system/gui/server.py:1662` (Route in Liste),
  `:5781-5784` (`GUI_DIR/unified_dashboard.html`),
  `:6712-6718` (`GET /token-dashboard` aus `TEMPLATES_DIR/token-dashboard.html`).
- Activity-Dashboard: `system/gui/activity_dashboard.py:8` delegiert an
  `from ocean_gui_shell import render_activity_dashboard as _render`; `:27,32,37` API
  (`get_activity_dashboard_template`, `render_activity_dashboard`, `DEFAULT_BRANDING`,
  `TEMPLATE_PATH`); `system/gui/__init__.py:14-17,35,38` re-exportiert die Symbole.
- Planung: `docs/architecture/DOMAINS-DASHBOARDS-PLAN-v1.md:1-33` — Task #1677, M5 nur
  Planung, vier Einzel-Dashboards, `/api/domains/installed` hardcodiert,
  Slot-Architektur v2 `/domains` + `/domains/{id}`.
- Nachweispflicht: `OCEAN-TRANSFER-PLAN.md:11-18,22` — Nachweis je Fähigkeitsschnitt,
  Altteile erst nach Parität in `DEPRICATED.md`, Release v3.15.0.

## 7. Negativbefund

- **`ki-center.html` existiert nicht** in `system/gui/` (weder in `templates/` noch in
  `static/`). Die SACKGASSEN-Annahme aus dem Vorgängerzettel bzw. aus #2153 ist damit
  widerlegt; es wird kein `ki-center.html` als Quelle geführt.

## 8. Grenzen dieses Belegs

- **Keine SHA-256-Berechnung** der Inventur selbst: `execute_command` ist in dieser
  Umgebung auf `pytest`/`unittest`/`compileall` beschränkt; `file_info` liefert nur Größe
  und Zeitstempel (`kit_manifest.json` = 496 B), keinen Hash. Die einzigen belastbaren
  Hashes in diesem Beleg sind **übernommene Quellwerte** aus Manifest, Consumer und
  Receipt — nicht nachgerechnet.
- Keine Aussage über den **Live-Installationszustand** (vgl. Quelle C, Z. 17).
- Keine Umsetzung der Konsolidierung; kein PR, kein Merge in diesem Beleg.

## 9. Offene Folgearbeit

1. Konsolidierung der Generatoren/Pages/Verweise auf die fünf Quellen (A–E) umsetzen.
2. Neuer Deployment-Receipt für den Pin-Stand 0.2.30 / `eb0251ac…` (schließt die
   Divergenz aus Abschnitt 4).
3. Prüfpfad für SHA-256-Berechnung außerhalb des `pytest`-Whitelists bereitstellen,
   damit Inventarbelege reproduzierbar hashbar sind.
4. #2153 als **unaccepted/stale** führen, nicht als Abnahmequelle.

## 10. Kanonischer Readback — Korrektur-76-Stand

- **Kanonischer #2021-Readback gelungen** via `task_manage detail 2021`: status
  `pending`, result_correction_request_id `76`, task_version
  `1955963d1e86fcfb1073a6bdb944b6e878168bbe44b47b05aa64d81b06ad919c`.
- **Kanonischer #2153-Readback gescheitert**: Task-API-Sperre im gebundenen Lauf
  („Im gebundenen Lauf nur eigene ID lesbar"); #2153 daher nur aus dem
  Korrekturtext als **unaccepted/stale** behandelt.
- Rest ausgelagert in Folgetask **#4184** (Dashboardkonsolidierung Rest;
  depends_on 2021).
