# Externe Worker und kanonische Ergebnisabnahme

Status: Vertrag in Umsetzung. Der bestehende native Abschlussweg bleibt erhalten.
Die folgenden Grundlagen allein schließen noch keine externe Aufgabe ab.
Nativer Restauftrag: BACH #2339; Commit, Push, Integration und Live-Abnahme werden
jeweils gesondert belegt.

## Herkunft und Identität

Ein außerhalb von BACHs ChatRuntime ausgeführter Codex-/Claude-Turn ist keine
native BACH-Modellanfrage. Er erhält einen eigenen Belegtyp `external_attested`.
Plattform, Tenant, Account und Quellprincipal beschreiben die externe Herkunft.
Der **globale Modellprincipal** bleibt eine getrennte, ausdrücklich vom Operator
verwaltete Zuordnung. Ein weiteres Konto oder eine andere Plattform macht dasselbe
Modell nicht zu einem unabhängigen Reviewer. Native und externe Aliasse desselben
Modells müssen denselben globalen Modellprincipal verwenden.

`operator_checked_artifacts` bedeutet, dass ein authentisierter Operator reale
Herkunftsartefakte geprüft hat. Es behauptet keine kryptografische Bestätigung
durch den Modellanbieter. Ein vom Worker selbst geposteter Modellname oder Hash
reicht nicht. Die externe Zuordnung ist versioniert; Änderungen einer anderen
Quelle verändern die Bindung der eigenen unveränderten Quelle nicht.

Der globale Katalog umfasst bestehende native Principals und ausdrücklich
registrierte externe Modelle. `model_key` benennt das im Herkunftsartefakt
beobachtete Deployment; ein Anzeigename allein ist keine Identität. Wird ein
ausdrücklich registrierter Principal ohne verbleibende native Route entfernt,
bleibt seine ID dauerhaft stillgelegt. Weder erneutes Registrieren noch eine
neue native Aliaszuordnung darf alte externe Bindungen dadurch wiederbeleben.
Für ein anderes Modell ist eine neue globale Principal-ID erforderlich.
Auch das Entfernen der letzten nativen Route legt den Principal atomar still,
sofern er nicht ausdrücklich im globalen Katalog aktiv gehalten wird. Eine
vorübergehende Änderung der Routen muss deshalb die globale Identität erhalten.

## Private Artefakte

`worker_external_evidence` speichert tatsächliche Bytes in einem privaten,
unveränderlichen Datenbankbestand und berechnet den SHA-256 selbst. Maximal
2 MiB je Artefakt; unterstützt sind JSON, JSONL und Klartext. Die Speicherung
verlangt eine bestehende gesonderte Task-Result-Operatorberechtigung. Allgemeine
Geräteanmeldung oder Workerzugriff genügt nicht. Keine Zugangsdaten importieren.

Artefaktinhalt, Pfade und private Referenzen gehören nicht in öffentliche
Task-/Result-DTOs. Ein Inhaltsabruf verlangt erneut die Operatorberechtigung.
Speicherung eines Artefakts attestiert noch keine Herkunft und erteilt keine Abnahme.

## Implementierter Belegkern

`worker_external_attestation` bietet den gesonderten Writer, DB-/History-Reader
und die aktuelle Scope-Projektion. Der Writer bindet Task-/Result-ID, Hash,
Fence, Generation, Taskversion, Status-, Submissionrevision und beide
Submission-Ereignisse. Ein eigenes privates Ergebnisartefakt muss bytegenau
mit dem vollständigen Result übereinstimmen. Für die Operatorprüfung der
Herkunft werden getrennte private Quellartefakte verlangt.

Git und Sperren werden über `snapshot_task_scope` außerhalb der
SQLite-Transaktion geprüft. Unter `BEGIN IMMEDIATE` werden anschließend
Operator, freie Lease, aktuelle Task-/Resultrevision, Identitätsbindung und
die tatsächlichen Artefaktbytes erneut geprüft. Zwei eigene History-Ereignisse
binden den externen Herkunfts- und Scope-Beleg. BACH setzt die heutige
Attestierungszeit; eine externe Quellzeit bleibt separat ausgewiesen.

