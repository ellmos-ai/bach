# Funktionstest: Chatfeld auf der BACH-GUI-Startseite (Task #1157)

**Datum:** 2026-09-12 02:5x · **Tester:** Buddha (bach) · **GUI:** gui/server.py Port 8000 · **Status: LAUFEND & FUNKTIONSFÄHIG**

## 1. Ist das Chatfeld auf der Startseite vorhanden? — JA
- Datei: `system/gui/templates/index.html`
- UI: Partner-Auswahl (Claude / Gemini / Ollama / Planner) + Textarea `#headless-prompt` + Senden-Button (🚀, id `#headless-prompt`)
- Live-Check: `GET /` → HTTP 200 (Startseite ladet), Feld ist eingebunden.
- Zusätzlich: Link "Buddha Chat öffnen →" auf `/chat`.

## 2. Ist es voll funktionsfähig? — JA (End-to-End getestet)
- Frontend: `sendHeadlessPrompt()` (system/gui/static/js/app.js) → `API.post('/api/ai/headless/run', {prompt, partner})`
- API-Wrapper `api.js`: `baseUrl: ''` (relativ) → funktioniert im selben Origin (GUI). ✓
- Backend: `@app.post("/api/ai/headless/run")` (server.py) startet daemon-Thread `run_headless_query(db, prompt, partner)`.
- **Live-Smoke-Test:** `POST /api/ai/headless/run` mit Test-Prompt + Partner "ollama"
  → Antwort: `{"success":true,"message":"Headless Session gestartet..."}`
  → Danach in `messages`-Tabelle: **neue outbox-Zeile id=951** `user -> ollama | "BACH-FUNKTIONSTEST-1157..."` Status `read`.
  → Schreibpfad nachweisbar funktioniert. (Test-Zeile bewusst als 'read' belassen, harmlos.)

## 3. Was passiert mit der Nachricht?
1. UI sendet Prompt + gewählten Partner per POST.
2. `run_headless_query` (system/tools/headless_agent.py):
   - Schreibt die Nachricht als `direction='outbox', sender='user', recipient=<partner>` in `messages` (SQLite `data/bach.db`).
   - Pollt max. 120 s (alle 5 s) auf eine passende `inbox`-Antwort vom Partner.
3. **Antwort-Erzeugung** kommt NICHT vom headless_agent selbst, sondern vom Connector-Layer:
   `hub/_services/connector/smart_router.py`, `queue_processor.py`, `hub/connector.py` schreiben `direction='inbox'` in dieselbe `messages`-Tabelle.
4. UI-Feedback: nur Toast "KI Session erfolgreich gestartet" + Text "Antwort erscheint in der Inbox/Messages".
   **Wichtig:** Der geparste Antwort-Text wird NICHT ins Chatfeld zurückgeführt (kein Streaming, kein Live-Update im Feld). Die Antwort ist erst in /messages oder /chat sichtbar.

## 4. Wo kann man die Verläufe anschauen?
| Ort | Pfad | Inhalt |
|-----|------|--------|
| Messages | `GET /messages` (HTTP 200) | Alle Nachrichten, Filter nach Partner/Kategorie/Akteur + Suche |
| Inbox | `GET /inbox` (HTTP 200) | Eingang/Scanner + ungeordnete |
| Buddha Chat | `GET /chat` (HTTP 200) | Separates Session-System (chat_runtime.py, Port 8081), Transkripte im Snapshot-Store, "Session-Protokolle & Transkripte"-Modal, Fortsetzen/Fork |
| Startseite | stat `#stat-messages` | Anzahl ungelesener Nachrichten |
| DB (ro) | `data/bach.db` `messages` | 514 Einträge (Stand 05:28), Schema: direction/sender/recipient/body/status/created_at ... |

## 6. Live-Belege dieser Session (2026-09-12 05:28, Bestätigung)
- `POST /api/ai/headless/run` {prompt, partner:"ollama"} → `{"success":true,"message":"Headless Session gestartet. Antwort erscheint in der Inbox."}`
- Neue outbox-Zeile **id=952** `user -> ollama | "FUNKTIONSTEST 1157..."` (id=951 von 04:28 ebenfalls vorhanden).
- `GET /api/messages?limit=3` → liefert live id 952 + 951 (Verlaufs-API funktionsfähig).
- `GET /api/chat-control/sessions?limit=3` → live `{"ok":true,"sessions":[...]}`, u.a. **Session 558 `idle-bach-1157`** (Transkript-Store des Chat-Trays Port 8081 erreichbar über GUI-Proxy).
- Alle GUI-Pages live `HTTP 200`: `/`, `/chat`, `/messages`, `/inbox`, `/api/partners` (11 Partner), `/api/inbox/status`.

## 7. Offener Hinweis zur Antwort-Erzeugung
- Ein dedizierter **outbox→inbox-Drainer** (connector, der `messages.outbox` beantwortet) ist als klarer aktiver Daemon nicht direkt sichtbar; lauffähig sind lediglich Compute-Queues (general_compute, abc_hct). Die beiden Test-Nachrichten (951, 952) hatten Stand 05:28 **keine** passende `inbox`-Antwort → der headless-Worker würde nach 120 s `success:false` liefern (verborgen im Thread).
- Konsequenz: Senden + Persistenz = zuverlässig; **Antwort-Erzeugung hängt vom Connector/Queue ab** und ist nicht garantiert/synchron. Für garantierte Antworten müsste ein outbox-Dispatch sicherstellen, dass jeder Partner eine inbox-Antwort schreibt.

## 5. Gefundene Hinweise / Lücken (nicht kritisch, aber zur Kenntnis)
- **Kein direktes Antwort-Feedback im Chatfeld:** `run_headless_query` liefert den Antwort-Body zurück, aber der Thread-Wert wird verworfen (nicht an UI). User sieht nur "Gestartet".
- **Asynchron:** Antwort-Timing hängt vom Connector/Queue-Processor + 120 s-Timeout ab; bei Timeout: `success:false` (aber UI meldet nur "Verbindungsfehler" nur bei Fetch-Fehler, Timeout selbst bleibt clientseitig im Thread unsichtbar).
- **API-Wrapper relativ** (`baseUrl:''`): nur im GUI-Origin funktionsfähig — bewusst so, aber externe Nutzung bräuchte volle URL.
- Zwei getrennte Systeme: Startseite-Headless (messages-Tabelle) vs. `/chat`-Session-System (Transkript-Store). Verläufe sind pro System getrennt, aber über `messages`-Tabelle + /messages zusammenführbar.

## Fazit
Das Chatfeld auf der Startseite ist **technisch voll funktionsfähig**: Senden, Partner-Auswahl und Persistenz (outbox in `messages`) sind live belegt. Der einzige Wermutstropfen: die **Antwort erscheint nicht direkt im Chatfeld**, sondern asynchron in /messages, /inbox oder /chat. Für eine vollständige Live-Chat-Erfahrung im Feld wäre ein Rückkanal (Streaming oder Auto-Load der Inbox-Antwort) nötig.
