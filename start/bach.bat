@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title BACH Boot Menu

REM Absoluten Pfad auflösen (& im Pfad sicher)
pushd "%~dp0..\system"
set "SYS_DIR=%CD%"
popd
pushd "%~dp0.."
set "ROOT_DIR=%CD%"
popd
set "CHAT_DIR=!SYS_DIR!\hub\_services\chat"
set "STARTSPINE=!ROOT_DIR!\start\startspine.py"
set PYTHONIOENCODING=utf-8

:menu
cls
echo.
echo   ______   ______   ______   __  __
echo  /\  == \ /\  __ \ /\  ___\ /\ \_\ \
echo  \ \  __^< \ \  __ \\ \ \____\ \  __ \
echo   \ \_____\\ \_\ \_\\ \_____\\ \_\ \_\
echo    \/_____/ \/_/\/_/ \/_____/ \/_/\/_/
echo.
echo   Personal AI Operating System v3.13.0
echo   ==================================================
echo.
echo   --- SCHNELLSTART --------------------------------
echo   [D]  Default Start (GUI + System Tray)
echo.
echo   --- KONSOLEN ------------------------------------
echo   [1]  Claude Code (lokal, volle Rechte)
echo   [2]  Claude Code (remote, volle Rechte)
echo   [3]  Codex Konsole
echo   [4]  Agent beauftragen
echo.
echo   --- DIENSTE -------------------------------------
echo   [B]  Chat Service (Telegram Bot + Tray)
echo   [W]  Buddha Connect (Server-Modus)
echo   [G]  Web-GUI starten (Port 8000)
echo   [S]  Status anzeigen
echo   [X]  Chat Service stoppen
echo.
echo   --- ERWEITERT -----------------------------------
echo   [E]  Erweiterte Optionen (Loops, Sessions, ...)
echo.
echo   [Q]  Beenden
echo   ==================================================
echo.

set /p "choice=  Auswahl: "

if /i "!choice!"=="D" goto default_start
if "!choice!"=="1" goto claude_local
if "!choice!"=="2" goto claude_remote
if "!choice!"=="3" goto codex_console
if "!choice!"=="4" goto agent_start
if /i "!choice!"=="B" goto chat_start
if /i "!choice!"=="W" goto server_connect
if /i "!choice!"=="G" goto gui
if /i "!choice!"=="S" goto status
if /i "!choice!"=="X" goto chat_stop
if /i "!choice!"=="E" goto extended_menu
if /i "!choice!"=="Q" goto end

echo   Ungültige Auswahl.
timeout /t 2 >nul
goto menu

REM ============================================================
REM  DEFAULT START (GUI + System Tray)
REM ============================================================
:default_start
title BACH Default Start
cls
echo.
echo  ============================================
echo   BACH DEFAULT START
echo   Web-GUI + System Tray
echo  ============================================
echo.

python "!STARTSPINE!" start --gui --tray --open-browser
if errorlevel 1 (
    echo.
    echo [FEHLER] Mindestens ein erforderlicher Dienst ist nicht bereit.
) else (
    echo.
    echo [OK] Erforderliche Dienste sind bereit. Optionale Details stehen im Status.
)
pause
goto menu

REM ============================================================
REM  CLAUDE CODE (lokal, volle Rechte)
REM ============================================================
:claude_local
title BACH Claude Code (lokal)
cls
echo.
echo  ============================================
echo   CLAUDE CODE - Lokale Session
echo   Volle Rechte (skip-permissions)
echo  ============================================
echo.
pushd "!ROOT_DIR!"
claude --print "Starte mit Lesen und Ausführen von SKILL.md. Du hast volle Rechte. Arbeite selbstständig an offenen Tasks, erstelle neue Features, fixe Bugs und führe Wartungsaufgaben durch. Frage bei Unklarheiten den User." --dangerously-skip-permissions
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

