# NemoFold-Adapter für native Sequenzen

Stand: 2026-10-11 · Task #2001 · Proposal-Adapter, keine Produktivpromotion.

## Vertrag

`build_native_sequence_proposal(candidate)` bildet ausschließlich einen aktuell
inhaltlich geprüften, versionsgebundenen NemoFold-Kandidaten ab. Die Eingabe muss
Status und Review-Receipt für dieselbe `candidate_id`, `candidate_revision` und
denselben SHA-256-Digest tragen. Der Adapter prüft zusätzlich den kanonischen
Provider-Payload gegen den gespeicherten Vorschlagsdigest.

Die Antwort hat genau die Felder `schema`, `source`, `definition` und `resolved`.
`source` bindet Anbieter, Kandidaten-ID, Revision und Digest. `definition` wird
mit dem vorhandenen `SequenceStore.definition(...)`-Validator kanonisiert.
`resolved.config_version` bindet den vorhandenen System-Agentenstand;
`resolved.agent_slots` und `resolved.skills` nennen nur die tatsächlich
verwendeten Referenzen samt Version.

## Auflösung und Grenzen

Ein Schritt muss eine vorhandene Workerreferenz enthalten. `agent_slot` wird als
exakte System-Agenten-ID aufgelöst. Ein historisches `agent` darf nur exakt einer
vorhandenen System-Agenten-ID oder einem eindeutigen angezeigten Registry-Namen
entsprechen. Fehlende, mehrdeutige, deaktivierte oder nicht als Worker
konfigurierte Einträge bleiben gesperrt. Es wird kein Standardagent gewählt und
kein Agent angelegt.

Aus `skill_ids` werden aktuelle native `SKILL.md`-Quellversionen gepinnt.
Fehlende Skills, doppelte oder ungültige IDs und ungültige Digests blockieren den
Vorschlag. Ein geänderter Agenten-Konfigurationsstand wird während der Auflösung
abgewiesen. Ändert sich später die aufgelöste Konfiguration oder Skillquelle,
weicht der erneute Proposal vom ursprünglichen Proposal ab und der
Promotions-Callback bricht vor Zielmutation und Receipt mit einem Konflikt ab.

Legacy-Schritte mit nichtleeren `tool`- oder `inputs`-Feldern bleiben
`unsupported_legacy_tool_semantics`. SequenceStore-Schritte führen keinen
NemoFold-Toolaufruf aus; eine sprachliche Wiedergabe dieser Felder würde eine
funktionsgleiche Migration vortäuschen. Solche Kandidaten benötigen zuerst einen
gesonderten, geprüften Stepvertrag. `trigger_type`, statische TÜV-Metadaten und
Reversibilitätsangaben lösen keine Ausführung aus und gelten nicht als
Ausführungsbeleg.

Die bestehenden Feldnamen `agent_slot` und `agent_slots` bezeichnen hier
versionierte Sequenz-/Worker-Registry-Referenzen. Sie reservieren keine lokalen
Modellressourcen für Cloudagenten und erzeugen keine physischen Slots.

## Transaktion und Betriebsgrenze

Der Adapter ist rein lesend: keine SQL-Änderung, kein SequenceStore-Write, keine
Agentenerzeugung und kein Sequenzstart. `LearningPromotionService` erstellt
zunächst einen Proposal. Innerhalb derselben nativen SequenceStore-
Schreibtransaktion lädt der Source-Validator den weiterhin geprüften Kandidaten
mit derselben Revision und demselben Digest erneut, baut den Proposal erneut und
vergleicht ihn exakt mit dem ersten. Erst danach darf der SequenceStore sein
Ziel-CAS und Receipt schreiben. Geänderte Quelle, Agentenkonfiguration oder
Skillversion führen vorher zum Konflikt.

Das Inhaltsreview bedeutet keine empirische Validierung. Der Adapter belegt
weder die funktionale Gleichwertigkeit beliebiger Legacy-Tools noch die
Produktivkonfiguration, Freigabe oder Ausführung einer Sequenz. Veröffentlichung,
Start, unabhängige Wiederverwendung und empirische Lernabnahme bleiben getrennte
Schritte.
