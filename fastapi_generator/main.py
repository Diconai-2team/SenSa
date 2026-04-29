"""
main.py — FastAPI 애플리케이션 진입점

역할:
  - 기동 시 scheduler.run_simulation_loop 를 백그라운드로 띄움
  - 시나리오 조회/전환 HTTP 엔드포인트 제공
  - 헬스체크용 GET /

설계 원칙:
  - FastAPI 에 WebSocket 엔드포인트 없음 (WS 는 Django Channels 전담)
  - FastAPI 는 판정하지 않음 — 시뮬 루프만 돌림
  - lifespan 컨텍스트로 백그라운드 태스크 수명 관리
  - 상태는 app.state 에 둠 (전역 변수 금지)

[E7 추가 — CORS 설정]
  브라우저 base.js 의 setScenario() 가 Django(:8000) 에서 FastAPI(:8001) 로
  cross-origin POST 함. CORS 허용 안 해두면 브라우저가 요청 자체를 차단.
  개발 환경(localhost/127.0.0.1) 에서만 동작하도록 origin 제한.

기동:
  cd ~/SenSa/fastapi_generator
  source .venv/bin/activate
  uvicorn main:app --host 127.0.0.1 --port 8001
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import DEFAULT_SCENARIO, VALID_SCENARIOS, TICK_INTERVAL
from scheduler import run_simulation_loop


# ═══════════════════════════════════════════════════════════
# Lifespan — 기동/종료 시점 훅
# ═══════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱 수명 주기 관리.

    startup:
      - app.state.scenario 초기화
      - scheduler.run_simulation_loop 를 별도 태스크로 기동
    shutdown:
      - scheduler 태스크 취소 (CancelledError 전파)
      - 취소 완료까지 대기
    """
    # startup
    app.state.scenario = DEFAULT_SCENARIO
    app.state.sim_task = asyncio.create_task(
        run_simulation_loop(app.state),
        name="sim_loop",
    )
    print(
        f"[main] FastAPI 기동 완료 (scenario={app.state.scenario}, tick={TICK_INTERVAL}s)"
    )

    try:
        yield
    finally:
        # shutdown
        print("[main] 종료 중 — scheduler 태스크 취소")
        app.state.sim_task.cancel()
        try:
            await app.state.sim_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[main] scheduler 종료 중 예외: {e!r}")
        print("[main] 종료 완료")


# ═══════════════════════════════════════════════════════════
# 앱 인스턴스
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="SenSa Simulation Generator",
    description="1초 주기로 센서/작업자 데이터를 생성해 Django 로 POST",
    version="0.7.0",  # Phase E7
    lifespan=lifespan,
)


# ═══════════════════════════════════════════════════════════
# CORS 미들웨어 (E7)
# ═══════════════════════════════════════════════════════════
#
# Django 대시보드(:8000) → FastAPI(:8001) 로의 cross-origin 요청 허용.
# base.js 의 setScenario() 가 fetch('http://.../8001/api/scenario?mode=...') 호출 시
# 브라우저가 CORS preflight 를 보내고, 여기서 허용하지 않으면 실제 POST 는
# 나가지도 못함.
#
# 허용 origin 은 개발 환경만 명시 — 운영 배포 시 실제 Django 호스트/포트로 교체.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)


# ═══════════════════════════════════════════════════════════
# HTTP 엔드포인트
# ═══════════════════════════════════════════════════════════


@app.get("/")
async def root():
    """헬스체크 — 기동 여부 + 현재 시나리오 조회."""
    return {
        "status": "running",
        "scenario": app.state.scenario,
        "tick_interval": TICK_INTERVAL,
        "valid_scenarios": list(VALID_SCENARIOS),
    }


@app.get("/api/scenario")
async def get_scenario():
    """현재 시나리오 조회."""
    return {"scenario": app.state.scenario}


@app.post("/api/scenario")
async def set_scenario(mode: str):
    """
    시나리오 런타임 전환.
    호출 예:
      curl -X POST 'http://127.0.0.1:8001/api/scenario?mode=danger'
    또는 브라우저 대시보드에서 window.setScenario('danger').

    scheduler 는 매 틱 app.state.scenario 를 읽으므로 변경이 즉시 반영.
    """
    if mode not in VALID_SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid scenario '{mode}'. valid: {list(VALID_SCENARIOS)}",
        )
    prev = app.state.scenario
    app.state.scenario = mode
    print(f"[main] scenario 변경: {prev} → {mode}")
    return {"scenario": mode, "previous": prev}
