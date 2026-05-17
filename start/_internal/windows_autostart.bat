@echo off
REM ============================================
REM BACH Chat Tray - Windows Autostart Setup
REM ============================================

echo [BACH] Erstelle Windows Autostart-Eintrag...
echo.

set "TRAY_SCRIPT=%~dp0..\..\system\hub\_services\chat\chat_tray.py"
set "TRAY_HOST=127.0.0.1"
if not "%BACH_HOST%"=="" set "TRAY_HOST=%BACH_HOST%"

REM Alten Bridge-Eintrag entfernen (falls vorhanden)
schtasks /delete /tn "BACH Bridge Tray" /f >nul 2>&1

REM Neuen Chat Tray Eintrag erstellen
schtasks /create /tn "BACH Chat Tray" ^
    /tr "pythonw \"%TRAY_SCRIPT%\" --host %TRAY_HOST%" ^
    /sc onlogon ^
    /rl highest ^
    /f

if %ERRORLEVEL% EQU 0 (
    echo [OK] Autostart-Eintrag erstellt
    echo      Chat Tray startet jetzt automatisch bei Login
    echo      Host: %TRAY_HOST%:8081
) else (
    echo [ERROR] Autostart-Eintrag fehlgeschlagen
    echo         Bitte als Administrator ausfuehren
)

echo.
pause
