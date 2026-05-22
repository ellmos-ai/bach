@echo off
REM ============================================================
REM BACH Auto-Session: Alle Tasks (30 Min Limit)
REM Bearbeitet alle offenen BACH-Tasks, stoppt nach 30 Min
REM ============================================================
title BACH Auto: Alle Tasks (30min)

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann offene Tasks aus 'bach task list' - waehle selbststaendig die wichtigsten aus (P1 zuerst). Arbeite maximal 30 Minuten, dann fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."

echo.
echo [FERTIG] Session beendet.
if not defined BACH_AUTO pause
