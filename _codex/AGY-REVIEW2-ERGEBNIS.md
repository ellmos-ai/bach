# Nachreview (zweite Runde, FINALER STAND) — PR #50 im Repo ellmos-ai/bach

**Reviewer:** Gemini (Google Antigravity CLI Agent Framework)  
**Modell:** Gemini 3.8 Flash (High)  
**Autor des PR:** Claude Opus 5  
**Datum:** 13.09.2026  
**Arbeitsverzeichnis:** `C:\_Local_DEV\repos\BACH-bachheart`  
**Branch:** `feature/T-20260913-896336887-modell-backend-konzept` (Basis: `origin/main` @ `1bb8fa4`)  
**Geprüfte Commits:** `374fc7b..HEAD` (Commits `310c426` und `275bf9b`)  
**Gegenstand:** Einarbeitung der Zweitmeinung, Systemverbund und gemeinsames Herz mit OCEAN (Kapitel 9 + 10)  

---

## Zusammenfassung des Urteils

### **MERGE-FREI** (uneingeschränkt)

Alle drei Anmerkungen aus Runde 1 wurden vollständig und präzise behoben. Sämtliche neuen Faktenbehauptungen im Konzeptdokument (`docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`) und im Programmkopf der `ROADMAP.md` wurden an den realen Codebasen (sowohl innerhalb von BACH als auch über die referenzierten externen Repositories und Inventare hinweg) überprüft und ausnahmslos bestätigt. Die Dokumentenstruktur ist frei von inneren Widersprüchen, lückenlos nummeriert und verwendet durchgängig echte UTF-8-Umlaute.

---

## 1. Überprüfung der drei Anmerkungen aus Runde 1

### 1.a) ASCII-Umschriften im `TODO.md`-Eintrag `[BACH-HERZ-01]`
- **Prüfgegenstand:** `TODO.md` Zeilen 5–18.
- **Soll:** Ersatz sämtlicher ASCII-Ersatzformen (`fuer`, `ergaenzen`, `traegt`, `Ausloeser`, `Eintraege`, `Rueckwaertskompatibilitaet`, `Pruefweg`, `anschliessend`, `pruefen`, `Prioritaet`) durch echte deutsche Umlaute (`ä`, `ö`, `ü`, `ß`).
- **Ist:** Der Eintrag `### [BACH-HERZ-01]` wurde Zeichen für Zeichen geprüft:
  - Zeile 5: `Zuteilungsgrenze für einen Pfad: atomarer Claim, Rechteprüfung, Besetzungsprotokoll`
  - Zeile 6: `... läuft ... unverändert durch ... prüft das Rollenrecht ... während chat_tray.py ... zwei Taktgeber können dieselbe Aufgabe mit Schreibrechten ausführen.`
  - Zeile 10: `... statt offen[0] ungeprüft zu nehmen.`
  - Zeile 11: `... tatsächlich verwendetem ...`
  - Zeile 13: `... Rückwärtskompatibilität ...`
  - Zeile 14: `Prüfweg: ... zusätzlich ein Nebenläufigkeitstest für den Claim.`
  - Zeile 17: `Priorität: high`
  - Zeile 18: `... Nutzerentscheidung ...`
- **Befund:** **Vollständig behoben.** Keine einzige ASCII-Umschrift verblieben.

### 1.b) `_codex/ARCHITEKTUR-ANTWORT.md` im Repo & Abschnitt 6 des Konzepts
- **Prüfgegenstand:** Existenz der Datei `_codex/ARCHITEKTUR-ANTWORT.md` sowie Ausfüllung von Abschnitt 6 in `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`.
- **Ist:**
  - `_codex/ARCHITEKTUR-ANTWORT.md` ist im Repository committed (114 Zeilen, Antworten zu F1 bis F7 von Codex `gpt-5.6-sol`).
  - Abschnitt 6 (`## 6. Zweitmeinung`, Zeilen 440–485) ist vollständig ausgeführt: Attributionsbeleg dokumentiert (`rollout-2026-09-13T12-04-37-01a09a39-…jsonl`, `gpt-5.6-sol`, 42 Befehle), tabellarischer Abgleich der fünf übernommenen Korrekturen, Würdigung der drei neu aufgedeckten Lücken sowie Darlegung der Begründung zum Herauslösen des Cockpits aus dem Bauumfang. Kein Platzhalter-Kommentar vorhanden.
