# Ticket-Entwurf: Claim-Änderungen an ticket-master melden statt auf den Desktop legen

> Entwurf für ein Ticket im externen ticket-master-Ökosystem (taskplan-Paket, OneDrive).
> Erarbeitet im BACH-Task #2560; die Umsetzung liegt vollständig extern (nicht im BACH-Repo).

## Metadaten

- **Vorgeschlagene Ticket-ID:** `T-20261025-XXXXXXXX` – endgültige ID vergibt das ticket-master-System; Format `T-YYYYMMDD-XXXXXXXX` gemäß ROADMAP.md:916 (Beispiel: T-20260920-829000873).
- **Ablageort:** `_control-center/_TICKETS/` (Auflösung über den Lebenszyklusordner gemäß ticket-master-Ökosystem, ROADMAP.md:894-921 „Routing v2").
- **Datum des Nutzerentscheids:** 25.10.2026
- **Herkunft:** BACH Task #2560
- **Umsetzungsort:** externes taskplan-Paket / OneDrive; BACH bindet ticket-master nur lesend-spiegelnd über die Taskplan-Bridge ein (`legacy_only`, `manual_mirror_import_only`), daher kein Ticket-Schreiben über die BACH-Bridge.

## Problemstellung

Claim-Änderungen werden bislang als Datei auf den Desktop gelegt, statt als Ticket gemeldet zu werden. Die Recherche im BACH-Repo (Task #2560) ergab: Die Quelle der Desktop-Ablage ist im BACH-Repo nicht auffindbar – sie liegt extern. Die relevanten Live-Pfade des ticket-master sind `lib/ticket_writer.py` und `lib/systems_registry.py` (Routing v2, `--systems-registry`) in OneDrive, nicht im BACH-Repo. Das externe taskplan-Paket startet ticket-master über die Agent-Starter (`import taskplan.startcenter`; `python -m taskplan startcenter --role ticket-master`, siehe `start/agents/windows/TICKET-MASTER.bat` und `start/agents/posix/ticket-master.sh`).

## Anforderungen (Nutzerentscheidung vom 25.10.2026)

1. **Je Claim-Änderung ein Ticket**, mit: betroffenem Projekt, altem Wortlaut, neuem Wortlaut, Fundstelle (Quelle/Stelle) und Anlass der Änderung.
2. **Benachrichtigung** an Lukas oder den persönlichen Assistenten bei jeder Claim-Änderung.
3. **Keine Desktop-Kopie mehr** – die Ablage einer Kopie auf dem Desktop entfällt vollständig.

## Offene externe Umsetzungsschritte

1. Die Automation im taskplan-Paket identifizieren, die bisher die Desktop-Datei erzeugt.
2. Auf `lib/ticket_writer.py` umstellen (Ticket-Routing v2 mit `--systems-registry` über `lib/systems_registry.py`).
3. Die Benachrichtigung an Lukas bzw. den persönlichen Assistenten anbinden.
4. Die Desktop-Ablage entfernen.
5. **Abnahmekriterium:** Je Claim-Änderung entsteht genau ein Ticket im Format `T-YYYYMMDD-XXXXXXXX` in `_control-center/_TICKETS/` **plus** eine Benachrichtigung an Lukas oder den persönlichen Assistenten – **statt** einer Desktop-Datei.

## Beleglage (BACH Task #2560)

- `start/agents/windows/TICKET-MASTER.bat` und `start/agents/posix/ticket-master.sh`: ticket-master läuft im externen taskplan-Paket.
- `docs/MODELL-BACKEND-KONZEPT_2026-09-13.md:584-586`: Live-Pfade `lib/systems_registry.py`, `lib/ticket_writer.py` (Routing v2) – extern in OneDrive, nicht im BACH-Repo.
- `ROADMAP.md:894-921`: Ticket-Routing-Vertrag „Routing v2", Tickets in `_control-center/_TICKETS/`, ID-Beispiel T-20260920-829000873.
- `system/hub/_services/taskplan_bridge.py:335-357`: BACH-Bridge nur lesend/spiegelnd (`legacy_only`, `automatic_write_mirror` False, `taskplan_role manual_mirror_import_only`); Ticket-Schreiben über die Bridge wäre ein Vertragsbruch.
- Recherche im BACH-Repo (`ticket_writer`, `systems_registry`, Desktop-/Schreibtisch-Muster): keine Desktop-Ablage-Quelle gefunden – Ursache liegt extern.

## Referenzen

- OneDrive: `.TOPICS/_control-center/_CONTROL/_PLANS/AUTOMATISIERUNG-2027.md`, Agenda A8
- OneDrive: `_USER-MIND/avatar/USER.md`, Abschnitt „Automatisierungsgrad“
- BACH Task #2560