# Native Taskmaster-Vorlagen v1

Die vorhandenen fachlichen Vorlagen heißen `taskmaster-maintainer` und
`taskmaster-operator`; dieselben Namen dienen als Rollenkennungen.
Numerische IDs werden nativ vergeben. Es gibt keine reservierten IDs.

## Fachliche Anforderungen und echte Skillbindung

Die Begriffe aus Auftrag2325 sind fachliche Anforderungen, keine erfundenen
Registry-IDs. Die Vorlagen referenzieren folgende tatsächlich auflösbare Skills:

| Rolle | Erhaltene Anforderung | Kanonische Skill-IDs und belegte Zuständigkeit |
| --- | --- | --- |
| Maintainer | dedup | `docs-analysis` konsolidiert doppelte Dokumentpunkte unter Erhalt ihrer Quellen; `tidy-up` behandelt doppelte Kopien und Registerhygiene; `folder-organization` ergänzt inhalts-/hashgestützte Zuordnung und reversible Archivierung |
| Maintainer | project-docs | `docs-analysis` prüft Anforderungen und konsolidiert Pläne; `tidy-up` pflegt Projekt- und Pipeline-Dokumentation |
| Maintainer | maintenance | `tidy-up` pflegt Register und Projektbestände; `folder-organization` erhält Vorgänger/Nachfolger, Originale und Rückwege |
| Operator | scheduling | `operator` wählt belegte nächste Schritte und Prioritäten; `orchestrator` koordiniert unabhängige Pakete und gemeinsame Scopes |
| Operator | budgeting | `budgetierung` führt Modellkontingente, Zeitfenster und tatsächliche Reviewer-/Advisor-Einsätze; `orchestrator` beachtet verfügbare Budgets |
| Operator | review | `operator` behält Integration und Abnahme; `orchestrator` prüft Ergebnisse gegen Auftragsvertrag und aktuelle Evidenz |

Maintainer bindet `docs-analysis`, `tidy-up`, `folder-organization`.
Operator bindet `operator`, `orchestrator`, `budgetierung`.
Die Primärtexte des bestehenden nativen Skillkatalogs sind maßgeblich;
`budgetierung` bezeichnet hier Modellkontingente, keine privaten Finanzen.
Die Kombination für dedup ist keine Behauptung einer allgemeinen Dedup-Engine.
Der Operator führt keine eigene Claimqueue.

Alle sechs IDs müssen im vorhandenen Resolver auflösbar sein. Der native
Readback muss `skills_validation.valid=true`, die sechs Zuordnungen sowie
deren tatsächliche Versionen und Quellversionen zeigen. Ein lokaler Skilltext
darf nicht ohne Hashgleichheit als identisch mit der Mac-Quelle bezeichnet werden.

## Additive Erstanlage und Schutz

Der vorhandene `seed_default_blueprints` legt die zwei Rollen additiv an:
`kind=agent`, `is_template=1`, `is_materialized=0`, initial `version=1`.
`INSERT OR IGNORE` erhält vorhandene Namen, Revisionen und Zuordnungen.
Ein gleichnamiger Benutzer- oder unerwarteter Systemeintrag ist ein Konflikt,
kein erfolgreicher Vorlagennachweis. Bestehende coding-agent-,
taskmaster-writer- und taskmaster-solver-Einträge bleiben unverändert.

Governance erlaubt zunächst nur `read_files` und `search_content`.
Skillauflösung erteilt keine Werkzeugrechte und belegt keinen Skill- oder
Agentenlauf. Materialisierung und Starts benötigen eigene Autorität.

## Explizite Migration der früheren sechs Platzhalter

Die ursprünglichen Seeds mit den nicht auflösbaren Listen
`dedup/project-docs/maintenance` und `scheduling/budgeting/review` benötigen
eine gezielte Migration. Gewöhnliches `POST /api/agent-studio/blueprints`
bleibt für Systemvorlagen gesperrt.

Nach Bereitstellung der geprüften Quelle wird der vorhandene native API-Weg
um `POST /api/agent-studio/bootstrap/taskmaster-skills` ergänzt.
Er verwendet denselben Geräteschutz wie der vorhandene Bootstrap.
Der Body enthält ausschließlich `expected`: genau zwei Objekte mit
`id`, `name`, `expected_version` und `content_sha256` aus dem frischen GET.
Die IDs stammen aus dem Readback, nicht aus historischen Annahmen.

Die Migration akzeptiert nur die zwei festen fachlichen Namen, native
Version1, die exakten alten Skilllisten und unveränderte Inhaltspins.
Beide Einträge müssen agent/template/unmaterialized sein, die passende
Rollenkennung tragen und ohne externe Providerbindung bestehen.
Der bestehende Resolver muss alle sechs neuen Skill-IDs bestätigen.
Eine eigene atomare Transaktion prüft beide Einträge vor Änderungen.

Caller können keine Ersatzskills, Rollen, Prompts oder Rechte übergeben.
Geändert werden ausschließlich `skills_json`, `version` und `updated_at`;
Version1 wird zu Version2. IDs, alle anderen Felder und sämtliche fremden
Vorlagen bleiben erhalten. Ein falscher Pin, höherer Versionsstand,
materialisierter oder unerwarteter Eintrag beendet die gesamte Migration
ohne Teiländerung. Wiederholte alte Pins ergeben einen Konflikt.
Es gibt keine neue Tabelle und keine Freigabe allgemeiner Systemtemplate-Saves.

## Tatsächliche Abnahme

Authentifizierter GET vor und nach dem einmaligen nativen Bootstrap bzw.
der expliziten Migration: beide Identitäten, Rollen, auflösbare Skills,
Versionen und Vorlagenflags auslesen. Sämtliche zuvor vorhandenen fremden
Zeilen anhand ihrer IDs, Versionen und Inhalte unverändert bestätigen.
Nach einem Transporttimeout zuerst unabhängigen Zustand lesen;
keinen POST blind wiederholen.

Quellreview, automatische CI, Commit/Push und Bereitstellung getrennt belegen.
Ein erfolgreicher POST allein genügt nicht. Keine Materialisierung,
kein Workerstart, kein Skilllauf und keine zweite Task- oder Skillquelle.
