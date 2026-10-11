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
überschrieben werden. Die SHA-256 bindet die tatsächlich verwendete Projektion,
nicht die vollständige Datenbankzeile. Der lokale Datenbankpfad wird nicht
ausgegeben.

## Transportvertrag

Requestschema: `bach.subscription-agent-onboarding.request.v1`.

```json
{
  "schema": "bach.subscription-agent-onboarding.request.v1",
  "target_client": {"client_id": "codex-cli", "host": "client-host"},
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
Eine spätere HTTP-Route kann `SubscriptionAgentsComposer.compose(request)` direkt
aufrufen. Dieses Paket registriert keine HTTP-Route; die bestehende Route
`POST /api/agent-studio/synthesize-prompt` bleibt beim bisherigen Blueprint-Prompt.
Eine künftige Remote-Integration braucht vor Freigabe einen eigenen Authentifizierungs-
und Datenschutzvertrag für die ausgewählten lokalen Inhalte.

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
diese Architekturdokumentation. Gemeinsame HTTP-Router und GUI-Dateien bleiben
außerhalb dieses Pakets. Vor einer Integration sind die Quell-/Testabnahme auf
dem vorgesehenen Mac, ein separater HTTP-Aufrufvertrag und die Darstellung des
Vorschau-Status im GUI erforderlich. Ein grüner Komposertest würde weder
Providerverfügbarkeit noch Berechtigungen oder reale Agentenausführung belegen.
