# Ticket- und Plan-Abgleich 2026-10-24

## Kopf

- **Task:** #3730 (Restauftrag aus #2461)
- **Worktree:** task-3730 (/Users/lukas/services/bach-worktrees/task-3730)
- **Status:** Teilstand
- **Verfasst:** 2026-10-25
- **Abgleichsstand:** 2026-10-24
- **Autoritäten:** Vertrag `docs/architecture/SHARED-GUI-KIT-AND-ORIGIN-CONTRACT-v1.md`; Plan `docs/BACH_OCEAN_GUI_SHARED_REPO_PLAN_2026-10-03.md`
- **Pfadnotiz (Abweichung):** Sollpfad `docs/BERICHTE/2026-10-25_Doku-und-Ticketabgleich/` ist nicht verfügbar – `docs/` enthält im Worktree nur die Ordner architecture, reviews, operations, i18n und video, einen BERICHTE-Ordner gab es nicht; OneDrive-Ablage zweimal gesperrt (file_info ~/OneDrive: 2× „nicht gefunden“). Ausweich: Ablage im **Worktree-ROOT** unter `TICKET-PLAN-ABGLEICH-2026-10-24.md`.

## a) W1 – Tickets 652455601, 387788448, 112086128 (Vertragskonformität SHARED-GUI-KIT)

- Vertrag :17: `ellmos-system-gui` ist die „Single Source of Truth“; Vertrag :18: `ellmos-universal-gui` ist der „Eigenständige Fallback“.
- GUX-002-Block Vertrag :55–65, Einzelzeilen :58, :60, :61, :63, :64, :65.
- **652455601:** Wrapper erledigt. Autorität: `docs/REVIEW-T652-SHELL-EXTRACTION-20260930.md` Zeile 5 – im Worktree einziger Treffer der Ticket-IDs, Abgleich damit quellengebunden bestätigt.
- **387788448:** Abdeckung system-gui „voll“ und universal-gui „schlank“ vertragskonform umgesetzt; die **Dateimarkierung** des Umsetzungsstands bleibt offen.
- **112086128:** offen; verknüpft mit #2337/RAM-Distributor, im Worktree keine Belege.
- **ASUS-GEI:** über `.gitignore`:168 außerhalb des Repos verwaltet, im Worktree nicht prüfbar.

## b) #2465 – Rename konsistent umgesetzt

- Rename vollzogen (Plan :18/:58): Repository zu `ellmos-ai/ellmos-universal-gui` umbenannt.
- Paketname bleibt (Plan :61/:63).
- `unified_gui` + Modul-/Capability-IDs kompatibel (Plan :17).
- Keine Astro-Duplizierung der Jinja-Quelle (Plan :60–61/:65).
- Kein Rückbau, keine Codeänderung nötig.
- Plan :17 (exaktes Blockzitat):

> „Das vorhandene `ellmos-ai/ellmos-unified-gui` wird als Repository zu `ellmos-ai/ellmos-universal-gui` umbenannt, damit Git-Historie, Issues, Releases, Stars und Beobachter erhalten bleiben. Sein Python-Paket `ellmos-unified-gui`, Importname `unified_gui` und vorhandene Modul-/Capability-IDs bleiben während der Konsumentenumstellung kompatibel. Der Anzeigename und die Rollenbeschreibung werden in README/Manifest berichtigt; seine Jinja-Quelle wird nicht mit Astro dupliziert. Rename erfolgt erst nach Altverweis-Inventur und gezieltem Update der Quellreferenzen. GitHub-Redirects ersetzen keine Paket- oder Actions-Migration.“

## c) W2 – Q1–Q7 („Neun Bereiche“)

- 0 Treffer im Worktree (grep „Neun Bereiche|Neun-Bereiche|Q1–Q7“); die Quellen liegen vermutlich in OneDrive und sind dort gesperrt.
- OCEAN-TRANSFER-PLAN.md, grep Q[1-7]: 0 Treffer; „Neun Bereiche“ dort nicht verortet.
- **Vermerk: Q1–Q7 NICHT zurückdrehen.** Punkt bleibt offen, solange keine Belege zugänglich sind.

## d) Existenzprüfung von Tickets

- Zu prüfen waren: #2060–#2067, #2070, #2465, #2479, #2480, #2482.
- `task_manage(list)` liefert nur [3730]; die Ticket-Existenz weiterer IDs ist mit dem vorhandenen Werkzeug (API-Mangel) nicht prüfbar. Nur dokumentiert, nicht bestätigt.

## e) Blocker OneDrive

- `file_info ~/OneDrive`: 2× „nicht gefunden“ (gesperrt). Berichtsablage und W2-Quellen dort nicht erreichbar.

## f) Korrektur zu OCEAN-TRANSFER-PLAN.md

- Datei ist **nicht leer**: 84 Zeilen, Stand 13.10.2026.
- Rückmodularisierung ab 13.10.2026, 64 Folgeaufgaben.
- v3.15.0 „BACH meets Ocean – BACH fließt ins Meer“, policy-registry-Ersttransfer.
- 0 Treffer für Q[1-7].

## Fazit / offene Punkte

1. **387788448:** Dateimarkierung offen.
2. **W2:** Q1–Q7 offen, NICHT zurückdrehen; Quellen vermutlich OneDrive (gesperrt).
3. **Ablage:** Bericht liegt im Worktree-ROOT statt in `docs/BERICHTE/2026-10-25_Doku-und-Ticketabgleich/` (Pfadabweichung, OneDrive gesperrt).
4. **Existenzprüfung** weiterer Ticket-IDs (#2060–#2067, #2070, #2479, #2480, #2482) via API nicht möglich.
5. **112086128** (mit #2337/RAM-Distributor) offen.