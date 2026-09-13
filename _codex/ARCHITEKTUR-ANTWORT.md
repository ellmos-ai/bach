## F1 — Grundunterscheidung

Die Grundidee trägt, aber **„Agent = Besetzung“ ist zu unscharf** und kollidiert mit dem vorhandenen `agent_instances`/`core.agent_runtime`-Begriff, der einen ausführbaren Agententyp bezeichnet.

Tragfähiger sind vier getrennte Begriffe:

- **Rolle:** versionierter Vertrag aus Fähigkeiten, Rechten, Werkzeuggrenzen und Budgetrahmen.
- **Agentenprofil:** ausführbare Kombination aus Backend-Adapter, Modellklasse, Host-Anforderungen und technischen Fähigkeiten.
- **Besetzung/Assignment:** zeitlich begrenzte Bindung von Rolle, Agentenprofil, Auftrag und Slot.
- **Run/Session:** konkrete Ausführung einer Besetzung mit eigener ID und tatsächlichem Modell.

`buddha_chat`, `buddha_always_on` und `buddha_connector` sind **Plätze beziehungsweise Dienstkanäle**, keine Rollen. `buddha_connector` ist sogar primär ein Ingress-Kanal. Ein Slot kann nacheinander unterschiedlich besetzt werden; eine Rolle kann gleichzeitig in mehreren Slots besetzt sein.

## F2 — Zwei Rollenwelten

Die Annahme von genau zwei Rollenwelten ist unvollständig. Zusätzlich existieren mindestens:

- `DEFAULT_ROLE_PROMPTS` in `slots_config.py`,
- `PERSONA_MAP` im Tray,
- `AGENT_DELEGATIONS` im Core-Launcher,
- `agent_instances` mit aktiver `core.agent_runtime`,
- Persona-Frontmatter und Launcher-Runtime-Defaults.

**Die DB sollte Wahrheit für Rollenverträge werden.** Slot-JSON bleibt zulässig für Platzkonfiguration und gewünschten Betriebszustand, darf aber keine kopierte Rollendefinition enthalten. Es sollte nur auf `role_id`, `agent_profile_id` und gegebenenfalls eine Prompt-Revision verweisen.

`preferred_backend` und `preferred_model` sind keine Wesensmerkmale einer Rolle, sondern weiche Besetzungspolitik. `fackel_bedarf` gehört überhaupt nicht an die Rolle, weil er von Modell, Kontextfenster und Host abhängt. Rechte und Budgetgrenzen gehören dagegen zum Rollenvertrag, müssen aber am Executor durchgesetzt werden.

Das größte Migrationsrisiko ist **stiller Bedeutungsverlust**: freie Prompttexte, Aliasnamen und benutzerdefinierte Slot-Prompts lassen sich nicht zuverlässig allein über Namen auf DB-Rollen abbilden. Hinzu kommt, dass die bisherige JSON-Fallbackwelt auch bei DB-Problemen starten kann. Deshalb: unveränderten Export sichern, IDs/Aliase explizit abbilden, unbekannte Prompts konservieren, zunächst dual lesen und Ergebnisse vergleichen; für Recovery einen minimalen statischen Safe-Mode behalten.

## F3 — Zuteilungsstrategie

„Clutch schlägt vor, BACH gated“ ist nur richtig, wenn die Gates **vor** der eigentlichen Auswahl wirken. Ein nachträgliches Veto erzeugt tatsächlich ein Zwei-Hirn-Problem.

Die Verantwortungsgrenze sollte so verlaufen:

1. BACH bildet anhand von Rechten, Host, Compute-Lock, Fackeln, Delegationstiefe und harten Budgetgrenzen die **zulässige Kandidatenmenge**.
2. Clutch bewertet und exploriert ausschließlich innerhalb dieser Menge.
3. BACH nimmt die atomare Besetzung vor und prüft unmittelbar vor dem Start noch einmal flüchtige Ressourcen.
4. Clutch erhält Feedback nur über das tatsächlich ausgeführte Modell.

Ein Gate-Ausschluss darf nicht als Modellmisserfolg in Epsilon-Greedy eingehen. Zu protokollieren sind mindestens Kandidatenmenge, Clutch-Vorschlag, tatsächlich gewähltes Modell, Fallbackgrund und Ergebnis. Infrastrukturfehler, Policy-Ablehnung und fachlicher Misserfolg brauchen unterschiedliche Ergebnisarten. Andernfalls lernt Clutch vor allem BACHs Vetos statt Modellqualität.

Der stille Rückfall auf `delegation_legacy` sollte im Zielzustand nicht bleiben: Er kann als ausdrücklich aktivierter Recovery-Modus existieren, aber nicht als unbemerkter zweiter Lern- und Routingkern.

## F4 — Fackeln vs. Budget

Die Prinzipien widersprechen sich nicht, weil sie verschiedene Dimensionen regeln:

- **Fackeln:** momentane physische Zulässigkeit auf einem Host.
- **Clutch-Budget:** kumulativer Verbrauch von Geld, Tokens oder Kontingent.

Eine Besetzung muss beide Bedingungen erfüllen, ohne daraus ein gemeinsames Guthabenkonto zu machen. BACH fragt: „Passt dieses konkrete Modell jetzt?“ Clutch fragt: „Ist diese Ausführung innerhalb des Verbrauchsrahmens sinnvoll und erlaubt?“

Es darf daher kein dauerhaftes Register „Agent X hält fünf Fackeln“ entstehen. Zulässig sind:

- eine Bedarfsschätzung aus Modell, Kontext und Host,
- die unmittelbar gemessene Belegung samt Messquelle,
- eine kurzlebige Admission-Lease beziehungsweise ein Start-Mutex gegen zwei gleichzeitige Modellstarts.

