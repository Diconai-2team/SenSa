"""
fastapi_ai/main.py — SenSa AI 추론 서버.

Phase E-1: 기본 서버 구조 + 헬스체크.
Phase E-2 에서 TTM 추론 엔드포인트 추가 예정.

[기동]
    cd fastapi_ai
    bash run.sh
    → http://localhost:8002 에서 응답

[설계 원칙]
- 모델은 startup 시 1회 로드, 추론 시 재사용 (Phase E-2)
- SenSa Django 와는 HTTP API 로만 통신 (느슨한 결합)
- 응답 스키마는 Pydantic 으로 명시 (E-2 에서 활용)
"""
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI

from schemas import HealthResponse, RootResponse


# 서비스 메타 정보
SERVICE_NAME = "SenSa AI Server"
SERVICE_VERSION = "0.1.0"

# 서버 상태 (E-2 에서 모델 로딩 상태 등 추가)
_state = {
    "started_at": None,
    "model_loaded": False,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 기동/종료 시 실행되는 라이프사이클 훅.

    Phase E-2 에서 여기서 TTM 모델 로딩 예정.
    """
    _state["started_at"] = datetime.utcnow()
    print(f"[{SERVICE_NAME}] 기동 완료 (v{SERVICE_VERSION})")
    yield
    print(f"[{SERVICE_NAME}] 종료")


app = FastAPI(
    title=SERVICE_NAME,
    description="TTM zero-shot 기반 시계열 이상 탐지 추론 API",
    version=SERVICE_VERSION,
    lifespan=lifespan,
)


@app.get("/", response_model=RootResponse)
async def root():
    """서비스 정보."""
    return RootResponse(
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        status="running",
        started_at=_state["started_at"],
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """헬스체크 — Django 측에서 서버 가용성 확인 시 호출."""
    return HealthResponse(
        status="ok",
        model_loaded=_state["model_loaded"],
        uptime_sec=(
            (datetime.utcnow() - _state["started_at"]).total_seconds()
            if _state["started_at"] else 0.0
        ),
    )
