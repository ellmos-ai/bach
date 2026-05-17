@echo off
REM ============================================================
REM BACH Automatisierung - Neue Kette erstellen
REM Interaktiver Dialog zum Erstellen von llmauto Chains
REM ============================================================
title BACH Chain Creator
setlocal

set "LLMAUTO_DIR=%~dp0..\..\system\tools\llmauto"
set PYTHONIOENCODING=utf-8

echo.
echo  ===================================================
echo   BACH Chain Creator
echo  ===================================================

if not exist "%LLMAUTO_DIR%\chain_creator.py" (
    echo.
    echo  chain_creator.py nicht gefunden: %LLMAUTO_DIR%
    pause
    exit /b 1
)

echo.
echo  [1]  Neue Kette erstellen
echo  [2]  Prompt-Vorlagen anzeigen
echo  [0]  Abbrechen
echo.
set /P CHOICE=  Auswahl:

if "%CHOICE%"=="0" exit /b 0
if "%CHOICE%"=="" exit /b 0

if "%CHOICE%"=="2" (
    cd /d "%LLMAUTO_DIR%"
    python chain_creator.py --list
    echo.
    pause
    exit /b 0
)

if "%CHOICE%"=="1" (
    cd /d "%LLMAUTO_DIR%"
    python chain_creator.py
    echo.
    pause
    exit /b 0
)

echo  Ungueltige Auswahl.
pause
