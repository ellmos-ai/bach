@echo off
REM ============================================================
REM BACH Agent Starter - Interaktives Menue
REM Scannt Agenten und Experten, startet Claude mit SKILL.md
REM ============================================================
title BACH Agent Starter
setlocal enabledelayedexpansion

set "BACH_DIR=%~dp0..\..\system"
set "AGENTS_DIR=%BACH_DIR%\agents"
set "EXPERTS_DIR=%BACH_DIR%\agents\_experts"

echo.
echo  ===================================================
echo   BACH Agent Starter
echo  ===================================================
echo.

REM --- Agenten sammeln ---
set COUNT=0

echo  --- Agenten (Bosse) ---
for /D %%A in ("%AGENTS_DIR%\*") do (
    if exist "%%A\SKILL.md" (
        if /I not "%%~nxA"=="_experts" (
            set /A COUNT+=1
            set "AGENT_!COUNT!=%%~nxA"
            set "AGENT_TYPE_!COUNT!=agent"
            set "AGENT_PATH_!COUNT!=%%A"
            echo   [!COUNT!]  %%~nxA
        )
    )
)

echo.
echo  --- Experten ---
for /D %%E in ("%EXPERTS_DIR%\*") do (
    if exist "%%E\SKILL.md" (
        set /A COUNT+=1
        set "AGENT_!COUNT!=%%~nxE"
        set "AGENT_TYPE_!COUNT!=expert"
        set "AGENT_PATH_!COUNT!=%%E"
        echo   [!COUNT!]  %%~nxE
    )
)

echo.
echo  [0]  Abbrechen
echo.

if %COUNT%==0 (
    echo  Keine Agenten mit SKILL.md gefunden.
    pause
    exit /b 1
)

set /P CHOICE=  Auswahl (1-%COUNT%):
if "%CHOICE%"=="0" exit /b 0
if "%CHOICE%"=="" exit /b 0

REM Validierung
set "SEL_NAME=!AGENT_%CHOICE%!"
if "%SEL_NAME%"=="" (
    echo  Ungueltige Auswahl.
    pause
    exit /b 1
)

set "SEL_TYPE=!AGENT_TYPE_%CHOICE%!"
set "SEL_PATH=!AGENT_PATH_%CHOICE%!"

echo.
echo  Agent: %SEL_NAME% (%SEL_TYPE%)
echo.
echo  --- Modus waehlen ---
echo   [1]  Interaktiv (mit Bestaetigung)
echo   [2]  Autonom (volle Rechte, --dangerously-skip-permissions)
echo.
set /P MODE=  Modus (1/2):
if "%MODE%"=="" set MODE=1

echo.
echo  --- Modell waehlen ---
echo   [1]  Sonnet (Standard, empfohlen)
echo   [2]  Opus (langsamer, staerker)
echo   [3]  Haiku (schnell, guenstiger)
echo.
set /P MODEL_CHOICE=  Modell (1/2/3):
if "%MODEL_CHOICE%"=="" set MODEL_CHOICE=1

if "%MODEL_CHOICE%"=="1" set MODEL=sonnet
if "%MODEL_CHOICE%"=="2" set MODEL=opus
if "%MODEL_CHOICE%"=="3" set MODEL=haiku

REM Starte Agent via agent_start_direct.bat
if "%MODE%"=="2" (
    call "%~dp0agent_start_direct.bat" %SEL_NAME% %SEL_TYPE% autonom %MODEL%
) else (
    call "%~dp0agent_start_direct.bat" %SEL_NAME% %SEL_TYPE% interaktiv %MODEL%
)

echo.
echo  Agent %SEL_NAME% gestartet (neues Fenster).
echo.
pause
