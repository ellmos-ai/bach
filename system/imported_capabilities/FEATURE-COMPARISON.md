# T797: Vollständiges statisches Quellinventar und Vergleichsmatrix

**Stand:** 2026-09-30. **Ticket:** `T-20260929-797360984`.

[FEATURE-COMPARISON.json](FEATURE-COMPARISON.json) erfasst alle getrackten
Dateien der vier festgelegten Quellstände. Vergleichszeilen gibt es für jedes
Python-Modul außerhalb `tests/`, jeden kanonischen mitgelieferten `SKILL.md`
und jeden Eintrag des FolderHome-Endpunktkatalogs. Übersetzungen, Tests,
Schemas und weitere Ressourcen bleiben im vollständigen Dateiinventar.
425 Zeilen bedeuten keine 425 unabhängigen Produktfeatures: Hilfsmodule,
Beispiele, Verträge und Abnahmeprogramme sind ebenfalls erfasst.

## Quellen und Umfang

| Quelle | Commit | Getrackte Dateien | Python-Module | Skills | Endpunkte |
| --- | --- | ---: | ---: | ---: | ---: |
| NemoFold | `b0545be39fc7740704f5bfe1b54458fe960dbdaf` | 796 | 95 | 1 | — |
| FolderHome | `2c52211dad0bb2680014a7da244dbacde5b8a23c` | 606 | 138 | 13 | 33 |
| Roshambo | `f56efcbb926294f12f75e39b8c5865d454164060` | 164 | 57 | 2 | — |
| SentinelFleet | `e7f9c748df0ed6a677dbba38dcd725fe700fe75e` | 171 | 54 | 32 | — |

Vergleichsstände: BACH `b7891cba74cc72024234ccd644dc68ea3c9b7844`,
Ocean `7127a0f5beea7d3784121c89ca69a118af5ca32b`, öffentliche Skills-Quelle
`eb547edd176f1ef2e78a8ab464b9975855ec16c8`. Der `.SKILLS`-Mirrorpointer nennt
noch `7356934dbb22db29340b0069adbbc0fc992f21ca`; er wird nicht mit dem neueren
Git-Stand gleichgesetzt. Das zusätzlich gelesene lokale Skillinventar ist
durch Einzelhashes und einen Gesamthash gebunden. Private Gegenstücke sind
über Hashreferenzen im privaten Analyse-Receipt auflösbar, ohne persönliche
Skillpfade in diesem öffentlichen Dokument zu veröffentlichen.

## Vergleich nach Funktionsbereichen

Die folgenden BACH-Pfade sind konkrete Vergleichsgegenstücke, keine Zusage
gleicher Semantik. Die JSON-Zeilen enthalten deren Hashes und definierte APIs,
passende öffentliche Skillpfade und die tatsächliche Ocean-Matrixzeile.

