@echo off
REM ============================================
REM BACH Chat Tray - Autostart Entfernen
REM ============================================

echo [BACH] Entferne Windows Autostart-Eintraege...

REM Neuen Chat Tray Eintrag entfernen
schtasks /delete /tn "BACH Chat Tray" /f >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Chat Tray Autostart entfernt
)

REM Alten Bridge Eintrag entfernen (falls noch vorhanden)
schtasks /delete /tn "BACH Bridge Tray" /f >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Alter Bridge Autostart entfernt
)

echo.
echo [DONE] Alle BACH Autostart-Eintraege entfernt
pause
