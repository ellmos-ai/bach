@echo off
REM ============================================================
REM BACH Automatisierung - Status uebersicht
REM Zeigt Status von MarbleRun und llmauto
REM ============================================================
title BACH Automation Status
setlocal

set "LLMAUTO_DIR=%~dp0..\..\system\tools\llmauto"
set "MARBLE_DIR=%~dp0..\..\system\tools\llmauto"
set PYTHONIOENCODING=utf-8

echo.
echo  ===================================================
echo   BACH Automatisierung - Status
echo  ===================================================

echo.
echo  --- llmauto ---
if exist "%LLMAUTO_DIR%\llmauto.py" (
    cd /d "%LLMAUTO_DIR%"
    python -m llmauto chain list 2>nul
    if errorlevel 1 echo   (Fehler beim Laden)
) else (
    echo   Nicht installiert
)

echo.
echo  --- MarbleRun (integriert in llmauto) ---
if exist "%MARBLE_DIR%\llmauto.py" (
    cd /d "%MARBLE_DIR%"
    python -m llmauto chain status 2>nul
    if errorlevel 1 echo   (Fehler beim Laden)
) else (
    echo   Nicht installiert
)

echo.
pause
