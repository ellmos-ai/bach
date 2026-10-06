# T797: begrenzter Journal- und Lease-Autorencheckpoint

Stand: 30.09.2026. Basis: `d85ed197d65b424135069650ee89942e411e5e19`.
Keine unabhängige Abnahme und kein Nachweis vollständiger Runtime-Integration.

## Autorität und Dateiumfang

Der delegierte Restauftrag erlaubt isolierte Sicherheitskorrekturen. P-009
verlangt Wiederverwendung vorhandener Standards. Deshalb bleibt der kopierte
Nemo `action_journal.py` unverändert. Der Wrapper verwendet dessen Journal,
Hashprüfung, Undo und explizite Crash-Reconciliation. Genau drei zuvor fehlende
Standardbibliothek-Abhängigkeiten wurden aus einem belegten Gitcommit ergänzt:

| Datei unter `src/nemofold/` | SHA256 der unveränderten neuen Kopie |
| --- | --- |
| `contracts.py` | `5d3a33141e653f60d5cd3c2a9cbbe42676bb54d753949f56dab032d1d0e62dde` |
| `smart_inbox.py` | `f50a94ecbc652265b233015b6f7ff05a979e012eced8ba5f2e01ca080020386f` |
| `storage_policy.py` | `e01a5aead0b4ed76085fcd885f2ccfdea31b65f430bed3fc0e6012b07575f42a` |

Quelle: `ellmos-ai/NemoFold`, Commit
`b0545be39fc7740704f5bfe1b54458fe960dbdaf`. Der dort beobachtete MIT-Lizenztext
liegt unverändert unter `system/imported_capabilities/licenses/NemoFold/LICENSE`.
Ein separates Root-`NOTICE` wurde in diesem Gitbaum nicht gefunden. Der bestehende
Journalcode stimmt nach ausschließlich CRLF→LF-Normalisierung mit der dortigen
Quelldatei überein; diese Beobachtung ist kein Beleg des historischen Kopiercommits.

## Tatsächlicher Vertrag

- Nur `copy` und `move` mit vollständiger Vorprüfung aller Quellen, Ziele und
  erwarteten SHA256-Werte. Belegte alte Ziele werden verweigert, nicht überschrieben.
- BACH `sanitize_host_path` prüft die ausdrücklich erlaubten Wurzeln.
  Symlinks/Junctions, Hardlinks, Selbst-/Mehrfach-/Quell-Ziel-Aliase und Ressourcen
  im Journalverzeichnis werden verweigert. Elternverzeichnisse gehören zum Guardscope.
- Der Host muss einen exklusiven Lock-/Lease-Kontext für alle kontrollierten
  Pfade und das Journal bereitstellen und ihn bis zum Kontextende halten.
  Dessen frischer Eigentumscheck muss exakt `True` liefern. Fehlender, falscher
  oder unbekannter Guard ist keine Schreibfreigabe. Es gibt keinen erlaubenden
  Default und keine zusätzliche Lockimplementation. Fixtures liefern ausschließlich
  private Temp-Kontexte; die Anbindung eines echten Hosts ist noch offen.
- Persistenz- und Paket-Consumer verwenden den unveränderten Nemo-Vertrag.
  Ein unterbrochener Lauf wird ausdrücklich mit exakt demselben Plan erneut
  aufgerufen; anschließend kann Undo erfolgen. Hashdrift oder eine neue belegte
  Quelle werden vor Wiederaufnahme/Undo verweigert. Unbekannte alte Journale
  werden nicht als freigegebene Mutationsbelege akzeptiert.
- `write`, `delete`, externe Backup-Pfade und unbekannte Aktionen werden vor
  einer Mutation abgelehnt: Die alte API stellte hierfür keinen definierten
  Payload-/Autorisierungsvertrag bereit. Keine automatische Crash-Hintergrundarbeit.

## Isolierte Belege

Lease-Testcheckpoint `0e5c8fa6`: **46 fehlgeschlagen, 1 bestanden** vor Fix.
Leasefix `ecd54534`, spätere rein formale Bereinigung `169d0493`:
47 neue Fälle plus 10 vorhandene Adapterfälle bestanden ohne Skip.
Geprüft: Terminal-/Blockstatus, begrenzte TTL, unbekannte/leere Laufzeit,
gleicher Agent, vier konkurrierende Erstinitialisierungen, UUID-Fencing,
erneute Verbindung, abgelaufene Erneuerung/Freigabe und fremde Transaktionen.

Journal-Testcheckpoint `81e8e219`: **22 fehlgeschlagen, 1 bestanden** vor Fix,
einschließlich tatsächlich verlorener Move-Quelle und gemeldetem Schreib-Erfolg
ohne Schreiboperation. Der Sicherheitskontext der Fixture wurde danach an die
ausdrückliche neue API angepasst; die Datenverlustassertion blieb bestehen.

Finaler enger Lauf: **92 bestanden, null Skips** (47 Lease-, 35 Journal- und
10 ursprüngliche Adapterfälle), 7.93 Sekunden. Die Journalfälle belegen reale
Dateibytes, erneutes Öffnen, simulierten Absturz nach Mutation/vor Receipt,
Absturz während Undo, unveränderte fremde Zielbytes, erwartete Quellhashes,
unbekannte Guards, Guardverlust nach Persistenz und konkurrierende Host-Lease.
Ruff für beide Autorenadapter und beide neuen Tests meldet keine Befunde.

```text
python -m pytest system/tests/test_imported_lease_safety.py system/tests/test_imported_journal_safety.py system/tests/test_imported_capabilities.py -q
```

## Offene Gates

Keine BACH-Worker-/API-/Ocean-/Skill-Anbindung, kein Live-Dateivorgang,
kein Mac-Service-/Jobstart, kein Datenbanktransfer, keine Veröffentlichung.
Der zusätzliche dauerhafte CI-Eintrag bleibt ein eigener Autorencommit.
Eine vollständige Featurevergleichsmatrix, fehlende übrige Quellpaket-Abhängigkeiten
und der unabhängige Review stehen gesondert aus. Der Metadatenzustand der Mac-Tasks
ist kein Implementierungsbeleg. Das Vollticket bleibt offen.
