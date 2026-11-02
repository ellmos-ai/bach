# BACH 3.15.0 – Readback-Dokumentation GUI-Pin (Task #3718)

Sollort lt. Task: docs/operations/BACH-3.15.0-READBACK-3718.md · Worktree task-3718

| Feld | Wert |
| --- | --- |
| Task | #3718 (Readback-Doku GUI-Pin) |
| Folgetask | #3720 (Deploy/Tag-Rest: Mac-Deploy, installed_dist verified, annotierter Tag v3.15.0, autoritative 39er-Liste) |
| Meilenstein | BACH 3.15.0 – docs/operations/BACH-3.15.0-MILESTONE.md |
| Belegzeitpunkt | 2026-11-01T12:13:11Z |
| Server | http://127.0.0.1:8000 |
| Quellen | gui_readback_3718.py (450 Z.), gui_readback_3718_result.json (96 Z.), BACH-3.15.0-MILESTONE.md, OCEAN-TRANSFER-PLAN.md |
| PR | https://github.com/ellmos-ai/bach/pull/623 |

## 1 Pin-Abgleich (MILESTONE :17–25 vs. Server)

Erwartet (expected_gui_pin): Version 0.2.30, Commit eb0251ac4b85574087ad934611d19dc3df1f9c4c, page_count 39.

| Prüfung | Erwartet | Erhalten | Status |
| --- | --- | --- | --- |
| Version | 0.2.30 | 0.2.30 | OK |
| Pin (pinned_source_commit) | eb0251ac4b85574087ad934611d19dc3df1f9c4c | eb0251ac4b85574087ad934611d19dc3df1f9c4c | OK |
| Schema kit-manifest | ellmos-system-gui.kit-manifest.v1 | ellmos-system-gui.kit-manifest.v1 | OK |
| installed_dist.installed | true | true | OK |
| installed_dist.verified | true | false | Differenz → #3720 |
| installed_dist.reason_code | – | commit_mismatch | Differenz → #3720 |
| installed_dist.source_commit | Pin-Commit | null | Differenz → #3720 |
| installed_dist.page_count (Dist) | 375 | 375 | OK |
| Routenziel (HTML) | 39 lt. MILESTONE | 38 prüfbar | dokumentiert (Abschnitt 5) |

Pin-Träger: system/gui/kit_manifest.json (11 Z.), system/gui/gui-consumer.v1.json (18 Z.).

Fazit: Alle harten Assertions bestanden (Version, Pin, Schema, installed, page_count 375). `verified=false (commit_mismatch, source_commit=None)` ist die dokumentierte Deploy-Abweichung: Mac-Deploy/Tag v3.15.0 ausstehend – Rest via #3720.

## 2 API-Endpunkte

| Endpunkt | Status | Bytes | Anmerkung |
| --- | --- | --- | --- |
| /api/gui/kit-manifest | 200 | 696 | pinned_source_commit=eb0251ac… (Pin OK) |
| /api/gui/capabilities | 200 | 53948 | schema ellmos.gui.capabilities.v1, pages_type=list, pages_count=24 |
| /dist-manifest.json | 401 | – | „unerwarteter Status 401 (Soft, kein Hard-Fail); autoritative 39er-Liste ohne Auth nicht lesbar" (Abschnitt 4) |

## 3 HTML-Routen (38/38 Status 200)

Quelle routes_plan (result.json Z.23–29): count 38, html_200 38/38; Herkunft 24 PAGE_READS + 12 Legacy.

> „Ziel 39 lt. MILESTONE; ohne Auth pruefbar 38; Differenz dokumentiert"

| Route | Erwartet | Erhalten | Bytes | Art |
| --- | --- | --- | --- | --- |
| / | 200 | 200 | 70512 | page_root |
| /tasks | 200 | 200 | 83116 | page |
| /agenten/running | 200 | 200 | 173240 | page |
| /agenten/blueprints | 200 | 200 | 79529 | page |
| /agenten/subscription-agents | 200 | 200 | 68171 | page |
| /agenten/fabrika | 200 | 200 | 63625 | page |
| /agenten/marbolerun | 200 | 200 | 66518 | page |
| /agenten/sessions | 200 | 200 | 72023 | page |
| /skills | 200 | 200 | 67620 | page |
| /skills/plugins | 200 | 200 | 63678 | page |
| /skills/mcp | 200 | 200 | 65644 | page |
| /skills/software | 200 | 200 | 63955 | page |
| /skills/ocean | 200 | 200 | 65600 | page |
| /user-inbox | 200 | 200 | 57527 | page |
| /memory | 200 | 200 | 149604 | page |
| /domains | 200 | 200 | 63686 | page |
| /routinen | 200 | 200 | 69191 | page |
| /artefakte | 200 | 200 | 68998 | page |
| /governance | 200 | 200 | 82440 | page |
| /governance/logs | 200 | 200 | 63563 | page |
| /governance/usecases | 200 | 200 | 64340 | page |
| /governance/funk | 200 | 200 | 61225 | page |
| /life | 200 | 200 | 121262 | page |
| /settings | 200 | 200 | 121134 | page |
| /system?tab=ocean | 200 | 200 | 61844 | tab_alias |
| /daemon?tab=chains | 200 | 200 | 68400 | tab_alias |
| /ati | 200 | 200 | 47694 | page |
| /chat | 200 | 200 | 87852 | page |
| /denkarium | 200 | 200 | 68706 | page |
| /financial | 200 | 200 | 116610 | page |
| /gesundheit | 200 | 200 | 7545 | page |
| /help | 200 | 200 | 69736 | page |
| /kontakte | 200 | 200 | 34709 | page |
| /maintenance | 200 | 200 | 63681 | page |
| /persoenlich | 200 | 200 | 8979 | page |
| /steuer | 200 | 200 | 23764 | page |
| /tools | 200 | 200 | 66140 | page |
| /inbox | 200 | 200 | 62832 | page |

