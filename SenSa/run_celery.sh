#!/bin/bash
# run_celery.sh — Celery worker + beat 통합 실행.
#
# 개발/단순 운영용. 프로덕션에선 worker 와 beat 분리 권장:
#     celery -A mysite worker --loglevel=info
#     celery -A mysite beat   --loglevel=info
#
# [9차 ㅂ / A안] prometheus multiprocess mode:
#   prefork child 들의 메트릭을 mmap 파일로 모으기 위해
#   PROMETHEUS_MULTIPROC_DIR 를 worker 시작 전에 export + 초기화.
#   celery_metrics.py 의 worker_ready 핸들러가 :9809 로 합산 노출.

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

# ── [9차 ㅂ] prometheus multiprocess 디렉터리 준비 ──
# 매 기동 시 초기화 (stale mmap 파일 누적 방지).
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/sensa_celery_prom}"
export CELERY_METRICS_PORT="${CELERY_METRICS_PORT:-9809}"
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
echo "PROMETHEUS_MULTIPROC_DIR = $PROMETHEUS_MULTIPROC_DIR (초기화됨)"
echo "CELERY_METRICS_PORT      = $CELERY_METRICS_PORT"

LOG_LEVEL="${LOG_LEVEL:-info}"

echo "Starting Celery worker + beat (loglevel=$LOG_LEVEL)"
exec celery -A mysite worker -B --loglevel="$LOG_LEVEL"
