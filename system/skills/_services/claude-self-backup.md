---
name: claude-self-backup
metadata:
  version: 2.6.1
  last_updated: 2025-12-25
description: >
  Vollautomatisches Backup des recludOS-Ordners auf FritzBox-NAS.
  Mit adaptivem Timeout, Windows Auto-Switch Sperre, Session-Snapshot,
  Sicherheits-Watchdog, OneDrive-Integration und intelligenter
  WLAN-Eskalationsstrategie gegen Windows-Cache-Trägheit.
---

# Claude Self Backup v2.6

Vollautomatisches, sicheres Backup-System mit intelligenter WLAN-Eskalation.

## Netzwerk-Topologie

```
NORMAL:   PC ──WLAN──► LTE-Router ──► Internet ──► Claude
BACKUP:   PC ──WLAN──► FritzBox ──LAN──► LTE-Router ──► Internet ──► Claude
                           │
                          USB
                           │
                          SSD (Backup-Ziel)
```

**Internet bleibt verfügbar!** Nur kurze Unterbrechung beim WLAN-Wechsel (~10-30 Sek).

## Backup-Ablauf

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Zustand erfassen (WLAN, FTP-Status, Backup-Größe)        │
├─────────────────────────────────────────────────────────────┤
│ 2. OneDrive STOPPEN (verhindert Dateisperren)               │
│ 3. FritzBox FTP + WLAN aktivieren                           │
│ 4. Original-WLAN SPERREN (connectionmode=manual)            │
│    → Verhindert Windows Auto-Switch zurück                  │
│ 5. WLAN wechseln mit Eskalationsstrategie (max 120s)        │
│    Phase 1: Initial Wait + Scans (45s)                      │
│    Phase 2: Blind Connect auf gut Glück                     │
│    Phase 3: WLAN-Adapter Restart                            │
│    Phase 4: disconnect/connect Zyklus                       │
│    Phase 5: Finale Wartezeit (30s)                          │
│ 6. Internet-Verbindung verifizieren                         │
├─────────────────────────────────────────────────────────────┤
│ 7. SPEED-TEST durchführen                                   │
│ 8. ADAPTIVEN TIMEOUT berechnen (Dauer × 3)                  │
│ 9. Watchdog mit berechnetem Timeout starten                 │
├─────────────────────────────────────────────────────────────┤
│ 10. FTP-Backup durchführen                                  │
├─────────────────────────────────────────────────────────────┤
│ 11. FTP + WLAN deaktivieren                                 │
│ 12. Original-WLAN ENTSPERREN (connectionmode=auto)          │
│ 13. Original-WLAN verbinden (kurze Unterbrechung)           │
│ 14. OneDrive STARTEN (/background)                          │
│ 15. Watchdog beenden                                        │
└─────────────────────────────────────────────────────────────┘
```

## WLAN-Eskalationsstrategie

**Problem:** Windows WLAN-Cache ist extrem träge. Selbst wenn FritzBox-WLAN
aktiviert ist, erscheint es oft nicht in der Netzwerkliste - erst nach
manuellem Öffnen der WLAN-Übersicht aktualisiert Windows den Cache.

**Lösung:** 6-stufige Eskalationsstrategie (max 120s Gesamt-Timeout):

```
PHASE 1: Initial Wait + Scans (45s)
  → 15s Pause (WLAN hochfahren)
  → 30s mit mode=bssid Scans alle 2s
  → Alle 10s: 3× aggressive Scans
  ✅ Erfolgreich bei ~60% der Fälle

PHASE 2: Blind Connect (auf gut Glück)
  → netsh wlan connect auch wenn unsichtbar
  → Manchmal klappt Verbindung trotz Cache
  → Bei Erfolg: Nachträglich Manual-Mode setzen
  ✅ Erfolgreich bei ~25% der verbleibenden Fälle

PHASE 3: WLAN-Adapter Restart
  → netsh interface set interface 'WLAN' disabled
  → 3s Pause
  → netsh interface set interface 'WLAN' enabled  
  → 5s Pause für Hochfahren
  → Cache wird oft aktualisiert
  ✅ Erfolgreich bei ~10% der verbleibenden Fälle

