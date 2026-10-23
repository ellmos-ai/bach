# BACH-Adapter für den gemeinsamen Dokumentationsregelkreis

## Auftrag und Quelle

Dieser Adapter bindet BACH an den gemeinsamen Workflow **doc-reality-loop** an.
Die vollständige Methode, Zustände und Pflichtbelege liegen im Ocean-Repository.
[Quellpin](doc-reality-loop-source.v1.json) nennt Repository, festen Commit,
Dateien und SHA-256 ihrer unveränderten Git-Blobs. Die dortigen Links sind
portabel; ein vorhandener Checkout ist nur nach Abgleich mit diesem Pin eine
Quelle. Abweichende oder nicht erreichbare Quellen sind `unknown`; keine
stillschweigende Verwendung von `main`, alten lokalen Kopien oder ähnlich
benannten Modulen. Ein Pinwechsel benötigt eigenen Quellenreview.

Der Pin installiert oder startet nichts. Der Shared-Prüfer beurteilt die Form
einer Belegkette; sein Erfolg beweist weder einen realen Lauf noch den Inhalt
der angegebenen Belegdateien. BACH führt hier keinen fremden Python-Code aus.
Es gibt durch diesen Adapter keinen weiteren Scheduler und keinen Doku-Writer.

## Varianten und bisherige Methoden

| Bisherige Methode / native Routine | Gemeinsame Variante | BACH-Quelle |
|---|---|---|
| help-forensic, help-expert-review / help_forensic | help | Themenfamilien unter `system/docs/help/`, einschließlich Sprachvarianten |
| root-docs-review | root | Tatsächlich getrackte Einstiegstexte im Repository und unter `system/` |
| docs-analyse / roadmap_review | requirements | Explizit beauftragte Konzept-, Plan- und Anforderungsdokumente |
| doc_freshness, docs_changelog_review | freshness | Explizit beauftragte Versions-, Datums- und Changelog-Aussagen |

Bei einem Quell-Delta wird die Variante je betroffenem Dokument bestimmt.
Die vier alten Dateien unter `system/skills/workflows/` bleiben Herkunft und
Fachkontext. Ihre festen Modelle, Agentenzahlen, Zeitannahmen, alten Pfade und
Archivprozentsätze werden nicht übernommen. Ein Erfüllungsgrad allein erlaubt
weder Archivieren noch Umbenennen. Die gemeinsame Methode gilt auch dann,
wenn eine alte Methode Code über tatsächliche Wirkung einordnet.

## BACH-Aufnahme und Analyse

1. Den echten Auftrag und die aktuelle Lease über den nativen BACH-Vertrag lesen.
   Die kanonische Taskautorität bleibt bei `TaskLeaseClient` / `bach_api`.
   Keine direkte TaskDB, erfundenen IDs oder selbst angelegten Folgeaufgaben.
   Persönliche Freigaben, Locks, Generations- und Scopegrenzen bleiben gültig.
2. Scope aus dem Auftrag erfassen. Der Delta-Dispatcher nennt begrenzte Quellen;
   weitere Dateien sind nicht automatisch geprüft. Recurring-Konfiguration ist
   Auslöserquelle, kein Ersatz für die zu prüfende Dokumentfamilie.
3. Beauftragte Dokumente vollständig lesen. Jede überprüfbare Aussage mit
   Dokument und Fundstelle erfassen: Befehle/Optionen, Handler, Tabellen,
   Endpunkte, Pfade, Versionen, Zahlen, Datum und Verweise. Wünsche als
   Anforderungen kennzeichnen. Bei zu großem Scope die verbleibenden Aussagen
   ausdrücklich offen lassen; keinen vollständigen Prüferfolg behaupten.
4. Leser aus dem gültigen Dokumentregister rücklesen. Registerpfad und Revision
   aus dem konkreten Consumer ermitteln; dieser Adapter erfindet keine zweite
   Registry. Ohne belegten Registereintrag heißen die Leser `unknown`.
   Zusätzlich getrackte Links prüfen; relative Links am verweisenden Dokument
   auflösen. Aktive Boot-, Tool-, Test-, Menschen- oder Linkleser erhalten.
5. Für jede Aussage die passende Oberfläche und Autorisierung bestimmen.
   Laufende Instanz mit Host, Instanz-ID und Version separat von Checkout und
   Quellcommit erfassen. Tatsächliche CLI/API/GUI-Wirkung hat Vorrang vor Code,
   Schema, Dateisystem und älterer Beschreibung. Ein vorhandener Handler beweist
   seine Quellimplementierung, keinen erfolgreichen Lauf.
6. Nur autorisierte, lesende Messungen durchführen. Keine Tests, Builds,
   Dienste, Modelle, Schreibbefehle oder potenziell schreibenden GET-Aufrufe
   allein wegen dieser Methode ausführen. Bei fehlender Befugnis oder
   unerreichbarer Oberfläche `unknown` samt Grund und nächstem nötigen Nachweis
   festhalten. Vorhandene genaue Laufbelege können geprüft werden; deren Scope
   und Zeitpunkt bleiben erhalten.
