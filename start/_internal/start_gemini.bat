@echo off
setlocal
REM Ins System-Verzeichnis wechseln
cd /d "%~dp0..\system"
set PYTHONIOENCODING=utf-8

:menu
cls
echo ============================================================
echo   BACH GEMINI STARTER
echo ============================================================
echo   [D] Default (1 Task)
echo   [B] Bulk (Alle zugewiesenen Tasks)
echo   [A] Auto (2 Tasks, headless)
echo   [N] Analyse (prompts/analyse.txt)
echo   [R] Research (prompts/research.txt)
echo   [W] Wiki-Update (prompts/wiki-update.txt)
echo   [H] Help-Update (prompts/help-update.txt)
echo   [O] Docs-Update (prompts/docs-update.txt)
echo   [F] Frei (Interaktiver Modus)
echo   [C] Close (Beenden)
echo ============================================================
echo.

set /p choice="Waehle eine Option: "

if /i "%choice%"=="D" goto start_default
if /i "%choice%"=="B" goto start_bulk
if /i "%choice%"=="A" goto start_auto
if /i "%choice%"=="N" goto start_analyse
if /i "%choice%"=="R" goto start_research
if /i "%choice%"=="W" goto start_wiki
if /i "%choice%"=="H" goto start_help
if /i "%choice%"=="O" goto start_docs
if /i "%choice%"=="F" goto start_frei
if /i "%choice%"=="C" goto end

echo Ungueltige Auswahl.
pause
goto menu

:start_default
python tools\partner_communication\gemini_start.py --gui --tasks 1
goto menu

:start_bulk
python tools\partner_communication\gemini_start.py --gui --bulk
goto menu

:start_auto
python tools\partner_communication\gemini_start.py --cli --auto
goto menu

:start_analyse
python tools\partner_communication\gemini_start.py --gui --mode analyse
goto menu

:start_research
python tools\partner_communication\gemini_start.py --gui --mode research
goto menu

:start_wiki
python tools\partner_communication\gemini_start.py --gui --mode wiki-update
goto menu

:start_help
python tools\partner_communication\gemini_start.py --gui --mode help-update
goto menu

:start_docs
python tools\partner_communication\gemini_start.py --gui --mode docs-update
goto menu

:start_frei
python tools\partner_communication\gemini_start.py --gui --default
goto menu

:end
exit
