@echo off
REM =====================================================
REM  BACH Advanced-Konsole (voller Kommandozeilen-Zugriff)
REM  Fuer erfahrene Benutzer mit direktem bach.py Zugriff
REM =====================================================

REM Ins System-Verzeichnis wechseln
cd /d "%~dp0..\..\system"

title BACH Advanced Console

echo =====================================================
echo  BACH Advanced Console v2.0
echo =====================================================
echo.
echo Verfuegbare Befehle:
echo   python bach.py help              - Hilfe anzeigen
echo   python bach.py task list         - Aufgaben verwalten
echo   python bach.py workflow run [wf] - Workflow ausfuehren
echo   python bach.py --status          - Systemstatus
echo   python bach.py fs check          - Dateisystem pruefen
echo   python bach.py --backup          - Backup erstellen
echo.
echo Tippe 'exit' zum Beenden.
echo =====================================================
echo.

REM Normales CMD-Fenster mit BACH im Pfad
cmd /k "set PATH=%CD%;%PATH% && set PYTHONIOENCODING=utf-8"
