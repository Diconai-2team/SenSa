#!/bin/bash
# run_celery.sh — Celery worker + beat 통합 실행.
#
# 개발/단순 운영용. 프로덕션에선 worker 와 beat 분리 권장:
#     celery -A mysite worker --loglevel=info
#     celery -A mysite beat   --loglevel=info

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# venv 활성화
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Redis 헬스체크
if ! redis-cli ping > /dev/null 2>&1; then
    echo "ERROR: Redis 가 동작하지 않습니다. sudo service redis-server start"
    exit 1
fi

LOG_LEVEL="${LOG_LEVEL:-info}"

echo "Starting Celery worker + beat (loglevel=$LOG_LEVEL)"
exec celery -A mysite worker -B --loglevel="$LOG_LEVEL"
