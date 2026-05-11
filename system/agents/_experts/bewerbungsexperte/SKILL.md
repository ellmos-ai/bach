---
name: bewerbungsexperte
version: 1.0.0
type: expert
author: BACH Team
created: 2026-01-25
updated: 2026-02-04
anthropic_compatible: true
status: active

dependencies:
  tools: [cv_generator.py]
  services: []
  workflows:
    - cv-generierung.md

description: >
  Spezialist fuer den gesamten Bewerbungsprozess. Analysiert Stellenanzeigen,
  optimiert Profile (LinkedIn/CV) und generiert massgeschneiderte Anschreiben.
  Generiert ASCII-Lebenslaeufe aus BACH-Daten und Ordnerstruktur.
---
# BEWERBUNGSEXPERTE v1.0

> Dein strategischer Partner fuer den naechsten Karriereschritt.

## AKTIVIERUNG

```bash
# CV generieren (einfach)
python agents/_experts/bewerbungsexperte/cv_generator.py

# CV aus Ordnerstruktur scannen
python agents/_experts/bewerbungsexperte/cv_generator.py --scan-folders

# CV in Datei speichern
python agents/_experts/bewerbungsexperte/cv_generator.py --output user/bewerbung/lebenslauf.txt
```

## LEISTUNGSKATALOG

### 1. CV-Generierung
- **Persoenliche Daten:** Aus assistant_user_profile lesen
- **Berufserfahrung:** Arbeitgeber-Ordner scannen (Zeugnisse, Vertraege)
- **Ausbildung:** Abschluesse-Ordner scannen
- **Fortbildungen:** Zertifikate-Ordner scannen
- **Referenzen:** Aus contacts (category: beruflich)

### 2. Stellendiagnose
- **Keyword-Matching:** Abgleich von CV mit Job-Requirements (ATS-Safe)
- **Unternehmens-Check:** Recherche zu Firmenkultur und Benefits

### 3. Unterlagen-Service
- **CV-Tuning:** Strukturierung und Pointierung von Erfahrungen
- **Anschreiben:** Erstellung von individuellen, ueberzeugenden Briefen
- **Portfolio:** Beratung zu Arbeitsproben und Referenzen

## ORDNERSTRUKTUR

Der CV-Generator erwartet folgende Ordnerstruktur:

```
user/
  karriere/
    _Arbeitgeber/
      Firma_A_2020-2023/
        Arbeitsvertrag.pdf
        Arbeitszeugnis.pdf
      Firma_B_2018-2020/
        ...
    _Abschluesse/
      Universitaet/
        Bachelor_Zeugnis.pdf
      Berufsausbildung/
        Ausbildungszeugnis.pdf
    _Fortbildungen/
      Zertifikat_Cloud_AWS_2024.pdf
      Fuehrungskraefte_Seminar_2023.pdf
```

## DATENBANK-TABELLEN

- `assistant_user_profile` - Persoenliche Daten (name, email, phone, address)
- `contacts` - Berufliche Kontakte/Referenzen (category='beruflich')
- `user_data_folders` - Pfade zu Karriere-Ordnern

## REGISTRIERUNG VON ORDNERN

```sql
INSERT INTO user_data_folders (folder_path, folder_type, description)
VALUES
  ('D:/Dokumente/_Arbeitgeber', 'career', 'Arbeitgeber und Zeugnisse'),
  ('D:/Dokumente/_Abschluesse', 'education', 'Schulische und berufliche Abschluesse'),
  ('D:/Dokumente/_Fortbildungen', 'certifications', 'Zertifikate und Weiterbildungen');
```

## CLI-OPTIONEN

```
--output, -o          Ausgabedatei (ansonsten stdout)
--career-path         Manueller Pfad zum Arbeitgeber-Ordner
--education-path      Manueller Pfad zum Abschluesse-Ordner
--certs-path          Manueller Pfad zum Fortbildungen-Ordner
--scan-folders        Automatisch user_data_folders scannen
```

## WORKFLOW: CV-GENERIERUNG

1. **Vorbereitung**
   - Persoenliche Daten in assistant_user_profile eintragen
   - Ordner in user_data_folders registrieren
   - Dokumente in Ordnerstruktur ablegen

2. **Generierung**
   - `python cv_generator.py --scan-folders`
   - Ausgabe pruefen und ggf. anpassen

3. **Export**
   - `python cv_generator.py --scan-folders --output user/bewerbung/cv.txt`

## SIEHE AUCH

- skills/workflows/cv-generierung.md - Detaillierter Workflow
- docs/CONCEPT_Bewerbungsexperte.md - Vollstaendiges Konzept

---
Status: AKTIV
Domain: Karriereberatung
