@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run: setting things up...
  call "%~dp0setup.bat"
  if not exist ".venv\Scripts\pythonw.exe" exit /b 1
)
rem pythonw = no console window; startup errors are shown in a dialog and in logs\chessmind.log
start "" ".venv\Scripts\pythonw.exe" gui.py
