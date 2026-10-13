@echo off
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
REM Optional settings come from the user environment; no permissions are changed.
python -c "import taskplan.startcenter" >nul 2>&1
if errorlevel 1 (
  echo [FEHLER] TASKPLAN mit Startcenter fehlt. Installiere die Version mit Starter-Ressourcen.
  exit /b 2
)
python -m taskplan startcenter --role pingpong %*
exit /b %ERRORLEVEL%
