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
set "WATCHER_DIR=!SYS_DIR!\hub\_services\watcher"
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
echo   Personal AI Operating System v3.9.1
echo   ==================================================
echo.
echo   --- VERBINDEN ----------------------------------
echo   [W]  Buddha Connect (Server-Modus)
echo.
echo   --- BACH CHAT SERVICE --------------------------
echo   [B]  Chat Service starten (Tray + Bot)
echo   [S]  Chat Service Status
echo   [X]  Chat Service stoppen
echo.
echo   --- ALWAYS-ON (Daemon) ------------------------
echo   [A]  Watcher + Telegram
echo.
echo   --- INTERAKTIV --------------------------------
echo   [1]  User-Konsole (einfaches CLI)
echo   [2]  Advanced Console (bach.py direkt)
echo   [3]  Web-Dashboard (Port 8000)
echo   [5]  Gemini-Partner Menue
echo.
echo   --- CLAUDE AUTO-SESSIONS ----------------------
echo   [6]  Alle Tasks - 15 Min
echo   [7]  Alle Tasks - 30 Min
echo   [8]  Alle Tasks - 1 Stunde
echo   [9]  Zugewiesene Tasks - 15 Min
echo   [0]  Zugewiesene Tasks - Unbegrenzt
echo.
echo   --- CLAUDE SPEZIAL ----------------------------
echo   [F]  Full Access (skip-permissions)
echo   [P]  Remote Control (Mobile App, Bypass)
echo   [M]  Maintenance (Recurring/Backup/Docs)
echo.
echo   --- CLAUDE LOOP (Endlos) ----------------------
echo   [L]  Loop alle 15 Min
echo   [N]  Loop alle 30 Min
echo   [H]  Loop jede Stunde
echo.
echo   --- AGENTEN -----------------------------------
echo   [G]  Agent starten (Menue)
echo.
echo   --- AUTOMATISIERUNG ----------------------------
echo   [C]  Neue Kette erstellen (Chain Creator)
echo   [R]  MarbleRun Kette
echo   [U]  llmauto Kette
echo   [T]  Automation Status
echo.
echo   [Q]  Beenden
echo   ==================================================
echo.

set /p "choice=  Auswahl: "

if /i "!choice!"=="W" goto server_connect
if /i "!choice!"=="B" goto bridge_start
if /i "!choice!"=="S" goto bridge_status
if /i "!choice!"=="X" goto bridge_stop
if /i "!choice!"=="A" goto always_on
if "!choice!"=="1" goto console
if "!choice!"=="2" goto advanced
if "!choice!"=="3" goto gui
if "!choice!"=="5" goto gemini
if "!choice!"=="6" goto claude_all_15
if "!choice!"=="7" goto claude_all_30
if "!choice!"=="8" goto claude_all_1h
if "!choice!"=="9" goto claude_assigned_15
if "!choice!"=="0" goto claude_assigned_nolimit
if /i "!choice!"=="F" goto claude_full
if /i "!choice!"=="P" goto claude_rc
if /i "!choice!"=="M" goto claude_maintenance
if /i "!choice!"=="L" goto loop_15
if /i "!choice!"=="N" goto loop_30
if /i "!choice!"=="H" goto loop_1h
if /i "!choice!"=="G" goto agent_start
if /i "!choice!"=="C" goto automation_create
if /i "!choice!"=="R" goto automation_marblerun
if /i "!choice!"=="U" goto automation_llmauto
if /i "!choice!"=="T" goto automation_status
if /i "!choice!"=="Q" goto end

echo   Ungueltige Auswahl.
timeout /t 2 >nul
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
    echo.
    echo       Moegliche Ursachen:
    echo         - Tailscale nicht aktiv
    echo         - Mac Studio ausgeschaltet
    echo         - Anderer Host? SET BACH_HOST=hostname
    echo.
    set /p "fallback=  Lokal starten stattdessen? [J/N]: "
    if /i "!fallback!"=="J" goto bridge_start
    goto menu
)
echo       [OK] Control API erreichbar

echo [2/3] Starte System Tray (verbunden mit !BACH_HOST_TARGET!)...
pushd "!CHAT_DIR!"
start "" pythonw chat_tray.py --host "!BACH_HOST_TARGET!" --port 8081
popd
echo       [OK] Tray gestartet

echo [3/3] Oeffne Zugangswege...
timeout /t 2 /nobreak >nul
start "" "http://!BACH_HOST_TARGET!:8000"
echo       [OK] GUI Dashboard geoeffnet
echo.
echo  ============================================
echo   Verbunden mit !BACH_HOST_TARGET!
echo  ============================================
echo   GUI:       http://!BACH_HOST_TARGET!:8000
echo   Dashboard: http://!BACH_HOST_TARGET!:8081
echo   Telegram:  @bach_assistant_bot
echo   Tray:      System Tray (Icon pruefen)
echo  ============================================
echo.
echo   Tipp: SET BACH_HOST=anderer-host fuer anderen Server
echo.
pause
goto menu

