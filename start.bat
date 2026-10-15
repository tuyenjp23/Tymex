@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Football Analytics

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY goto nopython

if exist ".venv\Scripts\python.exe" goto havevenv
echo [1/3] Tao moi truong ao Python (chi lan dau)...
%PY% -m venv .venv
if errorlevel 1 goto fail
:havevenv

echo [2/3] Kiem tra thu vien...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  rem Mat mang khong nen chan viec mo website neu thu vien da duoc cai tu truoc.
  ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, dotenv" >nul 2>nul
  if errorlevel 1 goto fail
  echo Khong cap nhat duoc thu vien nhung ban cai san van dung duoc, tiep tuc...
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Da tao file .env. Hay nhap khoa API tai trang Cai dat tren website.
)

echo [3/3] Khoi dong website tai http://127.0.0.1:8000  (dong cua so nay de tat)
".venv\Scripts\python.exe" run.py
goto end

:nopython
echo Khong tim thay Python. Cai Python 3.10 tro len tai https://www.python.org/downloads/ (nho tick "Add python.exe to PATH").
goto end
:fail
echo Co loi khi cai dat. Xem thong bao phia tren.
:end
pause
