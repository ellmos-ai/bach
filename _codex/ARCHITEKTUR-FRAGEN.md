# Architektur-Zweitmeinung: BACH Modell-Backend als "neues Herz"

Du bist Zweitmeinung (Reviewer/Architekt) zu einem Architekturkonzept. Antworte auf Deutsch,
knapp und substantiell, ohne Höflichkeitsfloskeln. Widerspruch ist erwünscht: Wenn eine
Annahme falsch ist, sag das zuerst.

**Du arbeitest read-only.** Der Worktree ist `C:/_Local_DEV/repos/BACH-bachheart`
(Stand `origin/main`, Commit 1bb8fa4). Du darfst alles lesen, nichts ändern.

## Auftrag des Nutzers (Originalwortlaut, maßgeblich)

> "wichtigste Neuerung in Bach ist aktuell Modell backend und dessen verwaltung. Das wird das
> neue Herz von Bach. Sprich bach wird lebendig, wer spielt wann welche der Rollen und Agenten usw."

BACH ist ein lokales Assistenz-/Automationssystem (Python, SQLite `bach.db`, CLI `bach.py`,
GUI auf :8000, eine zweite "Control API" auf :8081, Telegram-Anbindung, lokale Ollama-Modelle
auf einem Mac Studio, dazu Claude-Code- und Codex-CLI als Backends).

## Gemessener Ist-Stand (Phase 1, alles mit Zeilenbeleg erhoben)

**Es gibt heute DREI voneinander unabhängige Modell-/Backend-Register:**

1. `system/hub/_services/chat/telegram_chat.py::BACKEND_PRESETS` (Z. 385-439) — 8 Backends
   (`ollama`, `ollama-cloud`, `lmstudio`, `hermes`, `claude`, `claude-api`, `codex`, `openai`)
   mit `type`, `base_url`, `default_model`, `method` (api|cli), `description`. Verfügbarkeit
   wird live geprüft (`_backend_inventory`, Z. 2867). **Das ist das einzige echte
   Backend-Register — es liegt aber im Telegram-Modul.**
2. `system/hub/agent_runners.py::BUILTIN` (Z. 39-69) — 4 Runner (`claude`, `codex`, `agy`,
   `local`), Auswahl per `fnmatch` auf den Modellnamen (`gpt-*`, `gemini-*`, `qwen*`).
3. `system/hub/_services/delegation/__init__.py::_ScorerAdapter.get_recommended_model` —
   kennt nur `haiku|sonnet|opus`.

Dazu eine harte Sperre: `system/hub/agent_launcher.py:1395` lässt nur `sonnet|opus|haiku`
durch. Die Runner für `codex`, `agy` und lokale Modelle sind deklariert, aber über den
regulären Weg unerreichbar.

**Rollen tragen kein Modell.** Die Rollen leben in SQLite (`bach_agents`, `bach_experts`,
Schema `system/data/schema/schema.sql:596-635`): Name, Kategorie, Beschreibung, `persona`
(Freitext), `capabilities` (JSON, nur Experten). **Kein Feld für Modell, Backend, Rechte
oder Budget.** Alle 20 exportierten Personas unter `system/agents/personas/*.md` stehen auf
`runtime.model: null`.

**Es gibt aber eine zweite, parallele Rollenwelt**, die sehr wohl Modelle trägt:
`system/hub/_services/chat/slots_config.py`. Drei fest codierte "Core-Slots"
(`buddha_chat`, `buddha_always_on`, `buddha_connector`, Z. 36-83) plus beliebig viele
`dynamic_workers`. Jeder Slot/Worker trägt `backend`, `model`, `mode` (safe|full), `think`,
`max_tool_rounds`, `system_prompt`, und Worker zusätzlich `role_id`, `multi_role`,
`max_experts`, `expert_models` (ein Dict Modell-je-Experte) und `sub_mode`
(`task_worker` | `hintergrund_worker` | `boss_routing` | `expert_role`).
Die Rolle wirkt dort aber **ausschließlich als Prompt-Text**: `compose_worker_prompt`
(Z. 369-430) baut daraus einen System-Prompt zusammen. Persistenz: eine JSON-Datei
`system/data/slots_config.json`, nicht die DB.

**Der generische Rollen-Router ist tot.** `system/hub/agent_router.py::route` (Keyword-Scoring
über alle 27 Rollen aus `bach_agents`/`bach_experts`) hat **null Importeure** und ist keine
Handler-Subklasse, wird also auch von der Auto-Discovery nicht erfasst. Aktiv ist stattdessen
ein hartkodiertes Fünf-Fälle-Dict `system/core/launcher.py::AGENT_DELEGATIONS` (Z. 88-94).

