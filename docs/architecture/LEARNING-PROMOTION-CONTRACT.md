# Lernkandidaten, Inhaltsreview und native Veröffentlichung

Stand: 2026-10-11 · Task #2000, Phase B Sourcepaket · Keine Produktivpromotion oder Betriebsabnahme.

## Schutzvertrag

- Die lokalen Hermes- und NemoFold-Services erzeugen Kandidaten. Sie belegen keine native Integration oder empirische Wirksamkeit.
- Kandidaten binden ihren vollständigen Inhalt an candidate_revision, SHA256 candidate_digest und einen kanonischen Payload. Das gespeicherte Review-Receipt bindet sich an genau diese Quelle.
- reviewed bedeutet ausschließlich **Inhaltsreview**. Das Review-Receipt nennt review_scope=candidate_content_only, empirically_validated=false und targets_published=false. TÜV-Metadaten, Konfidenz und deklarierte Unterstützung ersetzen keine empirische Prüfung.
- Eine native Promotion ist ein eigener, zieltypgebundener Request. Request-ID, Akteur, Kandidatenrevision/-digest, Zieltyp und erwartete Zielversion werden zusammen gebunden. Abweichende Wiederverwendung einer Request-ID und veraltete Zielversionen scheitern geschlossen.
- Es wird keine gemeinsame Atomizität zwischen BACH-Datenbank und Dateisystem behauptet. learning_promotions speichert vor dem Zielschreibvorgang den unveränderlichen Request- und Payload-Snapshot. Native Zielversionen werden nach dem Schreiben zurückgelesen. Ein Neustart kann prepared anhand von vorheriger und gewünschter Zielversion fortsetzen; ein dritter Zielzustand wird Konflikt. Rücknahme stellt nur wieder her, wenn das Ziel noch exakt der veröffentlichten Version entspricht.

## Native Hermes-Skills

Die Skill-Promotion schreibt ausschließlich über skill_source_service in einen konfigurierten nativen Skill-Root. Der vorbereitete Request bindet die Vorversion an source_kind, absolute Root, relativen Quellpfad und Quelldigest sowie die Sollzielquelle an die erwartete Write-Root, den relativen SKILL.md-Zielpfad und den gewünschten Digest. Das öffentliche Receipt enthält nur Bindungsdigests. Write, Crash-Recovery und Rücknahme akzeptieren genau diese Zielquelle; ein Wechsel der Write-Root führt zum Konflikt, selbst wenn in der neuen Root bytegleiche Zieldaten liegen. Der Schreib-Readback muss die vollständige gebundene Zielquelle bestätigen. Ein bekannter nativer skill_source_version_conflict wird als Promotionskonflikt HTTP 409 ausgegeben, unbekannte RuntimeError bleiben interne Fehler.

Der Quell-Digest und das Inhaltsreview bleiben an den unveränderten Kandidaten gebunden. Die deterministische Transformation serialisiert ausschließlich das typisierte YAML-Frontmatter; der Markdown-Body bleibt bytegleich. Der vollständige YAML-Header muss nach sicherem Parsen dem gebundenen Frontmatter-JSON entsprechen. Doppelte YAML-Schlüssel, ungültige oder inkonsistente Header werden abgewiesen. Eine eng begrenzte Legacy-Ausnahme kann eine ungequotete, einzeilige Hermes-Beschreibung mit Doppelpunkt übernehmen, wenn ihr roher Text exakt dem geprüften description-Wert entspricht; nur dieser Wert wird für die Ausgabe korrekt gequotet. Mehrzeilige Beschreibungen und sonstige YAML-Fehler werden nicht repariert. Die Frontmatter-Schlüssel werden sortiert, Unicode bleibt erhalten.

Nach einem Zielschreib-Crash vergleicht die Wiederaufnahme den gespeicherten Ziel-Digest mit dem nativen Readback. Eine identische Zielversion schließt die vorbereitete Promotion ab; die Vorversion erlaubt eine sichere Wiederholung. Fremde Änderungen bleiben Konflikt. Bei einer Rücknahme wird ein zuvor vorhandener lokaler Override aus der nativen Versionshistorie wiederhergestellt. War die Vorversion eine System-/Factory-Quelle oder war keine Quelle vorhanden, wird nur der neu angelegte lokale Override per Delete-CAS entfernt; davor und danach muss die gebundene darunterliegende Root-/Quellversion übereinstimmen. Eine inzwischen geänderte Systemquelle bleibt geschützt und führt zum Konflikt. Eine Promotion ändert weder die Inhaltsreview-Entscheidung noch vergibt sie Werkzeuge oder startet Agenten.

## Hermes-Lessons

