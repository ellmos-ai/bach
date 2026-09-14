# Zwei-Modell-Review: PR #50 (Modell-Backend als Herz von BACH)

**Reviewer:** Gemini (Antigravity CLI)  
**Modell:** Gemini 3.8 Flash (Reasoning-Stufe: High)  
**Autor des PR:** Claude Opus 5  
**Datum:** 13.09.2026  
**Arbeitsverzeichnis:** `C:\_Local_DEV\repos\BACH-bachheart`  
**Branch:** `feature/T-20260913-896336887-modell-backend-konzept` (Basis: `origin/main` @ `1bb8fa4`)  
**Gegenstand:** Dokumentation Phase 1 (Bestandsaufnahme, Programmkopf, Architekturkonzept)

---

## 1. Faktentreue

Die Belege und Zeilenangaben im Konzeptdokument (`docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`) wurden direkt am Quellcode im Arbeitsverzeichnis geprüft. Nachfolgend der Abgleich für die geforderten Stichproben sowie ergänzende Befunde:

### 1.1 `system/hub/agent_launcher.py` Zeile 1395 — Modell-Whitelist
- **Soll (Konzept Z. 55):** Modell-Whitelist lässt nur `sonnet|opus|haiku` durch; sperrend für andere Runner.
- **Ist (Code Z. 1395–1397):**
  ```python
  1395:         if model not in ("sonnet", "opus", "haiku"):
  1396:             message = f"[ERROR] {t('agent_invalid_model', default='Ungueltiges Modell')}: {model} (sonnet, opus, haiku)"
  1397:             return self._action_response(...)
  ```
- **Befund:** **Exakt bestätigt.** Zeilennummer und Whitelist-Inhalt stimmen präzise überein.

### 1.2 `system/hub/_services/chat/telegram_chat.py` Zeile 385 — `BACKEND_PRESETS`
- **Soll (Konzept Z. 51):** `BACKEND_PRESETS` Z. 385–439 umfasst genau 8 Backends.
- **Ist (Code Z. 385–438):**
  `BACKEND_PRESETS = {` beginnt bei Z. 385 und endet bei Z. 438.
  Enthält exakt 8 Einträge: `ollama` (Z. 386), `ollama-cloud` (Z. 393), `lmstudio` (Z. 400), `hermes` (Z. 407), `claude` (Z. 414), `claude-api` (Z. 420), `codex` (Z. 426), `openai` (Z. 432).
- **Befund:** **Exakt bestätigt.**

### 1.3 `system/hub/agent_router.py` — `route()` ohne Importeure
- **Soll (Konzept Z. 81):** `agent_router.py::route/explain/load_roles` Z. 35–148 hat null Importeure und ist keine Handler-Subklasse.
- **Ist (Code / Grep):**
  Grep über das gesamte Repository nach `agent_router` und `load_roles` liefert Vorkommen ausschließlich in `agent_router.py` selbst, in `system/docs/help/roles.txt` sowie in den neuen PR-Dokumenten. Kein einziges Python-Modul im Repo importiert `agent_router` oder eine seiner Funktionen. Es existiert keine Subklasse von `BaseHandler` oder ein Eintrag in Registrierungsmechanismen.
- **Befund:** **Exakt bestätigt.** Die Funktion `route()` ist de facto toter Code.

### 1.4 `system/core/launcher.py` Zeile 88–94 — `AGENT_DELEGATIONS`
- **Soll (Konzept Z. 82):** Hartkodiertes Dict mit fünf Fällen gegenüber 27 Rollen.
- **Ist (Code Z. 88–94):**
  ```python
  88:     AGENT_DELEGATIONS = {
  89:         "steuer": "steuer-agent",
  90:         "research": "research-agent",
  91:         "production": "production-agent",
  92:         "entwickler": "entwickler-agent",
  93:         "bewerbung": "bewerbungsexperte",
  94:     }
  ```
- **Befund:** **Exakt bestätigt.** Genau 5 Einträge in Zeile 88–94.

### 1.5 `system/hub/_services/chat/slots_config.py` Zeile 524–558 — `record_activity`
- **Soll (Konzept Z. 189, 269):** Schreibt in 100-Einträge-Ringpuffer in `slots_config.json`; Felder `id`, `timestamp`, `source`, `activity`, `status`, `details` — kein Modell, kein Backend, kein Akteur.
- **Ist (Code Z. 524–558):**
  ```python
  535:     entry = {
  536:         "id": f"act-{uuid.uuid4().hex[:6]}",
  537:         "timestamp": datetime.now(timezone.utc).isoformat(),
  538:         "source": source,
  539:         "activity": activity,
  540:         "status": status,
  541:         "details": details or {},
  542:     }
  545:     if len(history) > 100:
  546:         cfg["activity_history"] = history[:100]
  ```
