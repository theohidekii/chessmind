@echo off
cd /d "%~dp0"
title ChessMind setup
rem Usage: setup.bat [--yes | --no-data]
rem   (no flag)  asks before downloading Stockfish and the optional data
rem   --yes      downloads everything without asking
rem   --no-data  only creates the environment (download later from the app: Tools menu)

echo.
echo   ChessMind - setup
echo   -----------------
echo.

rem ---- 1) find a suitable Python (3.11+ with Tk; 3.13 is the version the project is tested on) ----
set "PY="
for %%V in (3.13 3.14 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import tkinter" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python 3.11 or newer with Tk was not found.
  echo         Install Python 3.13 from https://www.python.org/downloads/
  echo         ^(keep "tcl/tk and IDLE" ticked, and tick "Add python.exe to PATH"^) and run setup.bat again.
  goto :fail
)
echo Python: %PY%

rem ---- 2) virtual environment + dependencies ----
if not exist ".venv\Scripts\python.exe" (
  echo Creating the virtual environment...
  %PY% -m venv .venv || goto :fail
)
echo Installing dependencies ^(first time takes a minute or two^)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

rem ---- 3) Stockfish + opening book + tablebases ----
if /i "%~1"=="--no-data" goto :skipdata
if /i "%~1"=="--yes" goto :getdata
echo.
echo ChessMind needs the Stockfish chess engine. It can download it now ^(~80 MB, from the official
echo Stockfish GitHub releases^), plus an opening book ^(~0.4 MB^) and 3-4 piece endgame tablebases ^(~4.4 MB^).
choice /c YN /m "Download them now"
if errorlevel 2 goto :skipdata
:getdata
".venv\Scripts\python.exe" scripts\get_data.py --all
goto :done
:skipdata
echo Skipped. The app offers to download them on first launch ^(Tools menu - Verify installation^).

:done
echo.
echo Done! Start ChessMind with gui.bat
if /i not "%~1"=="--yes" if /i not "%~1"=="--no-data" pause
exit /b 0

:fail
echo.
echo [ERROR] Setup did not finish. See the messages above.
if /i not "%~1"=="--yes" if /i not "%~1"=="--no-data" pause
exit /b 1
