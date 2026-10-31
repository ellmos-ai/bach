# Ocean–BACH-Transferplan

Stand: 31. Oktober 2026. Dieser Plan beschreibt die laufende Integration und die offiziell gestartete Rückmodularisierung. Laufzustand und Bearbeitung liegen in der TaskDB; dieses Dokument enthält die Architektur und Abnahmeregeln.

## Meilenstein `v3.15.0-ocean-stack-m1` – BACH als gebrandeter Teil-OS-Stack von Ocean (2026-10-31)

Ab Commit `0dab1a8fa1` (Tag `v3.15.0-ocean-stack-m1`) ist das verbindliche Architekturmuster für die schrittweise Umwandlung von BACH in einen gebrandeten Teil-OS-Stack von Ocean produktiv im Code verankert:

1. **Zentrale Ocean-Consumer-Brücke (`system/hub/_services/ocean_stack_bridge.py`):**
   - Lädt die kanonischen Ocean-Module (`ocean-resources`, `task-master/taskplan`, `open-ocean/tools/*`) konfliktfrei neben `bach/system/tools` und stellt den Live-Bindungsstatus unter `GET /api/ocean/stack-bindings` (`stack_role: "branded_partial_os_stack_of_ocean"`) bereit.
   - Aktuell 10 produktiv angebundene Modul-Seams (Tasks `#1858, #1859, #1860, #1862, #1869, #1896, #1898, #1906, #1914, #1917` auf `done`):
     1. `ocean_resources`: `ocean_resources.ram_distributor.RAMDistributor` & `WatchdogHysteresisPolicy` (über `ocean_resources_adapter.evaluate_ocean_ram_admission`)
     2. `taskplan_lease`: `taskplan.lease.TaskLeaseManager` (über `taskplan_bridge.execute_taskplan_lease`)
     3. `worker_worktree_policy`: Multi-Repo-Arbeitsbaum- und Schreibschutzvertrag (`open-ocean/tools/worker_worktree_policy.py`)
     4. `task_result_review_policy`: Konfigurierbare Modell-Review-Regeln & Auto-Accept für Text-Ergebnisse ohne Code-Scope (`open-ocean/tools/task_result_review_policy.py`)
     5. `escalation_ladder`: 5-stufige Autoritäts- und Eskalationsleiter (`open-ocean/tools/escalation_ladder.py`)
     6. `persona_routing`: Rollen- und Wartungsmanifest-Prüfung (`open-ocean/tools/persona_routing.py`)
     7. `learning_loop`: Skill-Gärtner-Kandidatenvertrag (`open-ocean/tools/learning_loop.py`)
     8. `agent_library`: Einheitliche Agenten-Bibliothek (`open-ocean/tools/agent_library.py`)
     9. `capability_views`: Software-Inventar `/api/capabilities/software` (`open-ocean/tools/capability_views.py`)
     10. `governance_bridge`: Governance-Audit, Assignees & Task-Result-Projektion (`open-ocean/tools/governance_bridge.py`)
2. **Verbindlicher Deprecation-Mechanismus (`@deprecated_legacy_bach("<canonical-ocean-module>")`):**
   - Jede durch ein Ocean-Modul abgelöste BACH-Altklasse oder -Altfunktion wird mit `@deprecated_legacy_bach(...)` dekoriert (`__bach_deprecated__ = True`, `__ocean_replacement__ = "<modul>"`, `DeprecationWarning` beim Aufruf) und in [`DEPRICATED.md`](DEPRICATED.md) registriert.
   - Die verbleibenden 54 `OCEAN-TRANSFER`-Tasks (`#1854`–`#1916`) werden Modul für Modul nach genau diesem 3-Stufen-Verfahren abgearbeitet: **(1) Ocean-Modul über Seam/Adapter anbinden → (2) BACH-Altcode mit `@deprecated_legacy_bach` markieren → (3) Altcode nach Paritätsabnahme entfernen.**

## Rückmodularisierung: Start und Entwicklungsregel

Der Nutzer hat die Rückmodularisierung am 13. Oktober 2026 ausdrücklich gestartet. Neue Fachlogik entsteht bevorzugt direkt in einem passenden bestehenden ellmos-/Ocean-Modul. Fehlt ein sinnvoller Modulort, wird eine abgegrenzte Fähigkeit als neues Modul geplant. BACH konsumiert den gepinnten Provider über schmale Adapter; gemeinsame Module bleiben unabhängig von BACH nutzbar.