REM ============================================================
REM  BACH CHAT SERVICE (Telegram Bot + Control API + Tray)
REM ============================================================
:bridge_start
title BACH Chat Service Start
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

:bridge_status
title BACH Chat Service Status
cls
echo.
echo  ============================================
echo   BACH CHAT SERVICE - Status
echo  ============================================
echo.
set "STATUS_HOST=127.0.0.1"
if not "!BACH_HOST!"=="" set "STATUS_HOST=!BACH_HOST!"
pushd "!SYS_DIR!"
python -c "import urllib.request,json; r=urllib.request.urlopen('http://!STATUS_HOST!:8081/api/status'); d=json.loads(r.read()); print(f'  Host:     !STATUS_HOST!'); print(f'  Backend:  {d.get(\"backend\",\"?\")}'); print(f'  Modell:   {d.get(\"model\",\"?\")}'); print(f'  Modus:    {d.get(\"mode\",\"?\")}'); print(f'  Think:    {d.get(\"think\",\"?\")}'); print(f'  Sessions: {d.get(\"sessions\",\"?\")}')" 2>nul || echo [WARN] Control API nicht erreichbar (!STATUS_HOST!:8081)
popd
echo.
pause
goto menu

:bridge_stop
title BACH Chat Service Stop
cls
echo.
echo  ============================================
echo   BACH CHAT SERVICE - Stop
echo  ============================================
echo.
echo [INFO] Stoppe Telegram Bot...
for /f "tokens=2 delims=," %%p in ('wmic process where "commandline like '%%telegram_chat%%'" get processid /format:csv 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /f /pid %%p >nul 2>&1
)
echo [INFO] Stoppe System Tray...
for /f "tokens=2 delims=," %%p in ('wmic process where "commandline like '%%chat_tray%%'" get processid /format:csv 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /f /pid %%p >nul 2>&1
)
echo.
echo [OK] Chat Service gestoppt
pause
goto menu

REM ============================================================
REM  ALWAYS-ON: Mistral Watcher + Telegram
REM ============================================================
:always_on
title BACH Always-On: Mistral Watcher
cls
echo.
echo  ============================================
echo   BACH ALWAYS-ON MODUS
echo   Mistral Watcher + Telegram/Discord
echo  ============================================
echo.

echo [1/4] Pruefe Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo       Ollama nicht erreichbar - starte Ollama...
    start "" "ollama" serve
    timeout /t 5 /nobreak >nul
    curl -s http://localhost:11434/api/tags >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo [FEHLER] Ollama konnte nicht gestartet werden!
        pause
        goto menu
    )
)
echo       [OK] Ollama laeuft

echo [2/4] Pruefe Mistral-Modell...
pushd "!SYS_DIR!"
python -c "import urllib.request,json; r=urllib.request.urlopen('http://localhost:11434/api/tags'); d=json.loads(r.read()); models=[m['name'] for m in d.get('models',[])]; print('OK' if any('istral' in m for m in models) else 'MISSING')" 2>nul | findstr "OK" >nul
if !ERRORLEVEL! neq 0 (
    echo       Mistral nicht gefunden - lade Modell...
    ollama pull mistral
    if !ERRORLEVEL! neq 0 (
        echo [FEHLER] Mistral konnte nicht geladen werden!
        popd
        pause
        goto menu
    )
)
popd
echo       [OK] Mistral verfuegbar

echo [3/4] Starte Connector-Dienste...
python -c "bd=r'!SYS_DIR!'; open(r'%TEMP%\bach_poll_loop.bat','w').write('@echo off\nset PYTHONIOENCODING=utf-8\ncd /d \"'+bd+'\"\n:loop\necho [%%time%%] Polling Connectors...\npython hub\\_services\\connector\\queue_processor.py --action poll_and_route\ntimeout /t 30 /nobreak >nul\ngoto loop\n')"
python -c "bd=r'!SYS_DIR!'; open(r'%TEMP%\bach_dispatch_loop.bat','w').write('@echo off\nset PYTHONIOENCODING=utf-8\ncd /d \"'+bd+'\"\n:loop\necho [%%time%%] Dispatching...\npython hub\\_services\\connector\\queue_processor.py --action dispatch\ntimeout /t 30 /nobreak >nul\ngoto loop\n')"
start "BACH Connector Poll" /min "%TEMP%\bach_poll_loop.bat"
start "BACH Connector Dispatch" /min "%TEMP%\bach_dispatch_loop.bat"
echo       [OK] Connector Poll + Dispatch (30s) gestartet

