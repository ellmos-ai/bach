# Imported Capabilities: Herkunft und tatsächlicher Transferstand

**Stand:** 2026-09-30 | **Ticket:** `T-20260929-797360984`

Dieser Nachtrag ersetzt die pauschalen Aussagen „eingebaut“, „überlegen“ und
„Kernlücke 1 geschlossen“ des historischen Katalogs vom 2026-09-29 unten.
PR #169 hat Kopien, Adapter und zehn Tests integriert. Das belegt keine
vollständige Integration der vier Quellpakete oder Überlegenheit gegenüber
BACH, Ocean und Skills. Die Kategorieverzeichnisse sind historische Zuordnungen.

## Herkunft und Lizenztexte

[PROVENANCE.json](PROVENANCE.json) enthält die geprüften Quellcommits,
Dateipfade, SHA-256-Werte der Git-Blobs, LF-normalisierte Vergleichshashes,
direkten AST-Importe und vorhandenen Lizenz-/NOTICE-Dateien. Es beschreibt
beobachtete Inhalte; der ursprüngliche historische Kopiercommit ist unbekannt.

| Quelle | Geprüfter Commit | Beobachteter Root-Lizenztext | Beigefügt |
| --- | --- | --- | --- |
| NemoFold | `b0545be39fc7740704f5bfe1b54458fe960dbdaf` | MIT | [LICENSE](licenses/NemoFold/LICENSE) |
| FolderHome | `2c52211dad0bb2680014a7da244dbacde5b8a23c` | MIT | [LICENSE](licenses/FolderHome/LICENSE) |
| Roshambo | `f56efcbb926294f12f75e39b8c5865d454164060` | Apache License 2.0 | [LICENSE](licenses/Roshambo/LICENSE), [NOTICE](licenses/Roshambo/NOTICE) |
| SentinelFleet | `e7f9c748df0ed6a677dbba38dcd725fe700fe75e` | GNU Affero General Public License, Version 3 | [LICENSE](licenses/SentinelFleet/LICENSE) |

SentinelFleet ist damit nicht durch die frühere pauschale Angabe „MIT/Apache“
beschrieben. Aus dem AGPL-Text allein wird keine Wahl „nur Version 3“ oder
„Version 3 oder später“ abgeleitet. Root-NOTICE-Dateien wurden nur bei
Roshambo gefunden; weitere Lizenzinventare sind im Manifest benannt.
Diese Bestandsaufnahme enthält keine rechtliche Gesamtfreigabe.

## Elf bisher ausgewählte Komponenten

Die Ziele sind die bestehenden Ocean-Modulzuordnungen; ein Zielname ist kein
Nachweis, dass die Quelle dort bereits exponiert oder ausführbar ist.

| Mac-Task / Priorität | Komponente | Ziel | Nachgewiesener lokaler Stand / Rest |
| --- | --- | --- | --- |
| 1510 / P1 | Roshambo-Leases | `coordination` | SQLite-Adapter mit UUID-v4-Fence und TTL, lokal unabhängig geprüft. Original-Roshambo benötigt PostgreSQL-/Paketabhängigkeiten. Runtime-Fence-Weitergabe offen. |
| 1511 / P2 | Failure Trails | `working_memory` | Kopie und eigener SQLite-Adapter; Originalimport benötigt unter anderem `psycopg` und fehlende Roshambo-Module. Kein belegter Task-Ausführungshook. |
| 1512 / P2 | FinanceStore | `finance_assist` | Kopiertes `finance_store/__init__.py`, lokal `contract_store.py` genannt. Es enthält FinanceStore, keinen Nachweis des vollständigen Vertrags-/Versicherungscockpits. `folderhome.contracts` fehlt. |
| 1513 / P1 | Model Armor | `K9-BOUNDARY` | Kopie und Adapter vorhanden; `pydantic` erforderlich, weitere Gateway-Imports benötigen `sentinel_fleet`. Keine belegte Runtime-Interceptor-Anbindung. |
| 1514 / P2 | Interrater | `evaluation` | Kopie und Adapter mit lokalem Test. Keine belegte Einbindung in den Skill `compare-race`; keine vergleichende Überlegenheitsabnahme. |
| 1515 / P2 | Action Journal | `K9-BOUNDARY` | Unveränderte Nemo-Kernmodule mit isoliertem Guard-Wrapper, lokal unabhängig geprüft. Copy/move nur unter explizitem exklusivem Hostguard; write/delete verweigert. Kein produktiver Hostguard-/Consumerbeleg. |
| 1516 / P2 | Administrative Notice / Dispute Loop | `doc_handler`, `finance_assist` | Kopien und eigener Prüfadapter. Vollständiges SentinelFleet-Paket/Workflow und fachliche Gesamtprüfung nicht belegt. |
| 1517 / P2 | Blueprint-/Chronicle-SVG | `ellmos-unified-gui` | Kopien plus eigener SVG-Adapter. Kein belegter neutraler GUI-Mount oder Recipe-Consumer. |
| 1518 / P3 | InventoryStore | `daily_life` | BACH-Adapter vorhanden; Quellkopie benötigt `folderhome.contracts`. Ocean-Exposition offen. |
| 1519 / P3 | MedicationStore | `health_assist` | BACH-Adapter vorhanden; Quellkopie benötigt `folderhome.contracts`. Ocean-Exposition offen; keine medizinische Funktionsabnahme. |
| 1520 / P2, abhängig von 1510 | Swarm Radar | `ellmos-unified-gui`, `coordination` | Eigener SQLite-Leseadapter. Kein belegter Live-Radar-/Multi-Host-GUI-Consumer. |

