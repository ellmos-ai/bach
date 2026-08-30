@echo off
setlocal enabledelayedexpansion
title BACH Boot Menu

REM Absoluten Pfad aufloesen (& im Pfad sicher)
pushd "%~dp0..\system"
set "SYS_DIR=%CD%"
popd
pushd "%~dp0.."
set "ROOT_DIR=%CD%"
popd
set "CHAT_DIR=!SYS_DIR!\hub\_services\chat"
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

echo   Ungueltige Auswahl.
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

echo [1/3] Starte Web-GUI (Port 8000)...
pushd "!SYS_DIR!"
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    call :kill_if_bach_gui %%a
)
start "BACH Server" /min cmd /k "set PYTHONIOENCODING=utf-8 && python gui\server.py --port 8000"
popd
echo       [OK] GUI Server gestartet

echo [2/3] Starte BACH System Tray...
set "TRAY_HOST=127.0.0.1"
if not "!BACH_HOST!"=="" set "TRAY_HOST=!BACH_HOST!"
curl -s --max-time 2 "http://!TRAY_HOST!:8081/api/status" >nul 2>&1
if !ERRORLEVEL! equ 0 (
    pushd "!CHAT_DIR!"
    start "" pythonw chat_tray.py --host "!TRAY_HOST!"
    popd
    echo       [OK] System Tray gestartet ^(verbunden mit !TRAY_HOST!:8081^)
) else (
    echo       [SKIP] System Tray uebersprungen ^(keine Control API auf !TRAY_HOST!:8081^)
    echo              Starte Chat Service mit [B] oder nutze [W] fuer Server-Modus
)

echo [3/3] Oeffne Web-GUI im Browser...
if "!BACH_NO_BROWSER!"=="1" (
    echo       [SKIP] Browser nicht geoeffnet ^(BACH_NO_BROWSER=1^)
) else (
    timeout /t 3 /nobreak >nul
    start "" "http://127.0.0.1:8000"
    echo       [OK] Browser geoeffnet
)
echo.
echo  ============================================
echo   BACH laeuft!
echo  ============================================
echo   GUI:         http://127.0.0.1:8000
echo   System Tray: Im Infobereich pruefen
echo  ============================================
echo.
echo   Zum Beenden: Tray-Icon rechtsklick -^> Beenden
echo   GUI stoppen: Ctrl+C im Server-Fenster
echo.
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
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Du hast volle Rechte. Arbeite selbststaendig an offenen Tasks, erstelle neue Features, fixe Bugs und fuehre Wartungsaufgaben durch. Frage bei Unklarheiten den User." --dangerously-skip-permissions
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
    claude --print "Starte mit lesen und ausfuehren von SKILL.md. Du hast volle Rechte. Remote-Session: Arbeite selbststaendig, der User steuert ggf. ueber Mobile. Frage bei Unklarheiten." --dangerously-skip-permissions
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

echo  Verfuegbare Agenten:
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
echo   (Telegram Bot + Control API + System Tray)
echo  ============================================
echo.
pushd "!CHAT_DIR!"
echo [1/2] Starte Telegram Bot + Control API...
start "BACH Chat Bot" cmd /k "set PYTHONIOENCODING=utf-8 && python telegram_chat.py"
timeout /t 3 /nobreak >nul
echo       [OK] Bot gestartet (Control API auf Port 8081)
echo.
echo [2/2] Starte System Tray...
start "" pythonw chat_tray.py
echo       [OK] Tray gestartet - Icon pruefen
popd
echo.
echo [OK] Chat Service laeuft
echo      Dashboard: http://127.0.0.1:8081
echo      Telegram:  @bach_assistant_bot
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

set "BACH_HOST_TARGET=%BACH_HOST%"
if "!BACH_HOST_TARGET!"=="" set "BACH_HOST_TARGET=macstudvonlukas"

