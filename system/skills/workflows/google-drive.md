# Google Drive Delegation Workflow - SKILL v1.0

**Version:** 1.0.0

## Zweck

Multi-AI Kollaboration via Google Drive als Shared Workspace.

**Workflow:** Claude → Drive inbox → Gemini/Copilot → Drive outbox → Claude

---

## Ordnerstruktur auf Google Drive

```
Google Drive/RecludOS_Workspace/
├── delegation/
│   ├── inbox/      # Claude → andere AIs (neue Aufgaben)
│   ├── outbox/     # Andere AIs → Claude (Ergebnisse)
│   └── done/       # Abgeschlossene Delegationen
├── tasks/
│   ├── active/     # Laufende Tasks (JSON/MD)
│   └── archived/   # Archivierte Tasks
└── shared_memory/  # Persistente Daten für alle AIs
    ├── knowledge_base/
    └── context_files/
```

**User-Aktion erforderlich:** Diese Struktur muss einmalig auf Google Drive angelegt werden.

---

## Phase 1: Manuelle Delegation (JETZT nutzbar)

### Workflow

1. **Claude erstellt Delegation-Datei**
   - Format: Markdown (.md)
   - Speicherort: Google Drive/delegation/inbox/
   - Naming: task-{id}_delegation.md

2. **User informiert andere AI**
   - "Schau in Google Drive: RecludOS_Workspace/delegation/inbox/"
   - Gemini/Copilot findet neue Aufgabe

3. **Andere AI bearbeitet Task**
   - Liest task-{id}_delegation.md
   - Führt Aufgabe aus
   - Speichert Ergebnisse in outbox/task-{id}_results/

4. **Claude prüft Ergebnisse (bei Boot)**
   - Schritt 7 in Boot-Sequenz
   - `google_drive_search(api_query="'delegation/outbox' in parents")`
   - Ergebnisse laden → Task-Manager updaten → User informieren

---

## Delegation Template

**Datei:** task-{id}_delegation.md

```markdown
# Task: [Titel]

**Delegiert an:** Gemini Advanced / Copilot / etc.
**Task-ID:** task-{id}
**Priorität:** D (Delegiert)
**Deadline:** YYYY-MM-DD

## Aufgabe

[Detaillierte Beschreibung der Aufgabe]

## Erwartetes Output

- **Format:** PDF + Markdown + DOCX
- **Umfang:** [z.B. basierend auf 40+ Quellen]
- **Qualität:** [Anforderungen]

## Kontext

[Hintergrund-Informationen für besseres Verständnis]

## Quellen

[Liste von URLs, Dokumenten, etc.]

## Notizen

**Geschätzte Zeit:** [z.B. 2-3h]
**Claude's Empfehlung:** [Grund für Delegation]
```

---

## Delegation Targets

| AI Tool | Best For | Drive Path | Integration |
|---------|----------|------------|-------------|
| **Gemini** | Research, 40+ Sources, Vision | Google Drive | ✅ Nativ |
| **Copilot** | Excel, Word, Outlook | OneDrive* | ⚠️ Separates System |
| **Ollama** | Prompts, Simple Text | - | Local Queue |

*OneDrive ≠ Google Drive → Separate Workflow für Copilot

---

## Boot-Integration (Schritt 7)

**Aus boot/SKILL.md:**

```
7. Google Drive Delegation prüfen:
   → google_drive_search(api_query="'delegation/outbox' in parents")
   → Falls Ergebnisse vorhanden:
     - Laden und analysieren
     - Task-Manager Status: delegated → completed
     - User informieren
     - (Optional) Nach done/ verschieben
```

**Trigger:** Jeder Boot-Vorgang  
**Frequenz:** Einmal pro Session  
**Fallback:** Manuell durch User-Info

---

## Beispiel-Workflow: Research Task

### 1. Claude erstellt Delegation

```markdown
# Task: KI-OS Marktanalyse

**Delegiert an:** Gemini Advanced
**Task-ID:** task-402
**Priorität:** D

## Aufgabe
Analysiere 35+ KI-Betriebssysteme. Erstelle Report mit:
- Executive Summary
- Kategorisierung
- Strategische Analyse  
- Vergleichstabelle

## Erwartetes Output
- PDF (Publication Ready)
- Markdown (Versionskontrolle)
- DOCX (editierbar)

**Geschätzte Zeit:** 2-3h
```