Die zwölf starken Lease-Gegenfälle prüfen echte deferred-FK-Commitfehler und
partielle DDL-Rollbacks unter drei SQLite-Modi. Journal-Gegenfälle prüfen
Guardverlust unmittelbar vor Mutationen, kurze Writes, Instanzisolation und
echten FD-Abschluss. Die geprüften Adapter ersetzen keine vollständigen
Quellpaket-Imports. Permanente CI wird als eigenes Delta vorbereitet.

## Atomarer Claim und offene Ausführungsgrenze

BACH `main` bei `7120cd1e891a447a8de1bb27f2b57480d47a435b` besitzt bereits
seit `2cfda653` einen conditional UPDATE vor Verarbeitung:
`worker.py` → `task.py:_claim` → `task_audit.claim_task_atomic` sowie
`chat_tray.py` → `gui/server.py` → denselben Claim. Die frühere Aussage
„worker nimmt offen[0] ohne Claim“ beschreibt diesen Stand nicht.

Offen ist die Konvergenz dieser vorhandenen Autorität mit dem UUID-/TTL-Vertrag
und die geprüfte Weitergabe des Fence bis Ausführung und Abschluss. Der
Journalwrapper hat derzeit Tests als Consumer; ein externer produktiver
Aufrufpfad wurde nicht belegt. Keine zweite Claim- oder Journalengine ist
aus diesen Tests abgeleitet.

## Messung und verbleibender Analyseumfang

Die schreibgeschützt gelesenen Mac-Tasks 1510–1520 beschreiben Status,
Priorität und Abhängigkeiten. „done/completed“ ist keine Implementierungs-
oder Abnahmebescheinigung. Die Leseverbindung nutzte SQLite `mode=ro` und
`query_only`; eine spätere separate Dateimessung ersetzt keinen
Vorher/Nachher-Beleg unveränderter Sidecars.

Die [statische Vergleichsmatrix](FEATURE-COMPARISON.md) erfasst inzwischen
die vollständigen getrackten Quellinventare mit Modul-, Skill- und
Endpunktzeilen, Importketten und konkreten Skills-/BACH-/Ocean-Gegenstücken.
Die elf ausgewählten Komponenten allein deckten diesen Analyseauftrag nicht ab.
Optionale/dynamische Importpfade, vollständige Paketabhängigkeiten und
produktive Transfergates bleiben bei fehlendem Beleg ausdrücklich offen.

---

## Historischer Katalog vom 2026-09-29 (durch obigen Nachtrag superseded)

Die folgenden ursprünglichen Beschreibungen sind historische Autorenangaben,
keine aktuelle Funktions-, Überlegenheits-, Lizenz- oder Integrationsabnahme.

Dieser Katalog dokumentiert die systematische Erfassung, Klassifikation und den Code-Transfer aus vier internen Spitzen-Repositories:
1. **NemoFold** (`ellmos-ai/NemoFold`) — Dokument-Agent, Evidenz-Bindung, Reversible Action Journals, Inter-Rater-Reliabilität.
2. **FolderHome** (`ellmos-ai/folderhome`) — Lokale Assistenz, Vertrags-/Versicherungscockpit, Haushaltsinventar, Medikationsplan, Bescheidprüfung.
3. **SentinelFleet** (`sentinel-fleet`) — Zero-Trust Model Armor, Sovereign Tool Gateway, § 14 UStG Dispute Loop, Blueprint Circuit SVG.
4. **Roshambo** (`ellmos-ai/roshambo`) — Multi-Agent-Koordinator, serielle atomare Leases, negatives Gedächtnis (Failure Trails).