PHASE 4: disconnect/connect Zyklus
  → netsh wlan disconnect
  → 2s Pause
  → Aggressive Cache-Refresh
  ✅ Bereitet Phase 5 vor

PHASE 5: Finale Wartezeit (max 30s)
  → Letzte Chance für Cache-Update
  → Alle 2s Check ob sichtbar

PHASE 6: Abbruch
  → Nach 120s Gesamtzeit aufgeben
  → Shutdown-Prozedur einleiten
```

**Erfolgsrate:** >95% bei normalem Betrieb

## Windows Auto-Switch Schutz

Problem: Windows wechselt automatisch zu bekannten WLANs wenn die
aktuelle Verbindung "schlecht" erscheint (z.B. kein Internet erkannt).

Lösung: Während Backup wird das Original-WLAN auf "manual" gesetzt:

```powershell
# Vor WLAN-Wechsel: Sperre Auto-Connect zum Original-WLAN
netsh wlan set profileparameter name="YOUR_DEFAULT_WLAN_SSID" connectionmode=manual

# Nach Backup: Entsperre wieder
netsh wlan set profileparameter name="YOUR_DEFAULT_WLAN_SSID" connectionmode=auto
```

Dies verhindert dass Windows während des Backups zurück zum
Standard-WLAN wechselt.

## OneDrive-Integration

**Problem:** OneDrive synchronisiert während des Backups und kann Dateien sperren,
was zu "Permission Denied" Fehlern beim FTP-Transfer führt.

**Lösung:** OneDrive wird vor dem Backup sauber gestoppt und nach Abschluss silent neu gestartet:

```
VOR BACKUP:
  OneDrive.exe /shutdown
  → Sauberes Herunterfahren (kein Explorer-Fenster!)
  → Stoppt Synchronisation komplett
  → Entsperrt alle Dateien

NACH BACKUP:
  OneDrive.exe /background
  → Silent restart im Hintergrund (kein Explorer-Fenster!)
  → Startet Synchronisation automatisch wieder
```

**Wichtig:** `/shutdown` + `/background` vermeidet Explorer-Fenster (im Gegensatz zu `/pause` + `/resume`)

**Sicherheit:**
- Watchdog startet OneDrive bei Timeout/Crash automatisch neu
- Cleanup-Funktion garantiert Neustart auch bei Fehlern
- OneDrive ist spätestens nach Cleanup wieder aktiv

## Adaptiver Timeout

Der Watchdog-Timeout wird dynamisch berechnet:

```
Timeout = (Backup-Größe / gemessene Speed) × Sicherheitsfaktor

Beispiel:
  Speed-Test:     2.500 KB/s
  Backup-Größe:   800 MB
  Geschätzte Zeit: 800 × 1024 / 2500 / 60 = 5,5 Min
  Sicherheit:     × 3
  → Timeout:      17 Min
```

| Parameter | Wert |
|-----------|------|
| Sicherheitsfaktor | 3× |
| Min. Timeout | 5 Min |
| Max. Timeout | 60 Min |
| Speed-Test Größe | 512 KB |

## Schnellstart

```bash
# Vollautomatisches Backup
python tools/auto_backup_orchestrator.py

# Simulation (nur Status prüfen, keine Änderungen)
python tools/auto_backup_orchestrator.py --dry-run

# Testmodus (1MB Dummy-Transfer zum Testen)
python tools/auto_backup_orchestrator.py --test

