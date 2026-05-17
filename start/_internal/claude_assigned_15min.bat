@echo off
REM ============================================================
REM BACH Auto-Session: Zugewiesene Tasks (15 Min Limit)
REM Bearbeitet nur Claude zugewiesene Tasks, stoppt nach 15 Min
REM ============================================================
title BACH Auto: Zugewiesene Tasks (15min)

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann NUR dir (Claude) zugewiesene Tasks aus 'bach task list'. Arbeite maximal 15 Minuten, dann fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."

echo.
echo [FERTIG] Session beendet.
if not defined BACH_AUTO pause
