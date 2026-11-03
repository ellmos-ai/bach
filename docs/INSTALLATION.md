# BACH — Installations- und Modularisierungsanleitung

> **Status:** Kanonisch | **Version:** 3.15.0  
> **Architektur:** Entflochtener Core mit dynamischer Modul-Resolution (*Rinnsal ↔ BACH ↔ Meer*)  
> **Source of Truth (Plan D):** `C:\_Local_DEV\repos\bach` (Git-Klon) & `C:\_Local_DEV\repos\<module>`

---

## 1. Architektur & Leitprinzipien

BACH ist als zukunftssicherer, robuster Agenten-Core konzipiert, der durch **entflochtene, self-contained Module** erweitert wird.

### Kernprinzipien:
1. **Core-Stabilität vor Neuerung:** Der Kern bleibt schlank, lauffähig und abwärtskompatibel.
2. **Kataloggeregelte Auflösung (`modules.catalog.json`):** Sämtliche externen Module und Bibliotheken werden über den zentralen Modulkatalog versioniert und referenziert.
3. **Reversibilität & Fail-Closed:** Ungültige oder unvollständige Module werden vor dem Import abgelehnt.
4. **Zwei-Wege-Lebenszyklus:**
   - Innovationen werden in BACH erprobt und als self-contained Standalone-Module exportiert.
   - Module werden in eigenständigen Repositories weiterentwickelt.
   - Per `bach update modules --sync` werden die neuesten Versionen automatisch wieder in den Core verdrahtet.

---

## 2. Die 3 Ausbaustufen (Tiers)

Je nach Anwendungsfall und Ressourcenbudget kann BACH in einer von drei Ausbaustufen betrieben werden:

| Tier | Name | Charakteristik | Enthaltene Module |
|:---|:---|:---|:---|
| **1** | **Rinnsal** | Ultrakompakt, minimale Latenz, reiner Agenten-Loop & Task-Planer | `open-ocean`, `task-master`, `agents-heart`, `condition-gates` |
| **2** | **BACH** | Kuratierter Standard (12 kanonische Ocean-Stack-Module) | `open-ocean`, `ocean-resources`, `agents-heart`, `gardener`, `anonymizer`, `doc-keeper`, `task-master`, `condition-gates`, `foerderplaner`, `ellmos-system-gui`, `law-checker`, `worksheet-generator` |
| **3** | **Meer** | Vollausbau, maximale Fähigkeiten | Alle 79+ Module aus `modules.catalog.json` (inkl. Hardware-Module wie `ellmos-sensation`, `ellmos-homecontrol`, `ellmos-robotics`, `accounts-core` etc.) |

---

## 3. Voraussetzungen

- **Betriebssystem:** Windows 10/11, macOS, Linux
- **Python:** Python 3.10 bis 3.12 (mit SQLite3 und JSON-Unterstützung)
- **Versionskontrolle:** Git auf dem Systempfad
- **Arbeitsverzeichnis (Plan D):** `C:\_Local_DEV\repos` (oder konfigurierbar über `LOCAL_DEV_REPOS`)

---

## 4. Erstinstallation

### Schritt 1: Core klonen
```bash
cd C:\_Local_DEV\repos
git clone https://github.com/ellmos-ai/bach.git
cd bach
```

### Schritt 2: Systemverifikation & Preflight
```bash
python bach.py update check
```

### Schritt 3: Modulpaket auflösen und installieren
Wähle die gewünschte Ausbaustufe:

```bash
# Minimal-Installation (Rinnsal)
python bach.py update modules --tier rinnsal --sync

# Kuratierte Standard-Installation (BACH - Empfohlen)
python bach.py update modules --tier bach --sync

# Vollständige Installation (Meer)
python bach.py update modules --tier meer --sync
```

*(Hinweis: Bei `--sync` klont BACH fehlende Repositories automatisch nach `C:\_Local_DEV\repos` und gleicht die Manifeste mit `.MODULES/.CONTROL/` ab.)*

---

## 5. Laufender Betrieb & Synchronisation

Um den Core, alle installierten Module und Skills auf dem neuesten Stand zu halten:

```bash
# Gesamtes System prüfen und aktualisieren
python bach.py update all --apply

# Nur Skills mit zentraler Bibliothek und Agentenflotte (~/.claude/skills, ~/.codex/skills) abgleichen
python bach.py update skills --apply

# Nur Module und Manifeste abgleichen
python bach.py update modules --sync
```

---

## 6. Modul-Lifecycle: Export, Standalone-Dev & Re-Import

1. **Modul / Skill exportieren:**
   ```bash
   python bach.py skills export <skill_name>
   ```
2. **Eigenständig weiterentwickeln & testen:**
   Das exportierte Modul ist self-contained mit `manifest.json`, Quellcode und Tests.
3. **Integritätsprüfung vor Re-Import:**
   ```bash
   python bach.py skills verify <pfad_zum_modul>
   ```
4. **Re-Import in den BACH-Core:**
   ```bash
   python bach.py skills install <pfad_zum_modul>
   ```
