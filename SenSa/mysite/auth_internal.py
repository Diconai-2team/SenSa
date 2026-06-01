"""
mysite/auth_internal.py — 내부 서비스(FastAPI generator) 전용 DRF 인증 클래스.

[배경]
기존 InternalAPIKeyMiddleware 는 request.user 만 세팅하지만, DRF APIView 는
자체 인증 단계에서 request.user 를 재평가하므로 미들웨어 세팅이 무시되어
DEFAULT_PERMISSION_CLASSES=[IsAuthenticated] 에서 401 이 발생했다.

이 클래스는 미들웨어와 동일한 헤더/계정 규약으로 'DRF 레벨'에서 인증을 완료한다.
  - X-Internal-API-Key 헤더가 settings.INTERNAL_API_KEY 와 일치하면
    내부 서비스 계정(__internal_fastapi__)으로 인증 성공 (user, None) 반환.
  - 헤더가 없거나 불일치면 None 반환 → 다음 인증기(JWT/Session)로 패스.
    → 브라우저 세션/JWT 동작에 영향 없음. generator 내부 경로만 통과.
  - INTERNAL_API_KEY 미설정 시 동작 안 함(안전).
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication

HEADER_NAME = 'HTTP_X_INTERNAL_API_KEY'   # 미들웨어와 동일
SERVICE_USERNAME = '__internal_fastapi__'  # 미들웨어와 동일


class InternalAPIKeyAuthentication(BaseAuthentication):
    """X-Internal-API-Key 헤더 기반 내부 서비스 인증 (DRF)."""

    def authenticate(self, request):
        expected = getattr(settings, 'INTERNAL_API_KEY', '') or ''
        if not expected:
            return None  # 키 미설정 → 이 인증기 비활성

        provided = request.META.get(HEADER_NAME, '')
        if not provided or provided != expected:
            return None  # 없음/불일치 → 다음 인증기로 패스 (세션/JWT 보존)

        User = get_user_model()
        service_user, _ = User.objects.get_or_create(
            username=SERVICE_USERNAME,
            defaults={'is_active': True, 'is_staff': False},
        )
        # 비활성 계정이면 인증 실패 처리(방어적)
        if not service_user.is_active:
            return None
        return (service_user, None)