REM ============================================================
REM  CLAUDE CODE (remote, volle Rechte)
REM ============================================================
:claude_remote
title BACH Claude Code (remote)
cls
echo.
echo  ============================================
echo   CLAUDE CODE - Remote Session
echo   Volle Rechte + Fernzugriff (Mobile App)
echo  ============================================
echo.
pushd "!ROOT_DIR!"
if exist "%~dp0_internal\claude_remote_control.py" (
    python "%~dp0_internal\claude_remote_control.py"
) else (
    claude --print "Starte mit Lesen und Ausführen von SKILL.md. Du hast volle Rechte. Remote-Session: Arbeite selbstständig, der User steuert ggf. über Mobile. Frage bei Unklarheiten." --dangerously-skip-permissions
)
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

REM ============================================================
REM  CODEX KONSOLE
REM ============================================================
:codex_console
title BACH Codex Konsole
cls
echo.
echo  ============================================
echo   CODEX KONSOLE
echo  ============================================
echo.
pushd "!ROOT_DIR!"
where codex >nul 2>&1
if !ERRORLEVEL! equ 0 (
    codex
) else (
    echo [FEHLER] Codex nicht gefunden.
    echo Installieren: npm install -g @openai/codex
)
popd
echo.
pause
goto menu

REM ============================================================
REM  AGENT BEAUFTRAGEN
REM ============================================================
:agent_start
title BACH Agent Starter
cls
echo.
echo  ============================================
echo   AGENT BEAUFTRAGEN
echo  ============================================
echo.
pushd "!SYS_DIR!"

echo  Verfügbare Agenten:
echo  -------------------------------------------
REM Agenten sind Ordner mit SKILL.md (seit v2.6), keine .json-Dateien
python -c "import os; adir='agents'; names=[d for d in sorted(os.listdir(adir)) if os.path.isdir(os.path.join(adir,d)) and not d.startswith(('_','.')) and os.path.isfile(os.path.join(adir,d,'SKILL.md'))]; [print(f'  [{i+1}] {n}') for i,n in enumerate(names)]" 2>nul
echo  -------------------------------------------
echo.
set /p "agent_choice=  Agent-Name (wie in der Liste): "
set /p "agent_task=  Aufgabe: "
set /p "agent_model=  Modell [S]onnet/[O]pus/[H]aiku (default: S): "

set "MODEL_FLAG=--model sonnet"
if /i "!agent_model!"=="O" set "MODEL_FLAG=--model opus"
if /i "!agent_model!"=="H" set "MODEL_FLAG=--model haiku"

if not exist "agents\!agent_choice!\SKILL.md" (
    echo.
    echo [FEHLER] Agent "!agent_choice!" nicht gefunden ^(agents\!agent_choice!\SKILL.md fehlt^).
    popd
    pause
    goto agent_start
)

echo.
echo  Starte Agent "!agent_choice!" mit Aufgabe...
claude !MODEL_FLAG! --print "Lies agents/!agent_choice!/SKILL.md und agiere als dieser Agent. Aufgabe: !agent_task!" --dangerously-skip-permissions
popd
echo.
echo [FERTIG] Agent-Session beendet.
pause
goto menu

REM ============================================================
REM  CHAT SERVICE (Telegram Bot + Tray)
REM ============================================================
:chat_start
title BACH Chat Service
cls
echo.
echo  ============================================
echo   BACH CHAT SERVICE - Start
echo   Telegram Bot + Control API + System Tray
echo  ============================================
echo.
python "!STARTSPINE!" start --chat --tray
if errorlevel 1 echo [FEHLER] Chat/Control ist nicht bereit. Details stehen im Startspine-Log.
pause
goto menu

REM ============================================================
REM  SERVER-MODUS (Buddha Connect)
REM ============================================================
:server_connect
title BACH Server Connect
cls
echo.
echo  ============================================
echo   BUDDHA CONNECT - Server-Modus
echo  ============================================
echo.