- **Befund:** **Exakt bestätigt.** Exakt diese 6 Felder, 100-Element-Deckelung, Ablage direkt in der Konfigurationsdatei `slots_config.json`.

### 1.6 `system/hub/compute_lock.py` Zeile 431–498 — `set_fackel_preference`
- **Soll (Konzept Z. 125, 297):** Schreibt keinen Log-Eintrag; ruft `record_activity` nicht auf.
- **Ist (Code Z. 460–498):**
  `set_fackel_preference` validiert den Eingabewert, schreibt eine Datei mit `preference` und `updated_at` (Z. 476–481) und aktualisiert `fackel_preference` in `slots_config.json` (Z. 488–492). Es erfolgt weder ein Aufruf von `record_activity` noch ein Eintrag mit Akteursbezug.
- **Befund:** **Exakt bestätigt.**

### 1.7 `system/hub/scheduler_provider.py` — `load_external_scheduler()`
- **Soll (Konzept Z. 152):** `probe_scheduler_provider` ist nur Statusprobe ohne Weiche; `load_external_scheduler()` hat null Aufrufer.
- **Ist (Code Z. 43–49 / Grep):**
  `load_external_scheduler()` existiert ab Zeile 43. Eine Repository-weite Suche nach `load_external_scheduler` liefert genau 0 Aufrufer. `probe_scheduler_provider()` (Z. 26–40) wird ausschließlich in `system/hub/scheduler.py:373–388` in `_check_scheduler_provider` aufgerufen, welches laut eigenem Docstring (Z. 374) explizit das Laufzeitverhalten nicht ändert.
- **Befund:** **Exakt bestätigt.**

### 1.8 `system/gui/server.py` Zeile 57 — `DEFAULT_TASK_ASSIGNEE`
- **Soll (Konzept Z. 108–109):** `DEFAULT_TASK_ASSIGNEE = "OLLAMA"` in `gui/server.py:57`, Z. 384, 1602; gespiegelt in `gui/api/headless.py:211`, Testkopplung in `tests/test_gui_server_smoke.py:318`.
- **Ist (Code):**
  - `system/gui/server.py:57`: `DEFAULT_TASK_ASSIGNEE = "OLLAMA"`
  - `system/gui/server.py:384`: `assigned_to: Optional[str] = DEFAULT_TASK_ASSIGNEE`
  - `system/gui/server.py:1602`: `payload.get("assigned_to") or DEFAULT_TASK_ASSIGNEE`
  - `system/gui/api/headless.py:211`: `DEFAULT_TASK_ASSIGNEE = "OLLAMA"`
  - `system/tests/test_gui_server_smoke.py:318`: `assert srv.DEFAULT_TASK_ASSIGNEE == headless.DEFAULT_TASK_ASSIGNEE`
- **Befund:** **Exakt bestätigt.** Alle Zeilennummern treffen auf den Punkt.

### Weitere Stichproben:
- `system/hub/agent_runners.py::BUILTIN` (Z. 39–69): Exakt 4 Runner (`claude`, `codex`, `agy`, `local`) mit Match-Patterns.
- `system/hub/_services/delegation/__init__.py::_load_external_clutch_scorer` (Z. 108–129): Bestätigt.
- `system/data/schema/schema.sql:596–635`: Tabellen `bach_agents` und `bach_experts` enthalten tatsächlich keinerlei Spalten für Modell, Backend, Budget oder Berechtigungen.
- `system/hub/_services/limits.py:29`: `BACH_DELEGATION_DEPTH` steht nur im Kopf-Docstring, nicht im `DEFAULTS`-Dictionary.

### Anmerkung zur Notation im Konzeptdokument:
Das Konzeptdokument `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md` gibt Pfade relativ zum Verzeichnis `system/` an (z. B. `hub/agent_launcher.py` statt `system/hub/agent_launcher.py`). Dies ist im BACH-Projektkonsens schlüssig, da `system/` der primäre Anwendungs-Root ist.

---

## 2. Widersprüche

