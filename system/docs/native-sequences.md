# Native Ketten in BACH

MarbleRun verwendet die vorhandenen BACH-Worker, ihre Rollen, Modellanbieter und Werkzeugfreigaben. Die Modulrevision ist in `requirements.txt` gepinnt. Ein fehlendes oder anders installiertes Modul macht die Ausführung ausdrücklich unverfügbar; Kettendefinitionen bleiben lesbar und bearbeitbar.

## Zwei Modi

- **Agentenfolge:** Jeder Schritt wählt einen vorhandenen Living-Worker. Das fachliche Ergebnis eines Schritts wird an den folgenden Agenten übergeben.
- **Skillfolge:** Ein ausgewählter Agent führt je Schritt einen Skill aus. Alle Schritte verwenden dasselbe freigegebene Profil und jeweils einen neuen nativen Einzellauf. Die tatsächlichen Skill-Dateien werden beim Start mit ihrem SHA-256 gebunden.

Im Editor lassen sich Schritte durch Ziehen hinzufügen, verschieben und entfernen. Darstellung und Pfeile stammen aus dem bisherigen Agents-Board-Renderer `skills-board.js/renderFlowNodes`; die dortige reine Ausführungsanzeige wurde durch den nativen Dispatcher ersetzt. Bestehende Ketten ohne diese Bindungen bleiben als Altdefinitionen sichtbar und brauchen vor einem Start eine ausdrückliche Zuordnung.

## Laufvertrag

Ein Start legt einen unveränderlichen Plan in der kanonischen TaskDB des Leads an. Der Auftrag umfasst Kettenversion, Living-Konfiguration und Controllerinstanz. Wiederholungen derselben Startkennung erzeugen keinen zweiten Lauf. Ein weiterer Start derselben Kette wird bei laufender oder ungeklärter Ausführung abgewiesen.

Pro Schritt entstehen ein eigener Laufsteckplatz und eine Task mit genau dieser Steckplatz-/Modellbindung. Persönliche Profile bleiben erhalten. Der Agent bestätigt das fachliche Ergebnis mit `task_manage(action="done", task_id=..., result="...")`. Ergebnis und Lease-Abschluss werden in derselben SQLite-Transaktion gespeichert. Das Ergebnis ist auf 3000 Zeichen begrenzt; eine verlorene Abschlussbestätigung begründet keinen Erfolg.

Erst bestätigter Taskabschluss, fachliches Ergebnis, übereinstimmende Request-/Generations-/Controllerkennungen und physisches Threadende erlauben den nächsten Schritt. `finishing` bedeutet noch kein physisches Ende. Eine PR zur Prüfung oder die Nachricht „Task erledigt“ allein ersetzt das fachliche Ergebnis nicht.

Ein Stop wird vor der Cancellation dauerhaft gespeichert. Er betrifft ausschließlich die korrelierte native Generation. Bei Controllerwechsel, unklarer Zulassung oder verlorenem Checkpoint wird kein weiterer Schritt gestartet. Ein alter ungeklärter Lauf wird nach einem Neustart weder als abgeschlossen angezeigt noch automatisch wiederholt; die Betriebsprüfung muss sein tatsächliches Ende klären.

## Quellen und API

- `GET /api/marblerun/catalog`: echte Ketten, Living-Profile, aktuelle Skill-Quellen und Laufbelege.
- `POST /api/marblerun/chains`, `PUT /api/marblerun/chains/{id}`, `DELETE /api/marblerun/chains/{id}?version=...`: Anlage und Änderungen mit Versionsprüfung.
- `POST /api/marblerun/chains/{id}/run`: ausdrücklicher Start mit Ketten-/Konfigurationsversion und neuer Request-ID.
- `GET /api/marblerun/runs/{id}`, `POST /api/marblerun/runs/{id}/stop`: Readback und kooperativer Stop.

GUI und Control API verlangen Geräteautorisierung. Ein Katalogabruf migriert keine Datenbank und startet kein Modell. Cloud-/API-Modelle arbeiten nur nach dem ausdrücklichen Start der ausgewählten Kette; die vorhandene Providerpolicy einschließlich `openrouter/free` gilt weiter. Der Compute-Turn-Gate serialisiert lokale Inferenz und lässt den Vordergrund an sicheren Grenzen vor.
