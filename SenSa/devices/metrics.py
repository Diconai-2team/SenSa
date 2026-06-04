"""
devices/metrics.py — API 수신 및 DB 저장 메트릭 + 센서 실측값 게이지

[시나리오 관측 A] 추가 (관측 공백 G1/G2/G3 해결):
  - G1: 가스 농도(ppm)/전력값 실시간 추이 (op_* 시나리오 ramp-up 곡선)
  - G2: device 차원 — 어느 센서가 누출원/영향권인지 식별
  - G3: 가스 종류 차원 — op_h2s(H2S) vs op_single(CO) 구분
"""
from prometheus_client import REGISTRY, Counter
from prometheus_client.core import GaugeMetricFamily

sensa_api_requests_total = Counter(
    'sensa_api_requests_total',
    'SensorData POST 수신 수 (sensor_type별, result: success/error)',
    labelnames=('sensor_type', 'result'),
)

sensa_db_save_total = Counter(
    'sensa_db_save_total',
    'SensorData DB 저장 수 (sensor_type별, result: success/failure)',
    labelnames=('sensor_type', 'result'),
)


# ═══════════════════════════════════════════════════════════
# 센서 실측값 Collector (G1/G2/G3)
# ═══════════════════════════════════════════════════════════
#   매 /metrics scrape 시점에 활성 device 별 최신 SensorData 를 조회해
#   device_id × sensor(필드) × sensor_type 라벨로 노출.
#
#   - set_function 은 라벨 child 에 안 통하므로(geofence/metrics.py 참고)
#     다중 라벨 게이지는 Collector 로 구현.
#   - 정상 POST(devices/views.py)와 시나리오 Celery(tasks_scenario.py)가
#     모두 동일 DB 의 SensorData 에 쓰므로, Django 단일 프로세스 collector 가
#     두 경로를 한 번에 포착(프로세스 분산/job 중복 없음).
#   - "현재 상태" 라 scrape 시점 조회가 자연스럽고, 사라진 device 의 stale
#     series 도 남지 않음.
#
#   카디널리티: 활성 device 수 × 필드 수(가스 9 / 전력 3). 현 규모(센서 5~27)
#   에서 수백 건 — 안전. 디바이스가 수백개로 늘면 Postgres 데이터소스 직접
#   쿼리로 전환 권장.

GAS_FIELDS = ['co', 'h2s', 'co2', 'o2', 'no2', 'so2', 'o3', 'nh3', 'voc']
POWER_FIELDS = ['current', 'voltage', 'watt']


class SensorValueCollector:
    """활성 device 의 최신 SensorData 실측값을 scrape 시점에 노출."""

    def collect(self):
        g = GaugeMetricFamily(
            'sensa_sensor_value',
            '센서 최신 실측값 (device_id × sensor 필드 × sensor_type). '
            '가스=ppm/%, 전력=A/V/W. op_* 시나리오 ramp-up 추적용.',
            labels=['device_id', 'sensor', 'sensor_type'],
        )
        try:
            from devices.models import Device, SensorData

            devices = Device.objects.filter(is_active=True).only(
                'id', 'device_id', 'sensor_type',
            )
            for d in devices:
                sd = (SensorData.objects
                      .filter(device=d)
                      .order_by('-timestamp')
                      .first())
                if sd is None:
                    continue
                fields = GAS_FIELDS if d.sensor_type == 'gas' else POWER_FIELDS
                for f in fields:
                    v = getattr(sd, f, None)
                    if v is None:
                        continue
                    g.add_metric([d.device_id, f, d.sensor_type], float(v))
        except Exception:
            # 메트릭 수집 실패가 scrape 전체를 깨지 않도록 격리 — 부분 결과 노출
            pass
        yield g


def _register_collectors():
    """중복 등록 방지하며 collector 등록 (테스트 다중 import 안전)."""
    try:
        REGISTRY.register(SensorValueCollector())
    except ValueError:
        pass  # 이미 등록됨 (동일 메트릭 이름) — 무시


_register_collectors()
