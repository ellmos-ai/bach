# Gap-Report: Vertrags- & Kündigungscockpit

> Auftrag: Task #1545 – Analyse Lücken & Schnittstellen für Vertrags- & Kündigungscockpit  
> Erstellt: 2026-09-29  
> Geprüfte Quellen: `hub/abo.py` (711 Zeilen), `hub/versicherung.py` (Bereich Z. 120–1150), `tests/test_versicherung_handler.py` (Schema-Fragment)

---

## 1. Zielsetzung

Das „Vertrags- & Kündigungscockpit“ soll Verbraucher*innen zentrale Kontrolle über laufende Abonnements (Abo) und Versicherungen geben. Dazu gehören:

- Übersicht aller Verträge
- Kündigungsfristen & automatische Erinnerungen
- Kostenentwicklung & Exportmöglichkeiten
- Schadenfallmanagement (Versicherungen)
- Einheitliche Bedienung über beide Domänen hinweg

Dieser Report vergleicht die beiden existierenden Domänenmodule `hub/abo.py` und `hub/versicherung.py`, identifiziert Lücken und empfiehlt nächste Schritte zur Vereinheitlichung.

---

## 2. Datenmodell-Vergleich

### 2.1 Abo-Domäne (`hub/abo.py`)

**Haupttabelle `abo_subscriptions`:**

| Feld | Bedeutung |
|------|-----------|
| `id` | Primärschlüssel |
| `name` | Bezeichnung des Abos |
| `anbieter` | Anbietername |
| `kategorie` | Kategorie |
| `betrag_monatlich` | Monatlicher Kostenbetrag |
| `zahlungsintervall` | Zahlungsintervall |
| `kuendigungslink` | URL zur Kündigungsseite |
| `erkannt_am` | Zeitpunkt der Erkennung |
| `bestaetigt` | Bestätigungsstatus |
| `aktiv` | Aktiv-Flag |
| `created_at` / `updated_at` | Zeitstempel |

**Sekundärtabellen:**
- `abo_payments` – Zahlungshistorie
- `abo_patterns` – Erkennungsmuster für Abos

**Operationen:**
- `_init_db`
- `_load_default_patterns`
- `_scan`
- `_list_abos`
- `_confirm`
- `_dismiss`
- `_costs`
- `_export`
- `_sync_mail`
- `_show_patterns`
- `_import_abotracker`
- `_prepare_abotracker_rows`
- `_schedule_import`
- `_arg_value`

**Stärken:**
- Automatische Erkennung aus E-Mails / Mailsync
- Bestätigungs-Workflow (`bestaetigt`, `aktiv`)
- Pattern-Import (`abo_patterns`)
- Kostenübersicht (`_costs`)
- Export (`_export`)
- Sync-Mail (`_sync_mail`)

**Schwächen / Fehlende Felder:**
- Keine Kündigungsfristen (weder Monate noch Datum)
- Keine automatische Kündigungserinnerung
- Kein Verlängerungsintervall / Mindestlaufzeit
- Kein Schadenfall-Modell (für Versicherungen irrelevant, aber Cockpit generisch nützlich)
- Keine Dokumentenreferenz (z. B. Vertragsschein, Rechnung)
- Kein Status außerhalb von `bestaetigt` und `aktiv`

---

### 2.2 Versicherungs-Domäne (`hub/versicherung.py`)

**Haupttabelle `fin_insurances`:**

| Feld | Bedeutung |
|------|-----------|
| `id` | Primärschlüssel |
| `name` | Bezeichnung |
| `versicherungsschein` | Vertrags-/Scheinnummer |
| `beginn_datum` | Vertragsbeginn |
| `ablauf_datum` | Vertragsablauf |
| `kuendigungsfrist_monate` | Kündigungsfrist in Monaten |
| `verlaengerung_monate` | Verlängerungsintervall in Monaten |
| `naechste_kuendigung` | Nächstmögliches Kündigungsdatum |
| *(weitere Standardfelder)* | ggf. Beitrag, Status etc. |

**Sekundärtabelle `fin_insurance_claims` (Schadenfälle):**

