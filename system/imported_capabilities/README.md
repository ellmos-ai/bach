# Imported Capabilities Architecture & Provenance Catalog

**Stand:** 2026-09-29 | **Host:** ASUS-GEI | **Ticket:** `T-20260929-797360984`

Dieser Katalog dokumentiert die systematische Erfassung, Klassifikation und den Code-Transfer aus vier internen Spitzen-Repositories:
1. **NemoFold** (`ellmos-ai/NemoFold`) — Dokument-Agent, Evidenz-Bindung, Reversible Action Journals, Inter-Rater-Reliabilität.
2. **FolderHome** (`ellmos-ai/folderhome`) — Lokale Assistenz, Vertrags-/Versicherungscockpit, Haushaltsinventar, Medikationsplan, Bescheidprüfung.
3. **SentinelFleet** (`sentinel-fleet`) — Zero-Trust Model Armor, Sovereign Tool Gateway, § 14 UStG Dispute Loop, Blueprint Circuit SVG.
4. **Roshambo** (`ellmos-ai/roshambo`) — Multi-Agent-Koordinator, serielle atomare Leases, negatives Gedächtnis (Failure Trails).

Alle vier Quell-Repositories wurden **ausschließlich lesend** analysiert und nicht modifiziert.

---

## 1. Kategorie-Übersicht & Zuordnung

| Kategorie | Quelle | Komponente / Feature | Ziel in BACH / OCEAN | Status |
|:---|:---|:---|:---|:---:|
| **1. Schon gelöst, was wir bauen wollten** | Roshambo | Atomare serielle Leases (`leases.py`) | `system/core/leases.py` & TaskHandler | Eingepflegt |
| **1. Schon gelöst, was wir bauen wollten** | Roshambo | Negatives Gedächtnis / Failure Trails (`memory.py`) | `system/hub/_services/memory/` | Eingepflegt |
| **1. Schon gelöst, was wir bauen wollten** | FolderHome | Vertrags- & Versicherungscockpit (`finance_store`) | `system/capabilities/contract_cockpit/` | Eingepflegt |
| **2. Besser gelöst als in Ocean/Bach/Skills** | SentinelFleet | Zero-Trust Model Armor (`model_armor.py`) | `system/core/model_armor.py` | Eingebaut |
| **2. Besser gelöst als in Ocean/Bach/Skills** | NemoFold | Inter-Rater-Reliabilität (`interrater.py`) | `system/hub/_services/interrater.py` | Eingebaut |
| **2. Besser gelöst als in Ocean/Bach/Skills** | NemoFold | Reversibles 2-Phasen Action Journal (`action_journal.py`)| `system/core/action_journal.py` | Eingebaut |
| **2. Besser gelöst als in Ocean/Bach/Skills** | SentinelFleet | § 14 UStG Rechnungsprüfung & Dispute Loop | `system/capabilities/administrative_notice_engine/` | Eingebaut |
| **3. Bereichernde Features für Ocean & Bach** | SentinelFleet | Dynamischer SVG Circuit & Blueprint Graph | Bach Web GUI & Ocean Recipe Topology | Mitgeliefert |
| **3. Bereichernde Features für Ocean & Bach** | FolderHome | Haushaltsinventar- & Verfallsdaten-Tracker | `system/capabilities/inventory_store/` | Mitgeliefert |
| **3. Bereichernde Features für Ocean & Bach** | FolderHome | Medikationsplan & Einnahme-Logger | `system/capabilities/medication_store/` | Mitgeliefert |
| **3. Bereichernde Features für Ocean & Bach** | Roshambo | Swarm Radar / Multi-Agent GPS (`live map`) | `system/gui/` & Swarm Coordinator | Mitgeliefert |

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