**Drei unabhängige Taktgeber, die einander nicht kennen:**
- `system/hub/scheduler.py` (Legacy, aktiv, Jobs in `scheduler_jobs`/`scheduler_runs`),
- `system/hub/_services/chat/chat_tray.py::_poll_loop` (5-Sekunden-Poll im Tray-Prozess;
  der **einzige** Ort, der `assigned_to = "OLLAMA"` liest und daraufhin `POST :8081/api/chat`
  auslöst, Z. 553-694),
- `system/hub/_services/chat/worker.py` (eigener OS-Prozess, sequentiell, wartet auf
  Chat-Stille und Compute-Lock).

Der Seam zum externen `ellmos-scheduler` (`system/hub/scheduler_provider.py`) ist **nicht**
fail-closed verdrahtet: er macht nur eine `find_spec`-Probe, und `load_external_scheduler()`
hat im ganzen Repo null Aufrufer.

**Ressourcenseite ("Fackel"):** `system/docs/TORCH-KONZEPT.md` +
`system/hub/_services/fackel.py`. Zehn Fackeln pro System, eine Fackel = ein Zehntel des
modelltauglichen GPU-Speichers (auf dem Mac 2,50 GiB von 24,96 GiB). Grundsatz des Dokuments:
**gemessen, nicht gebucht** — kein Buchhaltungsregister, wer wie viele Fackeln hält; der Zustand
wird per `vm_stat` und Ollamas `/api/ps` erfragt. Davon getrennt ein globaler Vorrangschalter
`fackel_preference ∈ {compute, ollama}` (`system/hub/compute_lock.py:431-498`), Default
`compute` = Schutz laufender Rechenjobs; `ollama` hebt den Schutz auf und pausiert Compute-Jobs
per SIGSTOP.

**Beobachtbarkeit:** `slots_config.py::record_activity` (Z. 524-558) schreibt in einen
100-Einträge-Ringpuffer **innerhalb derselben JSON-Datei**. Felder: `id`, `timestamp`,
`source` (Slot-/Worker-ID), `activity` (Freitext), `status`, `details`. **Kein Feld für
Modell, Backend oder Akteur.** Das Fackel-Umschalten ruft `record_activity` gar nicht auf —
ein Vorbefund belegte, dass deshalb rückwirkend nicht feststellbar war, wer die Fackel
umgestellt hatte. Angezeigt wird das Ganze unter `:8081/activity`.

**Vorhandene Bausteine, die nicht neu gebaut werden sollen (Policy P-009: Standards vor
Eigenbau):** `clutch` (eigenständiges, provider-neutrales Routing-Modul, v0.6.2, 387 Tests;
Anthropic/Gemini/OpenAI/Ollama/agy/Kimi; `clutch route … --json`, `clutch models --json`,
Budget-Tankuhr, Circuit Breaker, Epsilon-Greedy-Lernen). BACH bindet clutch bereits per
echtem Python-Import über `system/hub/_services/delegation/__init__.py` ein und fällt **still**
auf einen eigenen Fork unter `system/hub/_archive/delegation_legacy/` zurück, wenn das externe
Paket nicht im `sys.path` liegt.

## Der Architekturvorschlag, den du prüfen sollst

**Grundunterscheidung:** *Rolle* = Vertrag (was darf/soll getan werden: Fähigkeiten, Rechte,
Budgetrahmen, Werkzeugkreis). *Agent* = Besetzung dieses Vertrags zur Laufzeit (Modell +
Backend + Ort + konkretes Budget/Fackeln). Eine Rolle ist besetzbar durch verschiedene Agenten;
derselbe Agent kann nacheinander verschiedene Rollen spielen. "Wer spielt wann welche Rolle"
ist damit eine Besetzungsentscheidung, die protokolliert werden kann.

**Fünf Festlegungen:**

1. **Ein Backend-Register statt drei.** `BACKEND_PRESETS` wird aus `telegram_chat.py` in ein
   eigenes Modul gehoben und die einzige Wahrheit; `agent_runners.BUILTIN` und die Whitelist
   in `agent_launcher.py:1395` werden darauf zurückgeführt. Verfügbarkeit bleibt gemessen,
   nicht konfiguriert.
