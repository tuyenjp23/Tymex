@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo Hay chay start.bat mot lan truoc. & pause & exit /b 1 )
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest -q
pause
