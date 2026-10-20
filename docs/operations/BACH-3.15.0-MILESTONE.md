# BACH 3.15.0 – BACH fließt ins Meer

Dieses Dokument definiert den Meilenstein und seine Abnahmekriterien. Versionsmetadaten im Quellstand, ein veröffentlichtes GUI-Paket und ein laufender Mac-Dienst sind getrennte Nachweise. Ein Versionswechsel allein bestätigt keinen erfolgreichen Deploy.

## Architektur des Meilensteins

- Einzige Quelle für die gemeinsame Web-GUI: `ellmos-ai/ellmos-system-gui`.
- BACH konsumiert einen festen GUI-Quellcommit und ein geprüftes Releasearchiv. Renderer, Clientskripte und Assets werden im gemeinsamen GUI-Repository weiterentwickelt.
- BACH behält seine API, Fachlogik, kanonische TaskDB und private Konfiguration. Die gemeinsame GUI besitzt diese Daten nicht.
- `system/gui/web` ist eine gekennzeichnete Übergangs-/Archivkopie. Der bestehende Rückweg für Hosts ohne Release-Konfiguration bleibt bis zu einer gesonderten Caller- und Hostabnahme erhalten.
- Ocean verwendet dieselbe Frontendquelle mit eigenen Backend-Adaptern. Der BACH-Meilenstein bestätigt noch keine vollständige Ocean-Laufzeit, keinen Installer-Grant und keinen Ocean-Cutover.

## Aktueller Prüfstand 2026-10-20

`system/gui/gui-consumer.v1.json` und `system/gui/kit_manifest.json` deklarieren inzwischen GUI **0.2.24**, Quellcommit `ff13cccde77a997ab4d0a0173db43ff88ee3c2be`, Archiv `ellmos-system-gui-0.2.24-ff13cccde77a.zip`, Archiv-SHA-256 `ac767dcb4b129f7e97a9f8ec7de312126638f9abbbcca5fe2868370dcd40abbf` und **26 erwartete HTML-Seiten**. Das sind Quellangaben, kein Nachweis vorhandener oder installierter Releasebytes.

Beim GitHub-Readback am 20. Oktober fehlen sowohl Release als auch Tag `v0.2.24` im GUI-Repository (HTTP 404); die Release-Liste endet bei `v0.2.23`. Vor dem BACH-Tag muss der deklarierte GUI-Kandidat upstream geprüft und regulär veröffentlicht oder der Pin durch einen separat geprüften Integrationsschritt korrigiert werden. Danach sind Archiv-, Manifest-, Seiten- und Assetidentität sowie der reale Mac-Deploy nachzuweisen. Die folgenden 0.2.19-Werte dokumentieren den ursprünglichen Meilensteinstand und sind kein aktueller Abnahmebeleg.

## Historischer GUI-Pin 0.2.19

| Nachweis | Wert |
|---|---|
| Version | `0.2.19` |
| Quellcommit / Tag | `e909dd92bd2ce50710f565b44e0ccd8ddf66b9d2` / `v0.2.19` |
| Archiv | `ellmos-system-gui-0.2.19-e909dd92bd2c.zip` |
| Archivgröße | 16.016.360 Bytes |
| Archiv-SHA-256 | `66aba8081743aa4c8e44c9cea09644ce7f88cfb15365ef0822f27536decc03b4` |
| Distmanifest-SHA-256 | `6e684938bdb0078105fd96984ae5188a2bdf4ef28a98c73e9673e4dd1240f750` |
| Seiteninventar-SHA-256 | `f29759b8e0fac9daa08a77ae50622623eeac2d9f8a5e9fb67eefb5c2cd02d44d` |
| Buildinventar | 25 HTML-Seiten; 194 Distdateien einschließlich Distmanifest |

Das Seiteninventar `page-reads.v1.json` ist Bestandteil des Pakets. Der veröffentlichte GUI-Pin enthält das Robotericon und die Entfernung des Werkstatt-Hintergrundbildes. Das später veröffentlichte Schiffsbrückenbanner betrifft ausschließlich die README des GUI-Repositorys und verändert dieses Releasearchiv nicht.

## Abnahme vor BACH-Tag und Veröffentlichung

1. JSON-/Hook-Ausgabekorrektur aus BACH PR #343 und GUI-Verbraucherpin aus PR #345 gegen den aktuellen Main-Stand prüfen und regulär integrieren. Unabhängige Modellprüfung und die geltenden GitHub-Regeln bleiben verbindlich.
2. Beide BACH-Paketmetadaten (`pyproject.toml`, `setup.py`) und aktuelle Root-README-Versionsangaben müssen `3.15.0` führen. Historische Versionsvergleiche, Skillvertragsversionen und ältere generierte Handbücher werden nicht pauschal umgeschrieben.
3. Verwendete GUI-Bytes gegen den tatsächlich veröffentlichten, aktuellen Verbraucherpin prüfen; sämtliche im zugehörigen Kitmanifest erwarteten HTML-Routen (derzeit 26) und ihre etablierten Tab-Aliase über den realen BACH-Server lesen. Eine Pfadliste allein genügt nicht als Funktionsnachweis.
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
