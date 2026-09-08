# Architektur-Dokumentation: BACH Cloud-Control Service

**Version:** 1.0.0  
**Datum:** 2026-09-09  
**Status:** Aktiv  
**Modul:** `system/hub/_services/cloud/`  
**CLI:** `bach cloud`  
**API:** `/api/cloud/*`  

---

## 1. Problemstellung & Motivation

In verteilten Arbeitsumgebungen und Multi-Device-Setups greifen KI-Agenten, Hintergrunddienste und der Nutzer gleichzeitig auf Dateien in Cloud-Verzeichnissen zu (Microsoft OneDrive, Apple iCloud Drive, Google Drive, Dropbox, Nextcloud).

### Historische Konflikte:
1. **SQLite-WAL-Konflikte:** SQLite schreibt Transaktionen in Write-Ahead-Log-Dateien (`.db-wal`). Wenn ein Cloud-Sync-Client diese während eines aktiven Schreibzugriffs sperrt, wirft SQLite `sqlite3.OperationalError: database is locked`. OneDrive erzeugte dadurch durchnummerierte Duplikate (`bach 2.db-wal` bis `bach 12.db-wal`).
2. **Dokumenten- und Markdown-Kollisionen:** Parallele Schreibvorgänge führten zu Tausenden Konfliktdateien (`* - ASUS-GEI.md` / `* - WORKSTATION-LG.md`).
3. **Alte Fehl-Implementierung (`proc.suspend()`):** Früher fror der `daemon_service.py` den Windows-Prozess von OneDrive beim Start dauerhaft ein und taute ihn erst beim Herunterfahren auf. Dies führte zu stummen Sync-Blockaden über Tage hinweg.

---

## 2. Architektur & Komponenten

Der **Cloud-Control-Service** entkoppelt die Cloud-Steuerung von einzelnen Skripten und stellt eine providerneutrale Schnittstelle für CLI, Web-API und Python-Pipelines bereit.

```mermaid
graph TD
    subgraph Clients ["Schnittstellen & Aufrufer"]
        CLI["CLI: bach cloud [status|pause|resume|toggle]"]
        API["REST-API: /api/cloud/*"]
        CTX["Python: with cloud_pause(): ..."]
        DAEMON["daemon_service.py (Operative Jobs)"]
    end

    subgraph Core ["Cloud Control Core (hub/_services/cloud)"]
        MGR["CloudManager (Singleton)"]
        WATCH["Safety Watchdog (Auto-Resume Timer)"]
        DETECT["Auto-Detection (Process / App Scan)"]
    end

    subgraph Adapters ["Provider-Adapter"]
        OD["OneDriveAdapter (Win / macOS / Linux)"]
        GD["GoogleDriveAdapter (Win / macOS)"]
        IC["ICloudAdapter (macOS bird / Win iCloud)"]
        DB["DropboxAdapter (Win / macOS / Linux)"]
        NC["NextcloudAdapter (Win / macOS / Linux)"]
    end

    CLI --> MGR
    API --> MGR
    CTX --> MGR
    DAEMON --> MGR

    MGR --> DETECT
    MGR --> WATCH
    MGR --> OD
    MGR --> GD
    MGR --> IC
    MGR --> DB
    MGR --> NC
```

---

## 3. Operativer Job-Ablauf im Daemon

Im Gegensatz zur alten Dauer-Blockade pausiert der sanierte `daemon_service.py` Cloud-Sync-Clients **ausschließlich operativ während der tatsächlichen Ausführung schreibintensiver Jobs** (z. B. nächtliches Datenbank-Backup oder Memory-Konsolidierung).