Neue Hermes-Lessons bleiben bis zur ausdrücklichen Promotion in hermes_skill_candidates.lessons_draft_json. Die Promotion schreibt ausschließlich in den vorhandenen nativen memory_lessons-Speicher, prüft doppelte Titel und speichert Ziel-IDs/Snapshots gemeinsam mit dem Request. Transaktionsfehler rollen die Zieländerungen zurück. Eine Rücknahme löscht keine Lesson-Zeile, sondern setzt die gebundene Zielzeile per CAS auf is_active=0 und bewahrt sie samt Zusatzfeldern. Der CAS bindet ausschließlich ID, category, title und solution; updated_at wird bei der Deaktivierung aktualisiert; sonstige nicht gebundene Zusatzspalten werden nicht verglichen und bleiben unverändert. Ein Aktivstatus von 1 wird per CAS auf 0 deaktiviert. Ein bereits auf 0 gesetzter Status bleibt unverändert und zählt als already_inactive; Werte außerhalb von 0 und 1 blockieren. target_snapshot_json dokumentiert die gebundenen Inhaltsfelder samt ursprünglichem Aktivstatus, aber keinen vollständigen Zeilensnapshot. Geänderte Inhaltsfelder blockieren die Rücknahme.

## NemoFold und #2001

Ungültige Legacy-steps werden nicht in ausführbare Sequenzen übersetzt. Ohne eine geprüfte native Definition und echte Agenten-/Skillauflösung bleibt die Promotion waiting_for_native_definition; daraus folgt weder eine Sequenz noch ein allgemeines targets_published=true. Der Codepfad akzeptiert ausschließlich das native, zieltypisierte SequenceStore-Format und bestätigt Digest, Konfigurationsversion, referenzierte Slots/Skills und Ziel-CAS. Ein isolierter Adapterfixture ist kein Ersatz für den #2001-Providervertrag. Die produktive native Übersetzung wird erst nach dessen Review und Integration angeschlossen.

## API

Für hermes und nemofold gelten die versionierten Kandidatenendpunkte:

| Aufruf | Vertrag |
|---|---|
| GET /api/learning/{provider}/candidates/{id} | Revision, Digest, review_state, review_available und zieltypbezogener Promotionszustand; promotion_available ist genau dann wahr, wenn mindestens ein Ziel ready_for_target_cas meldet |
| POST /api/learning/{provider}/candidates/{id}/review | Inhaltsreview für die exakt gebundene Revision; keine Veröffentlichung |
| POST /api/learning/{provider}/candidates/{id}/reject | Ablehnung der exakt gebundenen Revision; keine Zielmutation |
| POST /api/learning/{provider}/candidates/{id}/promote | Native Veröffentlichung mit Request-ID und erwarteter Zielversion |
| POST /api/learning/{provider}/candidates/{id}/revoke | CAS-gebundene Rücknahme einer konkreten Promotionsrequest |

Das promotion_available-Feld in Listenprojektionen ist veraltet; dort verweist promotion_availability_replacement auf promotion_targets.targets.<target_kind>.state. Kandidatendetails berechnen das Kompatibilitätsfeld aus genau diesen Zielzuständen. Der Akteur wird serverseitig aus dem authentifizierten Gerätetoken gebunden. Frei gesendete Namen wie approved_by verleihen keine Identität. Alte direkte Approve-Aufrufe bleiben gesperrt. Ungültige Parameter ergeben HTTP 422, unbekannte Kandidaten HTTP 404, Versions-/Zustandskonflikte HTTP 409. NemoFold meldet zieltypbezogen waiting_for_native_definition, solange #2001 keine gültige native Definition liefert.

## Offener Umfang

Task #2000 bleibt offen, bis Quellpaket, Ziel-CAS, Receipt-Wiederholung, Crash-Recovery und Rücknahme integriert und im Rootreview abgenommen sind. Dieses Paket nimmt keine Produktivpromotion vor.

- **#2001:** native NemoFold-Kettendefinitionen und echte Agenten-/Skillauflösung; dieser Adapter bleibt Voraussetzung für NemoFold-Promotion.
- **#2002:** empirische Wiederverwendung in einer unabhängigen Sitzung und Qualitätsnachweis außerhalb heuristischer Konfidenzangaben.
- **#2003:** vollständiger Herkunfts- und Dokumentationsabgleich mit den tatsächlich angeschlossenen Providern.
- **Gemeinsame GUI:** bestehende Review- und Statusfelder anbinden. Alte Approve-/Reject-Caller ohne Voraussetzungen dürfen keine Mutation bewirken.

## Prüfumfang und Grenzen

Die Regressionen verwenden isolierte Datenbanken, temporäre Skill-Roots, persistierte Receipts, inhaltliche Änderungen, CAS-Konflikte und simulierte Prozessunterbrechungen. NemoFold-Tests belegen ausschließlich das isolierte native SequenceStore-Format, nicht die #2001-Integration.

Quellprüfung und CI ersetzen weder Mergefreigabe noch Deploy, Geräteprüfung oder empirische Lernabnahme. Historisch aktive Lessons werden ohne belegte Kandidatenzuordnung nicht nachträglich umklassifiziert. Es wurden keine produktiven Tasks, Geräte, Lessons, Skills oder Ketten für diese Tests verändert.