| Feld | Bedeutung |
|------|-----------|
| `schadensdatum` | Datum des Schadens |
| `beschreibung` | Sachverhalt |
| `status` | Bearbeitungsstatus |
| `betrag_gefordert` | Geforderter Betrag |
| `betrag_gezahlt` | Tatsächlich gezahlter Betrag |
| `aktenzeichen_versicherung` | Externes Aktenzeichen |

**Referenztabelle `insurance_types`:**

| Feld | Bedeutung |
|------|-----------|
| `name` | Name der Versicherungsart |
| `category` | Kategorie |
| `priority` | Priorität |
| `when_useful` | Hinweise zur Sinnhaftigkeit |
| `legal_requirement` | Rechtliche Pflicht? |

**Operationen (Methoden):**
- `_add` (Z. 489)
- `_edit` (Z. 581)
- `_delete` (Z. 711)
- `_fristen` (Z. 832) – Fristenübersicht & Erinnerungen
- `_check` (Z. 928) – Plausibilitäts-/Steuer-Check
- `_claim` (Z. 1083) – Schadenfall erfassen
- `_schedule_import` (Z. 251)

**Stärken:**
- Vollständige Kündigungsfristen-Modellierung
- Fristenüberwachung & Erinnerungen (`_fristen`)
- Schadenfallmanagement (`fin_insurance_claims`)
- Typen-Beratung (`insurance_types`)
- Steuer-/Plausibilitäts-Check (`_check`)
- Import-Integration (`_schedule_import`)

**Schwächen / Fehlende Felder:**
- Keine automatische E-Mail-Erkennung wie bei Abos
- Kein Kündigungslink pro Vertrag
- Kein Bestätigungs-Workflow für importierte/gescannte Verträge
- Keine zentrale Kostenübersicht wie `abo.costs`
- Kein generischer Export wie `abo.export`

---

### 2.3 Gegenüberstellung im Überblick

| Thema | Abo (`hub/abo.py`) | Versicherung (`hub/versicherung.py`) | Lücke |
|-------|--------------------|--------------------------------------|-------|
| **Kündigungsfristen** | ❌ nicht vorhanden | ✅ `kuendigungsfrist_monate`, `verlaengerung_monate`, `naechste_kuendigung` | Abo braucht Kündigungsfristen |
| **Status-Workflow** | ✅ `bestaetigt`, `aktiv` | ⚠️ implizit über Datumsfelder | Versicherung braucht expliziten Status |
| **Erinnerungen** | ❌ nicht vorhanden | ✅ `_fristen` | Abo braucht Erinnerungslogik |
| **Kündigungslink** | ✅ `kuendigungslink` | ❌ nicht vorhanden | Versicherung braucht Kündigungslink |
| **E-Mail-Scan / Erkennung** | ✅ `_scan`, `_sync_mail`, `abo_patterns` | ⚠️ `_schedule_import` | Versicherung braucht ggf. Pattern-basierte Erkennung |
| **Kosten / Export** | ✅ `_costs`, `_export` | ⚠️ verstreut / nicht zentral | Versicherung braucht zentrale Kosten-/Export-API |
| **Schadenfälle** | ❌ nicht relevant | ✅ `fin_insurance_claims` | Cockpit braucht Schadenfall-View |
| **Vertragsschein / Aktenzeichen** | ❌ nicht vorhanden | ✅ `versicherungsschein`, `aktenzeichen_versicherung` | Abo könnte Vertrags-/Kundennummer speichern |
| **Vertragsbeginn / -ablauf** | ❌ nicht vorhanden | ✅ `beginn_datum`, `ablauf_datum` | Abo braucht Laufzeitfelder |
| **Typen-Beratung** | ❌ nicht vorhanden | ✅ `insurance_types` | Abo könnte Kategorien-Rating erhalten |
| **Steuer-Check** | ❌ nicht vorhanden | ✅ `_check` | Cockpit braucht generischen Steuer-Check |

---

## 3. Identifizierte Lücken

### 3.1 Domänenübergreifend (Cockpit-Vereinheitlichung)