echo [1/3] Pruefe Verbindung zu !BACH_HOST_TARGET!...
curl -s --max-time 5 "http://!BACH_HOST_TARGET!:8081/api/status" >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo.
    echo       [OFFLINE] !BACH_HOST_TARGET! nicht erreichbar.
    echo       Moegliche Ursachen: Tailscale nicht aktiv, Mac Studio aus
    echo       SET BACH_HOST=hostname fuer anderen Server
    echo.
    set /p "fallback=  Lokal starten stattdessen? [J/N]: "
    if /i "!fallback!"=="J" goto chat_start
    goto menu
)
echo       [OK] Control API erreichbar

echo [2/3] Starte System Tray (verbunden mit !BACH_HOST_TARGET!)...
pushd "!CHAT_DIR!"
start "" pythonw chat_tray.py --host "!BACH_HOST_TARGET!" --port 8081
popd
echo       [OK] Tray gestartet

echo [3/3] Oeffne Zugangswege...
if "!BACH_NO_BROWSER!"=="1" (
    echo       [SKIP] Browser nicht geoeffnet ^(BACH_NO_BROWSER=1^)
) else (
    timeout /t 2 /nobreak >nul
    start "" "http://!BACH_HOST_TARGET!:8000"
    echo       [OK] GUI Dashboard geoeffnet
)
echo.
echo  ============================================
echo   Verbunden mit !BACH_HOST_TARGET!
echo  ============================================
echo   GUI:       http://!BACH_HOST_TARGET!:8000
echo   Dashboard: http://!BACH_HOST_TARGET!:8081
echo   Telegram:  @bach_assistant_bot
echo  ============================================
echo.
pause
goto menu

REM ============================================================
REM  WEB-GUI
REM ============================================================
:gui
title BACH GUI Server
pushd "!SYS_DIR!"
echo  Beende alte Prozesse auf Port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    call :kill_if_bach_gui %%a
)
if exist "gui\__pycache__" rd /s /q "gui\__pycache__" >nul 2>&1
start "BACH Server" cmd /k "set PYTHONIOENCODING=utf-8 && python gui\server.py --port 8000"
timeout /t 3 >nul
if "!BACH_NO_BROWSER!"=="1" (
    echo  [SKIP] Browser nicht geoeffnet ^(BACH_NO_BROWSER=1^)
    echo  URL: http://127.0.0.1:8000
) else (
    start "" "http://127.0.0.1:8000"
)
popd
echo  [OK] GUI gestartet auf http://127.0.0.1:8000
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
set "STATUS_HOST=127.0.0.1"
if not "!BACH_HOST!"=="" set "STATUS_HOST=!BACH_HOST!"

echo  Control API (!STATUS_HOST!:8081):
pushd "!SYS_DIR!"
python -c "import urllib.request,json; r=urllib.request.urlopen('http://!STATUS_HOST!:8081/api/status'); d=json.loads(r.read()); print(f'    Backend:  {d.get(\"backend\",\"?\")}'); print(f'    Modell:   {d.get(\"model\",\"?\")}'); print(f'    Modus:    {d.get(\"mode\",\"?\")}'); print(f'    Think:    {d.get(\"think\",\"?\")}'); print(f'    Sessions: {d.get(\"sessions\",\"?\")}')" 2>nul || echo    [OFFLINE] Control API nicht erreichbar

echo.
echo  GUI (Port 8000):
curl -s --max-time 2 "http://127.0.0.1:8000/" >nul 2>&1
if !ERRORLEVEL! equ 0 ( echo    [ONLINE] ) else ( echo    [OFFLINE] )

echo.
echo  Ollama (Port 11434):
curl -s --max-time 2 "http://localhost:11434/api/tags" >nul 2>&1
if !ERRORLEVEL! equ 0 ( echo    [ONLINE] ) else ( echo    [OFFLINE] )

popd
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
for /f "tokens=2 delims=," %%p in ('wmic process where "commandline like '%%telegram_chat%%'" get processid /format:csv 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /f /pid %%p >nul 2>&1
)
for /f "tokens=2 delims=," %%p in ('wmic process where "commandline like '%%chat_tray%%'" get processid /format:csv 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /f /pid %%p >nul 2>&1
)
echo [OK] Chat Service gestoppt
pause
goto menu

