# telemetry – lokale Zähler

## SOLL

Ein eigenständiger, netzwerkfreier Telemetriebaustein speichert ausschließlich erlaubte Counter und validierte Labels. BACH bleibt für die Auswahl seiner kanonischen UserDB zuständig. Export und vorhandene Core-Produzenten müssen dieselben Tabellen- und Labelschlüssel verwenden.

## IST

`system/hub/telemetry.py` übergibt `hub.bach_paths.BACH_DB` ausdrücklich an Report, Status und Reset. Eine abweichende oder fehlende optionale Umgebungsvariable wählt dadurch keinen anderen Store. Das Modul selbst importiert keinen BACH-Core.

Ein expliziter `db_path` (oder `BACH_DB`) bezeichnet einen vorhandenen SQLite-Store. Die Datei wird nicht neu angelegt. `increment` darf darin die Telemetrietabelle additiv vorbereiten; Report und Status lesen nur. Bei fehlendem/unlesbarem Store oder fehlendem Leseschema gibt es keinen erfolgreichen Memory-Fallback und keine Resetbestätigung. Ohne ausgewählten Store ist eigenständiger Memory-Betrieb weiterhin möglich; explizite DB-Operationen mischen oder löschen diesen Speicher nicht.

Labelschlüssel entsprechen exakt dem bisherigen `core.telemetry`-JSONformat: sortierte Schlüssel, vorhandene erlaubte Labels, normales JSON-Spacing. Neue Core-/Export-Inkremente derselben Serie landen dadurch in derselben Zeile. Vorhandene historische Zeilen werden nicht migriert oder umgeschrieben.

Report summiert pro Counter und Labelserie über UTC-Tage ab der inklusiven Grenze `date('now', '-N days')`; bei `days <= 0` gilt sieben. Der Serien-Cap gilt pro Counter und UTC-Tag: nach 200 Serien gehen neue Labelsets in outcome-bezogene Overflow-Buckets; bestehende Serien zählen weiter. Diese Buckets können zusätzlich zu den 200 regulären Serien bestehen. SQLite prüft die Grenze im Schreibvorgang. Im lokalen Memory-Prozessspeicher schützt eine gemeinsame Sperre Capprüfung und Inkrement, konsistente Report-/Status-Snapshots sowie Reset auch zwischen gewöhnlichen Threads. Das ist kein verteilter Zählerservice.

`BACH_TELEMETRY_DISABLED=1` verhindert neue Erfassung. Bestehende Zähler bleiben lesbar und können nur mit `confirm=True` bzw. CLI `--confirm` zurückgesetzt werden. Fehler beeinflussen den Aufrufer von `increment` nicht: es liefert `False`.

Synthetische Akzeptanz liegt in `system/tests/test_telemetry_export_contract.py`, ergänzt durch die unveränderten Core-Tests und die Standalone-Smokes. Der aktuelle isolierte Windows-Lauf besteht 47 Fälle ohne Skip, einschließlich des echten Bridge-/Consumerpfads und fünf gezielter Threadfälle für zwei Writer, Zählsummen, Report, Status und Reset. Die kontrollierte Zweischreiber-Probe bestätigt bei 199 vorhandenen Serien plus zwei neuen Writes genau 200 reguläre Serien, einen Overflow und 201 Ereignisse. Getestete Quelle, unabhängige Abnahme und produktive Laufzeit bleiben getrennte Belege. Kein produktiver Store, Providerstart, Export zu einem Netzservice oder Deployment gehört zu dieser Lieferung.
