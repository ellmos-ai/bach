# BACH Agents & Experts

**Generiert:** (automatisch aus bach.db)
**Quelle:** bach.db (bach_agents, bach_experts)
**Generator:** `bach export mirrors` oder `python tools/agents_export.py`

---

## Boss-Agenten (Orchestrierer)

Boss-Agenten orchestrieren komplexe Workflows und delegieren an Experten.

### Entwickler Agent (ATI)
- **Typ:** Expert
- **Status:** active
- **Beschreibung:** Spezialisiert auf Tool-Ueberwachung und Software-Entwicklung.

### Bueroassistent
- **Typ:** boss
- **Kategorie:** beruflich
- **Beschreibung:** Steuern, Foerderplanung, Dokumentation

### Gesundheitsassistent
- **Typ:** boss
- **Kategorie:** privat
- **Beschreibung:** Arztberichte, Medikamente, Laborwerte, Vorsorge

### Persoenlicher Assistent
- **Typ:** boss
- **Kategorie:** privat
- **Beschreibung:** Briefings, Termine, Kalender, Haushalt

### Production
- **Typ:** boss
- **Kategorie:** kreativ
- **Beschreibung:** Content-Erstellung und Medienproduktion

---

## Experten

Experten sind spezialisierte Sub-Agenten unter Boss-Agenten.

*(Wird automatisch aus bach.db generiert)*

---

## Mess- und Arbeitsgrundlage für Änderungen

Für jede Messung und jede Bearbeitung wird ein frischer Worktree von `origin/<default>` angelegt:

```bash
git worktree add <path> -b <branch> origin/<default>
```

Im Arbeitsbaum des Hauptklons wird weder gemessen noch gebaut. Der Hauptklon kann einen alten Feature-Branch ausgecheckt haben und dadurch einen veralteten Stand zeigen. Der Lock bleibt im Hauptklon (auflösbar über `git rev-parse --git-common-dir`), die Arbeit findet im frischen Worktree statt.

---

<!--
  HINWEIS: Diese Datei ist ein Template.
  BACH generiert die vollstaendige Liste automatisch.
-->

---
🇬🇧 [English version](AGENTS.template.md)
