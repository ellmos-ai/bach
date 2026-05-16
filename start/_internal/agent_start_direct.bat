@echo off
REM ============================================================
REM BACH Agent Direktstart
REM Usage: agent_start_direct.bat <name> <type> [autonom|interaktiv] [model]
REM   name:  Agent-Name (z.B. steuer-agent, research-agent)
REM   type:  agent oder expert
REM   mode:  autonom oder interaktiv (default: interaktiv)
REM   model: sonnet, opus, haiku (default: sonnet)
REM ============================================================
setlocal enabledelayedexpansion

set AGENT_NAME=%1
set AGENT_TYPE=%2
set AGENT_MODE=%3
set AGENT_MODEL=%4

if "%AGENT_NAME%"=="" (
    echo Fehler: Agent-Name erforderlich.
    echo Usage: agent_start_direct.bat ^<name^> ^<type^> [autonom^|interaktiv] [model]
    exit /b 1
)
if "%AGENT_TYPE%"=="" set AGENT_TYPE=agent
if "%AGENT_MODE%"=="" set AGENT_MODE=interaktiv
if "%AGENT_MODEL%"=="" set AGENT_MODEL=sonnet

set "BACH_DIR=%~dp0..\..\system"

REM SKILL.md finden
if /I "%AGENT_TYPE%"=="expert" (
    set "SKILL_PATH=%BACH_DIR%\agents\_experts\%AGENT_NAME%\SKILL.md"
) else (
    set "SKILL_PATH=%BACH_DIR%\agents\%AGENT_NAME%\SKILL.md"
)

if not exist "%SKILL_PATH%" (
    echo Fehler: SKILL.md nicht gefunden: %SKILL_PATH%
    exit /b 1
)

REM Temp-Projektverzeichnis
set PROJECT_DIR=%TEMP%\bach_agent_%AGENT_NAME%
if not exist "%PROJECT_DIR%" mkdir "%PROJECT_DIR%"

REM CLAUDE.md generieren (SKILL.md einbetten)
(
    echo # BACH Agent: %AGENT_NAME%
    echo.
    echo Du bist der BACH Agent "%AGENT_NAME%". Befolge die folgende SKILL.md
    echo als deine Identitaet und Arbeitsanweisung.
    echo.
    echo BACH System-Pfad: %BACH_DIR%
    echo Nutze die Tools und Dateien im BACH-System unter diesem Pfad.
    echo Antworte auf Deutsch.
    echo.
    echo ---
    echo.
    type "%SKILL_PATH%"
) > "%PROJECT_DIR%\CLAUDE.md"

REM Mode-Label und Flags
if /I "%AGENT_MODE%"=="autonom" (
    set MODE_LABEL=Autonom
    set PERMS=--dangerously-skip-permissions
) else (
    set MODE_LABEL=Interaktiv
    set PERMS=
)

REM Start-BAT fuer neues Fenster
(
    echo @echo off
    echo title BACH: %AGENT_NAME% [%MODE_LABEL%]
    echo cd /d "%PROJECT_DIR%"
    echo echo === BACH Agent: %AGENT_NAME% ^(%MODE_LABEL%^) ===
    echo echo Modell: %AGENT_MODEL%
    echo echo.
    echo claude --model %AGENT_MODEL% %PERMS%
    echo if not defined BACH_AUTO pause
) > "%PROJECT_DIR%\start.bat"

REM In neuem Fenster starten
start cmd /c "%PROJECT_DIR%\start.bat"

echo [OK] Agent %AGENT_NAME% gestartet [%MODE_LABEL%, %AGENT_MODEL%]