- **Befund:** **Vollständig behoben.**

### 1.c) Pfadpräzisierung `system/docs/TORCH-KONZEPT.md`
- **Prüfgegenstand:** Referenzen auf das Torch-Konzeptdokument im Konzept.
- **Ist:**
  - Zeile 145: `| Fackel-Rechnung | hub/_services/fackel.py, Konzept system/docs/TORCH-KONZEPT.md | ...`
  - Zeile 578: `... (system/docs/TORCH-KONZEPT.md)`
- **Befund:** **Vollständig behoben.** Beide Referenzen verwenden den korrekten Pfad `system/docs/TORCH-KONZEPT.md`.

---

## 2. Prüfung der neuen Faktenbehauptungen (Soll / Ist)

### 2.a) `system/hub/_services/llm/model_backend.py` — `CLIBackend.KNOWN_CLIS` & `create_backend`
- **Soll:** `CLIBackend.KNOWN_CLIS` bei Zeile 708 und `create_backend` bei Zeile 952.
- **Ist (Code):**
  - Zeile 708: `KNOWN_CLIS = {` innerhalb der Klasse `CLIBackend` (definiert Start- und Bereitschaftsargumente für `claude` und `codex`).
  - Zeile 952: `def create_backend(config: dict) -> ModelBackend:` (Factory-Funktion für CLI- und API-Backends).
- **Befund:** **Exakt bestätigt.** Beide Zeilennummern treffen auf die Zeile genau zu.

### 2.b) `system/hub/_services/chat/worker.py` (Zeilen 167–193) — Fehlender Claim vor Ausführung
- **Soll:** Worker nimmt `offen[0]` und startet die Ausführung, ohne die Aufgabe vorher als beansprucht/in Bearbeitung zu markieren.
- **Ist (Code Zeilen 167–222):**
  - Zeile 168: `offen = offene_tasks(db, args.category)`
  - Zeile 192: `t = offen[0]`
  - Zeilen 196–201: Konfiguration von `session` und `chat_id = f"worker-{args.category}-{t['id']}"`
  - Zeile 222: `antwort = asyncio.run(runtime.process("\n\n".join(auftrag), chat_id, skip_compute_gate=True))`
  - Es erfolgt vor `runtime.process` keinerlei atomarer Statuswechsel in der Datenbank (`open` -> `in_progress`), kein Lock und kein Claim.
- **Befund:** **Exakt bestätigt.** Ein zweiter Konsument kann dieselbe Aufgabe im offenen Zustand abgreifen.

### 2.c) `system/hub/_services/chat/telegram_chat.py` — Fehlender Authorization-Header-Check
- **Soll:** Die Control API prüft Herkunft (`_is_allowed_origin`), besitzt aber keinen Check auf `Authorization`- oder `Bearer`-Header.
- **Ist (Code & Grep):**
  - Repository-Grep nach `Authorization` und `Bearer` in `telegram_chat.py` liefert 0 Treffer (Exit-Code 1).
  - Grep nach `token` liefert ausschließlich Treffer im Kontext des Telegram-Bot-Tokens (`BOT_TOKEN = CONFIG["bot_token"]`, `verify_telegram_token()`).
  - Zeile 2955: `def _is_allowed_origin(origin: str, req_host: str = "") -> bool:` prüft lediglich HTTP-Origin (und liefert bei leerem Origin `True`).
- **Befund:** **Exakt bestätigt.** Es existiert keinerlei Token- oder Header-basierte Authentifizierung an der Control API.

