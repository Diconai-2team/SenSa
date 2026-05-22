"""
metrics.py — FastAPI generator publish 메트릭 정의 [P4-D, 8차 신규]

기본 prometheus_client REGISTRY 에 등록되어 main.py 의
make_asgi_app() 마운트로 자동 노출됨.

사용처:
  poster.py — post_sensor_data / post_worker_location / post_check_geofence
    안에서 .inc() / .observe()
"""
from prometheus_client import Counter, Histogram

# Counter — publish 호출 누적
#   endpoint:  'sensor_data' | 'worker_location' | 'check_geofence'
#   result:    'ok' | 'http_error' | 'exception'
generator_publish_total = Counter(
    'sensa_generator_publish_total',
    'FastAPI generator → Django POST 누적 수 (endpoint/result 별)',
    labelnames=('endpoint', 'result'),
)

# Histogram — publish 1건 소요 시간
#   endpoint:  'sensor_data' | 'worker_location' | 'check_geofence'
generator_publish_duration_seconds = Histogram(
    'sensa_generator_publish_duration_seconds',
    'publish 1건 (Django POST) 소요 시간 (초)',
    labelnames=('endpoint',),
    # 시뮬 환경 latency 분포 — 5ms ~ 1s
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
