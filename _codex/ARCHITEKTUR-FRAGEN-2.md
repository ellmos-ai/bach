# Zweitmeinung Runde 2: ocean-heart — wo lebt das Herz, und was ist schon gebaut?

Du bist Zweitmeinung zu einer **Erweiterung** eines Architekturkonzepts, das du in Runde 1
bereits geprüft hast (deine Antwort liegt als `_codex/ARCHITEKTUR-ANTWORT.md` im Repo; alle
deine Einwände wurden übernommen). Antworte auf Deutsch, knapp, substantiell. Widerspruch ist
erwünscht. **Read-only**, Worktree `C:/_Local_DEV/repos/BACH-heart2` (Stand `origin/main`
nach dem Merge von PR #50).

Lies `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md`, besonders die Kapitel **9** (Systemverbund)
und **10** (gemeinsames Herz mit OCEAN). Die Kapitel 1 bis 8 kennst du im Kern schon.

## Was sich seit Runde 1 geändert hat

Der Nutzer hat den Auftrag erweitert: Das Herz soll **für BACH und OCEAN gemeinsam** entwickelt
werden, hostübergreifend, mit Rücktransfer aus drei Schwestersystemen. Dazu sind zwei
Nachmessungen hinzugekommen, die frühere Aussagen korrigieren:

1. **Das Systemregister ist nicht dünn — seine Quelle ist reich.**
   `.SYNC/_inventory/systems-registry.json` hat vier Felder, aber
   `.SYNC/_inventory/systems/<slot>.json` trägt je Host rund 14 KB mit Chip, RAM, GPU,
   Tailscale-Adresse, SSH-Schlüssel, offenen Ports, installierter Software, Agenten und venvs.
   Die schmale Registry ist eine bewusste Ableitung
   (`ticket-master/lib/systems_registry.py::build_snapshot`, Docstring „DERIVED, never
   authored"), die genau die Erreichbarkeit wegfiltert, die eine Besetzung bräuchte.
   Die Quelldateien sind **handgepflegt** (`_gepflegt_von`, `_gepflegt_hinweis`).

2. **Ein hostübergreifendes Besetzungsprotokoll existiert bereits.**
   `ticket-master/lib/routing_contract.py` (1154 Zeilen) führt je Zielsystem ein Ledger mit
   Zuständen `pending|claimed|done|blocked`, und jede Zeile trägt eine Quittung mit
   Pflichtfeldern (`_RECEIPT_FIELDS`, Z. 988-991):
   `signature, status, executed_by, actual_provider, actual_model, occurred_at, evidence`.
   `record_receipt` (Z. 1041-1053) verweigert unvollständige Quittungen und nimmt sie nur unter
   passendem Anspruch an.

## Die zentrale neue Entscheidung

Wo lebt das Herz? Drei Optionen, Empfehlung im Dokument ist **C**:

- **A — BACH-intern.**
- **B — clutch erweitern** (clutch ist der vorhandene provider-neutrale Modellrouter mit
  Budget und Lernschleife, kennt aber keine Rollen, Rechte, Plätze, Fackeln).
- **C — eigenes Modul**, das BACH und OCEAN beide konsumieren; clutch bleibt Router und wird
  konsumiert statt erweitert.

Begründet über zwei Sätze aus OCEANs README: „extraction changes the bed, never the water"
(Z. 69) und „BACH stays supplied by consuming the same modules as OCEAN" (Z. 76); dazu die
Messung, dass OCEANs Extraktions-Roadmap (`architecture/BACH-EXTRACTION-ROADMAP.md`) im
zuerst gezogenen **Cluster 9** (System/Daten/Betrieb: Registry, dbsync, snapshot) **kein**
Modell-Backend-Paket führt, während LLM- und Mehr-Agenten-Orchestrierung ausdrücklich
**Cluster 5** ist (Z. 198).

## Deine Fragen

**G1 — Ort des Herzens.** Trägt die Empfehlung C? Prüfe insbesondere: Ist „clutch erweitern"
wirklich schlechter, oder unterschätzt das Dokument, wie nah Rollenwahl und Modellwahl
beieinanderliegen? Und ist ein eigenes Modul nicht bloß ein drittes Register neben den fünf,
die das Dokument selbst beklagt?

**G2 — Der Routing-Vertrag als Vorbild.** Das Dokument schlägt vor, für das
Besetzungsprotokoll die Feldnamen des Routing-Vertrags zu übernehmen statt neue zu erfinden.
Ist das richtig, oder vermischt es zwei Dinge, die getrennt gehören — Ticket-Transport gegen
Modell-Besetzung? Beachte, dass der Vertrag `claimed` bereits als Zustand führt, während BACHs
Worker ohne Anspruch startet. Sollte BACH den Vertrag **benutzen** oder nur sein Format
nachahmen?

**G3 — Handgepflegte Quelle.** Die reichen Inventardateien sind handgepflegt. Das Fackel-Prinzip
sagt „gemessen, nicht gebucht". Wo genau verläuft die Grenze: Welche Felder darf eine
Besetzungsentscheidung aus einer handgepflegten Datei lesen, und welche muss sie messen? Nenne
das Kriterium, nicht nur Beispiele.

**G4 — OCEANs Lokalitätsschranke.** `validate_model_locality` (in `ellmos-core`, nicht in
OCEAN selbst) erzwingt **nur lokale Modelle** und prüft bei Ollama, dass der Host lokal
auflösbar ist. Ein hostübergreifendes Herz will Modelle auf **anderen** Rechnern besetzen.
Ist das ein Widerspruch, der die Option C untergräbt, oder lässt er sich auflösen? Wie?

**G5 — Reihenfolge der Extraktion.** Das Dokument sagt: Fackel zuerst, Board als zweites, Tray
zuletzt, weil der Tray erst entflochten werden muss. Stimmt die Reihenfolge? Gibt es einen
Baustein, der vor allen dreien kommen müsste?

**G6 — Was ist zu viel?** Das Konzept hat jetzt zehn Kapitel und acht offene Entscheidungen.
Welche Entscheidung ist keine echte, sondern schon beantwortet? Welches Kapitel würdest du
streichen? Sag ausdrücklich, wenn du das Ganze für überbaut hältst.

Schreibe deine Antwort in die Datei, die dir als `--output-last-message` vorgegeben ist.
