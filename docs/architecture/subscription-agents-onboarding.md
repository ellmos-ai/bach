# Subscription-Agenten: Onboarding-Promptvertrag

## Zweck und Grenze

`SubscriptionAgentsComposer` erstellt aus einer gespeicherten Blueprint-Revision,
ausgewählten Skill-Revisionen, einer Nutzeraufgabe, optionalen Task-Referenzen
und lesenden Governance-Verweisen eine versionierte Vorschau.
Der Composer ist transportneutral. Er startet keinen Agenten, claimt keine Task,
scannt keine Queue und schreibt nicht in die Zwischenablage.

Die Vorschau ist ein Arbeitsentwurf für eine menschliche Prüfung. Sie ist weder
eine Autorisierung noch der Nachweis eines Agentenstarts oder einer Task-Lease.
Fehlende Skills und Governance-Quellen werden als `missing` beziehungsweise
`needs_sources` ausgewiesen; der für die Vorschau notwendige Blueprint muss
dagegen mit der angezeigten Revision geladen werden können. Inhalte werden
weder durch angenommene Defaults ersetzt noch still gekürzt.

## Bestehende Bausteine

- Rollen- und Startpromptgrundlage: `hub._services.blueprint_service.synthesize_start_prompt`.
- Skillquelle und Revisionsbindung: `hub._services.skill_source_service.read_skill`
  und `load_skill_instructions`.
- Task-Snapshots: `hub._services.task_lease_client.TaskLeaseClient.task_snapshot`.
  Der Composer projiziert nur ID, Titel, Status und Priorität; Beschreibung,
  Claim-Daten und weitere Taskfelder gelangen nicht in die Vorschau.
- Governance: `hub._services.policy_registry_adapter.observe` liefert begrenzte,
  lesende Policy- und Decision-Metadaten. Volltexte und lokale Registry-Pfade
  werden nicht übernommen. `enforcement_verified` bleibt immer `false`.

Es entsteht keine zweite Blueprint-, Skill-, Policy- oder Taskbibliothek.
Der Aufrufer übergibt nur die Blueprint-ID und die angezeigte Revision. Der
Composer lädt die gespeicherte Quelle über den vorhandenen
`blueprint_service._execution_blueprint`-Validator aus der kanonischen BACH-DB,
mit einer read-only Verbindung. Eine fehlende oder inzwischen veraltete Revision
wird abgelehnt; Rollenprompt, Skills und Konfiguration können nicht vom Request
überschrieben werden. Die SHA-256 bindet die tatsächlich verwendete, typisierte Projektion,
nicht die vollständige Datenbankzeile oder unveränderte Rohquelle. Die
Contractus-Projektion ist mit bach.contractus-projection.v1 markiert und
normalisiert nur bekannte Preset-/Seed-Aliase. Preset-ID, Titel und
Beschreibung werden getrennt typisiert und in der Projektion gebunden, aber
nicht in den Prompt übernommen. Widersprüchliche Aliaswerte, unbekannte
Felder und verschachtelte contractus.execution-Werte werden abgewiesen.
task_type und task_types bleiben getrennte Angaben. Die
Contractus-Sektion im Prompt ist deklarativ und erteilt keine Laufzeit-,
Werkzeug- oder Startfreigabe. Der lokale Datenbankpfad wird nicht ausgegeben.

## Transportvertrag

Requestschema: `bach.subscription-agent-onboarding.request.v1`.

```json
{
  "schema": "bach.subscription-agent-onboarding.request.v1",
  "target_client": {"client_id": "codex-cli", "host": "client-host", "workspace": "/path/to/project"},
  "blueprint": {"id": 7, "version": 3},
  "selected_skill_ids": ["quellenpruefung"],
  "user_task": "Fasse die Belege mit echten Umlauten zusammen.",
  "task_refs": [42],
  "task_selection_rule": "",
  "governance": {"scope": "BACH", "policy_query": "onboarding", "decision_query": ""}
}
```

Die Handler-Operation liest genau eine UTF-8-JSON-Datei bis 256 KB. Dadurch
enthält `App.execute` nur den Dateipfad in seinen Hook-Argumenten, nicht den
Prompt oder den Requesttext. CLI-Aufruf:

```text
bach subscription_agents compose <Request-JSON-Datei>
```

