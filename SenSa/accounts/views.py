"""
accounts 앱 뷰

- 페이지 뷰: Django Template 기반 로그인/로그아웃/회원가입/내정보 (함수 기반)
- API 뷰: JWT 기반 로그인/로그아웃/회원가입/사용자정보/비밀번호변경 (클래스 기반 Generic)

[변경 이력]
  v1 : 로그인/회원가입/로그아웃/홈/me
  v2 : profile_page (내 정보 페이지) + PasswordChangeAPIView (비밀번호 변경)
"""

import re

from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

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
        if getattr(request.user, "is_super_admin_role", False):
            return redirect("backoffice:landing")
        if request.user.role == "admin":
            return redirect("backoffice:landing")
        return redirect("dashboard")
    return redirect("login")


def login_page(request):
    """로그인 페이지 렌더링 + 폼 처리"""
    if request.user.is_authenticated:
        return redirect("home")

    error_message = None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        serializer = LoginSerializer(
            data={
                "username": username,
                "password": password,
            }
        )

        if serializer.is_valid():
            user = serializer.validated_data["user"]

            # ─── 백오피스 — 잠금/비활성 계정 차단 ───
            if not user.is_active:
                error_message = "비활성 계정입니다. 관리자에게 문의해 주세요."
                return render(
                    request,
                    "accounts/login.html",
                    {
                        "error_message": error_message,
                        "next": request.GET.get("next", ""),
                        "prefill_username": username,
                    },
                )
            if getattr(user, "is_locked", False):
                error_message = "잠긴 계정입니다. 관리자에게 문의해 주세요."
                return render(
                    request,
                    "accounts/login.html",
                    {
                        "error_message": error_message,
                        "next": request.GET.get("next", ""),
                        "prefill_username": username,
                    },
                )

            login(request, user)
            messages.success(request, f"{user.username}님 환영합니다.")

            # ─── 역할별 진입 분기 ───
            # 슈퍼관리자는 백오피스로, 그 외는 기존 대시보드로.
            # next 파라미터가 명시되어 있으면 우선 적용 (외부 deep link 호환).
            next_url = request.GET.get("next") or request.POST.get("next")
            if not next_url:
                if getattr(user, "is_super_admin_role", False):
                    next_url = "/backoffice/"
                elif user.role == "admin":
                    # v5: admin 도 백오피스 진입 가능 — MenuPermission 으로 메뉴 제어
                    next_url = "/backoffice/"
                else:
                    next_url = "/dashboard/"
            if not next_url.startswith("/"):
                next_url = "/home/"
            return redirect(next_url)
        else:
            errors = serializer.errors
            if "non_field_errors" in errors:
                error_message = errors["non_field_errors"][0]
            elif errors:
                first_key = list(errors.keys())[0]
                error_message = (
                    errors[first_key][0]
                    if errors[first_key]
                    else "입력값을 확인해주세요."
                )
            else:
                error_message = "입력값을 확인해주세요."

    return render(
        request,
        "accounts/login.html",
        {
            "error_message": error_message,
            "next": request.GET.get("next", ""),
            "prefill_username": request.GET.get("username", ""),
        },
    )