**Speichern in:** `delegation/inbox/task-402_delegation.md`

### 2. User → Gemini

```
"Schau in Google Drive:
RecludOS_Workspace/delegation/inbox/
→ task-402_delegation.md
Bearbeite und lege Ergebnisse in outbox/ ab."
```

### 3. Gemini arbeitet

- Liest Aufgabe
- Recherchiert 35+ Quellen
- Erstellt 3 Formate (PDF, MD, DOCX)
- Speichert in: `delegation/outbox/task-402_results/`

### 4. Claude prüft (nächster Boot)

```
Schritt 7: Google Drive Delegation Check
→ Gefunden: task-402_results/
→ Laden: 3 Dateien
→ Task-Manager: task-402 status = completed
→ User: "Delegation task-402 abgeschlossen! 3 Dateien verfügbar."
```

---

## Vorteile

### Für User
- ✅ Ein Workspace für alle AIs
- ✅ Keine Downloads/Uploads mehr
- ✅ Transparenz (alles an einem Ort)
- ✅ Asynchrone Verarbeitung

### Für Claude
- ✅ Automatische Result-Checks
- ✅ Strukturiertes Format
- ✅ Audit Trail
- ✅ Token-Ersparnis bei Delegation

### Für Gemini/Copilot
- ✅ Klare Task-Spezifikation
- ✅ Kontext via shared_memory/
- ✅ Feedback Loop möglich

---

## Erwartete Zeitersparnis

| Metrik | Ohne Drive | Mit Drive | Ersparnis |
|--------|------------|-----------|-----------|
| User-Zeit pro Delegation | 10 Min | 5 Min | **-50%** |
| Claude Tokens (Research) | 50k+ | 500 | **-99%** |
| Durchlaufzeit | Synchron | Async | **-50%** |

---

## Roadmap

### ✅ Phase 1: Manuelle Delegation (JETZT)
- Claude erstellt Delegation-Dateien
- User informiert andere AI
- Boot-Check für Ergebnisse (Schritt 7)

**Aufwand:** 5 Min Setup, 2 Min pro Delegation

### 🔜 Phase 2: Semi-Automatisch (in 1-2 Wochen)
- Python-Script für Auto-Check
- Notification-System
- Delegations-Dashboard (HTML)

**Aufwand:** 4-6h Entwicklung

### 🔮 Phase 3: Voll-Automatisch (Zukunft)
- Direct Drive Write (google_drive_create)
- Webhooks/Polling
- Gemini API Integration
- Retry-Logic

**Aufwand:** 20-30h

---

## Risiken & Mitigation

| Risiko | Mitigation |
|--------|-----------|
| Drive API Limits | Polling max 1x/Min, Exponential Backoff |
| Gemini kein Auto-Check | Phase 1 bleibt manuell (User informiert) |
| Datenschutz | Nur nicht-sensible Tasks, Optional Encryption |

---

## Nutzung

### Neue Delegation erstellen

1. Task analysieren → Delegation sinnvoll?
2. Template füllen
3. In Drive/delegation/inbox/ speichern
4. User informieren → andere AI beauftragen
5. Task-Manager: status = "delegated_to_{target}"

### Ergebnisse abholen

1. Boot-Sequenz Schritt 7 ausgeführt
2. Falls Ergebnisse gefunden:
   - Laden via google_drive_fetch
   - Validieren
   - Task-Manager updaten
   - User informieren

---

## Best Practices

**DO:**
- ✅ Klare, detaillierte Task-Beschreibungen
- ✅ Kontext mitgeben für bessere Ergebnisse
- ✅ Erwartungen definieren (Format, Umfang)
- ✅ Geschätzte Zeit angeben

**DON'T:**
- ❌ Sensible Daten ohne Encryption
- ❌ Delegation ohne klare Spezifikation
- ❌ Ergebnisse ohne Validierung integrieren
- ❌ Audit Trail ignorieren

---

**Version:** 1.0  
**Erstellt:** 2025-12-27  
**Status:** Phase 1 einsatzbereit  
**Next Review:** Nach 5 Test-Delegationen