echo [4/4] Starte Watcher Daemon...
echo.
echo  ============================================
echo   Alle Dienste aktiv!
echo   Telegram -^> poll (30s) -^> Mistral (15s) -^> Antwort (30s)
echo   Stop: Ctrl+C oder Fenster schliessen
echo  ============================================
echo.

pushd "!WATCHER_DIR!"
python watcher_daemon.py
popd

echo.
echo [INFO] Watcher beendet - stoppe Connector-Dienste...
taskkill /fi "WINDOWTITLE eq BACH Connector Poll" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq BACH Connector Dispatch" /f >nul 2>&1
del "%TEMP%\bach_poll_loop.bat" >nul 2>&1
del "%TEMP%\bach_dispatch_loop.bat" >nul 2>&1
echo [OK] Alle Dienste gestoppt.
pause
goto menu

REM ============================================================
REM  INTERAKTIV
REM ============================================================
:console
title BACH User-Konsole
pushd "!SYS_DIR!"
python tools\user_console.py
popd
pause
goto menu

:advanced
title BACH Advanced Console
pushd "!SYS_DIR!"
echo =====================================================
echo  BACH Advanced Console v2.0
echo =====================================================
echo.
echo  Befehle:  python bach.py help ^| task list ^| --status
echo  Beenden:  exit
echo =====================================================
echo.
cmd /k "set PATH=%CD%;%PATH% && set PYTHONIOENCODING=utf-8"
popd
goto menu

:gui
title BACH GUI Server
pushd "!SYS_DIR!"
echo  Beende alte Prozesse auf Port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
if exist "gui\__pycache__" rd /s /q "gui\__pycache__" >nul 2>&1
set TIMESTAMP=%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%
set TIMESTAMP=!TIMESTAMP: =0!
start "BACH Server" cmd /k python gui\server.py --port 8000
timeout /t 3 >nul
start "" "http://127.0.0.1:8000?nocache=!TIMESTAMP!"
popd
echo  [OK] GUI gestartet auf http://127.0.0.1:8000
pause
goto menu

:gemini
title BACH Gemini Starter
pushd "!SYS_DIR!"
:gemini_menu
cls
echo ============================================================
echo   BACH GEMINI STARTER
echo ============================================================
echo   [D] Default (1 Task)
echo   [B] Bulk (Alle zugewiesenen Tasks)
echo   [A] Auto (2 Tasks, headless)
echo   [N] Analyse       [R] Research
echo   [W] Wiki-Update   [H] Help-Update
echo   [O] Docs-Update   [F] Frei (Interaktiv)
echo   [Q] Zurueck zum Hauptmenue
echo ============================================================
echo.
set /p "gchoice=  Auswahl: "
if /i "!gchoice!"=="D" ( python tools\partner_communication\gemini_start.py --gui --tasks 1 & goto gemini_menu )
if /i "!gchoice!"=="B" ( python tools\partner_communication\gemini_start.py --gui --bulk & goto gemini_menu )
if /i "!gchoice!"=="A" ( python tools\partner_communication\gemini_start.py --cli --auto & goto gemini_menu )
if /i "!gchoice!"=="N" ( python tools\partner_communication\gemini_start.py --gui --mode analyse & goto gemini_menu )
if /i "!gchoice!"=="R" ( python tools\partner_communication\gemini_start.py --gui --mode research & goto gemini_menu )
if /i "!gchoice!"=="W" ( python tools\partner_communication\gemini_start.py --gui --mode wiki-update & goto gemini_menu )
if /i "!gchoice!"=="H" ( python tools\partner_communication\gemini_start.py --gui --mode help-update & goto gemini_menu )
if /i "!gchoice!"=="O" ( python tools\partner_communication\gemini_start.py --gui --mode docs-update & goto gemini_menu )
if /i "!gchoice!"=="F" ( python tools\partner_communication\gemini_start.py --gui --default & goto gemini_menu )
if /i "!gchoice!"=="Q" ( popd & goto menu )
echo Ungueltige Auswahl.
timeout /t 2 >nul
goto gemini_menu

REM ============================================================
REM  CLAUDE AUTO-SESSIONS
REM ============================================================
:claude_all_15
title BACH Auto: Alle Tasks (15min)
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann offene Tasks aus 'bach task list' - waehle selbststaendig die wichtigsten aus (P1 zuerst). Arbeite maximal 15 Minuten, dann fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

:claude_all_30
title BACH Auto: Alle Tasks (30min)
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann offene Tasks aus 'bach task list' - waehle selbststaendig die wichtigsten aus (P1 zuerst). Arbeite maximal 30 Minuten, dann fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

:claude_all_1h
title BACH Auto: Alle Tasks (1h)
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann offene Tasks aus 'bach task list' - waehle selbststaendig die wichtigsten aus (P1 zuerst). Arbeite maximal 60 Minuten, dann fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

