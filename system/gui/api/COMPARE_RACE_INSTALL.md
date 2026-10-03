# Compare-Race im BACH-GUI

Der HTTP-Adapter nutzt `compare_race.race.run_race()` und dessen COMA-Spawner. Die
Mac-Prüfung am 03.10.2026 fand weder `compare_race` noch `coma` in der BACH-venv.
Auch `COMPARE_RACE_CONFIG` sowie drei geprüfte Standardkandidaten fehlten. Daher
meldet `/api/chat/compare-race/status` derzeit `unavailable`; es gab keinen
Provideraufruf.

## Geprüfte Quellen und Installation

Lokale kanonische Quellen, jeweils MIT und mit `pyproject.toml`:

| Paket | Geprüfter Stand | Version | Zweck |
| --- | --- | --- | --- |
| `compare-race` | `21372bcced8578950f9d483ed17a65c3b03b0496` | 0.7.1 | Race-Plan, Lanes, Evidenz |
| `coma` | `110b25b27a0de96d4be9d91a25cac7718db6af89` | 0.3.2 | CLI-Spawner und Adapter |
| `system-auditor` | `b01096bbd2dcb1fc7d2dd933d48997d3877394ca` | 0.9.2 | Token-Hilfsmodul für Compare-Race |

Der Mac-Owner prüft die dortigen kanonischen Quellen und installiert passende,
geprüfte Commits oder daraus gebaute Wheels in die bestehende BACH-venv. Keine
Windows-Nutzerdaten, lokalen TODO-Dateien oder Credentials kopieren. Die
Compare-Race-Abhängigkeit zu `system-auditor` ist als Git-URL deklariert;
bei pinngenauer Installation alle drei Pakete getrennt und ohne unkontrolliertes
Upgrade auflösen. Danach `import compare_race, coma, system_auditor` in der
BACH-venv prüfen. Das ist nur SDK-Abnahme, noch keine Providerfreigabe.

## Freigabevertrag

Die Konfiguration kommt ausschließlich aus `BACH_COMPARE_RACE_CONFIG`,
`COMPARE_RACE_CONFIG` oder `~/.compare-race/compare-race.config.json`. Nur
Operator-konfigurierte, von COMA verifizierte Lanes `claude`, `codex` und `agy`
werden angeboten. `BACH_COMPARE_RACE_ENABLED=1` ist ein zusätzlicher
Operator-Schalter. `BACH_COMPARE_RACE_MAX_LANES` (2–4) und
`BACH_COMPARE_RACE_MAX_SECONDS` (10–300 je Spur) begrenzen Aufrufe, bilden
aber **kein** Geldbudget ab. Die UI zeigt die lokale CLI-Erkennung und markiert
Providerzugang ausdrücklich als ungeprüft.

Vor einer echten Ausführung benötigt der Adapter das geprüfte Modul
`gui.api.compare_race_spend_authority` mit:

- `available() -> bool`: nur `True`, wenn eine autoritative, laufende
  Provider-Kostenstelle zugänglich ist.
- `reserve(*, device_id: int, model_ids: tuple[str, ...], max_seconds: int,
  prompt_chars: int) -> context manager`: Reservierung **vor** dem Subprozess,
  atomar gegen parallele Anforderungen, mit Abrechnung/Freigabe beim Verlassen
  auch nach Fehler oder Timeout. Die Stelle muss Modellpreise, laufendes
  Kontingent und das aktive Gerät kennen; ein bloßes Ja/Nein oder eine
  Zeitgrenze erfüllt den Vertrag nicht.

Dieses Modul existiert derzeit nicht. Der untersuchte ChatRuntime-Compute-Gate
schützt Modelllast, nicht Ausgaben; ClaudeBridge-Budget gilt für einen anderen
Dienst. Der Adapter bleibt deshalb fail-closed (`spend_authority_unavailable`).
Die HTTP-Route verlangt außerdem ein aktives, in der BACH-DB validiertes
Gerätetoken. Ein `confirm_cost`-Flag bestätigt nur die Anzeige und ersetzt
weder Authentifizierung noch Reservierung.

Ein Lauf benutzt sequentiell höchstens die ausgewählten Lanes, einen Durchgang
und einen isolierten Child-Prozess. Ergebnisse behalten `evidence_kind`; nur
erfolgreiche `live`-Antworten werden angezeigt. Eine Siegerentscheidung wird
nicht aus Simulation, manuellem Ergebnis oder Fehler abgeleitet. Provideraufrufe
und Mac-Deployment erfordern getrennte Abnahme durch den Owner.