### Abgleich mit `ROADMAP.md` Abschnitt „Abgeschlossen: clutch als Routing-Engine übernommen (M8)“:
- In der ROADMAP (M8, Z. 345–370) wird festgehalten:
  *„Scorer, PartnerRegistry, Streckenanalyse, Gas/Bremse, Bordcomputer, Fahrschule und Fahrtenbuch laufen über das externe `clutch`; [...] Der frühere Fork liegt nur noch als expliziter Notfall-Fallback unter `system/hub/_archive/delegation_legacy/`."*
- Das neue Konzeptdokument (`docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`, Z. 61–70) stellt fest:
  *„`delegation.get_component_sources()` meldet `external_clutch: available` und alle sieben Komponenten [...] als `clutch`. Die ROADMAP-Aussage ‚alle acht Quellen extern‘ ist damit bestätigt. Der Auflösungsweg läuft allerdings nicht über die im Code gesuchten `.MODULES`-Pfade [...] sondern darüber, dass `clutch` als Paket installiert ist [...]. Fiele die Installation weg, würde BACH ohne Vorwarnung auf den archivierten Fork zurückfallen: Ein Ausfall sähe aus wie normale Funktion."*

**Bewertung:**
Es liegt **kein Widerspruch** vor, sondern eine **fundierte, empirische Präzisierung**.
Das Konzeptdokument bestätigt die Kernaussage der Roadmap (clutch bedient die Komponenten extern). Es deckt jedoch den technischen Lademechanismus auf: Die in `_candidate_clutch_roots` hartkodierten relativen Suchpfade (`.MODULES/clutch`) greifen in dieser Umgebung nicht; stattdessen greift der direkte Python-Import des installierten Pakets.
Das Konzept identifiziert zu Recht das architektonische Risiko dieses „stillen Fallbacks" (kein fail-closed-Verhalten bei Deinstallation/Beschädigung).
Die Darstellung ist vollkommen konsistent und architektonisch sauber herausgearbeitet.

---

## 3. Sprache und Form

### 3.1 Echte Umlaute in `.md`-Dateien
- `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`: **Vorbildlich.** Durchgängig echte Umlaute (`ä`, `ö`, `ü`, `ß`).
- `ROADMAP.md` (neuer Abschnitt): **Vorbildlich.** Durchgängig echte Umlaute.
- `_codex/ARCHITEKTUR-FRAGEN.md`: **Vorbildlich.** Durchgängig echte Umlaute.
- **`TODO.md` (Abweichung / Mangel):**
  Im neu hinzugefügten Eintrag `[BACH-HERZ-01]` wurden an mehreren Stellen ASCII-Umschriftformen verwendet:
  - `ergaenzen` statt `ergänzen` (Z. 5)
  - `traegt` statt `trägt` (Z. 6)
  - `Ausloeser` statt `Auslöser` (Z. 6)
  - `Eintraege` statt `Einträge` (Z. 8)
  - `Rueckwaertskompatibilitaet` statt `Rückwärtskompatibilität` (Z. 9)
  - `Pruefweg:` statt `Prüfweg:` (Z. 10)
  - `anschliessend` statt `anschließend` (Z. 10)
  - `pruefen` statt `prüfen` (Z. 10)
  - `Prioritaet:` statt `Priorität:` (Z. 13)
  
  Die übrigen Einträge in `TODO.md` (z. B. `[BACH-HOOK-01]`, `[BACH-MCP-01]`, `[BACH-MOD-01]`) verwenden regulär echte Umlaute (`Prüfweg:`, `Priorität:`, `vollständig`, `ablösen`). Diese Umschrift sollte vor dem Merge korrigiert werden.

### 3.2 Syntax der Markdown-Tabellen
- Sämtliche 13 Tabellen in `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md` (Tabellen in 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 4.3, 5, 8) wurden auf syntaktische Korrektheit (Kopfzeile, Trenner, Zellentrennung) geprüft. Alle Tabellen sind valide und syntaktisch einwandfrei formatiert.

### 3.3 Interne Links
- **Link in `ROADMAP.md` (Z. 306):**
  `[`docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`](docs/MODELL-BACKEND-KONZEPT_2026-09-13.md)`
  Verweist ausgehend vom Repository-Root exakt auf die neu erstellte Datei. Der Link ist funktional und korrekt.
- **Inhaltsverzeichnis-Anker in `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md` (Z. 18–25):**
  Alle 8 Anker (`#1-messgrundlage` bis `#8-reihenfolge-und-folgetickets`) stimmen mit den Markdown-Überschriften überein.
