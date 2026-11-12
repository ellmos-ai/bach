# Seitenfähigkeiten aus dem gemeinsamen GUI-Release

BACH konsumiert `page-reads.v1.json` aus dem installierten gemeinsamen
GUI-Release. Die normative Quelle liegt in ellmos-system-gui,
`docs/CONSUMER_CONTRACT.md`; die GUI prüft ihre Aufrufstellen gegen das
Manifest. BACH hält keine eigene Seiten-zu-Endpunkt-Tabelle.

## Bindung und Auswertung

Der vorhandene Distprüfer erfasst die Manifestbytes während desselben
Dateilesens, dessen SHA256 er gegen das Dist-Manifest prüft. Erst eine
vollständig erfolgreiche Prüfung von Quellcommit, Dateimenge und Hashes
übergibt den Snapshot. Der Konsument verlangt zusätzlich die gültige
Kitidentität und die passende erwartete HTML-Seitenzahl.

Nur erforderliche GET-Aufrufe bestimmen den Seitenstatus. Optionale
Lesezugriffe, Layoutaufrufe und Schreibaktionen machen eine Seite nicht
unverfügbar. Methoden bleiben getrennt; Parameternamen werden für den
Routenvergleich normalisiert. Der Compose-POST bleibt als eigene
Vorschaufähigkeit deklariert und bestimmt die Freigabe des Vorschauknopfs.

Fehlende oder ungültige Manifestdaten ergeben keine als konfiguriert
behaupteten Seiten. `gui.page_reads` nennt Zustand und Grund, bei gelesenen
gültigen Bytes außerdem deren SHA256. Die Endpunktdeklarationen bleiben
als Adapterinformationen verfügbar. Ein vollständig verifiziertes Dist
ohne Seitenmanifest bestätigt weiterhin nur seine Dateiintegrität.

## Schutz vor alten Seiten

Die bestehenden gemeinsamen HTML-Routen sind in ihrer nativen Registrierung
mit dem Tag `shared-gui` markiert. Die Middleware verwendet den tatsächlichen
methodengebundenen Routingtreffer, keine zusätzliche Seitentabelle.
Bei ausdrücklich gewähltem gemeinsamen Release scheitern diese HTML-Navigationen
ohne verifizierbare gemeinsame Seite mit HTTP503. Ein fehlendes Manifest
schaltet diesen Schutz nicht aus. Weiterleitungsaliase und separate Anwendungen wie die Konsole bleiben
unmarkiert. API-Routen, Datei-/Assetanfragen sowie
die bestehende Geräteauthentifizierung behalten ihre eigenen Grenzen.
Nach der Prüfung liefert die Middleware exakt die erfassten und gehashten
HTML-Bytes aus; sie öffnet die Datei nicht erneut und ruft keinen alten
Seitenhandler auf. /system, /logs, /tasks-board und /usecases leiten im
gemeinsamen Modus auf die geschützten kanonischen Seiten weiter.
Die statische Hülle /system/ocean ist wie die übrigen gemeinsamen Hüllen
öffentlich erreichbar; ihre Datenrouten behalten die Geräteauthentifizierung.
Es gibt keinen automatischen Rückfall auf eine alte BACH-Seitentabelle.

## Nachweisgrenze

`configured` bestätigt passende registrierte Adapterrouten. Es bestätigt
weder deren fachliche Laufzeit noch Browserbedienung, Datenzugriff,
Geräteabnahme oder einen laufenden Agenten. Quellenintegration, automatische
CI, native Bereitstellung und unabhängige Produktabnahme bleiben getrennte
Schritte. Diese Änderung installiert kein GUI-Release und startet keinen
Dienst.