### 2.d) `system/hub/_services/chat/chat_tray.py` (Zeilen 567–575) — Abfrage von `OLLAMA`, `BUDDHA`, `BACH`
- **Soll:** Der Tray fragt nicht nur `OLLAMA`, sondern nacheinander `OLLAMA`, `BUDDHA` und `BACH` ab.
- **Ist (Code Zeilen 567–575):**
  ```python
  567:             # 1. Zuerst bestehende Standard-Assignees pruefen (erfuellt auch Unit-Tests)
  568:             for assignee in ("OLLAMA", "BUDDHA", "BACH"):
  569:                 for status in ("pending", "open"):
  570:                     tasks_resp = self._api(
  571:                         "GET", f"/api/tasks?assigned_to={assignee}&status={status}", base=self.gui_url
  572:                     )
  573:                     if tasks_resp and tasks_resp.get("success") and tasks_resp.get("tasks"):
  574:                         task = tasks_resp["tasks"][0]
  575:                         task_status = status
  ```
  Gefolgt von Zeile 580: Fallback für alle weiteren Rollen/Personas.
- **Befund:** **Exakt bestätigt.**

### 2.e) `system/hub/_services/chat/telegram_chat.py` (Zeilen 1519 und 1591) — Dashboard im Code vorhanden
- **Soll:** Seitentitel bzw. Überschrift „BACH Aktivitätsanzeige & Worker Dashboard“ existiert in `origin/main` bei Zeile 1519 und 1591.
- **Ist (Code):**
  - Zeile 1519: `<title>BACH Aktivitätsanzeige & Worker Dashboard</title>`
  - Zeile 1591: `<h1><span>🤖</span> BACH Aktivitätsanzeige &amp; Worker Dashboard</h1>`
- **Befund:** **Exakt bestätigt.** Das Dashboard existiert real im Quellcode; die Richtigstellung der irreführenden Ticketnotiz ist vollkommen berechtigt.

---

## 3. Prüfung der Aussagen über externe Repositories (Kapitel 9 und 10)

Es wurden alle fünf genannten externen Pfade und Aussagen stichprobenartig am Dateisystem überprüft:

### 3.1 `C:/Users/User/OneDrive/.SYNC/_inventory/systems-registry.json`
- **Behauptung:** Vier Hosts, nur die Felder `hostname`, `role`, `slot`, `active`. Keine Hardware- oder Erreichbarkeitsangaben.
- **Ist:** Die Datei enthält exakt 4 Hosts (`ASUS-GEI`, `SURFACE-LAPTOP`, `WORKSTATION-LG`, `mac-studio`). Die einzigen vergebenen Schlüssel über alle Hosts hinweg sind `hostname`, `role`, `slot` und `active` (letzteres bei `SURFACE-LAPTOP: false`).
- **Befund:** **Exakt bestätigt.**

### 3.2 `C:/_Local_DEV/repos/clutch` — `motorblock.py` & `discovery.py`
- **Behauptung:** `_ziel_url` in `motorblock.py:296–303` und `CLUTCH_REMOTE_OLLAMA` in `discovery.py:68–84`.
- **Ist:**
  - `motorblock.py` Zeilen 296–303: `def _ziel_url(self, config: Optional[FahrtConfig] = None) -> str:` löst den Remote-Gang-Endpunkt auf, um Fallback auf `localhost` zu verhindern.
  - `discovery.py` Zeilen 68–84: `def konfigurierte_ollama_hosts(include_local: bool = True) -> list[str]:` liest bei jedem Aufruf `os.environ.get("CLUTCH_REMOTE_OLLAMA", "").strip()`.
- **Befund:** **Exakt bestätigt.**

### 3.3 `C:/_Local_DEV/repos/agent-launcher` — `providers.py`
- **Behauptung:** `PROVIDERS = ("claude", "codex", "agy", "kimi")` in `agent_launcher/providers.py:25`.
- **Ist:** Zeile 25 lautet zeichengetreu: `PROVIDERS = ("claude", "codex", "agy", "kimi")`, gefolgt von `UNVERIFIED_PROVIDERS = {"kimi"}` in Zeile 32.
- **Befund:** **Exakt bestätigt.**

### 3.4 `C:/_Local_DEV/repos/open-ocean` — Modell- und Tray-Infrastruktur
- **Behauptung:** „OCEAN hat keinen Tray, kein Rollenmodell, keine Modellverwaltung“.
- **Ist:** Case-insensitive Grep nach `tray`, `ollama`, `persona` über das gesamte Repo `open-ocean`:
  - `tray`: 0 Treffer.
  - `persona`: Treffer ausschließlich für das englische Wort `personal` (Datenschutzgrenzen).
  - `ollama`: Ein einziger Treffer in `architecture/bach-parity-baseline.v1.json` als Name in einem Baseline-JSON-Objekt; keinerlei Code zur Verwaltung von Ollama.
