"""
geofence/scenarios/base.py — Phase D 시나리오 베이스 클래스.

[라이프사이클]
    execute(verify, keep) → 결과 dict
      ├ setup()        : Device 확보, 사전 상태 준비
      ├ run()          : 데이터 주입 + tick / trigger 호출
      ├ expected()     : 기대 결과 dict 반환
      ├ _collect_actual : 실제 결과 자동 수집 (created_zone_ids 기준)
      ├ _verify_actual : verify=True 시 비교
      └ teardown()     : zone + sensordata + device 정리 (keep=True 시 생략)

[격리 보장]
    모든 인공 생성물은 self.created_* 리스트에 기록. teardown 일괄 삭제.
    실 운영 device 와 충돌 방지 위해 device_id 에 'sensa_scenario_' 접두사 강제.
"""
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import List, Optional, Tuple

from django.utils import timezone

from devices.models import Device, SensorData


# 인공 device device_id 접두사. teardown 안전 + 운영 device 와 격리.
DEVICE_PREFIX = 'sensa_scenario_'


class ScenarioBase(ABC):
    """추상 시나리오. 하위 클래스가 setup / run / expected 구현."""

    name: str = ''
    description: str = ''

    def __init__(self):
        self.created_zone_ids: List[int] = []
        self.created_sensordata_ids: List[int] = []
        self.created_device_ids: List[int] = []
        self._actual: dict = {}

    # ── 하위 클래스가 구현해야 할 것 ───────────────────────────────
    @abstractmethod
    def setup(self) -> None:
        """인공 device 확보, baseline 데이터 등 사전 상태."""

    @abstractmethod
    def run(self) -> None:
        """주 시나리오 — 데이터 주입 + zone 생성 + tick 등."""

    @abstractmethod
    def expected(self) -> dict:
        """기대 결과. 지원 키:
            zones_created   (int)
            final_tier      (str | list[str])  포함 검사
            event_types     (list[str])         포함 검사
            critical_count  (int)               일치 검사
            confirmed_count (int)               일치 검사
        """

    # ── 공통 유틸 ─────────────────────────────────────────────────
    def inject_sensor_data(
        self,
        device: Device,
        gas_type: str,
        value: float,
        seconds_ago: float,
        status: str = 'normal',
    ) -> SensorData:
        """SensorData 즉시 주입 + timestamp 강제 (auto_now_add 우회)."""
        sd = SensorData.objects.create(
            device=device, status=status, **{gas_type: value},
        )
        stamp = timezone.now() - timedelta(seconds=seconds_ago)
        SensorData.objects.filter(pk=sd.pk).update(timestamp=stamp)
        self.created_sensordata_ids.append(sd.pk)
        return sd

    def inject_baseline(
        self,
        device: Device,
        gas_type: str,
        value: float,
        count: int = 10,
        start_seconds_ago: float = 500.0,
        interval_seconds: float = 120.0,
    ) -> int:
        """LOOKBACK_RECENT_SEC=300 윈도우 밖 (정상값) 다회 주입.

        함정 #1 회피: start_seconds_ago=500 (>300) 으로 윈도우 분리.
        """
        injected = 0
        for i in range(count):
            sec = start_seconds_ago + i * interval_seconds
            self.inject_sensor_data(device, gas_type, value, sec)
            injected += 1
        return injected

    def inject_spike(
        self,
        device: Device,
        gas_type: str,
        value: float,
        count: int = 3,
        start_seconds_ago: float = 5.0,
        interval_seconds: float = 1.0,
    ) -> int:
        """LOOKBACK_RECENT_SEC=300 윈도우 안 (spike) 다회 주입."""
        injected = 0
        for i in range(count):
            sec = start_seconds_ago + i * interval_seconds
            self.inject_sensor_data(
                device, gas_type, value, sec, status='caution',
            )
            injected += 1
        return injected

    def create_test_device(
        self,
        local_id: str,
        x: float,
        y: float,
        sensor_type: str = 'gas',
    ) -> Device:
        """인공 device 확보. device_id 에 DEVICE_PREFIX 자동 부착.

        같은 local_id 로 재호출 시 좌표만 갱신 (재실행 안정성).
        """
        full_id = f"{DEVICE_PREFIX}{local_id}"
        device, created = Device.objects.get_or_create(
            device_id=full_id,
            defaults={
                'device_name': f"[시나리오] {local_id}",
                'sensor_type': sensor_type,
                'x': x, 'y': y,
                'is_active': True,
            },
        )
        if created:
            self.created_device_ids.append(device.pk)
        # 좌표 동기화 (재사용 시)
        if not created and (device.x != x or device.y != y):
            Device.objects.filter(pk=device.pk).update(x=x, y=y)
            device.refresh_from_db()
        return device

    def age_zone(self, zone, seconds: float) -> None:
        """zone.created_at 을 N 초 과거로 강제 — 시간 경과 시뮬레이션.

        운영 환경에서는 Celery beat (기본 30초 주기) tick 누적으로
        zone 의 elapsed 가 자연스럽게 증가하지만, 시나리오는 즉시 실행
        이므로 zone 생성 직후 elapsed ≈ 0 이 된다. 이 상태로 tick 을
        호출하면 update_zone_radius 가 diffusion_radius(gas, ~0) ≈ 0 으로
        반경을 줄여 이웃 후보가 0 개가 된다 (= 승격 불가).

        이 helper 는 created_at 을 강제로 과거 시점으로 보내 운영의
        압축 시간을 시뮬레이션. Phase D 시나리오에서 zone 생성 직후
        tick 검증 시 반드시 호출.

        Args:
            zone:    GeoFence 인스턴스 (이미 DB 저장됨)
            seconds: 과거로 보낼 시간 (초). 일반적으로
                     zone_lifecycle.INITIAL_ELAPSED_SEC (=10) 이상.
        """
        from datetime import timedelta
        from geofence.models import GeoFence

        new_created = timezone.now() - timedelta(seconds=seconds)
        GeoFence.objects.filter(pk=zone.pk).update(created_at=new_created)
        zone.refresh_from_db()

    # ── 라이프사이클 진입점 ────────────────────────────────────────
    def execute(
        self,
        verify: bool = False,
        keep: bool = False,
        demo_ttl_seconds: int = None,
    ) -> dict:
        """전체 실행. 예외 발생해도 teardown 보장 (keep=False).

        Args:
            verify: True 시 expected vs actual 비교
            keep:   True 시 teardown 스킵 (zone/device DB 에 남김)
            demo_ttl_seconds: 시연 모드. 양수면 zone 들의 expires_at 을
                              N 초 후로 강제하고 teardown 스킵.
                              expire_zones Celery tick 이 N 초 후 자동 만료
                              → 화면에서도 자연 소실. 다음 execute() 의
                              _cleanup_all_scenario_artifacts() 가 device 수거.
        """
        # ── 시작 전: 이전 실행 잔존 시나리오 객체 자동 정리 ──
        # teardown 실패 (외부 주입자 race 등) 후 재실행 시에도 안전.
        self._cleanup_all_scenario_artifacts()

        # demo 모드면 keep 강제 활성 (zone 화면 노출 유지용)
        if demo_ttl_seconds is not None and demo_ttl_seconds > 0:
            keep = True

        result = {
            'name': self.name,
            'description': self.description,
            'started_at': timezone.now().isoformat(),
            'status': 'pending',
        }

        try:
            self.setup()
            self.run()

            self._actual = self._collect_actual()
            result['actual'] = self._actual
            result['expected'] = self.expected()

            if verify:
                ok, diffs = self._verify_actual()
                result['verify_ok'] = ok
                if not ok:
                    result['verify_diffs'] = diffs

            result['status'] = 'success'

        except Exception as e:
            result['status'] = 'failed'
            result['error'] = f"{type(e).__name__}: {e}"
            # teardown 시도 후 예외 재발생
            if not keep:
                try:
                    self.teardown()
                    result['cleaned_up'] = True
                except Exception:
                    result['cleaned_up'] = False
            raise

        else:
            if keep:
                result['cleaned_up'] = False
                result['kept_zone_ids'] = list(self.created_zone_ids)
                result['kept_device_ids'] = list(self.created_device_ids)

                # ── demo 모드: zone 의 expires_at 을 N 초 후로 강제 ──
                # expire_zones Celery tick (30s) 이 자동 만료 처리.
                if demo_ttl_seconds is not None and demo_ttl_seconds > 0:
                    from datetime import timedelta
                    from geofence.models import GeoFence

                    new_expires = timezone.now() + timedelta(
                        seconds=demo_ttl_seconds,
                    )
                    GeoFence.objects.filter(
                        id__in=self.created_zone_ids,
                    ).update(expires_at=new_expires)
                    result['demo_mode'] = True
                    result['demo_ttl_seconds'] = demo_ttl_seconds
                    result['expires_at'] = new_expires.isoformat()
            else:
                self.teardown()
                result['cleaned_up'] = True

        finally:
            result['ended_at'] = timezone.now().isoformat()

        return result

    # ── 결과 수집 + 검증 ──────────────────────────────────────────
    def _collect_actual(self) -> dict:
        from geofence.models import GeoFence, ZoneEvent

        zones = GeoFence.objects.filter(id__in=self.created_zone_ids)
        events = ZoneEvent.objects.filter(
            zone_id__in=self.created_zone_ids,
        ).order_by('created_at')

        return {
            'zones_created':    zones.count(),
            'final_tiers':      list(zones.values_list('tier', flat=True)),
            'event_types':      list(events.values_list('event_type', flat=True)),
            'critical_count':   zones.filter(tier='critical').count(),
            'confirmed_count':  zones.filter(tier='confirmed').count(),
            'tentative_count':  zones.filter(tier='tentative').count(),
        }

    def _verify_actual(self) -> Tuple[bool, List[str]]:
        expected = self.expected()
        actual = self._actual
        diffs: List[str] = []

        if 'zones_created' in expected:
            if actual['zones_created'] != expected['zones_created']:
                diffs.append(
                    f"zones_created: expected={expected['zones_created']} "
                    f"actual={actual['zones_created']}"
                )

        if 'final_tier' in expected:
            exp = expected['final_tier']
            exp_list = [exp] if isinstance(exp, str) else list(exp)
            actual_tiers = set(actual['final_tiers'])
            missing = [t for t in exp_list if t not in actual_tiers]
            if missing:
                diffs.append(
                    f"final_tier: missing={missing} "
                    f"actual_tiers={actual['final_tiers']}"
                )

        if 'event_types' in expected:
            actual_events = set(actual['event_types'])
            missing = [et for et in expected['event_types']
                       if et not in actual_events]
            if missing:
                diffs.append(
                    f"event_types: missing={missing} "
                    f"actual={actual['event_types']}"
                )

        for key in ('critical_count', 'confirmed_count'):
            if key in expected and actual[key] != expected[key]:
                diffs.append(
                    f"{key}: expected={expected[key]} actual={actual[key]}"
                )

        return (len(diffs) == 0, diffs)

    # ── cleanup ──────────────────────────────────────────────────
    def teardown(self) -> None:
        """현 실행 cleanup. 외부 데이터 주입자 (fastapi_generator) race 회피.

        [순서]
            1. zone 삭제 (created_zone_ids)
            2. device 비활성화 → 외부 주입자가 더 이상 데이터 안 흘림
            3. SensorData device 기준 일괄 삭제 (외부 주입까지 포함)
            4. device 삭제 (실패 시 비활성화 상태로 유지 — 다음 실행이 정리)
        """
        from geofence.models import GeoFence

        # 1. zone 정리
        if self.created_zone_ids:
            GeoFence.objects.filter(id__in=self.created_zone_ids).delete()

        if self.created_device_ids:
            # 2. device 비활성화 — fastapi_generator 등 외부 주입자 차단.
            #    sensor_type='gas', is_active=True 필터 통과하는 자동 데이터
            #    주입을 즉시 멈춤.
            Device.objects.filter(
                id__in=self.created_device_ids,
            ).update(is_active=False)

            # 3. SensorData 일괄 삭제 — 외부 주입까지 모두 정리.
            #    created_sensordata_ids 기준만으로는 fastapi_generator 가
            #    추가한 row 가 남아 device 삭제 시 race 발생.
            SensorData.objects.filter(
                device_id__in=self.created_device_ids,
            ).delete()

            # 4. device 삭제. race 로 실패해도 is_active=False 유지되어
            #    운영 시야에서 제외되며, 다음 execute() 의 자동 정리가 수거.
            try:
                Device.objects.filter(
                    id__in=self.created_device_ids,
                ).delete()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f'시나리오 device cleanup 실패 (비활성화 유지): {e}'
                )

        elif self.created_sensordata_ids:
            # device 추적 안 됐을 때 fallback — id 기준 정리만
            SensorData.objects.filter(
                id__in=self.created_sensordata_ids,
            ).delete()

    # ── 잔존물 자동 정리 (재실행 안정성) ────────────────────────────
    def _cleanup_all_scenario_artifacts(self) -> None:
        """모든 시나리오 잔존물 일괄 정리 — execute() 시작 시 호출.

        이전 실행이 teardown 실패한 경우 (외부 주입자 race 등) 남은 device
        와 SensorData, zone 을 일괄 정리. 비파괴적: DEVICE_PREFIX 시작 + 시나리오
        이름 패턴만 대상이라 운영 데이터 영향 없음.
        """
        from geofence.models import GeoFence

        # 1. 시나리오 zone 정리
        GeoFence.objects.filter(name__startswith='[시나리오]').delete()

        # 2. 시나리오 device 의 SensorData 정리 (외부 주입 포함)
        SensorData.objects.filter(
            device__device_id__startswith=DEVICE_PREFIX,
        ).delete()

        # 3. 시나리오 device 정리
        try:
            Device.objects.filter(
                device_id__startswith=DEVICE_PREFIX,
            ).delete()
        except Exception:
            # 만에 하나 실패해도 비활성화는 보장
            Device.objects.filter(
                device_id__startswith=DEVICE_PREFIX,
            ).update(is_active=False)
