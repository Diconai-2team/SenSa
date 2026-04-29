"""
realtime/consumers.py — 대시보드 실시간 WebSocket 처리

Phase B: 연결 확립 + 인증 + 그룹 가입 (여기까지)
Phase C: alarm.new 핸들러 추가
Phase D: worker.position, sensor.update 핸들러 추가
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer

# Django Channels에서 제공하는 WebSocket 기반 클래스.
# 'Async'이므로 비동기(async/await)로 동작하고,
# 'Json'이므로 send/receive 시 JSON 직렬화·역직렬화를 자동으로 처리해 줌.


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

    # 대시보드가 구독할 Channel Layer 그룹 이름 목록.
    # 이 그룹에 메시지가 발행되면 해당 이름의 핸들러 메서드가 자동으로 호출됨.
    GROUPS = ["dashboard.alarms", "dashboard.workers", "dashboard.sensors"]

    async def connect(self):
        # 브라우저가 WebSocket 연결을 시도할 때 가장 먼저 호출되는 메서드.

        # ── 1. 인증 확인 ──
        # AuthMiddlewareStack이 session 쿠키를 읽어서 self.scope["user"] 세팅
        # 로그인 안 된 사용자는 4001 코드로 거절
        # (WS 커스텀 close 코드는 4000~4999 범위 사용)
        user = self.scope.get("user")
        # HTTP 요청과 달리 WS는 헤더가 없으므로, ASGI scope 딕셔너리에서 로그인 사용자를 꺼냄.

        if not user or not user.is_authenticated:
            await self.close(code=4001)
            # 비로그인 사용자(익명 사용자)면 연결을 강제 종료. 4001은 "인증 실패" 의미의 커스텀 코드.
            return

        # ── 2. 세 그룹 전부 가입 ──
        for group in self.GROUPS:
            await self.channel_layer.group_add(group, self.channel_name)
            # Channel Layer의 Redis(또는 InMemory) 그룹에 이 연결의 채널명을 등록.
            # 이후 publishers.py에서 해당 그룹으로 메시지를 보내면 이 연결이 수신함.

        # ── 3. 연결 수락 ──
        await self.accept()
        # WebSocket 핸드셰이크를 완료하고 연결을 공식 수락. 이 전에 close()하면 연결 자체가 거절됨.

        # ── 4. 연결 성공 인사 (브라우저가 "진짜 붙었네" 확인용) ──
        await self.send_json(
            {
                "type": "connection.established",
                "user": user.username,
                "groups": self.GROUPS,
            }
        )
        # 연결 직후 브라우저에 환영 메시지 전송. 어떤 그룹에 가입됐는지도 알려줘서
        # 프론트엔드에서 디버깅할 때 유용함.

    async def disconnect(self, close_code):
        """연결 끊기면 모든 그룹에서 빠짐 — 메모리 누수 방지"""
        # 브라우저 탭이 닫히거나 네트워크가 끊기면 자동 호출됨.
        for group in self.GROUPS:
            await self.channel_layer.group_discard(group, self.channel_name)
            # Channel Layer 그룹에서 이 연결의 채널명을 제거.
            # 안 하면 끊긴 연결로 계속 메시지를 보내려다 에러가 쌓임.

    async def receive_json(self, content, **kwargs):
        """
        클라이언트 → 서버 메시지 처리
        Phase B에서는 ping/pong만. 나머지는 서버 → 클라이언트 단방향.
        """
        # 브라우저가 WS로 JSON 메시지를 보낼 때 호출되는 메서드.
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})
            # 브라우저가 "살아있어?" 신호(ping)를 보내면 "살아있어"(pong)로 응답.
            # 일부 로드밸런서나 프록시가 일정 시간 무통신이면 WS를 끊어버리므로
            # 프론트에서 주기적으로 ping을 보내 연결을 유지하는 패턴.

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
        # Channel Layer가 "alarm.new" 타입 메시지를 받으면 자동으로 이 메서드를 호출.
        # (Django Channels 규칙: 이벤트 타입의 점(.)을 밑줄(_)로 바꾼 이름의 메서드를 찾음)
        await self.send_json(
            {
                "type": "alarm.new",
                "payload": event["payload"],
            }
        )
        # 받은 알람 데이터를 그대로 브라우저로 전달. 브라우저는 type을 보고 알람 UI를 업데이트함.

    async def worker_position(self, event):
        """
        dashboard.workers 그룹에 worker.position 메시지가 오면 호출.
        """
        # "worker.position" → 메서드명 worker_position으로 자동 라우팅됨.
        await self.send_json(
            {
                "type": "worker.position",
                "payload": event["payload"],
            }
        )
        # 작업자의 최신 위치 데이터를 브라우저로 전달. 프론트엔드 지도에서 마커 위치를 갱신하는 데 사용.

    async def sensor_update(self, event):
        """
        dashboard.sensors 그룹에 sensor.update 메시지가 오면 호출.
        """
        # "sensor.update" → 메서드명 sensor_update로 자동 라우팅됨.
        await self.send_json(
            {
                "type": "sensor.update",
                "payload": event["payload"],
            }
        )
        # 센서의 최신 측정값을 브라우저로 전달. 프론트엔드 대시보드 카드·그래프를 실시간 갱신하는 데 사용.
