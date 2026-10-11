# Empirischer Lernkreislauf #2002

## Status und Aussagegrenze

Der isolierte Mac-Lauf für Stufe 1 ist mit 7 Tests und Exitcode 0 abgeschlossen. Er umfasste die synthetische Hermes-Quelle, Review, native Promotion, erneutes Lesen über den vorhandenen Memoryhooker-Pfad in einer frischen Sitzung und Scanner-Guard-Regressionen. Receipt-SHA-256: `cad9040b59d39112e78517a08bd80105b452d3e829bcc97c5b9c0ecbdf9ce381`; Log-SHA-256: `a1a07a478beb9d211da5ef56226b4e336869aa40642e5019b4abe27b3815ec68`. Das belegt den Servicepfad für die synthetische Fixture, keine Antwortqualität und keine Laufzeitwirkung in einer echten Nutzersitzung.

Stufe 2 ist weiterhin nicht ausgeführt. Der festgeschriebene Plan lässt Modell, Modellrevision, Tokenizerrevision und tatsächlich promovierte Quellrevision absichtlich offen; der Harness muss vor Kontextabruf und Inferenz abbrechen, bis diese Bindungen in einer neuen konkreten Präregistrierung stehen.

Ein Review ist eine Inhaltsentscheidung. Es ist kein Empiriebeleg. Eine Promotion speichert eine freigegebene Lesson; sie setzt den Wert **empirically_validated** nicht auf wahr und startet keinen Agenten. Stufe 2 bleibt offen, bis der festgelegte Lauf und die verblindete Bewertung tatsächlich abgeschlossen sind.

## Stufe 1: reproduzierbarer Servicepfad

Der Regressionstest system/tests/test_learning_reuse_empirical.py führte den echten lokalen Servicepfad gegen tmp_path/data/bach.db aus:

1. Hermes liest die festgeschriebene synthetische Quellsitzung aus system/tests/fixtures/learning_reuse/source-session-v1.json.
2. Der Kandidat beginnt als Entwurf. Der Promotionsversuch vor dem Inhaltsreview muss scheitern und darf keine aktive Lesson anlegen.
3. Ein explizites Review bindet Kandidaten-ID, Revision und Digest. Das Receipt bleibt auf candidate_content_only; empirically_validated und targets_published sind falsch.
4. Der native Promotionsservice veröffentlicht genau diese Revision in der isolierten memory_lessons-Tabelle. Receipt, Revision, Digest und Zielversion werden erneut gelesen.
5. Eine neue, leere ChatRuntime-Sitzung ruft den echten memoryhooker-Adapter gegen dieselbe temporäre Datenbank auf. Der zurückgegebene Kontext muss den Titel und den Inhalt der Lesson enthalten. Es wird kein ChatRuntime.process aufgerufen und kein Modell angesprochen.

Der Test bindet das unveränderliche Fixture-Manifest SHA-256 `4892a1823bc07618d3e4723946a62e6f3d95345b5aa4f868cd184a28f5d429e0`. Das Manifest bindet Bytezahl und SHA-256 der synthetischen Quellsitzung, des festen Panels, des Stufe-2-Plans und der Datenschemas. Änderungen an Panel, Quelltext oder Plan brauchen eine neue, vorab dokumentierte Revision; sie dürfen nicht nach Sichtung von Ergebnissen still ersetzt werden.

Der Harness importiert den nativen Promotionsservice aus PR #322. Bis dessen Vertrag in main verfügbar ist, muss der Test in einer ausdrücklich darauf gestapelten Integrationskomposition laufen. Ein übersprungener oder gemockter Promotionsschritt zählt nicht als Abnahme.

## Stufe 2: präregistrierter Vergleich

`system/tests/learning_reuse_stage2.py` enthält den test-only Ablauf. Der vorhandene Backend-Aufruf, Tokenizer, Kontextlieferant und private Rohdatenspeicher müssen explizit injiziert werden. Es gibt keine Backend-Discovery, keinen Provider-Fallback und keine Zugangsdatenauflösung in diesem Modul. Die Tests verwenden nur einen synthetischen Callback; das ist kein Modelllauf und misst keine Antwortqualität.

Der festgeschriebene Plan `paired-experiment-plan-v1.json` bindet Quellsitzung `2045da786ef663755d24a6e09dcae278b7d2c7e042ac1325934d18a40ea68ee0` und Panel `88948d9c3ac4ee9dd2e1e819785c9b23406aabd6b065a13af9ed41fe95ad0d02`. Er setzt 128 Tokens für den reservierten Kontextplatz, höchstens 512 Tokens für die gesamte Eingabe und 512 Ausgabetokens fest. Ein Paar ist nur gültig, wenn beide Bedingungen mit dem exakt gebundenen Tokenizer dieselbe Kontext- und Eingabetokenzahl erreichen. Vor dem Kontextabruf muss ein verpflichtender Read-only-Bindungsprüfer die exakte Modell- und Tokenizerrevision im vorhandenen Backend- beziehungsweise Tokenizerbestand bestätigen. Eine nicht bestätigte Revision, ein unbekanntes Quellartefakt, eine Budgetabweichung oder eine geänderte Panel-/Quellhashbindung stoppt vor Kontextabruf und Backendaufruf. Der Prüfer darf keine Inferenz starten.

Das feste Panel enthält acht synthetische, voneinander unabhängige Fälle. Jeder Fall wird genau einmal in zwei Bedingungen ausgeführt:

- **A, Kontrollbedingung:** fester neutraler Inhalt im reservierten Lernkontextplatz.
- **B, Wiederverwendung:** die exakt gebundene, geprüfte und promovierte Lesson im selben Kontextplatz.

