import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# ==========================================================
# 기본 경로
# ==========================================================
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / '.env')

# ==========================================================
# 시크릿 / 디버그
# ==========================================================
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-only')
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# ==========================================================
# 앱
# ==========================================================
INSTALLED_APPS = [
    # ── daphne는 반드시 최상단 ──
    # runserver가 자동으로 ASGI/Daphne 모드로 뜨려면
    # django.contrib.staticfiles 보다 먼저 와야 함
    'daphne', # ← 추가[0421.1]

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 서드파티
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'channels', # ← 추가[0421.1]

    # 로컬
    'realtime',          # ← 추가 (다른 로컬 앱보다 먼저, 4차에서도 배관 역할 유지)
    'accounts',
    'devices',
    'geofence',
    'alerts',
    'workers',
    'dashboard',
]

# ==========================================================
# 미들웨어
# ==========================================================
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'mysite.middleware.InternalAPIKeyMiddleware',    # ← 추가 (Auth 뒤)
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'mysite.urls'
WSGI_APPLICATION = 'mysite.wsgi.application'
ASGI_APPLICATION = 'mysite.asgi.application'   # ← 추가[0421.1]

# ==========================================================
# 템플릿
# ==========================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ==========================================================
# 데이터베이스 — SQLite
# ==========================================================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ==========================================================
# 커스텀 User 모델
# ==========================================================
AUTH_USER_MODEL = 'accounts.User'

# ==========================================================
# 비밀번호 검증
# ==========================================================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==========================================================
# 로그인 관련 URL
# ==========================================================
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ==========================================================
# DRF
# ==========================================================
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
}

# ==========================================================
# JWT
# ==========================================================
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ==========================================================
# CORS (개발용)
# ==========================================================
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# ==========================================================
# 국제화
# ==========================================================
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# ==========================================================
# 정적 파일
# ==========================================================
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


# ==========================================================
# Channels — WebSocket용 Channel Layer (Redis 백엔드) 추가[0421.1]
# 4차에서 Celery broker, 캐시로 확장 예정
# ==========================================================
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [(REDIS_HOST, REDIS_PORT)],
        },
    },
}

# ==========================================================
# 내부 서비스 간 인증 (FastAPI 데이터 생성기용)
# Phase E에서 추가. FastAPI가 /dashboard/api/* 의 일부 경로를
# 내부 API 키로 인증하여 호출할 수 있게 함.
# ==========================================================
INTERNAL_API_KEY = os.getenv('INTERNAL_API_KEY', '')

# 내부 키로 인증 가능한 경로 프리픽스 (세션 인증 우회 허용)
INTERNAL_API_ALLOWED_PATHS = [
    '/dashboard/api/sensor-data/',
    '/dashboard/api/worker-location/',
    '/dashboard/api/check-geofence/',
    '/dashboard/api/device/',       # ← 추가: FastAPI 기동 시 장비 목록 GET
    '/dashboard/api/worker/',       # ← 추가: 작업자 목록 GET + /worker/<pk>/latest/
    '/dashboard/api/geofence/',     # ← 추가: (현재 scheduler 에서 호출 안 하지만 django_loader 에 load_geofences 있음)
]

ALARM_RE_ALARM_INTERVAL_SEC = 60   # 상태 지속 시 재알림 주기
ALARM_RECOVERY_CONFIRM_TICKS = 3   # 회복 전이에 필요한 연속 관측 횟수 (3 = 약 3초)