Diese Lease verhindert das Check-then-start-Rennen, behauptet aber keinen Ressourcenbesitz. Nach dem Start bleibt die reale Messung autoritativ.

## F5 — Beobachtbarkeit

**Nein: Ein Activity-Log darf nicht zugleich Ereignisstrom und aktueller Zustand sein.** Benötigt werden:

- ein append-only Ereignisstrom für Entscheidungen und Lebenszyklusänderungen,
- eine abfragbare Assignment-/Run-Tabelle oder deterministische Projektion für den aktuellen Zustand.

Für „Wer spielte um 10:34 welche Rolle?“ braucht eine Besetzung mindestens:

- `assignment_id`,
- `started_at` und `ended_at` beziehungsweise korrelierte Start-/End-Events,
- `role_id` plus Rollenrevision,
- `agent_instance_id`,
- tatsächlich verwendete `backend_id`, `model_id` und `host`,
- `slot_id`, `session_id` und möglichst `task_id`,
- `initiated_by` als menschlicher oder technischer Auslöser,
- Status, Ergebnis und Grund einer Umschaltung.

„Akteur“ muss dabei getrennt werden in **Auslöser** und **ausführende Instanz**. Bei Fackeln werden Präferenzwechsel mit altem/neuem Wert und Auslöser sowie Mess-Snapshots protokolliert. Ein Feld `held_by` wäre mit „gemessen, nicht gebucht“ unvereinbar.

## F6 — Was fehlt, was ist zu viel?

Der Vorschlag ist in seiner konkreten Form **an der Datenmodell- und Cockpitseite überbaut, an der Ausführungsgrenze aber unterbaut**.

Festlegung 5 würde ich aus dieser Migration streichen. Das Cockpit ist ein nachgelagerter Consumer und schafft keine korrekte Zuteilung. Auch Festlegung 1 muss umformuliert werden: Es braucht einen gemeinsamen **Backend-Katalog**, aber getrennte Adapterverträge für Chat-Backends und Prozess-Runner. `BACKEND_PRESETS` ist nicht alleinige technische Wahrheit; Verhalten und weitere Modelllisten liegen auch in `model_backend.create_backend()` und `CLIBackend.KNOWN_CLIS`. Ein flaches Register würde unterschiedliche Start-, Tool- und Sessionsemantiken verdecken.

Gefährlicher als die Registerduplikation sind zwei andere Lücken:

1. **Kein atomarer Claim:** Der Tray liest eine Aufgabe und setzt sie erst danach auf `in_progress`; der separate Worker startet offene Aufgaben sogar ohne vorherigen Claim. Mehrere Taktgeber können dieselbe Aufgabe mit Schreibrechten ausführen.
2. **Rechte sind nicht am Executor erzwungen:** Slot/API/Prompt können `full` setzen. Ein neues DB-Feld `rights` wäre nur Dokumentation, solange der zentrale Tool-/Prozessstarter es nicht prüft.

Zusätzlich erzwingt die Control API bei Remote-Bind keinen Authentifizierungsnachweis. Der POST-Guard prüft Origin und Content-Type; CORS ist keine API-Authentifizierung. Das ist besonders kritisch, weil darüber Slots geändert, Full-Mode-Worker gestartet und die Fackelpräferenz umgeschaltet werden können.

Auch der Ist-Befund zum Tray ist am geprüften Commit unvollständig: Er liest nicht nur `OLLAMA`, sondern auch `BUDDHA`, `BACH` und anschließend nahezu alle nicht-menschlichen Assignees. Dadurch ist seine tatsächliche Zuständigkeit breiter als beschrieben.

## F7 — Reihenfolge

**Anfangen sollte man mit einer zentralen `DispatchService`-Grenze für genau einen produktiven Pfad, vorzugsweise den Always-on-Worker.** Sie soll zunächst die bisherige Modellauswahl unverändert durchreichen, aber Aufgabe atomar claimen, Rechte prüfen, eine `assignment_id` erzeugen und Start/Ende protokollieren. Das ist der beste erste Schritt, weil er Doppelarbeit verhindert und einen Strangler-Seam schafft, ohne das bestehende Routing sofort umzubauen.

Danach:

1. Additive Assignment-/Eventtabellen und Zustandsprojektion einführen.
2. Chat-Backends und Runner unter einem Katalog mit getrennten Adaptertypen zusammenführen; bestehende Befehle per Paritätstests bewahren.
3. Rollenverträge in der DB kanonisieren; Prompt- und Aliasdaten zunächst dual lesen. Slots referenzieren Rollen nur noch.
4. BACHs harte Gates implementieren; Clutch zunächst im Shadow-Modus innerhalb der vorgefilterten Kandidatenmenge laufen lassen.
5. Nach Vergleich der Entscheidungen Clutch aktiv schalten und nur ausgeführte Runs zurückmelden.
6. Tray, separaten Worker, Launcher und später Scheduler-Trigger schrittweise durch dieselbe Dispatch-Grenze führen. Der Scheduler darf auslösen, aber nicht selbst Besetzungslogik besitzen.
7. Erst nach belegter Nutzungslosigkeit Whitelist, tote Router, doppelte Promptmaps und stillen Legacy-Fallback entfernen.
8. Zum Schluss die Projektion über `:8081/activity` und das GUI-Cockpit sichtbar machen.

Damit bleibt jeder Zwischenschritt rückwärtskompatibel und die neue Architektur wird vertikal bewiesen, bevor weitere Datenfelder oder Oberflächen entstehen.

