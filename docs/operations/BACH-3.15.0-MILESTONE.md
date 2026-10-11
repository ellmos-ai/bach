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
3. Verwendete GUI-Bytes gegen den veröffentlichten Pin prüfen; sämtliche 25 HTML-Routen und ihre etablierten Tab-Aliase über den realen BACH-Server lesen. Eine Pfadliste allein genügt nicht als Funktionsnachweis.
4. Vor dem Mac-Deploy Host, Konfiguration, Locks, Dirty State, Datenhoheit, Taskleases und Toolgrenzen prüfen. Bestehende private Daten sowie fremde Dateien erhalten; Code und GUI-Pin sichern. Task #2102 bleibt bei ungeklärten Toolwirkungen zur Prüfung blockiert.
5. Nach kontrolliertem Reload den tatsächlichen BACH-Commit, GUI-Pin, Manifest, Seiten und Assets am Mac erneut prüfen. Ein TestClient-Lauf ersetzt diesen Produktivnachweis nicht. Deployment startet keine Cloudworker.
6. Erst danach den geprüften BACH-Commit als annotierten `v3.15.0` taggen und veröffentlichen. Titel: **BACH fließt ins Meer – gemeinsame GUI**. Releasebelege müssen Quellcommit, GUI-Pin, Prüfumfang, Produktivreadback und verbleibende Gates nennen.
7. Task #2071, Zuarbeit #2099, Masterticket und OneDrive-Dokumentation anhand dieser Belege nachführen. Erst bei erfüllten Kriterien den Meilensteintask abschließen.

## Weiterführung und offene Grenzen

- Cloud/Free/Buddha benötigen gesonderte produktive Aufgaben-, Tool-, Ergebnis- und Reviewnachweise. Sourceprüfungen oder ein Threadstatus ersetzen diese Abnahme nicht.
- Ocean-Pin und Neukomposition folgen dem gemeinsamen Release; nutzergebundene Cutover- und Installer-Gates bleiben erhalten.
- Die Desktop-App ist ein eigenes Vorhaben. Die Web-GUI und das Tauri-2-Konzept sind kein bereits gebautes Desktop-Gerüst.
- Modularisierung erfolgt anschließend pro Fähigkeit nach [OCEAN-TRANSFER-PLAN.md](../../OCEAN-TRANSFER-PLAN.md). Die 64 Folgepakete werden nicht pauschal freigegeben.
- Ersatz, Endpunktparität, Probleme, Rollback und endgültige Entfernung werden in [DEPRICATED.md](../../DEPRICATED.md) geführt.
- Gemeinsame GUI-/Moduldokumentation bleibt upstream; BACH ergänzt seine CLI-, API- und Betriebsverträge. Die empirischen Dokumentationsworkflows und Tasks #2031/#2032/#2035 bleiben für die laufende Nachführung zuständig.
