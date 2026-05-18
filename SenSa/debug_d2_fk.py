"""
debug_d2_fk.py — Phase D-2 teardown FK 위반 원인 추적.

(5) verify_phase_d2.py 가 teardown 단계에서 IntegrityError 발생한 이유 찾기.
남은 sensa_scenario_ device + 그를 참조하는 외부 FK/M2M 모두 검사.

사용:
    SENSA_NOTIFY_DRY_RUN=true python manage.py shell -c \\
        "exec(open('debug_d2_fk.py').read())"
"""
from django.apps import apps
from devices.models import Device
from geofence.models import GeoFence

print("\n" + "═" * 60)
print("  Phase D-2 teardown FK 위반 진단")
print("═" * 60)


# [A] 남은 시나리오 잔존물
print("\n[A] 남은 sensa_scenario_ device + [시나리오] zone")
remaining_devs = Device.objects.filter(
    device_id__startswith='sensa_scenario_',
)
remaining_zones = GeoFence.objects.filter(
    name__startswith='[시나리오]',
)
print(f"  device: {remaining_devs.count()}개")
for d in remaining_devs[:20]:
    print(f"    - {d.device_id} (pk={d.pk}, x={d.x}, y={d.y}, active={d.is_active})")
print(f"  zone:   {remaining_zones.count()}개")
for z in remaining_zones[:10]:
    print(f"    - {z.name} (pk={z.pk}, tier={z.tier}, active={z.is_active})")


# [B] device 외부 FK + M2M 참조 검사
print("\n[B] sensa_scenario_ device 를 참조하는 외부 모델")
if remaining_devs.exists():
    dev_ids = list(remaining_devs.values_list('pk', flat=True))
    found = False
    for model in apps.get_models():
        if model is Device:
            continue
        for f in model._meta.get_fields():
            related = getattr(f, 'related_model', None)
            if related is not Device:
                continue
            remote = getattr(f, 'remote_field', None)
            if remote is None:
                continue

            try:
                if f.many_to_many:
                    cnt = model.objects.filter(
                        **{f.name + '__in': dev_ids}
                    ).distinct().count()
                    rel_type = 'M2M'
                elif f.many_to_one or f.one_to_one:
                    on_del = remote.on_delete.__name__ if hasattr(remote, 'on_delete') else '?'
                    cnt = model.objects.filter(
                        **{f.name + '_id__in': dev_ids}
                    ).count()
                    rel_type = f'FK on_delete={on_del}'
                else:
                    continue
            except Exception as e:
                print(f"    {model._meta.label}.{f.name}: 조회 실패 ({e})")
                continue

            if cnt > 0:
                print(f"    {model._meta.label}.{f.name} [{rel_type}]: {cnt}건")
                found = True

    if not found:
        print("    (없음 — 그렇다면 GeoFence M2M 또는 다른 원인)")
else:
    print("  남은 device 없음")


# [C] zone 외부 FK + M2M 참조 검사
print("\n[C] [시나리오] zone 을 참조하는 외부 모델")
if remaining_zones.exists():
    zone_ids = list(remaining_zones.values_list('pk', flat=True))
    found = False
    for model in apps.get_models():
        if model is GeoFence:
            continue
        for f in model._meta.get_fields():
            related = getattr(f, 'related_model', None)
            if related is not GeoFence:
                continue
            remote = getattr(f, 'remote_field', None)
            if remote is None:
                continue

            try:
                if f.many_to_many:
                    cnt = model.objects.filter(
                        **{f.name + '__in': zone_ids}
                    ).distinct().count()
                    rel_type = 'M2M'
                elif f.many_to_one or f.one_to_one:
                    on_del = remote.on_delete.__name__ if hasattr(remote, 'on_delete') else '?'
                    cnt = model.objects.filter(
                        **{f.name + '_id__in': zone_ids}
                    ).count()
                    rel_type = f'FK on_delete={on_del}'
                else:
                    continue
            except Exception as e:
                print(f"    {model._meta.label}.{f.name}: 조회 실패 ({e})")
                continue

            if cnt > 0:
                print(f"    {model._meta.label}.{f.name} [{rel_type}]: {cnt}건")
                found = True

    if not found:
        print("    (없음)")
else:
    print("  남은 zone 없음")


# [D] GeoFence.confirmed_devices M2M 직접 검사 — 일반 검사에서 잡힐 텐데 명시
print("\n[D] GeoFence.confirmed_devices M2M (device-zone 양쪽)")
if remaining_devs.exists():
    dev_ids = list(remaining_devs.values_list('pk', flat=True))
    # device 를 confirmed_devices 로 가진 zone (시나리오 zone 외에도)
    from_devs_side = GeoFence.objects.filter(
        confirmed_devices__in=dev_ids,
    ).distinct()
    print(f"  sensa_scenario_ device 가 confirmed_devices 에 포함된 zone: "
          f"{from_devs_side.count()}개")
    for z in from_devs_side[:10]:
        nbr_ids = list(z.confirmed_devices.filter(
            device_id__startswith='sensa_scenario_'
        ).values_list('device_id', flat=True))
        print(f"    - zone {z.name} (pk={z.pk}, tier={z.tier}) ← {nbr_ids}")


# [E] 수동 정리 시도 — 안전한 순서
print("\n[E] 수동 정리")
zones_count = GeoFence.objects.filter(name__startswith='[시나리오]').count()
deleted_zones, _ = GeoFence.objects.filter(name__startswith='[시나리오]').delete()
print(f"  zone 삭제: {deleted_zones} (대상 {zones_count})")

try:
    devs_count = Device.objects.filter(device_id__startswith='sensa_scenario_').count()
    deleted_devs, _ = Device.objects.filter(
        device_id__startswith='sensa_scenario_',
    ).delete()
    print(f"  device 삭제: {deleted_devs} (대상 {devs_count})")
except Exception as e:
    print(f"  device 삭제 실패: {type(e).__name__}: {e}")
    print(f"  → fallback: is_active=False")
    Device.objects.filter(
        device_id__startswith='sensa_scenario_',
    ).update(is_active=False)


print("\n" + "═" * 60)
print("  진단 종료")
print("═" * 60 + "\n")
