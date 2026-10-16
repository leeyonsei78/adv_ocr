#!/bin/sh
# 폐쇄망 PC: 인터넷 없이 패키지 설치 (wheels 폴더는 app 의 상위 폴더에 있다고 가정)
cd "$(dirname "$0")/.." || exit 1
W="../wheels"; [ -d "$W" ] || W="wheels"
python3 -m venv .venv && . .venv/bin/activate || exit 1
python -m pip install --no-index --find-links "$W" -r requirements-offline.txt && echo "설치 완료. sh scripts/run_web.sh 로 실행하세요."