Exakte Routennamen, Bytes und sha256 je Route: autoritative Quelle gui_readback_3718_result.json Z.57–94.

## 4 dist-manifest 401 statt erwartetem 404

Das Prüfskript erwartet /dist-manifest.json mit 404 (Soft, kein Hard-Fail). Tatsächlich antwortete der Endpunkt mit 401: „unerwarteter Status 401 (Soft, kein Hard-Fail); autoritative 39er-Liste ohne Auth nicht lesbar". Ein 200 hätte serverseitig die Hard-Asserts ausgelöst (Pin, page_count, 39er-Liste); 401/404 bleibt soft. Kein Funktionsfehler, aber Ursache für die Messgrenze in Abschnitt 5.

## 5 Differenz Routenziel 39 vs. 38 prüfbare Routen

MILESTONE :35 fordert die Abnahme von 39 Routen plus Tab-Aliase über den realen Server. Ohne Auth prüfbar: 38 dokumentierte Routen (24 PAGE_READS + 12 Legacy + 2 Tab-Aliase). Die autoritative 39er-Liste ist nicht lesbar (dist-manifest 401, page-reads.v1.json nicht im Repo). Wörtlich aus result.json (reason 2):

> „INFO: Routenziel 39 lt. MILESTONE; ohne Auth pruefbar: 38 dokumentierte Routen (24 PAGE_READS + 12 Legacy + 2 Tab-Aliase); autoritative 39er-Liste nicht lesbar (dist-manifest 401, page-reads.v1.json nicht im Repo) → Differenz dokumentiert"

Einordnung: Messgrenze, kein Funktionsfehler – alle 38 geprüften Routen antworten 200.

## 6 Abweichungen (5 Punkte)

1. installed_dist abweichend: verified=false, reason_code=commit_mismatch, source_commit=None – Mac-Deploy/Tag v3.15.0 ausstehend (Rest via #3720).
2. Doku-Stand: MILESTONE :27 „Doku auf 0.2.29 nachgezogen" – nicht 0.2.30.
3. /dist-manifest.json antwortet 401 statt erwartetem 404 (Soft).
4. Routen 39 lt. MILESTONE vs. 38 ohne Auth prüfbar (Abschnitt 5).
5. OCEAN-TRANSFER-PLAN.md :84 „bindet GUI 0.2.19/e909dd92" – veraltet gegenüber Pin 0.2.30.

## 7 Offene Punkte → Task #3720

- Mac-Deploy durchführen; installed_dist verified=true erreichen (Readback am Mac nach kontrolliertem Reload, MILESTONE :37).
- Erst danach annotierter Tag v3.15.0 „BACH fließt ins Meer – gemeinsame GUI" (MILESTONE :38).
- Autoritative 39er-Liste lesbar machen (dist-manifest bzw. page-reads.v1.json) und Differenz 39/38 aufklären.
- #2102 blockiert Tag/Release – offen lassen, nicht eigenmächtig schließen.
- Keine Modularisierung (MILESTONE :47).

## 8 Testbeleg

`python -m unittest -v gui_readback_3718` im Worktree-Root: Ran 4 tests in 0.503s, OK (Exitcode 0). Test 03 meldet die workflowhooker-Seam fail-closed (cli._run_active_checks fehlt), Suite läuft OK. Nur stdlib verwendet; Vorläuferläufe identisch.

## 9 Verdict: NOT-OK

summary: 43 Einträge (api 2, dist_manifest 1, routes_plan 2, page_root 1, page 35, tab_alias 2); Status 200=40, 401=1, None=2. Beide reasons wörtlich aus result.json (Z.48–49):

> „installed_dist abweichend (verified=False, reason_code='commit_mismatch', source_commit=None) — dokumentierte Deploy-Abweichung: Mac-Deploy/Tag v3.15.0 ausstehend (Rest via #3720)"

> „INFO: Routenziel 39 lt. MILESTONE; ohne Auth pruefbar: 38 dokumentierte Routen (24 PAGE_READS + 12 Legacy + 2 Tab-Aliase); autoritative 39er-Liste nicht lesbar (dist-manifest 401, page-reads.v1.json nicht im Repo) → Differenz dokumentiert"

Einordnung: Alle harten Assertions bestanden (Pin 0.2.30/eb0251ac…, Schema, page_count 375, 38/38 Routen 200). Beide NOT-OK-Gründe sind dokumentierte Abweichungen mit klarem Restpfad #3720, kein Hard-Fail. Stand: Messung vor Mac-Deploy.