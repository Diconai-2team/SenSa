from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    # 루트 및 홈
    path('', views.root_redirect, name='root'),
    path('home/', views.home_page, name='home'),

    # 페이지
    path('accounts/login/', views.login_page, name='login'),
    path('accounts/signup/', views.signup_page, name='signup'),
    path('accounts/logout/', views.logout_view, name='logout'),
    path('accounts/profile/', views.profile_page, name='profile'),        # ⭐ Phase 2

    # API
    path('api/accounts/login/', views.LoginAPIView.as_view(), name='api-login'),
    path('api/accounts/signup/', views.SignupAPIView.as_view(), name='api-signup'),
    path('api/accounts/logout/', views.LogoutAPIView.as_view(), name='api-logout'),
    path('api/accounts/me/', views.MeAPIView.as_view(), name='api-me'),
    path('api/accounts/password-change/',                                 # ⭐ Phase 2
         views.PasswordChangeAPIView.as_view(),
         name='api-password-change'),
    path('api/accounts/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]