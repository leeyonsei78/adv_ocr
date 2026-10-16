@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
rem 사내망 공유 + 로그인:  set ADREVIEW_PASSWORD=검수자암호 ^& set ADREVIEW_ADMIN_PASSWORD=관리자암호 후  run_web.bat 0.0.0.0
set HOST=%1
if "%HOST%"=="" set HOST=127.0.0.1
python -m adreview web --host %HOST% --port 8080
