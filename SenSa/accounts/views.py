"""
accounts 앱 뷰

- 페이지 뷰: Django Template 기반 로그인/로그아웃/회원가입/내정보 (함수 기반)
- API 뷰: JWT 기반 로그인/로그아웃/회원가입/사용자정보/비밀번호변경 (클래스 기반 Generic)

[변경 이력]
  v1 : 로그인/회원가입/로그아웃/홈/me
  v2 : profile_page (내 정보 페이지) + PasswordChangeAPIView (비밀번호 변경)
"""
import re
# 정규표현식 — 비밀번호 규칙 검증에 사용

from django.contrib.auth import login, logout, update_session_auth_hash
# login: 세션에 사용자 등록 / logout: 세션 제거 / update_session_auth_hash: 비번 변경 후 세션 유지
from django.contrib.auth.decorators import login_required
# 함수 뷰에 적용해 미인증 사용자를 로그인 페이지로 보내는 데코레이터야
from django.contrib import messages
# 1회성 플래시 메시지 (성공/실패 알림) 프레임워크
from django.shortcuts import render, redirect
# render: 템플릿 렌더링 / redirect: 다른 URL로 이동
from django.urls import reverse
# URL 이름(name)으로부터 실제 경로 문자열을 거꾸로 만들어주는 함수야
from django.utils.decorators import method_decorator
# 함수용 데코레이터를 클래스 기반 뷰에 적용할 수 있게 변환해주는 헬퍼
from django.views.decorators.csrf import csrf_exempt
# CSRF 검증을 면제하는 데코레이터 — JWT API에서 사용 (세션 쿠키 비의존)

from rest_framework import status
# HTTP 상태 코드 상수 (status.HTTP_400_BAD_REQUEST 등)
from rest_framework.permissions import AllowAny, IsAuthenticated
# 권한 클래스 — 누구나 접근 / 인증된 사용자만 접근
from rest_framework.response import Response
# DRF용 JSON 응답 클래스
from rest_framework.views import APIView
# DRF 클래스 기반 뷰의 기본 부모
from rest_framework.generics import CreateAPIView, RetrieveAPIView
# CreateAPIView: POST로 객체 생성 / RetrieveAPIView: GET으로 단일 객체 조회 (보일러플레이트 단축용)
from rest_framework_simplejwt.tokens import RefreshToken
# JWT refresh 토큰 객체 — for_user()로 발급, blacklist()로 무효화

from .serializers import LoginSerializer, UserSerializer, SignupSerializer
# 같은 앱의 시리얼라이저 3종을 가져와


# ============================================================
# 페이지 뷰 (Django Template + 세션)
# ============================================================

def root_redirect(request):
    # 루트 경로 진입 시 사용자 상태/역할에 따라 어디로 보낼지 결정하는 분기 뷰야
    if request.user.is_authenticated:
        # 로그인된 사용자라면
        if getattr(request.user, 'is_super_admin_role', False):
            return redirect('backoffice:landing')
            # 슈퍼관리자는 백오피스 랜딩으로 — getattr로 안전하게 속성 체크
        if request.user.role == 'admin':
            return redirect('backoffice:landing')
            # 일반 관리자도 백오피스로 — 메뉴 권한은 백오피스 내부에서 분기
        return redirect('dashboard')
        # 그 외(operator)는 일반 대시보드로
    return redirect('login')
    # 비로그인 사용자는 로그인 페이지로


