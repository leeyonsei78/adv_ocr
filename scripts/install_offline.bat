@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set W=..\wheels
if not exist "%W%" set W=wheels
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --no-index --find-links "%W%" -r requirements-offline.txt || goto :err
echo 설치 완료. scripts\run_web.bat 로 실행하세요.
goto :eof
:err
echo [오류] 설치 실패 - 파이썬 버전/플랫폼이 wheel 과 맞는지 확인하세요.
exit /b 1