| Bereich | Quelloberfläche und möglicher Mehrwert | Konkreter BACH-Gegenpart | Ziel / offenes Vergleichsgate |
| --- | --- | --- | --- |
| Koordination | Roshambo `leases`, SentinelFleet Task-/Ticket-Lifecycle, Conductor/Swarm: zeitgebundene Anspruchs- und Ablaufmodelle | `hub/task_audit.py`, `hub/task.py` | Ocean `coordination`; vorhandenen Claim mit UUID/Fence bis zur Ausführung verbinden. Kein neuer Claim von null. |
| Gedächtnis | Roshambo `memory`/Embeddings, SentinelFleet Bank/Gardener/Hooker, Nemo-Notebooks: unterschiedliche strukturierte Gedächtnisoberflächen | `hub/memory.py`, `hub/memory_hook_provider.py` | `working_memory`; Paketabhängigkeiten, dauerhafter Caller und Konsolidierungsparität offen. |
| Evaluation | Nemo `interrater`, Vollständigkeit, Corroboration, Verifier und G01–G16: zusätzliche Metriken und explizite Beleggates | `hub/seal.py` als bestehendes Qualitätsgate; Skill `compare-race` | `evaluation`; Seal ist keine Cohen-Kappa-Implementierung. Kein Beleg, dass Interrater bereits in compare-race läuft oder bessere Entscheidungen erzeugt. |
| Sicherheit | SentinelFleet Armor/Gateway/Permissions/Privacy/Identity, Nemo Authority/Anonymizer, FolderHome Ressourcenpolitik: mehrere unterschiedliche Grenzen | `tools/fs_protection.py`, `hub/agent_spawn_gate.py` | `K9-BOUNDARY`; Regex-/PII-Oberfläche ist keine vollständige Autorisierung oder Laufzeitabsicherung. |
| Dateisystem | Nemo ActionJournal/SmartInbox/StoragePolicy, FolderHome FilesystemTransaction/Plan/Execution/Cleanup: nachvollziehbare Plan- und Undo-Verträge | `tools/fs_protection.py`, `hub/fs.py` | `K9-BOUNDARY`; Journalwrapper lokal geprüft, exklusiver produktiver Pfadguard/Consumer nicht belegt. |
| Finanzen und Verwaltung | FolderHome FinanceStore und eigenes vollständiges ContractCockpit, Benefit-/Notice-/Tax-Workflows; SentinelFleet OmniLedger | `hub/steuer.py`, `hub/abo.py` | `finance_assist` / `doc_handler`; kopierter FinanceStore ersetzt nicht das vollständige Cockpit. Fach-/Laufzeitparität nicht abgenommen. |
| Gesundheit | FolderHome HealthDossier/MedicationIntake/Store, Nemo MedicationReconcile: beleggebundene Dokument- und Einnahmeoberflächen | `hub/mediplaner.py`, `_services/mediplaner_projection.py` | `health_assist`; vorhandene BACH-Funktion und offene Ocean-Exposition getrennt betrachten. Keine medizinische Abnahme. |
| Haushalt | FolderHome Inventory/Household/DailyBriefing, Quellvorlagen für Vorräte und lokale Briefe | `hub/haushalt.py`, `_services/household/inventory_engine.py` | `daily_life`; BACH-Mindestbestand/Einkaufsprojektion vorhanden, Ocean-Exposition nicht dadurch bewiesen. |
| Kalender | FolderHome Store/ICS/Handoff/Connector-Verträge, SentinelFleet Scheduler-Mathematik | `hub/calendar_handler.py` | Ocean-Matrix `calendar` mit Skill-Carrier; Ressourcen-/Providerkonfiguration und semantische Parität offen. |
| Kontakte | FolderHome ContactRegistry, Nemo ContactMonitor, SentinelFleet PrivacyContacts | `hub/contact.py` | Matrix `contact` / `mail-connector`; unterschiedliche Aufbewahrungs-/Bestätigungsgrenzen vergleichen. |
| Mail und Korrespondenz | FolderHome Draft/Gateway/Connector/Correspondence, Nemo Mail/Recipient-Bridge | `hub/email.py` | Matrix `email`; Draft-, Versand- und Rücknahmegrenzen nicht aus ähnlichen Namen ableiten. |
| Recherche und Evidenz | Nemo EvidenceAnalyst/FactDistill/WebResearch, SentinelFleet WebReader/Research | `hub/docs_search.py`, `hub/doc.py` | `doc_handler` / `working_memory`; Belegbindung, Budget und Netzwerkfreigaben als eigene Verträge. |
| Medien und Diagramme | Nemo Chronicle-/Report-SVG, FolderHome ArtifactStudio, SentinelFleet BlueprintGraph | `hub/media.py` | `ellmos-unified-gui` / Dokumentoberfläche; keine belegte Mount-/Recipe-Einbindung dieser Kopien. |
| GUI | Nemo Webapp/Wizard, FolderHome LocalApp/Installer, SentinelFleet Webserver/Governance | `hub/gui.py`, `gui/server.py` | Neutraler GUI-Consumer; Auth-, Branding-, Offline- und Mount-Parität separat prüfen. |
| Modell-/Cloud-Provider | Nemo Provider/NemoClaw/Nebius, FolderHome AgentCore/Strands, Roshambo AWS, SentinelFleet Backends/Router | `hub/clutch.py`, `hub/agent_router.py` | Tatsächliche Matrix-Carrier; optionale Extras, Credentials, Preise und externe Freigaben nicht konfiguriert oder ausgeführt. |
| Dokumente | Nemo Extraktion/Index/QA/Compose/Voyages/StructuredSources, FolderHome Ingest/Search/Package/Versions, SentinelFleet PDF/StructuredDocuments | `hub/doc.py`, `hub/docs.py` | `doc_handler`; zusätzliche Quell-APIs beobachtet, vollständiger Workflowtransfer nicht belegt. |
| Orchestrierung und Paketoberflächen | CLI/MCP/Application/Recipes/Runtime und unterstützende Verträge aller vier Quellen | `hub/agent_launcher.py`, `hub/chain.py` | Bestehende Matrix-Carrier; kein Ersatz der vorhandenen Agenten-/Governanceautorität. |

