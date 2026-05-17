@echo off
REM ============================================
REM BACH Bridge - CLI-Modus (ohne Tray)
REM ============================================

echo [BACH] Starte Bridge im CLI-Modus...
cd /d "%~dp0..\..\system\hub\_services\claude_bridge"

REM Prüfe ob Bridge bereits läuft (Lock liegt im Temp-Ordner)
if exist "%TEMP%\bach_bridge.lock" (
    echo [WARN] Bridge läuft bereits
    echo        Lock-File: %TEMP%\bach_bridge.lock
    echo        Zum Stoppen: CTRL+C oder Prozess beenden
    echo.
    pause
    exit /b 1
)

REM Starte Daemon direkt
echo [INFO] Bridge startet (CTRL+C zum Beenden)
echo.
python bridge_daemon.py
