"""
mysite/celery_metrics.py — Celery task 메트릭 [9차 ㅂ / A안 exporter]

[구조적 배경 — 왜 multiprocess mode 인가]
  Celery worker 는 prefork (concurrency=8) → task 는 child 프로세스
  (ForkPoolWorker-N)에서 실행됨. prometheus_client 의 기본 REGISTRY 는
  프로세스별 독립 메모리이므로, child 가 올린 카운터를 main 프로세스나
  Django `/metrics` 가 볼 수 없음 (검증으로 확인된 구조적 제약).

  해결: prometheus_client multiprocess mode.
    - 각 child 가 PROMETHEUS_MULTIPROC_DIR 의 mmap 파일에 write
    - main 프로세스가 MultiProcessCollector 로 합산하여 :9809 로 노출
    - Prometheus 가 host.docker.internal:9809 를 scrape

  ※ PROMETHEUS_MULTIPROC_DIR 환경변수는 run_celery.sh 가 worker 시작
    전에 export. 이 변수가 있어야 Counter/Histogram 이 multiproc 모드로 동작.

[연결 지점]
  Celery worker 가 mysite/celery.py import 시 이 모듈도 import
  (celery.py 의 `from mysite import celery_metrics`).
  signal handler 등록 + worker_ready 시 metrics HTTP 서버 기동.

[Django 영향]
  없음. multiprocess mode 는 Celery worker 프로세스에만 적용.
  Django `/metrics`(django-prometheus, 별도 프로세스)는 그대로.
  → Celery 메트릭은 :9809 전용, Django :8000/metrics 와 분리가 정상.

[발표 정직 표현]
  P2 STEP 8 autoretry(max_retries=3, exponential backoff) 작동 증거를
  sensa_celery_task_total{state="retried"} 로 수치화.
"""
import logging
import os
import time

from celery.signals import task_prerun, task_postrun, task_retry, worker_ready
from prometheus_client import Counter, Histogram


logger = logging.getLogger(__name__)

# metrics HTTP 서버 포트 (prometheus.yml 의 sensa-celery job 과 일치해야 함)
CELERY_METRICS_PORT = int(os.environ.get('CELERY_METRICS_PORT', '9809'))


# ═══════════════════════════════════════════════════════════
# 메트릭 정의
#   multiprocess mode 면 (PROMETHEUS_MULTIPROC_DIR 존재 시) 자동으로
#   mmap 파일 기반으로 동작 — 코드 변경 없이 동일 정의 사용.
# ═══════════════════════════════════════════════════════════

celery_task_total = Counter(
    'sensa_celery_task_total',
    'Celery task 누적 (state 별: started/succeeded/failed/retried)',
    labelnames=('task_name', 'state'),
)

celery_task_duration_seconds = Histogram(
    'sensa_celery_task_duration_seconds',
    'Celery task 실행 시간 (초)',
    labelnames=('task_name', 'state'),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


# task_id → start_time (prerun ↔ postrun 매칭). postrun 에서 pop.
_task_start_times: dict = {}


# ═══════════════════════════════════════════════════════════
# metrics HTTP 서버 (worker_ready 시 main 프로세스에서 1회 기동)
# ═══════════════════════════════════════════════════════════

@worker_ready.connect
def _start_metrics_server(sender=None, **kwargs):
    """
    worker 가 준비되면 :9809 에 metrics HTTP 서버 기동.

    multiprocess mode:
      PROMETHEUS_MULTIPROC_DIR 가 설정돼 있으면 MultiProcessCollector 로
      child 들의 mmap 메트릭을 합산해 노출.
    단일 모드 (변수 없음):
      기본 REGISTRY 노출 (fallback — main 프로세스 메트릭만, 정확도 낮음).
    """
    try:
        from prometheus_client import start_http_server, CollectorRegistry
        mp_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR')

        if mp_dir:
            from prometheus_client import multiprocess
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            start_http_server(CELERY_METRICS_PORT, registry=registry)
            logger.info(
                "celery metrics HTTP server on :%d (multiprocess, dir=%s)",
                CELERY_METRICS_PORT, mp_dir,
            )
        else:
            start_http_server(CELERY_METRICS_PORT)
            logger.warning(
                "celery metrics HTTP server on :%d (SINGLE process mode — "
                "PROMETHEUS_MULTIPROC_DIR 미설정. child 메트릭 누락 가능)",
                CELERY_METRICS_PORT,
            )
    except OSError as exc:
        # 포트 이미 점유 등 — worker 자체는 정상 동작해야 하므로 흡수
        logger.warning(
            "celery metrics server start failed (port %d): %s",
            CELERY_METRICS_PORT, exc,
        )
    except Exception as exc:
        logger.warning("celery metrics server start failed: %s", exc)


# ═══════════════════════════════════════════════════════════
# Signal Handlers
# ═══════════════════════════════════════════════════════════

@task_prerun.connect
def _on_task_prerun(sender=None, task_id=None, task=None, **kwargs):
    """task 시작 — started counter + 시작 시각 기록."""
    try:
        task_name = task.name if task is not None else 'unknown'
        _task_start_times[task_id] = time.monotonic()
        celery_task_total.labels(task_name=task_name, state='started').inc()
    except Exception as exc:
        logger.warning("celery_metrics prerun handler failed: %s", exc)


@task_postrun.connect
def _on_task_postrun(sender=None, task_id=None, task=None, state=None, **kwargs):
    """
    task 종료 — Histogram observe + succeeded/failed counter.
      'SUCCESS' → succeeded, 'FAILURE' → failed,
      그 외(RETRY 등) → retry signal 에서 별도 카운트.
    """
    try:
        task_name = task.name if task is not None else 'unknown'
        start = _task_start_times.pop(task_id, None)

        if state == 'SUCCESS':
            outcome = 'succeeded'
        elif state == 'FAILURE':
            outcome = 'failed'
        else:
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
    """task retry — retried counter (P2 autoretry 정책 작동 증거)."""
    try:
        task_name = sender.name if sender is not None else 'unknown'
        celery_task_total.labels(task_name=task_name, state='retried').inc()
    except Exception as exc:
        logger.warning("celery_metrics retry handler failed: %s", exc)


logger.info(
    "celery_metrics loaded: signal handlers registered, "
    "metrics server will start on :%d at worker_ready", CELERY_METRICS_PORT
)
