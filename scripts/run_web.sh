#!/bin/sh
# 사용 예)  ADREVIEW_PASSWORD=검수자암호 ADREVIEW_ADMIN_PASSWORD=관리자암호 sh scripts/run_web.sh 0.0.0.0
cd "$(dirname "$0")/.." || exit 1
[ -f .venv/bin/activate ] && . .venv/bin/activate
python -m adreview web --host "${1:-127.0.0.1}" --port "${2:-8080}"
