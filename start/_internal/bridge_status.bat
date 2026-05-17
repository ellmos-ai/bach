@echo off
REM ============================================
REM BACH Bridge - Status
REM ============================================

echo [BACH] Bridge Status:
echo ================================

REM Via bach.bat bridge status
call "%~dp0..\..\system\bach.bat" bridge status

echo.
pause
