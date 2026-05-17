@echo off
REM ============================================================
REM BACH Auto-Session: Alle Tasks (1 Stunde Limit)
REM Bearbeitet alle offenen BACH-Tasks, stoppt nach 1 Stunde
REM ============================================================
title BACH Auto: Alle Tasks (1h)

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann offene Tasks aus 'bach task list' - waehle selbststaendig die wichtigsten aus (P1 zuerst). Arbeite maximal 60 Minuten, dann fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."

echo.
echo [FERTIG] Session beendet.
if not defined BACH_AUTO pause
