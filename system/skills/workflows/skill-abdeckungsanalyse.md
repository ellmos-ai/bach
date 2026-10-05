# Skill-Abdeckungsanalyse Workflow

**Version:** 1.0.0

**Zweck:** Systematische Analyse der BACH Skill-Abdeckung im Vergleich zu Industrie-Standards.
**Frequenz:** Alle 2-4 Wochen oder nach groesseren Aenderungen
**Output:** Aktualisierte skills/SKILL_ANALYSE.md

---

## 1. VORBEREITUNG

### 1.1 Inventar erfassen
```bash
# Skills zaehlen
bach --help dirs
# Oder manuell:
ls agents/
ls skills/_service/
ls skills/workflows/
ls skills/_templates/
ls skills/mediaproduction/
ls skills/textproduction/
```

### 1.2 Referenz-Frameworks pruefen
Web-Recherche nach aktuellen Standards:
- LangChain Capabilities
- CrewAI Features
- AutoGen Functions
- Anthropic Skills (awesome-llm-skills)

---

## 2. ANALYSE-SCHRITTE

### 2.1 Industrie-Benchmark erstellen

Standard LLM-Agent Faehigkeiten bewerten:

| Bereich | Fragen |
|---------|--------|
| Planning | Task-Decomposition vorhanden? Subgoals? |
| Memory | Short/Long-term? RAG? Lessons? |
| Tool Integration | Wie viele Tools? MCP? API? |
| Code Generation | Write? Debug? Test? |
| Document Analysis | PDF? DOCX? Summarize? |
| Web Search | Research? Fact-Check? |
| Communication | Multi-Agent? Routing? |
| Content Creation | Text? Media? Templates? |
| Data Analysis | CSV? Charts? Stats? |
| Automation | Workflows? Schedules? Daemon? |
| Self-Reflection | Error-Learning? Success-Tracking? |
| Context Management | Compression? Retrieval? |

### 2.2 Koeffizienten berechnen

```
ABDECKUNGSKOEFFIZIENT = (Implementiert / Benoetigt) * Qualitaet

Qualitaet:
  1.0 = Vollstaendig, getestet, dokumentiert
  0.8 = Implementiert, dokumentiert
  0.6 = Implementiert, nicht dokumentiert
  0.4 = Teilweise implementiert
  0.2 = Nur Konzept/Entwurf
```

Visualisierung:
```
[█████] 90-100%  Exzellent
[████░] 70-89%   Gut
[███░░] 50-69%   Mittel
[██░░░] 30-49%   Lueckenhaft
[█░░░░] 0-29%    Kritisch
```

### 2.3 Luecken identifizieren

Kategorisieren nach Koeffizient:
- **Kritisch** (< 0.50): Sofort adressieren
- **Mittel** (0.50-0.70): Mittelfristig
- **Verbesserung** (0.70-0.85): Nice-to-have

### 2.4 Synergien pruefen

Matrix erstellen:
```
            Komp_A  Komp_B  Komp_C
Komp_A        -      ?       ?
Komp_B        ?      -       ?
Komp_C        ?      ?       -

Legende: ✓ = aktiv, ○ = potenziell
```

Fragen:
- Welche Komponenten arbeiten bereits zusammen?
- Welche KOENNTEN zusammenarbeiten?
- Was blockiert die Synergie?

---

## 3. OUTPUT ERSTELLEN

### 3.1 SKILL_ANALYSE.md aktualisieren

Struktur:
1. Skill-Inventar (Anzahl pro Ordner)
2. Abdeckungsanalyse (Tabelle mit Koeffizienten)
3. Lueckenbericht (kritisch/mittel/verbesserung)
4. Synergien (bestehend/potenziell)
5. Empfehlungen (Quick-Wins/Mittelfristig/Langfristig)
6. Framework-Vergleich
7. Changelog

### 3.2 Aenderungen dokumentieren

Im Changelog eintragen:
```
| Datum | Aenderung |
|-------|-----------|
| YYYY-MM-DD | Analyse durchgefuehrt, Koeffizienten aktualisiert |
```

---

## 4. CHECKLISTE

```
[ ] 1. Skill-Inventar gezaehlt
[ ] 2. Web-Recherche zu Frameworks
[ ] 3. Benchmark-Tabelle erstellt
[ ] 4. Koeffizienten berechnet
[ ] 5. Luecken kategorisiert
[ ] 6. Synergien geprueft
[ ] 7. Empfehlungen formuliert
[ ] 8. SKILL_ANALYSE.md aktualisiert
[ ] 9. Changelog ergaenzt
```

---

## 5. REFERENZ-METRIKEN

### Letzter Stand (2026-01-17)

| Bereich | Koeffizient |
|---------|:-----------:|
| Tool-Integration | 0.95 |
| Memory-System | 0.90 |
| Kommunikation | 0.85 |
| Context-Management | 0.85 |
| Automation/Daemon | 0.80 |
| Planning | 0.80 |
| Content-Creation | 0.75 |
| Self-Reflection | 0.70 |
| Code-Generation | 0.70 |
| Document-Analysis | 0.60 |
| Web-Search | 0.50 |
| Data-Analysis | 0.20 |

**Gesamt: 72%**

### Ziel-Metriken

| Bereich | Aktuell | Ziel | Delta |
|---------|:-------:|:----:|:-----:|
| Data-Analysis | 20% | 60% | +40% |
| Web-Search | 50% | 70% | +20% |
| Document-Analysis | 60% | 80% | +20% |
| **Gesamt** | **72%** | **80%** | **+8%** |

---

## 6. TRIGGER

Analyse durchfuehren wenn:
- 2+ Wochen seit letzter Analyse
- Neuer Skill hinzugefuegt
- Groessere Refaktorierung
- Vor Major-Release
- User fragt nach Status

---

*Workflow erstellt: 2026-01-17*
*Basiert auf: skills/SKILL_ANALYSE.md*
