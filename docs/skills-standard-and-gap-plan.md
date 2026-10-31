# Kanonischer Skills-Standard & Gap-Plan (BACH / Ocean / ControlCenter)

> **Status:** Verbindlicher Standard & Ausbauplan (Tasks `#2450`, `#3673`, `#3674`)  
> **Stand:** 2026-10-31  
> **Geltungsbereich:** Zentrale Skill-Bibliothek (`OneDrive/.TOPICS/.AI/.SKILLS/skills/`), Host-Skill-Depots (`~/.agents/skills/`, `~/.claude/skills/`, `~/.gemini/skills/`), BACH (`system/hub/_services/skill_source_service.py`) und `ellmos-controlcenter-mcp`.

---

## 1. Kanonischer Skill-Standard

Jeder Skill im Ökosystem (BACH, Ocean, Claude Code, Codex, Antigravity/Gemini, Kimi) folgt einem einheitlichen, provider-neutralen Aufbau.

### 1.1 Verzeichnisstruktur

```text
<skill-name>/
├── SKILL.md          # Pflicht: YAML-Frontmatter + strukturierte Ausführungsanleitung
├── scripts/          # Optional: Ausführbare Hilfsskripte (Python/Shell, CLI-fähig)
├── references/       # Optional: Vertiefende Spezifikationen, Schemata und Richtlinien
├── resources/        # Optional: Vorlagen, statische Assets, Konfigurationsmuster
└── examples/         # Optional: Referenzbeispiele und Testfälle
```

### 1.2 Verbindliches YAML-Frontmatter (`SKILL.md`)

Die Datei `SKILL.md` ist die alleinige Quelle der Wahrheit für Katalogisierung, Routing und Synchronisation (`sync_skills.sh` liest `category` direkt via `frontmatter_category()`):

```yaml
---
name: <kebab-case-name>
description: <Präzise Auslöse- und Funktionsbeschreibung (wann nutzen, wann nicht nutzen)>
category: dev | infrastructure | utilities | therapy | research | education | web
version: 1.0.0
standalone: true
bach_compatible: true
---
```

**Pflichtregeln für das Frontmatter:**
1. **`name`** muss exakt dem Ordnernamen (`<skill-name>`) entsprechen.
2. **`category`** im Frontmatter bestimmt den Zielordner unter `.SKILLS/skills/<category>/<skill-name>/`. Händische Überschreibungen in `LIB_CAT` sind unzulässig; das CI-Gate `testing/skill_tester.py::frontmatter_gate_errors` prüft Ordner gegen Frontmatter fail-closed.
3. **`description`** muss klar benennen, bei welchen Nutzeranfragen oder Systemereignissen der Skill aktiviert wird und welche Nachbardomänen ausgeschlossen sind.
4. **Mehrsprachige Varianten** (`SKILL_de.md`, `<name>-de`) werden in der GUI (`Skills › Übersicht`, Task `#2481`) unter der Hauptsprache gruppiert und über den Sprachumschalter im Seitenpanel gewechselt.

### 1.3 Zwei-Bäume- & Lock-Sicherheit bei Skill-Operationen

- Vor jeder Schreiboperation auf einer Skill-Quelle prüft `system/hub/_services/skill_source_service.py::check_write_locks` den kanonischen Lock-Scanner (`lock_scan.py --check-path <target> --json`) fail-closed.
- Sowohl der zentrale OneDrive-Spiegel (`OneDrive/.TOPICS/.AI/.SKILLS/`) als auch lokale Host-Spiegel (`~/.agents/skills/`, `~/.claude/skills/`) unterliegen der Zwei-Bäume-Regel (`LOCK-SYSTEM.md`).

---

## 2. Ist-Inventar & Architektur-Rollen