1. **Kein gemeinsames Vertrags-Datenmodell.**
   - Abo und Versicherung haben unterschiedliche Tabellen, unterschiedliche Konzepte für Laufzeit/Kündigung und unterschiedliche Statusmodelle.
   - Eine generische `contracts`- oder `vertraege`-Tabelle würde Redundanz reduzieren.

2. **Kein gemeinsamer Vertragsstatus.**
   - Abo: `bestaetigt`, `aktiv`
   - Versicherung: implizit über `beginn_datum` / `ablauf_datum`
   - Benötigt wird ein einheitlicher Status-Workflow: z. B. `erkannt` → `bestaetigt` → `aktiv` → `gekuendigt` → `abgelaufen`.

3. **Keine gemeinsame Kündigungsfristen-Engine.**
   - Die Berechnung von `naechste_kuendigung` existiert nur bei Versicherungen.
   - Abos benötigen dieselbe Engine für ihre Kündigungsfristen.

4. **Keine gemeinsame Erinnerungsinfrastruktur.**
   - `_fristen` ist versicherungsspezifisch.
   - Eine generische `reminders`-Tabelle für beide Domänen wäre sinnvoll.

5. **Keine gemeinsame Export-/Kosten-API.**
   - `_costs` und `_export` sind abo-spezifisch.
   - Das Cockpit benötigt einen domänenübergreifenden Export (CSV, PDF, iCal).

6. **Keine gemeinsame Dokumenten-/Notizen-Anbindung.**
   - Weder Abo noch Versicherung verlinkt zentrale Vertragsdokumente oder Notizen einheitlich.

### 3.2 Abo-spezifisch

- **Laufzeitfelder fehlen:** `beginn_datum`, `ablauf_datum`, `verlaengerung_monate`.
- **Kündigungsfrist fehlt:** `kuendigungsfrist_monate` bzw. `kuendigungsfrist_tage`.
- **Kündigungslink ist vorhanden, aber nicht genutzt für Erinnerungen.**
- **Keine Erinnerung an Kündigungsfrist / Kündigungsdatum.**
- **Keine Vertragsnummer / Kundennummer.**
- **Keine Kategorisierung nach „kündbar jederzeit“ vs. „Mindestlaufzeit“.**

### 3.3 Versicherungsspezifisch

- **Kein Kündigungslink pro Vertrag.**
- **Kein Bestätigungs-Workflow für importierte Verträge.**
- **Keine automatische E-Mail-Erkennung (Pattern-Engine).**
- **Keine zentrale Kosten- und Zahlungsübersicht wie bei Abos.**
- **Kein Export analog `abo.export`.**
- **Schadenfall-Status ist rudimentär; fehlende Erinnerung/Workflow für Nachfassaktionen.**

---

## 4. Empfehlungen für Cockpit-Vereinheitlichung

### 4.1 Architektur: Generisches Vertrags-Backend

Empfohlene Tabellenstruktur:

```text
contracts               -- gemeinsame Vertragsbasis
  id, type              -- 'abo' | 'versicherung' | evtl. weitere
  name, anbieter,
  status,               -- erkannt | bestaetigt | aktiv | gekuendigt | abgelaufen
  beginn_datum,
  ablauf_datum,
  kuendigungsfrist_monate,
  verlaegerung_monate,
  naechste_kuendigung,
  kuendigungslink,
  vertragsnummer,
  betrag_monatlich,
  zahlungsintervall,
  created_at, updated_at

contract_documents      -- Vertragsdokumente / Scheine
contract_reminders      -- Fristen-Erinnerungen
contract_payments       -- Zahlungshistorie (vereinheitlicht abo_payments)
contract_claims         -- Schadenfälle (nur type='versicherung')
contract_types          -- Typen-Beratung (aus insurance_types verallgemeinert)
contract_patterns       -- Erkennungsmuster (aus abo_patterns verallgemeinert)
```

