@echo off
REM ============================================================
REM BACH Auto-Session: Zugewiesene Tasks (kein Zeitlimit)
REM Bearbeitet nur Claude zugewiesene Tasks bis alle erledigt
REM ============================================================
title BACH Auto: Zugewiesene Tasks (unbegrenzt)

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann NUR dir (Claude) zugewiesene Tasks aus 'bach task list'. Arbeite alle zugewiesenen Tasks ab. Nach jeder erledigten Aufgabe pruefe ob weitere zugewiesene Tasks offen sind. Wenn alle erledigt sind, fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."

echo.
echo [FERTIG] Session beendet.
if not defined BACH_AUTO pause
