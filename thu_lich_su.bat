@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Chay thu nhap lich su tren may (khong dung khoa API, khong dung Supabase). Vi du: thu_lich_su.bat KR1 AU1 --seasons 1
if not exist ".venv\Scripts\python.exe" ( echo Hay chay start.bat mot lan truoc. & pause & exit /b 1 )
".venv\Scripts\python.exe" scripts\thu_lich_su.py %*
pause