Die eindeutige Kombination Plattform/Tenant/Account/Run/Turn gilt über alle
Tasks hinweg. Identische Wiederholung erzeugt bei unverändertem Scope keine
weiteren Events; ein anderer Beleg für dasselbe Result oder dieselbe Run-/Turn-
Kombination ist ein Konflikt. Bereits verknüpfte native Modellbelege können
auch bei beschädigter nativer Receipt nicht extern überschrieben werden.

Der Reader prüft Identitätsbindung, Artefaktbytes, Hashes, Events und aktuelle
Operatorgültigkeit neu. Ein Widerruf erhält die Historie, sperrt aber ihre
Verwendung zur Abnahme. Die öffentliche Projektion zeigt keine privaten
Artefakt-, Account-, Tenant-, Run-/Turn-IDs oder Dateipfade. Erst ein erneuter
Git-Vergleich erzeugt die eigene externe Ergebnisrevision. Diese Projektion
ist ausschließlich mit Daten des vertrauenswürdigen DB-Readers aufzurufen.

## Integrierte Quellenbehandlung

Der vertrauenswürdige Result-Reader unterscheidet nun `native`,
`external_attested` und `unattested`. Ein vorhandener externer Beleg bleibt
auch nach Widerruf als externe Herkunft erkennbar und darf dadurch keine
native Ersatzberechtigung erhalten. Seine native `execution` bleibt
unverfügbar; die externe Ergebnisrevision wird gesondert berechnet.

Completion-Policy und Review verarbeiten die gebundene externe Herkunft.
Ein explizit berechtigter Operator kann über die interne Servicefunktion
einen eigenen externen Review-Intent anlegen. Dieser bindet Herkunfts- und
Scope-Ereignisse, globale Modellidentität und Ergebnisrevision. Er benötigt
keinen erfundenen Autor-Slot. Der Reviewer verwendet weiterhin einen echten
nativen Ausführungsbeleg. Ein natives Alias desselben globalen Modells ist
kein unabhängiger Reviewer, auch wenn Account oder Route unterschiedlich sind.

Vor der Review-Anlage prüft der Writer erneut den freien Claim, den aktuellen
Task-/Result-/Statusstand, die Quellenbindung, die Policy und die
Operatorberechtigung. Vor einem Abschluss gelten die erneuten kanonischen
DB-Prüfungen und der bestehende abschließende Git-/Sperrvergleich. Ein
ausstehender Review hält die nächste Aufgabenübernahme des Workers nicht auf.

## Operator-API, SDK und CLI

Die Operator-Anbindung verlangt bei jedem Aufruf ein aktives Gerät und die
bestehende gesonderte Task-Result-Operatorberechtigung. Zugangsdaten werden
nicht über diese Schnittstelle ausgestellt. Private Antworten verwenden
`Cache-Control: no-store`; private Artefaktbytes und interne Receipts werden
nicht in den öffentlichen Ergebnis-Readback übernommen.

| Methode / Pfad unter `/api` | Funktion |
|---|---|
| GET/PUT `/system/worker-model-principal-catalog` | Globalen Modellkatalog lesen beziehungsweise mit Konfigurations-CAS ändern. |
| GET/PUT `/system/worker-external-principals` | Private Quellenzuordnungen lesen beziehungsweise mit Konfigurations-CAS ändern. |
| POST `/system/worker-external-artifacts` | Tatsächliche private Bytes als `media_type` und kanonisches `content_base64` speichern. |
| GET `/system/worker-external-artifacts/{artifact_id}` | Private Bytes nach erneuter Operatorprüfung abrufen. |
| POST `/tasks/{task_id}/result/external-attestation` | Strikten vollständigen Herkunftsauftrag attestieren; öffentlich projizierten Ergebnis-Readback zurückgeben. |
| POST `/tasks/{task_id}/result/external-review` | Normale Reviewaufgabe für die ausdrücklich ausgewählte externe Ergebnisrevision anlegen. |

