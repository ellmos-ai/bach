@echo off
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8

pushd "%~dp0..\..\system"
set "SYS_DIR=%CD%"
popd

title BACH Claude Remote Control

python "%~dp0claude_remote_control.py" %*

if not defined BACH_AUTO pause
