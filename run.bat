@echo off
rem ============================================================
rem  광고 1차 점검 - 더블클릭 한 번으로 실행 (폐쇄망 PC)
rem  - 처음 실행 시: 같은 폴더/상위 폴더의 wheels 에서 자동 설치 (인터넷 불필요)
rem  - 이후: 웹 서버를 띄우고 브라우저를 자동으로 연다.  종료: 이 창을 닫거나 Ctrl+C
rem  - 사내망 공유/로그인:  run.bat 앞에 아래를 설정 (또는 config\run.env 에 기록)
rem        set ADREVIEW_PASSWORD=검수자암호
rem        set ADREVIEW_ADMIN_PASSWORD=관리자암호
rem        set ADREVIEW_HOST=0.0.0.0
rem ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 광고 1차 점검

rem 설정 파일(선택): config\run.env 의 'KEY=값' 줄을 환경변수로 읽는다
if exist config\run.env (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("config\run.env") do set "%%a=%%b"
)
if "%ADREVIEW_HOST%"=="" set ADREVIEW_HOST=127.0.0.1
if "%ADREVIEW_PORT%"=="" set ADREVIEW_PORT=8080

rem 1) 파이썬 환경 준비
if not exist .venv\Scripts\python.exe (
  echo [최초 실행] 오프라인 설치를 진행합니다...
  where python >nul 2>nul || ( echo [오류] 파이썬이 설치되어 있지 않습니다. 반입한 파이썬 설치 파일로 먼저 설치하세요. & pause & exit /b 1 )
  set WHEELS=..\wheels
  if not exist "%WHEELS%" set WHEELS=wheels
  if not exist "%WHEELS%" ( echo [오류] wheels 폴더를 찾을 수 없습니다. 반입 묶음 전체를 복사했는지 확인하세요. & pause & exit /b 1 )
  python -m venv .venv || ( echo [오류] 가상환경 생성 실패 & pause & exit /b 1 )
  .venv\Scripts\python.exe -m pip install --no-index --find-links "%WHEELS%" -r requirements-offline.txt || ( echo [오류] 설치 실패 - 파이썬 버전/플랫폼이 wheel 과 맞는지 확인하세요. & pause & exit /b 1 )
  echo 설치 완료.
)

rem 2) 브라우저 자동 열기 (서버가 뜰 시간을 잠깐 준 뒤)
set URL=http://127.0.0.1:%ADREVIEW_PORT%
start "" /b cmd /c "ping -n 7 127.0.0.1 >nul & start "" %URL%"

rem 3) 서버 실행
echo.
echo  검수 화면: %URL%   (종료: 이 창을 닫거나 Ctrl+C)
echo.
.venv\Scripts\python.exe -m adreview web --host %ADREVIEW_HOST% --port %ADREVIEW_PORT%
echo.
echo 서버가 종료되었습니다.
pause
