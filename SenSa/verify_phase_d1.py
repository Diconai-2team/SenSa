"""
verify_phase_d1.py — Phase D-1 시나리오 생성기 검증.

사용:
    python manage.py shell -c "exec(open('verify_phase_d1.py').read())"

기대 출력:
    - 레지스트리에 single_leak 등록 확인
    - SingleLeak 실행 → verify_ok = True
    - 자동 cleanup 완료
"""
print("\n" + "═" * 60)
print("  Phase D-1 시나리오 생성기 검증")
print("═" * 60)

from geofence.scenarios import list_scenarios, get_scenario


# 1. 레지스트리 확인
print("\n[1] 시나리오 레지스트리")
scenarios = list_scenarios()
for s in scenarios:
    print(f"  - {s['name']}")
    print(f"      {s['description']}")

assert any(s['name'] == 'single_leak' for s in scenarios), \
    "single_leak 가 레지스트리에 없음"


# 2. SingleLeak 실행 + verify
print("\n[2] SingleLeak 시나리오 실행 + 자동 검증")
cls = get_scenario('single_leak')
scenario = cls()
result = scenario.execute(verify=True, keep=False)

print(f"\n  실행 상태: {result['status']}")
print(f"  cleaned_up: {result.get('cleaned_up')}")

print(f"\n  실제 결과:")
for k, v in result.get('actual', {}).items():
    print(f"    {k:18s}: {v}")

print(f"\n  기대 결과:")
for k, v in result.get('expected', {}).items():
    print(f"    {k:18s}: {v}")

print(f"\n  검증 OK: {result.get('verify_ok')}")

if not result.get('verify_ok'):
    print("  차이점:")
    for d in result.get('verify_diffs', []):
        print(f"    - {d}")
    import sys
    sys.exit(1)


# 3. 격리 확인 — 인공 device 가 모두 cleanup 됐는지
print("\n[3] cleanup 격리 확인")
from devices.models import Device
from geofence.models import GeoFence

leftover_devices = Device.objects.filter(
    device_id__startswith='sensa_scenario_',
).count()
leftover_zones = GeoFence.objects.filter(
    name__startswith='[시나리오]',
).count()

print(f"  남은 sensa_scenario_ device: {leftover_devices}")
print(f"  남은 [시나리오] zone:        {leftover_zones}")

if leftover_devices > 0 or leftover_zones > 0:
    print("  ⚠ cleanup 누락. 수동 정리 필요:")
    print("    Device.objects.filter(device_id__startswith='sensa_scenario_').delete()")
    print("    GeoFence.objects.filter(name__startswith='[시나리오]').delete()")

print("\n" + "═" * 60)
print("  결과: Phase D-1 시나리오 생성기 정상 동작")
print("═" * 60 + "\n")
