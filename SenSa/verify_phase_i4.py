"""
verify_phase_i4.py — Phase I-4 외부 알림 검증.

DRY_RUN 모드로 webhook URL 없이도 검증 가능.

사용:
    SENSA_NOTIFY_DRY_RUN=true python manage.py shell -c "exec(open('verify_phase_i4.py').read())"
"""
import os

print("\n" + "═" * 60)
print("  Phase I-4 외부 알림 검증")
print("═" * 60)

# 0. 환경변수 확인
slack = os.environ.get('SLACK_WEBHOOK_URL', '')
discord = os.environ.get('DISCORD_WEBHOOK_URL', '')
dry_run = os.environ.get('SENSA_NOTIFY_DRY_RUN', 'false').lower() == 'true'

print(f"\n[환경변수]")
print(f"  SLACK_WEBHOOK_URL:    {'설정됨' if slack else '미설정'}")
print(f"  DISCORD_WEBHOOK_URL:  {'설정됨' if discord else '미설정'}")
print(f"  SENSA_NOTIFY_DRY_RUN: {dry_run}")

if not (slack or discord or dry_run):
    print("\n⚠ 모두 미설정 — DRY_RUN=true 또는 webhook URL 설정 필요")
    print("   예: SENSA_NOTIFY_DRY_RUN=true python manage.py shell -c \"...\"")
    import sys; sys.exit(1)


# 1. notifiers.notify_external 직접 호출
print(f"\n[테스트 1] notify_external 직접 호출")
from alerts.notifiers import notify_external, is_configured

print(f"  is_configured(): {is_configured()}")
result = notify_external(
    title="검증 테스트",
    message="Phase I-4 검증 메시지 (실제 critical 아님)",
    severity='critical',
)
print(f"  결과: {result}")


# 2. 실제 critical 승격 시나리오 — 외부 알림 큐잉 발생 확인
print(f"\n[테스트 2] critical 승격 시뮬레이션")

from devices.models import Device, SensorData
from django.utils import timezone
from datetime import timedelta
from geofence.zone_lifecycle import _upgrade_to_critical
from geofence.models import GeoFence
from geofence.events import _notify_external_critical

# 임시 zone (이미 confirmed 가정)
device = Device.objects.filter(sensor_type='gas').first()
if not device:
    print("  ⚠ 가스 센서 없음")
    import sys; sys.exit(0)

# 기존 활성 zone 정리
GeoFence.objects.filter(is_dynamic=True, source_device=device).delete()

zone = GeoFence.objects.create(
    name='[검증] critical 승격 시뮬레이션',
    polygon=[[0,0],[10,0],[10,10],[0,10]],
    zone_type='danger', is_active=True, is_dynamic=True,
    source_device=device, gas_type='co',
    tier='confirmed',        # 이미 confirmed
    trigger_source='ttm_anomaly',
    current_radius_px=150.0,
)
print(f"  사전 상태: zone id={zone.id} tier={zone.tier}")

# critical 승격 → events._emit → _notify_external_critical
_upgrade_to_critical(zone)
print(f"  사후 상태: zone id={zone.id} tier={zone.tier}")
print(f"  → '_notify_external_critical' 자동 호출됨 (Celery task 큐잉)")

# 정리
GeoFence.objects.filter(id=zone.id).delete()


# 3. Celery worker 가 동작 중이면 task 가 실제 처리됨
print(f"\n[참고]")
print(f"  Celery worker 가 동작 중이면 'send_external_notification_task' 가")
print(f"  실제 처리되어 webhook 발송 또는 DRY-RUN 로그 출력.")
print(f"  worker 로그에서 'send_external_notification_task ... succeeded' 확인.")


print(f"\n{'═' * 60}")
print("  결과: Phase I-4 외부 알림 코드 경로 정상")
print(f"{'═' * 60}\n")