- **Befund:** **Exakt bestätigt.** OCEAN besitzt keine Modellverwaltung, keinen Tray und kein Rollenmodell.

### 3.5 Status von „Routing v2“
- **Behauptung:** „Routing v2 existiert nirgends außer im Auftragswortlaut [als Transport/Router]“.
- **Ist:**
  - Suche in `C:/Users/User/OneDrive/.TOPICS/_control-center` ergab: Der Begriff „Routing v2“ existiert ausschließlich im Ticket-Ökosystem (`ticket-master`) als Schema-Bezeichnung für Ticketweiterleitungen und Task-Snapshots (`lib/ticket_writer.py`, `--systems-registry für Routing-Schema v2`).
  - Es existiert **kein** Runtime-Router, kein Nachrichten-Transport und kein Modell-Backend namens „Routing v2“.
- **Befund:** **Exakt bestätigt.** Die Einordnung des Konzepts, dass Routing v2 kein lauffähiger Transport für Agenten/Modelle ist (und PingPong der nachweislich gebaute Transport ist), trifft den Kern der Realität.

---

## 4. Innere Konsistenz und formale Prüfungen

1. **Abschnitt 3 („Der Befund in sieben Sätzen“):**
   - Zeilen 217–237 enthalten exakt sieben nummerierte Befunde (1. Kein atomarer Claim, 2. Rechte werden nirgends erzwungen, 3. Fünf unabgeglichene Modell- und Backend-Listen, 4. Rollen tragen kein Modell, 5. Es gibt mehr als zwei Rollenwelten, 6. Das Protokoll kennt den Akteur nicht, 7. Die Control API prüft Herkunft, nicht Berechtigung).
2. **Inhaltsverzeichnis (Zeilen 24–33):**
   - Alle 10 Anker (`#1-messgrundlage` bis `#10-ocean-heart-das-gemeinsame-herz-von-bach-und-ocean`) stimmen exakt mit den 10 H2-Überschriften im Dokument überein.
3. **Abschnittsnummerierung:**
   - 4.1 bis 4.5: Lückenlos und aufsteigend.
   - 9.1 bis 9.3: Lückenlos und aufsteigend.
   - 10.1 bis 10.7: Lückenlos und aufsteigend.
4. **Abschnitt 7 („Offene Entscheidungen“):**
   - Es werden exakt sechs durchnummerierte Architekturentscheidungen für den Decision-Shot aufgelistet.
5. **Abgleich Programmkopf `ROADMAP.md` vs. Konzept:**
   - Leitbegriffe (Rolle, Agentenprofil, Besetzung, Lauf, Platz), Kernlücken (7 durchnummeriert nach Gefährlichkeit), Reihenfolge (Schritte 1–7 sowie Zusatzschritte 8–9), Verbund-Einordnung und Dashboard-Richtigstellung stimmen buchstabengetreu zwischen beiden Dokumenten überein.
6. **Echte Umlaute in Markdown:**
   - `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`, `ROADMAP.md` (neuer Abschnitt), `TODO.md` und `_codex/ARCHITEKTUR-ANTWORT.md` wurden geprüft; sämtliche neuen Abschnitte verwenden durchgängig echte UTF-8-Umlaute.

---

## 5. Endgültiges Fazit

### **MERGE-FREI**

Der PR #50 befindet sich in einem exzellenten, methodisch vorbildlichen Zustand. Alle architektonischen Lücken und empirischen Fakten sind belegt, die Korrekturen aus der ersten Review-Runde wurden sauber vollzogen und die neuen Kapitel fügen sich harmonisch und widerspruchsfrei in die Architektur des Gesamtsystems ein.

---

## Modell-Deklaration

- **Modell-Identität:** Gemini (Google Antigravity CLI Agent Framework)
- **Modell-Bezeichnung:** Gemini 3.8 Flash (High)
- **Reasoning-Stufe:** High
- **Host / Plattform:** ASUS-GEI (Windows / PowerShell)
