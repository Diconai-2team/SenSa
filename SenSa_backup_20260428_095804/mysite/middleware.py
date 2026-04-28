"""
mysite/middleware.py — 미들웨어 모음

[수록 미들웨어]
  1. InternalAPIKeyMiddleware
       FastAPI 같은 신뢰된 내부 서비스가 X-Internal-API-Key 헤더로
       Django REST API를 호출할 때, 세션/JWT 없이 요청을 통과시킨다.

  2. DevStaticNoCacheMiddleware  ⭐ Step 1A 후속
       DEBUG=True 환경에서 /static/ 및 /media/ 응답에 no-cache 헤더를 강제 적용.
       브라우저 캐시로 인한 정적 파일 옛 버전 로드 문제 영구 해결.

주의:
  - InternalAPIKeyMiddleware 는 AuthenticationMiddleware 뒤에 위치해야 request.user 를 덮어쓸 수 있음
  - DevStaticNoCacheMiddleware 는 응답 단계에서 헤더만 추가하므로 위치 영향 적음
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


class DevStaticNoCacheMiddleware(MiddlewareMixin):
    """
    개발 환경에서 정적/미디어 파일 응답에 no-cache 헤더를 강제 적용한다.

    [도입 배경 — Step 1A 후속]
      Step 1A(가스 패널 페이지네이션) 적용 후, 브라우저가 옛 JS 파일을
      디스크 캐시(304)에서 재사용하여 새 UI 가 동작하지 않는 문제 발생.
      디스크에는 새 파일이지만 브라우저는 if-modified-since 검증을 거쳐
      옛 파일을 재사용. Ctrl+Shift+R 수동 회피로 일회성 해결했으나,
      정적 파일 변경 시마다 재발할 수 있어 코드 수준 영구 해결.

    [동작 원리]
      DEBUG=True 환경에서만 활성화.
      STATIC_URL / MEDIA_URL 로 시작하는 모든 응답에
      Cache-Control: no-cache, no-store, must-revalidate, max-age=0
      Pragma: no-cache
      Expires: 0
      세 헤더를 강제 적용하여 브라우저가 매번 서버에 새로 요청.

    [운영환경 안전성]
      DEBUG=False 시 자동 비활성화. 운영환경의 정적 파일 캐시 정책은
      Nginx, CDN, 또는 ManifestStaticFilesStorage(파일 해시 기반) 등
      별도 계층이 담당하도록 설계.

    [성능 영향]
      개발 환경에서만 동작하므로 운영 트래픽 영향 0.
      개발 시에는 매 요청마다 정적 파일 재전송이 발생하나,
      로컬 환경(localhost) 에선 사실상 무시 가능한 비용.
    """

    def process_response(self, request, response):
        if not settings.DEBUG:
            return response

        path = request.path
        static_url = getattr(settings, 'STATIC_URL', '/static/') or '/static/'
        media_url  = getattr(settings, 'MEDIA_URL',  '/media/')  or '/media/'

        if path.startswith(static_url) or path.startswith(media_url):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        return response