set "BACH_HOST_TARGET=!BACH_HOST!"
if "!BACH_HOST_TARGET!"=="" set "BACH_HOST_TARGET=macstudvonlukas"
set "REMOTE_GUI_PORT=!BACH_GUI_PORT!"
if "!REMOTE_GUI_PORT!"=="" set "REMOTE_GUI_PORT=8000"

echo Starte System Tray für !BACH_HOST_TARGET!; bei Offline-Status verbindet er sich später neu.
python "!STARTSPINE!" start --tray --host "!BACH_HOST_TARGET!"
echo.
python "!STARTSPINE!" status --host "!BACH_HOST_TARGET!"
if "!BACH_NO_BROWSER!"=="1" (
    echo [SKIP] Browser nicht geöffnet ^(BACH_NO_BROWSER=1^)
) else (
    start "" "http://!BACH_HOST_TARGET!:!REMOTE_GUI_PORT!"
)
pause
goto menu

REM ============================================================
REM  WEB-GUI
REM ============================================================
:gui
title BACH GUI Server
python "!STARTSPINE!" start --gui --open-browser
if errorlevel 1 echo [FEHLER] GUI ist nicht bereit. Details stehen im Startspine-Log.
pause
goto menu

REM ============================================================
REM  STATUS
REM ============================================================
:status
title BACH Status
cls
echo.
echo  ============================================
echo   BACH SYSTEM STATUS
echo  ============================================
echo.
set "STATUS_HOST=!BACH_HOST!"
if "!STATUS_HOST!"=="" set "STATUS_HOST=127.0.0.1"
python "!STARTSPINE!" status --host "!STATUS_HOST!"
echo.
pause
goto menu

REM ============================================================
REM  CHAT SERVICE STOP
REM ============================================================
:chat_stop
title BACH Chat Service Stop
cls
echo.
echo  Stoppe Chat Service...
python "!STARTSPINE!" stop --services chat,tray
pause
goto menu

REM ============================================================
REM  ERWEITERTE OPTIONEN (Untermenü)
REM ============================================================
:extended_menu
cls
echo.
echo  ============================================
echo   ERWEITERTE OPTIONEN
echo  ============================================
echo.
echo   --- CLAUDE AUTO-SESSION -----------------------
echo   [1]  Auto-Session (Zeitlimit + Scope wählbar)
echo   [2]  Endlos-Loop (Intervall wählbar)
echo.
echo   --- WARTUNG ------------------------------------
echo   [M]  Maintenance (Recurring/Backup/Docs)
echo   [A]  Advanced Console (bach.py direkt)
echo.
echo   --- AUTOSTART ----------------------------------
echo   [C]  Autostart einrichten
echo   [R]  Autostart entfernen
echo.
echo   [Q]  Zurück zum Hauptmenü
echo  ============================================
echo.

set /p "echoice=  Auswahl: "

if "!echoice!"=="1" goto ext_auto_session
if "!echoice!"=="2" goto ext_loop
if /i "!echoice!"=="M" goto ext_maintenance
if /i "!echoice!"=="A" goto ext_advanced
if /i "!echoice!"=="C" goto ext_autostart
if /i "!echoice!"=="R" goto ext_autostart_remove
if /i "!echoice!"=="Q" goto menu

echo   Ungültige Auswahl.
timeout /t 2 >nul
goto extended_menu

