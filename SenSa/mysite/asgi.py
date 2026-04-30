"""
ASGI config for mysite project.

역할:
  - http:      Django의 기존 HTTP 처리
  - websocket: realtime 앱의 WS 라우팅 (Phase B에서 추가)
"""
# ⭐ ASGI vs WSGI: WSGI는 동기 HTTP만, ASGI는 HTTP + WebSocket 동시 지원
#    SenSa는 실시간 알람/위치 broadcast가 핵심이라 ASGI 필수
#    실제 구동 시 daphne/uvicorn 같은 ASGI 서버가 이 파일을 진입점으로 사용

import os

from django.core.asgi import get_asgi_application
# Django의 표준 HTTP ASGI 핸들러 — wsgi.py와 같은 역할이지만 async 인터페이스

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
# settings 모듈 위치를 환경변수로 지정 — Django 모든 import의 기준
# setdefault — 이미 환경변수에 있으면 덮어쓰지 않음 (운영 환경 오버라이드 가능)

# Django HTTP 앱을 먼저 초기화 (채널스 import보다 위)
django_asgi_app = get_asgi_application()
# ⭐ 순서가 중요한 이유: get_asgi_application()이 Django의 앱 레지스트리를 setup하기 때문
#    아래 channels import가 이 setup 결과에 의존 — 순서 바뀌면 AppRegistryNotReady 에러

from channels.auth import AuthMiddlewareStack       # noqa: E402
# WebSocket 연결 시 세션 쿠키를 읽어 self.scope["user"]에 채워줌
# E402: 모듈 상단에 import 모아둬야 한다는 PEP8 규칙 위반 — 위 setup 의존성 때문에 의도적
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
# ProtocolTypeRouter: http vs websocket 분기 / URLRouter: WS URL 라우팅
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
# CSRF 비슷한 역할 — Origin 헤더가 ALLOWED_HOSTS에 등록된 도메인이어야만 통과

from realtime.routing import websocket_urlpatterns  # noqa: E402
# realtime 앱의 WS URL 패턴 — 실제 Consumer 매핑은 realtime/routing.py에 정의


application = ProtocolTypeRouter({
    # ⭐ ASGI 서버가 이 'application' 변수를 진입점으로 사용 (관례)
    "http": django_asgi_app,
    # HTTP 요청은 기존 Django 그대로 처리 — accounts/dashboard/devices 등 모든 뷰
    
    # ─ WebSocket ─
    # 바깥→안쪽으로 요청이 흐름:
    #   1. AllowedHostsOriginValidator : Origin 헤더가 ALLOWED_HOSTS에 있는지 검사 (CSRF류 방어)
    #   2. AuthMiddlewareStack          : session 쿠키 → self.scope["user"]
    #   3. URLRouter                    : URL 매칭 후 Consumer로 dispatch
    "websocket": AllowedHostsOriginValidator(
        # 1단계: Origin 검증 — XSS로 탈취된 토큰을 외부 사이트에서 사용하는 공격 차단
        AuthMiddlewareStack(
            # 2단계: 인증 — Django 세션 기반 (JWT 미사용)
            # ⚠️ 비로그인 WS 연결도 허용 — Consumer에서 self.scope["user"].is_authenticated 체크 필요
            URLRouter(websocket_urlpatterns)
            # 3단계: URL 매칭 — /ws/alarms/, /ws/sensors/ 등을 적절한 Consumer로
        )
    ),
})
# ⭐ HTTP/WS 양방향 지원 구조 — daphne로 띄우면 한 포트에서 둘 다 받음