| Ebene | Pfad / Komponente | Rolle |
|---|---|---|
| **Kanonische Bibliothek** | `OneDrive/.TOPICS/.AI/.SKILLS/skills/<cat>/<name>/` | Zentrale, versionierte Master-Ablage (7 Kategorien: `dev`, `infrastructure`, `utilities`, `therapy`, `research`, `education`, `web`). |
| **Agenten-Depot (Host)** | `~/.agents/skills/<name>/` | Flaches, provider-neutrales Laufzeitdepot für Codex, Antigravity und CLI-Worker (~70 eigene Skills + ~20 HyperFrames-Skills). |
| **ControlCenter-MCP** | `ellmos-controlcenter-mcp` (`controlcenter_list_skills`, `controlcenter_find_skill`) | Semantisches Skill-Routing, Bundle-Zuweisung und Profilauflösung über alle Agenten hinweg. |
| **BACH Skill-Service** | `system/hub/_services/skill_source_service.py` | Lock-geprüfte Anzeige, Bearbeitung und Skill-Keeper-Verknüpfung (Hermes/Lernen unter `Skills & Software`, Task `#2480`). |

---

## 3. Gap-Analyse (Identifizierte Lücken)

Im Abgleich zwischen dem BACH/Ocean-Gesamtplan (`AKTUELLER-PLAN.md`, `MODUL-ZUORDNUNG.md`) und dem aktuellen Skill-Bestand bestehen folgende konkrete Lücken:

| Gap-ID | Bereich / Skill | Befund / Lücke | Zugehörige Tasks |
|---|---|---|---|
| **G-1** | **Eskalationsleiter & Autoritätsprüfung** (`escalation-ladder`) | Fehlende kanonische Spezifikation und Prüflogik für die 4-stufige Eskalationsleiter (Worker → Reviewer → Teamlead/Controller → Operator) inkl. Autoritätsprüfung. | `#2464`, `#3668`–`#3672` |
| **G-2** | **Plugin-Erstellung** (`plugin-creator`) | Kein dedizierter BACH/Ocean-Skill zum standardisierten Scaffolden neuer Plugins (`plugin.json` / `.claude-plugin` / `.codex-plugin` / MCP-Anbindung). | `#2554` |
| **G-3** | **Claim-Modus & Lease-Disziplin** (`claim-mode`) | Fehlender kompakter Betriebs-Skill für Agenten zur strikten Einhaltung von Task-Leases, Scope-Bindung, Cut-and-Close und Fail-Closed-Abgabe. | `#2561` |
| **G-4** | **Multi-Provider Plugin-Discovery** (`controlcenter_list_plugins`) | `ellmos-controlcenter-mcp` erkennt bisher Claude- und `.PLUGINS`-Einträge, übersieht aber `~/.codex/plugins` (`.codex-plugin/plugin.json`) und `~/.gemini/extensions` (`gemini-extension.json`). | `#2555` |
| **G-5** | **GUI-Gruppierung & Skill-Keeper** | Sprachvarianten (`DE`/`EN`) wurden bisher als separate Karten gezählt; Reiter 7 (Hermes/Lernen) aus `memory.astro` ist als *Skill Keeper* unter `Skills & Software` verankert. | `#2480`, `#2481` |

---

## 4. Umsetzungsfahrplan & Abnahmekriterien

1. **Standard-Dokumentation & CI-Härtung (`#2450`, `#3673`, `#3674`) — *Erledigt*:**
   - Kanonischer Standard in `docs/skills-standard-and-gap-plan.md` verankert.
   - Lock-Check in `skill_source_service.py` nutzt plattformübergreifende Pfadauflösung (`#2442`).
2. **ControlCenter Plugin-Discovery erweitern (`#2555`):**
   - `ellmos-controlcenter-mcp` um Discovery für Codex (`~/.codex/plugins`) und Antigravity/Gemini (`~/.gemini/extensions`, `~/.gemini/config/plugins`) erweitern und per Unit-Tests absichern.
3. **Fehlende Kern-Skills & Governance-Spezifikationen bereitstellen (`#2464`, `#2554`, `#2561`):**
   - Eskalationsleiter & Autoritätsprüfung (`#3668`–`#3672`) dokumentieren und testen.
   - Skills `plugin-creator` (`#2554`) und `claim-mode` (`#2561`) mit vollständigem YAML-Frontmatter und Referenzbeispielen anlegen.
