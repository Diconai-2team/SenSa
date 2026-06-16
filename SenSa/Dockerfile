# ============================================================
# SenSa Django/Celery 이미지 (C-1, slim)
#   - base: python:3.12-slim (venv 가 3.12, Django 4.2.29 호환)
#   - 의존성: requirements.docker.txt (C-1a 생성, 무거운 ML/GPU 제거)
#   - 배치 경로: ~/SenSa/SenSa/Dockerfile (Django 앱 디렉터리)
# ============================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ── (선택) 빌드 실패 시에만 주석 해제 ──
# 휠(wheel)로 설치되는 게 정상이라 평소엔 불필요. 특정 패키지가 sdist 빌드를
# 요구해 'gcc/Python.h not found' 류로 실패하면 아래 블록을 켜고 재빌드.
# RUN apt-get update && apt-get install -y --no-install-recommends \
#         build-essential python3-dev \
#     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 (레이어 캐시)
COPY requirements.docker.txt /app/requirements.docker.txt
RUN pip install -r requirements.docker.txt

# 앱 코드 (.dockerignore 로 .venv/db/bak/zip 제외)
COPY . /app

# [P-DAPHNE] 정적 파일 수집 — daphne 단독 구동의 전제.
#   urls.py 의 static 헬퍼가 STATIC_ROOT(staticfiles/)를 서빙하므로,
#   빌드 시 collectstatic 으로 채워 둔다 (과거 daphne 화면 깨짐의 근본 원인 = 이 단계 부재).
RUN python manage.py collectstatic --noinput

EXPOSE 8000 9809

# 기본 명령: daphne ASGI 단독 구동 (collectstatic 으로 정적 파일 문제 해소됨).
# Celery 서비스는 compose/K8s 의 command 로 override.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "mysite.asgi:application"]