def login_page(request):
    # 로그인 페이지 — GET이면 폼 렌더, POST면 인증 처리하는 통합 뷰야
    """로그인 페이지 렌더링 + 폼 처리"""
    if request.user.is_authenticated:
        return redirect('home')
        # 이미 로그인된 사용자가 로그인 페이지에 들어오면 홈으로 보내 — 중복 로그인 방지

    error_message = None
    # 템플릿에 전달할 에러 메시지 변수 초기화

    if request.method == 'POST':
        # 폼 제출인 경우 인증 시도
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        serializer = LoginSerializer(data={
            'username': username,
            'password': password,
        })
        # 페이지 뷰지만 검증 로직은 시리얼라이저 재사용 — DRY 원칙

        if serializer.is_valid():
            user = serializer.validated_data['user']
            # 검증 통과한 user 객체 꺼내기

            # ─── 백오피스 — 잠금/비활성 계정 차단 ───
            if not user.is_active:
                error_message = '비활성 계정입니다. 관리자에게 문의해 주세요.'
                return render(request, 'accounts/login.html', {
                    'error_message': error_message,
                    'next'            : request.GET.get('next', ''),
                    'prefill_username': username,
                })
                # is_active=False면 즉시 차단 — 사실 LoginSerializer에서도 검사하지만 이중 방어
            if getattr(user, 'is_locked', False):
                error_message = '잠긴 계정입니다. 관리자에게 문의해 주세요.'
                return render(request, 'accounts/login.html', {
                    'error_message': error_message,
                    'next'            : request.GET.get('next', ''),
                    'prefill_username': username,
                })
                # is_locked=True면 차단 — getattr로 안전 접근 (마이그레이션 미완료 환경 대비)

            login(request, user)
            # 세션에 user 등록 — request.user가 이때부터 user로 채워져
            messages.success(request, f'{user.username}님 환영합니다.')

            # ─── 역할별 진입 분기 ───
            next_url = request.GET.get('next') or request.POST.get('next')
            # next 파라미터 우선 — @login_required가 redirect 시 전달한 원래 가려던 URL
            if not next_url:
                if getattr(user, 'is_super_admin_role', False):
                    next_url = '/backoffice/'
                elif user.role == 'admin':
                    # v5: admin 도 백오피스 진입 가능 — MenuPermission 으로 메뉴 제어
                    next_url = '/backoffice/'
                else:
                    next_url = '/dashboard/'
                    # 운영자는 일반 대시보드로
            if not next_url.startswith('/'):
                next_url = '/home/'
                # next 파라미터가 외부 URL이면 차단 — open redirect 방지의 기초적 방어
            return redirect(next_url)
        else:
            # 검증 실패 시 에러 메시지 추출
            errors = serializer.errors
            if 'non_field_errors' in errors:
                error_message = errors['non_field_errors'][0]
                # validate() 메서드 raise한 에러
            elif errors:
                first_key = list(errors.keys())[0]
                error_message = errors[first_key][0] if errors[first_key] else '입력값을 확인해주세요.'
                # 필드별 에러 중 첫 번째만 표시 (단순 처리)
            else:
                error_message = '입력값을 확인해주세요.'

    return render(request, 'accounts/login.html', {
        'error_message': error_message,
        'next': request.GET.get('next', ''),
        'prefill_username': request.GET.get('username', ''),
        # 회원가입 직후 username을 미리 채워주는 UX 배려
    })


def signup_page(request):
    # 회원가입 페이지 — GET이면 빈 폼, POST면 SignupSerializer로 검증/생성
    """회원가입 페이지 렌더링 + 폼 처리"""
    if request.user.is_authenticated:
        return redirect('home')
        # 이미 로그인된 사용자는 가입할 수 없음 — 홈으로 보내

    error_message = None
    field_errors = {}
    # 필드별 인라인 에러 메시지 (템플릿에서 input 옆에 표시용)
    form_data = {}
    # 검증 실패 시 사용자가 입력했던 값 다시 채워주려는 용도

    if request.method == 'POST':
        form_data = {
            'username': request.POST.get('username', '').strip(),
            'email': request.POST.get('email', '').strip(),
            'department': request.POST.get('department', '').strip(),
            'phone': request.POST.get('phone', '').strip(),
        }

        data = {
            **form_data,
            'password': request.POST.get('password', ''),
            'password_confirm': request.POST.get('password_confirm', ''),
            # 비밀번호는 form_data에 안 넣음 — 실패 시에도 다시 표시하지 않기 위함 (보안)
        }

        serializer = SignupSerializer(data=data)

        if serializer.is_valid():
            user = serializer.save()
            # 검증 통과 → User 생성
            messages.success(
                request,
                f'{user.username}님, 회원가입이 완료되었습니다. 로그인해주세요.'
            )
            return redirect(f"{reverse('login')}?username={user.username}")
            # 로그인 페이지로 username 미리 채워서 리다이렉트
        else:
            for field, errs in serializer.errors.items():
                if field == 'non_field_errors':
                    error_message = errs[0] if errs else '입력값을 확인해주세요.'
                else:
                    if isinstance(errs, list) and errs:
                        field_errors[field] = str(errs[0])
                    else:
                        field_errors[field] = str(errs)
                    # 필드명을 키로 한 dict — 템플릿에서 {{ field_errors.username }} 형태로 사용

    return render(request, 'accounts/signup.html', {
        'error_message': error_message,
        'field_errors': field_errors,
        'form_data': form_data,
    })


