"""
fastapi_ai/schemas.py — API 요청/응답 스키마.

Phase E-1: 기본 응답 (RootResponse, HealthResponse).
Phase E-2 에서 PredictRequest, PredictResponse 등 추가 예정.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RootResponse(BaseModel):
    """루트 응답 — 서비스 메타 정보."""
    service: str
    version: str
    status: str
    started_at: Optional[datetime] = None


class HealthResponse(BaseModel):
    """헬스체크 응답."""
    status: str = Field(description="'ok' | 'degraded' | 'error'")
    model_loaded: bool = Field(description="TTM 모델 로딩 완료 여부 (E-2)")
    uptime_sec: float = Field(description="기동 후 경과 시간 (초)")
