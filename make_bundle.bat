@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 반입 묶음 만들기 - 인터넷 되는 PC 에서 실행. 이 PC 와 같은 파이썬/윈도우 기준으로 wheels 를 받는다.
rem 폐쇄망 PC 의 파이썬 버전이 다르면:  python scripts\make_offline_bundle.py --out adreview_offline --platform win_amd64 --python-version 3.11
set PYTHONUTF8=1
python scripts\make_offline_bundle.py --out ..\adreview_offline
echo.
echo 완료: 상위 폴더의 adreview_offline 폴더를 통째로 반입하세요. (파이썬 설치 파일도 함께)
pause
