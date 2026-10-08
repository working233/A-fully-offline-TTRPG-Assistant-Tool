@echo off
rem ===================================================================
rem  NOTE: This file is intentionally kept in pure ASCII (no Chinese).
rem  Reason: cmd.exe mis-computes file offsets for UTF-8 batch files
rem  when the codepage is switched, which randomly corrupts parsing.
rem  All Chinese messages are printed by start.py instead.
rem ===================================================================
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title TRPG Local Assistant - Launcher

echo ============================================================
echo    TRPG Local Assistant  -  One-click Launcher
echo ============================================================
echo.
echo [1/3] Looking for Python 3.11+ ...

set "PY="

py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto FOUND

python -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto FOUND

python3 -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python3"
if defined PY goto FOUND

call :CHKEXE "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if defined PY goto FOUND
call :CHKEXE "%USERPROFILE%\.workbuddy\binaries\python\versions\3.12.10\python.exe"
if defined PY goto FOUND
call :CHKEXE "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined PY goto FOUND
call :CHKEXE "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto FOUND
call :CHKEXE "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined PY goto FOUND
call :CHKEXE "C:\Python313\python.exe"
if defined PY goto FOUND
call :CHKEXE "C:\Python312\python.exe"
if defined PY goto FOUND
call :CHKEXE "C:\Python311\python.exe"
if defined PY goto FOUND

goto NOPY

:CHKEXE
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
"%~1" -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
set "PY=%~1"
exit /b 0

:FOUND
set PYTHONIOENCODING=
set PYTHONUTF8=0
%PY% start.py %*
if errorlevel 1 goto FAILED
goto END

:FAILED
echo.
echo [ERROR] Launch failed, see messages above.
echo         Try another port, e.g.: this-bat-file --port 9000
echo.
pause
exit /b 3

:NOPY
echo.
echo [ERROR] Python 3.11 or newer was not found on this computer.
echo.
echo  Please download and install Python from:
echo      https://www.python.org/downloads/
echo  During install, CHECK the box "Add python.exe to PATH",
echo  then double-click this file again.
echo.
pause
exit /b 2

:END
exit /b 0
