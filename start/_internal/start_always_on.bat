@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM BACH Always-On Modus: Mistral Watcher + Telegram
REM ============================================================
REM Stoppen: Ctrl+C oder dieses Fenster schliessen
REM ============================================================
title BACH Always-On: Mistral Watcher

REM Absoluten Pfad auflösen (vermeidet Probleme mit & im Pfad)
pushd "%~dp0..\..\system"
set "BACH_DIR=%CD%"
popd
set "WATCHER_DIR=!BACH_DIR!\hub\_services\watcher"
set PYTHONIOENCODING=utf-8

echo.
echo  ============================================
echo   BACH ALWAYS-ON MODUS
echo   Mistral Watcher + Telegram/Discord
echo  ============================================
echo.

REM --- 1. Ollama pruefen ---
echo [1/4] Pruefe Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo       Ollama nicht erreichbar - starte Ollama...
    start "" "ollama" serve
    timeout /t 5 /nobreak >nul
    curl -s http://localhost:11434/api/tags >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo [FEHLER] Ollama konnte nicht gestartet werden!
        echo          Bitte Ollama manuell starten: ollama serve
        pause
        exit /b 1
    )
)
echo       [OK] Ollama laeuft

REM --- 2. Mistral pruefen ---
echo [2/4] Pruefe Mistral-Modell...
pushd "!BACH_DIR!"
python -c "import urllib.request,json; r=urllib.request.urlopen('http://localhost:11434/api/tags'); d=json.loads(r.read()); models=[m['name'] for m in d.get('models',[])]; print('OK' if any('istral' in m for m in models) else 'MISSING')" 2>nul | findstr "OK" >nul
if !ERRORLEVEL! neq 0 (
    echo       Mistral nicht gefunden - lade Modell...
    ollama pull mistral
    if !ERRORLEVEL! neq 0 (
        echo [FEHLER] Mistral konnte nicht geladen werden!
        popd
        pause
        exit /b 1
    )
)
popd
echo       [OK] Mistral verfuegbar

REM --- 3. Connector-Dienste starten ---
echo [3/4] Starte Connector-Dienste...

REM Temporaere Loop-Skripte via Python erstellen (vermeidet CMD-Escaping-Probleme)
python -c "bd=r'!BACH_DIR!'; open(r'%TEMP%\bach_poll_loop.bat','w').write('@echo off\nset PYTHONIOENCODING=utf-8\ncd /d \"'+bd+'\"\n:loop\necho [%%time%%] Polling Connectors...\npython hub\\_services\\connector\\queue_processor.py --action poll_and_route\ntimeout /t 30 /nobreak >nul\ngoto loop\n')"
python -c "bd=r'!BACH_DIR!'; open(r'%TEMP%\bach_dispatch_loop.bat','w').write('@echo off\nset PYTHONIOENCODING=utf-8\ncd /d \"'+bd+'\"\n:loop\necho [%%time%%] Dispatching...\npython hub\\_services\\connector\\queue_processor.py --action dispatch\ntimeout /t 30 /nobreak >nul\ngoto loop\n')"

start "BACH Connector Poll" /min "%TEMP%\bach_poll_loop.bat"
start "BACH Connector Dispatch" /min "%TEMP%\bach_dispatch_loop.bat"

echo       [OK] Connector Poll (30s) + Dispatch (30s) gestartet

REM --- 4. Watcher Daemon starten ---
echo [4/4] Starte Watcher Daemon...
echo.
echo  ============================================
echo   Alle Dienste aktiv!
echo.
echo   Telegram/Discord  -^> poll (30s)
echo   Mistral Watcher   -^> classify (15s)
echo   Antwort-Dispatch  -^> send (30s)
echo.
echo   Stop: Ctrl+C oder Fenster schliessen
echo  ============================================
echo.

REM Watcher Daemon im Vordergrund (Ctrl+C stoppt alles)
pushd "!WATCHER_DIR!"
python watcher_daemon.py
popd

REM Aufraemen wenn Watcher beendet wird
echo.
echo [INFO] Watcher beendet - stoppe Connector-Dienste...
taskkill /fi "WINDOWTITLE eq BACH Connector Poll" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq BACH Connector Dispatch" /f >nul 2>&1
del "%TEMP%\bach_poll_loop.bat" >nul 2>&1
del "%TEMP%\bach_dispatch_loop.bat" >nul 2>&1
echo [OK] Alle Dienste gestoppt.
endlocal
pause