`bach_api.get_app().execute("subscription_agents", "compose", [request_path])`
läuft durch denselben automatisch entdeckten Handler und denselben Composer.
Der bestehende HTTP-Adapter ruft denselben Composer über
`POST /api/agent-studio/subscription-agents/compose` auf und ist im
BACH-Server-Quellstand gemountet. Die bestehende Route
`POST /api/agent-studio/synthesize-prompt` bleibt beim bisherigen Blueprint-Prompt.
Geräte-, Body- und Fehlergrenzen beschreibt
`subscription-agents-http-transport.md`; produktiver Dienst- und
Browsernachweis bleiben getrennte Abnahmen.

Antwortschema: `bach.subscription-agent-onboarding.preview.v1`. Die Antwort
enthält `prompt`, Zeichen- und UTF-8-Bytezahl, festes Promptlimit,
Blueprint-ID, tatsächlich geladene Version und Hash, Quellen mit Version/Hash/Host/Pfad/Größe,
`missing`-Gründe, Governance-Geltungsbereich und explizite Aktionsflags.
Skilltexte werden mit ihrer aktuellen Revision gelesen und über den bestehenden
Skill-Adapter erneut auf denselben Hash geprüft. Policy- und Decision-Inhalte
bleiben Metadatenverweise. Wenn Skill- oder Governance-Quellen fehlen, zeigt
`status` den Wert `needs_sources`. Blueprint-Fehler oder ein Revisionskonflikt
stoppen die Erstellung der Vorschau mit einem verständlichen Fehler.

## Begrenzungen und Sicherheit

- Requestdatei maximal 256 KB; Nutzerauftrag maximal 16.000 Zeichen; höchstens
  20 Task-Referenzen und 30 unterschiedliche Skills.
- Rollenprompt maximal 20.000 Zeichen. Skill-Inhalte unterliegen zusätzlich
  dem bestehenden Budget des Skill-Adapters. Die vollständige Vorschau ist auf
  120.000 Zeichen begrenzt; sie wird bei Überschreitung abgelehnt, nicht gekürzt.
- Task-IDs werden nur über `task_snapshot` gelesen. Die Vorschau bleibt ein
  Verweis: Ein Zielclient muss Status, Abhängigkeiten, Identität, Locks und die
  native Lease vor tatsächlicher Arbeit erneut prüfen.
- Der Credential-Scan erkennt einige verbreitete Schlüssel-/Wertmuster. Er ist
  heuristisch und keine Garantie, dass jeder vertrauliche Inhalt erkannt wird;
  Request, ausgewählte Skills und Vorschau müssen vor Weitergabe geprüft werden.
- Skill-Quellenpfade werden nur als Vorschau-Metadaten ausgegeben. Der lokale
  Pfad der Blueprint-Datenbank bleibt verborgen. Quellenpfade werden nicht als
  Zugriffspfad für den Zielclient in den Prompt geschrieben.
- Eine erzeugte Vorschau belegt keine Copy-Aktion. Zwischenablage im Browser,
  Agentstart, Task-Claim, Providerwahl und Laufnachweis liegen außerhalb dieses
  Vertrags.

## Integrations- und Abnahmegrenze

Geänderte Komponenten sind `hub._services.subscription_agents_composer`, der
automatisch entdeckte `hub.subscription_agents`-Handler, fokussierte Tests und
diese Architekturdokumentation. Der vorhandene HTTP-Adapter und sein
BACH-Servermount konsumieren den Composer; die Frontend-Seite lebt im
gemeinsamen GUI-Repository. Neben der Quell-/Testabnahme auf dem vorgesehenen
Mac bleiben die produktive Geräte-/Browserabnahme, die Darstellung des
Vorschau-Status und der tatsächliche Ocean-Adapter zu prüfen. Ein grüner Komposertest würde weder
Providerverfügbarkeit noch Berechtigungen oder reale Agentenausführung belegen.

## Arbeitskontext und Bootquellen

`target_client.workspace` ist ein optionales einzeiliges Metadatum bis
1.024 Zeichen. Der Composer prüft weder die Existenz noch den Zugriff und
liest oder erstellt dort keine Datei. Anfragen ohne das Feld behalten ihre
bisherige Zielclient-Projektion. Zielclient und Zielhost bleiben Nutzereingaben,
kein attestierter Launcher- oder Fähigkeitsnachweis.

Boot- und Onboarding-Skills müssen aus der tatsächlichen Skillbibliothek
ausgewählt werden. Eine historische Root-SKILL.md oder ein fehlender
BACH-Skill wird nicht als aktuell geprüfte Bootquelle vorausgesetzt. Die
vollständige Bootquellen-Abnahme bleibt offen, bis passende Quellen
empirisch geprüft und eingebunden sind.

