@echo off
cd /d "%~dp0"
py -3.13 -m venv .venv || python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
echo Done. Put Stockfish in engine\ (see README), then run gui.bat
