@echo off
REM ============================================================
REM BACH Auto-Session: Wartung
REM Fuehrt Wartungsaufgaben durch (Recurring, Backup, Cleanup)
REM ============================================================
title BACH Auto: Wartung

set "BACH_DIR=%~dp0..\.."
cd /d "%BACH_DIR%"

claude --print "Starte mit lesen und ausfuehren von SKILL.md. Fuehre dann folgende Wartungsaufgaben durch: 1) 'bach --recurring check' fuer faellige periodische Tasks 2) 'bach backup status' und bei Bedarf 'bach backup create' 3) 'bach --maintain docs' fuer Dokumentations-Check 4) 'bach consolidate run' fuer Memory-Konsolidierung. Erstelle abschliessend eine Session-Zusammenfassung mit 'bach --memory session' und beende mit 'bach --shutdown'."

echo.
echo [FERTIG] Wartung beendet.
if not defined BACH_AUTO pause