- **Hinweis zu Dateireferenzen im Text:**
  - Im Konzept Z. 123 wird `docs/TORCH-KONZEPT.md` referenziert; im Repo liegt die Datei unter `system/docs/TORCH-KONZEPT.md`.
  - Im Konzept Z. 349 wird auf `_codex/ARCHITEKTUR-ANTWORT.md` verwiesen; diese Datei ist noch nicht im Repo abgelegt (siehe Anmerkung zu Abschnitt 6).

### 3.4 Format des TODO-Eintrags
- Der neue Eintrag `[BACH-HERZ-01]` folgt bis auf die erwähnten Umlaut-Umschriften (`Pruefweg:`, `Prioritaet:`) exakt der etablierten Struktur der Datei (`Ziel`, `Quelle`, `Akzeptanzkriterien (DoD)`, `Prüfweg`, `Aufwand`, `Reichweite`, `Priorität`, `Hinweis`).

---

## 4. Risiko

### 4.1 Quellcode- und Verhaltensänderungen
- Der Pull Request verändert **keine einzige Zeile Python-, SQL-, HTML- oder Konfigurationscode**.
- Es werden ausschließlich Dokumentationsdateien, Task-Listen und eine Ignorier-Regel angepasst.
- Ausführung der relevanten Test-Suiten:
  - `system/tests/test_slots_and_workers.py`: **24 passed** (5.5s)
  - `system/tests/test_gui_server_smoke.py`: **42 passed** (15.8s)

### 4.2 `.gitignore`-Regel
- In `.gitignore` wurden folgende Zeilen ergänzt:
  ```gitignore
  # Codex-Zweitmeinung: Roh-Logs bleiben lokal, Fragen/Antwort werden committet
  _codex/*.log
  ```
- **Prüfung auf Überdeckung:**
  Die Maske `_codex/*.log` beschränkt sich strikt auf `.log`-Dateien innerhalb des Verzeichnisses `_codex/`.
  Dateien wie `_codex/ARCHITEKTUR-FRAGEN.md`, `_codex/ARCHITEKTUR-ANTWORT.md` oder dieses Review-Ergebnis werden nicht berührt. Außerhalb von `_codex/` liegende Dateien sind syntaktisch ausgeschlossen.
- **Befund:** Kein Fehl-Ausschluss, kein Risiko.

---

## 5. Urteil

### **MERGE-FREI MIT ANMERKUNGEN**

Der Pull Request ist konzeptionell herausragend strukturiert, analytisch tiefgehend und in allen überprüften Punkten fakten- und zeilentreu zum realen Quellcode. Da keine Codeänderungen vorgenommen werden, besteht kein Betriebsrisiko.

### Vor dem Merge zu behebende Anmerkungen:
1. **Umlaute in `TODO.md` glätten:**
   Im Block `### [BACH-HERZ-01]` sollten die ASCII-Ersatzformen durch echte Umlaute ersetzt werden (`Prüfweg:`, `Priorität:`, `ergänzen`, `trägt`, `Auslöser`, `Einträge`, `Rückwärtskompatibilität`, `anschließend`, `prüfen`), um Konsistenz mit dem Rest der Datei und den Repo-Regeln herzustellen.
2. **Referenz auf Zweitmeinungs-Antwort in Abschnitt 6:**
   In `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md` (Zeile 348–352) wird angekündigt:
   *„Fragen und Antwort liegen als `_codex/ARCHITEKTUR-FRAGEN.md` und `_codex/ARCHITEKTUR-ANTWORT.md` im Repo; die Einarbeitung ist im Abschnitt unten dokumentiert. <!-- ZWEITMEINUNG-EINARBEITUNG -->“*
   Da `_codex/ARCHITEKTUR-ANTWORT.md` noch nicht committet ist, sollte vor dem endgültigen Merge entweder die Antwortdatei ergänzt und der Kommentarblock ausgefüllt oder der Satz als „Antwort ausstehend / Zweitmeinungsverfahren läuft“ gekennzeichnet werden.
3. **Pfad zu Torch-Konzept:**
   In Tabelle 2.5 (Zeile 123) kann optional `system/docs/TORCH-KONZEPT.md` statt `docs/TORCH-KONZEPT.md` präzisiert werden.

---

## Modell-Deklaration

- **Modell-Identität:** Gemini (Google Antigravity CLI Agent Framework)
- **Modell-Bezeichnung:** Gemini 3.8 Flash
- **Reasoning-Stufe:** High
- **Umgebung / Host:** ASUS-GEI (Windows / PowerShell)