2. **Die Rolle bekommt ein Besetzungsfeld.** `bach_agents`/`bach_experts` erhalten
   `preferred_backend`, `preferred_model`, `budget`/`fackel_bedarf`, `rights`. Die
   Slot-/Worker-Welt aus `slots_config.json` wird als *Besetzung* darüber gelegt, nicht als
   zweite Rollenwelt daneben.
3. **Die Zuteilung fragt clutch, entscheidet aber selbst.** clutch liefert den
   Modellvorschlag (Komplexität, Zweck, Kosten, Budget); BACH legt die Gates darüber, die nur
   BACH kennt: Fackel-Verfügbarkeit, `fackel_preference`, Compute-Lock, Delegationstiefe,
   Rechte der Rolle. Der tote `agent_router.py` wird entweder an clutch angeschlossen oder
   gelöscht — nicht als Leiche behalten.
4. **Das Activity-Log wird die einzige Wahrheit über Besetzungen.** Jede Zuteilung und jede
   Umschaltung schreibt eine Zeile mit Akteur (Rolle, Agent, Modell, Backend, Auslöser,
   Ergebnis). Das Fackel-Umschalten wird einbezogen. Ringpuffer in einer JSON-Datei wird durch
   eine Tabelle in `bach.db` ersetzt.
5. **Cockpit ist `:8081/activity`**, wird ins GUI-Design (:8000) überführt und dort unter
   "Agenten" eingehängt (das passiert parallel in einem anderen Ticket).

## Deine Fragen

Antworte in genau dieser Reihenfolge, mit Überschriften:

**F1 — Grundunterscheidung.** Trägt "Rolle = Vertrag, Agent = Besetzung" für dieses System,
oder ist das eine Abstraktion, die sich nicht auszahlt? Gibt es einen dritten Begriff, der
fehlt (z. B. Session, Auftrag, Platz/Slot)? Wenn die Unterscheidung trägt: Wo genau verläuft
die Grenze zwischen Rolle und Slot — sind `buddha_chat`/`buddha_always_on`/`buddha_connector`
Rollen oder Plätze?

**F2 — Zwei Rollenwelten.** Heute gibt es Rollen in der DB (`bach_agents`, ohne Modell) und
Rollen als Prompt-Text in `slots_config.json` (mit Modell). Welche der beiden sollte die
Wahrheit werden, und warum? Nenne konkret das Migrationsrisiko der von dir bevorzugten
Richtung.

**F3 — Zuteilungsstrategie.** Wie viel Entscheidung gehört zu clutch, wie viel bleibt bei
BACH? Ist der Vorschlag "clutch schlägt vor, BACH gated" richtig geschnitten, oder entsteht
damit ein Zwei-Hirn-Problem, bei dem clutchs Lernschleife (Epsilon-Greedy) systematisch gegen
BACHs Gates lernt und dadurch falsche Statistiken bildet?

**F4 — Fackeln vs. Budget.** Das Fackel-Dokument sagt ausdrücklich "gemessen, nicht gebucht".
clutch dagegen bucht (Tankuhr, Budgetzonen). Widersprechen sich die beiden Prinzipien, wenn
man sie in einer Zuteilungsentscheidung zusammenführt? Wie löst man das, ohne einen der
beiden Grundsätze zu brechen?

**F5 — Beobachtbarkeit.** Ist "das Activity-Log ist die einzige Wahrheit" tragfähig, oder
braucht es die Trennung zwischen Ereignisstrom (append-only) und Zustand (abfragbar)? Welche
Felder müssen minimal in einer Zeile stehen, damit die Frage "wer spielte um 10:34 welche
Rolle" beantwortbar ist? Beachte, dass das Fackel-Prinzip "gemessen, nicht gebucht" auch hier
gegen ein Register sprechen könnte.

**F6 — Was fehlt, was ist zu viel?** Welche der fünf Festlegungen würdest du streichen, weil
sie Aufwand ohne Ertrag ist? Welche Lücke im Ist-Stand ist gefährlicher als die, die der
Vorschlag adressiert? Sag ausdrücklich, wenn du den Vorschlag für überbaut hältst — die
kleinste Änderung, die das Nutzerziel erfüllt, ist besser als die vollständige.

**F7 — Reihenfolge.** In welcher Reihenfolge müssten die Schritte kommen, damit das System
zu keinem Zeitpunkt kaputt ist? Nenne den einen Schritt, mit dem man anfangen sollte, und
begründe, warum gerade der.

Schreibe deine Antwort in die Datei, die dir als `--output-last-message` vorgegeben ist.
