# Zweitmeinung: was eingewandt und was übernommen wurde

Zwei Runden Codex `gpt-5.6-sol`, Stufe `high`, read-only. Diese Datei trägt die Provenienz,
damit das Konzeptdokument sie nicht mit jeder weiteren Runde mitschleppt.

**Regel für diese Datei:** Jede Zeile nennt den Einwand, wohin er eingearbeitet wurde, und ob
die zugrunde liegende Tatsachenbehauptung nachgemessen wurde. Ein Einwand ohne Nachmessung
wird nicht übernommen — auch nicht von einem guten Reviewer.

## Runde 1 — der Entwurf

| Einwand | Übernommen als | Nachgemessen |
|---|---|---|
| „Agent = Besetzung" kollidiert mit der Tabelle `agent_instances`; es braucht vier Begriffe | Abschnitt 4.1: Rolle, Agentenprofil, Besetzung, Lauf, dazu Platz | `core/agent_runtime.py::AgentRegistry` führt die Tabelle — bestätigt |
| Gates gehören **vor** die Auswahl, nicht als Veto danach | Abschnitt 4.2, Schritte 4 und 5 | Argument, keine Tatsachenbehauptung |
| Fackeln und Budget dürfen kein gemeinsames Konto bilden; es braucht eine kurzlebige Startsperre | Abschnitt 4.3 | — |
| Das Protokoll kann nicht zugleich Ereignisstrom und Zustand sein | Abschnitt 4.4, mit Feldliste | — |
| `BACKEND_PRESETS` ist nicht die alleinige Wahrheit | Abschnitt 2.1 und 5 | `model_backend.py::CLIBackend.KNOWN_CLIS` Z. 708, `create_backend` Z. 952 — **bestätigt, war übersehen** |

Dazu drei Lücken, die der Entwurf nicht kannte, alle nachgemessen und bestätigt: kein atomarer
Claim (`worker.py:167-193` gegen `chat_tray.py:567-575`), keine Rechtedurchsetzung am
Ausführenden, kein Authentifizierungsnachweis an der Control API (`_is_allowed_origin` Z. 2955
prüft nur Herkunft).

## Runde 2 — die Erweiterung auf ocean-heart

| Einwand | Übernommen als | Nachgemessen |
|---|---|---|
| Option C in der breiten Fassung ist selbst ein Monolith und ein drittes Register | Abschnitt 10.2: Verengung auf **C\*** — nur Besetzung, Anspruch, Zulassung, Protokoll; Backend-Katalog ausdrücklich draußen | Argument, gestützt auf die Roadmap-Aussage, dass Cluster keine Paketnamen vorentscheiden |
| „clutch kennt keine Rollen und Rechte" ist zu stark | Abschnitt 10.2, eigener Absatz | `clutch/fahrer.py`, `clutch/getriebe.py`, `prompt_library.py:20` mit Typen `rolle` und `agent` — **bestätigt, eigene Darstellung war zu stark** |
| Feldvokabular des Routing-Vertrags übernehmen ja, den Vertrag als Besetzungsmaschine benutzen nein | Abschnitt 9.4: zwei korrelierte Zustandsmaschinen, `assignment_id`/`run_id`/`ticket_id` verbinden sie | Argument; `claim_contract` beansprucht per Umbenennung — falsche Granularität für einen Fünf-Sekunden-Takt |
| Kriterium für handgepflegte gegen gemessene Daten | Abschnitt 9.4, als Blockzitat übernommen | — |
| Das Inventar ist nicht homogen | Abschnitt 9.4, mit Größentabelle | 14 KB bis 143 KB; `mac-studio.json` ist die **kleinste**; `network` steht nicht überall — **bestätigt, eigene Verallgemeinerung war falsch** |
| OCEANs Lokalitätsschranke ist kein Widerspruch zum Verbund | Abschnitt 10.1, eigener Absatz, plus das Auftragsmuster statt Fernaufruf | `ellmos-core/config.py:139-141` erlaubt Tailscale `100.64.0.0/10` — **bestätigt, eigene Deutung war falsch** |
| Die Fackel ist nicht extraktionsreif und ist fail-open | Abschnitt 10.8 | `frei()` gibt bei nicht messbarer Kapazität `float(FACKELN)` zurück, Import `hub._services.limits` Z. 33 — **bestätigt** |
| Das Board liest nicht nur, es schreibt | Abschnitt 10.8 | Fackel schalten, Worker anlegen, starten, stoppen, löschen per POST — bestätigt in Abschnitt 2.9 |
| Vor allen Extraktionen fehlt ein Vertrag („contract before code") | Abschnitt 10.8, fünfstufige Reihenfolge | OCEANs eigene Regel |
| Vier der acht Entscheidungen sind keine | Abschnitt 7.1, als Feststellung statt als Wahl | Argument — und es trägt: eine im selben Dokument beantwortete Frage vorzulegen ist Rückdelegation |
| Kapitel „Zweitmeinung" gehört nicht ins normative Dokument | Kapitel 6 auf einen Verweis verdichtet, Detail in dieser Datei | — |

## Was nicht übernommen wurde

Nichts. In beiden Runden wurde jeder Einwand übernommen. Wo die Zweitmeinung eine
Tatsachenbehauptung aufstellte, wurde sie vorher nachgemessen — in vier Fällen gegen die eigene
frühere Darstellung, und in allen vier Fällen hatte die Zweitmeinung recht.
