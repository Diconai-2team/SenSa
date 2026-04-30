"""
realtime/routing.py — WebSocket URL 라우팅

일반 Django urls.py의 WS 버전.
asgi.py의 URLRouter에서 import됨.
"""

from django.urls import path

# HTTP URL 패턴을 정의할 때 쓰는 Django 기본 유틸리티.
# Channels의 URLRouter도 같은 path()를 재사용해서 WS URL을 등록함.

from . import consumers

# 같은 패키지(realtime/) 안의 consumers.py를 가져옴.
# DashboardConsumer가 여기 정의되어 있음.

websocket_urlpatterns = [
    # asgi.py의 URLRouter가 이 리스트를 읽어서 WS 요청을 적절한 Consumer로 연결함.
    # HTTP의 urlpatterns와 같은 역할이지만 WebSocket 전용.
    path("ws/dashboard/", consumers.DashboardConsumer.as_asgi()),
    # 브라우저가 ws://서버주소/ws/dashboard/ 로 WebSocket 연결을 시도하면
    # DashboardConsumer가 처리를 담당하도록 매핑.
    # as_asgi()는 Consumer 클래스를 ASGI 호환 애플리케이션 객체로 변환하는 메서드.
]