## Kategorien und tatsächlicher Transfer

1. **Quelle für bestehende Wünsche:** Roshambo-Leases/Failure Trails und
   FolderHome-Finanz-/Cockpitoberflächen sind vorhanden. Die jeweilige
   BACH-/Ocean-Ausführungsgrenze ist damit noch nicht geschlossen.
2. **Vergleichskandidaten:** Die historischen Armor-/Interrater-/Journal-/
   Verwaltungszuordnungen bleiben als Kandidaten erkennbar. Diese Analyse
   weist keine gemessene Überlegenheit aus. Definierte Source-APIs und
   Guards sind belegbare Eigenschaften, keine Rangordnung vollständiger Systeme.
3. **Bereicherungskandidaten:** Die übrigen Quelloberflächen sind vollständig
   inventarisiert und Vergleichsbereichen zugeordnet. Das erteilt weder einen
   pauschalen Transfer- noch einen Deploymentauftrag.

[PROVENANCE.json](PROVENANCE.json) bindet die 19 bisherigen Originalkopien
an konkrete Sourceblobs. Für jede Quellzeile ist getrennt verzeichnet, ob
sie zu diesen Kopien gehört. Die elf Adapter sind kein vollständiger Import
aller Quellpakete. Lease-/Journal-Sicherheitsabnahmen gelten für den lokalen
Kandidaten `0d393bb9`, nicht als produktive Caller-/Host-/Mac-Abnahme.
Mac-Tasks 1510–1520 sind Metadatenbelege, keine Abnahme der dort behaupteten
Umsetzung; insbesondere enthalten 1511 und 1515 weiterhin Blockertexte.

## Abhängigkeiten und Beweisgrenzen

Pro Modul sind sämtliche AST-Importstellen, die transitive interne
Python-Importkette, Stdlib-Imports, externe oder nicht aufgelöste Imports
und dynamische Import-/exec-Stellen erfasst. Dazu kommen alle deklarierten
Pyproject-Abhängigkeiten/Extras sowie vorhandene `uv.lock`-/Requirements-
Manifeste mit Hashes und Paket-/Versionsangaben. Beim FolderHome-Katalog
bleiben logische Ressourcen, Effekte und der Unterschied zwischen
`typed_adapter_available`, `planning_only` und `no_typed_adapter` erhalten.

Das ist die vollständige **statische deklarierte** Abhängigkeitsaufnahme.
Dynamisch gewählte Ressourcen, Provider, Netzwerkbudgets und tatsächliche
Umgebungskonfiguration werden nicht als vollständig gelöst ausgegeben.
`runtime_dependency_closure_proven` bleibt deshalb ausdrücklich falsch.
Roshambo benötigt unter anderem PostgreSQL-/CockroachDB- und Paketmodule;
FolderHome-Kopien referenzieren `folderhome.contracts`; SentinelFleet-Kopien
referenzieren das Originalpaket und Pydantic. Ein erfolgreicher eigener
SQLite-Adaptertest beweist diese Quellimporte nicht.

Die Ocean-Vergleichsdatei bei `7127a0f` enthält weiterhin den historischen
BACH-Auditcommit `39d2457a`. Ihre `carrier`-/`gap`-Zeilen und
`use_case_state`-Felder werden unverändert zitiert; die modernen BACH-Dateihashes
sind ein eigener Beleg und kein stilles Upgrade dieser Paritätsabnahme.
