@echo off
REM ============================================================
REM BACH Automatisierung - Ketten verwalten
REM Zeigt verfuegbare llmauto Chains und Prompts
REM ============================================================
title BACH Chain Manager
setlocal

set "LLMAUTO_DIR=%~dp0..\..\system\tools"
set PYTHONIOENCODING=utf-8

echo.
echo  ===================================================
echo   BACH Chain Manager
echo  ===================================================

if not exist "%LLMAUTO_DIR%\llmauto\llmauto.py" (
    echo.
    echo  llmauto nicht gefunden: %LLMAUTO_DIR%\llmauto\
    pause
    exit /b 1
)

echo.
echo  [L]  Verfuegbare Ketten anzeigen
echo  [P]  Prompt-Vorlagen anzeigen
echo  [S]  Ketten-Status anzeigen
echo  [0]  Abbrechen
echo.
set /P CHOICE=  Auswahl:

if /I "%CHOICE%"=="0" exit /b 0
if /I "%CHOICE%"=="" exit /b 0

if /I "%CHOICE%"=="L" (
    cd /d "%LLMAUTO_DIR%"
    python -m llmauto chain list
    echo.
    pause
    exit /b 0
)

if /I "%CHOICE%"=="P" (
    echo.
    echo  Verfuegbare Prompt-Vorlagen:
    echo  ----------------------------
    dir /b "%LLMAUTO_DIR%\llmauto\prompts\*.txt" 2>nul
    echo.
    echo  Pfad: %LLMAUTO_DIR%\llmauto\prompts\
    echo.
    pause
    exit /b 0
)

if /I "%CHOICE%"=="S" (
    cd /d "%LLMAUTO_DIR%"
    python -m llmauto chain status
    echo.
    pause
    exit /b 0
)

echo  Ungueltige Auswahl.
pause
