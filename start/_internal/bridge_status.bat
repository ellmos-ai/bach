@echo off
REM ============================================
REM DEPRECATED: Old claude_bridge/ system
REM Replaced by chat/ (chat_tray.py, chat_runtime.py)
REM ============================================

echo [WARN] bridge_status.bat ist veraltet. Nutze stattdessen:
echo        bach.bat -^> [B] Chat Service starten
echo.
echo [BACH] Bridge Status:
echo ================================

REM Via bach.bat bridge status
call "%~dp0..\..\system\bach.bat" bridge status

echo.
pause
