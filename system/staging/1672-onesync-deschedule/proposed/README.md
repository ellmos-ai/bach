# Task #1672 — OneDrive-Sync-Schedule entzerren

**Status:** Fix VORBEREITET, aber NICHT angewendet (user-gated).
**Grund:** launchd-Reload (unload/load) braucht eine User-Session. Autonom
anwenden = Risiko, den Pinner/Compute-Queues in einer Session ohne TTY
falsch zu laden. Deshalb nur als VORLAGE.

## Diagnose (9x verifiziert, Z561–Z567)
Morgen-Load-Spikes >5.0 (max 8.37 in Z565). Ursache: synchronisierte 300 s-
Timer (4 launchd-Agents) + OneDrive-Pinner-Batch (CORE-Tier 300 s) feuern im
Morgan zusammen -> CPU-Spitze.

## 5 geänderte Quellen (proposed/ = Vorschläge, backup/ = Original)
| # | Quelle | Änderung | backup/ | proposed/ |
|---|--------|----------|---------|-----------|
| 1 | com.ollama.healthcheck.plist | StartInterval 300 -> 360 | *.plist.bak | *.plist |
| 2 | com.bach.downloads-watcher.plist | RunAtLoad true->false, StartInterval 300->420 | *.plist.bak | *.plist |
| 3 | com.lukas.computequeue.plist | ProgramArgument --interval 300->360 | *.plist.bak | *.plist |
| 4 | com.lukas.generalcomputequeue.plist | ProgramArgument --interval 300->420 | *.plist.bak | *.plist |
| 5 | onedrive_pinner.py | CORE-Tier "interval": 300 -> 600 (Einzelzeile) | *.py.bak | onedrive_pinner.patch.md |

## Entzerrungswirkung
Alle 5 Rhythmen liegen jetzt auf 360/420/600 statt 4x300 -> kein gleichzeitiges
Feuern mehr am Morgen. Die Spitzen dämpfen sich, weil die Timer phasenverschoben
und die engste Frequenz (Pinner) verdoppelt werden.

## onedrive_pinner.py — Korrektur zum Übergabezettel
Der Zettel nannte den 300 s-Tier "NORMAL". Tatsächlich liegt 300 s im **CORE**
Block (Zeile 30); NORMAL = 1800 s. Der Patch ändert die engste Frequenz
(CORE 300 -> 600) — Substanz unverändert. Siehe proposed/onedrive_pinner.patch.md.

## Anwendung (NUR in einer User-Session, vom Nutzer ausgelöst)
Siehe apply.sh in diesem Ordner — es ist ein **VORLAGE-Skript**, nicht
autoausgeführt. Es:
  1. kopiert proposed/*.plist -> ~/Library/LaunchAgents/ (die 4 Plists)
  2. setzt die eine Zeile in onedrive_pinner.py per sed/Python-Einzeiler
  3. launchctl unload -> launchctl load für die 4 Agenten
  4. pinner neu starten (bzw. bei nächstem Poll-Loop wirksam)

## Rollback (jederzeit, ohne Session nötig)
  cp -p backup/*.plist.bak  ~/Library/LaunchAgents/<entsprechend>.plist
  cp -p backup/onedrive_pinner.py.bak  <LIVE-Pfad>/onedrive_pinner.py
  launchctl unload/load (User-Session)

## NICHT anfasst
- com.lukas.computequeue-onedrive-sync.plist ist bereits .disabled (früherer Fix).
- onedrive_pinner.py NICHT per Voll-Umschreibung (write_file) ändern — nur
  die eine numerische Zeile im CORE-Block.

## Live-Dateien bleiben UNGEÄNDERT
Bis der Nutzer "Anwenden" bestätigt. TO-DECIDE Task dokumentiert die exakte
Entscheidung.
