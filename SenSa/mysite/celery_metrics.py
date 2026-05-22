"""
mysite/celery_metrics.py — Celery task 메트릭 [9차 ㅂ 신규]

prometheus_client 의 모듈 레벨 Counter / Histogram 정의 + Celery signals 연결.

Counter / Histogram 은 prometheus_client 기본 REGISTRY 에 등록 →
django-prometheus 의 /metrics 엔드포인트에 자동 노출.

[연결 지점]
  Celery worker 프로세스가 mysite/celery.py 를 import 할 때 이 모듈도
  함께 import (mysite/celery.py 마지막 줄에 `from mysite import celery_metrics`).
  signal handler 가 등록되어 모든 task 의 prerun/postrun/retry 가 자동 측정됨.

[설계]
  - 글로벌 signal (Celery 의 모든 task 에 자동 후크). 대상 task 별도 명시 불필요.
  - silent failure 방지: signal handler 가 예외 던지면 task 자체에 영향 — 그래서
    handler 내부에 try/except + logging.warning 으로 안전망.
  - task 코드 무수정 (P2 retry 정책 등 기존 구조 유지).

[발표 정직 표현]
  P2 STEP 8 의 autoretry 정책 (max_retries=3, exponential backoff) 작동 증거를
  `sensa_celery_task_total{state="retried"}` 로 수치화. Grafana 패널에 노출.
"""
import logging
import time

from celery.signals import task_prerun, task_postrun, task_retry
from prometheus_client import Counter, Histogram


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 메트릭 정의
# ═══════════════════════════════════════════════════════════

# Counter — task state 별 누적
#   state:
#     'started'    — task_prerun (실행 시작)
#     'succeeded'  — task_postrun state=SUCCESS
#     'failed'     — task_postrun state=FAILURE
#     'retried'    — task_retry (autoretry 발생)
celery_task_total = Counter(
    'sensa_celery_task_total',
    'Celery task 누적 (state 별: started/succeeded/failed/retried)',
    labelnames=('task_name', 'state'),
)

# Histogram — task 실행 시간 분포
#   state:
#     'succeeded' | 'failed'   (started 는 시간 없음)
celery_task_duration_seconds = Histogram(
    'sensa_celery_task_duration_seconds',
    'Celery task 실행 시간 (초)',
    labelnames=('task_name', 'state'),
    # 시연 환경 task latency 분포 — 5ms ~ 10s
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


# ═══════════════════════════════════════════════════════════
# task_id → start_time 매핑 (prerun ↔ postrun 매칭)
# ═══════════════════════════════════════════════════════════
# 메모리 leak 방지: postrun 에서 pop 으로 제거. retry 시에도 prerun 새로 호출됨.
_task_start_times: dict = {}


# ═══════════════════════════════════════════════════════════
# Signal Handlers
# ═══════════════════════════════════════════════════════════

@task_prerun.connect
def _on_task_prerun(sender=None, task_id=None, task=None, **kwargs):
    """task 시작 시점 — started counter + 시작 시각 기록."""
    try:
        task_name = task.name if task is not None else 'unknown'
        _task_start_times[task_id] = time.monotonic()
        celery_task_total.labels(task_name=task_name, state='started').inc()
    except Exception as exc:
        logger.warning("celery_metrics prerun handler failed: %s", exc)


@task_postrun.connect
def _on_task_postrun(sender=None, task_id=None, task=None, state=None, **kwargs):
    """
    task 종료 시점 — Histogram observe + succeeded/failed counter.

    state 값 (celery.states):
      'SUCCESS'  → 'succeeded'
      'FAILURE'  → 'failed'
      기타 ('RETRY' 등) → 명시적 retry signal 에서 별도 카운트
    """
    try:
        task_name = task.name if task is not None else 'unknown'
        start = _task_start_times.pop(task_id, None)

        if state == 'SUCCESS':
            outcome = 'succeeded'
        elif state == 'FAILURE':
            outcome = 'failed'
        else:
            # RETRY, REVOKED 등 — 별도 signal 에서 처리됨
            return

        if start is not None:
            duration = time.monotonic() - start
            celery_task_duration_seconds.labels(
                task_name=task_name, state=outcome,
            ).observe(duration)

        celery_task_total.labels(task_name=task_name, state=outcome).inc()
    except Exception as exc:
        logger.warning("celery_metrics postrun handler failed: %s", exc)


@task_retry.connect
def _on_task_retry(sender=None, request=None, reason=None, **kwargs):
    """
    task retry 시점 — retried counter 증가 (P2 autoretry 정책 작동 증거).

    sender 는 task 클래스 (sender.name 으로 task 이름 확보).
    """
    try:
        task_name = sender.name if sender is not None else 'unknown'
        celery_task_total.labels(task_name=task_name, state='retried').inc()
    except Exception as exc:
        logger.warning("celery_metrics retry handler failed: %s", exc)


logger.info(
    "celery_metrics loaded: sensa_celery_task_total, "
    "sensa_celery_task_duration_seconds (signal handlers registered)"
)
