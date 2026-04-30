"""
config.py — 환경 변수 로드 + 상수

.env 파일을 읽어 런타임 설정을 제공한다.
다른 모듈은 여기서만 환경 변수를 읽어야 한다 (Single Source of Truth).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# fastapi_generator/.env 로드
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ═══════════════════════════════════════════════════════════
# Django 연결
# ═══════════════════════════════════════════════════════════
DJANGO_BASE_URL = os.getenv("DJANGO_BASE_URL", "http://127.0.0.1:8000")

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
if not INTERNAL_API_KEY:
    raise RuntimeError(
        "INTERNAL_API_KEY is not set. "
        "Set it in fastapi_generator/.env and make sure the same value "
        "is configured in Django's .env"
    )

# 모든 내부 POST 요청에 붙일 헤더
INTERNAL_HEADERS = {
    "X-Internal-API-Key": INTERNAL_API_KEY,
    "Content-Type": "application/json",
}


# ═══════════════════════════════════════════════════════════
# 시뮬레이션 파라미터
# ═══════════════════════════════════════════════════════════
TICK_INTERVAL = float(os.getenv("TICK_INTERVAL", "1.0"))
DEFAULT_SCENARIO = os.getenv("DEFAULT_SCENARIO", "mixed")

VALID_SCENARIOS = ("normal", "mixed", "danger")