Alle vier Quell-Repositories wurden **ausschließlich lesend** analysiert und nicht modifiziert.

---

## 1. Kategorie-Übersicht & Zuordnung

| Kategorie | Quelle | Komponente / Feature | Zielmodul (Ocean-Modul / Bundle) | Task-ID (Mac) | Status |
|:---|:---|:---|:---|:---:|:---:|
| **1. Schon gelöst, was wir bauen wollten** | Roshambo | Atomare serielle Leases (`leases.py`) | `open-ocean` / `coordination` (`ellmos-coordination-choice-bundle` / `lock-master`) | #1510 | Eingepflegt |
| **1. Schon gelöst, was wir bauen wollten** | Roshambo | Negatives Gedächtnis / Failure Trails (`memory.py`) | `open-ocean` / `working_memory` (`ellmos-working-memory-bundle` / `session-checkpoint`) | #1511 | Eingepflegt |
| **1. Schon gelöst, was wir bauen wollten** | FolderHome | Vertrags- & Kündigungscockpit (`finance_store`) | `open-ocean` / `finance_assist` (`ellmos-finance-assist-bundle` / `accounts-core`) | #1512 | Eingepflegt |
| **2. Besser gelöst als in Ocean/Bach/Skills** | SentinelFleet | Zero-Trust Model Armor (`model_armor.py`) | `open-ocean` / `K9-BOUNDARY` (Security Interceptor Gateway) | #1513 | Eingebaut |
| **2. Besser gelöst als in Ocean/Bach/Skills** | NemoFold | Inter-Rater-Reliabilität (`interrater.py`) | `open-ocean` / `evaluation` (`skills` / `compare-race` & `ellmos-agents-bundle`) | #1514 | Eingebaut |
| **2. Besser gelöst als in Ocean/Bach/Skills** | NemoFold | Reversibles 2-Phasen Action Journal (`action_journal.py`)| `open-ocean` / `K9-BOUNDARY` (Transaktionale Dateisystem-Schicht) | #1515 | Eingebaut |
| **2. Besser gelöst als in Ocean/Bach/Skills** | SentinelFleet | § 14 UStG Rechnungsprüfung & Dispute Loop | `open-ocean` / `doc_handler` & `finance_assist` (`ellmos-doc-handler-bundle`) | #1516 | Eingebaut |
| **3. Bereichernde Features für Ocean & Bach** | SentinelFleet | Dynamischer SVG Circuit & Blueprint Graph | `open-ocean` / `ellmos-unified-gui` (Recipe & Topology Visualizer) | #1517 | Mitgeliefert |
| **3. Bereichernde Features für Ocean & Bach** | FolderHome | Haushaltsinventar- & Verfallsdaten-Tracker | `open-ocean` / `daily_life` (`ellmos-daily-life-bundle`) | #1518 | Mitgeliefert |
| **3. Bereichernde Features für Ocean & Bach** | FolderHome | Medikationsplan & Einnahme-Logger | `open-ocean` / `health_assist` (`ellmos-health-assist-bundle`) | #1519 | Mitgeliefert |
| **3. Bereichernde Features für Ocean & Bach** | Roshambo | Swarm Radar / Multi-Agent GPS (`live map`) | `open-ocean` / `ellmos-unified-gui` & `coordination` | #1520 | Mitgeliefert |

---

## 2. Detaillierte Analyse je Kategorie

### Kategorie 1: Schon gelöst, das wir noch bauen wollten

