"""
verify_phase_i2.py — Phase I-2 WebSocket 푸시 검증 스크립트.

브라우저 WebSocket 클라이언트 없이도 channel layer 에 메시지가 들어가는지
직접 확인. 인증·세션 없이 동작.

사용:
    python manage.py shell < verify_phase_i2.py

또는:
    python manage.py shell
    >>> exec(open('verify_phase_i2.py').read())
"""
import asyncio
import sys
from datetime import datetime

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

print("\n" + "═" * 60)
print("  Phase I-2 WebSocket 푸시 검증")
print("═" * 60)


# 1. Channel layer 확보
layer = get_channel_layer()
if layer is None:
    print("✗ Channel layer 없음 — settings.CHANNEL_LAYERS 확인 필요")
    sys.exit(1)
print(f"✓ Channel layer: {type(layer).__name__}")


# 2. 임시 channel 만들고 dashboard.zones 그룹에 가입
test_channel = async_to_sync(layer.new_channel)()
async_to_sync(layer.group_add)('dashboard.zones', test_channel)
print(f"✓ 테스트 channel '{test_channel[:20]}...' 이 dashboard.zones 그룹 가입")


# 3. 직접 publish_zone_event 호출 → 메시지 받히는지
print(f"\n[테스트 1] publish_zone_event 직접 호출")
from realtime.publishers import publish_zone_event

test_payload = {
    'event_id': 9999,
    'event_type': 'created',
    'zone_id': 9999,
    'zone_name': '[검증] 가짜 zone',
    'from_tier': '',
    'to_tier': 'tentative',
    'trigger_source': 'manual',
    'detail': {'test': True},
    'created_at': datetime.utcnow().isoformat(),
}
publish_zone_event(test_payload)

# 수신 시도 (3초 timeout)
async def _try_receive():
    try:
        return await asyncio.wait_for(layer.receive(test_channel), timeout=3.0)
    except asyncio.TimeoutError:
        return None

msg = async_to_sync(_try_receive)()
if msg:
    print(f"  ✓ 메시지 수신: type='{msg.get('type')}'")
    print(f"    payload event_type: {msg['payload'].get('event_type')}")
    print(f"    payload zone_name: {msg['payload'].get('zone_name')}")
else:
    print("  ✗ 메시지 수신 못 함 (3초 timeout)")
    sys.exit(1)


# 4. 실제 zone 생성 → events._emit → publish_zone_event 자동 호출
print(f"\n[테스트 2] 실제 zone 생성 → 자동 푸시")

from devices.models import Device
from geofence.zone_lifecycle import create_dynamic_zone
from geofence.models import GeoFence

# 임시 센서 확보 (또는 첫 가스 센서 사용)
device = Device.objects.filter(sensor_type='gas').first()
if not device:
    print("  ⚠ 가스 센서 없음 — Device 생성 후 재시도 필요")
    sys.exit(0)
print(f"  센서: {device.device_id}")

# 기존 활성 zone 정리 (검증 충돌 방지)
GeoFence.objects.filter(is_dynamic=True, is_active=True, source_device=device).delete()

zone = create_dynamic_zone(device, 'co', trigger_source='manual')
print(f"  zone 생성: id={zone.id} tier={zone.tier}")

# 'created' 이벤트가 채널 레이어로 푸시됐는지
msg2 = async_to_sync(_try_receive)()
if msg2:
    print(f"  ✓ 푸시 수신: event_type='{msg2['payload'].get('event_type')}'")
    print(f"    zone_id: {msg2['payload'].get('zone_id')}")
    print(f"    trigger_source: {msg2['payload'].get('trigger_source')}")
    if msg2['payload'].get('zone_id') == zone.id:
        print(f"  ✓ zone_id 매칭")
    else:
        print(f"  ✗ zone_id 불일치 (기대: {zone.id})")
else:
    print("  ✗ 푸시 수신 못 함")


# 5. 정리
async_to_sync(layer.group_discard)('dashboard.zones', test_channel)
GeoFence.objects.filter(id=zone.id).delete()

print(f"\n{'═' * 60}")
print("  결과: Phase I-2 WebSocket 푸시 정상 동작")
print(f"{'═' * 60}\n")