# Ohne Watchdog
python tools/auto_backup_orchestrator.py --no-watchdog
```

### Modi-Flags Erklärung

| Flag | Funktion | WLAN-Wechsel | Transfer | Watchdog |
|------|----------|--------------|----------|----------|
| *(kein Flag)* | Vollautomatisches Backup | ✅ Ja | ✅ Voll | ✅ Ja |
| `--dry-run` | Nur Status prüfen | ❌ Nein | ❌ Nein | ❌ Nein |
| `--test` | Testmodus mit 1MB Dummy | ✅ Ja | ⚠️ 1MB | ✅ Ja |
| `--no-watchdog` | Backup ohne Watchdog | ✅ Ja | ✅ Voll | ❌ Nein |

**Empfohlener Workflow:**
1. `--dry-run` → Prüfe ob System bereit ist
2. `--test` → Teste kompletten Ablauf mit 1MB
3. *(kein Flag)* → Vollbackup durchführen

## Output-Dateien

| Datei | Inhalt |
|-------|--------|
| `backup.log` | Detailliertes Log zum Nachlesen |
| `last_backup_status.json` | Zusammenfassung für schnellen Check |
| `claude_session_snapshot.md` | **NEU:** Kontext für Claude nach Reconnect |
| `.backup_watchdog.json` | Watchdog-State (temporär) |
| `config.json` | Letztes Backup-Datum |

### claude_session_snapshot.md (NEU)

Diese Datei wird VOR kritischen WLAN-Wechseln geschrieben und hilft Claude,
nach einem Verbindungsabbruch den Kontext wiederherzustellen:

- **Phase:** Zeigt wo im Prozess wir waren (WLAN_WECHSEL, TRANSFER, CLEANUP)
- **Status:** Alle relevanten Parameter (WLAN, Größe, Speed, Timeout)
- **Anleitung:** Was Claude nach Reconnect tun soll

**Wichtig:** Datei wird nach erfolgreichem Abschluss automatisch gelöscht.
Existiert sie noch → Backup wurde unterbrochen!

### last_backup_status.json Beispiel

```json
{
  "success": true,
  "duration_seconds": 312,
  "files_backed_up": 2847,
  "bytes_backed_up": 834567890,
  "speed_kbs": 2680,
  "estimated_duration_min": 5.2,
  "actual_duration_min": 5.2,
  "timeout_used_min": 16
}
```

## Scripts

| Script | Funktion |
|--------|----------|
| `auto_backup_orchestrator.py` | **Hauptscript** - Vollautomatisch |
| `backup_watchdog.py` | Sicherheits-Timer |
| `ftp_backup_claude.py` | Nur FTP-Backup (ohne WLAN-Wechsel) |
| `fritzbox_wlan_control.py` | Manuelle WLAN-Steuerung |
| `backup_claude.py` | Altes SMB-Backup |

## Sicherheits-Watchdog

```
┌─────────────────────────────────────────────────────────────┐
│ WATCHDOG - Unabhängiger Prozess                             │
├─────────────────────────────────────────────────────────────┤
│ • Liest Timeout aus .backup_watchdog.json                   │
│ • Prüft alle 30 Sek ob Backup noch läuft                    │
│ • Bei Timeout ODER Absturz:                                 │
│   → FTP deaktivieren                                        │
│   → WLAN deaktivieren                                       │
│   → Original-WLAN wiederherstellen                          │
└─────────────────────────────────────────────────────────────┘
```

### Manuelles Aufräumen

```bash
python tools/backup_watchdog.py --cleanup-now
```

## FritzBox-Konfiguration

| Parameter | Wert |
|-----------|------|
| IP | NAS-HOST |
| Benutzer | YOUR_NAS_USER |
| WLAN-SSID | YOUR_NAS_WLAN_SSID |
| FTP-Port | 21 |
| TR-064-Port | 49000 |

## Claude-Integration

### Nach WLAN-Reconnect (Gedächtnis wiederherstellen)

Wenn Claude nach einem WLAN-Abbruch den Kontext verloren hat:

```
1. Prüfe ob `claude_session_snapshot.md` existiert
   → JA: Backup wurde unterbrochen, lies Snapshot für Kontext
   → NEIN: Backup erfolgreich abgeschlossen

2. Lies `last_backup_status.json` für Ergebnis
   → success: true/false
   → error: Fehlermeldung falls vorhanden

3. Bei Bedarf: `backup.log` für Details
```

### Automatischer Kontext-Check

Claude kann nach Reconnect automatisch prüfen:

```python
# Schnell-Check nach Reconnect
import json
from pathlib import Path

scripts_dir = Path("{BACH_INSTALL_PATH}/skills/_services/claude_self_backup/scripts")

