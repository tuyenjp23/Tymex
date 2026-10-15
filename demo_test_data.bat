@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Chay website voi DU LIEU KIEM THU GIA (khong can khoa API) de thu giao dien.
if not exist ".venv\Scripts\python.exe" ( echo Hay chay start.bat mot lan truoc. & pause & exit /b 1 )
".venv\Scripts\python.exe" scripts\seed_test_data.py
".venv\Scripts\python.exe" run.py --db test
pause
