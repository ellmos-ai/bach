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

## Aktueller Source-Pin: GUI 0.2.21

Der veröffentlichte Release v0.2.21 bindet Commit 8ea653e0061f85a9d6f2ead5e7cce2317bcdb19c,
das ZIP ellmos-system-gui-0.2.21-8ea653e0061f.zip und die SHA-256-Prüfsumme
9a10008b9506a7b69a09e1c7b8bf9f8c5ab0075358e5da17b8295ca816697d12. Das Release-Manifest
führt 197 Dateien, darunter 26 HTML-Seiten. Der Consumer-Pin und der operative Kit-Pin
müssen Commit, Archiv-SHA-256, Dist-Manifest-Schema und Seitenzahl identisch binden.

Diese Release-Identität ist ein Quell-/Kit-Pin. Sie belegt allein keine Installation,
keine aktive LaunchAgent-Konfiguration und keine Live-Auslieferung. Dafür bleibt die
separate Prüfung des tatsächlich konfigurierten Dist-Verzeichnisses samt vollständiger
Dateiliste und Datei-Hashes erforderlich.

## Historischer Rollout-Plan für GUI 0.2.20

Der damalige Pin band Commit daac428d25c93c319489748f541d9c4459c233e7, das ZIP
ellmos-system-gui-0.2.20-daac428d25c9.zip und 195 Dateien mit 26 HTML-Seiten. Beim
damaligen Wechsel waren ZIP-SHA, eingebettetes Dist-Manifest, exakte Dateiliste und alle
Hashes zu prüfen. Die Dist sollte in einem unveränderlichen, versionsgebundenen
Verzeichnis bereitgestellt und ein vorhandenes Auslieferungsverzeichnis nicht
überschrieben werden.

Der damalige Rollout-Plan verlangte dieselbe Release-Identität in kit_manifest.json und
ELLMOS_SYSTEM_GUI_DIST. Die API sollte während einer Abweichung den Dist als
unverifiziert melden; die technische Bestätigung sollte erst nach GET
/api/gui/kit-manifest und GET /api/gui/capabilities mit passendem Commit, vollständiger
Verifikation und 26 Seiten erfolgen. Pin, LaunchAgent-Konfiguration und vorherige Dist
sollten für einen abgestimmten Rollback erhalten bleiben. Das dokumentiert den früheren
Plan und ist kein Installations- oder Neustartnachweis für 0.2.20 oder 0.2.21.

Die Subscription-Agents-Seite kann ohne die separat gemountete BACH-Route nicht
komponieren; die Oberfläche muss diese Funktion als nicht verfügbar anzeigen. Der
GUI-Release-Pin behauptet keine Backend- oder Launcher-Bereitschaft.
