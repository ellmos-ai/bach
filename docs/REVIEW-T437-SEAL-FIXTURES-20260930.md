# T437: hermetische Release-Stichprobe

Autor: GPT-6.1-Sol. Unabhängige Astra-Abnahme bleibt erforderlich.
Base: `e3fbd8f15e5dfc74466b64d42b509d3d789f7b82`.
Eigener Worktree: `C:\_Local_DEV\worktrees\bach-seal437-codex-20260930`.
Main, expliziter OneDrive-Twin und eigener WT wurden frei geprüft.
Klon hat keine `CLAUDE.md`; Twin-`CLAUDE.md` und `REPO.pointer.json` belegen
`ellmos-ai/bach`, lokalen Klon und Main als Git-Autorität. Gemessen wurde
am frisch gefetchten Default, nicht am fremden Hauptklon-Arbeitsbaum.

## Pflichtkriterium und gemessene Differenz

Das vollständige Ticket T-20260927-437372073 fordert im Feld ANFORDERUNGEN
„Startup-Check-Existenzkriterium angleichen“. PR151 ist bereits integriert;
Root-Fallback und Auswahl des neuesten Versionshashs werden nicht neu gebaut.
Die bestehende Startup-Sektion 0.75 meldet **jede** fehlende Sample-Datei.
Das manuelle Tool akzeptierte dagegen vier von fünf vorhandenen Dateien.
Der alte Kommentar bezeichnete dies fälschlich als gleiches Startup-Kriterium.
Eine Policy oder Entscheidung für die Toleranz einer fehlenden Datei wurde
nicht belegt. Dies war eine gemessene Differenz, keine belegte Absicht.

Der enge Fix verlangt fünf vorhandene Samples. Er verschärft das Gate;
er ändert kein Kriterium zugunsten grüner Ergebnisse. Hash-Abweichungen
bleiben wie im integrierten PR151 informativ. Das ist ein Präsenznachweis,
keine vollständige Hash- oder echte Release-/Seal-Abnahme.

## Explizite Zuordnung der Restanforderungen

| Restanforderung | Tatsächlicher hermetischer Beleg |
|---|---|
| Root-/System-Pfade | Root-README/requirements/start, system-Präfix, system-relative Datei; bestehender system-first Vorrang und fehlender Pfad |
| Neuester Hash statt historischem JOIN | Je Sample alter und neuer Versionsdatensatz; Ausgabe muss 5/5 Hash-Match zeigen |
| Template-Fallback | Ohne Versionsdatensätze ebenfalls 5/5 Hash-Match |
| Hash-Drift bleibt informativ | Fünf geänderte vorhandene Dateien ergeben Präsenz-PASS und Hash-Match 0/5 |
| Manuelles Tool vollständig, mindestens vier Prüfungen | Zehn private synthetische Releases mit je 200 CORE-Dateien; tatsächliches run_all jeweils 4 PASS, 0 FAIL |
| Startup meldet jede Fehlmenge | Ausschließlich unveränderten Sektion-0.75-Quellblock aus dem aktuellen AST als Callable in Temp-DB/Temp-Dateien ausgeführt; Fälle 0 bis 5 fehlende Dateien |
| Exakte Gate-Angleichung | Eine fehlende Datei: vor Fix 1 failed/5 passed, nach Fix Manual-FAIL und Startup-Warnung; alle fünf vorhanden: beide ohne Fehlmeldung |
| Zu wenige Samples | Vier vorhandene Manifest-Samples bleiben FAIL |
| Keine DB-Nebenwirkung | DB-Bytes vor/nach Prüfungen gleich; mode=ro verweigert DELETE und erzeugt fehlende DB nicht |

Die Startup-Fixture startet keinen StartupHandler, keine Dienste oder Jobs.
Nur der genau identifizierte bestehende Präsenzblock wird ausgeführt; bei
Änderung seiner Struktur scheitert die Fixture ausdrücklich. Kein echter
Seal wurde berechnet, akzeptiert oder repariert. Die künstliche
instance_identity dient ausschließlich zur Aktivierung dieses Testblocks.

Neue Suite: `system/tests/test_seal_release_sampling.py`, **22 passed in
20.38s, keine Skips**. Ruff der neuen Suite und `git diff --check` bestanden.
Basetemp: `C:\_Local_DEV\test-tmp\seal437-final22`.
Keine Workflowänderung; Einbindung in CI benötigt einen separaten Auftrag.
Die alten Claims „10/10 live“ oder externe CI sind nicht diese Belege.

Offen: unabhängige Abnahme, Integration und echte CI, sofern autorisiert.
Live-DB, Runtime, Startup, Release, Tags, Deployment, Remote- und Ticketwrites
wurden nicht ausgeführt.
