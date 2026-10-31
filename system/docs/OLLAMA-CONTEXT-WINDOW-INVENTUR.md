# OLLAMA-CONTEXT-WINDOW-INVENTUR

Inventur zum Eltern-Task **#2545** (Kontextfenster lokaler Modelle `num_ctx` einstellbar machen),
Resultat des abgeschlossenen Kind-Tasks **#2968** (num_ctx-Fundorte a–k).

Zeilenangaben sind Navigationshilfe, keine Wahrheitsbelege; exakte Wortlaute im Quelltext prüfen.

## Fundorte a–k

### (a) Backend-Vorbild: `system/hub/_services/llm/model_backend.py`
- env-Zugriff Z26; num_ctx-Handling Z126–154: `configured_num_ctx = num_ctx if num_ctx is not None else os.environ.get("OLLAMA_NUM_CTX", "4096")`.
- int()-Konvertierung mit `except (TypeError, ValueError)` → `ValueError("Ollama num_ctx muss eine ganze Zahl sein")`.
- Range-Check `if not 512 <= self.num_ctx <= 262144:` → `ValueError("Ollama num_ctx muss zwischen 512 und 262144 liegen")`.
- `get_context_limit` Z152–154.

### (b) Provider-Options: `system/chat/local_provider_config.py`
- Key-Tuple Z60 inkl. `"num_ctx"`, `"timeout_seconds"`; env `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, `OLLAMA_TIMEOUT_SECONDS`; `ValueError`-Grenzen: 511 abgelehnt, ganzzahlig, True/False (bool) abgelehnt.

### (c) Reserve-Whitelist: `system/chat/local_resource_reserve.py`
- Whitelist/Absicherung Z124/130: `_integer(num_ctx, 512, 262_144)`.
- Vergleich Budget/Beobachtung Z292/295: `observed.resident_context >= budget.num_ctx`.

### (d) Chat-Runtime-Zugriff: `system/chat/chat_runtime.py`
- `getattr(backend, "num_ctx", None)` Z1345/1775 — Backend-Attribut wird gelesen, CLI-Pfad liefert das bisher nicht.

### (e) Kaltstart-Beobachtung: `system/chat/buddha_cold_start.py`
- Z104–112: `record_observation` mit Schema `bach.local-load-observation.v1` (Anknüpfungspunkt Messroutine #2970).

### (f) Förderbericht-Pipeline: `system/document/foerderbericht_pipeline.py`
- Z733–762: num_ctx aus env oder `loaded_ctx or 12288`; `num_predict 6000`, temp 0.2.
- Abbruchkriterium „Kontext erschoepft (used von num_ctx)" wenn `done_reason == length`.

### (g) Report-Provider: `system/document/report_provider_adapter.py`
- Z1240: Docstring/Reserve-Bezug zu num_ctx.

### (h) CLI-Weg (ohne num_ctx): `system/hub/ollama.py` → `system/tools/ollama/ollama_client.py`
- `ollama_client.py`: `OllamaModel` Z27 (Felder name/size_bytes/modified_at/digest — kein num_ctx), `OllamaClient` Z65, `list_models` Z144, CLI Z400–419.
- `generate` Z182–240: payload `{"model", "prompt", "stream"}`, system, `merged_options` (temperature, num_predict), think. `chat` Z242–294 analog (payload `{"model","messages","stream"}`).
- Beide Pfade (`_post` Z347, `_curl_post` Z377) erhalten dasselbe payload → ein options-Merge genügt.
- Kein num_ctx, kein env-Fallback, keine Validierung.

### (i) Hub-Config-Datei: `system/hub/ollama.py`
- `target_file` Z53–55: `self.base_path / "data" / "ollama_config.json"` — bisher ohne num_ctx-Format.
- `__init__` Z35–37 (`self._client = None`), lazy client-Property Z39–47, `get_operations` Z57–63 (status/ask/models/embed), `_ask` Z138–189, `_embed` Z191 ff.

### (j) Tests (Bestands-Satz, kein neuer Test im Auftrag)
- `system/tests/test_local_provider_options.py` — Provider-Options-Parsing/Grenzen.
- `system/tests/test_model_backend.py` — Z340 options num_ctx 8192; Z395–408 `OllamaBackend().num_ctx == 4096` ohne env.
- `system/tests/test_local_resource_reserve.py` — 262145 abgelehnt; `reserve.observe_ollama` = Vorbild für #2970.
- `system/tests/test_foerderbericht_modus.py` — Z119/141–150 num_ctx 16384, keep_alive 30m.

### (k) Doku
- `docs/architecture/LOCAL-MODEL-RESERVE.md` Z38/50: `kv_headroom_bytes`/`overhead_bytes`/`num_ctx`, „Kontext muss zum tatsächlich gesendeten num_ctx passen".
- `CHANGELOG.md` Z41 (num_ctx-Bezug).

## Zwei Wege für num_ctx

1. **Backend-Weg (existiert):** `model_backend.py` num_ctx-Attribut + env `OLLAMA_NUM_CTX` (Default 4096), Validierung 512–262144; Provider-Options key num_ctx; Reserve prüft Budget gegen `num_ctx`; chat_runtime liest `backend.num_ctx`.
2. **CLI-Handler-Weg (baut #2545):** `system/tools/ollama/ollama_client.py`:
   - `OllamaModel` bekommt Feld `num_ctx: int = 4096` + `__post_init__`-Validierung (int() und Range 512–262144, Meldungen wie (a)).
   - `OllamaClient.__init__` erhält `num_ctx: int = None`; ohne Param greift env `OLLAMA_NUM_CTX` (Default „4096" wie Vorbild (a)); gleiche Validierung.
   - `generate`/`chat` erhalten Parameter `num_ctx`; Anwendung per `merged_options.setdefault("num_ctx", <effektives num_ctx>)` vor dem `if merged_options:`-Block — deckt `_post` und `_curl_post` ab.
   - `system/hub/ollama.py`: `_load_num_ctx_config()`/`set_num_ctx(model, num_ctx=None, num_ctx_recommended=None)` über `target_file` (`data/ollama_config.json`, Format `{"models": {"<name>": {"num_ctx": int, "num_ctx_recommended": int}}}`); Laden best-effent (Datei fehlt/korrupt → `{}`), Schreiben mit `json.dumps(indent=2)`; `_ask` liest num_ctx je Modell und ruft `client.generate(prompt, model=model, num_ctx=...)` (None → Client-Default/env).

## Defaults
- CLI/Backend: **4096** (env `OLLAMA_NUM_CTX` überschreibbar, Default „4096").
- Förderbericht-Pipeline: **16384** (bevorzugt), dazu keep_alive 30m, num_predict 6000, temp 0.2.
- Zulässiger Range überall: **512–262144** (Whitelist (c), Grenzen (b)).

## Übergabeschwelle
- **12300–14400 Tokens, 80 %-Schwelle, PR#520-Harness: nicht im Repo** (geprüft: Repo-weit nicht vorhanden, auch nicht in `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md` — Treffer dort nur Delegation/GUI-Kontext; und nicht in `docs/architecture/LOCAL-MODEL-RESERVE.md`).
- Stammen aus der Übergablage; behandelt als „extern/PR#520". Kind-Task #2973 macht die Schwelle relativ zu `num_ctx`.

## Offene Punkte je Kind-Task (#2545)
- **#2968** Inventur/Finden der Fundorte a–k — **abgeschlossen**; diese Doku ist das Resultat.
- **#2969** CLI-Client num_ctx (`system/tools/ollama/ollama_client.py`: OllamaModel-Feld, Client-Param, generate/chat-Merge) — wird im aktuellen Zug umgesetzt.
- **#2970** Messroutine lokal (resident/Kontext-Auslastung); Vorbild: `reserve.observe_ollama` in `chat/local_resource_reserve.py`, Anknüpfung `bach.local-load-observation.v1` (e).
- **#2971** `system/hub/ollama.py`: Config-Laden/Schreiben + `set_num_ctx` + `_ask`-Anwendung — wird im aktuellen Zug umgesetzt.
- **#2972** GUI `ellmos-system-gui` (anderes Repo) — Einstellfläche für num_ctx pro Modell.
- **#2973** Übergabeschwelle (12300–14400 / 80 %) relativ zu num_ctx statt absolut.
- **#2974** LLM-Beratung (Empfehlungen zu num_ctx pro Modell/Gerät).