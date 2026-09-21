# Wiki-Autor Report: versicherungen — Schadensmanagement
**Datum:** 2026-09-18 · **Task:** #1331 · **Workflow:** skills/workflows/wiki-author.md (Modus A) · **Agent:** Claude

## 1. Agenten-Auswahl
- **Gewählt:** `agents/versicherungen` (v1.1.0, aktiv, zuletzt geändert 18.09.)
- **Begründung:** Kein Eintrag im Wiki-Author-Log (letzte Abdeckungen:
  word_template_service 17.09., skills_board/claude_code_memory 16.09.,
  reflection 12.09. — alle keine Versicherungs-Domain)
- **Profil:** Versicherungsmanagement, Vertragsanalyse, Bedarfsermittlung,
  Schadensmanagement (3 Kernkompetenzen)

## 2. Gap-Analyse (Ordner finanzen_versicherungen/, 9 Artikel vorhanden)
| Wissensbereich | Im Wiki? | Priorität |
|----------------|----------|-----------|
| Versicherungssparten-Übersicht | Ja | – |
| Bedarfsanalyse | Ja | – |
| **Schadensmanagement/Regulierung** | **Nein** | **HOCH** |
| Kündigungsfristen/Vertragswechsel | nur erwähnt | MITTEL (Follow-up) |

Gewähltes Thema: **Schadensmanagement** — Kernkompetenz 3 des Agenten
(Meldung, Ansprüche, Eskalation) hatte keinerlei Wiki-Unterfütterung;
ohne dieses Wissen ist die Agent-Aufgabe nicht arbeitsfähig (Kriterium „Hoch").

## 3. Web-Recherche (Primärquellen, live verifiziert 2026-09-18)
1. **§ 31 VVG** (gesetze-im-internet.de): Auskunftspflicht nach Schadensfall —
   jede erforderliche Auskunft + zumutbare Belege; gilt auch für Dritte (Abs. 2)
2. **§ 14 VVG** (gesetze-im-internet.de): Fälligkeit nach Beendigung der
   Erhebungen; **Abschlagszahlungen verlangbar ab 1 Monat nach Anzeige**
   (Abs. 2); Verzugszinsen-Ausschluss unwirksam (Abs. 3)
3. **§ 195 BGB** (gesetze-im-internet.de): reguläre Verjährung 3 Jahre
4. **Versicherungsombudsmann** (versicherungsombudsmann.de): anerkannte
   Verbraucherschlichtungsstelle (VSBG), neutral, **verbindliche Entscheidung
   bis 10.000 EUR Beschwerdewert**, darüber Empfehlung; Verbraucher nicht
   gebunden (Gerichtsweg offen)

### Korrigierte/verifizierte Missverständnisse (warum Primärquellen!)
- **§ 12 VVG ist NICHT die Verjährung** — dort steht die Versicherungsperiode.
  Die 2-Jahres-Regel war VVG 1908; heute gilt BGB (3 Jahre). Im Artikel als
  explizite Warnung dokumentiert (Verwechslungsrisiko für LLM-Antworten).
- Ombudsmann-Höchstbetrag: veraltet wären 100.000 EUR; aktuell 10.000 EUR
  verbindlich (Quelle 2026-09-18 abgerufen).

## 4. Artefakte
- **Neu:** `wiki/finanzen_versicherungen/schadenmanagement.txt` (6,3 KB)
  — 5-Phasen-Ablauf, Obliegenheiten, 3-Stufen-Eskalationsplan,
  Fristen-Schnellreferenz, BACH-Integration (Mapping auf Agent-Kompetenz 3),
  Haftungshinweis
- **Aktualisiert:** `wiki/finanzen_versicherungen/_index.txt` (Eintrag im
  Abschnitt VERSICHERUNGEN)
- Format konform zu wiki_konventionen.txt: Portabilität UNIVERSAL,
  Validierungsmetadaten, Quellenangabe, nächste Prüfung 2027-09-18

## 5. Offene Lücken für spätere Durchläufe
- Kündigungsfristen/Vertragswechsel/Sonderkündigungsrecht (Priorität M)
- Sparten-Gutachterwesen (Haus & Buch, Medizin) — für große Schäden
- Aktualisierungen der 9 Bestandsartikel (Naechste-Pruefung-Daten
  teils überfällig, z.B. bach_versicherungs_modul: 2026-07-28)

## 6. Status
Task #1331: **done** · Commit folgt mit CHANGELOG-Eintrag.