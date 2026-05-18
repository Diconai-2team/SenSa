"""
geofence/tasks.py — Celery 비동기 task.

Phase G: 동적 zone tick 자동화.

[설계]
- 기존 동기 zone_lifecycle.tick() 을 그대로 호출 (로직 재사용)
- 기존 tick_dynamic_zones 관리 명령은 보존 (디버깅·수동 실행용)
- Celery beat 가 30 초 주기로 자동 호출 (settings.py 의 CELERY_BEAT_SCHEDULE)

[운영]
이 task 가 호출될 때마다 다음을 수행:
    1. 만료된 zone 비활성화 (expire_zones)
    2. 활성 zone 의 반경 갱신 (update_all_active_zones)
    3. tier 승격 검사 (check_all_active_zones_upgrade)
       - has_anomaly 호출 (v2 simple residual 기반)

[idempotency]
같은 zone 에 대해 동시 호출되어도 안전 (`update_fields` 사용, 시간 비교 기반).

[5차 세션 C′-3b-1]
TTM 폐기에 따라 scan_forecast_warnings_task 제거.
"""
from celery import shared_task

from geofence.zone_lifecycle import tick


@shared_task(name='geofence.tasks.tick_zones')
def tick_zones() -> dict:
    """동적 zone 의 반경 진화 + 만료 + 승격 검사 (Celery beat 자동 호출).

    Returns:
        {'updated': N, 'expired': M,
         'upgraded_to_confirmed': X, 'upgraded_to_critical': Y}
    """
    return tick(check_upgrade=True)


from .tasks_scenario import sustain_spike_task  # noqa: F401
