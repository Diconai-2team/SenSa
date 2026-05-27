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
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,host.docker.internal').split(',')

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
    'django_prometheus',   # [Phase 4 P4-A] Prometheus metrics

    # 로컬
    'realtime',          # ← 추가 (다른 로컬 앱보다 먼저, 4차에서도 배관 역할 유지)
    'accounts',
    'devices',
    'geofence',
    'alerts',
    'workers',
    'dashboard',
    'safety',
    'vr_training',     # ← 추가
    'backoffice',      # ← 백오피스 (슈퍼관리자 채널)
    'ml_engine',       # ← AI 이상 탐지 파이프라인
]

# ==========================================================
# 미들웨어
# ==========================================================
MIDDLEWARE = [
    # [Phase 4 P4-A] PrometheusBeforeMiddleware — 가장 먼저 (요청 측정 시작)
    'django_prometheus.middleware.PrometheusBeforeMiddleware',

    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'mysite.middleware.InternalAPIKeyMiddleware',    # ← 추가 (Auth 뒤)
    'backoffice.middleware.AuditContextMiddleware',  # v6 — 시그널이 request user/IP 를 알 수 있게
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'mysite.middleware.DevStaticNoCacheMiddleware',   # ⭐ Step 1A 후속 — DEBUG 시 정적 파일 캐시 무효화

    # [Phase 4 P4-A] PrometheusAfterMiddleware — 가장 마지막 (응답 측정 완료)
    'django_prometheus.middleware.PrometheusAfterMiddleware',
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
                'backoffice.context_processors.menu_perms',
            ],
        },
    },
]

# ==========================================================
# 데이터베이스 — PostgreSQL (Docker 컨테이너)
# [운영 전환 시] DB_PASSWORD 를 강력한 비밀번호로 교체
# ==========================================================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'sensa'),
        'USER': os.getenv('DB_USER', 'sensa'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'sensa'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
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
    '/dashboard/api/thresholds/',   # ← 추가: 임계치 DB → FastAPI 동기화
]

ALARM_RE_ALARM_INTERVAL_SEC = 60   # 상태 지속 시 재알림 주기 [운영 전환 시] → 300
ALARM_RECOVERY_CONFIRM_TICKS = 3   # 회복 전이에 필요한 연속 관측 횟수 [운영 전환 시] 값 유지 (3틱 = dev 9초 → 운영 3분, 의미 동일)# ─────────────────────────────────────────────
# Celery / Redis (Phase G)
# ─────────────────────────────────────────────
# 이 블록을 mysite/settings.py 의 가장 아래에 추가하세요.
# TIME_ZONE 변수는 이미 settings.py 위에 정의되어 있을 것입니다.

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 5 * 60       # 5분 (TTM 추론 여유)
CELERY_TASK_SOFT_TIME_LIMIT = 4 * 60

# ─────────────────────────────────────────────
# Django 캐시 (Phase 3 — Redis DB 2)
# ─────────────────────────────────────────────
# 최신 상태 캐시 키 (sensor:latest:*, worker:latest:*) 저장용.
# Celery (DB 0) 과 분리해서 캐시 flush 가 task 큐에 영향 안 줌.
#
# 활용: realtime/cache.py 의 set_latest_sensor, get_latest_sensor 등
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': f'redis://{REDIS_HOST}:{REDIS_PORT}/2',
        'TIMEOUT': 300,   # 5분 — 센서 데이터 stale 방지
        'KEY_PREFIX': 'sensa',
    },
}

# ── Beat 스케줄 ──
# 30초마다 동적 zone 의 반경 갱신 + 만료 + 승격 검사
CELERY_BEAT_SCHEDULE = {
    'tick-dynamic-zones': {
        'task': 'geofence.tasks.tick_zones',
        'schedule': 30.0,
    },
    # ─── 5차 세션 C′-3b-1: Phase L (TTM 사전 경고) 항목 제거 ──────────
    # 'scan-forecast-warnings' 항목은 TTM 폐기에 따라 삭제됨.
    # Isolation Forest 기반 IF 분석기 (C′-3b-2) 는 Celery 가 아닌
    # SensorDataView.post 안에서 실시간 호출됨 → beat 스케줄 불필요.

    # ─── 데이터 보관 정책 (DataRetentionPolicy) ───────────────────────
    # 매일 새벽 3시 실행 — sensor_data/worker_location 30일, alarms 365일
    # [운영 전환 시] 값 유지 (정책은 DB의 DataRetentionPolicy 에서 관리)
    'cleanup-retention-data': {
        'task': 'backoffice.tasks.run_cleanup',
        'schedule': 86400.0,   # 24시간
    },

    # ─── ARIMA AIPrediction 만료 pending 정리 ─────────────────────────
    # 5분마다 실행 — expires_at 지난 pending → failure 전환
    # 배경: spike 태스크가 REST API 우회로 DB 직접 저장 시
    #       _verify_ai_predictions() 미호출 → pending 방치 문제 해결
    # [운영 전환 시] 값 유지 (5분 주기는 expires_at TTL=30초 대비 충분)
    'cleanup-expired-ai-predictions': {
        'task': 'backoffice.tasks.cleanup_expired_ai_predictions',
        'schedule': 300.0,   # 5분
    },
}
