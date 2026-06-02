"""
realtime/consumers.py — 대시보드 실시간 WebSocket 처리

[Phase I-2 변경]
  - dashboard.zones 그룹 추가
  - zone_event 핸들러 추가 — 동적 zone 라이프사이클 이벤트 수신

구독 그룹 (자동 가입):
  dashboard.alarms   — 알람 발생
  dashboard.workers  — 작업자 위치
  dashboard.sensors  — 센서값 변화
  dashboard.zones    — [Phase I-2] zone 라이프사이클 이벤트
"""
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from realtime.metrics import sensa_ws_connections_active


class DashboardConsumer(AsyncJsonWebsocketConsumer):
    """
    대시보드 한 개의 WS 연결로 네 종류의 실시간 데이터를 전부 수신.

    "왜 그룹 4개를 한 연결에 다 묶나?"
      → 브라우저 하나당 WS 연결 1개만 유지하는 게 관리 쉬움.
        4차 스케일에선 트래픽이 크지 않아 충분.
    """

    GROUPS = [
        "dashboard.alarms",
        "dashboard.workers",
        "dashboard.sensors",
        "dashboard.zones",     # [Phase I-2] 추가
    ]

    async def connect(self):
        # 인증 확인
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        # 모든 그룹 가입
        for group in self.GROUPS:
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()
        sensa_ws_connections_active.inc()
        await self.send_json({
            "type": "connection.established",
            "user": user.username,
            "groups": self.GROUPS,
        })

    async def disconnect(self, close_code):
        """연결 끊기면 모든 그룹에서 빠짐 — 메모리 누수 방지"""
        sensa_ws_connections_active.dec()
        for group in self.GROUPS:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        """클라이언트 → 서버 메시지 처리 (ping/pong)."""
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    # ═══════════════════════════════════════════════
    # Channel Layer 이벤트 핸들러
    # ═══════════════════════════════════════════════

    async def alarm_new(self, event):
        """dashboard.alarms 그룹 → 클라이언트로 알람 전달."""
        await self.send_json({
            "type": "alarm.new",
            "payload": event["payload"],
        })

    async def worker_position(self, event):
        """dashboard.workers 그룹 → 클라이언트로 작업자 위치 전달."""
        await self.send_json({
            "type": "worker.position",
            "payload": event["payload"],
        })

    async def sensor_update(self, event):
        """dashboard.sensors 그룹 → 클라이언트로 센서값 전달."""
        await self.send_json({
            "type": "sensor.update",
            "payload": event["payload"],
        })

    async def zone_event(self, event):
        """[Phase I-2] dashboard.zones 그룹 → 클라이언트로 zone 이벤트 전달."""
        await self.send_json({
            "type": "zone.event",
            "payload": event["payload"],
        })
