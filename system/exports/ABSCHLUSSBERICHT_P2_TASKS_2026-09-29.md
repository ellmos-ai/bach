# Abschlussbericht: Autonome Abarbeitung offener BACH-P2-Tasks

**Datum:** 2026-09-29
**Auftrag:** 13 offene P2-Tasks (#1549, #1537, #1536, #1463, #1462, #1424, #1371, #1370, #1368, #1367, #1359, #1358, #1250) auf autonom bearbeitbare Anteile prüfen und ggf. abarbeiten.

## Kernbotschaft

**0 von 13 Tasks autonom abschließbar.**

| Kategorie | Anzahl | Tasks |
|---|---|---|
| USER-Entscheidung nötig | 9 | #1549, #1537, #1536, #1424, #1371, #1370, #1368, #1367, #1359 |
| Hart BLOCKED | 2 | #1358, #1250 |
| USER-gebunden (Dateien fehlen) | 2 | #1463, #1462 |

## Task-für-Task-Befund und Empfehlung

| Task | Thema | Befund (2026-09-29) | Konkrete Empfehlung / Nächster Schritt |
|---|---|---|---|
| #1549 | Vision Backend-Fallback | USER-Entscheidung; Quelldokument fehlt | USER legt Quelldokument/Entscheid vor; danach Umsetzung delegierbar |
| #1537 | CAP-1.3 (finance_assist) | `finance_assist` nicht in bach.git auffindbar; `folderhome/services/contract_store.py` existiert nicht (kein Branch, keine History) | USER benennt Ziel-Repo/Speicherort **oder** stellt Task zurück (P4/Archiv) |
| #1536 | CAP-2.3 | `tools/ocean/k9_boundary/action_journal.py` existiert (in bach.db verzeichnet); Blocker: open-ocean ist bare Mirror ohne Worktree, NemoFold-Repo leer | USER entscheidet: Code nach `tools/ocean/k9_boundary/` in bach.git statt open-ocean? Danach autonom umsetzbar |
| #1463 | Export-Dateien | USER-Task; reale Export-Dateien fehlen | USER stellt Dateien bereit oder gibt Mock/Fixture frei |
| #1462 | CAMT-Import | USER-Task; reale CAMT-Dateien fehlen | USER stellt CAMT-Dateien bereit oder gibt Testdaten frei |
| #1424 | Nutzer-Briefing | USER-Task, hängt an externem Briefing | Briefing abwarten; kein autonomer Anteil |
| #1371 | Reifegate-Abnahme (#1207) | mem-Index: keine Treffer für "Reifegate"; TO-DECIDE-USER.txt existiert nicht im Repo; DECIDED-AND-DONE.md (nur `hub/_services/trithon/`) ohne Treffer zu 1207/Reifegate | USER legt Reifegate-Nachweis/Receipts vor **oder** erklärt Gate für entfallen. Zentraler Blocker (s.u.) |
| #1370 | USER-Entscheid | Nicht autonom entscheidbar | In USER-Session entscheiden (TO-DECIDE-Liste) |
| #1368 | USER-Entscheid | Nicht autonom entscheidbar | In USER-Session entscheiden (TO-DECIDE-Liste) |
| #1367 | USER-Entscheid | Nicht autonom entscheidbar | In USER-Session entscheiden (TO-DECIDE-Liste) |
| #1359 | BACH20-11 Reifegate | `depends_on`: #1357 (in_progress, blockiert durch #1341) + #1358 (blocked). Kann nicht anschaltbar gemacht werden | Pending lassen; automatisch prüfbar sobald #1357 + #1358 done. Wurzel der Kette: **#1341** zuerst lösen |
| #1358 | BACH20-09 | Hart BLOCKED: blocked via #1357 (blockiert durch #1341); Removal-Gate — **nicht autonom bearbeiten** | Nicht anfassen. Wartet auf #1357. Freigabe nur durch USER nach Gate-Prüfung |
| #1250 | WORKSTATION-LG | Hart BLOCKED: reine Operator-Abhängigkeit, WORKSTATION-LG nicht erreichbar; keine lokale Lösung möglich | Operator stellt Netz-/Erreichbarkeit her; danach Task erneut prüfen |

## Kritischste Blocker (Priorität für USER)

1. **#1359 (BACH20-11 Reifegate):** Abhängigkeitskette #1341 → #1357 → #1358 → #1359 blockiert den BACH20-Abschluss. Hebel: #1341 zuerst angehen.
2. **#1358 (BACH20-09):** Durch Removal-Gate geschützt — autonome Bearbeitung ausdrücklich verboten. USER muss Gate-Status prüfen/freigeben.
3. **#1250:** Operator-Abhängigkeit (WORKSTATION-LG unerreichbar). Lokal nicht lösbar.

## Konkrete Next Steps

**Für USER-Session (Entscheidungen):**
1. #1536: Ziel-Repo festlegen (Vorschlag: bach.git, `tools/ocean/k9_boundary/`) → danach autonom umsetzbar
2. #1537: Repo für `finance_assist` benennen oder Task zurückstellen
3. #1549: Quelldokument für Vision Backend-Fallback liefern
4. #1367, #1368, #1370: Entscheidungen treffen
5. #1371: Reifegate-Nachweis vorlegen oder Gate #1207 für entfallen erklären
6. #1341 (Wurzel der BACH20-Blockerkette) bearbeiten/entscheiden

**Für USER (Bereitstellung):**
7. #1463: reale Export-Dateien; #1462: reale CAMT-Dateien
8. #1424: Nutzer-Briefing

**Für Operator:**
9. #1250: WORKSTATION-LG erreichbar machen

## Sackgassen / verifizierte Negative

- mem-Index enthält keine Treffer zu "Reifegate" (Index-Lücke oder Namensabweichung möglich)
- TO-DECIDE-USER.txt existiert nicht im Repo
- T-20260728-12 existiert nicht als Datei, nur Zirkelreferenz in ROADMAP.md
- `finance_assist` / `contract_store.py`: nur bach.db-Befundtexte, kein Code