@login_required
# 비로그인 사용자는 자동으로 LOGIN_URL로 리다이렉트
def logout_view(request):
    # 세션 로그아웃 처리
    """로그아웃 처리 (세션 삭제 후 로그인 페이지로)"""
    username = request.user.username
    # logout() 호출 후엔 request.user가 AnonymousUser로 바뀌므로 미리 저장
    logout(request)
    messages.info(request, f'{username}님 로그아웃 되었습니다.')
    return redirect('login')


@login_required
def home_page(request):
    """로그인 후 이동하는 임시 홈 페이지"""
    return render(request, 'home.html')
    # 단순 템플릿 렌더 — 컨텍스트 없음


# ═══════════════════════════════════════════════════════════
# ⭐ Phase 2 — 내 정보 페이지
# ═══════════════════════════════════════════════════════════

@login_required(login_url='/accounts/login/')
# login_url 명시 — 프로젝트 LOGIN_URL 설정과 별개로 강제 지정
def profile_page(request):
    # 내 정보 조회 페이지 (편집 X, 비밀번호 변경 모달 진입점)
    return render(request, 'accounts/profile.html', {
        'profile_user': request.user,
        # 템플릿에서 user와 별개의 변수명으로 노출 — context_processor와 충돌 방지
    })


# ============================================================
# API 뷰 (JWT + Generic)
# ============================================================

class SignupAPIView(CreateAPIView):
    # CreateAPIView 상속 — POST 메서드만 자동 제공돼
    """회원가입 API"""
    serializer_class = SignupSerializer
    permission_classes = [AllowAny]
    # 비로그인 상태에서 호출 가능 (당연 — 가입 자체가 비로그인 상태에서 일어남)

    def create(self, request, *args, **kwargs):
        # 부모의 create를 오버라이드해 응답 포맷을 커스터마이즈
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # 실패 시 자동으로 400 응답 — 보일러플레이트 단축
        user = serializer.save()
        return Response({
            'detail': '회원가입이 완료되었습니다.',
            'user': UserSerializer(user).data,
            # 응답에는 SignupSerializer 대신 UserSerializer를 사용 — 비밀번호 등 노출 차단
        }, status=status.HTTP_201_CREATED)


