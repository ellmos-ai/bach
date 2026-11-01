# Release-Audit 2026-10-20

## Ausgangsstand

- Frischer Worktree von `origin/main` `015550b351c953f8944a1b54deeb71218784889f`, Repository `ellmos-ai/bach`.
- PR #415 ist seit dem 16. Oktober integriert. Die dort behobenen persönlichen Pfade und generierten Gardener-Ausgaben werden nicht erneut verändert.
- Paketversion `3.15.0` bleibt ein Releasekandidat. GitHub Latest ist `v3.14.0`; ein Remote-Tag `v3.15.0` existiert beim Audit nicht.
- Die Main-Workflows `tests` und `CodeQL` sind für den genannten Ausgangscommit erfolgreich. GitHub meldet beim Audit keine offenen Dependabot-Alerts.

## Befund und Korrektur

Die Ignore-Regel `PRIVATE.txt` verhinderte, dass eine Veröffentlichungssperre regulär versioniert und in anderen Klonen sichtbar wird. Die aktuelle gemeinsame Gate-Regel verlangt die Versionierung von `PRIVATE.txt` und `PUBLIC.txt`. Die veraltete Ignore-Regel wurde entfernt und durch einen erklärenden Kommentar ersetzt. Es wird kein Gate angelegt, aufgehoben oder inhaltlich verändert.

Der Meilensteintext führte noch GUI 0.2.19 mit 25 Seiten, während beide Verbraucher-Manifeste GUI 0.2.24 mit 26 Seiten deklarieren. Der Vertrag benennt jetzt den tatsächlichen Quellpin und kennzeichnet den ursprünglichen Stand als historisch. GitHub meldet für Release und Tag `v0.2.24` HTTP 404; die GUI-Release-Liste endet bei `v0.2.23`. Das fehlende Releaseartefakt ist ein zusätzlicher konkreter Release-Blocker; der Quellpin wird hier weder zurückgesetzt noch als installiert bestätigt.

## Verifikation

- Ausgangsbaum: 4172 Git-Blobs. 4008 unveränderte Blobs übernehmen die dokumentierte Privacy-Prüfung vom 14./16. Oktober; alle 164 geänderten UTF-8-Blobs wurden erneut geprüft und ihre Git-Hashes verifiziert. Das Delta enthält keine Binärdateien.
- Die neun unveränderten Bild-/Icondateien sind über ihre Blobidentität erfasst; ihre Inhalte wurden nicht auf persönliche Informationen geprüft.
- Zwei Secret-Kandidaten sind synthetische Sicherheitsfixtures: ein bloßer Private-Key-Header ohne Schlüsselmaterial und der ausdrücklich als Testsentinel bezeichnete Wert in `test_readiness_is_not_credential_clearance`. Kein neuer echter Credential- oder persönlicher Pfadbefund in diesem Prüfumfang.
- Gitignore-Proben: 26/26 sensible Pfade bleiben ausgeschlossen, 9/9 Quell-, Manifest- und Gate-Dateien werden berücksichtigt. Die beiden Gate-Namen sind am Root und in einem normalen Unterverzeichnis erfasst.
- Der bereits versionierte Dateisatz enthält keine Ignore-Treffer. Die Änderung betrifft ausschließlich Gitignore und Release-Dokumentation; keine Laufzeitlogik wurde verändert.
- Lokaler GUI-Pin-/Integritäts- und Seitenvertrag: `22 passed, 1 skipped` unter Windows/Python 3.12; der Symlinktest wird bei fehlender Hostberechtigung übersprungen. Die Tests verwenden isolierte Datenpfade und bestätigen keine produktive GUI-Installation. `git diff --check` ist erfolgreich; die Editable-Quellenprüfung meldet 0 Abweichungen.

## Offene Release-Gates

- Maßgeblich bleibt der [Meilensteinvertrag](BACH-3.15.0-MILESTONE.md): fehlendes GUI-Release 0.2.24 regulär bereitstellen oder einen geprüften Pin integrieren; anschließend alle erwarteten Seiten, Aliase, Manifeste und Assets am realen Mac-Deployment prüfen; Task #2071 anhand dieser Produktivbelege abnehmen. Quellcode- und CI-Ergebnisse ersetzen diesen Nachweis nicht.
- `BACH-SEC-ROTATE-01`: Der redigierte Verbraucher-, Ersatz- und Alt-Token-Widerrufbeleg bleibt offen. Dieser Audit verändert keine produktiven Credentials.
- Diese Korrektur wird über einen eigenen Branch und PR zur regulären Integration eingereicht. Kein Release-Tag; fremde Arbeitsbäume und die OneDrive-Projektion werden durch diese Korrektur nicht übernommen.
