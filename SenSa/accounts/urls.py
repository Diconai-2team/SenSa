from django.urls import path
# Django에서 URL 경로를 정의하는 path 함수를 불러와
from rest_framework_simplejwt.views import TokenRefreshView
# JWT 액세스 토큰을 갱신하는 SimpleJWT 내장 뷰를 불러와 (refresh 토큰으로 새 access 발급)
from . import views
# 같은 앱(accounts) 안의 views 모듈을 불러와


urlpatterns = [
    # === 루트 및 홈 ===
    path('', views.root_redirect, name='root'),
    # 루트 경로('/')로 접근하면 root_redirect 함수가 실행돼 — 로그인/역할별로 분기 리다이렉트할게
    path('home/', views.home_page, name='home'),
    # 'home/' 경로로 접근하면 로그인 후 임시 홈 페이지를 보여줄게 (로그인 필수)

    # === 페이지 ===
    path('accounts/login/', views.login_page, name='login'),
    # 'accounts/login/' 경로로 GET/POST 모두 받아 — 로그인 폼 렌더링과 폼 처리를 같이 담당해
    path('accounts/signup/', views.signup_page, name='signup'),
    # 'accounts/signup/' 경로 — 회원가입 폼 렌더링과 가입 처리를 함께 담당해
    path('accounts/logout/', views.logout_view, name='logout'),
    # 'accounts/logout/' 경로 — 세션 로그아웃 후 로그인 페이지로 리다이렉트할게
    path('accounts/profile/', views.profile_page, name='profile'),        # ⭐ Phase 2
    # 'accounts/profile/' 경로 — 내 정보 페이지 (Phase 2에서 추가, 비밀번호 변경 진입점 포함)

    # === API ===
    path('api/accounts/login/', views.LoginAPIView.as_view(), name='api-login'),
    # 'api/accounts/login/' 경로로 POST하면 JWT access/refresh 토큰을 발급해줄게
    path('api/accounts/signup/', views.SignupAPIView.as_view(), name='api-signup'),
    # 'api/accounts/signup/' 경로로 POST하면 회원가입 API가 실행돼 (CreateAPIView 기반)
    path('api/accounts/logout/', views.LogoutAPIView.as_view(), name='api-logout'),
    # 'api/accounts/logout/' 경로 — refresh 토큰을 블랙리스트 처리해서 로그아웃시킬게
    path('api/accounts/me/', views.MeAPIView.as_view(), name='api-me'),
    # 'api/accounts/me/' 경로로 GET하면 현재 로그인 사용자의 정보를 반환해줄게
    path('api/accounts/password-change/',                                 # ⭐ Phase 2
         views.PasswordChangeAPIView.as_view(),
         name='api-password-change'),
    # 'api/accounts/password-change/' 경로 — 비밀번호 변경 API (Phase 2 신규)
    path('api/accounts/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    # 'api/accounts/token/refresh/' 경로로 refresh 토큰 보내면 새 access 토큰을 발급해줄게
]