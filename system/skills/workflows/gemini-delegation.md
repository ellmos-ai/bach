# Gemini Delegation Workflow

**Version:** 1.0.0

> **Delegiere ressourcenintensive Tasks an Google Gemini**

---

## Übersicht

Gemini wird für Tasks genutzt, die:
- Sehr viel Kontext benötigen (40+ Seiten)
- Umfangreiche Recherche erfordern
- Lange Outputs generieren (5000+ Wörter)
- Claude's Token-Budget schonen sollen

---

## Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  GEMINI DELEGATION WORKFLOW                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. TASK ERSTELLEN                                              │
│     Claude erstellt Task-Datei in:                              │
│     → gemini/inbox/task_YYYYMMDD_HHMMSS.md                     │
│                                                                 │
│  2. TRANSFER ZU GEMINI                                          │
│     User kopiert/synct zu Google Drive oder                     │
│     öffnet direkt in AI Studio                                  │
│                                                                 │
│  3. GEMINI VERARBEITET                                          │
│     Via AI Studio, Gemini App oder API                          │
│                                                                 │
│  4. ERGEBNIS ABLEGEN                                            │
│     Ergebnis in:                                                │
│     → gemini/outbox/result_YYYYMMDD_HHMMSS.md                  │
│                                                                 │
│  5. CLAUDE INTEGRIERT                                           │
│     Bei nächstem Boot prüft Claude outbox/                      │
│     und integriert Ergebnisse                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Task-Format

```markdown
# Delegation Task [ID]

**Created:** 2025-12-31T14:00:00
**Target:** Gemini
**Priority:** Normal

## Task

[Beschreibung der Aufgabe]

## Context

[Relevanter Kontext, Hintergrund]

## Instructions

1. [Schritt 1]
2. [Schritt 2]
3. [Schritt 3]

## Expected Output

- Format: Markdown
- Länge: ~3000 Wörter
- Struktur: [Gewünschte Struktur]

## Attachments

- [Falls vorhanden: Links zu Dokumenten]
```

---

## Ergebnis-Format

```markdown
# Result for Task [ID]

**Completed:** 2025-12-31T16:00:00
**Model:** Gemini 1.5 Pro

## Summary

[Kurze Zusammenfassung]

## Detailed Analysis

[Hauptinhalt]

## Sources

- [Quellen falls verwendet]

## Recommendations

- [Empfehlungen/Nächste Schritte]
```

---

## Trigger für Gemini-Delegation

| Trigger | Beschreibung |
|---------|--------------|
| **Keywords** | "deep research", "long document", "concept analysis" |
| **Token-Budget** | Claude bei >80% Token-Verbrauch |
| **Dokument-Länge** | Input >40 Seiten |
| **Output-Länge** | Erwarteter Output >5000 Wörter |
| **Explizit** | User sagt "delegate to Gemini" |

---

## Use Cases

### 1. Deep Research
```
"Research the current state of mRNA vaccine technology,
including recent developments, clinical trials, and future prospects.
Provide a comprehensive 5000-word analysis."
```

### 2. Document Analysis
```
"Analyze the attached 80-page research paper on CRISPR.
Summarize key findings, methodologies, and implications."
```

### 3. Literature Review
```
"Create a literature review of the last 5 years of research
on autism spectrum disorder interventions. Include at least
20 peer-reviewed sources."
```

### 4. Concept Synthesis
```
"Compare and synthesize the following 5 approaches to
machine learning interpretability: SHAP, LIME, Attention,
Integrated Gradients, and Concept Bottleneck Models."
```

---

## Pfade

| Typ | Pfad |
|-----|------|
| **Inbox** | `connections/connected_AIs/external/gemini/inbox/` |
| **Outbox** | `connections/connected_AIs/external/gemini/outbox/` |
| **Registry** | `connections/connected_AIs/external/gemini/registry.json` |

---

## Integration mit Communication Executor

```bash
# Task an Gemini routen
python communication_executor.py route --partner gemini --message "Research task..."

# Ergebnis: Task-Datei wird in inbox/ erstellt
```

---

**Version:** 1.0.0
**Status:** ✅ ACTIVE
**Erstellt:** 2025-12-31