Würde eine Aufgabe eine neue Fachlogik innerhalb einer noch monolithischen BACH-Struktur verlangen, gehört die Übertragung der beteiligten Fähigkeit möglichst gleich zum Auftrag. Dazu darf der Schnitt über die ursprünglich angefragte Einzeländerung hinausgehen. Gemeinsam genutzte Strukturen werden soweit nötig mit entkoppelt. Der gemeinsame GUI-Ausbau, der tatsächliche Ocean-Anschluss und die priorisierte Hintergrundarbeit werden dabei weitergeführt.

Pro Änderung wird ein zusammenhängender Fähigkeitsschnitt mit folgenden Nachweisen bearbeitet:

- Vorhandene BACH-Implementierung, gemeinsame Aufrufer, native Datenhoheit und kanonisches Zielmodul bestimmen; keinen zweiten Store, Scheduler, Modellrouter oder Governance-Kern einführen.
- Fachlogik und gemeinsame Verträge upstream entwickeln; BACH-spezifische CLI-, API-, GUI- und Betriebsadapter erhalten und an denselben Provider anschließen.
- Pins, Modulmanifest, Installerprofil und vollständige Abhängigkeiten nachführen. Private Rezepte, Berichtpipelines und Nutzerdaten bleiben in privaten Repositories beziehungsweise lokaler Konfiguration.
- Vertragstests, unabhängiges Review, betroffene Endpunkte und tatsächliche Konsumenten prüfen. Source, Installation, Laufzeit, fachliche Abnahme und Gerätetest getrennt ausweisen.
- Vor Umschaltung Rückfallweg sichern; Altteile nach bestätigter Parität in [DEPRICATED.md](DEPRICATED.md) führen. Entfernung bleibt ein überprüfter Schritt.
- Ist der vollständige Schnitt durch eine konkrete Sperre, fehlenden Vertrag oder Datenmigration verhindert, die begrenzte BACH-Zwischenlösung kapseln und mit Blockade, Zielmodul und Folgetask dokumentieren.

Die 64 geplanten Folgeaufgaben in der TaskDB werden einzeln je betroffenem Fähigkeitsschnitt gesteuert. Der Phasenstart meldet keine Transfers als erledigt und ersetzt keine bestehenden Rechte-, Lock- oder Abnahmeverträge.

Der geplante annotierte Release `v3.15.0` **BACH meets Ocean – BACH fließt ins Meer** markiert den GUI-Übergang und den Beginn dieser Phase. Der Tag behauptet keinen vollständigen Ocean-Cutover und keine abgeschlossene Modularisierung. Am 13. Oktober ist dieser Tag noch nicht veröffentlicht; Task #2071 führt den Release, #2099 liefert Zuarbeit. Die Startentscheidung gilt bereits, während die Release-Abnahmen gemäß [Meilensteinvertrag](docs/operations/BACH-3.15.0-MILESTONE.md) weiterlaufen.

## Umfang des aktuellen Auftrags

- Gemeinsame GUI aus `ellmos-system-gui`, konsumiert über einen festen Quellcommit, ein Releasearchiv und dessen SHA-256.
- Gemeinsamer Installer mit getrennten Produktprofilen für BACH und Ocean. Ocean bleibt die einzige Engine für Fetch, Place, Activate und Rollback.
- Erster begrenzter Modultransfer: `policy-registry` als lesender kanonischer Provider. Das umfasst Registry-, Quellen- und effektive Policy-Metadaten. Schreibende Governance ist eine getrennte, ausdrücklich freizugebende Fähigkeit.
- Weitere Transfers sind geplant. Nach Zusammenführung gleicher Modulquellen sind 64 Folgeaufgaben in der TaskDB geplant; ihre Planung bestätigt keine Umsetzung.

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

## GUI-Meilenstein 3.15.0 und weitere Reihenfolge

Der [Meilensteinvertrag](docs/operations/BACH-3.15.0-MILESTONE.md) bindet GUI 0.2.19/e909dd92, Verbraucherprüfung, sicheren Mac-Deploy und anschließenden BACH-Tag. Ein veröffentlichtes GUI-Paket ist noch keine produktive BACH- oder Ocean-Abnahme. Der gemeinsame GUI-Umzug und der tatsächliche Ocean-Adapteranschluss werden weiter abgenommen. Seit der Startentscheidung vom 13. Oktober werden beteiligte BACH-Fähigkeiten bereits im jeweiligen Auftrag rückmodularisiert; neue gemeinsame Fachlogik wird direkt upstream gebaut. Die 64 Transferaufgaben bleiben einzeln gesteuert. Die alte web/-Kopie ist keine zweite Entwicklungsquelle; ihre vorhandenen Rückweg-/Testcaller müssen vor endgültiger Entfernung gesondert abgenommen werden.
