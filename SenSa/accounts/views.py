"""
accounts 앱 뷰

- 페이지 뷰: Django Template 기반 로그인/로그아웃/회원가입 (함수 기반)
- API 뷰: JWT 기반 로그인/로그아웃/회원가입/사용자정보 (클래스 기반 Generic)
"""
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView, RetrieveAPIView
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import LoginSerializer, UserSerializer, SignupSerializer


# ============================================================
# 페이지 뷰 (Django Template + 세션)
# ============================================================

def root_redirect(request):
    if request.user.is_authenticated:
        return redirect('dashboard')    # 'home' → 'dashboard'
    return redirect('login')


def login_page(request):
    """
    로그인 페이지 렌더링 + 폼 처리

    GET  /accounts/login/         → 로그인 폼 표시
    POST /accounts/login/         → 로그인 시도
    """
    if request.user.is_authenticated:
        return redirect('home')

    error_message = None

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        serializer = LoginSerializer(data={
            'username': username,
            'password': password,
        })

        if serializer.is_valid():
            user = serializer.validated_data['user']
            login(request, user)
            messages.success(request, f'{user.username}님 환영합니다.')

            next_url = request.GET.get('next') or request.POST.get('next') or '/dashboard/'
            if not next_url.startswith('/'):
                next_url = '/home/'
            return redirect(next_url)
        else:
            errors = serializer.errors
            if 'non_field_errors' in errors:
                error_message = errors['non_field_errors'][0]
            elif errors:
                first_key = list(errors.keys())[0]
                error_message = errors[first_key][0] if errors[first_key] else '입력값을 확인해주세요.'
            else:
                error_message = '입력값을 확인해주세요.'

    return render(request, 'accounts/login.html', {
        'error_message': error_message,
        'next': request.GET.get('next', ''),
        'prefill_username': request.GET.get('username', ''),
    })


def signup_page(request):
    """
    회원가입 페이지 렌더링 + 폼 처리

    GET  /accounts/signup/    → 가입 폼 표시
    POST /accounts/signup/    → 가입 시도
    """
    if request.user.is_authenticated:
        return redirect('home')

    error_message = None
    field_errors = {}
    form_data = {}

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
        }

        serializer = SignupSerializer(data=data)

        if serializer.is_valid():
            user = serializer.save()
            messages.success(
                request,
                f'{user.username}님, 회원가입이 완료되었습니다. 로그인해주세요.'
            )
            # 방금 가입한 아이디를 쿼리 파라미터로 넘겨서 로그인 폼에 미리 채움
            return redirect(f"{reverse('login')}?username={user.username}")
        else:
            for field, errs in serializer.errors.items():
                if field == 'non_field_errors':
                    error_message = errs[0] if errs else '입력값을 확인해주세요.'
                else:
                    if isinstance(errs, list) and errs:
                        field_errors[field] = str(errs[0])
                    else:
                        field_errors[field] = str(errs)

    return render(request, 'accounts/signup.html', {
        'error_message': error_message,
        'field_errors': field_errors,
        'form_data': form_data,
    })


@login_required
def logout_view(request):
    """로그아웃 처리 (세션 삭제 후 로그인 페이지로)"""
    username = request.user.username
    logout(request)
    messages.info(request, f'{username}님 로그아웃 되었습니다.')
    return redirect('login')


@login_required
def home_page(request):
    """로그인 후 이동하는 임시 홈 페이지"""
    return render(request, 'home.html')


# ============================================================
# API 뷰 (JWT + Generic)
# ============================================================

class SignupAPIView(CreateAPIView):
    """
    회원가입 API — POST /api/accounts/signup/

    요청:
        {
            "username": "newuser",
            "password": "strongpass123",
            "password_confirm": "strongpass123",
            "email": "new@example.com",
            "department": "현장팀",
            "phone": ""
        }
    성공 (201):
        {
            "detail": "회원가입이 완료되었습니다.",
            "user": {...}
        }
    """
    serializer_class = SignupSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'detail': '회원가입이 완료되었습니다.',
            'user': UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class LoginAPIView(APIView):
    """
    JWT 로그인 API — POST /api/accounts/login/

    요청: {"username": "admin", "password": "admin1234"}
    성공 (200):
        {
            "access": "eyJ...",
            "refresh": "eyJ...",
            "user": {...}
        }
    실패 (400): serializer 에러 반환
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        })


class LogoutAPIView(APIView):
    """
    JWT 로그아웃 API — POST /api/accounts/logout/
    refresh 토큰을 블랙리스트에 등록하여 재사용 방지.

    요청: {"refresh": "<refresh_token>"}
    응답: {"detail": "로그아웃 되었습니다."}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                RefreshToken(refresh_token).blacklist()
            return Response({'detail': '로그아웃 되었습니다.'})
        except Exception as e:
            return Response(
                {'detail': f'로그아웃 처리 중 오류: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class MeAPIView(RetrieveAPIView):
    """
    현재 로그인한 사용자 정보 — GET /api/accounts/me/

    헤더: Authorization: Bearer <access>
    응답: UserSerializer 형태
    """
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user