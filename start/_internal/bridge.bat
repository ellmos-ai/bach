@echo off
REM ============================================
REM BACH Bridge - Standard-Startverfahren
REM Startet immer: Tray + Daemon (gekoppelt)
REM ============================================

echo [BACH] Bridge Standard-Start...
cd /d "%~dp0..\..\system\hub\_services\claude_bridge"

REM Prüfe ob TRAY schon läuft
if exist "%TEMP%\bach_bridge_tray.lock" (
    echo [WARN] Bridge Tray laeuft bereits
    echo        Lock-File: %TEMP%\bach_bridge_tray.lock
    echo        Zum Stoppen: bach bridge stop
    echo.

    REM Prüfe ob Daemon auch läuft (sollte beides laufen)
    if exist "%TEMP%\bach_bridge.lock" (
        echo [OK] Tray + Daemon laufen beide - kein Neustart noetig
    ) else (
        echo [WARN] Tray laeuft aber Daemon fehlt - Bridge hat Problem
        echo        Bitte stoppen und neu starten
    )
    echo.
    pause
    exit /b 0
)

REM Prüfe ob Daemon ohne Tray läuft (Problem: Kopplung verletzt!)
if exist "%TEMP%\bach_bridge.lock" (
    echo [INFO] Daemon laeuft ohne Tray - starte Tray neu (Kopplung herstellen)
    REM Tray starten - erkennt externe Daemon-Instanz und haengt sich dran
)

REM Starte Tray (startet dann Daemon wenn noetig, oder haengt sich an)
echo [INFO] Starte Bridge Tray...
start pythonw bridge_tray.py

echo.
echo [OK] Bridge Tray gestartet
echo      System Tray-Icon pruefen (unten rechts)
echo      Gruen = Bridge aktiv, Rot = gestoppt
echo.
timeout /t 3 /nobreak > nul

REM Kurz warten und Status prüfen
if exist "%TEMP%\bach_bridge_tray.lock" (
    echo [OK] Tray-Lock erstellt - Bridge startet
) else (
    echo [WARN] Kein Tray-Lock nach 3s - Startproblem?
    echo        Log prüfen: system\data\logs\claude_bridge.log
)
echo.
