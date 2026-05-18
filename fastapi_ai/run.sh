#!/bin/bash
# fastapi_ai/run.sh — AI 서버 시작 스크립트
#
# ai_lab/venv 를 재사용 (torch, granite-tsfm 이미 설치됨).
# 처음 실행 시 fastapi, uvicorn 등 의존성 설치 필요:
#     source ../ai_lab/venv/bin/activate
#     pip install -r requirements.txt

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ai_lab venv 활성화
VENV_PATH="../ai_lab/venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: ai_lab venv 를 찾을 수 없음: $VENV_PATH"
    exit 1
fi

source "$VENV_PATH/bin/activate"

# 의존성 확인
if ! python -c "import fastapi" 2>/dev/null; then
    echo "fastapi 미설치 — 설치 중..."
    pip install -r requirements.txt
fi

# 서버 시작
PORT="${PORT:-8002}"
HOST="${HOST:-0.0.0.0}"

echo "Starting SenSa AI Server on $HOST:$PORT"
exec uvicorn main:app --host "$HOST" --port "$PORT" --reload
