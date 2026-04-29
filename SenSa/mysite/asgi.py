"""
ASGI config for mysite project.

역할:
  - http:      Django의 기존 HTTP 처리
  - websocket: realtime 앱의 WS 라우팅 (Phase B에서 추가)
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")

# Django HTTP 앱을 먼저 초기화 (채널스 import보다 위)
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from realtime.routing import websocket_urlpatterns  # noqa: E402


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # ─ WebSocket ─
        # 바깥→안쪽으로 요청이 흐름:
        #   1. AllowedHostsOriginValidator : Origin 헤더가 ALLOWED_HOSTS에 있는지 검사 (CSRF류 방어)
        #   2. AuthMiddlewareStack          : session 쿠키 → self.scope["user"]
        #   3. URLRouter                    : URL 매칭 후 Consumer로 dispatch
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