**Vorgehen:**
- **Phase 1 (empfohlen für Task #1546):** Refactor-Schema designen, Migrationsskripte für bestehende `abo_subscriptions` / `fin_insurances` erstellen.
- **Phase 2:** Gemeinsame `ContractService`-Klasse mit Adapter-Pattern für Abo und Versicherung.
- **Phase 3:** UI-Cockpit bauen, das beide Domänen in einer View darstellt.

### 4.2 Gemeinsame Funktionen

| Funktion | Beschreibung | Priorität |
|----------|--------------|-----------|
| **Kündigungsfristen-Engine** | Berechnet `naechste_kuendigung` aus Beginn, Ablauf, Frist und Verlängerung. | Hoch |
| **Erinnerungsservice** | Erstellt reminders für Kündigungsfristen, Ablaufdatum, Schadensnachfassung. | Hoch |
| **Kosten- & Export-API** | Monatliche/tägliche Kosten + CSV/PDF/ICS-Export. | Mittel |
| **E-Mail-Scanner (generisch)** | Erweitert `abo_patterns` auf alle Vertragstypen. | Mittel |
| **Dokumenten-Upload** | Verknüpft Vertragsdokumente / Scheine. | Mittel |
| **Steuer- / Plausibilitätscheck** | Prüft doppelte Versicherungen, ungenutzte Abos etc. | Niedrig |

### 4.3 Schnittstellen-Empfehlung

- **CLI/Handler:** Einheitliche Subcommands:
  - `cockpit list [--type abo|versicherung|all]`
  - `cockpit add|edit|delete <id>`
  - `cockpit fristen` (Kündigungsfristen-Check)
  - `cockpit costs` (Kostenübersicht)
  - `cockpit export` (CSV/PDF)
  - `cockpit reminders` (Erinnerungen)
  - `cockpit scan` (E-Mail-Erkennung)
- **Interne API:** `ContractService` als zentrale Schicht, dahinter `AboRepository` und `InsuranceRepository` als Adapter.

### 4.4 Migration & Abwärtskompatibilität

- Bestehende Tabellen (`abo_subscriptions`, `fin_insurances`, `abo_payments`, `fin_insurance_claims`, `insurance_types`, `abo_patterns`) bleiben zunächst erhalten.
- Migration erzeugt die neuen `contract_*`-Tabellen und füllt sie aus den Altdaten.
- Handler für `abo` und `versicherung` werden schrittweise auf das neue Modell umgeleitet.

---

## 5. Nächste Schritte / Task #1546

Task #1546 soll die **Cockpit-Implementierung / Refactor** auf Basis dieses Reports starten:

1. **Schema-Design & Migration**
   - `contracts`-Haupttabelle + `contract_reminders`, `contract_payments`, `contract_claims`, `contract_documents`, `contract_types`, `contract_patterns`.
   - Migrationsskript von `abo_subscriptions` und `fin_insurances` nach `contracts`.

2. **Kündigungsfristen-Engine**
   - Extrahiere Logik aus `hub/versicherung.py` (`_fristen`) in generisches Modul.
   - Wende Engine auf Abos an.

3. **Erinnerungsservice**
   - Erstelle `contract_reminders` mit Trigger-Datum, Status, Verknüpfung zu `contracts`.

4. **Cockpit-Handler / CLI**
   - Neuer Eintrittspunkt oder Erweiterung bestehender Handler mit einheitlichen Subcommands.

5. **Tests**
   - Migrationstests, Fristenberechnungstests, Reminder-Tests, Export-Tests.

---

## 6. Zusammenfassung

- `hub/abo.py` ist stark in **Erkennung, Bestätigung, Kosten, Export und Sync**, aber schwach bei **Kündigungsfristen, Laufzeiten und Erinnerungen**.
- `hub/versicherung.py` ist stark in **Kündigungsfristen, Fristenmanagement, Schadenfällen und Typen-Beratung**, aber schwach bei **E-Mail-Erkennung, Bestätigungs-Workflow, Kündigungslink und Kosten-/Export-API**.
- Die größte Lücke ist das **fehlende gemeinsame Vertragsdatenmodell und die fehlende gemeinsame Fristen-/Erinnerungsinfrastruktur**.
- Empfohlene Lösung: Einführung einer generischen `contracts`-Schicht mit Adapter-Pattern für Abo und Versicherung.

---

*Ende des Gap-Reports.*
