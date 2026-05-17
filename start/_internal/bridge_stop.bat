@echo off
REM ============================================
REM BACH Bridge - Stoppen
REM ============================================

echo [BACH] Stoppe Bridge...

REM Via bach.bat bridge stop
call "%~dp0..\..\system\bach.bat" bridge stop

echo.
echo [OK] Bridge-Stop-Befehl gesendet
echo.
pause
