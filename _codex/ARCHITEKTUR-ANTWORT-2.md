## G1 — Ort des Herzens

**Empfehlung C trägt nur in einer deutlich schmaleren Form.** Als vorgeschlagenes Sammelmodul aus Rollenregister, Backend-Katalog, Zuteilung, Protokoll, Fackel, Wartung, Board und Tray wäre `agents-heart` tatsächlich ein drittes Register und ein neues Großmodul.

Das Konzept unterschätzt zudem clutch. Der aktuelle Code enthält bereits:

- `Fahrer` als ausdrücklich bezeichneten Orchestrator,
- `Getriebe` als providerneutrales Modellregister,
- Modellwahl, Ausführung, Failover und Lernschleife,
- Team-, Schwarm- und Kettenmuster,
- Profile, Prompt-Typen `rolle|agent`,
- default-deny Toolsets als Rechtevorstufe.

„clutch kennt keine Rollen oder Rechte“ ist daher nur noch teilweise richtig. Es besitzt keine **kanonischen Rollenverträge**, Slots oder hostübergreifenden Claims, ist diesen Achsen aber wesentlich näher als das Dokument darstellt. Auch OCEANs Roadmap beweist C nicht: Sie ordnet die Fähigkeit Cluster 5 zu, erklärt aber ausdrücklich, dass Cluster keine vorentschiedenen Paketnamen sind und ein neues Repository nur bei einer klaren API- und Zustandsgrenze gerechtfertigt ist.

Meine Empfehlung ist deshalb **C\***:

- `agents-heart` besitzt ausschließlich die Besetzungs-/Laufzustandsmaschine, atomare Admission und das Besetzungsprotokoll.
- clutch bleibt Eigentümer von Modellkatalog, Bewertung, Budget und Lernschleife und erhält nur die bereits zulässige Kandidatenmenge.
- agent-launcher beziehungsweise Backend-Adapter führen aus.
- Systeminventar und lokale Probes liefern Hosts und Ressourcen.
- Rollen kommen aus genau einem kanonischen Rollen-Repository; bestehende BACH-Tabellen werden migriert oder zu Adaptern, nicht parallel weitergeschrieben.
- Tray und Board sind Clients des Herzens, nicht Bestandteil seines Domänenkerns.

Damit bleibt Rollenwahl nahe an Modellwahl, ohne beides in derselben Komponente zu besitzen. **Ein Modul ist nicht automatisch ein Register; problematisch wird es erst, wenn es fremde Wahrheiten kopiert.** Den Backend-Katalog würde ich daher ausdrücklich aus Schritt 8 des geplanten `agents-heart` herausnehmen.

## G2 — Der Routing-Vertrag als Vorbild

**Feldvokabular und Invarianten übernehmen: ja. Den Ticket-Vertrag als allgemeine Besetzungsmaschine benutzen: nein.**

`routing_contract.py` ist eine dateibasierte Transportzustandsmaschine. `claim_contract()` beansprucht ein Ticket durch Umbenennen und Umschreiben der Vertragsdatei; `record_receipt()` beendet eine Zielzeile mit `done|blocked`. Das ist für seltene, hostübergreifende Ticketübergaben sinnvoll, aber nicht die richtige Persistenz oder Lebenszyklusgranularität für Chats, Slots, Scheduler-Läufe und lokale Worker.

Es sind zwei korrelierte Zustandsmaschinen:

1. **Transport:** Welcher Host hat das Ticket angenommen?
2. **Ausführung/Besetzung:** Welche Rolle wurde auf welchem Platz mit welchem Agentenprofil tatsächlich gestartet und beendet?

`claimed` im Transportvertrag ersetzt daher nicht den atomaren Claim der lokalen BACH-Aufgabe. Ein Host kann ein Ticket korrekt übernommen haben, während die lokale Ausführung noch nicht admitted, gestartet oder bereits abgebrochen ist.

Konkret:

- Bei einem Routing-v2-Ticket muss BACH den vorhandenen Vertrag tatsächlich benutzen und **vor** lokaler Ausführung claimen.
- Die lokale Aufgabe braucht zusätzlich einen atomaren Compare-and-set-Claim in ihrem kanonischen Task-Store.
- `assignment_id`, `run_id` und `ticket_id` korrelieren beide Ebenen.
- Am Laufende erzeugt das Herz eine gemeinsame, versionierte `ExecutionReceipt`, aus der der Ticket-Adapter die vorhandenen Felder `executed_by`, `actual_provider`, `actual_model`, `occurred_at`, `evidence` und `status` befüllt.
- `executed_by` muss präzisiert werden: Im Ticketvertrag meint es den Runner; für das Herz werden zusätzlich `agent_instance_id`, Rolle, Rollenrevision, Slot und Host benötigt.

