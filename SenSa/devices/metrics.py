"""
devices/metrics.py — API 수신 및 DB 저장 메트릭
"""
from prometheus_client import Counter

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
