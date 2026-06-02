"""
realtime/metrics.py — WebSocket 연결 수 및 전송 성공/실패 메트릭
"""
from prometheus_client import Counter, Gauge

sensa_ws_connections_active = Gauge(
    'sensa_ws_connections_active',
    '현재 활성 WebSocket 연결 수',
)

sensa_ws_send_total = Counter(
    'sensa_ws_send_total',
    'WebSocket(Channel Layer) 전송 시도 수 (result: success/failure)',
    labelnames=('result',),
)