1. **Atomare Distributed Leases (`category_1_solved_wanted/leases/`)**:
   - **Löst Bach Kernlücke 1** (ROADMAP.md Z. 677: *„Kein atomarer Claim. worker.py nimmt offen[0] und startet ohne Anspruch; chat_tray.py liest erst und markiert danach. Zwei Taktgeber können dieselbe Aufgabe mit Schreibrechten ausführen."*).
   - **Mechanismus:** Einzelschritt-SQL-Mutation ohne „check-then-write"-Rennbedingungen. Automatischer Timeout (TTL), Heartbeat-Verlängerung und Freigabe.
   - **Adapter:** `adapter_bach.py` bindet das Verfahren an SQLite (`tasks`-Tabelle) und Rheingold (Multi-Host-Federation).

2. **Negatives Gedächtnis / Failure Trails (`category_1_solved_wanted/failure_trails/`)**:
   - **Löst Bach Kognitions-Ziel** (ROADMAP.md Z. 630: *„Kognitives Memory-System ... Aktive Konsolidierung"*) und verhindert, dass autonome Subagenten in Endlosschleifen dieselben gescheiterten Ansätze wiederholen.
   - **Mechanismus:** Speichert fehlgeschlagene Pfade mit Fehlerursache, Kontext und Parametern ab. Vor Ausführung neuer Tasks wird das Fehlerschlag-Gedächtnis konsultiert.
   - **Adapter:** `adapter_bach.py` bindet `FailureMemoryStore` an die SQLite-Datenbank an.

3. **Vertrags- & Versicherungscockpit (`category_1_solved_wanted/contract_cockpit/`)**:
   - **Löst persönliches OS-Feature**: Fristenüberwachung von Verträgen, Versicherungen, Kündigungsterminen und monatlichen Fixkosten.
   - **Adapter:** `adapter_bach.py` liefert automatische Warnung vor nahenden Kündigungsfristen (Default: 60 Tage Fenster).

---

### Kategorie 2: Besser gelöst, als wir es bisher hatten

1. **Zero-Trust Model Armor (`category_2_superior_solutions/model_armor/`)**:
   - **Überlegenheit:** Kanonische Spacing-Normalisierung (erkennt getarnte Prompts wie `i g n o r e p r i o r`), rekursive Argumentprüfung bis 10 Ebenen Tiefe gegen Stack-Overflow/DOS, und PII-Maskierung (IBAN, API-Keys, Kreditkarten).
   - **Adapter:** `adapter_bach.py` schützt Prompt-Generatoren und Werkzeug-Ausführer.

2. **Inter-Rater-Reliabilität (`category_2_superior_solutions/interrater/`)**:
   - **Überlegenheit:** Ersetzt einfache Text-Diffs in `compare-race` durch echte statistische Reliabilitätsmetriken (Cohen's Kappa & Prozent-Übereinstimmung).
   - **Adapter:** `adapter_bach.py` liefert matrixbasierte Entscheidungsabgleiche zweier Modelle.

3. **Zwei-Phasen Action Journal (`category_2_superior_solutions/action_journal/`)**:
   - **Überlegenheit:** Rollback-Sicherheit mit Vorab-Prüfung aller Zielpfade, SHA-256-Prüfsummen vor und nach der Operation, atomarem Fsync-Schreiben und automatischem Crash-Reconciliation-Mechanismus.
   - **Adapter:** `adapter_bach.py` kapselt Dateimutationen in Bach ab.

4. **§ 14 UStG Rechnungsprüfung & Dispute Loop (`category_2_superior_solutions/administrative_notice_engine/`)**:
   - **Überlegenheit:** Vollständige Prüfung der 7 Pflichtangaben nach § 14 Abs. 4 UStG mit automatischer Generierung höflicher, rechtssicherer Korrekturbriefe.
   - **Adapter:** `adapter_bach.py` prüft und formuliert Korrekturschreiben.

---

### Kategorie 3: Bereichernde Features für Ocean und Bach

1. **SVG Blueprint & Circuit Graph Generator (`category_3_enriching_features/blueprint_graph/`)**:
   - Standalone-Vektorgraphik-Engine ohne externe Node-/npm-Abhängigkeiten.
   - Rendert interaktive Topologiekarten für Bach Services/Agenten und Ocean Paket-Rezepturen.

2. **Haushaltsinventar & Mindestbestand (`category_3_enriching_features/inventory_store/`)**:
   - Strukturierte Erfassung von Vorräten, Mindestbeständen und automatischen Einkaufslisten-Kandidaten.

3. **Medikationsplan & Einnahme-Logger (`category_3_enriching_features/medication_store/`)**:
   - Sichere Einnahme-Dokumentation mit Zeitstempeln und strikter Non-Diagnostic-Leitplanke.

4. **Swarm Radar / GPS (`category_3_enriching_features/swarm_radar/`)**:
   - Live-Kollisionsradar für Multi-Host-Agenten-Schwärme auf dem Bach Dashboard.
