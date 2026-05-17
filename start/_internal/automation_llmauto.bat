@echo off
REM ============================================================
REM BACH Automatisierung - llmauto Ketten
REM Scannt und startet llmauto Chains
REM ============================================================
title BACH llmauto
setlocal enabledelayedexpansion

set "LLMAUTO_DIR=%~dp0..\..\system\tools\llmauto"
set CHAINS_DIR=%LLMAUTO_DIR%\chains

echo.
echo  ===================================================
echo   BACH llmauto - Ketten starten
echo  ===================================================
echo.

if not exist "%LLMAUTO_DIR%\llmauto.py" (
    echo  llmauto nicht gefunden: %LLMAUTO_DIR%
    pause
    exit /b 1
)

REM Ketten auflisten
set COUNT=0
echo  Verfuegbare Ketten:
echo.

for %%F in ("%CHAINS_DIR%\*.json") do (
    set /A COUNT+=1
    set "CHAIN_!COUNT!=%%~nF"
    echo   [!COUNT!]  %%~nF
)

echo.
echo  ---
echo   [S]  Status aller Ketten
echo   [X]  Stoppen
echo   [0]  Abbrechen
echo.

if %COUNT%==0 (
    echo  Keine Ketten in %CHAINS_DIR% gefunden.
    pause
    exit /b 1
)

set /P CHOICE=  Auswahl:
if /I "%CHOICE%"=="0" exit /b 0
if /I "%CHOICE%"=="" exit /b 0

if /I "%CHOICE%"=="S" (
    cd /d "%LLMAUTO_DIR%"
    set PYTHONIOENCODING=utf-8
    python -m llmauto chain list
    echo.
    pause
    exit /b 0
)

if /I "%CHOICE%"=="X" (
    set /P STOP_NAME=  Ketten-Name zum Stoppen:
    cd /d "%LLMAUTO_DIR%"
    set PYTHONIOENCODING=utf-8
    python -m llmauto chain stop !STOP_NAME!
    echo.
    pause
    exit /b 0
)

set "SEL_CHAIN=!CHAIN_%CHOICE%!"
if "%SEL_CHAIN%"=="" (
    echo  Ungueltige Auswahl.
    pause
    exit /b 1
)

echo.
echo  Starte Kette: %SEL_CHAIN%
echo.

REM In neuem Fenster starten
start cmd /k "title llmauto: %SEL_CHAIN% && cd /d "%LLMAUTO_DIR%" && set PYTHONIOENCODING=utf-8 && python -m llmauto chain start %SEL_CHAIN%"

echo  [OK] Kette %SEL_CHAIN% gestartet (neues Fenster).
echo.
pause
