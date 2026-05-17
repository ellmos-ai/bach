@echo off
REM ============================================================
REM BACH Auto-Session: Volle Rechte (interaktiv)
REM Startet Claude Code mit vollen Rechten und BACH-Kontext
REM ============================================================
title BACH Claude: Volle Rechte

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Du hast volle Rechte. Arbeite selbststaendig an offenen Tasks, erstelle neue Features, fixe Bugs und fuehre Wartungsaufgaben durch. Nutze 'bach --recurring check' fuer faellige periodische Aufgaben. Frage bei Unklarheiten den User." --dangerously-skip-permissions

echo.
echo [FERTIG] Session beendet.
if not defined BACH_AUTO pause
