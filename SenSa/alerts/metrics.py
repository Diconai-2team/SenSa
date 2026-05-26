"""
alerts/metrics.py — 알람 비즈니스 메트릭 정의 [P4-C, 8차 신규]

prometheus_client 의 모듈 레벨 Counter 정의.
정의만 하면 django-prometheus 의 /metrics 에 자동 노출됨
(prometheus_client 기본 레지스트리 공유).

사용처:
  alerts/services/sensor_evaluator.py — 알람 생성/throttle 시 .inc()
"""
from prometheus_client import Counter

# 알람 생성 누적 (Counter)
#   labels:
#     sensor_type  — 'gas' | 'power' | ...
#     alarm_level  — 'warning' | 'critical' | 'recovery' | ...
#     reason       — 'transition' | 'ongoing'
alarm_created_total = Counter(
    'sensa_alarm_created_total',
    '센서 알람 생성 수 (transition/ongoing 별, alarm_level 별)',
    labelnames=('sensor_type', 'alarm_level', 'reason'),
)

# 60s throttle 차단 누적 (Counter)
#   labels:
#     sensor_type  — 'gas' | 'power' | ...
#     reason       — 'within_interval' (60s 안에 같은 sensor 재발 시도)
alarm_throttled_total = Counter(
    'sensa_alarm_throttled_total',
    'throttle 차단된 잠재 알람 수 (RE_ALARM_INTERVAL_SEC 60s 중복 방지)',
    labelnames=('sensor_type', 'reason'),
)
