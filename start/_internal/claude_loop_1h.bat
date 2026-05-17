@echo off
REM ============================================================
REM BACH Auto-Loop: Jede Stunde eine Session
REM Startet endlos jede Stunde eine neue Claude-Session
REM Ctrl+C zum Beenden
REM ============================================================
title BACH Loop: Jede Stunde

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

:loop
echo.
echo [%date% %time%] Starte neue BACH-Session...
echo ============================================================

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite offene Tasks aus 'bach task list' (P1 zuerst). Arbeite maximal 50 Minuten, dann fuehre 'bach --memory session' mit Zusammenfassung aus und beende mit 'bach --shutdown'." --max-turns 150

echo.
echo [%date% %time%] Session beendet. Naechste in 1 Stunde...
echo Druecke Ctrl+C zum Beenden.
timeout /t 3600 /nobreak
goto loop
