"""
WSGI config for mysite project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""
# ⭐ ASGI(asgi.py)와 별도 존재 — 동기 HTTP만 필요한 환경(예: Apache mod_wsgi)에서 사용 가능
# ⚠️ SenSa는 WebSocket 필요 → 실제 운영은 daphne/uvicorn으로 asgi.py 진입점 사용
#    이 파일은 사실상 미사용 (Django 프로젝트 생성 시 자동 생성된 기본 파일)

import os
# 환경변수 설정용

from django.core.wsgi import get_wsgi_application
# Django의 표준 WSGI 핸들러 팩토리

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
# settings 모듈 위치 지정 — asgi.py와 동일 (둘 중 어느 진입점이든 같은 settings 사용)

application = get_wsgi_application()
# WSGI 서버가 'application' 변수를 진입점으로 사용 (PEP 3333 표준)
# ⚠️ asgi.py와 동일한 이름이라 헷갈리기 쉬움 — 한쪽만 사용하면 됨