@echo off
REM =====================================================
REM  BACH User-Konsole starten
REM =====================================================

REM Ins System-Verzeichnis wechseln
cd /d "%~dp0..\..\system"
set PYTHONIOENCODING=utf-8

title BACH User-Konsole

python tools\user_console.py

pause