Reviewaufträge enthalten exakt `task_id`, `result_id`, `result_sha256`,
`result_revision`, `task_version` und `status_revision` aus dem aktuellen
projizierten Ergebnis. Ein veraltetes Ziel wird zurückgewiesen. Der Writer
prüft anschließend dieselben kanonischen Daten, freie Lease, Quellenbindung,
Operatorberechtigung und Policy erneut. Die Reviewanlage startet kein Modell
und akzeptiert kein Ergebnis.

JSON-Aufträge sind auf 3 MiB begrenzt, auch bei gestreamter Übertragung ohne
Content-Length. Doppelte Schlüssel, zusätzliche Vertragsfelder und nicht
endliche Zahlen werden abgewiesen. Artefakte bleiben auf 2 MiB begrenzt.

`hub._services.worker_external_client.WorkerExternalResultClient` verwendet
einen expliziten entfernten Lead über HTTPS. HTTP ist standardmäßig nur für
Loopback zugelassen. Für eine separat geprüfte verschlüsselte Tailnet-Route
gibt es die ausdrückliche SDK-Einstellung `trusted_tailnet_http=True` und die
CLI-Option `--trusted-tailnet-http`. Die Ziel-IP muss im Tailnet-Adressbereich
liegen; die Adresse allein belegt keine verschlüsselte Route.
Umgebungs-Proxys werden nicht verwendet.
Er folgt keinen Redirects, wiederholt keine
Schreibanfragen automatisch und wechselt bei Fehlern nicht auf eine lokale DB.
Upload- und Download-Readbacks werden gegen die tatsächlichen Bytehashes geprüft.
Ein Attestierungs-ACK zählt nur bei passendem aktuellen Ergebnis, verfügbarer
Herkunft und verfügbarem Scope mit derselben Ergebnisrevision als Erfolg.
Ändert sich das Ziel nach dem Schreiben, kann der Beleg bereits gespeichert
sein, obwohl das SDK den Readback zurückweist. Dann den aktuellen Zustand
lesen und die Ursache klären; keine automatische Schreibwiederholung.

Die CLI lautet `python system/tools/worker_external_results.py`. Sie verwendet
`--lead-url` beziehungsweise `BACH_LEAD_URL`; vorhandene Berechtigungen kommen
aus `BACH_DEVICE_TOKEN` und `BACH_RESULT_OPERATOR_TOKEN` oder einer ausdrücklich
angegebenen privaten `--credentials-file` mit exakt `device_token` und
`operator_token`. Tokens gehören nicht in Befehlsargumente oder Ergebnisbelege.

Unterbefehle: `catalog`, `sources` (ohne `--payload` nur lesen),
`artifact-store DATEI --media-type text/plain`,
`artifact-read ID --output NEUE_DATEI`, `attest TASK_ID --payload AUFTRAG.json`
und `review TASK_ID --payload ZIEL.json`. Downloads erzeugen eine neue private
Datei exklusiv und überschreiben keine vorhandene Datei. Unter Windows wird
die Datei bereits mit einer geschützten NTFS-DACL für Besitzer und SYSTEM
angelegt; unter POSIX mit Modus 0600. Payloaddateien für
Herkunftsaufträge und private Quellen bleiben ebenfalls privat.

Diese Implementierung enthält noch keinen Nachweis eines tatsächlichen
externen Modelllaufs oder eines Deployments in die laufenden Mac-Dienste.

## Noch zu integrierender Abschlussweg

1. API/SDK/CLI unabhängig prüfen und Ergebnisanzeige integrieren.
2. Den tatsächlichen unabhängigen Reviewer-Modelllauf und den vollständigen
   Ablauf mit echten Herkunftsartefakten live abnehmen und auf dem Mac deployen.

Frühere Ergebnisse lassen sich nur mit real vorhandenen, nachvollziehbar zum
Result passenden Artefakten neu revalidieren. Die neue Revision ist heute
attestiert; sie erfindet weder einen früheren Modelllauf noch einen früheren
Scope-Beleg. Unabhängiger Review und normale Akzeptanzentscheidung bleiben nötig.