REM --- Claude Auto-Session (konsolidiert) ---
:ext_auto_session
cls
echo.
echo  ============================================
echo   CLAUDE AUTO-SESSION
echo  ============================================
echo.
echo  Zeitlimit:
echo   [1] 15 Minuten   [2] 30 Minuten   [3] 1 Stunde   [4] Unbegrenzt
set /p "atime=  Zeitlimit: "
set "MAX_MIN=15"
set "MAX_TURNS="
if "!atime!"=="1" set "MAX_MIN=15"
if "!atime!"=="2" set "MAX_MIN=30"
if "!atime!"=="3" set "MAX_MIN=60"
if "!atime!"=="4" set "MAX_MIN=0"
echo.
echo  Scope:
echo   [A] Alle offenen Tasks   [Z] Nur zugewiesene Tasks
set /p "ascope=  Scope: "
set "SCOPE_TEXT=Bearbeite offene Tasks aus 'bach task list' (P1 zuerst)."
if /i "!ascope!"=="Z" set "SCOPE_TEXT=Bearbeite NUR dir (Claude) zugewiesene Tasks."
set "TIME_TEXT=Arbeite maximal !MAX_MIN! Minuten, dann Session-Summary und Shutdown."
if "!MAX_MIN!"=="0" set "TIME_TEXT=Arbeite alle Tasks ab, dann Session-Summary und Shutdown."
echo.
pushd "!ROOT_DIR!"
claude --print "Starte mit Lesen und Ausführen von SKILL.md. !SCOPE_TEXT! !TIME_TEXT!" --dangerously-skip-permissions
popd
echo.
echo [FERTIG] Session beendet.
pause
goto extended_menu

REM --- Claude Endlos-Loop (konsolidiert) ---
:ext_loop
cls
echo.
echo  ============================================
echo   CLAUDE ENDLOS-LOOP
echo  ============================================
echo.
echo  Intervall zwischen Sessions:
echo   [1] 15 Minuten   [2] 30 Minuten   [3] 1 Stunde
set /p "lint=  Intervall: "
set "LOOP_SEC=900"
set "LOOP_MAX=40"
set "LOOP_MIN=12"
if "!lint!"=="1" ( set "LOOP_SEC=900" & set "LOOP_MAX=40" & set "LOOP_MIN=12" )
if "!lint!"=="2" ( set "LOOP_SEC=1800" & set "LOOP_MAX=80" & set "LOOP_MIN=25" )
if "!lint!"=="3" ( set "LOOP_SEC=3600" & set "LOOP_MAX=150" & set "LOOP_MIN=50" )
echo.
echo  Loop läuft. Ctrl+C zum Stoppen.
echo.
pushd "!ROOT_DIR!"
:ext_loop_cycle
echo [%date% %time%] Starte Session (max !LOOP_MIN! Min)...
claude --print "Starte mit Lesen und Ausführen von SKILL.md. Bearbeite offene Tasks (P1 zuerst). Max !LOOP_MIN! Min, dann Summary und Shutdown." --max-turns !LOOP_MAX! --dangerously-skip-permissions
echo [%date% %time%] Nächste Session in !LOOP_SEC! Sekunden... (Ctrl+C = Stop)
timeout /t !LOOP_SEC! /nobreak
goto ext_loop_cycle

REM --- Wartung ---
:ext_maintenance
pushd "!ROOT_DIR!"
claude --print "Starte mit Lesen und Ausführen von SKILL.md. Wartungsaufgaben: 1) 'bach --recurring check' 2) 'bach backup status' und ggf. 'bach backup create' 3) 'bach --maintain docs' 4) 'bach consolidate run'. Abschließend Session-Summary und Shutdown." --dangerously-skip-permissions
popd
pause & goto extended_menu

REM --- Advanced Console ---
:ext_advanced
pushd "!SYS_DIR!"
echo =====================================================
echo  BACH Advanced Console
echo  Befehle: python bach.py help ^| task list ^| --status
echo  Beenden: exit
echo =====================================================
cmd /k "set PATH=%CD%;%PATH% && set PYTHONIOENCODING=utf-8"
popd
goto extended_menu

REM --- Autostart ---
:ext_autostart
echo  Erstelle Windows Autostart-Eintrag...
python "!STARTSPINE!" autostart-install
pause & goto extended_menu

:ext_autostart_remove
echo  Entferne Windows Autostart-Eintrag...
python "!STARTSPINE!" autostart-remove
pause & goto extended_menu

:end
echo.
echo  Auf Wiedersehen!
endlocal
exit /b 0
