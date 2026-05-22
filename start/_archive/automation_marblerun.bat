@echo off
REM ============================================================
REM BACH Automatisierung - llmauto Ketten (ehemals MarbleRun)
REM Startet llmauto Chains aus system/tools/llmauto/
REM ============================================================
title BACH llmauto
setlocal enabledelayedexpansion

set "LLMAUTO_DIR=%~dp0..\..\system\tools"

echo.
echo  ===================================================
echo   BACH llmauto - Ketten starten
echo  ===================================================
echo.

if not exist "%LLMAUTO_DIR%\llmauto\llmauto.py" (
    echo  llmauto nicht gefunden: %LLMAUTO_DIR%\llmauto\
    pause
    exit /b 1
)

echo  Verfuegbare Aktionen:
echo.
echo   [1]  Kette starten (Name eingeben)
echo   [S]  Status anzeigen
echo   [X]  Kette stoppen
echo   [L]  Ketten auflisten
echo   [0]  Abbrechen
echo.

set /P CHOICE=  Auswahl:
if /I "%CHOICE%"=="0" exit /b 0
if /I "%CHOICE%"=="" exit /b 0

if /I "%CHOICE%"=="L" (
    cd /d "%LLMAUTO_DIR%"
    set PYTHONIOENCODING=utf-8
    python -m llmauto chain list
    echo.
    pause
    exit /b 0
)

if /I "%CHOICE%"=="S" (
    cd /d "%LLMAUTO_DIR%"
    set PYTHONIOENCODING=utf-8
    python -m llmauto chain status
    echo.
    pause
    exit /b 0
)

if /I "%CHOICE%"=="X" (
    set /P CHAIN_ID=  Ketten-Name zum Stoppen:
    if "!CHAIN_ID!"=="" exit /b 0
    cd /d "%LLMAUTO_DIR%"
    set PYTHONIOENCODING=utf-8
    python -m llmauto chain stop !CHAIN_ID!
    echo.
    pause
    exit /b 0
)

if "%CHOICE%"=="1" (
    set /P CHAIN_ID=  Ketten-Name eingeben:
    if "!CHAIN_ID!"=="" exit /b 0

    echo.
    echo  Starte llmauto: !CHAIN_ID!
    echo.

    start cmd /k "title llmauto: !CHAIN_ID! && cd /d "%LLMAUTO_DIR%" && set PYTHONIOENCODING=utf-8 && python -m llmauto chain start !CHAIN_ID!"

    echo  [OK] Kette !CHAIN_ID! gestartet (neues Fenster^).
    echo.
    pause
    exit /b 0
)

echo  Ungueltige Auswahl.
pause
