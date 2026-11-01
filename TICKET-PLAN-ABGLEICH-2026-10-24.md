# TICKET-PLAN-ABGLEICH-2026-10-24 – Teilstandsbericht zu Task #2461

**Hinweis:** Diese Datei ist eine flache Arbeitskopie im Task-Worktree-Root, da der kanonische Ablageort `OneDrive/Desktop/OCEAN/BERICHTE/2026-10-25_Doku-und-Ticketabgleich/TICKET-PLAN-ABGLEICH-2026-10-24.md` im gebundenen Lauf gesperrt ist (Task-Fence: OneDrive-Lesepfade blockiert; Schreibpfade unter docs/ wurden nicht bestätigt). Nach Freigabe ist der Inhalt dorthin zu überführen.

**Stand:** 25.10.2026, Task-Worktree `/Users/lukas/services/bach-worktrees/task-2461`, Vorläufer-Teilstand vom 01.11.2026 (complete=false), Commit-SHA `e9307a8c`.

## W1-Entscheidungen (Nutzer, 25.10.2026 – verbindlich, NICHT zurückdrehen)

- **T-20260926-652455601 → abgelöst durch Wrapper:** Ablösung durch die GUI-Ticket-Nachfolgearbeit (ellmos-system-gui) gilt als erledigt; das alte Ticket ist als abgelöst zu kennzeichnen.
- **T-20260926-387788448 → Wahlregister:** Nachfolger sind das Wahlregister (ellmos-system-gui, vollständig) sowie ellmos-universal-gui (schlank).
- **T-20260926-112086128 → bleibt bestehen:** Ticket bleibt aktiv, hängt an #2337 und dem RAM-Distributor; Umbenennung läuft als eigene Task #2465.

## W2-Entscheidung (Neun-Bereiche-Layout)

W2 ist offen; das Neun-Bereiche-Layout ist gegen die Bereiche Q1–Q7 weiterzuführen und **nicht zurückzudrehen**. Real-Nachfolger-Tickets: #2479 (Nachrichten), #2480 (Memory/Architektur), #2482 (Notizen/Life).

## Lücken-Tasks (angelegt am 25.10.2026 per task_manage add, Quelle: Ticket-/Planabgleich)

- **#3721** (P2): BACH-CI – 121 Testdateien liegen außerhalb der CI, 6 rot; CI-Abdeckung herstellen und rote Tests fixen.
- **#3722** (P3): DB-Stufen S3/S4/S6/S7 – fehlende Stufen dokumentieren/umsetzen.
- **#3723** (P2): `migrate_unify_distribution.sql` löscht `instance_identity` (T-20260926-357988320); Migration fixen.
- **#3724** (P2): Lock-Auswerter – Unicode-False-Clear (T-20261024-533036158) korrigieren.
- **#3725** (P3): ocean-dev Installer – Installation/Aufruf bereitstellen.
- **#3726** (P3): Task-Listen-API kappt bei 200 Einträgen; Paginierung/Limit heben.
- **#3727** (P3): OpenRouter-404 – Endpunkt/Fehler untersuchen und beheben.
- **#3728** (P2): Nutzerhandlung ellmos-multi-bot – Berechtigung „Pull requests: write“ (T-20261018-552477816, T-20261018-422571861) durch den Nutzer setzen.
- **#3729** (P3): GitHubBot-OCEAN Issues #2060–#2067 prüfen und in Tasks überführen (deckt den Issue-Block des Abgleichs ab).
- **#3730** (P2, Resttask): W1/W2-Ticket-Kennzeichnung in OneDrive, Wrapper-Fortschreibung (T652/T797), Verifikation der fremden Task-IDs #2060–#2067/#2070/#2465/#2479/#2480/#2482, kanonischer Bericht auf OneDrive, Freigabe OneDrive-Lesebereich.

## Nicht erfolgt in diesem Lauf

- **W1/W2-Kennzeichnung der GUI-Tickets:** NICHT durchgeführt. OneDrive ist im Task-Fence gesperrt, kein Ticketinhalt lesbar; die ASUS-GEI-Ticketdateien (`*-ASUS-GEI.*`) lagen nie im Worktree (nur `.gitignore:168` erwähnt sie). → Resttask #3730.
- **Wrapper-Fortschreibung:** NICHT erfolgt. Im Worktree fand die Wrapper-Suche nur einen Autoritäts-Treffer ohne Inhalt (`docs/REVIEW-T652-SHELL-EXTRACTION-20260930.md:5`); T652/T797 blieben unbezogen.
- **Verifikation fremder Task-IDs** (#2060–#2067, #2070, #2465, #2479, #2480, #2482): Im gebundenen Lauf ist `task_manage detail` nur für die eigene ID lesbar; Existenz ist unverifizierbar. #2070 wurde deshalb nicht neu angelegt. → Resttask #3730.

## Freigabebedarf (an Controller/Nutzer)

OneDrive-Lesebereich für den gebundenen Lauf, damit #3730 durchführbar wird:

- `OneDrive/Desktop/OCEAN/AKTUELLER-PLAN.md`
- `OneDrive/Desktop/OCEAN/TEILPLAN-GUI-ANBINDUNG-2026-10-25.md`
- `OneDrive/Desktop/OCEAN/GUI-DURCHGANG-2026-10-25.md`
- `OneDrive/Desktop/OCEAN/ANFORDERUNGEN-DETAIL.md` (Abschnitte „Dokumentation“/„Ticket-Abgleich“)
- QUEUED-Tickets in `OneDrive/.TOPICS/_control-center/_TICKETS`
- Schreibzugriff auf `OneDrive/Desktop/OCEAN/BERICHTE/2026-10-25_Doku-und-Ticketabgleich/`

Vorschlag: z. B. CLAUDE-Slot mit OneDrive-Recht für #3730.

## Vorerfahrungen / Sackgassen

- `create_directory` für `docs/BERICHTE/2026-10-25_Doku-und-Ticketabgleich` blockiert („Task-Verzeichnispfad nicht bestätigt“); verschachtelte Neupfade per `write_file` ebenso blockiert; auch der flache Dateiname unter `docs/` wurde nicht als Schreibpfad bestätigt → Bericht daher flach im Worktree-Root abgelegt.
- `list_directory` auf `/Users/lukas/services/bach-worktrees` blockiert („Task-Lesebereich nicht bestätigt“); OneDrive-Desktop/OCEAN- und `.TOPICS/_TICKETS`-Pfade blockiert.
- „Wrapper“-Suche im Worktree: 15s-Suchtimeout, 8388608-Byte-Limit; nur der Autoritäts-Treffer oben.
- `backups/` enthält nur `.gitkeep`, `_codex/` nur Review-/Auftragsdokumente – dort keine Ticketdateien.
- Maßgebliche Quellen: `OneDrive/Desktop/OCEAN/ANFORDERUNGEN-DETAIL.md` („Dokumentation“/„Ticket-Abgleich“); QUEUED-Tickets in `OneDrive/.TOPICS/_control-center/_TICKETS`.