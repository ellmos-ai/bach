# Rest zu #3746: Testbeleg, Doku-Korrektur, writer.py — Task #4178

Arbeitsort: Worktree `task-4178` (Branch `bach-task/4178`). Kein Zugriff auf den
Worktree `task-3746`; alle Aussagen beziehen sich auf diesen Arbeitsbaum.

## Testbeleg

Der Lease-/Star-Testbestand liegt in `system/tests/test_resource_lease.py`
(Importe: `hub._services.lease_core`, `resource_lease`, `resource_lease_client`).

    python -m pytest -q -- system/tests/test_resource_lease.py
    48 passed, 1 warning in 10.20s   (Exitcode 0)

Die Warnung betrifft `PytestConfigWarning: Unknown config option: confcutdir` und
ist von dieser Task unberührt.

## Doku-Korrektur

Im #3746-Kontext wurde die Testdatei als `test_star_lease.py` genannt. Dieser Name
existiert nicht; korrekt ist `test_resource_lease.py` (Beleg oben). Eine Suche nach
`star_lease` in `docs/` und im Teilbereich `system/` lieferte keinen Treffer, die
Fehlbenennung steht also nur im Task-/Berichtskontext und nicht im Repository.

## Nicht vorhandene Integrationsgrundlagen

- `system/hub/star_lease_INTEGRATION.md` existiert nicht. Es wird keine solche
  Datei angelegt, solange ihr Inhalt nicht aus einer realen Quelle stammt.
- `system/hub/writer.py` existiert nicht; im Modul vorhanden ist
  `domain_writer_gate.py`. Eine writer.py-Integration ist damit gegen die reale
  Quelle aus dem #3743-Umfeld und nur nach Polarstern-Freigabe umzusetzen. Sie ist
  hier ausdrücklich **nicht** erledigt.

## PR-Anlage

Der PR für den Branch `bach-task/3746` ist aus diesem Arbeitsbaum nicht anlegbar
(fremder Worktree gesperrt). Über `finish_task` wird ausschließlich der PR für
`bach-task/4178` erzeugt; ein PR für #3746 bleibt offener Folgeschritt.

## Grenzen

Keine Änderung an Lease-Kernmodulen, Migrationen oder Laufzeitpfaden. Nur diese
Befunddatei ist neu; der Testlauf wurde unverändert auf dem Bestand ausgeführt.

## Update Lauf 2, 2026-11-15

finish_task-Läufe anfangs an PR-Titellimit ("GraphQL: Title is too long (maximum
is 256 characters)") bzw. an fehlender Bestätigung ("Worktree-Ergebnis oder
Taskänderung nicht bestätigt") gescheitert; erneuter Versuch mit kurzem
message-Text. Diese Ergänzung stellt sicher, dass der Commit Inhalt trägt.
