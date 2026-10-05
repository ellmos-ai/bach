# Boss-Agent Laufzeit-Evaluierung

**Auftrag:** Boss-Agent-Evaluierung (#1398, P3)  
**Status:** Abgeschlossen / Dokumentiert  
**Ziel:** Klärung, ob BACH derzeit einen funktionierenden Boss-Agent/Orchestrierungs-Laufzeitmechanismus besitzt.

---

## Zusammenfassung

**Befund: Es existiert aktuell keine generische Boss-Agent-Laufzeit.**

- Die Datenbank `bach-ASUS-GEI.db` enthält zwar Agent-/Expert-Datensätze und wurde vollständig ausgelesen.
- Persona-Markdown-Dateien wurden aus der DB generiert (`system/agents/personas/*.md`).
- Alle geprüften Python-Module im `tools/agents/`-, `tools/skills/`-, `tools/llmauto/`- und `system/agents/`-Bereich sind entweder rein administrativ, statisch, oder Datei-/JSON-basiert.
- Die einzige tatsächliche Laufzeit-Automatisierung ist `tools/llmauto/` mit Claude-Subprozess-Ketten (`claude -p`), jedoch ohne DB-basierte Agent-Orchestrierung oder Boss-Agent-Delegation.
- Spezifische "Hauptorchestrator"-Logik existiert nur im ATI-Projekt-Bootstrap-Kontext (`system/agents/ati/tools/project_bootstrapper.py`), nicht als generischer Laufzeit-Agent.

---

## 1. Datenbank-Zustand

**Quelle:** `/Users/lukas/services/bach/system/data/bach-ASUS-GEI.db`

### 1.1 `bach_agents` (10 Zeilen, IDs 1–10)

| Feld | Befund |
|------|--------|
| Sprache | de/en Duplikate |
| Typen | `boss`, `assistant`, `Expert` |
| Beispiele | ATLAS=ati, u.a. |
| Verwendung | Statische Definitionen; keine Laufzeit-Instanziierung gefunden |

### 1.2 `bach_experts` (22 Zeilen, IDs 1–22)

| Feld | Befund |
|------|--------|
| Zuordnung | Experts mit `agent_id` |
| Duplikate | en/de ab ID 16 |
| Beispiele | ANTON=aboservice |
| Verwendung | Statische Definitionen; keine Laufzeit-Orchestrierung |

### 1.3 Root-Datenbank `bach.db`

| Feld | Befund |
|------|--------|
| Status | Leer |
| Agent-Tabellen | Nicht vorhanden |
| Relevanz | Wird von `agent_cli.py` und `agent_service_integration.py` verwendet, aber nicht von `bach-ASUS-GEI.db` |

---

## 2. Geprüfte Dateien und Befunde

### 2.1 Agenten-Framework und Verwaltung

| Datei | Befund |
|-------|--------|
| `agents_export.py` | Reiner DB-Exporter, keine Laufzeitklasse |
| `agent_framework.py` | JSON/Registry-basiert, statisch. Nutzt `registry.json` (existiert nicht), `services.json`, `external_ki_tools_registry.json`, `cli_tools_registry.json`. Keine Laufzeit-Orchestrierung, keine Boss-Agent-Delegation. |
| `agent_service_integration.py` | DB-basiert, liest aber `bach.db` (Root, leer), nicht `bach-ASUS-GEI.db`. Statische Verbindungsmatrix, keyword-basierte Empfehlung. Keine Laufzeit-Orchestrierung. |
| `agent_cli.py` | Verwaltungs-CLI für `bach.db`, initiiert Schema/User-Ordner. Keine Laufzeitklasse. |
| `portable_base.py` | Abstrakte Basisklasse `PortableAgent` mit `BACHAdapter`. Keine konkrete Boss-Agent/Orchestrierungslogik. |

### 2.2 Skills und Personas

| Datei/Verzeichnis | Befund |
|-------------------|--------|
| `tools/skills/*.py` (`skill_init.py`, `skill_package.py`, `skill_validate.py`) | Reine Skill-Verwaltungs-Utilities. Keine `run`/`orchestrate`/`delegate`/`boss`/`AgentRuntime`-Logik. |
| `tools/agents/personas` | Existiert **nicht**. |
| `system/agents/personas/*.md` | 20 Markdown-Dateien, generiert aus `bach-ASUS-GEI.db`. Duplikate en/de. YAML-Frontmatter mit `name`/`display_name`/`short_name`/`role`/`db_table`/`system_name`. |

### 2.3 LLM-Auto / Ketten-Laufzeit

| Datei | Befund |
|-------|--------|
| `tools/llmauto/*.py` + `core/` + `modes/` | Claude-Subprozess-basierte Ketten. |
| `tools/llmauto/core/runner.py` | `ClaudeRunner.run`, `ClaudeRunner.run_parallel` |
| `tools/llmauto/chain.py` | `run_chain`, `run_parallel_workers` |
| Chain-Configs | `system/tools/llmauto/chains/*.json` (16 Dateien) |
| Prompt-Resolution | Unterstützt `bach://prompt_templates` aus `bach.db`, Standard läuft aber auf file-basierten Prompts |
| Einschränkung | Keine DB-basierte Agent-Orchestrierung, keine Boss-Agent-Delegation |

### 2.4 ATI-Bereich

| Datei | Befund |
|-------|--------|
| `system/agents/ati/tools/project_bootstrapper.py` | Statischer Projekt-Onboarding-Orchestrator. Bezeichnet als "Hauptorchestrator" nur im ATI-Bootstrap-Kontext. Kein generischer Boss-Agent, keine DB-basierte Agent-Delegation. |

---

## 3. Code-Grep-Befunde

| Suchmuster | Ergebnis |
|------------|----------|
| `class.*Agent` in `tools/agents/*.py` | `AgentFramework`, `AgentServiceIntegration`, `PortableAgent` + 4 `PortableAgent`-Subklassen |
| `Boss-Agent` projektweit | Nur Dokumentation/Exporter, keine Laufzeit-Implementierung |
| `run` / `orchestrate` / `delegate` / `boss` / `AgentRuntime` in `tools/skills/` | Keine Treffer |
| Boss-Agent/Orchestrierungs-Keywords in `tools/llmauto/` | Keine Treffer |

---

## 4. Sackgassen

| Annahme | Realität |
|---------|----------|
| Root `bach.db` enthält Agent-Tabellen | Leer, keine Agent-Tabellen |
| Suche nach "Boss-Agent" findet Implementierung | Nur Dokumentation/Exporter |
| `/Users/lukas/services/bach/agents/` existiert | Existiert nicht |
| `tools/agents/personas` ist der Persona-Speicherort | Existiert nicht; Personas liegen in `system/agents/personas/` |
| `AgentFramework` nutzt `registry.json` | Datei existiert nicht |
| `tools/skills/` und `tools/llmauto/` enthalten DB-basierte Agent-Runtime | Nein, Datei-/JSON-basiert |
| `system/agents/ati/` ist ein generischer Boss-Agent | Nein, ATI-Projekt-Bootstrapper |

---

## 5. Fazit: Laufzeit-Fähigkeiten

| Fähigkeit | Verfügbarkeit | Bemerkung |
|-----------|---------------|-----------|
| Agent-Definitionen in DB | ✅ Ja | `bach-ASUS-GEI.db` |
| Statische Personas | ✅ Ja | `system/agents/personas/*.md` |
| Skill-Verwaltung | ✅ Ja | `tools/skills/*.py` |
| LLM-Ketten-Laufzeit | ✅ Ja | `tools/llmauto/` mit Claude-Subprozessen |
| Generische Boss-Agent-Laufzeit | ❌ Nein | Kein Runtime-Agent, der Tasks an andere Agenten delegiert |
| DB-basierte Agent-Orchestrierung | ❌ Nein | Keine Laufzeitnutzung von `bach_agents`/`bach_experts` zur Aufgabenverteilung |
| Dynamische Agent-Instanziierung | ❌ Nein | Agenten sind statisch definiert/extrahiert |
| Agent-zu-Agent-Kommunikation | ❌ Nein | Nicht implementiert |

---

## 6. Empfehlungen

1. **Klarstellen, dass kein Boss-Agent existiert.**  
   Dokumentation und README sollten diesen Punkt eindeutig kommunizieren, um falsche Erwartungen zu vermeiden.

2. **Entscheiden, ob eine Boss-Agent-Laufzeit gebraucht wird.**  
   Falls ja: Konzeption eines generischen `AgentRuntime`/`BossAgent`, der aus `bach-ASUS-GEI.db` Agenten/Experten lädt, Aufgaben parsed und an Experten delegiert.

3. **Vereinheitlichung der Datenbanken.**  
   `agent_cli.py` und `agent_service_integration.py` lesen `bach.db`, während die eigentlichen Agent-Daten in `bach-ASUS-GEI.db` liegen. Ein konsistenter Datenbankpfad oder eine Migrationsstrategie ist sinnvoll.

4. **`registry.json` anlegen oder Fallback-Verhalten implementieren.**  
   `agent_framework.py` verweist auf `registry.json`, das nicht existiert. Entweder Datei bereitstellen oder Code robust gegen fehlende Dateien machen.

5. **Einsatzmöglichkeit von `tools/llmauto/` prüfen.**  
   Die einzige vorhandene Laufzeit ist die Claude-Subprozess-Kette. Sie kann ggf. als Grundlage für einen einfachen Orchestrator dienen, wenn eine Boss-Agent-Laufzeit später benötigt wird.

6. **ATI-ProjectBootstrapper nicht als generischen Boss-Agent missverstehen.**  
   Sollte bei Bedarf ausgebaut oder explizit als ATI-spezifisch dokumentiert werden.

---

## 7. Datei- und Verzeichnisnachweise

- Datenbank: `/Users/lukas/services/bach/system/data/bach-ASUS-GEI.db`
- Personas: `/Users/lukas/services/bach/system/agents/personas/*.md` (20 Dateien)
- Agenten-Code: `/Users/lukas/services/bach/tools/agents/`
- Skills: `/Users/lukas/services/bach/tools/skills/`
- LLM-Auto: `/Users/lukas/services/bach/tools/llmauto/`
- Chain-Configs: `/Users/lukas/services/bach/system/tools/llmauto/chains/*.json`
- ATI-Bootstrapper: `/Users/lukas/services/bach/system/agents/ati/tools/project_bootstrapper.py`

---

*Dokument erstellt im Rahmen von Task #1398.*
