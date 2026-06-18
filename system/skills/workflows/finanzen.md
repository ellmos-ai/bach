# Workflow: Finanzen

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Finanz-Usecases, bei denen wiederkehrende,
insbesondere unregelmäßige Kosten strukturiert geplant oder überprüft werden.

Der Workflow deckt insbesondere Usecase 32 ab:

- Wiederkehrende jährliche Kosten planen

Primäre BACH-Rolle: Assistenz `finanz-assistent`.
Typische Experten: `aboservice`, `financial_mail`, `steuer-agent`.

---

## Leitlinien

1. **Kalenderlogik vor Schätzwerten.**
   Wiederkehrende Kosten brauchen Fälligkeit, Turnus, Betrag und Quelle.

2. **Aktive und inaktive Posten trennen.**
   Nicht jeder historische Eintrag ist noch zahlungsrelevant.

3. **Planbarkeit ist das Ziel.**
   BACH soll erwartbare Spitzen sichtbar machen, nicht nur Daten sammeln.

4. **Belege und Herkunft mitdenken.**
   Relevante Dokumente oder Mailquellen sauber referenzieren.

---

## Vorbereitung

```bash
bach usecase show 32
bach help tasks
bach help memory
bach tools search abo
```

Zusätzlich prüfen:

- Welche Quelle ist führend: Übersichtsdokument, Mail, Vertrag, Tabelle?
- Geht es um Monatsvorschau, Jahresplan oder Statuspflege?
- Sind Beträge, Intervalle und nächste Fälligkeiten vorhanden?

---

## Ablauf

### 1. Kostenart und Zeitraum festlegen

- Monatliche Vorschau, Jahresplanung oder Statusabgleich unterscheiden.

### 2. Bestehende Finanzdaten prüfen

- Wiederkehrende Kosten, Verträge, Abos oder Steuerbezüge sichten.

### 3. Planstruktur erzeugen

- Betrag, Intervall, nächster Termin und Kategorie pro Posten erfassen.
- Größere finanzielle Spitzen gesondert hervorheben.

### 4. Offene Stellen markieren

- Fehlende Beträge, unklare Fälligkeiten oder unsichere Aktiv-Status
  ausdrücklich benennen.

### 5. Usecase-Check

```bash
bach usecase run 32 --dry-run
bach usecase run-all FINANZEN --dry-run
```

---

## Ergebnis

Ein sauberer Finanz-Usecase endet mit:

- einer planbaren Übersicht wiederkehrender Kosten,
- klaren Fälligkeiten und offenen Unsicherheiten,
- und einer Basis für spätere Abo-, Mail- oder Steuerfälle.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für FINANZEN-Usecases |
