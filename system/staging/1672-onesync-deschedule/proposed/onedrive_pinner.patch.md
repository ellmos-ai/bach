# Patch: onedrive_pinner.py — Entzerren des engsten Pinner-Timers (Task #1672)

## Zweck
Morgen-Load-Spikes >5.0 dämpfen. Die engste Pinner-Frequenz (300 s = 5 Min)
triggert im 60 s-Poll-Loop (Zeile ~231 `for _ in range(60): time.sleep(1)`)
alle ~3 Minuten einen Sync-Batch. Zusammen mit den 4 synchronisierten 300 s-
launchd-Timetern (healthcheck, downloads-watcher, computequeue, generalcomputequeue)
erzeugt das eine Lastspitze. Wir lösen den engsten Timer auf 600 s (10 Min) auf.

## WICHTIGE KORREKTUR zum Übergabezettel
Der Zettel nannte den 300 s-Tier "NORMAL". Tatsächlich ist im Code:
  - CORE  = 300 s  (Zeile 30)  <- die engste Frequenz, die wir entzerren
  - NORMAL= 1800 s (Zeile 38)
  - LOW   = 7200 s (Zeile 48)
Die zu ändernde Zeile ist also im **CORE**-Block (nicht NORMAL).
Die Substanz der Maßnahme (300 s -> 600 s beim engsten Timer) ist unverändert.

## Einzelzeilen-Patch (NICHT die ganze Datei umschreiben!)

Suche (exakt, inkl. Kommentar):
         "interval": 300,    # 5 min

Ersetzen durch:
         "interval": 600,    # 10 min (entzerren T1672)

Der Anchor "# 5 min" ist in der Datei eindeutig (nur diese Zeile trägt ihn),
daher ist ein gezielter Einzeiler-Replace sicher.

## Diff-Äquivalent (unified, Referenz)
--- onedrive_pinner.py (CORE-Block)
+++ onedrive_pinner.py (CORE-Block)
-        "interval": 300,    # 5 min
+        "interval": 600,    # 10 min (entzerren T1672)

## Warum Einzelzeilen-Patch statt Voll-Umschreibung
Die .py ist groß (Poll-Loop, 3 Tier-Blöcke, Logging). Ein write_file über die
gesamte Datei ist fehleranfällig (weitere Blöcke versehentlich überschreiben).
Nur die eine numerische Zeile im CORE-Block ändert sich; alles bleibt identisch.

## Sicherheit
- Kein semantischer Nebeneffekt: 600 s > 300 s bedeutet nur selteneres Pinning
  des CORE-Tiers -> weniger Batch-Frequenz -> weniger Morgen-Spitze.
- CORE-Tier-Wege (.TOPICS/.AI/.OS/BACH/system, .SYNC, .SYNC/scripts) werden
  alle 10 statt 5 Min geprüft. Für den Pinner (Pin/Unlock, kein Live-Sync)
  ist 10 Min ausreichend.
- Kein KeepAlive/Throttle in der Pinner-Plist betroffen (nur RunAtLoad+KeepAlive).

## Rollback
backup/onedrive_pinner.py.bak enthält den Originalzustand.
Rückweg: cp -p backup/onedrive_pinner.py.bak <LIVE-Pfad>/onedrive_pinner.py