class LoginAPIView(APIView):
    # 일반 APIView 상속 — Generic은 모델 생성 패턴이 아니라서 안 맞아
    """JWT 로그인 API"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)
        # 해당 user에 대한 refresh 토큰 신규 발급 — JTI claim 자동 생성
        return Response({
            'access': str(refresh.access_token),
            # access는 짧은 수명, API 호출 헤더에 실어 보내는 용도
            'refresh': str(refresh),
            # refresh는 긴 수명, access 갱신용으로만 사용 (보안상 안전한 곳에 보관)
            'user': UserSerializer(user).data,
        })


class LogoutAPIView(APIView):
    """JWT 로그아웃 API"""
    permission_classes = [IsAuthenticated]
    # 로그인된 사용자만 로그아웃 호출 가능

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                RefreshToken(refresh_token).blacklist()
                # blacklist 앱이 활성화돼 있어야 동작 — 이후 이 refresh로는 access 재발급 불가
            return Response({'detail': '로그아웃 되었습니다.'})
        except Exception as e:
            return Response(
                {'detail': f'로그아웃 처리 중 오류: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
                # 광범위 예외 catch — 운영 시엔 구체화 권장 (TokenError 등)
            )


class MeAPIView(RetrieveAPIView):
    # RetrieveAPIView — GET 단일 조회 자동 제공
    """현재 로그인한 사용자 정보"""
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user
        # 현재 로그인 사용자를 그대로 반환 — pk 라우팅 불필요


# ═══════════════════════════════════════════════════════════
# ⭐ Phase 2 — 비밀번호 변경 API
# ═══════════════════════════════════════════════════════════

# 비밀번호 규칙 (디자인 시안 Image 3): 8~16자 영문+숫자+특수문자 조합
_PASSWORD_RE = re.compile(
    r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[~!@#$%^&*()_\-+={}\[\]|\\:;"\'<>,.?/])[A-Za-z\d~!@#$%^&*()_\-+={}\[\]|\\:;"\'<>,.?/]{8,16}$'
)
# lookahead로 영문/숫자/특수문자 각 1자 이상 강제, 본문은 8~16자 — 모듈 레벨에서 한 번만 컴파일


def _validate_new_password(pw: str) -> str | None:
    # 신규 비밀번호 검증 헬퍼 — 통과면 None, 실패면 에러 문구 반환
    if not pw:
        return '새로운 비밀번호를 입력해 주세요.'
    if not _PASSWORD_RE.match(pw):
        return '8~16자의 영문, 숫자, 특수문자를 조합하여 입력해 주세요.'
    return None


@method_decorator(csrf_exempt, name='dispatch')
# 클래스의 dispatch 메서드에 csrf_exempt 적용 — JWT 인증 API라 CSRF 토큰 불필요
class PasswordChangeAPIView(APIView):
    """
    비밀번호 변경 API — POST /api/accounts/password-change/

    요청 (JSON):
        {
            "current_password": "현재_비밀번호",
            "new_password":     "새_비밀번호",
            "new_password_confirm": "새_비밀번호"
        }

    응답 (200 성공):
        {"status": "ok", "detail": "비밀번호가 변경되었습니다."}

    응답 (400 실패 — 필드별 에러):
        {
            "status": "error",
            "errors": {
                "current_password": "현재 비밀번호가 일치하지 않습니다. 다시 확인해 주세요.",
                "new_password": "...",
                "new_password_confirm": "..."
            }
        }

    [보안]
      - current_password 검증 필수 (본인 재인증)
      - 변경 성공 시 update_session_auth_hash 로 세션 유지 (재로그인 불필요)
    """
    permission_classes = [IsAuthenticated]
    # 본인만 자기 비밀번호 변경 가능

    def post(self, request):
        user = request.user
        current_pw = request.data.get('current_password', '')
        new_pw = request.data.get('new_password', '')
        new_pw_confirm = request.data.get('new_password_confirm', '')

        errors: dict[str, str] = {}
        # 필드별 에러 누적 dict — 한 번에 모든 에러를 응답해 UX 향상

        # 1) 현재 비밀번호 확인
        if not current_pw:
            errors['current_password'] = '현재 사용 중인 비밀번호를 입력해 주세요.'
        elif not user.check_password(current_pw):
            errors['current_password'] = '현재 비밀번호가 일치하지 않습니다. 다시 확인해 주세요.'
            # check_password는 해시 비교 — 평문 비교 절대 금지

        # 2) 신규 비밀번호 규칙
        new_pw_err = _validate_new_password(new_pw)
        if new_pw_err:
            errors['new_password'] = new_pw_err
        elif current_pw and new_pw == current_pw:
            errors['new_password'] = '현재 사용 중인 비밀번호는 신규 비밀번호로 사용할 수 없습니다.'
            # 동일 비밀번호 재사용 차단 — 보안 정책

        # 3) 확인 필드 일치
        if not new_pw_confirm:
            errors['new_password_confirm'] = '비밀번호 확인을 위해 한 번 더 입력해 주세요.'
        elif new_pw and new_pw != new_pw_confirm:
            errors['new_password_confirm'] = '입력하신 신규 비밀번호와 일치하지 않습니다.'

        if errors:
            return Response(
                {'status': 'error', 'errors': errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4) 저장 + 세션 유지
        user.set_password(new_pw)
        # 새 비밀번호 해시화
        user.save(update_fields=['password'])
        # password 필드만 UPDATE — 다른 필드 race condition 방지 + 효율
        update_session_auth_hash(request, user)
        # 비번 변경 후 세션 재해시 — 안 하면 현재 세션이 무효화돼 자동 로그아웃됨

        return Response({
            'status': 'ok',
            'detail': '비밀번호가 변경되었습니다.',
        })