def signup_page(request):
    """회원가입 페이지 렌더링 + 폼 처리"""
    if request.user.is_authenticated:
        return redirect("home")

    error_message = None
    field_errors = {}
    form_data = {}

    if request.method == "POST":
        form_data = {
            "username": request.POST.get("username", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "department": request.POST.get("department", "").strip(),
            "phone": request.POST.get("phone", "").strip(),
        }

        data = {
            **form_data,
            "password": request.POST.get("password", ""),
            "password_confirm": request.POST.get("password_confirm", ""),
        }

        serializer = SignupSerializer(data=data)

        if serializer.is_valid():
            user = serializer.save()
            messages.success(
                request,
                f"{user.username}님, 회원가입이 완료되었습니다. 로그인해주세요.",
            )
            return redirect(f"{reverse('login')}?username={user.username}")
        else:
            for field, errs in serializer.errors.items():
                if field == "non_field_errors":
                    error_message = errs[0] if errs else "입력값을 확인해주세요."
                else:
                    if isinstance(errs, list) and errs:
                        field_errors[field] = str(errs[0])
                    else:
                        field_errors[field] = str(errs)

    return render(
        request,
        "accounts/signup.html",
        {
            "error_message": error_message,
            "field_errors": field_errors,
            "form_data": form_data,
        },
    )


@login_required
def logout_view(request):
    """로그아웃 처리 (세션 삭제 후 로그인 페이지로)"""
    username = request.user.username
    logout(request)
    messages.info(request, f"{username}님 로그아웃 되었습니다.")
    return redirect("login")


@login_required
def home_page(request):
    """로그인 후 이동하는 임시 홈 페이지"""
    return render(request, "home.html")


# ═══════════════════════════════════════════════════════════
# ⭐ Phase 2 — 내 정보 페이지
# ═══════════════════════════════════════════════════════════


@login_required(login_url="/accounts/login/")
def profile_page(request):
    """
    내 정보 페이지.

    디자인 시안 기준으로 조회 전용 + 비밀번호 변경 모달 진입점 포함.
    편집 기능은 이번 범위 제외.
    """
    return render(
        request,
        "accounts/profile.html",
        {
            "profile_user": request.user,
        },
    )


# ============================================================
# API 뷰 (JWT + Generic)
# ============================================================


class SignupAPIView(CreateAPIView):
    """회원가입 API"""

    serializer_class = SignupSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "detail": "회원가입이 완료되었습니다.",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginAPIView(APIView):
    """JWT 로그인 API"""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )


class LogoutAPIView(APIView):
    """JWT 로그아웃 API"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                RefreshToken(refresh_token).blacklist()
            return Response({"detail": "로그아웃 되었습니다."})
        except Exception as e:
            return Response(
                {"detail": f"로그아웃 처리 중 오류: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class MeAPIView(RetrieveAPIView):
    """현재 로그인한 사용자 정보"""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


# ═══════════════════════════════════════════════════════════
# ⭐ Phase 2 — 비밀번호 변경 API
# ═══════════════════════════════════════════════════════════

# 비밀번호 규칙 (디자인 시안 Image 3): 8~16자 영문+숫자+특수문자 조합
_PASSWORD_RE = re.compile(
    r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[~!@#$%^&*()_\-+={}\[\]|\\:;"\'<>,.?/])[A-Za-z\d~!@#$%^&*()_\-+={}\[\]|\\:;"\'<>,.?/]{8,16}$'
)


def _validate_new_password(pw: str) -> str | None:
    """
    신규 비밀번호 규칙 검증.
    통과하면 None, 실패하면 에러 메시지 문자열 반환.
    """
    if not pw:
        return "새로운 비밀번호를 입력해 주세요."
    if not _PASSWORD_RE.match(pw):
        return "8~16자의 영문, 숫자, 특수문자를 조합하여 입력해 주세요."
    return None


@method_decorator(csrf_exempt, name="dispatch")
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

    def post(self, request):
        user = request.user
        current_pw = request.data.get("current_password", "")
        new_pw = request.data.get("new_password", "")
        new_pw_confirm = request.data.get("new_password_confirm", "")

        errors: dict[str, str] = {}

        # 1) 현재 비밀번호 확인
        if not current_pw:
            errors["current_password"] = "현재 사용 중인 비밀번호를 입력해 주세요."
        elif not user.check_password(current_pw):
            errors["current_password"] = (
                "현재 비밀번호가 일치하지 않습니다. 다시 확인해 주세요."
            )

        # 2) 신규 비밀번호 규칙
        new_pw_err = _validate_new_password(new_pw)
        if new_pw_err:
            errors["new_password"] = new_pw_err
        elif current_pw and new_pw == current_pw:
            errors["new_password"] = (
                "현재 사용 중인 비밀번호는 신규 비밀번호로 사용할 수 없습니다."
            )

        # 3) 확인 필드 일치
        if not new_pw_confirm:
            errors["new_password_confirm"] = (
                "비밀번호 확인을 위해 한 번 더 입력해 주세요."
            )
        elif new_pw and new_pw != new_pw_confirm:
            errors["new_password_confirm"] = (
                "입력하신 신규 비밀번호와 일치하지 않습니다."
            )

        if errors:
            return Response(
                {"status": "error", "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4) 저장 + 세션 유지
        user.set_password(new_pw)
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)

        return Response(
            {
                "status": "ok",
                "detail": "비밀번호가 변경되었습니다.",
            }
        )