Also weder Copy-and-paste noch eine direkte Abhängigkeit des Herzens von Ticketdateien. Am saubersten wäre die Extraktion eines kleinen gemeinsamen Claim-/Receipt-Vertragspakets, das ticket-master und `agents-heart` beide konsumieren.

## G3 — Handgepflegte Quelle

Das Kriterium lautet:

> **Handgepflegte Daten dürfen Absicht, Identität und mögliche Topologie beschreiben. Alles, dessen aktueller Wahrheitswert über Zulässigkeit, Sicherheit oder Erfolg eines konkreten Starts entscheidet, muss am Zielsystem frisch gemessen werden.**

Eine falsche oder veraltete Angabe beantwortet die Grenzfrage: Könnte sie einen unzulässigen Start, Datenabfluss, Ressourcenverdrängung, Doppelarbeit oder eine falsche Ausführungsquittung verursachen? Falls ja, darf sie nicht alleinige Admission-Grundlage sein.

Damit dürfen handgepflegte Daten beispielsweise:

- Host- und Slot-Identität,
- administrative Rolle,
- deklarierte Vertrauenszone,
- Hardwareklasse als grobe Vorauswahl,
- bekannte Adresse oder Schlüsselpfad als **Probe-Ziel**,
- gewünschte beziehungsweise erlaubte Provider

liefern. Ein menschliches Verbot oder eine Freigabe ist dabei Policy und darf durch eine Messung nicht überstimmt werden.

Frisch zu messen sind insbesondere:

- Erreichbarkeit und Authentifizierbarkeit,
- tatsächlich vorhandene und startbare Modelle/Runner,
- freie Fackeln, RAM/VRAM und Compute-Lock,
- laufende Jobs und Admission-Lease,
- Port- und Dienstgesundheit,
- Kontingent, Anmeldung und Providerzustand,
- tatsächlicher Provider, Modell, Host und Executor des Laufs.

Die aktuelle Inventarquelle ist außerdem nicht so homogen wie Kapitel 9 behauptet: Die Dateien reichen gegenwärtig von rund 14 KB bis 143 KB; `surface.json` ist vom 17.05.2026, und nur `mac-studio.json` besitzt die beschriebene Top-Level-Struktur `network`. Die Ableitung darf daher nicht einfach weitere Felder blind durchreichen. Sie benötigt ein versioniertes Schema, Provenienz, Messzeit/Freshness und einen Zustand `unknown`. **Adresse aus dem Inventar heißt „dort prüfen“, nicht „dort ist der Dienst erreichbar“.**

## G4 — OCEANs Lokalitätsschranke

Die angenommene harte Kollision besteht im aktuellen Code nicht. `_validate_local_endpoint()` erlaubt ausdrücklich:

- Loopback,
- private Adressen,
- link-lokale Adressen,
- den Tailscale-Bereich `100.64.0.0/10`.

`validate_model_locality` bedeutet also praktisch **on-premises beziehungsweise private Inferenz**, nicht zwingend „Modell auf demselben Rechner“. Ein Ollama-Modell auf dem Mac Studio über Tailscale kann die bestehende Prüfung bereits bestehen. Verboten bleiben öffentliche Ziele und – bei `local_models_only` beziehungsweise Tier L1 – Cloud-Provider.

Trotzdem reicht diese Prüfung für das Herz nicht aus. Eine private IP beweist weder Vertrauen noch Authentizität, und auch innerhalb von Tailscale verlässt der Prompt den Ursprungsrechner. Deshalb sollte die Lokalisierung dreistufig modelliert werden: `same_host`, `trusted_cluster`, `external`.

Bevorzugtes Muster:

1. Das Herz sendet eine authentifizierte, korrelierte Ausführungsanforderung an den Zielhost.
2. Der Zielhost misst seine Fackeln und Claims lokal.
3. Der Zielhost ruft sein Ollama über Loopback auf.
4. Er quittiert das tatsächliche Modell und die lokale Messung.

So bleibt „gemessen, nicht gebucht“ erhalten. Ein direkter Remote-Ollama-Aufruf sollte nur als ausdrücklich erlaubter `trusted_cluster`-Pfad mit Transportverschlüsselung, Dienstauthentifizierung und Datenfreigabe existieren. Die Lokalitätsschranke wird also nicht entfernt, sondern zu einem harten Vorfilter der Kandidatenmenge erweitert.

