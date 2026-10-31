# BACH 3.15.0 – BACH fließt ins Meer

Dieses Dokument definiert den Meilenstein und seine Abnahmekriterien. Versionsmetadaten im Quellstand, ein veröffentlichtes GUI-Paket und ein laufender Mac-Dienst sind getrennte Nachweise. Ein Versionswechsel allein bestätigt keinen erfolgreichen Deploy.

## Architektur des Meilensteins

- Einzige Quelle für die gemeinsame Web-GUI: `ellmos-ai/ellmos-system-gui`.
- BACH konsumiert einen festen GUI-Quellcommit und ein geprüftes Releasearchiv. Renderer, Clientskripte und Assets werden im gemeinsamen GUI-Repository weiterentwickelt.
- BACH behält seine API, Fachlogik, kanonische TaskDB und private Konfiguration. Die gemeinsame GUI besitzt diese Daten nicht.
- `system/gui/web` ist eine gekennzeichnete Übergangs-/Archivkopie. Der bestehende Rückweg für Hosts ohne Release-Konfiguration bleibt bis zu einer gesonderten Caller- und Hostabnahme erhalten.
- Ocean verwendet dieselbe Frontendquelle mit eigenen Backend-Adaptern. Der BACH-Meilenstein bestätigt noch keine vollständige Ocean-Laufzeit, keinen Installer-Grant und keinen Ocean-Cutover.

## Festes GUI-Paket

| Nachweis | Wert |
|---|---|
| Version | `0.2.30` |
| Quellcommit / Tag | `eb0251ac4b85574087ad934611d19dc3df1f9c4c` / `v0.2.30` |
| Archiv | `ellmos-system-gui-0.2.30-eb0251ac4b85.zip` |
| Archivgröße | 8.323.951 Bytes |
| Archiv-SHA-256 | `ff07b55656349da60cb18b5ead867da3f03d43d81e6964bc6448212d7412b188` |
| Distmanifest-SHA-256 | `d64c9edf8a56fac80ec4bd7c39afae956834d9b046407436a1bfe5404556e7ba` |
| Seiteninventar-SHA-256 | `d1ba46fe31da64fdf94c3f8db7656b80688ae829d3e83b0fe246dda53f253890` |
| Buildinventar | 39 HTML-Seiten; 375 Distdateien einschließlich Distmanifest |
| Pin-Status | `pinned_release` (belegt: `system/gui/gui-consumer.v1.json`, `status`), gepinnt am 2026-10-31T12:52:00Z (belegt: `system/gui/kit_manifest.json`, `pinned_at`) |

Scope-Entscheid: Der in der Planung vorgesehene Zwischenpin 0.2.27 war überholt, da das BACH-Repo bereits auf 0.2.29 steht und die Integritätstests 0.2.29 verriegeln; ein Downgrade wird nicht durchgeführt. Diese Doku ist auf 0.2.29 nachgezogen. Die Mac-Aktivierung des Deployments bleibt eine eigene offene Arbeit.

Das Seiteninventar `page-reads.v1.json` ist Bestandteil des Pakets. Die bisherige inhaltliche Beschreibung (Robotericon, Entfernung des Werkstatt-Hintergrundbildes, README-Schiffsbrückenbanner) bezog sich auf GUI 0.2.19 und wird für 0.2.29 nicht vorausgesetzt; maßgeblich sind die Upstream-Releasebelege von 0.2.29.

## Abnahme vor BACH-Tag und Veröffentlichung

1. JSON-/Hook-Ausgabekorrektur aus BACH PR #343 und GUI-Verbraucherpin aus PR #345 gegen den aktuellen Main-Stand prüfen und regulär integrieren. Unabhängige Modellprüfung und die geltenden GitHub-Regeln bleiben verbindlich.
2. Beide BACH-Paketmetadaten (`pyproject.toml`, `setup.py`) und aktuelle Root-README-Versionsangaben müssen `3.15.0` führen. Historische Versionsvergleiche, Skillvertragsversionen und ältere generierte Handbücher werden nicht pauschal umgeschrieben.
3. Verwendete GUI-Bytes gegen den veröffentlichten Pin prüfen; sämtliche 39 HTML-Routen und ihre etablierten Tab-Aliase über den realen BACH-Server lesen. Eine Pfadliste allein genügt nicht als Funktionsnachweis.
4. Vor dem Mac-Deploy Host, Konfiguration, Locks, Dirty State, Datenhoheit, Taskleases und Toolgrenzen prüfen. Bestehende private Daten sowie fremde Dateien erhalten; Code und GUI-Pin sichern. Task #2102 bleibt bei ungeklärten Toolwirkungen zur Prüfung blockiert.
5. Nach kontrolliertem Reload den tatsächlichen BACH-Commit, GUI-Pin, Manifest, Seiten und Assets am Mac erneut prüfen. Ein TestClient-Lauf ersetzt diesen Produktivnachweis nicht. Deployment startet keine Cloudworker.
6. Erst danach den geprüften BACH-Commit als annotierten `v3.15.0` taggen und veröffentlichen. Titel: **BACH fließt ins Meer – gemeinsame GUI**. Releasebelege müssen Quellcommit, GUI-Pin, Prüfumfang, Produktivreadback und verbleibende Gates nennen.
7. Task #2071, Zuarbeit #2099, Masterticket und OneDrive-Dokumentation anhand dieser Belege nachführen. Erst bei erfüllten Kriterien den Meilensteintask abschließen.

## Weiterführung und offene Grenzen

- Cloud/Free/Buddha benötigen gesonderte produktive Aufgaben-, Tool-, Ergebnis- und Reviewnachweise. Sourceprüfungen oder ein Threadstatus ersetzen diese Abnahme nicht.
- Ocean-Pin und Neukomposition folgen dem gemeinsamen Release; nutzergebundene Cutover- und Installer-Gates bleiben erhalten.
- Die Desktop-App ist ein eigenes Vorhaben. Die Web-GUI und das Tauri-2-Konzept sind kein bereits gebautes Desktop-Gerüst.
- Die Rückmodularisierung wurde durch den Nutzer am 13. Oktober 2026 offiziell gestartet. Neue Fachlogik wird direkt in passenden ellmos-/Ocean-Modulen entwickelt; BACH konsumiert die Provider. Bei einer Änderung an einer monolithischen BACH-Struktur wird die beteiligte Fähigkeit möglichst im selben Auftrag mit übertragen, auch über die ursprüngliche Einzeländerung hinaus. Umfang, Callerparität, Datenhoheit, Installer, Abnahme und Rückfall richten sich nach [OCEAN-TRANSFER-PLAN.md](../../OCEAN-TRANSFER-PLAN.md).
- Der annotierte `v3.15.0`-Release markiert den GUI-Übergang und den Beginn dieser Phase. Er bestätigt keine abgeschlossene Modularisierung. Seine Release-Abnahmen bleiben gesondert zu erfüllen; die Startentscheidung gilt bereits. Die 64 Folgepakete werden je betroffenem Fähigkeitsschnitt gesteuert.
- Ersatz, Endpunktparität, Probleme, Rollback und endgültige Entfernung werden in [DEPRICATED.md](../../DEPRICATED.md) geführt.
- Gemeinsame GUI-/Moduldokumentation bleibt upstream; BACH ergänzt seine CLI-, API- und Betriebsverträge. Die empirischen Dokumentationsworkflows und Tasks #2031/#2032/#2035 bleiben für die laufende Nachführung zuständig.
