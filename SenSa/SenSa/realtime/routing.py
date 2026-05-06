"""
realtime/routing.py — WebSocket URL 라우팅

일반 Django urls.py의 WS 버전.
asgi.py의 URLRouter에서 import됨.
"""
from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('ws/dashboard/', consumers.DashboardConsumer.as_asgi()),
]