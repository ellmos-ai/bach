<img src="assets/banner_v2.png" width="100%" alt="BACH Banner">

# ellmos BACH — Textbasiertes Betriebssystem für LLMs

> Der Fluss, der alles vereint.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-v3.15.0-orange)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/Status-Production--Ready-brightgreen)](ROADMAP.md)
[![Tests](https://img.shields.io/badge/Tests-4436%20gesammelt-blue)](system/tests/)
[![Last Checked](https://img.shields.io/badge/Last_Checked-2026--10--18-brightgreen)](CHANGELOG.md)
[![Haftung](https://img.shields.io/badge/Haftung-%C2%A7_521_BGB-blue)](https://www.gesetze-im-internet.de/bgb/__521.html)
[![Security SLA](https://img.shields.io/badge/Security_Response-48h_duale_SLA-blue)](SECURITY.md)

**Version:** v3.15.0

## 🎬 Demo-Video

BACH live im Einsatz erleben — Dashboard, Codex-Backend, Operator-Steuerung — in 2:22 Min.:

[![BACH Demo — lokales LLM-Betriebssystem (2:22)](assets/bach-demo-preview.png)](https://youtu.be/Gv5nxF8HssU)

### Screenshots (folgt)
Echte Screenshots der BACH-GUI 0.2.29 folgen. Namensschema und Mindestumfang stehen im Bildvertrag: [assets/gui/README.md](assets/gui/README.md).

## Sprachen

Die README-Dokumentation ist in elf Sprachen verfügbar. Die Übersetzungsabdeckung für die Laufzeit ist davon getrennt und umfasst im aktuellen Release-Snapshot de, en, es, ru, ja und zh.

[English](README.md) | **Deutsch** | [Español](README.es.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [Français](README.fr.md) | [हिन्दी](README.hi.md) | [العربية](README.ar.md) | [বাংলা](README.bn.md) | [Português](README.pt.md)

Der aktuelle Release-Snapshot aktiviert `de`, `en`, `es`, `ru`, `ja` und `zh` in `system/exports/translations/languages_config.release.json` und exportiert passende Locale-Dateien in `system/exports/translations/locales/`. Für Web-Crawler und direkte Spracheinstiege existiert zudem für jede Sprache eine eigene `README.md` unter `docs/i18n/<lang>/`.

<p align="center">
  <img src="overview.jpg" alt="BACH Überblick" width="700">
</p>

## Überblick

**BACH** ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befähigt, eigenständig zu arbeiten, zu lernen und sich zu organisieren. Als Herzstück der **ellmos**-Familie (Extra Large Language Model Operating Systems) bietet BACH eine umfassende Infrastruktur für Task-Management, Wissensmanagement, Automatisierung und Multi-Agenten-Orchestrierung.

## 📦 Download, Geführte Installation & Ocean-Editions-Branding

Egal ob du über eine Suche auf **BACH** oder auf **[open-ocean](https://github.com/ellmos-ai/open-ocean)** landest — beide Wege führen dich zur selben modularen **Ocean**-Plattform mit gemeinsamer Oberfläche (`ellmos-system-gui`):

1. **Betriebssystem-Installer (Primärer Weg) & App-Stores (Zusatzservice):**
   - **Windows:** Nativer `.exe`- / `.msi`-Installer (ergänzend der **Microsoft Store** als komfortabler Zusatzservice)
   - **macOS:** Nativer `.dmg`- / `.pkg`-Installer
   - **Linux:** Nativer `.AppImage`- / `.deb`- / `.rpm`-Installer
   - Technisch getragen vom [`ellmos-installer`](https://github.com/ellmos-ai/ellmos-installer) und der transaktionalen [`open-ocean`](https://github.com/ellmos-ai/open-ocean)-Engine.
2. **Hermes-inspirierte 4-stufige Out-of-the-Box-Menüführung & jederzeitiges Nach-/Deinstallieren (`Rinnsal ↔ BACH ↔ Meer`):**
   - Nach dem Start leitet dich der Installer (`ellmos-installer onboarding`) streng geordnet von wichtig zu unwichtiger durch alle Verbindungen:
     1. **Stufe 1 — Modelle, Subscriptions & API-Zugänge:** Lokale Modelle (**Ollama**) erkennen sowie Subscriptions und API-Keys (**Claude**, **Codex/OpenAI**, **Gemini**, **OpenRouter**, **Ollama Cloud**, **Kimi**) sicher im lokalen Keyring hinterlegen.
     2. **Stufe 2 — Wichtige System-MCPs, Berechtigungs- & Autoritätseinstellungen:** **`ellmos-filecommander`** und **`ellmos-controlcenter-mcp`** (sowie `codecommander`/`homebase`) konfigurieren; Arbeitsbaum-Zugriffsbereich (`sandbox | ocean | free`), Review-Modus und 5-stufige Eskalationsleiter einstellen.
     3. **Stufe 3 — Connectoren:** **Telegram**, **WhatsApp**, **Discord** und **E-Mail-Bridge** direkt verbinden.
     4. **Stufe 4 — Ausdehnung (`Rinnsal ↔ BACH ↔ Meer`), Plugins, weitere MCPs & Skills:** Das öffentliche Ocean bringt eine **Standard-Ausdehnung** an Modulen mit. Indem du Module, Plugins, MCPs und Skills bei der Einrichtung an- oder abwählst — oder **Bestandteile später jederzeit über den Installer bzw. die System-GUI nachinstallierst oder deinstallierst** — erhältst du dein individuelles Ocean: schlank wie ein **Rinnsal**, kuratiert wie ein **BACH** oder breit ausgebaut wie ein **Meer**.
3. **Eintrittsweg bestimmt das Branding (`bach` vs. `open-ocean`):**
   - **Einstieg über `bach` (dieses Repository):** Du erhältst das **BACH-Branding**, bei dem **ebenfalls Ocean im Vordergrund der GUI steht**, BACH aber als kuratierte Versions-/Ausprägungsform von Ocean dargestellt wird (*„BACH — eine Edition von Ocean“*).
   - **Einstieg über [`open-ocean`](https://github.com/ellmos-ai/open-ocean):** Reines **Ocean-Branding** (das BACH-Branding entfällt).
4. **Berechtigungs- & Systemstufen (`full-ocean` · `ocean-dev` · `ocean-admin`):**
   - **`full-ocean`:** An den `ellmos-installer` gebundenes Zugangskonzept — gewährt Zugriff auf den vollen Ocean-Katalog, soweit du dazu berechtigt bist (für normale Nutzer alle öffentlichen Module; für berechtigte Personen zusätzlich nicht-öffentliche/lizenzierte Fachmodule).
   - **`ocean-dev`:** Entwickler-, Diagnose- und Bau-Module (`system-explorer`, `system-auditor`, `system-gap-master`, `ellmos-tests`, `module-gate`), die durchaus öffentlich sein können, aber von normalen Nutzern nicht zwingend mitinstalliert werden.
   - **`ocean-admin`:** Das vollständige Betreiber-/Maintainer-Gesamtsystem (mit Mac Studio als 24/7-Leader, Workstations, unveröffentlichten privaten Fach-/Forschungsmodulen und `.SYNC`).

## 🧭 Kern-Governance: Identität & Autoritätsfluss, 3-Ursachen-Dokumentationsmodell & Transparente Entscheidungsverarbeitungsregeln

Das Verhalten von **BACH** und **Ocean** wird durch **transparente, einsehbare und vom Nutzer einstellbare Entscheidungsverarbeitungsregeln (`decision_processing_rules`)** bestimmt. Nichts geschieht als Blackbox: Jede Autoritätsprüfung, jede Klassifikation einer Doku-Abweichung und jeder ausgelöste Aktionszweig erzeugt eine nachvollziehbare Regelspur (`decision_rule_trace`).

### 1. Identität, 3-Stufen-Autoritäts-Tunneling & Schutz vor der „Autoritätswüste“

- **Identität vs. Autorität:** **Identität** entsteht durch Kontobesitz auf dem Gerät und die einmalige Registrierung von Gerät/Kanal (Geheimnisse liegen unsichtbar im lokalen Keyring). **Autorität** fließt vom Nutzer über **Operator-Kanäle** (Konsole, Telegram, System-GUI-Chat) zweckgebunden an beauftragte Subagenten und Hintergrund-Worker.
- **Natur (Automatische Erosion & Drift) vs. Terraforming (Gewollte Formung):** Erosion und Drift entstehen von selbst durch die reale Systemnutzung (Kontext-Kompaktierung, Sitzungswechsel, Zeitverlauf) — es gibt keinen künstlichen Verfalls-Cronjob, der gültige Entscheidungen entwertet. Wenn wir `DECISIONS.md`, `AKTUELLER-PLAN.md`, `USER.md` oder Code bewusst ändern, ist das **Terraforming**: überholte Einträge werden direkt an der Quelle als `superseded` markiert.
- **3-Stufen-Tunneling & Inward-First-Kaskade (`open-ocean/tools/escalation_ladder.py`):**
  1. **Stufe 1 — Semantisches Authority-Tunneling (~80 % reversibler Alltag):** Schnelle Ausführung innerhalb eines aktiven Goals/Plans (`authority_ref`, `active_goal_or_plan_id`), verhindert unnötige Rückfragen trotz kontextgesichertem Userwillen (**Fehlerklasse `error_authority_desert` / Autoritätswüste**).
  2. **Stufe 2 — Deterministischer Zitate-Tunnel (~15 % Schwellen-Übergänge, `ellmos-authority-evidence`):** Extrahiert aus NemoFold (`evidence.py`); prüft in `< 1 ms` (`validate_quote_tunnel_evidence`), ob das mitgelieferte `literal_quote` **wortwörtlich** und nicht-`superseded` in der Originalquelle (`DECISIONS.md`, `transcript.jsonl`, `AKTUELLER-PLAN.md`) steht.
  3. **Stufe 3 — Harte Kryptografie- & Lock-Gates (~5 % irreversibel / Hochrisiko):** Durchgesetzt über `lock_status.py` (`LOCK.user.*`), gehashte Sicherheitsfrage (`ellmos-installer`) und Ed25519-`capability-grant.v1`-Zertifikate.

```mermaid
flowchart TD
    classDef userLayer fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef cogLayer fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46
    classDef tunnelLayer fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e
    classDef errorLayer fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b

    subgraph L0["1. Ursprung: Natur (Erosion/Drift) vs. Terraforming (Gewollt)"]
        U["Nutzer im Operator-Kanal\n(Konsole, Telegram, GUI-Chat)"]:::userLayer
        TF["Terraforming (Gewollte Formung)\nDECISIONS.md, Plan, USER.md, policy-registry"]:::userLayer
        NAT["Natur & Tektonik (Automatische Erosion)\nKontext-Kompaktierung, Sitzungswechsel, Zeit"]
        U -->|"Formt aktiv"| TF
    end

    subgraph L1["2. Kognitives System & 3-Stufen-Autoritäts-Tunneling"]
        COG["Kognitives System + WorkflowHookers\n(Metakognition, Goals, Pläne, Skills -> Want to Act)"]:::cogLayer
        T1["Stufe 1 (~80% Reversibel)\nSemantic Authority Tunneling"]:::tunnelLayer
        T2["Stufe 2 (~15% Schwellen)\nDeterministischer Zitate-Tunnel (<1ms Wörtlich-Check)"]:::tunnelLayer
        T3["Stufe 3 (~5% Irreversibel)\nHartes Gate (LOCK.user / Sicherheits-Hash / Ed25519)"]:::tunnelLayer
        U --> COG
        TF --> COG
        COG --> T1
        COG --> T2
        COG --> T3
        TF -.->|"Wörtlicher Abgleich"| T2
        NAT -.->|"Erodiertes Zitat fällt durch"| T2
    end

    subgraph L2["3. Authority Checker, Inward-First-Kaskade & Reflexion"]
        CHK{"Authority Checker:\nAre you allowed to act?"}:::tunnelLayer
        ACT["JA: Sofort ausführen (Do It)"]:::cogLayer
        ASK["NEIN: Inward-First-Kaskade (Ask There To Get)\n1. Goal/Kontext -> 2. DECISIONS/USER.md\n-> 3. Parent-Orchestrator -> 4. User-Gate"]:::tunnelLayer
        REF["After-Action Reflection & Learning\nVerhindert Autoritätswüste (error_authority_desert)"]:::errorLayer

        T1 --> CHK
        T2 --> CHK
        T3 --> CHK
        CHK -->|"Ja"| ACT
        CHK -->|"Nein"| ASK
        ASK -->|"Aufgelöst"| ACT
        ACT --> REF
    end
```

### 2. Das 3-Ursachen-Dokumentationsmodell & Einstellbare Entscheidungsverarbeitungsregeln (`system/tools/llmauto/config.json`)

Stellt die automatisierte Dokumentationsprüfung (`ellmos-doc-keeper` + NemoFold-Claim-Nachbelegung) eine Abweichung zwischen Doku (`system/docs/help/*.txt`, `README.md`, `SKILL.md`, GUI `/help`) und gemessener Realität fest, überschreibt sie **niemals blind gewollte SOLL-Architektur**. Stattdessen klassifiziert `classify_doc_reality_diff()` den Diff deterministisch in **3 Ursachen**, und `resolve_doc_machine_dispatch()` wählt anhand transparenter, frei kombinierbarer **Entscheidungsverarbeitungsregeln** die Aktionszweige (`selected_branches`):

| Ursache (`classify_doc_reality_diff`) | Bedeutung | Transparente Aktionszweige (`selected_branches` — einzeln oder kombiniert einstellbar) |
|---|---|---|
| **1. `unintended_erosion`** *(Ungewollte Erosion / Drift)* | Doku beschreibt das richtige Verhalten, aber Code/Dienst ist ungewollt kaputtgegangen oder abgedriftet. | **SOLL in Doku bewahren** + IST-Warnhinweis setzen + Standard-Kombination **`["local_taskplan", "user_notification"]`** (stellt P1-Reparatur-Task für Hintergrund-Worker ein und benachrichtigt Nutzer; optional kombinierbar mit `local_genie_marblerun` oder `gitlab_wishes_come_true`). |
| **2. `planned_terraforming_pending`** *(Fehlendes / geplantes Terraforming)* | Vorauseilende Doku: beschreibt gewolltes SOLL aus Plan/`DECISIONS.md`, das im Code noch nicht fertig ist. | Taskstatus in `taskplan` prüfen/anpassen bzw. P2-Umsetzungs-Task über **`["local_taskplan"]`** anlegen + in der Doku sauber als **SOLL (mit Task-ID)** vs. **IST** trennen. |
| **3. `completed_terraforming_doc_lag`** *(Erfolgtes Terraforming mit lückenhafter Doku)* | Vorauseilender Code: wurde gewollt weiterentwickelt (Commit/PR/`task_status=done`), Doku hinkt hinterher. | Zweig **`["local_doc_update"]`**: zieht `.txt`-CLI-Help, `.md`-Doku, CLI/API-Referenzen und Übersetzungen (`de/en/es/ja/ru/zh`) automatisch lokal nach. |

```mermaid
flowchart TD
    classDef probe fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e
    classDef c1 fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b
    classDef c2 fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef c3 fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46

    subgraph S1["1. Stück-für-Stück-Claim-Prüfung & 3-Ursachen-Klassifikation"]
        CLAIM["Doku-Claims extrahieren (docs/help/*.txt, README, SKILL.md, GUI /help)\n& gegen Code/CLI/Tests prüfen"]:::probe
        CLS{"3-Ursachen-Klassifikator\n(classify_doc_reality_diff)"}:::probe
        U1["Ursache 1: Ungewollte Erosion\n(Code/Dienst ungewollt kaputt/abgedriftet)"]:::c1
        U2["Ursache 2: Geplantes Terraforming fehlt noch\n(Vorauseilende Doku = SOLL, Code noch offen)"]:::c2
        U3["Ursache 3: Erfolgtes Terraforming\n(Code gewollt fertig, Doku hinkt hinterher)"]:::c3
        CLAIM --> CLS
        CLS --> U1
        CLS --> U2
        CLS --> U3
    end

    subgraph S2["2. Transparente & Kombinierbare Entscheidungsverarbeitungsregeln (config.json)"]
        RULE{"Entscheidungs-Regelwerk\n(resolve_doc_machine_dispatch)\nJe nach Ursache, Trigger oder Override"}:::probe
        B1["Zweig A: local_taskplan (Standard)\nEinfache P1/P2-Reparatur-/Bau-Task im lokalen taskplan\nfür Hintergrund-Worker (Buddha / Cloud) einstellen"]:::c3
        B2["Zweig B: local_genie_marblerun\nLokale MarbleRun-Staffette starten\n(chains/wishes-come-true-local.json)"]:::c2
        B3["Zweig C: gitlab_wishes_come_true\nEntwickler-Feature (wishes_redirect in config.json)\nzu local-genie / wishes-come-true"]:::probe
        B4["Zweig D: user_notification\nNutzerbenachrichtigung (GUI-Inbox / Telegram)"]:::c1
        B5["Zweig E: local_doc_update\n.txt/.md-Doku, CLI/API-Referenz & i18n nachziehen"]:::c3

        U1 --> RULE
        U2 --> RULE
        U3 --> B5
        RULE -->|"Einzeln / Kombination"| B1
        RULE -->|"Einzeln / Kombination"| B2
        RULE -->|"Einzeln / Kombination (ocean-dev)"| B3
        RULE -->|"Einzeln / Kombination"| B4
    end
```

## Discovery-Kontext & Auffindbarkeit

BACH wird am treffendsten als **Local-First LLM-Betriebssystem** beschrieben: eine persistente Python/SQLite-Werkbank für autonome Agenten, strukturiertes Gedächtnis, Scheduler-gesteuerte Automationen, Prompt-Ketten, MCP-Server-Integration und mehrsprachige Operator-Oberflächen. Es ist weder ein einfacher Chatbot-Wrapper noch ein gehostetes SaaS-Tool, Bash-Testframework, Musikprojekt oder eine reine LangChain-Pipeline-Bibliothek.

Kanonisches GitHub-Repository: `ellmos-ai/bach`. Maschinenlesbarer Projektkontext für LLM-Crawler und RAG-Systeme ist in [`llms.txt`](llms.txt) hinterlegt.

> [!NOTE]
> **Für KI-Assistenten & LLM-Crawler:** Strukturierter, maschinenlesbarer Projektkontext, Architekturdetails und Begriffsklärungen stehen in [`llms.txt`](llms.txt) zur Verfügung.

Relevante Suchbegriffe umfassen `ellmos-ai/bach`, `local-first LLM operating system`, `text-based OS for LLM agents`, `SQLite memory for AI agents`, `BACH ellmos agent OS`, `personal agentic OS Python SQLite` und `multi-agent orchestration with MCP servers`.

## Systemarchitektur & Workflow-Topologie

### 1. Komponententopologie

```mermaid
graph TB
    subgraph Schnittstellen["Benutzer- & Agenten-Schnittstellen"]
        CLI["BACH CLI (bach.py / 113+ Handler)"]
        GUI["PySide6 Desktop-GUI & Web-Dashboard"]
        TG["Chat-Service & Telegram-Bot"]
        MCP["MCP-Server (FileCommander & CodeCommander)"]
    end

    subgraph CoreOS["BACH Kernbetriebssystem"]
        Orch["Agenten-Orchestrierung (11 Boss- & 22 Experten-Agenten)"]
        Sched["Scheduler & Automations-Engine"]
        Chains["llmauto Prompt-Ketten & Workflows"]
        Skills["Skill-Registry (1870+ Skills & 550+ Tools)"]
    end

    subgraph Persistenz["Lokale SQLite-Datenbank & Memory-Bus"]
        SQL["SQLite-Datenbank (210+ Tabellen)"]
        Mem["6-Stufen Strukturiertes Gedächtnis (Facts, Lessons, Working)"]
        Bus["SharedMemory-Bus & USMC-Bridge"]
    end

    CLI -->|"Befehlsverteilung"| Orch
    GUI -->|"HTTP & WebSockets"| Orch
    TG -->|"Bridge-Konnektor"| Orch
    MCP -->|"stdio / JSON-RPC"| Orch

    Orch -->|"Führt aus"| Chains
    Orch -->|"Triggert"| Sched
    Orch -->|"Lädt"| Skills

    Orch -->|"Liest / Schreibt"| Bus
    Bus -->|"Konsolidiert"| Mem
    Mem -->|"Atomare Speicherung"| SQL
```

### 2. Lokale Agenten-Ausführungssequenz (Zero Egress)

```mermaid
sequenceDiagram
    autonumber
    actor User as Operator / Agent
    participant CLI as BACH CLI / API-Schnittstelle
    participant Hub as Kern-Orchestrator & Session Scope
    participant Mem as SQLite-Gedächtnis & SharedMemory-Bus
    participant LLM as Wählbares Backend (Lokales Ollama / CLI)
    participant Tool as Tool- & Skill-Ausführungsengine

    User->>CLI: Aufgabe oder Workflow-Befehl erteilen
    CLI->>Hub: Anfrage mit Session-Token weiterleiten
    Hub->>Mem: Kontext, Lessons und Arbeitsgedächtnis abfragen
    Mem-->>Hub: Relevante Fakten und aktive Rahmenbedingungen liefern
    Hub->>LLM: Prompt mit lokalem Kontext formulieren (Zero Egress)
    LLM-->>Hub: Plan und gewünschte Tool-Aufrufe streamen
    Hub->>Tool: Geprüftes Tool / Handler lokal ausführen
    Tool-->>Hub: Tool-Ergebnis zurückgeben
    Hub->>Mem: Neue Fakten, Lesson-Feedback und Audit-Log festhalten
    Hub-->>CLI: Strukturierte Antwort formatieren (JSON / Text)
    CLI-->>User: Abgeschlossenes Ergebnis an Operator übergeben
```

<a id="openai-build-week--codex-and-gpt-56"></a>
## OpenAI Build Week — Codex und GPT-5.6

BACH verwendet Codex sowohl als vollwertiges Laufzeit-Backend als auch als Partner für die Repository-Entwicklung. Die genauen Automationszeitpläne, Modellrouten und nachvollziehbaren Session-IDs sind der unten stehenden verifizierten Build-Week-Zuordnung zu entnehmen.

BACH nutzt Codex in zwei unterschiedlichen Rollen:

- **Laufzeit-Backend:** `codex-cli` ist eines von fünf steckbaren Chat-Backends; BACH-Agenten können Coding-Aufgaben über `codex exec` delegieren.
- **Repository-Entwicklung:** Drei aktive Codex-Automationen warten das Projekt: `bach-daily-care-and-dev-check`, `bach-start-and-health-checks` und `bach-github-release-service`. Seit dem 21. Juli 2026 sind alle drei für GPT-5.6 (`gpt-5.6-terra`) konfiguriert; die ersten beiden laufen täglich, der Release-Service wöchentlich.
- **Verifiziertes Modellrouting:** In Codex-Session `019f85c6-4339-7f13-b8e5-bf1823fd8432` prüfte GPT-5.6 Sol mit hoher Reasoning-Stufe alle 78 Automationsdefinitionen und routete BACH-Entwicklungs- und Release-Aufgaben an Terra/high sowie Gesundheitsprüfungen an Terra/medium.
- **Abschlussprüfung der Einreichung:** GPT-5.6 Sol prüfte und zertifizierte in Codex-Session `019f8674-fe9a-7d91-a80f-7ee799e8ced0` die ausstehenden BACH-Änderungen, korrigierte die Zuordnung zum Wettbewerb und schloss die Härtung des Web-Scrapings sowie die Regressionstests ab.

Zur Nachvollziehbarkeit gilt die GPT-5.6-Zuordnung der Automationen ab dieser Konfigurationsänderung; frühere Automationsläufe verwendeten frühere Codex-Modelle.

## Kernfunktionen

- **113+ Handler** – Vollständige CLI- und API-Abdeckung der Systemfunktionen.
- **550+ Tools** – Umfangreiche Werkzeugbibliothek für Dateiverarbeitung, Analyse und Automation.
- **1870+ Skills** – Wiederverwendbare Workflows und Vorlagen.
- **Skill-Quellregister** – `bach skills version bach` löst den kanonischen Skill im Repository-Root über `system/data/skill_sources.json` auf und kann optionale Codex-/Claude-Benutzerkopien ohne unscharfe Dateinamenszuordnung vergleichen.
- **71 Workflow-Vorlagen** – Vorgefertigte Prozess-Workflows.
- **4400+ Tests** – Umfassende automatisierte Testabdeckung für Handler, Services, GUI und MCP-Server.
- **Wissensspeicher** – Lessons, Facts und mehrstufiges Gedächtnissystem mit sechs Gedächtnistypen (Facts, Lessons, Working Memory und weitere) über 210+ SQLite-Tabellen. Neue Einträge erhalten zusätzlich pro Eintrag die BACH-Session-Provenienz; bei älteren Einträgen bleibt die Urheberschaft ausdrücklich unbekannt.
- **Agenten-CLI** – `bach agent start/stop/list` zur direkten Agentensteuerung.
- **Agent Doctor** – `bach agent doctor [name] [--json]` prüft vor dem Start die Verfügbarkeit der Claude CLI, Laufzeitverzeichnisse, Skill-Dateien und veraltete PID-Zustände.
- **Agenten-Steuerung durch Operatoren** – `bach agent pause/resume/checkpoint/steer/clear-steer [name] [--json]` ermöglicht kooperative Pausenanforderungen und Hinweise vor oder während eines Laufs, dokumentiert ausdrückliche Bestätigungen sicherer Checkpoints, spiegelt diesen Zustand nach `OPERATOR_NOTES.md`, erhält vorgemerkte Hinweise für den nächsten `bach agent start`-Lauf, fügt sie in die erzeugte Session-`CLAUDE.md` ein und stellt verschachtelte `operator_control`-Snapshots samt `queued_for_next_start` für automationstaugliche Abfragen bereit.
- **Vorgaben für Agenten-Laufzeitrechte** – `bach agent start` akzeptiert `--permission-mode`, `--allowed-tools` und `--max-turns` und kann dieselben Standardwerte aus dem SKILL-Frontmatter eines Agenten für dessen Schutzregeln vorladen.
- **Scheduler Doctor** – `bach scheduler doctor [--json]` und `bach scheduler session doctor [--json]` prüfen Automationsskripte, PID-Zustand, Datenbank-, Konfigurations- und Profiloberflächen und schlagen Wiederherstellungsschritte vor, bevor Hintergrunddienste gestartet werden.
- **Steuerung von Sessions** – `bach scheduler session pause/resume/steer/clear-steer [--json]` kann die nächste profilbezogene Auto-Session freigeben oder neu ausrichten, ohne die Daemon-Konfiguration von Hand zu bearbeiten.
- **Steuerung von Scheduler-Läufen** – `bach scheduler pause/resume/steer/clear-steer [--json]` bietet dieselbe Operator-Steuerung für fällige Scheduler-Jobs, einschließlich globaler Pause und vorgemerkter Laufhinweise. Scheduler-Hinweise werden jetzt auch in den nächsten Promptpfad für einen sicheren Checkpoint von llmauto-Ketten übernommen.
- **Maschinenlesbare Steuerungs- und Statusoberflächen** – `bach agent list/start/stop/pause/resume/checkpoint/steer/clear-steer/status --json`, `bach scheduler status/jobs/session status --json` und `bach scheduler session pause/resume/steer/clear-steer --json` liefern unter anderem Queue-Zustand, `queued_for_next_start`, Zeitstempel, Checkpoint-Bestätigungen und Operator-Notizen für automationstaugliche Abfragen.
- **Diagnose der Worker-Queue** – [Auswahlbeobachtungen](docs/worker-queue.md) zeigen datierte Kandidatenzahlen sowie Ablehnungen nach Bindung, Kategorie, Priorität, Tag, Zuständigkeit und nativer Beanspruchung über bestehende Worker-APIs; Leerlaufabfragen gelten nicht als Modellblockaden. Die authentifizierte Konfigurationsantwort enthält zusätzlich eine schreibgeschützte Auswahlrichtlinie; vorhandene GUI-Karten erhalten eine lesbare Wartezusammenfassung. Diese Beobachtungen erteilen keine Berechtigung zur Annahme von Aufgaben oder Ergebnissen.
- **Drift und Reparatur von Upgrades** – `bach upgrade list <path> --json`, `bach upgrade status/check --json` und `bach upgrade repair [--dry-run] [--version <tag>]` liefern automationstaugliche Angaben zu Version, Status, Drift, Reparaturhinweisen und Wiederherstellung defekter Distributionsmetadaten.
- **Pfadoberfläche** – `bach path` stellt kanonische System-, Workspace- und Datenbankpfade, Validierung, Auflösungshelfer und Datenbanküberschreibungen als Text oder JSON bereit.
- **Prompt-System** – Zentrale Promptverwaltung mit Boards und Versionierung.
- **Installations-Sicherheitsprüfung** – Statische Prüfungen vor dem Laden blockieren offensichtliche Code-Injection-Muster bei `skills install` und `plugins load`. Das MCP-Setup validiert zulässige Pakete und Konfigurationen fail-closed; Plugin-Setup-Verträge verlangen jetzt explizite Shell-, Desktop- und MCP-Prüfungen, und blockierte lokale Imports werden isoliert.
- **Manifest-zuerst-Plugins** – `bach plugins inspect` zeigt Aktivierung, Anbieter/Modell, Setup und Fähigkeitsmetadaten an, ohne Plugin-Laufzeitcode zu importieren.
- **Strukturierter `bach_api`-Kern** – `task` und `memory` stellen ihre auffindbaren Methoden über `dir(...)` bereit, geben für übliche Lese- und Schreibvorgänge Python-Objekte zurück und behalten `raw(...)` für Aufrufe im Stil älterer Handler.
- **SharedMemory-Bus** – Koordination mehrerer Agenten mit Konflikterkennung und Zerfall.
- **USMC-Bridge** – United Shared Memory Communication für die Kommunikation zwischen Agenten.
- **llmauto-Ketten** – Claude-Prompts als Kettenschritte mit `bach://`-URL-Auflösung.
- **Chat-Service** – Multi-Backend-Telegram-Bot mit fünf Backends, Control API, Web-Dashboard, plattformübergreifendem System-Tray und Web-Chat.
- **MCP-Server** – Eigene Server für Claude Code, Cursor und standardisierte IDE-Integration.

## Installation

```bash
# Repository klonen
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Abhängigkeiten installieren und CLI registrieren
pip install -e .

# Pre-Flight-Prüfung
bach setup preflight

# Vollständiges Setup (MCP-Server, Hooks, Secrets, Profil)
bach setup full-install
```

### Optionale Operator-Konsole

```bash
pip install -e ".[console]"
BACH_GUI_CONSOLE_ENABLED=1 python system/gui/server.py
```

Die Einbindung ist standardmäßig deaktiviert und verwendet `/control`. Mit `BACH_GUI_CONSOLE_PREFIX` lässt sich ein anderer absoluter URL-Pfad festlegen. Fehlt das optionale Paket oder kann es nicht eingebunden werden, läuft das BACH-Dashboard ohne Konsole weiter. BACH führt keine separate Anmeldung ein; die Unified GUI behält ihr bestehendes fähigkeitsbasiertes Verhalten auf einem BACH-Host. Da das BACH-Dashboard derzeit keine `AUTH_ROLE`-Host-Session bereitstellt, sollte diese Einbindung an der Loopback-Standardadresse oder hinter einer vorhandenen vertrauenswürdigen Zugriffsschranke bleiben.

## Quick Start

```bash
# Schnelle, nebenwirkungsfreie Metadatenabfrage
python bach.py --version
python bach.py --help

# BACH starten
python bach.py --startup

# Aufgabe erstellen
python bach.py task add "Projektstruktur analysieren"

# Agenten verwalten
python bach.py agent list
python bach.py agent start bueroassistent

# Scheduler-Status prüfen
python bach.py scheduler status

# Prompts verwalten
python bach.py prompt list
python bach.py prompt add "My Prompt" --content "..."

# Versionierte Exporte alltäglicher Daten importieren (idempotent)
python bach.py abo import PATH/abotracker-export-v1.json
python bach.py versicherung import PATH/bach-fin-insurances-v1.json

# Wiederkehrende Importe erst registrieren, wenn eine gültige Exportdatei vorliegt
python bach.py abo schedule-import PATH/abotracker-export-v1.json --interval 24h
python bach.py versicherung schedule-import PATH/bach-fin-insurances-v1.json --interval 24h

# Aktuelle Monats-/Jahresübersicht der Finanzen zunächst als Vorschau aktualisieren
python bach.py haushalt financial-summary refresh --dry-run
python bach.py haushalt financial-summary refresh

# BACH beenden
python bach.py --shutdown
```

### Programmatischer Python-Schnelleinstieg

```python
from bach_api import get_api

# Initialisierung des nebenwirkungsfreien API-Clients
api = get_api()

# Aufgabe anlegen
task = api.task.add("Lokale Agentenumgebung prüfen")
print(f"Aufgabe erstellt: {task.id} - {task.title}")

# Systemstatus abfragen
status = api.system.status()
print(f"BACH Status: {status.state} (Aktive Handler: {status.handlers_count})")
```

`--version`, `--help`, die kontextspezifische Hilfe und globale `--dry-run`-Startpfade umgehen AutoLogger, ProSync und Aktivitätserfassung. Normale Befehle kündigen den ProSync-Pull vor dessen Beginn an und halten ein Startbudget von 15 Sekunden ein. Mit `BACH_PROSYNC_STARTUP_TIMEOUT_SECONDS` lässt sich für einen langsameren Transit ein ausdrückliches lokales Budget zwischen 1 und 300 Sekunden setzen. Schlägt der Pull fehl oder läuft er in den Timeout, arbeitet BACH ohne einen Exit-Push für diesen Prozess weiter.

Die Importbefehle erwarten exakt die Schemas `abotracker-export-v1` und `bach.fin_insurances.v1`. Abrechnungszyklen von AboTracker gelten nicht als bestätigte nächste Zahlungstermine. Geplante Jobs sind aktive, idempotente Dateiimporte und werden erst erstellt, nachdem die aktuelle Quelldatei die Validierung bestanden hat.

Die Finanzübersicht hält aus E-Mails beobachtete Ausgaben getrennt von der aktuellen wiederkehrenden Abonnementrate. Alte doppelte Abonnementeinträge werden bei Berechnungen und Dashboard-Abfragen anhand des Anbieters zusammengeführt; widersprüchliche Duplikate führen fail-closed zu einem Fehler, statt erraten oder gelöscht zu werden.

## MCP-Server (Claude Code & IDE-Integration)

BACH liefert einen integrierten Python-MCP-Server sowie zwei Begleit-Server mit:

```bash
# Integrierten BACH-Server starten (stdio)
bach mcp serve

# MCP-Server installieren und konfigurieren (empfohlen)
python system/bach.py setup mcp

# Begleit-Server via npm installieren:
npm install -g ellmos-codecommander-mcp ellmos-filecommander-mcp
```

- **BACH MCP Server** – BACH-Ressourcen, Tools und Prompts via Handler-API (`bach mcp serve`)
- **[ellmos-codecommander-mcp](https://www.npmjs.com/package/ellmos-codecommander-mcp)** v1.3.14 – Code-Analyse und Refactoring (21 Tools)
- **[ellmos-filecommander-mcp](https://www.npmjs.com/package/ellmos-filecommander-mcp)** v1.9.1 – Dateiverwaltung und Batch-Operationen (46 Tools)

## Kernkomponenten

Lokale Inferenz kann an der bestehenden Modellaufrufgrenze eine explizite Reserve-Richtlinie für den Host durchsetzen. Sie prüft die native Modellidentität, den konfigurierten Kontext- und Speicherbedarf sowie den freien Speicherplatz für Aufgaben-, Slot- und Laufzeitpersistenz. Eine Warteantwort gibt den Inferenz-Owner zurück und erhält die aktuelle Session, ohne Tools erneut auszuführen. Diese optionale Reserveschranke ersetzt weder den Modellslot-Controller noch bescheinigt sie die Modellkapazität. [Lokale Modellreserven](docs/architecture/LOCAL-MODEL-RESERVE.md) erläutert Konfiguration, Verifikation und die getrennten Installations- und Laufzeitfreigaben.

Der [Model-Socket-Vertrag](docs/architecture/MODEL-SOCKETS.md) bindet native Dialog- und Connector-Aufrufe an stabile Agentenidentitäten, überführt konfigurierte Connector-Ziele bei einer ausdrücklichen Migration und erhält vorhandenen Dialogkontext. Eine Quellprüfung belegt weder eine native Migration noch Modellkapazität.

### 1. Aufgabenverwaltung
Vollständiges GTD-System mit Priorisierung, Fristen, Tags und Kontextverfolgung.

### 2. Wissenssystem
Strukturiertes Gedächtnis mit Facts, Lessons und automatischer Konsolidierung (sechs Gedächtnistypen, mehr als 210 Datenbanktabellen).

### 3. Agenten-Framework — Ocean-Rollen, Dual-Routing & Flexible Anbieter-Sockel (`ellmos.role-socket-catalog.v1`)
In der gemeinsamen Ocean/BACH-Architektur bleiben die bewährten BACH-**Boss-Agenten (Koordinatoren)** und **Domänen-Experten** vollständig erhalten, arbeiten jedoch als **anbieterunabhängige Ocean-Rollen (`roles[]`)** auf einem **flexiblen Anbieter-Sockel (`model_sockets` über `clutch` + `agents-heart`)**:

- **Duales Routing (Semantisch + Deterministisch):**
  - **Semantisches Routing:** Umbrella-Skills (`projekt-pipeline-umbrella`, `therapie-umbrella`, `selbstmanagement` usw.) und `semantic-persona-routing` (`persona_router.py`) routen Anfragen kontextsensitiv und aktivieren das passende Skill-Set samt Rollen-Persona.
  - **Deterministisches Routing:** `ellmos-controlcenter-mcp` (`controlcenter_resolve_semantic_route`, `controlcenter_switch_profile`, `controlcenter_find_skill`) übernimmt das regelgebundene, halluzinationsfreie Routing und Umschalten von Werkzeugprofilen.
- **Flexibler Anbieter-Sockel (`reasoning_coordinator`, `domain_specialist`, `fast_worker`):** Keine Rolle ist mehr starr an einen einzelnen LLM-Anbieter gekoppelt. Jede Rolle sitzt auf einem standardisierten Sockel, der zur Laufzeit wahlweise mit **Claude (`claude`)**, **OpenAI/Codex (`codex`)**, **Gemini/Antigravity (`agy`)**, **Kimi (`kimi`)**, **lokalem Ollama (`ollama`)** oder **OpenRouter (`openrouter`)** bestückt wird.
- **3-Tab-Agenten-Bibliothek (`/agenten/bibliothek`, `ellmos.agent-library.v1`):** `discover_ocean_agent_library_templates()` speist sowohl die BACH-Koordinatoren (`ati`, `bueroassistent`, `finanz-assistent`, `gesundheitsassistent`, `persoenlicher-assistent`, `produktivitaet`) und 22+ Domänen-Experten als auch die **17 expliziten Modul-Rollen (`roles[]`)** aus 9 Ocean-Modul-Repositories (`task-master`, `ticket-master`, `MarbleRun`, `system-auditor`, `compare-race`, `ellmos-installer`, `foerderplaner`, `ai-media-editor`, `clip-storyboard-director`) direkt als Vorlagen in die Bibliothek ein.
- **Operator-Steuerung:** Über `bach agent start/stop/list/pause/resume/checkpoint/steer` lassen sich Agenten direkt steuern, vor dem Start mit Hinweisen (`OPERATOR_NOTES.md`) versorgen und an sicheren Checkpoints bestätigen.

<p align="center">
  <img src="sketch_bach_boss_agents.jpg" alt="BACH Boss Agents" width="600"><br>
  <i>Illustration zeigt die ursprünglichen BACH-Koordinatoren (ati, bueroassistent, finanz-assistent, gesundheitsassistent, persoenlicher-assistent), die im Ocean-System auf flexiblen Anbieter-Sockeln gemeinsam mit 17 Modul-Manifest-Rollen laufen.</i>
</p>

```mermaid
flowchart TD
    classDef routeLayer fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef roleLayer fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46
    classDef socketLayer fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e

    subgraph R1["1. Duales Routing (Semantisch vs. Deterministisch)"]
        SEM["Semantisches Routing
Umbrella-Skills (*-umbrella) + semantic-persona-routing"]:::routeLayer
        DET["Deterministisches Routing
ellmos-controlcenter-mcp (resolve_semantic_route / switch_profile)"]:::routeLayer
    end

    subgraph R2["2. Ocean-Rollen & 3-Tab-Agenten-Bibliothek (ellmos.agent-library.v1)"]
        COORD["6 Koordinatoren-Rollen (ehem. BACH-Bosse)
ati, bueroassistent, finanz-assistent, gesundheitsassistent, persoenlicher-assistent, produktivitaet"]:::roleLayer
        EXP["22+ Domänen-Experten & 17 Modul-Rollen (roles[])
tasksolver, ticket-master, ticket-writer, marble-controller, doc-keeper, race-starter, foerderplaner-expert, media-creator, storyboard-director"]:::roleLayer
        SEM --> COORD
        DET --> COORD
        COORD --> EXP
    end

    subgraph R3["3. Flexibler Anbieter-Sockel (model_sockets + clutch + agents-heart)"]
        SOCK["Standardisierte Modell-Sockel
reasoning_coordinator | domain_specialist | fast_worker"]:::socketLayer
        PROV["Austauschbare LLM-Anbieter
Claude | Codex/GPT | Gemini/AGY | Kimi | Lokales Ollama | OpenRouter"]:::socketLayer
        COORD --> SOCK
        EXP --> SOCK
        SOCK --> PROV
    end
```

### 4. Prompt-System
Zentrale Verwaltung von Prompt-Vorlagen mit Boardsammlungen und vollständiger Versionierung (`bach prompt`).

### 5. Chat-Service und Bridge-System
Multi-Backend-Telegram-Bot mit austauschbaren LLM-Backends (Ollama, Claude CLI, Codex CLI, Claude API, OpenAI API), HTTP-Control-API mit Web-Dashboard und plattformübergreifender Systemablage. Dazu kommen ein Connector-Framework für weitere Dienste (E-Mail, WhatsApp usw.) und die USMC-Bridge für die Kommunikation zwischen Agenten.

### 6. Automation
SchedulerService für zeitgesteuerte Jobs (Ketten, Aufgaben, Skripte) und ereignisgesteuerte Workflows über das Hook-Framework.

### 7. SharedMemory
Koordination mehrerer Agenten mit Kontextgenerierung, Konflikterkennung, Zerfall und Delta-Abfragen.

### 8. llmauto-Integration
Kettenschritte als LLM-Prompts mit dynamischer Kontextauflösung über `bach://`-URLs.

## Die ellmos-Familie

Alle ellmos-Projekte folgen einer Wassermetapher — von der Quelle bis zum vollen Strom:

| Stufe | Projekt | Beschreibung | Repository |
|-------|---------|--------------|------------|
| 1 | **USMC** | United Shared Memory Client – die Quelle (Shared Memory) | [github.com/ellmos-ai/usmc](https://github.com/ellmos-ai/usmc) |
| 2 | **Rinnsal** | Das Rinnsal – USMC + llmauto (LLM-Orchestrierung), ultrakompakt | [github.com/ellmos-ai/rinnsal](https://github.com/ellmos-ai/rinnsal) |
| 3 | **BACH** | Der Strom, der alles vereint – 113+ Handler, 1870+ Skills, Agenten, GUI, Bridge | [github.com/ellmos-ai/bach](https://github.com/ellmos-ai/bach) |

## Dokumentation

Die native Dokumentationspflege, Aktivierung und Nachweisgrenzen sind in [DOCS-MAINTENANCE.md](docs/architecture/DOCS-MAINTENANCE.md) beschrieben.

- **[Modellsteckplätze und Agentenslots](docs/architecture/MODEL-SOCKETS.md)** – Quellvertrag, Bindungsprüfung und offene Aktivierungsabnahme
- **[Gemeinsame GUI und Agenten](system/docs/help/gui-integration.txt)** – Bedienung und tatsächliche Adapterprüfung
- **[Lernquellen und Prüfkandidaten](docs/architecture/LEARNING-SOURCE-CONTRACT.md)** – Begrenzte Vorschau und inaktive Entwürfe; [Befehlshilfe](system/docs/help/learning.txt). Veröffentlichung und unabhängige Wiederverwendung benötigen eine gesonderte Abnahme.
- **[Ocean–BACH-Transferplan](OCEAN-TRANSFER-PLAN.md)** – Installer, erster Modultransfer und weitere Aufgaben
- **[Deprecation-Register](DEPRICATED.md)** – Ersatz, offene Abnahmen und Rollback
- **[Erste Schritte](QUICKSTART.de.md)** – Erste Schritte mit BACH
- **[Befehlsreferenz](BACH_HELP_REFERENCE.template.de.md)** – Vollständige API-Dokumentation
- **[Skills-Katalog](SKILLS.template.de.md)** – Alle verfügbaren Skills
- **[Agenten-Katalog](AGENTS.template.de.md)** – Alle verfügbaren Agenten
- **[Benutzerhandbuch](BACH_USER_MANUAL.md)** – Umfassendes Handbuch

- **[Workflows](WORKFLOWS.template.md)** – In diesem Repository sind 42 Workflow-Vorlagen enthalten.
- **[SKILL-Vorlage](SKILL.template.md)** – LLM-Betriebsanweisungen als Vorlage für Claude, Gemini, Ollama und Codex-artige Agenten.

## Siehe auch: OpenClaw

Wie unterscheidet sich BACH von [OpenClaw](https://github.com/openclaw/openclaw), einem beliebten quelloffenen KI-Assistenten?

| | **BACH** | **OpenClaw** |
|---|---|---|
| **Schwerpunkt** | LLM-Betriebssystem – tiefe Autonomie, strukturiertes Gedächtnis und Multi-Agenten-Orchestrierung | Persönlicher KI-Assistent – breites Messaging-Gateway, Sprache und Begleit-Apps |
| **Tools/Skills** | Mehr als 550 Tools, 1870+ Skills, 42 Workflows (lokal und kuratiert) | Community-getriebenes Skill-/Plugin-Ökosystem; neuere Releases betonen Plugin-Metadaten nach Manifest und sichere Installation |
| **Gedächtnis** | Sechs Gedächtnistypen mit Zerfall, Konflikterkennung und Konsolidierung (mehr als 210 Datenbanktabellen) | Session-/Laufzeit-Workspace mit Bootstrap-Dateien wie `AGENTS.md`, `TOOLS.md`, `USER.md` und verwandten Kontextdateien |
| **Agenten** | Boss-/Experten-Orchestrierung (11 Boss-Agenten und 22 Experten), SharedMemory-Bus | Agentenlaufzeit mit Betrieb über mehrere Sessions und Kanäle |
| **Messaging** | Telegram, E-Mail, WhatsApp (Bridge-System) | Mehr als 20 Plattformen (WhatsApp, Telegram, Slack, Discord, Signal, Teams, Matrix …) |
| **Oberflächen** | CLI, Python-API, PySide6-GUI, Web-GUI, Telegram-Bot, Web-Chat und Systemablage | CLI, WebChat, macOS-/iOS-/Android-Apps und Sprache |
| **MCP** | Eigene MCP-Server (FileCommander, CodeCommander) | Native MCP-Registry |
| **Technologie-Stack** | Python 3.10+, SQLite | TypeScript, Node.js 22+ |
| **Lizenz** | MIT | MIT |

**Kurz gesagt:** BACH geht in die Tiefe (strukturiertes Gedächtnis, autonome Agenten, Scheduler und mehr als 210 Datenbanktabellen). OpenClaw geht in die Breite (mehr als 20 Messenger, native Apps, Sprache und große Community). Die Ansätze unterscheiden sich und können sich ergänzen.

### Competitive Watch

Zum 8. Oktober 2026 steht OpenClaw bei `v2026.9.8` (veröffentlicht am 8. Oktober 2026 nach `v2026.9.7`). Neuere Entwicklungen betonen stabilere Antworten mehrerer Agenten, die Integrität der Session-Zuweisung zwischen Agenten, geringeren Speicherbedarf über mehrere Codex-/Worker-Prozesse, robusteren Windows-Start und Wiederholungen von Updates sowie Stummschaltungseinstellungen in 20 Sprachen. Für BACH bleiben atomare Wiederherstellungs- und Updategrenzen (`bach update apply` / `rollback` / `upgrade repair`, `distribution_releases` v3.14.0), überwachte Neustartübergaben und Session-Fortsetzungskontext (OPS-RUN-001 / Task #1118), sichere Ausführung ohne Shell (`safe_exec.py` / PR #137) und lokale Telemetriezähler mit wenigen Kategorien (`system/core/telemetry.py` / Task #1315) relevante Architekturimpulse; eine breite Parität bei mobilen Apps und Messaging-Gateways bleibt außerhalb des BACH-Kernentwurfs.

Auf BACH-Seite bestätigte der Care-and-Dev-Check vom 8. Oktober den Repository-Zustand auf `main` (Fast-Forward von `origin/main` mit PRs #190–#253: native Abläufe und Marblerun-Worker-Fencing, Shared GUI v0.1.4, Astro-Allowlist für statische Assets, Agenten-Werkstatt und Blueprints, Lebensroutinen und Kalender, Domain-Katalog-Manifeste, Salt-Lease-Vertrag v1 für die Lead-Task-Datenbank und CodeQL-Sicherheitsbehebung). Das Session-Lifecycle-Management initialisierte für Partner Gemini eine frische Session (`session_20261008_162204`) mit vollständigen Fortsetzungssnapshots. Die Testprüfsuite (`test_setup_handler.py`, `test_maintain_handler.py`, `test_db_guard_hook.py`, `test_explorer_provider_wiring.py`) bestand vollständig (138/138 in 46,29 s). Agent-Doctor-Diagnosen (`ati`, `entwickler`: 7/7 Prüfungen bestanden, `ready: true`, `can_start: true`), Start-Trockenläufe, Scheduler Doctor (7/7 Prüfungen bestanden, 4/5 Jobs aktiv), 50/50 Usecase-Trockenläufe (100 % mit Workflows verknüpft), Aktualität der Dokumentation (2.101 Dokumente in `Doc_Update_Report_2026-10-08_16-25.md`, 30-Tage-Bericht `2026-10_docs_report.md`), Registry-Zustand (0 umsetzbare Probleme), Task-Datenbank-Prüfung (29 konsistente Aufgaben), Skill-Prüfung (30/30 Skills, 10/10 Agenten) und Prüfung des Arbeitsgedächtnisses (189 Einträge, 0 abgelaufen) wurden vollständig bestätigt. Ein frisches Backup `userdata_2026-10-08_162846.zip` wurde erstellt.

## Lizenz & Haftungsausschluss (§ 521 BGB)

MIT-Lizenz – siehe [LICENSE](LICENSE) für Details.

Dieses Projekt ist eine **unentgeltliche Open-Source-Schenkung** im Sinne der §§ 516 ff. BGB. Die Haftung des Urhebers ist gemäß **§ 521 BGB** auf **Vorsatz und grobe Fahrlässigkeit** beschränkt. Ergänzend gelten die Haftungsausschlüsse aus GPL-3.0 / MIT / Apache-2.0 §§ 15–16 (je nach gewählter Lizenz).

Nutzung auf eigenes Risiko. Keine Wartungszusage, keine Verfügbarkeitsgarantie, keine Gewähr für Fehlerfreiheit oder Eignung für einen bestimmten Zweck.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

English version: [README.md](README.md)

*ellmos BACH v3.15.0 - Textbasiertes Betriebssystem für LLMs*

## Portable Agentenstarter

`start/agents/windows/` enthält START, SYSTEM-AUDITOR, TICKET-MASTER, PINGPONG und MULTI-BOT als `.bat`-Dateien; `start/agents/posix/` enthält die Shell-Dateien. Das Wheel liefert sie unter `share/ellmos-bach/starters/` mit. Sie verwenden das vorhandene TASKPLAN-Startcenter und die Rollenverträge der Module. Zuerst die geprüfte TASKPLAN-Version mit Startcenter und die optionalen Rollenmodule installieren. Die Dateien setzen keine persönlichen Pfade, Konten, Modelle oder erweiterten Berechtigungen. Die Installation registriert oder startet keine Hintergrundjobs. START öffnet die Rollenauswahl. PingPong benötigt einen ausdrücklichen Sync-Root und eigenen Slot und unterstützt seine geprüften Codex-/Claude-Adapter. MULTI-BOT verwendet das öffentliche githubbot-core-Paket. Für Vorschauen `--dry-run --provider codex` übergeben; fehlende Module liefern einen Installationshinweis.
