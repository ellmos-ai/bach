# BACH vs. Claude Code

**Stand:** 2026-05-27
**Zweck:** Entscheidungsvorlage für Task `#1084`
**Frage:** Welche Agenten-, Skill- und Orchestrierungsfunktionen sollen in BACH selbst leben, wo ist Redundanz sinnvoll und wo sollte Claude Code nur als Oberfläche auf BACH zugreifen?

---

## Kurzfazit

BACH und Claude Code sollten **nicht** als zwei vollständige Konkurrenz-Systeme gepflegt werden.

- **BACH** sollte das dauerhafte System für Zustände, Aufgaben, Scheduler, Multi-Partner-Orchestrierung, lokale Services und domänenspezifische Workflows bleiben.
- **Claude Code** sollte die interaktive Coding-Oberfläche für Repo-Arbeit, Ad-hoc-Analyse, Subagenten, Hooks, MCP-Nutzung und schnelle Entwicklungsloops bleiben.
- **Doppelte Implementierung** ist nur dort sinnvoll, wo dieselbe Fähigkeit in beiden Welten einen klar anderen Zweck erfüllt.

---

## Leitentscheidung

Die sinnvolle Trennlinie ist:

1. **Claude Code steuert die aktuelle Arbeitssitzung.**
2. **BACH hält den langlebigen Betriebszustand.**
3. **BACH-Logik wird bevorzugt als CLI/API/Service bereitgestellt und von Claude Code genutzt, statt in Claude-spezifischen Prompt-Dateien nachgebaut zu werden.**

---

## Vergleichsmatrix

| Bereich | BACH | Claude Code | Entscheidung |
|---|---|---|---|
| Projektinstruktionen | `SKILL.md`, `AGENTS.md`, Workflow-Dokus, Systemkonventionen | `CLAUDE.md`, importierte Projekt- und User-Memory | **Beides ja**, aber mit klarer Rolle: Claude-spezifische Bedienhinweise in `CLAUDE.md`, systemische Fach- und Ablauflogik in BACH-Dokus |
| Persistente Tasks | Datenbank, Prioritäten, Zustände, Zuweisung, Historie | Keine gleichwertige persistente Task-Datenbank im Projekt | **Nur BACH** |
| Persistente Memory/Provenance | Working/Facts/Lessons/Sessions/Wiki | Projekt-/User-Memory über `CLAUDE.md` | **Beides ja**, aber verschieden: Claude für Instruktionen, BACH für operative und fachliche Zustände |
| Subagenten/Agenten | Langlebige Boss-/Experten-Architektur, Multi-Partner-Denken | Workspace-Subagents mit eigenem Kontextfenster und Tool-Scope | **Beides ja**: Claude-Subagents für kurzfristige Repo-Delegation, BACH-Agenten für dauerhafte Rollen und Systemarbeit |
| Hooks / Start- und Endereignisse | Eigenes Hook-System im BACH-Kern | Session-, Tool- und Subagent-Hooks in Claude Code | **Beides ja**, aber nicht doppelt für denselben Triggerpfad |
| Slash Commands / Kommandomenüs | Eigene CLI-Befehle und Help-System | Slash Commands, MCP-Prompts, `/agents`, `/mcp`, `/memory` | **Claude führt, BACH liefert Inhalte** |
| MCP | Eigene MCP-Server und Tool-Registrierung | MCP-Client mit Tool- und Prompt-Nutzung | **Beides ja**: BACH stellt MCP-Flächen bereit, Claude konsumiert sie |
| Scheduler / Recurring / Run-Historie | Eigenes System mit Jobs, Checks, Status und History | Kein gleichwertiger langlebiger Scheduler-Kern | **Nur BACH** |
| GUI / Dashboard / lokale Services | FastAPI-GUI, Control API, Chat-/Daemon-Dienste | Terminal-/Editor-Tool, keine BACH-äquivalente lokale Betriebsoberfläche | **Nur BACH** |
| Rechte- und Tool-Freigaben | Eigene Policies und Sicherheitslogik im System | Permission-Modi, Allow/Deny, Hook-Gates | **Claude lokal, BACH systemisch** |
| GitHub-/CI-Automation | Kann orchestrieren, aber ist nicht primär GitHub-zentriert | Offizielle GitHub-Action und SDK-Anbindung | **Claude-nativ bevorzugen**, BACH nur ergänzend |

---

## Wo Redundanz sinnvoll ist

### 1. Agenten / Subagenten

Redundanz ist sinnvoll, **wenn die Laufzeitform verschieden ist**:

- **Claude-Subagents** für kurzfristige, repo-nahe Delegation innerhalb einer Sitzung.
- **BACH-Agenten** für dauerhafte Rollen mit eigener Identität, Tasks, Dateien, Services oder systemübergreifender Verantwortung.

Faustregel:

- Wenn der Helfer nur innerhalb einer Coding-Session gebraucht wird, reicht Claude Code.
- Wenn der Helfer eine wiederverwendbare Systemrolle mit Gedächtnis und Betriebslogik ist, gehört er in BACH.

### 2. Memory

Redundanz ist sinnvoll, **wenn unterschiedliche Gedächtnistypen gemeint sind**:

- `CLAUDE.md` speichert Verhaltens- und Projektinstruktionen.
- BACH speichert operative Fakten, Lessons, Sitzungen, Aufgabenbezüge und Provenance.

### 3. Hooks / Automations-Trigger

Redundanz ist sinnvoll, **wenn unterschiedliche Ebenen gemeint sind**:

- Claude-Hooks für Sitzung, Tool-Aufrufe und lokale Guardrails.
- BACH-Hooks für systemweite Prozesse, Datenbankereignisse und längerlebige Automation.

---

## Was nicht doppelt gepflegt werden sollte

### 1. Scheduler-Logik

Claude Code sollte **keinen parallelen BACH-Scheduler nachbauen**.
Zeitgesteuerte Läufe, Run-Historie, Due-Jobs und Recovery gehören in BACH.

### 2. Task- und Zustandsdatenbank

Offene Aufgaben, Status, Zuweisungen und Langzeitverfolgung gehören in BACH.
Claude Code darf darauf arbeiten, sollte aber nicht einen zweiten Wahrheitsort erhalten.

### 3. Fach-Workflows als Claude-only Prompt-Sammlung

Wenn ein Workflow bereits in BACH als Handler, Skill, CLI oder API existiert, sollte er **nicht zusätzlich als unabhängige Claude-Promptlogik** gepflegt werden.
Claude-spezifische Kurzbefehle dürfen nur dünne Frontends sein.

### 4. Multi-Partner-Orchestrierung

Claude Code ist stark in der Sitzung.
BACH ist das passendere Zuhause für Partner-Zonen, Delegationsregeln, Routing, Shared Memory und systemübergreifende Koordination.

---

## Empfohlene Zielarchitektur

### Claude Code ist bevorzugt für

- Repo-Analyse und Code-Änderungen
- schnelle Ad-hoc-Diagnosen
- lokale Subagenten-Delegation
- Hook-basierte Session-Hygiene
- MCP-Konsum im Entwickler-Workflow
- GitHub- und Review-nahe Automationen

### BACH ist bevorzugt für

- langlebige Tasks und Memory
- Scheduler, Recurring, Jobs und Run-Steuerung
- Multi-Partner- und Multi-System-Orchestrierung
- domänenspezifische Agents/Experts
- lokale Services, Dashboard, Control API
- betriebliche Self-Heal- und Status-Oberflächen

### BACH als Bibliothek unter Claude Code

Der bevorzugte Integrationsmodus ist:

- Claude Code liest Projektkontext aus `CLAUDE.md`
- `CLAUDE.md` verweist auf BACH-Dokumente und Kommandos
- Claude Code führt bei Bedarf `bach ...` oder `bach_api ...` aus
- die Geschäftslogik bleibt in BACH

Das vermeidet Prompt-Drift und hält BACH als System testbar.

---

## Konkrete Ableitungen für BACH

1. **Keine parallelen Claude-only Kopien** von BACH-Workflows bauen, wenn bereits Handler/API existieren.
2. **Claude-spezifische Adapter** bewusst dünn halten: `CLAUDE.md`, Slash-Command-Hilfen, Hook-Aufrufe, MCP-Frontends.
3. **BACH-Agenten nicht nach „kann Claude das auch?“ löschen**, sondern nur, wenn sie keine dauerhafte Systemrolle haben.
4. **Neue Funktionen zuerst als BACH-Handler/API denken**, wenn sie auch außerhalb einer einzelnen Coding-Session nützlich sind.
5. **Claude-first statt BACH-first** nur bei rein interaktiven Coding-Funktionen wählen.

---

## Anti-Patterns

- Einen BACH-Workflow als zweite, leicht abweichende Prompt-Version in `CLAUDE.md` nachbauen
- dieselbe Zustandslogik einmal in Markdown und einmal in BACH-Tabellen pflegen
- Claude-Subagents mit BACH-Boss-Agenten verwechseln
- BACH-Scheduler-Aufgaben in ad-hoc Claude-Sitzungen „simulieren“
- systemische Features in rein Anthropic-spezifische Oberflächen einsperren

---

## Entscheidung für Task #1084

Task `#1084` ist inhaltlich beantwortet mit dieser Leitlinie:

- **Doppelt sinnvoll:** Instruktionsoberfläche, Subagenten, Hooks, MCP-Anbindung
- **Nur BACH:** persistente Tasks, persistente operative Memory, Scheduler, Multi-Partner-Orchestrierung, lokale Services
- **Nur Claude Code:** interaktive Sitzung, Slash-Command-Bedienung, lokale Tool-Permissions, repo-nahe Subagentenarbeit
- **BACH als Bibliothek:** überall dort, wo Claude Code vorhandene BACH-Fähigkeiten nur auslösen oder lesen soll

---

## Quellen

### BACH-intern

- [`SKILL.md`](../../SKILL.md)
- [`WORKFLOWS.md`](../../WORKFLOWS.md)
- [`PARTNERS.md`](../../PARTNERS.md)
- [`system/ARCHITECTURE.md`](../../system/ARCHITECTURE.md)

### Offizielle Claude-Code-Dokumentation, abgerufen am 2026-05-27

- [Claude Code Overview](https://docs.anthropic.com/en/docs/claude-code/overview)
- [Manage Claude's Memory](https://docs.anthropic.com/en/docs/claude-code/memory)
- [Slash Commands](https://docs.anthropic.com/en/docs/claude-code/slash-commands)
- [Hooks Reference](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Subagents](https://docs.anthropic.com/en/docs/claude-code/sub-agents)
- [Settings](https://docs.anthropic.com/en/docs/claude-code/settings)
- [CLI Reference](https://docs.anthropic.com/en/docs/claude-code/cli-usage)
- [Claude Code SDK Overview](https://docs.anthropic.com/en/docs/claude-code/sdk)
