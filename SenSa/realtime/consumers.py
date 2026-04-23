"""
realtime/consumers.py — 대시보드 실시간 WebSocket 처리

Phase B: 연결 확립 + 인증 + 그룹 가입 (여기까지)
Phase C: alarm.new 핸들러 추가
Phase D: worker.position, sensor.update 핸들러 추가
"""
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class DashboardConsumer(AsyncJsonWebsocketConsumer):
    """
    대시보드 한 개의 WS 연결로 세 종류의 실시간 데이터를 전부 수신
    
    구독 그룹 (모두 자동 가입):
      dashboard.alarms   — 알람 발생   (Phase C에서 사용)
      dashboard.workers  — 작업자 위치 (Phase D에서 사용)
      dashboard.sensors  — 센서값 변화 (Phase D에서 사용)
    
    "왜 그룹 3개를 한 연결에 다 묶나?"
      → 브라우저 하나당 WS 연결 1개만 유지하는 게 관리 쉬움.
        대신 서버에서 "이 클라이언트가 어떤 종류 메시지를 원하는지" 구분할
        필요가 없음 (다 준다). 트래픽이 크지 않으니 3차~4차 스케일에서는 충분.
    """
    
    GROUPS = ["dashboard.alarms", "dashboard.workers", "dashboard.sensors"]
    
    async def connect(self):
        # ── 1. 인증 확인 ──
        # AuthMiddlewareStack이 session 쿠키를 읽어서 self.scope["user"] 세팅
        # 로그인 안 된 사용자는 4001 코드로 거절
        # (WS 커스텀 close 코드는 4000~4999 범위 사용)
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return
        
        # ── 2. 세 그룹 전부 가입 ──
        for group in self.GROUPS:
            await self.channel_layer.group_add(group, self.channel_name)
        
        # ── 3. 연결 수락 ──
        await self.accept()
        
        # ── 4. 연결 성공 인사 (브라우저가 "진짜 붙었네" 확인용) ──
        await self.send_json({
            "type": "connection.established",
            "user": user.username,
            "groups": self.GROUPS,
        })
    
    async def disconnect(self, close_code):
        """연결 끊기면 모든 그룹에서 빠짐 — 메모리 누수 방지"""
        for group in self.GROUPS:
            await self.channel_layer.group_discard(group, self.channel_name)
    
    async def receive_json(self, content, **kwargs):
        """
        클라이언트 → 서버 메시지 처리
        Phase B에서는 ping/pong만. 나머지는 서버 → 클라이언트 단방향.
        """
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})
    

    # ═══════════════════════════════════════════════
    # Channel Layer 이벤트 핸들러
    # ═══════════════════════════════════════════════
    # publishers._send()가 event_type="alarm.new"로 보낸 메시지는
    # 여기 alarm_new 메서드로 자동 라우팅됨 (점 → 밑줄 변환).
    # Consumer는 각 그룹의 '수신 창구'이고, 변환된 메시지를
    # 클라이언트(브라우저)에게 send_json으로 내려보내는 역할.
    
    async def alarm_new(self, event):
        """
        dashboard.alarms 그룹에 alarm.new 메시지가 오면 호출.
        event는 publishers._send의 두 번째 인자 dict 그대로.
        """
        await self.send_json({
            "type": "alarm.new",
            "payload": event["payload"],
        })
        
    async def worker_position(self, event):
        """
        dashboard.workers 그룹에 worker.position 메시지가 오면 호출.
        """
        await self.send_json({
            "type": "worker.position",
            "payload": event["payload"],
        })
    
    async def sensor_update(self, event):
        """
        dashboard.sensors 그룹에 sensor.update 메시지가 오면 호출.
        """
        await self.send_json({
            "type": "sensor.update",
            "payload": event["payload"],
        })