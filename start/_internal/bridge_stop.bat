@echo off
REM ============================================
REM DEPRECATED: Old claude_bridge/ system
REM Replaced by chat/ (chat_tray.py, chat_runtime.py)
REM ============================================

echo [WARN] bridge_stop.bat ist veraltet. Nutze stattdessen:
echo        bach.bat -^> [B] Chat Service starten
echo.
echo [BACH] Stoppe Bridge...

REM Via bach.bat bridge stop
call "%~dp0..\..\system\bach.bat" bridge stop

echo.
echo [OK] Bridge-Stop-Befehl gesendet
echo.
pause
