---
name: selbstmanagement
version: 1.0.0
type: expert
author: Claude
created: 2026-02-04
updated: 2026-09-18
anthropic_compatible: true
status: active

dependencies:
  tools: [selbstmanagement_cli.py]
  services: []
  workflows: []

description: >
  Expert fuer persoenliches Selbstmanagement. Nutze diesen Skill fuer: (1)
  Lebenskreise/Lebensbereiche bewerten, (2) Berufsziele definieren und
  tracken, (3) ADHS-Strategien abrufen, (4) Work-Life-Balance analysieren.
---
# Selbstmanagement Expert

Unterstuetzt ganzheitliches Lebensmanagement mit Fokus auf Balance, Ziele und Strategien.

## Kernfunktionen

### 1. Lebenskreise (7 Bereiche)

Basiert auf dem "Wheel of Life" Modell mit angepassten Kategorien:

| Bereich | Beschreibung |
|---------|--------------|
| **Gesundheit** | Koerperliche & mentale Gesundheit, Fitness, Schlaf |
| **Beziehungen** | Partner, Familie, Freunde, soziales Netzwerk |
| **Karriere** | Beruf, Einkommen, Berufliche Entwicklung |
| **Finanzen** | Ersparnisse, Investitionen, Finanzielle Sicherheit |
| **Persoenliche Entwicklung** | Lernen, Hobbys, Kreativitaet, Spiritualitaet |
| **Freizeit** | Erholung, Spass, Reisen, Abenteuer |
| **Umfeld** | Wohnen, Arbeitsumgebung, physische Umgebung |

**Bewertungsskala:** 1-10 (1 = sehr unzufrieden, 10 = exzellent)

### 2. Berufsziele-Tracking

- Langfristige Karriereziele definieren
- Meilensteine mit Deadlines setzen
- Fortschritt tracken
- Ressourcen und Blocker erfassen
- Review-Termine automatisch planen

### 3. ADHS-Strategien-Bibliothek

Sammlung erprobter Strategien fuer ADHS-Management:

**Kategorien:**
- Zeitmanagement (Pomodoro, Time-Boxing, etc.)
- Organisation (Systeme, Routinen, Checklisten)
- Fokus (Ablenkungen minimieren, Deep Work)
- Emotionsregulation (Coping, Selbstfuersorge)
- Motivation (Belohnungssysteme, Gamification)
- Medikation (Reminder, Tracking - optional)

## Datenbank-Schema

```sql
-- Lebenskreise-Bewertungen
CREATE TABLE IF NOT EXISTS selfmgmt_life_circles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_date DATE NOT NULL,
    health INTEGER CHECK(health BETWEEN 1 AND 10),
    relationships INTEGER CHECK(relationships BETWEEN 1 AND 10),
    career INTEGER CHECK(career BETWEEN 1 AND 10),
    finances INTEGER CHECK(finances BETWEEN 1 AND 10),
    personal_growth INTEGER CHECK(personal_growth BETWEEN 1 AND 10),
    leisure INTEGER CHECK(leisure BETWEEN 1 AND 10),
    environment INTEGER CHECK(environment BETWEEN 1 AND 10),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Berufsziele
CREATE TABLE IF NOT EXISTS selfmgmt_career_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    target_date DATE,
    status TEXT DEFAULT 'active',
    progress INTEGER DEFAULT 0,
    resources TEXT,
    blockers TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

-- Meilensteine fuer Ziele
CREATE TABLE IF NOT EXISTS selfmgmt_milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES selfmgmt_career_goals(id),
    title TEXT NOT NULL,
    due_date DATE,
    completed_at DATE,
    notes TEXT
);

-- ADHS-Strategien
CREATE TABLE IF NOT EXISTS selfmgmt_adhd_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    when_to_use TEXT,
    steps TEXT,
    effectiveness INTEGER DEFAULT 3,
    personal_notes TEXT,
    times_used INTEGER DEFAULT 0,
    last_used DATE
);
```

## CLI-Befehle

```bash
# Lebenskreise
bach selbst kreise                    # Aktuelle Bewertung anzeigen
bach selbst kreise bewerten           # Neue Bewertung erstellen
bach selbst kreise historie           # Verlauf anzeigen
bach selbst kreise vergleich          # Letzten Monat vergleichen

# Berufsziele
bach selbst ziele list                # Alle Ziele
bach selbst ziele add "Titel"         # Neues Ziel
bach selbst ziele show <id>           # Details
bach selbst ziele progress <id> 50    # Fortschritt aktualisieren

# ADHS-Strategien
bach selbst adhd list                 # Alle Strategien
bach selbst adhd suche "fokus"        # Nach Kategorie/Begriff
bach selbst adhd verwenden <id>       # Strategie anwenden (tracked usage)
bach selbst adhd add                  # Neue Strategie hinzufuegen

# Zusammenfassung
bach selbst status                    # Gesamtuebersicht
```

## User-Datenordner

```
user/selbstmanagement/
  system/exports/              # PDF/Markdown Exporte
  assessments/          # Detaillierte Bewertungen
  goals/                # Ziel-Dokumentation
```

## Integration

- **Kalender:** Automatische Review-Termine
- **Tasks:** Meilensteine als Tasks importierbar
- **Gesundheit-Agent:** Gesundheitsbereich synchronisieren
- **Haushalt-Expert:** Finanzbereich synchronisieren

## Workflows

### Monatliches Review
1. Lebenskreise bewerten
2. Karriereziele-Fortschritt pruefen
3. ADHS-Strategien-Effektivitaet reviewen
4. Naechsten Monat planen

### Wochentlicher Check-in
1. Top-3 Fokus-Bereiche identifizieren
2. Blocker addressieren
3. Erfolge anerkennen

## Status

- **Expert-Typ:** Selbstmanagement
- **Kategorie:** Persoenliche Entwicklung
- **Status:** AKTIV
