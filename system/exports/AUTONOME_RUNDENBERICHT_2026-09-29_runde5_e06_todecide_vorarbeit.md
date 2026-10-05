# Autonomer Rundenbericht – Runde 5 (29.09.2026)

**Thema:** E06-Vorarbeit – lesende Klärung der TO-DECIDE-Punkte A–D aus `data/E06_scan_befund.md` (Task #1569, Parallel-Session)
**Runde:** 5 | **Zeit:** 29.09.2026, ~09:40 Uhr | **Modus:** Standard-Runde
**Charakter:** Lesende Vorarbeit – KEINE Änderungen an Code/Config vorgenommen.

---

## 1. Auftrag und Kontext

Fortsetzung der offenen Arbeit an E06 (Alt-Pfad-Stilllegung, Task #1568/#1569). Der Scan-Befund
`data/E06_scan_befund.md` (296 Alt-Pfad-Treffer in 136 Dateien; pytest: 61 passed) enthielt vier
offene TO-DECIDE-Punkte A–D, die durch lesende Verifikation (list_directory, search_text, safe_shell)
geklärt werden sollten, bevor die USER-Freigabe für `--apply` eingeholt wird.

E04/E07-Liefercheck wurde zuletzt 09:33 negativ durchgeführt und ist hier aktualisiert (s. Abschnitt 2).

## 2. E04/E07-Liefercheck (aktualisiert 09:40)

`find -mmin -30 -type f` über die 4 Lieferpfade – Ergebnis: **alle leer / negativ**.

| Pfad | Ergebnis (09:40) |
|---|---|
| /Users/lukas/Downloads | leer |
| /Users/lukas/MailProcessor | leer |
| /Users/lukas/Desktop | leer |
| /Users/lukas/transit | leer |

**Fazit:** E04-Dateien (T-20260902-294356643) und E07-CAMT (T-20260902-162225801) sind weiterhin
**nicht abgeliefert**. Ask bleibt bestehen (s. Abschnitt 6). Bisherige Suchen (Downloads, Desktop,
OneDrive-Spiegel, transit, MailProcessor, BACH-Root, DB-Logs) fanden die Dateien mehrfach nirgends.

## 3. Ergebnisse zu TO-DECIDE A–D

### A) `exports/translations/` – Backup-Dateien (Duplikatverdacht) → VERDACHT BESTÄTIGT
- Verzeichnis enthält **10 `backup_identical_*.json` vom 2026-09-15** – Sessions der
  Übersetzungs-Heilung #1298 (Beleg: `fix_1298_run.log` in diesem Ordner).
- Mehrere Dateien **exakt paarweise identische Größen**: en 798/798, en_helpdoc 2104/2104,
  en_helpdoc 53238×3 → Duplikatverdacht bestätigt.
- **Empfehlung:** Backups als veraltete Duplikate ignorieren bzw. löschen – **USER-Entscheidung**
  (nicht Teil der E06-Stilllegung; separat entscheiden).

### B) help-Migration & „system/exports"-Notation → VALIDIERT
- `help/` ist **physisch WEG**; `docs/help/` **EXISTIERT** (viele `*.txt` in de/en/es/ja/ru/zh)
  → help-Migration (system/help/wiki/ → system/wiki/) validiert.
- `exports/` ist physisch vorhanden (Root/exports mit translations/ + Rundenberichten).
  **„system/exports" ist kanonische Notation desselben Ordners** (Notation vom Services-Root,
  NICHT Root-relativ – s. Abschnitt 8, Sackgassen).
- Preview-Ersetzungen des Dry-Runs betreffen nur: `docs/memory_routing_mapping.md` 1×,
  `tests/test_tuev_handler.py` 6×, `tests/test_context_injector_db.py` 2×
  → **kein produktiver Runtime-Code betroffen.**
- **Empfehlung:** Guarded Ersetzungen sind validiert; die **9 Stellen vor `--apply` manuell reviewen**.

### C) `skills/_partners` → MIGRATION, NICHT ENTFERNUNG
- Echte Pfad-Treffer: `system/bach_legacy.py:78` (**PARTNERS_DIR = SKILLS_DIR/"_partners" – aktiver Code!**),
  `tools/skill_header_gen.py:86`, `tools/doc_update_checker.py:75-76`
  (= Mechanismus-Tupel, **BEHALTEN** bis Nullreferenznachweis; Abbau läuft über #1358-Gate).
- Alle übrigen search-Treffer sind **false positives** (active_partners/allowed_partners/
  applicable_partners/test_partners) – zählen nicht.
- `partners/` existiert (claude/, gemini/, ollama/, partner_config.json) → Migration ist
  physisch abgeschlossen; Referenz in `bach_legacy.py` muss vor Stilllegung behoben werden.
- **Empfehlung:** Migration statt Entfernung; `bach_legacy.py:78` vor/nach Apply nachziehen,
  Mechanismus-Tupel ausdrücklich aus der Stilllegung ausnehmen.

### D) `system/config/` → SEPARATES REFACTORING-DOKUMENT: JA
- Treffer nur in Scan-Artefakten (agg_out.txt:174, healing_report.json:291, Befund, Berichte)
  + DB-Protokoll: „system/config/ enthält nur db_sync_enabled, gehört definitiv in system/data/".
- **Empfehlung:** Separates Refactoring-Dokument anlegen (Verschiebung db_sync_enabled nach
  system/data/), `system/config/` **aus der E06-Stilllegung ausnehmen**.

## 4. Referenz: Offizielle Stilllegungsliste (8 Mappings)

Aus DB (bach.db, Quelle T-20260902-529112294), identisch mit `prep/E06_altpfad_stilllegung_checklist.md` §2:

1. skills/_agents/ati/ → agents/ati/
2. skills/_agents/ → agents/
3. skills/_connectors/ → connectors/
4. skills/_experts/ → agents/_experts/
5. skills/_workflows/ → skills/workflows/
6. skills/_partners/ → partners/
7. system/help/wiki/ → system/wiki/
8. scripts/ → tools/ (nur Doku)

**Trefferklassifikation:**
- (a) **Doku = Stilllegungsfläche:** docs/memory_routing_mapping.md Z.11
- (b) **Mechanismus = BEHALTEN:** doc_update_checker.py 63-75, doc_path_updater.py 107-112+139,
  path_healer.py 109-114+141

## 5. Zusammengefasste Empfehlungen an USER

| TO-DECIDE | Empfehlung |
|---|---|
| A) backup_identical_*.json | Als veraltete Duplikate ignorieren/löschen – USER-Entscheidung |
| B) Preview-Ersetzungen (9 Stellen) | Validiert; vor Apply manuell reviewen, dann freigeben |
| C) skills/_partners | Migration, nicht Entfernung (bach_legacy.py:78 ist aktiver Code); Mechanismus behalten |
| D) system/config/ | Separates Refactoring-Dokument; aus Stilllegung ausnehmen |
| Zusatz | skills/_services: eigene Migration, NICHT Teil der Stilllegung (bewusst nicht angefasst; 107 Treffer/51 Dateien) |

