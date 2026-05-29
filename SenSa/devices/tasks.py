"""
devices/tasks.py — AI 파이프라인 Celery task

[구조]
  HTTP POST /sensor-data/ 수신 후 AI 분석을 Celery worker 로 위임.
  views.py 의 _run_ai_pipeline_inner / _run_power_ai_pipeline_inner 를
  Celery task 로 감싸는 얇은 래퍼.

[설계 결정]
  - concurrency=1 (docker-compose.yml 에 설정) → 인메모리 모델 상태 분기 없음.
  - max_retries=2 : 일시적 DB/Redis 오류에만 재시도 (AI 오류는 재시도 의미 없음).
  - autoretry_for=() : 자동 재시도 없음 — 예외를 선별해 명시적 retry.
  - 큐 분리 없음 : 기본 Celery 큐(celery) 사용 — 단일 worker 이므로 불필요.

[이점 (threading 대비)]
  - 세마포어 초과로 인한 AI 분석 스킵 제거 → 모든 틱 분석 보장.
  - Django 프로세스 장애 격리 → AI 파이프라인 예외가 웹 서버에 영향 없음.
  - Celery 메트릭(sensa_celery_task_total)에 AI task 자동 추적.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name='devices.tasks.run_ai_pipeline',
    # 일시적 DB/Redis 오류 시 재시도 (최대 2회, 5s 간격)
    autoretry_for=(OSError, ConnectionError),
    retry_kwargs={'max_retries': 2, 'countdown': 5},
    retry_backoff=False,
    # task 실패가 worker 를 멈추면 안 됨 — acks_late=False (기본)
    ignore_result=True,
)
def run_ai_pipeline_task(device_id: str, gas_values: dict) -> None:
    """
    가스 센서 AI 파이프라인 Celery task.

    views.py 의 _run_ai_pipeline_inner 를 Celery worker 에서 실행.
    lazy import 로 순환 import 방지.
    """
    try:
        from devices.views import _run_ai_pipeline_inner
        _run_ai_pipeline_inner(device_id, gas_values)
    except Exception as exc:
        logger.warning("[ai_task/gas] %s: %s", device_id, exc)
        # 예외 삼키기 — AI 파이프라인 실패가 worker 재시도 루프에 들어가면 안 됨


@shared_task(
    name='devices.tasks.run_power_ai_pipeline',
    autoretry_for=(OSError, ConnectionError),
    retry_kwargs={'max_retries': 2, 'countdown': 5},
    retry_backoff=False,
    ignore_result=True,
)
def run_power_ai_pipeline_task(device_id: str, power_values: dict) -> None:
    """
    전력 센서 AI 파이프라인 Celery task.

    views.py 의 _run_power_ai_pipeline_inner 를 Celery worker 에서 실행.
    """
    try:
        from devices.views import _run_power_ai_pipeline_inner
        _run_power_ai_pipeline_inner(device_id, power_values)
    except Exception as exc:
        logger.warning("[ai_task/power] %s: %s", device_id, exc)
