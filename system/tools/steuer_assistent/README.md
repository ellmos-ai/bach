# steuer-assistent

*Lokale Beleg-Arbeitsunterlage für Arbeitnehmer-Werbungskosten — keine Steuerberatung.*

**Local receipt worksheet for employee tax records — not tax advice.**
A small, offline-first Python module that lets you record self-categorized
receipts for employee income-related expenses (*Werbungskosten*), sum them
to the cent, and export a private, non-official ZIP worksheet. It does not
assess deductibility and does not create or submit a tax return.

Das Modul erfasst vom Nutzer eingeordnete Angaben, summiert sie centgenau und
erzeugt ein privates ZIP. Es prüft weder die steuerliche Abziehbarkeit noch
erstellt oder übermittelt es eine Steuererklärung.

Die offizielle elektronische Übermittlung erfolgt über ELSTER beziehungsweise
dafür zugelassene Software. ELSTER weist außerdem darauf hin, dass bloß in
„Meine Belege“ erfasste Dokumente noch nicht an das Finanzamt übermittelt sind:
[ELSTER-Belegverwaltung](https://portal.elster.de/eportal/helpGlobal?themaGlobal=help_meine_belege),
[ELSTER-Belegnachreichung](https://www.elster.de/eportal/formulare-leistungen/alleformulare/belegnachreichung).

## Verwendung

| Schritt | Befehl |
|---|---|
| Beleg erfassen | `python -m steuer_assistent.cli add --kategorie Arbeitsmittel --betrag 49.90 --datum 2026-03-15 --notiz "USB-Hub"` |
| Belege ohne Notizen anzeigen | `python -m steuer_assistent.cli list` |
| Notizen bewusst anzeigen | `python -m steuer_assistent.cli list --mit-notiz` |
| Erfasste Werbungskosten summieren | `python -m steuer_assistent.cli werbungskosten --jahr 2026` |
| Private Arbeitsunterlage erzeugen | `python -m steuer_assistent.cli export --jahr 2026` |
| Status ohne Store-Pfad | `python -m steuer_assistent.cli status` |

Der Standardexport heißt `STEUER_UNTERLAGEN_<jahr>.zip`. Vorhandene Ziele
werden nicht überschrieben. Das ZIP enthält CSV, Zusammenfassung und einen
Hinweis zur Nicht-Amtlichkeit, aber keine eigentlichen Belegdateien.

## Store und Datenschutz

- Standard: `%USERPROFILE%\.steuer-assistent\steuer.db`
- Override: `STEUER_ASSISTENT_DB=<Pfad>` oder `--store <Pfad>`
- Store, Belegpfade und Exporte müssen kanonisch im Benutzerverzeichnis liegen.
- Geld wird intern zusätzlich als Integer-Cents gespeichert; Version 0.2.0
  migriert vorhandene `REAL`-Beträge und bestehende Nummernfolgen automatisch.
- Notizen und absolute Pfade erscheinen in der CLI nur mit explizitem Opt-in.
- Das Modul versucht restriktive Dateimodi zu setzen; maßgeblich bleiben die
  Zugriffsrechte und Sicherungseinstellungen des Betriebssystems.
- Keine Netzwerkverbindung, kein Cloud-Upload, kein Zugriff auf `bach.db`.

Tabellen: `belege`, `beleg_sequences`, `werbungskosten_kategorien`,
`export_runs`.

## Installation und Prüfung

```powershell
cd <pfad-zum-modul>\steuer-assistent
python -m pip install -e .
python -B -m pytest tests -q -p no:cacheprovider
```

## Grenzen

- Scope: private Arbeitsunterlage für Arbeitnehmer-Werbungskosten;
  kein Gewerbe-/Betriebsausgaben-Workflow
- keine Steuerberatung, Rechtsprüfung oder Anerkennungsentscheidung
- kein ELSTER-, ERiC- oder amtliches Finanzamt-Format
- keine direkte Beleg- oder Steuerdatenübermittlung
- BACH-Quelle `agents/_experts/steuer/` wird nicht zur Laufzeit gelesen
- Separates, eigenständiges Produkt (nicht Teil dieses Moduls): eine
  kommerzielle Voll-Pipeline „steuer-suite" befindet sich in Vorbereitung
  und unterliegt einer eigenen rechtlichen Prüfung, sobald sie existiert.

## Rechtlicher Rahmen und Betriebsform

KI-gestützte Ersteinschätzung (kein Ersatz für anwaltliche Beratung), Stand
2026-07-23: Für die aktuelle Betriebsform — reine Selbstanwendung auf lokal
gehaltene, vom Nutzer selbst eingeordnete Daten, ohne Netzwerkverbindung,
ohne Rechtsprüfung des Einzelfalls — ist dieses Modul nach den einschlägigen
Vorschriften des Steuerberatungsgesetzes (StBerG, insbes. § 2 Abs. 2) keine
„geschäftsmäßige Hilfeleistung in Steuersachen".

**Diese Einschätzung gilt nur für die beschriebene Betriebsform.** Eine
erneute rechtliche Prüfung ist nötig, sobald sich die Betriebsform ändert —
insbesondere bei:

1. **automatischer steuerlicher Einordnung oder Würdigung** durch das Tool
   selbst (statt reiner Nutzereingabe),
2. **Hosting- oder Servicebetrieb**, oder Bearbeitung fremder Belege durch
   den Betreiber (statt lokaler Selbstanwendung),
3. **ELSTER-, ERiC- oder sonstiger amtlicher Übermittlungsanbindung**,
4. **entgeltlicher Vermarktung** dieses Moduls oder einer daraus
   abgeleiteten Voll-Pipeline (z. B. „steuer-suite").

Diese Einschätzung wurde ohne Prüfung der Rechtsprechung und ohne
Fremdmodell-Review erstellt; bei Zweifeln oder vor produktivem Einsatz mit
echten Steuerdaten Dritter empfiehlt sich eine unabhängige anwaltliche
Prüfung.

## Origin

- BACH-Substanz: `agents/_experts/steuer/` (MIT)
- Extraktion: 2026-06-22
- Dieses private Modul: MIT

## Lizenz

MIT — siehe [`LICENSE`](LICENSE). Änderungen: siehe [`CHANGELOG.md`](CHANGELOG.md).
Sicherheitsmeldungen: siehe [`SECURITY.md`](SECURITY.md).
