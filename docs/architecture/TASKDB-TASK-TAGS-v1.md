# TaskDB Task-Tags (v1)

**Referenz:** Task `#2065` (`BACH: offizielles Task-Tag-Update ergänzen und githubbot-ocean nachtragen`).

## Zweck

`tasks.tags` existierte als Spalte (Schema: „JSON-Array“), hatte aber keinen nativen, auditierten Schreibweg;
alle Zeilen standen auf `NULL`. Dieser Vertrag legt den einzigen zulässigen Weg fest. Direkte SQLite-Schreibzugriffe
bleiben ausgeschlossen.

## Speicherform

Immer ein kompaktes JSON-Array aus Strings, Reihenfolge erhalten, ohne Duplikate, z. B. `["githubbot-ocean","T793"]`.
Kein Tag, leere Liste oder `null` ergibt `NULL`.

## Eingabeformen

Eine Liste, ein JSON-Array als Text oder komma-getrennter Text. Alle drei Formen führen zur selben gespeicherten Form
(`hub.task_audit.normalize_task_tags`).

| Regel | Wert |
|---|---|
| Zeichen je Tag | Buchstaben (Unicode), Ziffern, `_ . : / + -`; erstes Zeichen Buchstabe/Ziffer/`_` |
| Länge je Tag | 1 bis 64 Zeichen (nach dem Trimmen) |
| Anzahl | höchstens 20 je Task |
| Fehler | `ValueError` im Kern, HTTP `422` (`code: tags_invalid`) bzw. `LeaseValidationError` im Lease-Pfad |

## Schreibwege

Alle laufen durch `hub.task_audit.apply_task_field_changes`. Der Normalisierer sitzt dort, nicht in den Aufrufern;
jeder Pfad speichert deshalb gleich und schreibt eine `task_history`-Zeile (`field_change`, `field_changed = 'tags'`).

| Weg | Aufruf | Besonderheit |
|---|---|---|
| Lease (empfohlen für Worker) | `POST /api/tasks/{id}/lease/update` mit `changes: {"tags": [...]}` | durch Fence und `task_version` geschützt, Version wird fortgeschrieben |
| GUI-Server (Port 8000) | `PUT /api/tasks/{id}` mit `tags` | `null` leert das Feld; ohne `tags` bleibt es unverändert |
| Headless-API (Port 8001) | `PUT /api/v1/tasks/{id}` mit `tags` | wie oben |

Auf einer Task mit lebendem Lease ändert `PUT` den Inhalt und damit die `task_version`; der Halter erhält beim
nächsten Renew/Release `stale_task_version`. Für geleaste Tasks daher den Lease-Weg nutzen.

## Nicht Teil dieses Vertrags

- **CLI** (`bach task`): kein eigener Tag-Parameter; bei Bedarf eigene Aufgabe.
- **Nachtrag bestehender Tasks** (z. B. `githubbot-ocean`): erst nach Deployment der Lead-Instanz möglich, dann über
  die obigen Wege, nicht per SQLite.
- Suche/Filter nach Tags in `GET /api/tasks`: unverändert (`q` durchsucht Titel, Beschreibung und ID).

## Abnahme

`system/tests/test_task_tags.py`: Normalisierer (Formen, Idempotenz, Ablehnungen), Audit-Kern (kanonisch, Historie,
Löschen, keine Teilschreibung bei Fehler), Lease-Update (auditiert, versioniert, abgewiesen bei ungültigem Tag und
falschem Fence) und beide HTTP-Routen (setzen, leeren, unverändert lassen, 422 ohne Nebenwirkung).
