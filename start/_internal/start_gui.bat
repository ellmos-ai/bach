@echo off
REM =====================================================
REM  BACH GUI Server starten (Debug Modus)
REM =====================================================

REM Ins System-Verzeichnis wechseln
cd /d "%~dp0..\system"
set PYTHONIOENCODING=utf-8

echo  BACH GUI Server
echo  ================
echo.

REM Alten Server auf Port 8000 beenden (falls er noch laeuft)
echo  Beende alte Prozesse...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM Python Cache loeschen
echo  Loesche Python Cache...
if exist "gui\__pycache__" rd /s /q "gui\__pycache__" >nul 2>&1
if exist "hub\__pycache__" rd /s /q "hub\__pycache__" >nul 2>&1
if exist "tools\__pycache__" rd /s /q "tools\__pycache__" >nul 2>&1

REM Cache-Buster Timestamp
set TIMESTAMP=%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%

echo  Starte Server...

REM WICHTIG: "cmd /k" haelt das Fenster offen, damit du Fehlermeldungen siehst!
start "BACH Server Log - NICHT SCHLIESSEN" cmd /k "set PYTHONIOENCODING=utf-8 && python gui\server.py --port 8000"

REM Kurz warten
timeout /t 3 >nul

REM Browser oeffnen MIT Cache-Buster Parameter
if defined BACH_NO_BROWSER (
    echo  [SKIP] Browser nicht geoeffnet (BACH_NO_BROWSER gesetzt)
    echo  URL: http://127.0.0.1:8000
) else (
    echo  Oeffne Browser (mit Cache-Buster)...
    start "" "http://127.0.0.1:8000?nocache=%TIMESTAMP%"
)

echo.
echo  [OK] Versuche zu verbinden...
echo  Wenn die Seite nicht laedt, schau in das ANDERE schwarze Fenster fuer Fehlermeldungen!
echo.
pause
