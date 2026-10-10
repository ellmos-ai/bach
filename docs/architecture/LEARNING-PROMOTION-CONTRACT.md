# Lernkandidaten, Inhaltsreview und native Veröffentlichung

Stand: 2026-10-10 · Task #2000, Phase A · Sourcevertrag, keine native Betriebsabnahme.

## Implementierter Vertrag

- Die beiden BACH-Services sind lokale Heuristiken. Sie belegen keine Integration des nativen Hermes-Agenten oder des nativen NemoFold-Providers.
- Neue Hermes-Lessons bleiben in `hermes_skill_candidates.lessons_draft_json`. Die Extraktion schreibt sie weder aktiv noch inaktiv nach `memory_lessons`. Bestehende Memory-Leser und Toggle-Endpunkte können diese Entwürfe damit nicht aktivieren.
- Neue Kandidaten binden ihren vollständigen Inhalt an `candidate_revision`, SHA256 `candidate_digest` und einen kanonischen Payload. Ein Hermes-Review umfasst auch die Lesson-Entwürfe.
- NemoFold aktualisiert unveröffentlichte Entwürfe in einer Schreibtransaktion. Änderungen erhöhen die Revision und invalidieren das bisherige Review. Identischer Inhalt behält ID, Revision und Entscheidung. Historisch veröffentlichte Kandidaten werden bei Änderungen abgewiesen; vorhandene Ketten bleiben erhalten.
- Altkandidaten ohne gültige Inhaltsbindung erscheinen zusätzlich als `legacy_unverified`. Historische Statusangaben bleiben erhalten und berechtigen keine neue Veröffentlichung.
- `learning_candidate_reviews` liegt in derselben BACH-Datenbank. Entscheidung, Kandidaten-CAS, unveränderlicher Payload und Receipt werden mit `BEGIN IMMEDIATE` gemeinsam gespeichert. Identische Requests bestätigen dasselbe Receipt; anders verwendete Request-IDs ergeben Konflikte.
- Ein Receipt-Replay bestätigt eine historische Entscheidung für die darin genannte Revision. Nach einer erneuten Synthese bestätigt es keine Freigabe der aktuellen Revision und ändert deren Zustand nicht.
- `reviewed` bedeutet ausschließlich **Inhaltsreview**. Das Receipt nennt `review_scope=candidate_content_only`, `empirically_validated=false` und `targets_published=false`. Statische TÜV-Metadaten, Konfidenz und deklarierte Journal-Unterstützung ersetzen keine empirische Prüfung.
- Abgelehnte oder bereits entschiedene Revisionen können nicht erneut entschieden werden. Eine Ablehnung veröffentlicht und entfernt keine Zielartefakte.
- Der native Kettenstart prüft `is_active` vor dem Laden des Ausführungsmoduls und erneut bei der transaktionalen Runanlage. Ein bestätigter identischer Startrequest bleibt ein Receipt-Replay und erzeugt keinen neuen Lauf.

## API

Für `hermes` und `nemofold` gilt unter `/api/learning/{provider}/candidates/{id}`:

| Aufruf | Vertrag |
|---|---|
| `GET` | Revision, Digest, `review_state`, `review_available`, `promotion_available=false` |
| `POST /review` | `expected_revision`, `expected_digest`, explizite `request_id` und `notes`; Antwort `reviewed`, keine Veröffentlichung |
| `POST /reject` | Dieselbe Inhaltsbindung und Request-ID, optional `reason`; Antwort `rejected` |
| `POST /approve` | Alte Direktpromotion bleibt HTTP 409 / `native_learning_promotion_unavailable` |

Die Entscheidungsendpunkte prüfen bestehende aktive Gerätetokens. Der Akteur wird serverseitig als `device:{id}` gebunden. Frei gesendete Namen wie `approved_by` verleihen keine Identität. Ungültige Parameter ergeben HTTP 422, unbekannte Kandidaten HTTP 404, Versions-/Zustandskonflikte HTTP 409.

## Offene Umsetzung; Task #2000 bleibt offen

Diese Schutzstufe erfüllt noch nicht den vollständigen Lerntransfer:

1. **#1999:** gemeinsame Quellenadapter, belastbare Provenienz, No-Signal-Verhalten, Neutralisierung und deduplizierte Kandidatenformen.
2. **#2000:** native Promotion mit Zielidentität/-version, Requestbindung, Konfliktprüfung, persistiertem Recoveryzustand und überprüfter Rücknahme.
3. **#2001:** ausdrückliche Übersetzung neutralisierter NemoFold-Kandidaten in gültige native SequenceStore-Definitionen und Auflösung echter Agenten-/Skillreferenzen. Legacy-Schritte werden nicht als ausführbare native Ketten übernommen.
4. **#2002:** empirische Wiederverwendung in einer unabhängigen Sitzung und Qualitätsnachweis außerhalb heuristischer Konfidenzangaben.
5. **#2003:** vollständiger Herkunfts- und Dokumentationsabgleich mit den tatsächlich angeschlossenen Providern.
6. **Gemeinsame GUI:** Reviewfelder und echte Zustände anbinden. Alte Approve-/Reject-Caller ohne Voraussetzungen dürfen keine Mutation bewirken.

Die Zielautoritäten bleiben `SequenceStore`, `skill_source_service` und `memory_lessons`. Ein `skill_versions`-INSERT veröffentlicht keine ausführbare `SKILL.md`. Dateisystem- und Datenbankaktionen benötigen einen ehrlichen Recoveryvertrag; gemeinsame Atomizität wird nicht behauptet.

## Prüfgrenzen

Die Regressionstests verwenden isolierte Datenbanken, gespeicherte Receipts, Inhaltsänderungen, echte Transaktionsfehler per Trigger und die native Runanlage. Die native Sequenzsuite verwendet das gepinnte MarbleRun-Modul. Produktive Tasks, Geräte, Lessons und Ketten werden dafür nicht verändert.

Sourceprüfung und CI ersetzen weder Mergefreigabe noch Deploy, Geräteprüfung oder empirische Lernabnahme. Historisch aktive Lessons werden ohne belegte Kandidatenzuordnung nicht nachträglich umklassifiziert.