## 6. Asks (Fortbestehen – bitte beantworten)

1. **E04/E07-Dateien:** E04-Dateien (T-20260902-294356643) und E07-CAMT (T-20260902-162225801)
   senden oder Pfad nennen. (Liefercheck 09:33 und 09:40 über 4 Pfade: negativ.)
2. **E06-Freigabe (Task #1568):**
   - A/B-Entscheidung zu den Fragen 1 & 4 aus #1568,
   - Bestätigung: `python3 tools/maintenance/e06_path_deprecation_dryrun.py --apply --confirm`,
   - Entscheidung zu TO-DECIDE A–D (Empfehlungen s. Abschnitt 5),
   - Empfehlung skills/_services: eigene Migration, NICHT Teil der Stilllegung.
3. **Operator-RDP für #1250** (Handoff #1253): WORKSTATION-LG.local = 192.168.9.129, Ports
   135/445/3389 offen. Danach: 110 passed → #1251/#1243 freigeben.

## 7. System- und Taskstatus (geprüft)

- **Offene Tasks:** nur #1463/#1462/#1424/#1250 – alle USER/OPERATOR-gated, aus dieser Runde
  nicht autonom entscheidbar.
- **maintain check:** 11 Checks ✅; nächster fälliger Check: 2026-10-01.
- **Parallel-Session-Tasks** #1569/#1568/#1370/#1367/#1368/#1371: nicht angefasst.
- Für TO-DECIDE wurden **keine Tasks angelegt** (im Befund dokumentiert).

## 8. Sackgassen & Hinweise für die nächste Runde

- **Tool-Basis für relative Pfade** = `/Users/lukas/services/bach/system/` (= BACH-Root).
- „system/exports" als relativer Pfad → Root/system/system/exports existiert **nicht**;
  die Notation ist vom Services-Root aus gemeint.
- Richtiger Befund-Pfad: `data/E06_scan_befund.md` (nicht system/data/…).
- **safe_shell:** keine Tilde-Expansion, kein `2>/dev/null`, kein pwd, keine Verkettung –
  Delivery-Check immer als 4 separate find-Aufrufe.
- search_text „_partners" matcht false positives (active_/allowed_/applicable_/test_partners) –
  nur echte Pfad-Treffer zählen.
- skills/_services: bewusst nicht anfassen (aktiver Skill-Ort).
- E04/E07-Dateien: nie abgeliefert (alle Suchorte negativ).

## 9. Nächste Schritte

Diese Runde ist mit dem vorliegenden Bericht **abgeschlossen**. Ausstehend ist ausschließlich die
USER-/OPERATOR-Entscheidung zu den Asks in Abschnitt 6. Sobald die E06-Freigabe (TO-DECIDE A–D,
Fragen 1 & 4, `--apply --confirm`) vorliegt, kann die Stilllegung angewendet werden (ggf. Runde 6:
9 Preview-Stellen reviewen → apply → pytest 61 passed verifizieren → Rundenbericht).

---
*Autonom erstellt am 29.09.2026, ~09:40 Uhr – Runde 5, E06 lesende Vorarbeit (Task #1569, Parallel-Session).*