## Bootquellen mit gebundener Revision (Vertrag v2)

`bach.subscription-agent-onboarding.request.v2` erweitert denselben Composer
um zwei ausdrücklich zugeordnete Bootrollen: `system` und `bach`.
Beide verweisen mit Skill-ID und `source_version` auf die vorhandene
Skillbibliothek. Die Quellenversion ist der SHA-256 der vollständigen UTF-8-Datei
aus der Bibliotheksantwort, keine frei gewählte Versionsbezeichnung.

Zusätzlich zu den Feldern des v1-Beispiels enthält der Request:

```json
{
  "schema": "bach.subscription-agent-onboarding.request.v2",
  "boot_sources": {
    "system": {"id": "system-onboarding", "source_version": "<64 lowercase hex characters>"},
    "bach": {"id": "bach", "source_version": "<64 lowercase hex characters>"}
  }
}
```

Dies ist ein Feldbeispiel, keine vollständige ausführbare Anfrage. Die IDs
müssen in der tatsächlich konfigurierten Skillbibliothek vorhanden sein und
die Platzhalter durch deren aktuelle Hashes ersetzt werden. Der Composer
wählt keine Anleitung allein aufgrund eines Dateinamens und liest keine
beliebigen vom Request vorgegebenen Root- oder Workspace-Dateien.

Beide Rollen sind erforderlich; unbekannte Rollen und zusätzliche
Referenzfelder werden abgewiesen. Dieselbe Quelle darf beide Rollen tragen,
muss dabei aber denselben Hash haben. Bootquellen, Blueprint-Skills und
zusätzlich gewählte Skills werden gemeinsam nach Skill-ID dedupliziert.
Alle zusammen unterliegen der vorhandenen Grenze von 30 Quellen und dem
unveränderten Textbudget. Ein ausdrücklich gebundener Bootpin, der nicht
mehr zur gelesenen Datei passt, stoppt die Vorschau vor Task- und
Governance-Lesungen. Die Skilltexte werden zusätzlich durch den vorhandenen
Pinvalidator erneut gelesen. Die erste gelesene UTF-8-Fassung wird ebenfalls
gegen ihren angegebenen Hash geprüft.

Fehlende oder ungültige Bootquellen bleiben im Quellenbeleg sichtbar und
führen zu `needs_sources`. Eine solche Vorschau ist unvollständig.
Die verfügbaren Skilltexte werden vollständig eingebettet; keine Kürzung,
kein zweiter Bootspeicher und keine zusätzliche Dateisuche.
Die Rollen `system` und `bach` sind vom Aufrufer vergebene Zuordnungen,
keine maschinell bestätigte fachliche Eignung oder Policyautorität.

Die Antwort verwendet `bach.subscription-agent-onboarding.preview.v2`.
Sie enthält zusätzlich die gebundenen `boot_sources` sowie
`boot_delivery` mit `mode=text`, `source=current_skill_library`,
`target_readability_verified=false` und
`role_suitability_verified=false`.
Die vorhandenen `skill:<id>`-Quellenbelege erhalten `boot_roles`;
dieselben Texte und Belege werden bei Mehrfachauswahl nicht dupliziert.
Der erzeugte Prompt benennt Bootrollen, erwartete Hashes und fehlende Quellen.

CLI, Library-API und vorhandener BACH-HTTP-Transport verwenden denselben
Composer. Der HTTP-Adapter gibt keine internen Fehlermeldungen oder
Requestinhalte aus. v1 bleibt separat erhalten und enthält diese zusätzlichen
Antwortfelder nicht; vorhandene v1-Clients werden nicht automatisch auf v2
umgestellt und belegen keine Bootquellen-Abnahme.

Noch offen sind die v2-Auswahl und Antwortprüfung im gemeinsamen GUI-Client,
die tatsächliche Ocean-Anbindung und der Pfadmodus mit einem echten
Lesbarkeitsnachweis auf dem Zielhost. Ein auf dem Composerhost vorhandener
Pfad beweist keinen Zugriff des Zielclients. Daher erzeugt diese Erweiterung
ausschließlich vollständige Texte und behauptet keinen bestätigten
Zielzugriff. Produktiver Geräte-/Browsernachweis, fachliche Quellenprüfung
und vollständige Task2029-Abnahme bleiben eigene erforderliche Schritte.
