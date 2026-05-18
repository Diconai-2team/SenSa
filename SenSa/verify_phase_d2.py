"""
verify_phase_d2.py — Phase D-2 시나리오 (MultiLeak + Sudden) 검증.

사용:
    # 회귀 폭주 방지를 위해 DRY_RUN 권장 (critical 시나리오의 Slack 발송 회피)
    SENSA_NOTIFY_DRY_RUN=true python manage.py shell -c \\
        "exec(open('verify_phase_d2.py').read())"

기대 출력:
    - 레지스트리에 single_leak, multi_leak, sudden_leak 모두 등록
    - MultiLeak  실행 → verify_ok=True, final_tier=critical
    - SuddenLeak 실행 → verify_ok=True, final_tier=critical
    - 자동 cleanup 완료
"""
import os
import sys

print("\n" + "═" * 60)
print("  Phase D-2 시나리오 검증 (MultiLeak + SuddenLeak)")
print("═" * 60)


# 환경변수 확인
dry_run = os.environ.get('SENSA_NOTIFY_DRY_RUN', 'false').lower() == 'true'
slack_set = bool(os.environ.get('SLACK_WEBHOOK_URL', '').strip())
print(f"\n[환경]")
print(f"  SENSA_NOTIFY_DRY_RUN: {dry_run}")
print(f"  SLACK_WEBHOOK_URL:    {'설정됨' if slack_set else '미설정'}")
if slack_set and not dry_run:
    print(f"  ⚠ critical 승격 시 실제 Slack 발송 가능.")
    print(f"     데모 의도가 아니면 SENSA_NOTIFY_DRY_RUN=true 권장.")


from geofence.scenarios import list_scenarios, get_scenario


# 1. 레지스트리 확인
print("\n[1] 시나리오 레지스트리")
scenarios = list_scenarios()
for s in scenarios:
    print(f"  - {s['name']}")
    print(f"      {s['description']}")

required = ('single_leak', 'multi_leak', 'sudden_leak')
registered = {s['name'] for s in scenarios}
missing = [n for n in required if n not in registered]
if missing:
    print(f"\n  ✗ 미등록 시나리오: {missing}")
    sys.exit(1)


def run_and_check(scenario_name: str, label: str) -> bool:
    """시나리오 실행 + 결과 출력 + verify 통과 여부 반환."""
    print(f"\n[{label}] {scenario_name} 실행 + 자동 검증")
    cls = get_scenario(scenario_name)
    scenario = cls()
    result = scenario.execute(verify=True, keep=False)

    print(f"  실행 상태:    {result['status']}")
    print(f"  cleaned_up:   {result.get('cleaned_up')}")

    actual = result.get('actual', {})
    print(f"  실제 결과:")
    for k, v in actual.items():
        print(f"    {k:18s}: {v}")

    expected = result.get('expected', {})
    print(f"  기대 결과:")
    for k, v in expected.items():
        print(f"    {k:18s}: {v}")

    ok = result.get('verify_ok', False)
    print(f"  검증 OK:      {ok}")
    if not ok:
        print(f"  차이점:")
        for d in result.get('verify_diffs', []):
            print(f"    - {d}")

    return ok


# 2. MultiLeak
ok_multi = run_and_check('multi_leak', '2')

# 3. SuddenLeak
ok_sudden = run_and_check('sudden_leak', '3')


# 4. cleanup 격리 확인
print("\n[4] cleanup 격리 확인")
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
    print("  ⚠ cleanup 누락. 수동 정리:")
    print("    Device.objects.filter(device_id__startswith='sensa_scenario_').delete()")
    print("    GeoFence.objects.filter(name__startswith='[시나리오]').delete()")


# 5. 결론
print("\n" + "═" * 60)
if ok_multi and ok_sudden:
    print("  결과: Phase D-2 시나리오 (MultiLeak + Sudden) 정상 동작")
else:
    print("  ✗ 일부 시나리오 검증 실패")
    if not ok_multi:  print("    - multi_leak")
    if not ok_sudden: print("    - sudden_leak")
print("═" * 60 + "\n")

if not (ok_multi and ok_sudden):
    sys.exit(1)
