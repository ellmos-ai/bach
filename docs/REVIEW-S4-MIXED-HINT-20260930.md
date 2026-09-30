# S4 Punkt 4 — unbekannten CLI-Rest vor Auswahl erhalten

session: 01a0f189-21d6-7851-a075-0aab0e3ebe77 | codex-gui-program@ASUS-GEI | 2026-09-30

Auftrag: Nachbesserung des unabhängigen Astra-Befunds, ausschließlich S4
Punkt 4. Der eng abgenommene Punkt 3 und CLI-Rohregeln bleiben unverändert.
Frisch gefetchte Basis `ef27cbd82bf3628e9d4181c56444002d83fd52b8`;
ursprüngliches Delta `d3005c7b51c678672e1de7806e04329465916e98` unverändert
als `00dded363f1c4c359f8be62e4efe8d1a72fe1090` übernommen.
Keine GUI-Commits, Live-/Runtime-/Remote- oder Ticketänderungen.

## Tatsächliche Rot-Grün-Belege

Regression-Commit `2b927d182364a3c3c4bebd193f73a22227237cf0` enthält alle
drei originalen Fälle:

- `Gemischt: bach steuer status | python3 absent.py`
- `Gemischt: bach steuer status | python "absent.py"`
- `Gemischt: bach steuer status | --unknown-danger`

Die neun parametrisierten Prüfungen im Helper, tatsächlichen Legacy-
InjectorSystem und tatsächlichen externen Memoryhook scheiterten vor dem
Fix: **9 fehlgeschlagen, 24 deselektiert**. Der Helper verlor den unbekannten
Rest; beide Auswahlpfade zeigten ihn als scheinbar gültige Dokumentation an.
Nach dem Fix bestehen sämtliche Fälle. Die Tests prüfen unveränderten
Originaltext, keine Auswahl/Nutzungszählung/Cooldown für abgewiesene Hinweise,
anschließende Auswahl eines gültigen Hinweises und unveränderte CLI-Ausgabe.
Externe Datenbankprüfungen verwenden ausschließlich private Temp-DBs.

## Reparatur

Jeder ursprüngliche CLI-Marker muss vollständig einem aufgelösten lokalen
Verweis zugeordnet werden. Python und Python3 unterstützen auch quotierte
Pfade; unauflösbare Aufrufe bleiben sichtbar im Original und werden gefiltert.
Optionsnamen werden vollständig erkannt. Eine Option benötigt einen belegten
Eintrag im Dokument oder Python-Ziel des zugehörigen Befehlsabschnitts;
ein dokumentierter gleichnamiger Schalter hinter einer Pipe wird nicht
stillschweigend einem vorherigen Befehl zugerechnet. Unbekannte, fehlende,
außerhalb des Systems liegende oder nicht lesbare Ziele erhalten den ganzen
Hinweis. Erst danach erfolgen bestehende Auswahl, Zählung und Cooldown.

Die ältere Regel `arzt` enthält `bach gesundheit termine --upcoming`.
`--upcoming` fehlt aktuell sowohl im zugehörigen Hilfetext als auch im
Handler; deshalb bleibt dieser Hinweis unverändert und wird im API-Modus
abgewiesen. Die frühere positive Umwandlungserwartung wurde durch eine
ausdrückliche Filter-/CLI-Unverändertheitsregression ersetzt. Positive
Gegenproben für `appointments --all`, `backup create --to-nas` und beide
quotierten Pythonformen bleiben erhalten. Keine gespeicherte Regel geändert.

## Gesamter autorisierter Prüfumfang

Vier ursprüngliche Testdateien einschließlich neuer Regressionen:
`test_context_manual_hints.py`, `test_consolidation_handler.py`,
`test_context_injector_db.py`, `test_injector_parity.py`:
**226 bestanden in 52,84 Sekunden, keine Skips**.
Für die sechs Gardener-TTL-Fälle wurde dessen vorhandener Quellpfad explizit
rein lesend über `PYTHONPATH=C:\_Local_DEV\repos\gardener` ergänzt und
Bytecode deaktiviert. Ein vorausgehender Lauf ohne diesen Pfad hatte
220 bestanden und sechs Skips; er ist ausdrücklich nicht die Vollabnahme.
Private DB-/Runtime-/Backup-/Secretpfade erzwingt die unveränderte conftest.
Ruff für reparierten Helper/Test und Diffprüfung sauber.

Die sieben weiteren Dateien des ursprünglichen S4-Deltas sind bytegleich
zum Originalcommit, insbesondere Punkt-3-Policy und Ausführungsfolge.
CI-Ergänzung wird als eigener Ein-Zeilen-Workflowcommit geliefert.
Unabhängige andere-Modell-Abnahme sowie neue tatsächliche CI/Integration
stehen aus; kein Gesamt-S4-/Mutterprogramm-Abschluss.
