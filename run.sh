#!/bin/sh
# 한 번에 실행 (Linux): 최초 1회는 wheels 에서 오프라인 설치 후 서버를 띄운다.
cd "$(dirname "$0")" || exit 1
[ -f config/run.env ] && . ./config/run.env
HOST="${ADREVIEW_HOST:-127.0.0.1}"; PORT="${ADREVIEW_PORT:-8080}"
if [ ! -x .venv/bin/python ]; then
  W="../wheels"; [ -d "$W" ] || W="wheels"
  python3 -m venv .venv && .venv/bin/python -m pip install --no-index --find-links "$W" -r requirements-offline.txt || exit 1
fi
echo "검수 화면: http://127.0.0.1:$PORT  (종료: Ctrl+C)"
ADREVIEW_PASSWORD="${ADREVIEW_PASSWORD:-}" exec .venv/bin/python -m adreview web --host "$HOST" --port "$PORT"
