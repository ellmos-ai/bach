# Worker-Ergebnisse und getrennte Abnahme

Implementierungsentwurf für Task #1973. Laufzeitabnahme und Veröffentlichung
stehen aus. Ein gespeichertes Ergebnis belegt eine Abgabe; seine fachliche
Richtigkeit ist damit noch nicht geprüft.

## Native Zulassung

Jede `WorkerLeaseBinding` übergibt bei Acquire ihre `result_generation`, auch bei
expliziten Task-IDs und privaten Creator-Delegationen einer Staffel. Der Lead
bindet sie in `claim_result_generation`. Der Client verlangt die korrelierte
Bestätigung. Eine alte Gegenstelle ohne diesen Vertrag erlaubt keinen Lauf.

Diese Bindung ist nach Acquire unveränderlich. Auf einem solchen Lease lehnen
die kanonischen Release- und Decompose-Endpunkte `outcome=done` beziehungsweise
`close_parent=true` ab, auch bevor ein Ergebnis existiert. Der generische
Task-Audit-Pfad prüft dieselbe Grenze. Manuelle Leases bleiben getrennt: Die
bereits vorhandenen manuellen und PR-Review-Verträge werden weiter unterstützt.
Ein Modell erhält weder den privaten Lease noch ein Recht, diese Einordnung zu
ändern. `automatic=false` ist keine Ausnahme für native Worker.

## Ergebnisabgabe

`task_manage(action="submit_result", task_id=..., result="...")` verlangt ein
konkretes, nicht leeres Ergebnis bis 3000 Zeichen. `done` und
`update(status=done|completed)` sind bei nativen Workern ausschließlich Aliase
für dieselbe Abgabe. Zusätzliche Felder wie `accepted=true` sind unzulässig.
Ein bloßes „erledigt“ oder eine fehlende Abgabe schließen keine Task ab.

Der Lead speichert in einer Transaktion Ergebnis, SHA-256, Task-Version,
Workergeneration, Fence und Audit-Ereignis in `worker_task_results`; er setzt
Review und gibt die Lease frei. Der ACK ist typisiert und korreliert. Ein
verlorener ACK wird ausschließlich aus einem exakt korrelierten kanonischen
Lesesnapshot rekonstruiert; die Mutation wird nicht wiederholt. Ohne diese
Klärung bleibt der Ergebniszustand unbestätigt. Veraltete
Abgaben bleiben ausschließlich `late_result`; sie begründen keine Abnahme.

Eine bestätigte Zerlegung legt mit `close_parent=false` Teilaufgaben an. Sie ist
Fortschritt, kein fertiges Parent-Ergebnis. Der Worker kann den Plan mit den
bestätigten Kind-IDs anschließend zur Prüfung abgeben.

## Persönliche Abnahme

`GET /api/tasks/{id}/result` liefert einen konsistenten kanonischen Lesesnapshot:
Ergebnis, aktuellen Task-Status, Inhaltsversion und monotone Statusrevision.
Frühere `bach.task-result.v1`-Notizen bleiben zur Einsicht verfügbar; sie erhalten
keinen rückwirkenden Abnahmenachweis.

`POST /api/tasks/{id}/result/accept` verlangt Geräteauth und zusätzlich ein
separates Operator-Credential im Header `X-BACH-Result-Operator`. Der Body bindet
`result_id`, `result_sha256`, `task_version` und `status_revision`. Die tatsächliche
Abnahmeidentität wird innerhalb derselben Schreibtransaktion aus aktiven Geräten
und `task_result_operators` bestimmt. Ein Body-Feld oder Modelltext kann sie nicht
setzen. Widerruf und Abnahme sind dadurch serialisiert.

Vorhandene Worker-/Tray-Credentials, Loopback und der allgemeine Geräte-
Registrierungsendpunkt erhalten kein Abnahmerecht. Die lokal autorisierte
Einrichtung verwendet `gui.device_auth.create_task_result_operator(name)` und
erzeugt immer ein neues Credential. Dieses gehört ausschließlich zum Operator,
nicht in `BACH_DEVICE_TOKEN`, `TaskLeaseClient`, Modellkontext, Logs oder Repos.
Der Browser merkt es nur für den aktuellen Tab. Die Bereitstellung beim Nutzer
ist eine gesonderte offene Integrationsaufgabe; kein Schlüssel wird implizit
geteilt oder als eingerichtet ausgegeben.

Die Abnahme setzt Done und speichert eine korrelierte Entscheidung mit
Audit-Ereignis-ID. Ein erneutes Done über PUT/CLI ist kein Ersatz. Neue Inhalte,
ein neuer Fence oder ein späterer Statuswechsel entwerten die frühere Abnahme.
Die Statusrevision verhindert auch Done → Review → Done mit veralteter Abnahme.

## Status und Staffelübergabe

`submitted_task_ids` sind historische Abgaben. `completed_task_ids` enthalten
ausschließlich aktuell abgenommene, korrelierte Ergebnisse. Ein fehlgeschlagener
Readback ergibt `results_verified=false`; gespeicherte Erfolgs-ACKs ersetzen die
Quelle nicht. Unter dem Controllerlock wird nur der physische Zustand projiziert.
Binding-/DB-/HTTP-Abfragen gehören außerhalb sämtlicher Controllerlock-Ebenen.

MarbleRun behält bei ausstehender Abnahme oder unbestätigter Ergebnisquelle den
gleichen Handle und wartet. BACH projiziert den Wartegrund separat als
`result_wait`. Nach Abnahme kann derselbe Schritt fortsetzen. Ein ausdrücklicher,
korrelierter Stop mit physischem Ende bleibt terminal, auch während Review.
Eine Übergabe verlangt außerdem das physische Ende genau dieser Generation
und einen frischen kanonischen Abnahmenachweis. Vor der Übergabe zurückgezogene
Abnahmen begründen keine erfolgreiche Staffelübergabe. Bereits ausgeführte
Folgeschritte werden durch einen späteren Widerruf nicht rückwirkend aufgehoben.

## Noch offene Abnahme

- Bestehende Regressionserwartungen von automatischem Done auf Review umstellen.
- Operator-Provisionierung und Ergebnisansicht über echte Geräteauth abnehmen.
- Quellenfehler, Ergebnisänderung, Status-ABA, verlorene ACKs und direkten
  Lease-/Alias-/Parent-Abschluss prüfen.
- Staffel warten, abnehmen, fortsetzen und während Review ausdrücklich stoppen.
- Unabhängiges Review des endgültigen Heads, CI, Merge und Mac-Deployment.
