# Native Taskmaster-Vorlagen v1

## Vertrag

Die beiden fachlichen Namen `taskmaster-maintainer` und
`taskmaster-operator` sind zugleich ihre Rollenkennungen. Sie werden im
vorhandenen `seed_default_blueprints` ergänzt. Die Datenbank vergibt numerische
IDs; es gibt keine reservierten historischen Nummern.

| Name / Rolle | Skills | Zweck |
| --- | --- | --- |
| taskmaster-maintainer | dedup, project-docs, maintenance | Freigegebene Projekt- und Dokumentationsbestände pflegen |
| taskmaster-operator | scheduling, budgeting, review | Aufgaben, Budgets, Reihenfolge und Abnahme koordinieren |

Beide sind `kind=agent`, `is_template=1`, `is_materialized=0` und beginnen
bei `version=1`. Der Bootstrap materialisiert oder startet keinen Agenten.
Governance erlaubt zunächst nur `read_files` und `search_content`.
Eine spätere Instanz benötigt weiterhin ihre eigenen Berechtigungen und Freigaben.
Skillkennungen sind deklarierte Anforderungen; ihre Verfügbarkeit oder Ausführung
ist damit nicht nachgewiesen. Der Operator führt keine eigene Claimqueue.
Bestehende coding-agent-, taskmaster-writer- und taskmaster-solver-Identitäten
werden weder angelegt noch verändert.

## Additive Übernahme

Die bestehende Schemafunktion und der bestehende benannte
`INSERT OR IGNORE`-Seedvertrag bleiben erhalten. Bestehende Namen,
Revisionen, Zuordnungen und Inhalte werden nicht überschrieben. Auch ein
gleichnamiger Benutzereintrag bleibt erhalten: Ein solcher Konflikt muss im
Readback erkannt und gesondert geklärt werden; er ist kein erfolgreicher
Vorlagennachweis.

Nach regulärer Integration der Quelle und gesondert freigegebener Bereitstellung
auf dem laufenden BACH ist die vorhandene, authentifizierte API zu verwenden:

1. `GET /api/agent-studio/blueprints`: Schemaantwort,
   `configuration_version`, vorhandene Namen, Rollen und Revisionen sichern.
2. Prüfen, ob die laufende Quelle diese beiden Seeds tatsächlich enthält.
3. `POST /api/agent-studio/bootstrap`: vorhandener expliziter Bootstrap;
   kein SQL gegen die Live-Datenbank und kein impliziter Schreibzugriff beim GET.
4. Mit einem neuen `GET /api/agent-studio/blueprints` beide fachlichen Namen
   und Rollen, Skills, `kind`, Vorlagen-/Materialisierungsflags und Versionen
   auslesen. Für jeden Eintrag die tatsächlich vergebene ID dokumentieren.
5. Bestehende Einträge anhand ihrer zuvor gelesenen ID, Version und Inhalte
   abgleichen. Bootstrap erneut auszuführen darf diese nicht verändern.

Ein bereits vorhandener höherer Versionsstand wird erhalten. Ein unerwarteter
Inhalt oder Benutzereintrag unter demselben Namen darf nicht durch Löschen,
Umbenennen oder Zurücksetzen auf Version 1 repariert werden.

## Abnahmegrenze

Ein Commit, PR oder erfolgreicher Bootstrap-Aufruf allein schließt Aufgabe 2325
nicht ab. Erforderlich ist der native Readback beider Vorlagen aus dem tatsächlich
laufenden System. Eine Konfiguration belegt keinen Agentenlauf. Diese Änderung
enthält keinen Dienstneustart, keine Materialisierung, keinen Workerstart und
keine separate Taskmaster- oder GUI-Datenquelle.
