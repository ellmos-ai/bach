@echo off
REM ============================================================
REM BACH Auto-Loop: Alle 15 Minuten eine Session
REM Startet endlos alle 15 Min eine neue Claude-Session
REM Ctrl+C zum Beenden
REM ============================================================
title BACH Loop: Alle 15 Min

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

:loop
echo.
echo [%date% %time%] Starte neue BACH-Session...
echo ============================================================

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite offene Tasks aus 'bach task list' (P1 zuerst). Arbeite maximal 12 Minuten, dann fuehre 'bach --memory session' mit Zusammenfassung aus und beende mit 'bach --shutdown'." --max-turns 40

echo.
echo [%date% %time%] Session beendet. Naechste in 15 Minuten...
echo Druecke Ctrl+C zum Beenden.
timeout /t 900 /nobreak
goto loop
