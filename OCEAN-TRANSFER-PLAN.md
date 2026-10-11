# Ocean–BACH-Transferplan

Stand: 9. Oktober 2026. Dieser Plan beschreibt den begrenzten Integrationsauftrag und die anschließenden Modultransfers. Laufzustand und Bearbeitung liegen in der TaskDB; dieses Dokument enthält die Architektur und Abnahmeregeln.

## Umfang des aktuellen Auftrags

- Gemeinsame GUI aus `ellmos-system-gui`, konsumiert über einen festen Quellcommit, ein Releasearchiv und dessen SHA-256.
- Gemeinsamer Installer mit getrennten Produktprofilen für BACH und Ocean. Ocean bleibt die einzige Engine für Fetch, Place, Activate und Rollback.
- Erster begrenzter Modultransfer: `policy-registry` als lesender kanonischer Provider. Das umfasst Registry-, Quellen- und effektive Policy-Metadaten. Schreibende Governance ist eine getrennte, ausdrücklich freizugebende Fähigkeit.
- Weitere Transfers sind geplant. Nach Zusammenführung gleicher Modulquellen entstehen 64 Aufgaben; keine dieser Aufgaben ist dadurch bereits umgesetzt.

## Ersttransfer: policy-registry

Provider: `ellmos-ai/policy-registry`, Version `0.2.4`, Commit `2c4896b70cb39e2e24748b384d5d0cc7fcd15a16`.

BACH verwendet einen schmalen Adapter statt einer zweiten Registry. Die Aktivierung erfolgt explizit über `BACH_POLICY_REGISTRY_ENABLED=1`. Der native Provider bestimmt den Registryort über `POLICY_REGISTRY_PATH` oder seinen eigenen Standard. Paketversion, Git-Herkunft und Importpfad werden vor Verwendung geprüft.

Lesepfade:

- `GET /api/governance/policy-registry`
- `GET /api/governance/effective-policy?scope=...`
- Bestehende Governance-Policy-/Decision-Ansichten verwenden denselben Provider.

Fehlendes Paket, falsche Provenienz oder fehlende Registry ergeben einen Fehler; es gibt keinen stillen Rückfall auf feste Beispielpolicies. Die GUI erhält freigegebene Metadaten und Quellenprüfstände, keine privaten absoluten Pfade oder Regelvolltexte.

Beim ersten Mac-Readback am 8. Oktober wurden fünf vorhandene Entscheidungsquellen mit dem nativen Adapter registriert: vier bestätigte Dateihashes und ein vorhandener Verzeichniszeiger. Am 9. Oktober scheiterte ein erneuter Readback am Betriebssystemfehler EAGAIN einer Quelldatei. Der native Provider 0.2.4 weist solche Quellen einzeln als `unreadable` aus und prüft die übrigen Zeiger weiter. Dieser Stand ist ein Quellenprüfzustand; er bestätigt keine Durchsetzung der Policy. Das produktive Readback nach Installation des neuen Pins bleibt eine getrennte Abnahme. Die vollständige Policy-Adoption des Macs und der menschliche DecisionClicker-Schreibpfad sind ebenfalls noch nicht abgenommen.

## Installer und Paketgrenzen

Ein Installer verwendet Produktprofile und versionierte Komponentenmanifeste. BACH und Ocean erhalten dasselbe GUI-Paket, aber eigene Backend-Adapter und Betriebszustände. Nutzerdaten, Zugangsdaten, TaskDB, lokale Rollen und OneDrive-Steuerdokumente bleiben außerhalb der Codearchive.

Vor jeder Anwendung bindet die Planung Produkt, Zielhost, Quellenpins, GUI-Hash und die vollständige Komponentenmenge. Eine ausdrückliche Freigabe und ein extern signierter Capability-Grant bleiben erforderlich. Der frisch aufgelöste Ocean-Komponentensatz einschließlich aller Abhängigkeiten muss exakt dieser Menge entsprechen, bevor eine Mutation erfolgt. Rollback prüft ebenfalls alle protokollierten Komponenten vor der ersten Löschung.

Ein physischer Sammeltransfer aller Bundles wird nicht empfohlen: Er erzeugt parallele Autoritäten und erschwert Rollback. Stattdessen wird die gemeinsame Installationsschicht früh verwendet und pro Modul um einen gepinnten Vertrag erweitert. Der Installerplan darf keine fehlende Laufzeitimplementierung aus einem bloßen Manifestverweis ableiten.

## Ablauf je Modul

1. Kanonische Quelle, Repository, Branch, Sperren und vorhandene BACH-Entsprechung prüfen.
2. Native Fähigkeiten, Datenhoheit, echte Endpunkte und Rollen bestimmen. Deklarierte, implementierte und produktiv geprüfte Fähigkeiten getrennt ausweisen.
3. Einen schmalen Adapter mit einem überprüfbaren Pin und klarer Aktivierungsoption entwickeln.
4. Abhängigkeiten und Freigabemenge im Installationsplan vollständig auflösen.
5. Vertragstests, unabhängiges Review und Endpunkt-Readback am tatsächlichen Ziel ausführen. GUI- oder Geräteabnahme gesondert festhalten.
6. Nach bestätigter Parität den Altteil im [Deprecation-Register](DEPRICATED.md) mit Ersatz, Datum, Problemen und Rollback markieren.
7. Den alten Code erst in einer gesonderten, überprüften Entfernung beseitigen.

Ein geplanter Transfer darf weder Cloud-Worker automatisch starten noch kostenpflichtige Modellfallbacks einführen.

## Dokumentationsbrücke

- Rootdateien verweisen auf diesen Plan, das Deprecation-Register und die Bedienhilfe.
- Die gemeinsame GUI dokumentiert ihren Paket- und Capability-Vertrag.
- BACH dokumentiert seine CLI, API, Betriebszustände und die konkreten Konsumentenadapter.
- Ocean dokumentiert Profile, Manifestauflösung, Installation und Rollback.
- Module behalten ihre eigene kanonische API-/CLI-/Skill-Dokumentation. Die Systeme verlinken diese Quellen.
- Ein Capability-Katalog beschreibt registrierte Adapter. Registriert bedeutet nicht produktiv geprüft. Test-, Installations- und Gerätebelege werden separat geführt.

## Abnahme und Rollback

Ein Release benötigt einen sauberen Quellcommit, vollständige Datei- und Archivhashes sowie die identische Pin-Konfiguration des Konsumenten. Vor Deployment werden die bisherige Releaseidentität und Dienstkonfiguration gesichert. Rollback betrifft Code und Konfiguration; TaskDB und Nutzerdaten werden nicht durch einen alten Codebestand ersetzt.

Offene Abnahmen bleiben in der TaskDB. Ein erfolgreicher Testlauf ersetzt keinen produktiven Worker-Lauf und keine Browser- oder Tray-Abnahme.
