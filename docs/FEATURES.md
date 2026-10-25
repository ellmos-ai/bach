# Features

Übersicht über verlässliche Systemfunktionen. Jeder Abschnitt nennt die beteiligten Dateien, die API-Endpunkte und die GUI-Bausteine. In diesem Dokument stehen ausschließlich geprüfte Aussagen.

## Agenten-Verlauf (Snapshots)

Zweck: Gespeicherte Chat- und Task-Verläufe von Agenten einsehen und ausgewählte Läufe fortsetzen (Resume). Der Verlauf ist eine reine Lesesicht – Snapshots werden durch das Ansehen und Fortsetzen niemals verändert. Der API-Router startet selbst keinen Provider (Modul-Docstring in `system/gui/api/agent_history.py`: „Device-authenticated read-only native chat and task history; no provider starts.").

### Kreislauf eines Verlaufs

1. **Speichern:** Chat-Sitzungen werden als Snapshots gespeichert: je Nachricht Rolle und Inhalt; bei Assistenten zusätzlich `answer_status` (success|failed) und bei success die `completed_task_ids` (maximal 100, ohne Dubletten).
2. **Archivierung:** Archivierte Sitzungen tragen in ihrer `session_id` den Bestandteil `:archived:` plus Zeitstempel.
3. **Bereinigung:** Nach der Bereinigung antwortet der Endpunkt für das Transkript mit 404 („Gespeichertes Transkript nicht gefunden").
4. **Memory-Zugriff:** Alle Verlaufs-Endpunkte sind geräteauthentifiziert und rein lesend; Snapshots der Profilbindung erfordern eine verifizierte, aktuelle Profilbindung.

### API-Router `system/gui/api/agent_history.py`

Alle Endpunkte liegen unter `/api/agent-history` (OpenAPI-Tag `agent-history`). Zugrunde liegt ein `SQLiteChatSessionStore` auf der BACH-Datenbank; die Authentifizierung erfolgt gerätebasiert über den Memory-Device-Token.

#### `GET /sessions` – Sitzungsliste

- Query-Parameter: `limit` (Standard 25, 1–100), `offset` (Standard 0, maximal 100000), `agent_id` (optional), `archive` (Standard `all`; erlaubt `all|current|archived`).
- Antwort (`bach.chat-sessions.v1`): `source: session_snapshots`, `snapshot_type: chat-transcript.v1`, `context: profile|global` sowie `page` mit den Sitzungseinträgen (die GUI liest `data.page?.items`).
- Fehler: 409 „Profilquelle nicht mehr verifiziert"; 503 „Native Transkriptquelle nicht verfügbar".

#### `GET /sessions/{snapshot_id}` – Einzeltranskript

- Query-Parameter: `include_tools` (Standard `false`); nur damit werden Tool-Nachrichten ausgeliefert (`tool_result: true` und gekürzter `tool_name`).
- Antwort (`bach.chat-session.v1`): `snapshot_id`, `created_at`, `updated_at`, `name`, `archived`, `context`, `agent_id`, `stored_message_count` sowie `messages` mit je `index`, `role`, `content`. System-Nachrichten werden nicht ausgeliefert; Assistenten-Text erscheint ohne Denk- und Analyseanteile; Assistenten tragen zusätzlich `answer_status` (success|failed), `completed_task_ids` nur bei success.
- Fehler: 404 „Gespeichertes Transkript nicht gefunden"; 409, wenn die gespeicherte Profilbindung nicht mehr verifiziert ist; 422 bei ungültigen Parametern; 503, wenn die Transkriptquelle nicht verfügbar ist.

#### `GET /tasks` – dauerhafter Taskverlauf

- Antwort (`bach.task-history.v1`): `events` mit je `id`, `task_id`, `title`, `action`, `field`, `old_status`, `new_status`, `current_task_status`, `changed_at` sowie `total`, `offset`, `limit`, `has_more`.
- Fehler: 503 „Dauerhafter Taskverlauf nicht verfügbar".

#### `POST /sessions/{snapshot_id}/resume` – Lauf fortsetzen

- Body: `worker_id` (Pflicht, Muster `^[A-Za-z0-9._-]{1,64}$`), `model` (optional, max. 200 Zeichen; leer = Vorgabemodell), `prompt` (optionaler Nutzerhinweis, max. 2000 Zeichen).
- Verhalten: Es startet ein **neuer Lauf** auf dem gewählten Workerprofil mit **eigener Lease**; das **Modell ist frei wählbar**. Der Snapshot bleibt unberührt, weil Resume ausschließlich liest.
- Ablauf: Snapshot laden; Profilbindung prüfen; aus dem Original-Auftrag (erste Nutzernachricht, max. 6000 Zeichen), den letzten 10 Nachrichten (je max. 1500 Zeichen) und dem Nutzerhinweis (max. 2000 Zeichen) einen deterministischen Übergabezettel bauen (auf max. 18000 Zeichen gekürzt); die Worker-Konfiguration aktualisieren (`task_prompt`, wahlweise zusätzlich `model`); den Worker starten.
- Antwort: `ok: true`, `action: "resume"`, `worker_id`, `snapshot_id`, `model`, `start`.
- Fehler: 422 (ungültige Anfragedaten, ungültige Worker-ID, ungültiger oder zu langer Modellname, ungültiger oder zu langer Nutzerhinweis); 400 „Ungültige Resume-Anfrage"; 404, wenn der Snapshot fehlt; 409 „Gespeicherte Profilbindung nicht mehr verifiziert" oder „Transkript gehört nicht zum gewählten Kontext" sowie 409 bei Ablehnung durch die Workersteuerung; 503 „Gespeichertes Transkript nicht lesbar" (mehr als 1000 Nachrichten, Rollen außerhalb system/user/assistant/tool oder Inhalt über 1.000.000 Zeichen) und 503 „Hintergrundworker-Steuerung nicht verfügbar".

### GUI

- **Laufansicht** (`system/gui/web/src/pages/agenten/running.astro`): Ein Verlaufs-Button öffnet das Modal „Agenten-Verlauf" mit Ansichtsfilter (aktuell/archiviert/alle), Sitzungsliste, Transkript-Detail und Resume-Formular. Im Formular werden Workerprofil (nur idle/paused/completed/error), Backend, Modell und optionaler Nutzerhinweis gewählt; abgeschickt wird an `POST /api/agent-history/sessions/{snapshot_id}/resume`.
- **Sitzungsbereich** (`system/gui/web/src/pages/agenten/sessions.astro`): Der Tab „Agent history" listet Snapshots (Filter, Archiv-Kennzeichnung) und zeigt das Transkript als Detail. Der Tab ist **nur lesend**; Resume gibt es ausschließlich im Modal der Laufansicht.

### Offener Folgeschritt

- **Kerninterne Verlaufsspeicherung stilllegen:** Die kerninterne Verlaufsspeicherung soll stillgelegt werden, sodass die Snapshots die alleinige Verlaufsquelle bleiben. Dieser Folgeschritt ist hier ausdrücklich nicht umgesetzt und dient als Anknüpfungspunkt für die weitere Arbeit.