---
name: research-agent
version: 1.0.0
type: agent
author: Gemini
created: 2025-12-31
updated: 2026-09-17
anthropic_compatible: true
status: active

orchestrates:
  experts: []
  services: [prompt-manager, scheduling, memory]

dependencies:
  tools: [perplexity, consensus, notebooklm, elicit]
  services: []
  workflows: []

description: >
  Spezialisiert auf wissenschaftliche Recherche, Literaturanalyse und
  evidenzbasierte Zusammenfassungen. Orchestriert verschiedene KI-Tools und
  Datenbanken für umfassende Recherchen.
---
# Research Agent

> **Version:** 1.0.0 | **Status:** active | **Erstellt:** 2025-12-31 | **Aktualisiert:** 2026-09-17

## Überblick

Der Research Agent ist spezialisiert auf wissenschaftliche Recherche, Literaturanalyse und evidenzbasierte Zusammenfassungen. Er orchestriert verschiedene KI-Tools und Datenbanken für umfassende Recherchen.

---

## Fähigkeiten

### 1. Literaturrecherche

- Multi-Datenbank-Suche (PubMed, Consensus, Elicit)
- Fachspezifische Filterung
- Zeitraum-Einschränkungen
- Zitationsstil-Anpassung

### 2. Dokumentenanalyse

- PDF-Extraktion und Zusammenfassung
- Schlüsselkonzept-Identifikation
- Evidenz-Bewertung
- Quellenvergleich

### 3. Synthese

- Thematische Zusammenfassung
- Gap-Analyse
- Forschungsfragen-Entwicklung
- Hypothesen-Generierung

---

## Integrierte Services

| Service | Funktion |
|---------|----------|
| prompt-manager | Optimierte Recherche-Prompts |
| scheduling | Forschungs-Deadlines |
| memory | Recherche-Ergebnisse speichern |

---

## Externe Tools (KI-Center)

### Primär

- **Perplexity** - Web-Recherche mit Quellen
- **Consensus** - Wissenschaftliche Papers
- **NotebookLM** - Dokument-Analyse
- **Elicit** - Literatur-Review

### Sekundär

- **Scite.ai** - Zitations-Analyse
- **Claude** - Synthese und Analyse
- **Gemini** - Lange Dokumente

---

## MCP-Verbindungen

```
connections/
├── connected_APIs/pubmed/           # PubMed API
├── connected_services/google_drive/ # Dokument-Speicher
└── connected_AIs/external/gemini/   # Deep Research Delegation
```

---

## CLI-Befehle

```bash
# Agent starten (geplant)
bach research search "CRISPR autism therapy"

# Literatur-Review (geplant)
bach research review --topic "autism interventions" --years 5

# Dokument analysieren (geplant)
bach research analyze /path/to/paper.pdf

# Synthese erstellen (geplant)
bach research synthesize --sources ./papers/ --output report.md
```

> **Status:** CLI-Handler noch nicht implementiert

---

## Workflows

### Schnell-Recherche (5 Min)

1. Perplexity für Überblick
2. Top 3-5 Quellen identifizieren
3. Kurzzusammenfassung

### Standard-Review (30 Min)

1. PubMed/Consensus Suche
2. Abstract-Screening
3. Volltext-Analyse relevanter Papers
4. Synthese mit Evidenz-Level

### Deep Research (delegiert)

1. Task an Gemini delegieren
2. Ergebnis in outbox/ abholen
3. Review und Integration

---

## Delegation

Bei Token-Knappheit oder umfangreichen Aufgaben:

- **Gemini:** Lange Dokumente, 40+ Seiten
- **Perplexity:** Aktuelle Web-Recherche
- **NotebookLM:** Podcast-Generierung aus Quellen

---

## Output-Formate

- Markdown-Reports
- Annotierte Bibliographien
- Evidence-Maps
- Research-Briefs

---

## Verbundene Agenten

| Agent | Verbindung |
|-------|------------|
| Foerderplaner | Pädagogische Evidenz |
| Gesundheitsmanager | Medizinische Recherche |
| ATI | Technische Dokumentation |

---

## Roadmap

### Phase 1 (aktuell)

- [x] Agent-Dokumentation
- [ ] CLI-Handler: `hub/handlers/research.py`
- [ ] User-Bereich: `../user/research/`

### Phase 2

- [ ] PubMed MCP-Integration
- [ ] PDF-Analyse Pipeline
- [ ] Zitations-Management

---

*Research Agent für BACH v1.1*
