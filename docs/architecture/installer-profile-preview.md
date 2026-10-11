# Installer-Profilvorschau in BACH

## Zweck und Route

BACH stellt eine authentifizierte, reine GET-Vorschau für vorhandene Auswahlprofile bereit:

`GET /api/installer/profiles/{profile_id}/preview`

Der Route-Handler akzeptiert nur die Profil-ID. Instanzpfade, Hostnamen, Registrydateien,
Grants oder Installationsziele kommen nicht aus dem Clientpayload. Die ID muss dem
bestehenden Installerformat `[a-z][a-z0-9-]{0,79}` entsprechen.

Der Service ruft die PR4-Funktion
`ellmos_installer.bach_profile_factory.preview_profile_from_native_runtime` auf. Diese
verwendet den nativen `hub.bach_paths`-Resolver und die vorhandenen Kataloge, Registry-
bindungen, Explorer-, Auditor- und Open-Ocean-Verträge. BACH dupliziert keine Kataloge
oder Installationslogik. Die API projiziert nur bekannte Antwortfelder und erzwingt
`apply_allowed=false` sowie `deployable=false`; Fehler werden ohne Exception-Text oder
Traceback protokolliert und fail-closed beantwortet.

## Status und Grenzen

- `unavailable` bedeutet, dass eine notwendige Quelle, Bindung oder Laufzeitabhängigkeit
  fehlt oder ungültig ist.
- `awaiting_audit` enthält einen gebundenen Designentwurf, aber keinen Plan.
- `ready` bedeutet ausschließlich, dass die native Vorschau einen Design- und Planentwurf
  erzeugt hat. Es ist keine Freigabe und erlaubt keinen Apply.
- Fehlt das optionale Installerpaket, antwortet der Service mit
  `native_installer_unavailable`.
- Fehlerhafte Factory-Antworten und jede Antwort mit Apply- oder Deploy-Autorität werden
  verworfen.

Für den aktuellen BACH-Stand ist kein kanonischer nativer Instanzquellenvertrag mit einem
gültigen Instanzmanifest im von `hub.bach_paths` benannten Installationsbereich belegt.
Darum übergibt der Hostcaller bewusst `instance_path=None`. Die PR4-Factory antwortet
dadurch vor Discovery mit `native_instance_source_required`. Eine native
Instanzinitialisierung oder -migration bleibt Voraussetzung für spätere Discovery und
Planung. Die separat beobachteten veralteten Registry-Pins bleiben ein weiteres offenes
Gate; dieser Endpunkt repariert oder überschreibt sie nicht.

Der im Test verwendete optionale PR4-Test prüft nur den echten Factoryvertrag mit fehlender
Instanzquelle. Standard-CI installiert den Installer nicht; dort bleiben die unabhängigen
Router-, Authentifizierungs-, Projektion- und Fail-closed-Tests ausführbar. Auf dem Mac
kann der optionale Test mit dem exakt geprüften PR4-Quellstand ausgeführt werden.

## Integration

Die Routerdatei ist als Child-Router für den bestehenden Unified-API-Prefix `/api`
geschrieben. Die eine Registrierung in `unified_api.py` ist wegen eines fremden
Writer-Locks als separates, prüfbares Patch-Artefakt vorbereitet. Bis dieser Patch regulär
integriert ist, ist der Pfad nicht im laufenden BACH-Server gemountet. HTTP-Mount,
Installerpaket-Installation und produktive Instanzinitialisierung sind keine Abnahme dieses
Sourcepakets.

Der untersuchte PR4-Installer-Quellstand hat laut `pyproject.toml` die Paketversion
0.2.4 und den Commit `1287cab306999b18d172517efd5ec12fdf2b8ae1`. Der aktuelle GUI-Kandidat
ist 0.2.18; das ist die GUI-Version, nicht die Installer-Paketversion. Die älteren
0.2.15-Planungsnotizen sind historische Evidenz und kein aktueller Pin. Dieser Adapter
ändert keine Pins und führt
keine Installation, Freigabe, Grant-Erstellung oder Apply-Aktion aus.