```mermaid
sequenceDiagram
    autonumber
    participant D as Daemon (Idle-Loop)
    participant CM as CloudManager
    participant CS as Cloud-Sync (z.B. OneDrive / iCloud)
    participant J as Job (z.B. bach backup create)

    Note over D,CS: Daemon wartet im Leerlauf — Cloud-Sync läuft zu 100% normal
    D->>D: Job wird fällig (z.B. 02:00 Uhr)
    
    alt Job ist schreibintensiv (needs_cloud_guard = True)
        D->>CM: pause(timeout=330s)
        CM->>CS: Sauberer Stopp / SIGSTOP
        CM->>CM: Safety Watchdog Timer aktivieren
        D->>J: Subprocess ausführen
        J-->>D: Job erfolgreich beendet
        D->>CM: resume()
        CM->>CS: Start im Hintergrund (/background / SIGCONT)
        CM->>CM: Safety Watchdog Timer stoppen
        Note over D,CS: 2-3s Sync-Pufferfenster für sauberen Cloud-Upload
    else Normaler Lese-/Prüfjob
        D->>J: Job direkt ausführen (Sync läuft parallel unberührt)
    end

    Note over D,CS: Daemon kehrt in Idle-Zustand zurück
```

---

## 4. Ausfallsicherer Watchdog (Fail-Safe)

Bleibt ein Job hängen oder stürzt der ausführende Prozess unvorhergesehen ab, greift der **Safety-Watchdog**:

```mermaid
stateDiagram-v2
    [*] --> Aktiv: Sync läuft normal
    Aktiv --> Pausiert: pause(timeout=300s)
    
    state Pausiert {
        [*] --> TimerRunning
        TimerRunning --> Abgelaufen: 300 Sekunden verstrichen
        TimerRunning --> VorzeitigBeendet: Job ruft resume() auf
    }

    VorzeitigBeendet --> Aktiv: Sofortige Reaktivierung
    Abgelaufen --> Aktiv: Watchdog reaktiviert automatisch!
```

---

## 5. Provider-Details & Plattform-Befehle

| Provider | Plattform | Pause-Mechanismus | Resume-Mechanismus |
| :--- | :--- | :--- | :--- |
| **Microsoft OneDrive** | Windows | `OneDrive.exe /shutdown` (wartet 2s) | `OneDrive.exe /background` (detached) |
| | macOS | `osascript -e 'quit app "OneDrive"'` | `open -a "OneDrive" --background` |
| | Linux | `pkill -STOP onedrive` | `pkill -CONT onedrive` |
| **Google Drive** | Windows | `taskkill /IM GoogleDriveFS.exe` | Aufruf von `launch.bat` |
| | macOS | `osascript -e 'quit app "Google Drive"'` | `open -a "Google Drive" --background` |
| **Apple iCloud** | macOS | `killall -STOP bird` | `killall -CONT bird` |
| | Windows | `taskkill /IM iCloudDrive.exe` | Aufruf von `iCloud.exe` |
| **Dropbox** | Windows | `taskkill /IM Dropbox.exe` | Aufruf von `Dropbox.exe` |
| | macOS | `osascript -e 'quit app "Dropbox"'` | `open -a "Dropbox" --background` |
| | Linux | `dropbox stop` | `dropbox start` |
| **Nextcloud** | Windows | `nextcloud.exe --quit` | `nextcloud.exe --background` |
| | macOS | `osascript -e 'quit app "nextcloud"'` | `open -a "nextcloud" --background` |
| | Linux | `nextcloud --quit` | `nextcloud &` |

---

## 6. Code-Beispiele & Verwendung

### A. Im Python-Code via Context-Manager
```python
from hub._services.cloud import cloud_pause

# Automatisches Pausieren mit garantiertem Resume im finally:
with cloud_pause(timeout=120):
    # Gefahrlose Massen-Schreiboperationen oder Reorganisation
    datenbank.exportieren()
    dateien.verschieben()
# Hier läuft Cloud-Sync bereits wieder!
```

### B. Auf der Kommandozeile (CLI)
```bash
# Status aller Provider anzeigen
bach cloud status

# Gezielt OneDrive für 2 Minuten pausieren
bach cloud pause onedrive -t 120

# Alle pausierten Provider sofort wieder aktivieren
bach cloud resume

# Umschalten (Toggle)
bach cloud toggle
```
