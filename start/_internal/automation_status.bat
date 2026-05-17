@echo off
REM ============================================================
REM BACH Automatisierung - Status uebersicht
REM Zeigt Status von MarbleRun und llmauto
REM ============================================================
title BACH Automation Status
setlocal

set "TOOLS_DIR=%~dp0..\..\system\tools"
set PYTHONIOENCODING=utf-8

echo.
echo  ===================================================
echo   BACH Automatisierung - Status
echo  ===================================================

echo.
echo  --- llmauto ---
if exist "%TOOLS_DIR%\llmauto\llmauto.py" (
    cd /d "%TOOLS_DIR%"
    python -m llmauto chain list 2>nul
    if errorlevel 1 echo   (Fehler beim Laden)
) else (
    echo   Nicht installiert
)

echo.
echo  --- Ketten-Status ---
if exist "%TOOLS_DIR%\llmauto\llmauto.py" (
    cd /d "%TOOLS_DIR%"
    python -m llmauto chain status 2>nul
    if errorlevel 1 echo   (Fehler beim Laden)
) else (
    echo   Nicht installiert
)

echo.
pause