## G5 — Reihenfolge der Extraktion

**Tray zuletzt ist richtig. Fackel → Board → Tray ist aber nur als relative Reihenfolge nach einem vorgelagerten Vertrag vertretbar.**

Vor allen dreien muss ein kleiner, versionierter **Heart-/Dispatch-Vertrag** stehen:

- IDs und Zustandsmaschine für Besetzung und Lauf,
- atomarer Task-Claim und Admission-Lease,
- Rechteprüfung am Executor,
- Ports für Rollen, clutch, Host-Probe, Executor und Event-Sink,
- Lokalitäts- und Sicherheitsgrenze,
- genau ein State Owner,
- Paritäts- und Fehlertests.

Das entspricht OCEANs eigener Regel „Contract before code“. Auf Programmebene liegt außerdem Cluster 9 vor Cluster 5; ein Ausnahme-Gate für das Herz hebt die Kernel-, Lifecycle- und Reintegrationstore nicht automatisch auf.

Die Fackel ist entgegen Kapitel 10.8 **nicht unverändert extraktionsreif**: Sie importiert `hub._services.limits`, verwendet `BACH_FACKEL_KAPAZITAET_MB`, ist stark auf Ollama/Apple-Silicon-Probes zugeschnitten und meldet bei nicht messbarer Kapazität volle zehn Fackeln. Dieses Fail-open-Verhalten ist lokal als weicher Vorfilter erklärbar, darf einem fremden Host aber nicht als freie Kapazität angeboten werden. Für den Verbund muss `unknown` zu „nicht zulässig“ oder „weitere Messung erforderlich“ führen.

Auch das Board „liest“ nicht nur über HTTP. Es schaltet die Fackel und erstellt, startet, stoppt und löscht Worker per POST. Vor seiner Extraktion müssen daher authentifizierter Command-Vertrag und Autorisierung stehen.

Meine Reihenfolge:

1. Dispatch-/Heart-Vertrag und ein produktiver BACH-Pfad mit atomarem Claim.
2. Fackel als hostlokaler `ResourceProbe` hinter einer neutralen Schnittstelle.
3. Ereignisprojektion und authentifizierte Query-/Command-API.
4. Board als Client dieser API.
5. Tray nach Entfernung von Polling, Zuteilung und Ausführung.

## G6 — Was ist zu viel?

**Entscheidung 7 ist am eindeutigsten keine offene Entscheidung mehr.** `D-20260830-002` entschied bereits für neutrale, gemeinsam konsumierte Module; `D-20260903-001` setzte dieses Muster mit `assistant-core` um. Eine nachgebaute zweite OCEAN-Oberfläche wäre keine gleichwertige offene Alternative, sondern eine Abweichung von der bestehenden Entscheidung.

Darüber hinaus würde ich drei weitere Punkte aus der Nutzerentscheidungsliste entfernen:

- **E2:** Kapitel 4.2 hat bereits begründet entschieden: harte Gates bilden die Kandidatenmenge, clutch wählt darin.
- **E4:** Kapitel 4.5 entscheidet ausdrücklich, das Cockpit erst nach der Mechanik weiterzubauen.
- **E8:** Das ist eine falsche Entweder-oder-Frage. Inventar liefert Host-Discovery, Zielprobes liefern aktuelle Zulässigkeit, clutch bewertet Modelle. Alle drei werden gebraucht.

Streichen würde ich **Kapitel 6 „Zweitmeinung“ aus dem normativen Konzept**. Es ist wertvolle Provenienz, aber keine Architektur. Als Anhang oder separate Reviewakte bleibt es erhalten; im Hauptdokument wiederholt es Kapitel 2 bis 5 und wird mit jeder weiteren Reviewrunde länger.

**Mein Gesamturteil:** Der notwendige Dispatch-Kern ist nicht überbaut. Das Dokument und der derzeit beschriebene Umfang des Herzens sind es. Rollenregister, Modellkatalog, Tickettransport, Hostinventar, Fackel, Wartung, Board und Tray in ein Modul zu ziehen, würde einen neuen Monolithen schaffen. Ein kleines `agents-heart` für Claims, Admission, Assignments und Runs – mit clutch, Inventar, Rollenstore und Executor als klar getrennten Ports – ist dagegen eine tragfähige gemeinsame Architektur für BACH und OCEAN.