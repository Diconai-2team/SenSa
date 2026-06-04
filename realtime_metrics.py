# -*- coding: utf-8 -*-
"""
realtime.metrics — WebSocket Channel Layer 발행/연결 메트릭.

평가 지표:
  #4/#13 WebSocket 전송 성공률 / 전송 실패 수
    → ws_publish_total{event_type, result}

  #12    WebSocket 연결 수
    → ws_connections_active (Gauge)

호출 지점:
  realtime/publishers.py 의 _send 안 try/except 후 result 라벨 분기 inc
  realtime/consumers.py 의 connect / disconnect 시 Gauge +/- 1
"""

from prometheus_client import Counter, Gauge

ws_publish_total = Counter(
    'sensa_ws_publish_total',
    'WebSocket Channel Layer 메시지 발행 횟수',
    ['event_type', 'result'],    # event_type: alarm.new|sensor.update|...
                                 # result: success|failure
)

ws_connections_active = Gauge(
    'sensa_ws_connections_active',
    '현재 활성 WebSocket 연결 수 (DashboardConsumer 기준)',
)
