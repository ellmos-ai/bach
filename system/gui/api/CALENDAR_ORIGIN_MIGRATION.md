# Kalenderherkunft: additive Migration

`assistant_calendar.dist_type` bezeichnet die Verteilung einer Datei oder eines
Datensatzes. Daraus lässt sich kein Nutzer- oder Systemtermin ableiten. Bestehende
Kalenderzeilen bleiben deshalb `unknown`. Neue Termine aus der GUI erhalten
serverseitig `user`; ein Aufrufer kann `system` nicht per POST behaupten.

Vor dem produktiven Einsatz muss der Integrator die tatsächlich von
`hub.bach_paths.BACH_DB` verwendete SQLite-Datenbank identifizieren, mit der
SQLite-Backup-API konsistent sichern und die folgenden Schritte in einer
Transaktion durchführen. Eine Datei- oder WAL-Kopie ist kein Ersatz für das
SQLite-Backup. Die GUI führt diese Migration bei GET nicht selbst aus.

1. `PRAGMA table_info(assistant_calendar)` lesen. Existiert die Tabelle nicht,
   erstellt der erste autorisierte POST das aktuelle Schema. Ist
   `event_origin` bereits vorhanden, nur den zulässigen Spaltentyp und die
   Werte read-only prüfen; keine zweite Spalte anlegen.
2. Für ein vorhandenes Altschema genau einmal ausführen:

   ```sql
   BEGIN IMMEDIATE;
   ALTER TABLE assistant_calendar
     ADD COLUMN event_origin TEXT NOT NULL DEFAULT 'unknown';
   COMMIT;
   ```

3. Per `PRAGMA table_info` und `SELECT event_origin, COUNT(*) ... GROUP BY
   event_origin` nachlesen. Alle historischen Zeilen müssen `unknown` sein;
   Zeilenzahl vor und nach dem Schritt muss gleich bleiben.
4. Erst nach dem Readback die neue POST-Oberfläche freigeben. Bleibt die
   Spalte aus, antwortet POST ausdrücklich mit HTTP 503. GET liefert alte
   Einträge weiter als „Herkunft unbekannt“.

Ein echter Systemtermin braucht künftig einen eigenen vertrauenswürdigen
Schreibpfad mit belegtem Akteur und Herkunft. Die GUI legt keinen solchen
Termin per öffentlichem POST an.
