# worker_policy – BACH-Kompatibilitätsexport

## SOLL

Ein eigenständiges Ocean-Policymodul darf nur mit geprüfter Anbieterbindung,
expliziter Datenautorität und nachgewiesener Parität als eigenständig gelten.
Die vorhandenen Taskplan-Policytypen und die kanonische UserDB bleiben maßgeblich.

## IST

Dieser Export ist ein dünner Adapter auf
`hub._services.worker_policy_settings`, kein eigenständig fertiges Ocean-Modul.
`manifest.json` kennzeichnet ihn deshalb ausdrücklich mit `selfcontained: false`.
Der bestehende Self-contained-Validator lehnt seinen Re-Import ab; der BACH-Loader
verwendet weiterhin den korrekten nativen Legacydienst. Die Standalone-Statusanzeige
zählt diesen Fallback nicht als eigenständiges Modul.

Lesen und Schreiben reichen die nativen Rückgaben und Fehler unverändert weiter.
Es gibt keine erfundenen Defaults oder Speicherbestätigungen. CAS-Konflikte,
fehlender Store/Taskplanvertrag, fehlendes Schema und verweigerte Operatorrechte
bleiben Fehler. Eine erfolgreiche native Speicherung kann unabhängig über denselben
expliziten `db_path` gelesen werden; kein neuer Store wird angelegt.
`operator_token` wird ausschließlich an die vorhandene native Prüfung weitergegeben.
Der CLI-Adapter meldet Fehler als fehlgeschlagene Operation und behält seine
kanonische bzw. explizit injizierte UserDB bei.

Die Architekturentflechtung zu einem vollständig eigenständigen Ocean-Modul und
produktive Runtimeabnahme bleiben offen. Tests verwenden nur synthetische Stores.
