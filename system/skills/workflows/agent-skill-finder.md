# Agent/Skill Finder Workflow

**Version:** 1.0.0

## Zweck
Finde den passenden Agenten, Experten oder Skill für eine Benutzeranfrage.

## Trigger
- Benutzer beschreibt einen Usecase oder eine Anfrage
- System soll automatisch den besten Handler finden

## Ablauf

### 1. Anfrage analysieren
```bash
# Keywords aus der Anfrage extrahieren
# Beispiel-Keywords: "steuer", "dokument", "mail", "health"
```

### 2. Passenden Handler suchen

#### 2.1 Agenten prüfen
```bash
bach skills list --type agent
# Agenten: ATI, Persönlicher Assistent, Finanzassistent, etc.
```

#### 2.2 Experten prüfen
```bash
bach skills list --type expert
# Experten: steuer/, gesundheitsverwalter/, aboservice/, etc.
```

#### 2.3 Skills/Workflows prüfen
```bash
bach skills search "<keyword>"
bach help workflows
```

### 3. Entscheidungsbaum

```
Anfrage
  |
  +-- Gefunden?
  |     |
  |     +-- JA --> Delegieren/Ausführen
  |     |           bach skills run <skill>
  |     |
  |     +-- NEIN --> Weiter zu 4
  |
```

### 4. Kein passender Handler gefunden

#### 4.1 Allgemein helfen
- Mit vorhandenem Wissen antworten
- Help-System konsultieren: `bach help <thema>`

#### 4.2 Neuen Handler vorschlagen
```bash
# Task für neuen Agent/Experten/Skill erstellen
bach task add "SKILL: <Name> für <Usecase>" --category development
```

## Zuordnungstabelle (Beispiele)

| Keyword | Handler-Typ | Name |
|---------|-------------|------|
| steuer, beleg | Expert | steuer/ |
| gesundheit, arzt | Expert | gesundheitsverwalter/ |
| mail, email | Service | mail/ |
| dokument, scan | Service | document/ |
| code, bug, software | Agent | ATI |
| backup, sicherung | Service | backup_manager |
| workflow, prozess | Workflow | skills/workflows/ |

## CLI-Integration (geplant)

```bash
# Zukünftiger Befehl
bach find "Ich möchte meine Steuerbelege scannen"
# Output: Empfehlung: Expert steuer/ -> Workflow steuer-beleg-scan.md
```

## Siehe auch
- `bach help skills` - Skills-System
- `bach help agents` - Agenten-Übersicht
- `agents/` - Agenten-Profile
- `agents/_experts/` - Experten-Module