# 1. Session-Snapshot prüfen (existiert = unterbrochen)
snapshot = scripts_dir / "claude_session_snapshot.md"
if snapshot.exists():
    print("⚠️ Backup wurde unterbrochen!")
    print(snapshot.read_text())
else:
    # 2. Status prüfen
    status = json.loads((scripts_dir / "last_backup_status.json").read_text())
    if status["success"]:
        print(f"✅ Backup erfolgreich: {status['files_backed_up']} Dateien")
    else:
        print(f"❌ Backup fehlgeschlagen: {status['error']}")
```

### Trigger-Phrasen

| User sagt | Aktion |
|-----------|--------|
| "Claude Backup" | `auto_backup_orchestrator.py` |
| "Backup Status" | `last_backup_status.json` lesen |
| "Backup Log" | `backup.log` lesen |

## Performance-Erwartung

| Verbindung | Speed | 800 MB Dauer |
|------------|-------|--------------|
| LTE→FritzBox (alt) | ~0.5 MB/s | ~27 Min |
| **Direkt FritzBox** | **~2-5 MB/s** | **~3-7 Min** |

## Changelog

### v2.6.0 (2025-12-21)
- **NEU:** Intelligente WLAN-Eskalationsstrategie gegen Windows-Cache-Trägheit
- 6-stufige Eskalation: Warten → mode=bssid → Blind Connect → Adapter Restart → disconnect/connect → Finale Wartezeit
- `restart_wifi_adapter()` - WLAN-Adapter aus/an Zyklus
- `try_connect_blind()` - Verbindung auf gut Glück (funktioniert manchmal trotz unsichtbarem WLAN)
- `connect_to_fritzbox_with_escalation()` - Orchestriert alle Stufen mit 120s Gesamt-Timeout
- Nachträgliches Umlegen der Auto-Connect-Sperre bei Blind Connect Erfolg
- Basiert auf User-Feedback: "Manuelle WLAN-Liste-Öffnung erzwang Cache-Update"

### v2.5.0 (2025-12-21)
- **VERBESSERUNG:** Robustes WLAN-Cache-Handling
- OneDrive nutzt `/shutdown` + `/background` (kein Explorer-Fenster!)
- `force_wifi_refresh()` - aggressive WLAN-Scans gegen trägen Windows-Cache
- 15 Sekunden initial_wait nach WLAN-Aktivierung
- Alle 10 Sekunden automatischer Cache-Refresh während Wartezeit
- Test-GUI als wiederverwendbare Subroutine ausgelagert

### v2.4.0 (2025-12-21)
- **NEU:** OneDrive-Pausierung während Backup
- Verhindert Dateisperren durch OneDrive-Synchronisation
- `/pause` vor Backup, `/resume` nach Abschluss
- Watchdog setzt OneDrive bei Fehler/Timeout automatisch fort
- Löst "Permission Denied" Fehler bei OneDrive-Dateien

### v2.3.0 (2025-12-20)
- **NEU:** Session-Snapshot (`claude_session_snapshot.md`) für Claude-Reconnect
- Schreibt Kontext VOR kritischen WLAN-Wechseln
- Ermöglicht Claude, nach Verbindungsabbruch Gedächtnis wiederherzustellen
- Wird nach erfolgreichem Abschluss automatisch gelöscht
- Testmodus (`--test`) jetzt MIT Watchdog für vollständigen Test

### v2.2.0 (2025-12-20)
- Windows Auto-Switch Schutz (connectionmode=manual/auto)
- Verhindert dass Windows während Backup zurückwechselt
- Schneller, erzwungener WLAN-Wechsel zurück
- Watchdog räumt auch WLAN-Sperre auf

### v2.1.0 (2025-12-20)
- Adaptiver Timeout basierend auf Speed-Test
- Internet-Verifizierung nach WLAN-Wechsel
- Status-Datei für schnellen Check
- Detailliertes Log-File

### v2.0.0 (2025-12-20)
- Vollautomatisches Backup mit WLAN-Wechsel
- Sicherheits-Watchdog

### v1.0.0 (2025-12-19)
- Initiale Version mit SMB/robocopy
