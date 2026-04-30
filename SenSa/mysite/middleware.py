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
# ⭐ Django 미들웨어: 모든 HTTP 요청/응답이 통과하는 파이프라인
#    settings.MIDDLEWARE 리스트에 등록된 순서대로 실행됨 (요청은 위→아래, 응답은 아래→위)

from django.conf import settings
from django.contrib.auth import get_user_model
# 커스텀 User 모델(accounts.User)을 안전하게 가져오는 표준 방법
from django.utils.deprecation import MiddlewareMixin
# 신구 미들웨어 인터페이스 호환 mixin — process_request/process_response 둘 다 사용 가능


class InternalAPIKeyMiddleware(MiddlewareMixin):
    """내부 서비스 전용 API 키 인증"""
    # ⭐ 시스템 아키텍처 단서: SenSa는 Django + FastAPI 하이브리드
    #    FastAPI가 알람 발행 등을 위해 Django REST API를 호출할 때 사용
    #    JWT/세션 부재 환경에서 신뢰 가능한 내부 호출만 통과시킴

    HEADER_NAME = 'HTTP_X_INTERNAL_API_KEY'  # Django는 헤더 HTTP_ 프리픽스 + 대문자 변환
    # 클라이언트가 보내는 X-Internal-API-Key는 Django request.META에서 HTTP_X_INTERNAL_API_KEY로 변환됨
    SERVICE_USERNAME = '__internal_fastapi__'
    # 더블 언더스코어 prefix/suffix — 일반 사용자가 등록할 수 없는 패턴
    # 단, accounts.SignupSerializer.validate_username의 정규식 ^[a-zA-Z0-9_]+$는 _ 허용 → 충돌 가능
    # ⚠️ 운영 시 추가 검증: 일반 가입 경로에서 이 username 차단 필요

    def process_request(self, request):
        # 모든 요청에 대해 가장 먼저 호출되는 훅 — 인증 결정
        
        # 설정 확인
        expected = getattr(settings, 'INTERNAL_API_KEY', '')
        # settings.INTERNAL_API_KEY가 없으면 빈 문자열 — 실수로 설정 누락 시 자동 비활성화
        allowed_paths = getattr(settings, 'INTERNAL_API_ALLOWED_PATHS', [])
        # 어느 경로에 이 인증을 적용할지 화이트리스트
        if not expected or not allowed_paths:
            return None
            # 둘 중 하나라도 비어있으면 미들웨어 자체 비활성화 — 안전한 기본값

        # 1. 경로 화이트리스트 검사
        if not any(request.path.startswith(p) for p in allowed_paths):
            return None
            # 등록된 경로(/dashboard/api/* 등) 외에는 무시 — 권한 상승 공격 차단
            # 예: 어드민 페이지에 API 키만 보낸다고 admin 권한 얻을 수 없음

        # 2. 키 검사
        provided = request.META.get(self.HEADER_NAME, "")
        if not provided or provided != expected:
            return None
            # 키 없거나 다르면 그냥 통과 — 일반 인증(세션/JWT)으로 처리되도록
            # ⚠️ 타이밍 공격 가능 — `==` 비교는 문자열 길이별 시간 차 발생
            #    개선안: hmac.compare_digest 사용

        # 3. 내부 서비스 계정으로 인증
        User = get_user_model()
        service_user, _ = User.objects.get_or_create(
            username=self.SERVICE_USERNAME,
            defaults={
                'is_active': True,
                'is_staff': False,
                # is_superuser 누락 — 모델 default(False)에 의지
            },
        )
        # 첫 호출 시 자동 생성 — 운영자가 미리 등록할 필요 없음
        # ⚠️ 매 요청마다 get_or_create 호출 → DB 조회 1회 발생 (캐시 가능)
        request.user = service_user
        # AuthenticationMiddleware가 채워둔 request.user를 덮어씀
        # ⭐ 이 덮어쓰기 때문에 미들웨어 순서가 중요 (docstring의 주의사항 참조)

        # 4. DRF의 CSRF 검사 건너뛰기 — 내부 API 키 요청은 세션 기반이 아님
        # 이 플래그는 django.views.decorators.csrf.csrf_exempt 와 동일한 효과
        request._dont_enforce_csrf_checks = True
        # ⭐ 비공식 Django 내부 플래그 — 향후 Django 업그레이드 시 깨질 가능성 작지만 존재

        return None
        # None 반환 — 다음 미들웨어로 계속 진행 (response 객체 반환하면 처리 즉시 종료)


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
    # ⭐ 실전에서 배운 교훈을 코드로 박제한 좋은 사례
    #    "Ctrl+Shift+R로 일회성 해결" → "코드로 영구 해결"의 진화 과정이 docstring에 명시됨

    def process_response(self, request, response):
        # 응답 단계 훅 — 응답 헤더만 수정하고 통과시킴
        if not settings.DEBUG:
            return response
            # 운영 환경에서는 아무것도 하지 않음 — Nginx/CDN이 캐시 정책 담당

        path = request.path
        static_url = getattr(settings, 'STATIC_URL', '/static/') or '/static/'
        # 이중 fallback — 설정 누락 시 빈 문자열도 '/static/'으로 처리
        media_url  = getattr(settings, 'MEDIA_URL',  '/media/')  or '/media/'

        if path.startswith(static_url) or path.startswith(media_url):
            # 정적 파일 경로만 영향 — API/페이지 응답에는 영향 없음
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            # no-cache: 매번 서버에 검증 요청
            # no-store: 디스크 캐시 자체 금지
            # must-revalidate: 만료된 캐시 절대 사용 금지
            # max-age=0: 즉시 만료
            response['Pragma'] = 'no-cache'
            # HTTP/1.0 호환 — 구형 프록시 대응
            response['Expires'] = '0'
            # HTTP/1.0 호환 — Date 형식 무시하고 항상 만료
        return response
