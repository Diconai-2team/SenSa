"""
mysite/middleware.py — 내부 서비스 인증 미들웨어

FastAPI 같은 신뢰된 내부 서비스가 X-Internal-API-Key 헤더로
Django REST API를 호출할 때, 세션/JWT 없이 요청을 통과시킨다.
P
동작:
  1. 요청이 INTERNAL_API_ALLOWED_PATHS 로 시작하는 경로인지 확인
  2. X-Internal-API-Key 헤더가 settings.INTERNAL_API_KEY 와 일치하는지 확인
  3. 둘 다 만족 → request.user 를 내부 서비스 계정으로 설정
  4. 아니면 기존 인증 흐름 그대로 통과

주의:
  - INTERNAL_API_KEY 가 비어있으면(.env 미설정) 미들웨어는 아무것도 하지 않음
  - 이 미들웨어는 AuthenticationMiddleware 뒤에 위치해야 request.user 를 덮어쓸 수 있음
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.deprecation import MiddlewareMixin


class InternalAPIKeyMiddleware(MiddlewareMixin):
    """내부 서비스 전용 API 키 인증"""

    HEADER_NAME = 'HTTP_X_INTERNAL_API_KEY'  # Django는 헤더 HTTP_ 프리픽스 + 대문자 변환
    SERVICE_USERNAME = '__internal_fastapi__'

    def process_request(self, request):
        # 설정 확인
        expected = getattr(settings, 'INTERNAL_API_KEY', '')
        allowed_paths = getattr(settings, 'INTERNAL_API_ALLOWED_PATHS', [])
        if not expected or not allowed_paths:
            return None

        # 1. 경로 화이트리스트 검사
        if not any(request.path.startswith(p) for p in allowed_paths):
            return None

        # 2. 키 검사
        provided = request.META.get(self.HEADER_NAME, '')
        if not provided or provided != expected:
            return None

        # 3. 내부 서비스 계정으로 인증
        User = get_user_model()
        service_user, _ = User.objects.get_or_create(
            username=self.SERVICE_USERNAME,
            defaults={
                'is_active': True,
                'is_staff': False,
            },
        )
        request.user = service_user

        # 4. DRF의 CSRF 검사 건너뛰기 — 내부 API 키 요청은 세션 기반이 아님
        # 이 플래그는 django.views.decorators.csrf.csrf_exempt 와 동일한 효과
        request._dont_enforce_csrf_checks = True
        
        return None