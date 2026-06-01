"""
geofence/tasks_scenario.py — Phase Demo v3.1 spike 지속 주입.

[Phase Demo v3.1 변경점 — 핵심]
    v3 에서 발견된 버그: SensorData.objects.create() 직접 호출은 frontend
    가스 패널에 반영 안 됨. devices/views.py 의 POST API 만 publish_sensor_update
    호출 → WebSocket 푸시 → SenSa.emit('gasData', ...) → 패널 갱신.

    v3.1: SensorData create 직후 publish_sensor_update 명시 호출.
    fastapi_generator 와 동일한 흐름으로 frontend 에 spike 반영.

[기존 자동 중단 메커니즘 유지]
    zone is_active 확인 + countdown 패턴 (worker 친화).
"""
import random
import logging
from celery import shared_task


logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True)
def sustain_spike_task(
    self,
    zone_id: int,
    sensor_id: int,
    gas: str,
    spike_value: float,
    noise: float,
    interval_sec: float,
    max_steps: int,
    step: int = 0,
    base_value: float = None,
    ramp_up_sec: float = 30.0,
    sustain_sec: float = None,
    ramp_down_sec: float = None,
):
    """zone 살아있는 동안 sensor 에 spike 지속 주입 + WebSocket 푸시.

    [점진 증가 (Phase Realism)]
        base_value 가 지정되면 ramp_up_sec 동안 base → spike_value 선형 증가.
        예: CO 5 → 280 ppm 까지 30초 동안 점진 ramp-up.

    [자연 복귀 (산업안전 기반)]
        sustain_sec, ramp_down_sec 모두 지정 시 5단계 곡선:
          ramp_up (0~ramp_up_sec)         base → spike
          sustain (ramp_up_sec~+sustain)  spike 정점 유지
          ramp_down (~+ramp_down)         spike → base 자연 복귀
          종료                              base 도달 후 task return
        둘 중 하나라도 None이면 기존 동작 (cliff drop 후 max_steps 종료).

    Args:
        zone_id: 관련 GeoFence id (사라지면/비활성화면 task 자동 종료)
        sensor_id: spike 주입 대상 Device id
        gas: 'co' | 'h2s' | 'co2' | 'nh3'
        spike_value: 목표 spike 값 (ramp-up 종료 후 도달)
        noise: ± 노이즈
        interval_sec: 다음 spike 까지 간격
        max_steps: 안전 상한
        step: 현재 step (재귀 카운터, 외부에서 0 으로 호출)
        base_value: ramp-up 시작 값 (None = 즉시 spike_value)
        ramp_up_sec: 점진 증가 시간 (초)
    """
    from devices.models import Device, SensorData
    from geofence.models import GeoFence
    from realtime.publishers import publish_sensor_update

    # 1. zone 살아있는지 확인
    if not GeoFence.objects.filter(id=zone_id, is_active=True).exists():
        logger.info(
            '[sustain_spike] zone=%s inactive, stopping at step=%s',
            zone_id, step,
        )
        return

    # 2. 안전 상한
    if step >= max_steps:
        logger.info(
            '[sustain_spike] zone=%s max_steps=%s reached',
            zone_id, max_steps,
        )
        return

    # 3. spike 1건 주입
    try:
        sensor = Device.objects.get(id=sensor_id)
    except Device.DoesNotExist:
        logger.warning(
            '[sustain_spike] sensor=%s missing, stopping',
            sensor_id,
        )
        return

    # ── 곡선 계산 (5단계) ──
    elapsed_in_spike = step * interval_sec
    base_v = base_value if base_value is not None else spike_value

    if elapsed_in_spike < ramp_up_sec:
        # Phase 1: ramp-up (base → spike)
        progress = elapsed_in_spike / ramp_up_sec
        target = base_v + (spike_value - base_v) * progress
    elif sustain_sec is None or elapsed_in_spike < ramp_up_sec + sustain_sec:
        # Phase 2: sustain (spike 유지; sustain_sec None이면 무기한)
        target = spike_value
    elif ramp_down_sec is not None and \
         elapsed_in_spike < ramp_up_sec + sustain_sec + ramp_down_sec:
        # Phase 3: ramp-down (spike → base, 자연 복귀)
        progress_down = (elapsed_in_spike - ramp_up_sec - sustain_sec) / ramp_down_sec
        target = spike_value - (spike_value - base_v) * progress_down
    else:
        # Phase 4: 자연 종료
        logger.info(
            '[sustain_spike] zone=%s natural-end at step=%s (elapsed=%.1fs)',
            zone_id, step, elapsed_in_spike,
        )
        return

    noise_val = random.uniform(-noise, noise)
    value = max(0.0, target + noise_val)

    # ── 동적 status (농도로 결정 — caution 하드코딩 제거) ──
    from alerts.services.classifiers import GAS_THRESHOLDS
    thr = GAS_THRESHOLDS.get(gas, {})
    if value >= thr.get('danger', float('inf')):
        status = 'danger'
    elif value >= thr.get('caution', float('inf')):
        status = 'caution'
    else:
        status = 'normal'

    try:
        sd = SensorData.objects.create(
            device=sensor, status=status,
            **{gas: value},
        )
    except Exception as e:
        logger.error('[sustain_spike] SensorData create failed: %s', e)
        sd = None

    # 4. ★ frontend 푸시 (Phase Demo v3.1 핵심 추가) ★
    #     fastapi_generator 가 POST API 호출 시 자동 실행하는 publish 를
    #     명시 호출. WebSocket → SenSa.emit('gasData') → 가스 패널 갱신.
    if sd is not None:
        # 운영 흐름과 동일한 4가스 dict (없는 값은 0)
        # 가스 패널은 9종 표시하지만 spike 는 한 가스만 — 나머지는 baseline 추정값
        # 더 정확히: 동일 sensor 의 직전 SensorData 에서 다른 가스 값 가져옴
        last_sd = SensorData.objects.filter(
            device=sensor,
        ).exclude(id=sd.id).order_by('-timestamp').first()

        values = {}
        for k in ['co', 'h2s', 'co2', 'o2', 'no2', 'so2', 'o3', 'nh3', 'voc']:
            if k == gas:
                values[k] = value
            elif last_sd and getattr(last_sd, k, None) is not None:
                values[k] = getattr(last_sd, k)
            # 없으면 키 자체 안 포함 (frontend 가 빈 값 처리)

        try:
            # Device 자체 status 도 갱신 (sensor 마커 색상 일관성)
            sensor.status = status
            sensor.save(update_fields=['status'])

            publish_sensor_update({
                'device_id':   sensor.device_id,
                'sensor_type': 'gas',
                'status':      status,
                'values':      values,
                'timestamp':   sd.timestamp.isoformat(),
            })
        except Exception as e:
            logger.error('[sustain_spike] publish failed: %s', e)

    # 4.5 [알람 일원화 A] 실데이터와 동일한 평가 호출 → 알람 생성
    if sd is not None:
        try:
            from alerts.services import evaluate_sensor
            evaluate_sensor(
                device_id=sensor.device_id,
                sensor_type='gas',
                observed_status=status,
                raw_value=value,
            )
        except Exception as _e:
            logger.warning('[sustain_spike] evaluate_sensor 실패: %s', _e)

    # 5. 다음 step 큐잉 (countdown) — 신규 kwargs 전파
    sustain_spike_task.apply_async(
        args=[
            zone_id, sensor_id, gas, spike_value, noise,
            interval_sec, max_steps, step + 1, base_value, ramp_up_sec,
        ],
        kwargs={
            'sustain_sec':   sustain_sec,
            'ramp_down_sec': ramp_down_sec,
        },
        countdown=interval_sec,
    )
