# Software und Ocean in der gemeinsamen GUI

Die GUI 0.2.5 unterscheidet eigenständige Anwendungen und Modulquellen.

- Software: /skills/software und GET /api/capabilities/software lesen das
  bestehende .SOFTWARE/releases.json. BACH_APPLICATION_ROOTS kann eine
  JSON-Liste absoluter Anwendungswurzeln festlegen. Ohne Konfiguration wird
  OneDrive aus der Umgebung beziehungsweise dem Home-Verzeichnis abgeleitet.
- Ocean: /skills/ocean und GET /api/capabilities/ocean zeigen die bisherige
  Repository-/Modulübersicht. BACH_OCEAN_ROOTS ist ihre explizite Konfiguration.
  BACH_SOFTWARE_ROOTS bleibt für diese frühere Quellenansicht kompatibel.
- Plugins sind Erweiterungen der Agenten-Clients und behalten ihren eigenen Reiter.

Die Softwareansicht gibt nur Projektmetadaten aus: Name, Version, Kategorie und
deklarierte Veröffentlichungsziele. Private Notizen, Anwendungsdaten und
Launchbefehle werden nicht gelesen beziehungsweise nicht projiziert. Eine
Veröffentlichung laut Register ist keine Live-Abnahme im Store; eine
Katalogzeile ist kein Installationsnachweis. Fehlende Softwarequellen werden
angezeigt, ohne auf Repository-Quellen auszuweichen.

Deterministische Verarbeitung gehört in passende Software. Leichte und mittlere
Modellaufgaben können lokale Modelle übernehmen; schwere Aufgaben externe
Modelle. Diese Orientierung startet keine Cloud-Worker und ersetzt keine
aufgabenspezifische Modellwahl.

Der Shared-GUI-Quellstand und Archivhash stehen in system/gui/kit_manifest.json
und system/gui/gui-consumer.v1.json. Der Pin allein belegt kein Deployment.