:claude_assigned_15
title BACH Auto: Zugewiesene Tasks (15min)
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann NUR dir (Claude) zugewiesene Tasks aus 'bach task list'. Arbeite maximal 15 Minuten, dann fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

:claude_assigned_nolimit
title BACH Auto: Zugewiesene Tasks (unbegrenzt)
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite dann NUR dir (Claude) zugewiesene Tasks aus 'bach task list'. Arbeite alle zugewiesenen Tasks ab. Nach jeder erledigten Aufgabe pruefe ob weitere zugewiesene Tasks offen sind. Wenn alle erledigt sind, fuehre 'bach --memory session' mit einer Zusammenfassung aus und beende mit 'bach --shutdown'."
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

REM ============================================================
REM  CLAUDE SPEZIAL
REM ============================================================
:claude_full
title BACH Claude: Full Access
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Du hast volle Rechte. Arbeite selbststaendig an offenen Tasks, erstelle neue Features, fixe Bugs und fuehre Wartungsaufgaben durch. Nutze 'bach --recurring check' fuer faellige periodische Aufgaben. Frage bei Unklarheiten den User." --dangerously-skip-permissions
popd
echo.
echo [FERTIG] Session beendet.
pause
goto menu

:claude_rc
title BACH Claude: Remote Control
call "%~dp0_internal\claude_remote_control.bat"
goto menu

:claude_maintenance
title BACH Auto: Wartung
pushd "!ROOT_DIR!"
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Fuehre dann folgende Wartungsaufgaben durch: 1) 'bach --recurring check' fuer faellige periodische Tasks 2) 'bach backup status' und bei Bedarf 'bach backup create' 3) 'bach --maintain docs' fuer Dokumentations-Check 4) 'bach consolidate run' fuer Memory-Konsolidierung. Erstelle abschliessend eine Session-Zusammenfassung mit 'bach --memory session' und beende mit 'bach --shutdown'."
popd
echo.
echo [FERTIG] Wartung beendet.
pause
goto menu

REM ============================================================
REM  CLAUDE LOOP (Endlos)
REM ============================================================
:loop_15
title BACH Loop: Alle 15 Min
pushd "!ROOT_DIR!"
:loop_15_cycle
echo.
echo [%date% %time%] Starte neue BACH-Session...
echo ============================================================
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite offene Tasks aus 'bach task list' (P1 zuerst). Arbeite maximal 12 Minuten, dann fuehre 'bach --memory session' mit Zusammenfassung aus und beende mit 'bach --shutdown'." --max-turns 40
echo.
echo [%date% %time%] Session beendet. Naechste in 15 Minuten... (Ctrl+C = Stop)
timeout /t 900 /nobreak
goto loop_15_cycle

:loop_30
title BACH Loop: Alle 30 Min
pushd "!ROOT_DIR!"
:loop_30_cycle
echo.
echo [%date% %time%] Starte neue BACH-Session...
echo ============================================================
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite offene Tasks aus 'bach task list' (P1 zuerst). Arbeite maximal 25 Minuten, dann fuehre 'bach --memory session' mit Zusammenfassung aus und beende mit 'bach --shutdown'." --max-turns 80
echo.
echo [%date% %time%] Session beendet. Naechste in 30 Minuten... (Ctrl+C = Stop)
timeout /t 1800 /nobreak
goto loop_30_cycle

:loop_1h
title BACH Loop: Jede Stunde
pushd "!ROOT_DIR!"
:loop_1h_cycle
echo.
echo [%date% %time%] Starte neue BACH-Session...
echo ============================================================
claude --print "Starte mit lesen und ausfuehren von SKILL.md. Bearbeite offene Tasks aus 'bach task list' (P1 zuerst). Arbeite maximal 50 Minuten, dann fuehre 'bach --memory session' mit Zusammenfassung aus und beende mit 'bach --shutdown'." --max-turns 150
echo.
echo [%date% %time%] Session beendet. Naechste in 1 Stunde... (Ctrl+C = Stop)
timeout /t 3600 /nobreak
goto loop_1h_cycle

REM ============================================================
REM  AGENTEN
REM ============================================================
:agent_start
title BACH Agent Starter
call "%~dp0_internal\agent_start.bat"
goto menu

REM ============================================================
REM  AUTOMATISIERUNG
REM ============================================================
:automation_create
title BACH Chain Creator
call "%~dp0_internal\automation_create.bat"
goto menu

:automation_marblerun
title BACH MarbleRun
call "%~dp0_internal\automation_marblerun.bat"
goto menu

:automation_llmauto
title BACH llmauto
call "%~dp0_internal\automation_llmauto.bat"
goto menu

:automation_status
title BACH Automation Status
call "%~dp0_internal\automation_status.bat"
goto menu

REM ============================================================
:end
endlocal
exit