REM ============================================================
REM  ERWEITERTE OPTIONEN (Submenue)
REM ============================================================
:extended_menu
cls
echo.
echo  ============================================
echo   ERWEITERTE OPTIONEN
echo  ============================================
echo.
echo   --- CLAUDE AUTO-SESSION -----------------------
echo   [1]  Auto-Session (Zeitlimit + Scope waehlbar)
echo   [2]  Endlos-Loop (Intervall waehlbar)
echo.
echo   --- WARTUNG ------------------------------------
echo   [M]  Maintenance (Recurring/Backup/Docs)
echo   [A]  Advanced Console (bach.py direkt)
echo.
echo   --- AUTOSTART ----------------------------------
echo   [C]  Autostart einrichten
echo   [R]  Autostart entfernen
echo.
echo   [Q]  Zurueck zum Hauptmenue
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

echo   Ungueltige Auswahl.
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
claude --print "Starte mit lesen und ausfuehren von SKILL.md. !SCOPE_TEXT! !TIME_TEXT!" --dangerously-skip-permissions
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
echo  Loop laeuft. Ctrl+C zum Stoppen.
echo.
pushd "!ROOT_DIR!"
:ext_loop_cycle
echo [%date% %time%] Starte Session (max !LOOP_MIN! Min)...
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite offene Tasks (P1 zuerst). Max !LOOP_MIN! Min, dann Summary und Shutdown." --max-turns !LOOP_MAX! --dangerously-skip-permissions
echo [%date% %time%] Naechste Session in !LOOP_SEC! Sekunden... (Ctrl+C = Stop)
timeout /t !LOOP_SEC! /nobreak
goto ext_loop_cycle

REM --- Wartung ---
:ext_maintenance
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Wartungsaufgaben: 1) 'bach --recurring check' 2) 'bach backup status' und ggf. 'bach backup create' 3) 'bach --maintain docs' 4) 'bach consolidate run'. Abschliessend Session-Summary und Shutdown." --dangerously-skip-permissions
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
schtasks /create /tn "BACH Chat Tray" /tr "cmd /c \"set PYTHONIOENCODING=utf-8 && pythonw !CHAT_DIR!\chat_tray.py --host 127.0.0.1\"" /sc onlogon /rl highest /f >nul 2>&1
echo [OK] Autostart-Eintrag erstellt: "BACH Chat Tray"
pause & goto extended_menu

:ext_autostart_remove
echo  Entferne Windows Autostart-Eintrag...
schtasks /delete /tn "BACH Chat Tray" /f >nul 2>&1
echo [OK] Autostart-Eintrag entfernt.
pause & goto extended_menu

REM --- Port-8000-Guard ---
REM Beendet PID %1 nur, wenn es unser eigener GUI-Server ist (Kommandozeile enthaelt
REM gui\server.py). Ein Fremdprozess auf :8000 wird NICHT beendet, sondern gemeldet -
REM vorher hat der Start jeden Listener blind gekillt (auf ASUS-GEI z.B. run_web.py).
:kill_if_bach_gui
set "BACH_PORT_OWNER="
for /f "tokens=2 delims=," %%c in ('wmic process where "processid=%1" get commandline /format:csv 2^>nul ^| findstr /i "server.py"') do set "BACH_PORT_OWNER=%%c"
if defined BACH_PORT_OWNER (
    taskkill /F /PID %1 >nul 2>&1
    echo       [OK] Alten BACH GUI-Server PID %1 beendet.
) else (
    echo       [WARN] Port 8000 gehoert PID %1 - kein BACH gui\server.py, wird NICHT beendet.
    echo              Der GUI-Start auf Port 8000 wird scheitern. Fremdprozess pruefen oder beenden.
)
exit /b

:end
echo.
echo  Auf Wiedersehen!
endlocal
exit /b 0
