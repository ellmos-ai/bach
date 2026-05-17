@echo off
REM ============================================================
REM BACH Auto-Loop: Alle 30 Minuten eine Session
REM Startet endlos alle 30 Min eine neue Claude-Session
REM Ctrl+C zum Beenden
REM ============================================================
title BACH Loop: Alle 30 Min

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

:loop
echo.
echo [%date% %time%] Starte neue BACH-Session...
echo ============================================================

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite offene Tasks aus 'bach task list' (P1 zuerst). Arbeite maximal 25 Minuten, dann fuehre 'bach --memory session' mit Zusammenfassung aus und beende mit 'bach --shutdown'." --max-turns 80

echo.
echo [%date% %time%] Session beendet. Naechste in 30 Minuten...
echo Druecke Ctrl+C zum Beenden.
timeout /t 1800 /nobreak
goto loop
