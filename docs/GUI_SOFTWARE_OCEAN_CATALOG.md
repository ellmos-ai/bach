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

Der BACH-Quellkandidat der Shared GUI steht in
system/gui/gui-consumer.v1.json. Der operative Kit-Pin in system/gui/kit_manifest.json
bestimmt, welche Dist-Identität die laufende BACH-Instanz erwartet. Beide Einträge
müssen Commit, Archiv-SHA-256, Dist-Manifest-Schema und Seitenzahl konsistent binden.
get_pinned_kit_manifest() validiert nur diese Identitätsmetadaten. Erst
verify_installed_dist() prüft das konfigurierte Dist-Verzeichnis anhand von Commit,
vollständiger Dateiliste und Datei-Hashes. Ein Quellpin allein belegt keine Installation
oder Live-Auslieferung.

## Mac-Rollout-Prüfung für den 0.2.20-Kandidaten

Der geprüfte Kandidat bindet Commit daac428d25c93c319489748f541d9c4459c233e7,
das ZIP ellmos-system-gui-0.2.20-daac428d25c9.zip und 195 Dateien mit 26 HTML-Seiten.
Vor einer separat freigegebenen Aktivierung sind ZIP-SHA, eingebettetes Dist-Manifest,
exakte Dateiliste und alle Hashes zu prüfen. Die Dist wird in einem unveränderlichen,
versionsgebundenen Verzeichnis bereitgestellt; ein vorhandenes Auslieferungsverzeichnis
wird nicht überschrieben.

Für den Wechsel müssen kit_manifest.json und die LaunchAgent-Variable
ELLMOS_SYSTEM_GUI_DIST dieselbe Release-Identität erwarten. Während einer
zwischenzeitlichen Abweichung muss die API den Dist als unverifiziert melden; der
Rollout gilt erst nach GET /api/gui/kit-manifest und GET /api/gui/capabilities
mit passendem Commit, vollständiger Verifikation und 26 Seiten als technisch bestätigt.
Der bisherige Pin, die LaunchAgent-Konfiguration und die unveränderte vorherige Dist
bleiben für einen abgestimmten Rollback erhalten. Diese Beschreibung ist ein Prüfplan,
kein Installations- oder Neustartnachweis.

Die Subscription-Agents-Seite kann ohne die separat gemountete BACH-Route nicht
komponieren; die Oberfläche muss diese Funktion als nicht verfügbar anzeigen. Der
GUI-Release-Pin behauptet keine Backend- oder Launcher-Bereitschaft.