Beide Bedingungen verwenden denselben Provider, dieselbe Modell-ID und Modellrevision, dieselben Inferenzparameter, denselben Prompt, dieselben übrigen Kontextquellen, dieselben Werkzeugrechte und dieselbe Ausgabelänge. Beide starten in einer neuen leeren Sitzung. Der reservierte Kontextplatz muss mit dem Tokenizer des geprüften Modells auf dieselbe Tokenzahl gebracht werden. Wenn das nicht gelingt, wird der Lauf als Protokollabweichung dokumentiert und nicht als gültiges Paar gezählt. Der Kontrolltext enthält keine Lösungshinweise.

Die Reihenfolge der Fälle und der beiden Arme je Paar wird mit dem vorab festgelegten Algorithmus `sha256-rank-v1`, Seed `2002`, bestimmt. Der erwartete Reihenfolgedigest ist `500c6fd31bfbd84d0a09974c1dd1a810d1eb300a0d088b6c44edf049e93e1f63`. Die Anzeige der verblindeten Einreichungen verwendet Seed `2003` und enthält keine Laufreihenfolge. Es gibt genau 16 geplante Aufrufe, keine Wiederholung, keinen automatischen Retry, keinen Provider-Fallback und keine nachträgliche Fallauswahl. Timeout, Providerfehler, leere Antwort und Ausgabebudgetverletzung bleiben im Nenner und gelten als Fehlschlag. Ein fehlgeschlagenes Paar wird nicht durch einen neuen Fall ersetzt; das Blindpaket enthält dafür eine leere Antwort, aber keinen Fehlerstatus.

### Rohdaten

`raw-run-record.schema.json` beschreibt die vertrauliche Rohzeile. Sie bindet Planhash, Paar, vorab bestimmte Laufnummer, Seed, Fall, anonyme Einreichungs-ID, Bedingungscode, Modell- und Tokenizerrevision, feste Parameter, Prompt-/Kontexthash, Kontext-/Eingabe-/Ausgabetoken, Laufzeit, Ergebnisstatus, Ausgabedigest und Quellartefakt-Revision. Das Schema setzt `retry_count` auf `0`. Der explizit injizierte private Rohdatenspeicher erhält die Rohzeile und vollständige Antwort. Das zurückgegebene Blindpaket enthält absichtlich den verblindeten Antworttext zur Bewertung, aber keine privaten Lauf-, Modell-, Provider-, Tokenizer-, Bedingungs- oder Revisionsmetadaten. Ein Fehler des Speichers bricht ab und löst keinen Wiederholungslauf aus.

### Verblindete Bewertung

Vor dem Lauf erzeugt der Harness zufällige Einreichungs-IDs und hält die Zuordnung zu A/B ausschließlich in den privaten Rohzeilen. Bewertende erhalten über eine strikte Allowlist nur Schema, Fall, Einreichungs-ID, Prompt und Antwort. Modell, Provider, Tokenizer, Bedingung, Kandidatenrevision, Digest, Zielversion und Laufreihenfolge fehlen im Blindpaket. `blind-rating.schema.json` bleibt geschlossen und erlaubt keine zusätzlichen Metadaten.

Zwei Bewertende scoren unabhängig vier festgelegte Dimensionen von 0 bis 2: Korrektheit, Vollständigkeit, Einhaltung der Vorgaben sowie Belege und Prüfung. Zusätzlich markieren sie kritische Fehler und begründen die Bewertung. Der Fall gilt nur dann als bestanden, wenn beide Bewertenden jede Dimension mit mindestens 1 bewerten und keinen kritischen Fehler markieren. Differenzen werden anhand derselben verblindeten Antwort geklärt. Scores werden eingefroren, bevor die Zuordnung A/B geöffnet wird.

### Auswertung und Bericht

Primärer Messwert ist die Zahl bestandener gepaarter Fälle je Bedingung, mit der paarweisen Differenz und einer Liste aller Timeout-, Provider- und Leerantworten. Sekundär werden die vier Dimensionswerte und kritische Fehler je Fall berichtet. Bei acht Fällen wird ausschließlich die beobachtete Panelleistung beschrieben; daraus folgt keine allgemeine Erfolgswahrscheinlichkeit oder übertragbare Qualitätssteigerung. Es gibt keine Erfolgsbehauptung aus Hermes-Konfidenzwerten, Nutzungszählern, Review-Receipts oder Promotion-Receipts.

## Noch offene Laufgrenzen

- Bei erfolgreichem Lauf belegt der Test Wiederauffinden im bestehenden Memoryhooker-Kontextpfad, nicht die fachliche Richtigkeit einer Antwort.
- Die feste Panel-, Plan- und Rohdatenstruktur ist vorbereitet; echte Stufe-2-Rohantworten und Ratings liegen noch nicht vor. Die Präregistrierung enthält noch keine konkrete Modell-/Tokenizerrevision oder promovierte Quellartefaktrevision.
- Die Stufe-2-Regression prüft mit einem synthetischen Callback Einmalaufruf, Paarbindung, Tokenbudget und Blind-Allowlist. Sie ist kein Qualitäts- oder Providerbeleg.
- Ein späterer Modelllauf braucht eine konkrete Harness- und Runtimekoordination. Dieses Paket startet weder Provider noch Modell, verändert keine Produktivdaten und aktiviert keine automatische Lernschleife.
- Der isolierte Stufe-1-Maclauf und die unabhängige Root-Prüfung liegen vor. Der Test bleibt vom nativen Promotionsservice aus PR #322 abhängig, bis dessen Vertrag in `main` verfügbar ist; der isolierte Lauf ist kein Main-Integrationsnachweis.
