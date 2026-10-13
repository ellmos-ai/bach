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

## Aktueller Source-Pin: GUI 0.2.23

Der veröffentlichte Release v0.2.23 bindet Commit 99cde50dfaa0f0306b6c5b70aebc4161db0fc71c,
das ZIP ellmos-system-gui-0.2.23-99cde50dfaa0.zip und die SHA-256-Prüfsumme
18cd12c95157e05098a3105ff5ea446238d4ac6642f8aa89e38344878f85f893.
Das Release-Manifest führt 197 Dateien, darunter 26 HTML-Seiten.

Die Konfidenzanzeige unterscheidet ungemessene Werte, gespeicherte unverifizierte Fakten
und unverifizierte Hermes-Heuristiken. Sie ersetzt keine Messung oder native Lernabnahme.
Die Aktivierung benötigt kompatible Backendprojektionen und Lesson-Promotion-Verträge;
die Integration aus BACH PR #377 und dieser Verbraucher-Pin sind gemeinsam zu prüfen.
Insbesondere müssen null, ungültige sowie übergroße Werte ohne erfundene Prozentwerte
oder Fehler projiziert werden. Ein Pin oder Katalogeintrag belegt weder Installation
noch produktive Aktivierung. Vorherige Dist, Pin und LaunchAgent-Konfiguration bleiben
für einen koordinierten Rollback erhalten.

## Historischer Source-Pin: GUI 0.2.22

Der veröffentlichte Release v0.2.22 bindet Commit cb0784089d723f80aa7f508b741198419a4bde82,
das ZIP ellmos-system-gui-0.2.22-cb0784089d72.zip und die SHA-256-Prüfsumme
31456f46aa8d87fa908575bad026583432eec577b9df8e454cf4f5e9eab507b9. Das Release-Manifest
führt 197 Dateien, darunter 26 HTML-Seiten. Der Consumer-Pin und der operative Kit-Pin
müssen Commit, Archiv-SHA-256, Dist-Manifest-Schema und Seitenzahl identisch binden.

Diese Release-Identität ist ein Quell-/Kit-Pin. Sie belegt allein keine Installation,
keine aktive LaunchAgent-Konfiguration und keine Live-Auslieferung. Dafür bleibt die
separate Prüfung des tatsächlich konfigurierten Dist-Verzeichnisses samt vollständiger
Dateiliste und Datei-Hashes erforderlich.

GUI 0.2.22 enthält den auf Mermaid 11.17.2 abgestimmten KaTeX-Fix (0.18.7).
Die Veröffentlichung und Archivprüfung ersetzen weder die native Auslieferungsprüfung
noch die Prüfung des tatsächlichen Renderings auf ASUS oder im Ocean-Konsumenten.

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

Der aktuelle BACH-Quellstand enthält die Subscription-Agents-Seitenroute und den
Composer-Endpunkt. Die Pin-Regression prüft die Seitenroute gegen die exakten
Release-Bytes; ein fehlender Composer muss weiterhin als nicht verfügbar erscheinen.
Die Endpunktregistrierung belegt weder eine erfolgreich bediente native Komposition
noch einen Launcherstart. Der GUI-Pin behauptet diese Laufzeitabnahmen nicht.