7. Unterschiede als `better`, `partial`, `target-missing`, `wrong` oder
   `unknown` klassifizieren. Je Zeile: `statement`, `source`, `observed`,
   `evidence_ref` und `scope` mit Host, Instanz, Version und Oberfläche.
   Einen kleinen beschreibenden Korrekturvorschlag liefern. Gewünschte fehlende
   Funktionalität als Soll mit Quelle und vorhandener Task-ID erhalten.
   Fehlende Task-ID als offene Zuordnung melden; keine ID erfinden.
8. Analyse und Belegreferenzen als Ergebnis derselben Task/Generation abgeben.
   Ein Vorschlag ändert keine Dokumente und archiviert nichts. Auch keine
   Differenz ist ein zulässiges Analyseergebnis.

## Belegkette und tatsächliche Korrektur

Die Reihenfolge des gepinnten Vertrags lautet
`trigger_planned → task_created → executed → corrected → reviewed → repaired`.
Fehlende Zustände bleiben in `unknown`; keine Stufe wird aus Taskstatus,
Taskanlage, Dispatch, `last_run` oder Annahme eines Analyseergebnisses abgeleitet.

| Zustand | BACH-Nachweis |
|---|---|
| trigger_planned | Native Routine / Delta-Auslöser, konfigurierter Intervallverweis, Markerquelle, tatsächliche Fälligkeit und Beobachtungszeit |
| task_created | Native Task-ID, Titelhash, Workerbindung, verifizierter Readback mit Referenz/Hash und Erstellungszeit |
| executed | Tatsächlicher beendeter Prüflauf mit Run-ID, Host/Instanz/Version, Anfang/Ende, Ergebnis-ID, Exitstatus/-code und Autoridentität/-instanz |
| corrected | Autorisierte reale Textänderung mit Vorher-/Nachherhash, Diffreferenz, vollständiger Differenztabelle, Archiventscheidungen und erhaltenen offenen Anforderungen |
| reviewed | Andere Identität **und** andere Instanz prüfen Dateien und Belege selbst; genau ein Urteil je Unterschied mit Annahmezeit |
| repaired | Erneute Messung auf demselben Scope mit Referenz/Hash und Zeit: gleiche Wirkung, keine Regression, vorausgehender unabhängiger Review |

Alle Pflichtfelder und Zeitregeln des Shared-Vertrags gelten zusätzlich.
Native Datumsformate nur mit belegter Zeitzone normalisieren; keine UTC-Zeit
für unbekannte lokale Altmarker erfinden. Belegreferenzen müssen tatsächlich
existieren, vollständig rückgelesen und mit ihrem Hash gebunden sein.

Nach angenommenem Analysevorschlag bleibt eine tatsächliche Korrektur ein eigener,
ausdrücklich autorisierter Schritt im Scope des Dokumentbesitzers. Generierte
Texte gehen an ihren Generator; dessen Ausgabe wird regulär erneuert.
Archivierung verlangt Registerautorität, erlaubende Policy, vollständige aktuelle
Leser- und Linkprüfung sowie Ersatzreferenz oder Archivierbeleg und Rückweg.
Fehlende Befunde, aktive Leser oder offene Anforderungen bedeuten `keep`.

## Bericht, Rückweg und offene Abnahme

Der Bericht liegt im **konfigurierten Artefaktbereich des jeweiligen Consumers**.
Sein vollständiger Pfad, Produkt, Task-/Runbindung und Quellenpin stehen im
nativen Ergebnis. Keine feste Hostablage wird in den gemeinsamen Vertrag
eingetragen. Der Bericht enthält Differenztabelle, unverifizierte Aussagen,
offene Anforderungen, Datei- und Belegreferenzen mit Hashes, Reviewurteile sowie
gegebenenfalls erneute Messung und Rückweg. Unveränderte Analyse bekommt keine
erfundenen Vorher-/Nachherhashes und keinen `corrected`-Status.

Der vorhandene Wartungsowner behält Intervalle, Budget, Lock-, Konflikt-,
ACK-Recovery-, Fehler- und Nochange-Verhalten. Neue Aufträge verwenden diesen
Adapter; nach verlorenen ACKs werden auch bekannte exakte Altbeschreibungen
wiedergefunden. Weder bestehende Aufgaben noch ihre Ergebnisse werden umgeschrieben.
Ein Quellenupdate aktiviert keinen Wartungsprozess und erweitert keine Toolrechte.

Offen bis zu echten Belegen bleiben: integrierter BACH-/Ocean-Consumer,
gültige Registeranbindung, reale Ausführung, unabhängiger Review, tatsächliche
Dokukorrektur und erneute Messung beider Produkte, einschließlich Idempotenz,
Konflikt, Nochange, Fehler und Rückweg. `last_review_success` bleibt ein
Analyse-Reviewbeleg; `last_repair_success` bleibt ohne eigenen Reparaturnachweis leer.
