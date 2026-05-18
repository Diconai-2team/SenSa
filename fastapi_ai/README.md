# fastapi_ai

SenSa 4차 단계 — AI 추론 서버 (Phase E).

TTM zero-shot 기반 시계열 이상 탐지 추론 API. SenSa Django 와는
HTTP API 로만 통신하여 느슨하게 결합.

## Phase 진행 상황

| Phase | 내용 | 상태 |
|-------|------|------|
| E-1 | 기본 서버 구조 + 헬스체크 | ✅ 완료 |
| E-2 | TTM 추론 엔드포인트 (/predict/ttm) | 진행 예정 |
| E-3 | SenSa 측 클라이언트 통합 | 진행 예정 |

## 구조

```
fastapi_ai/
├── main.py             # FastAPI 앱 (라이프사이클 훅 포함)
├── schemas.py          # Pydantic 응답 스키마
├── requirements.txt    # 추가 의존성 (ai_lab venv 재사용)
├── run.sh              # 시작 스크립트
└── README.md
```

## 설치

ai_lab venv 를 재사용 (torch, granite-tsfm 이미 설치됨).
fastapi, uvicorn 등 신규 의존성만 추가 설치.

```bash
# 1) ai_lab venv 활성화
source ../ai_lab/venv/bin/activate

# 2) 추가 의존성 설치
cd ../fastapi_ai
pip install -r requirements.txt

# 3) 서버 시작
bash run.sh
```

## 엔드포인트 (E-1 시점)

### GET /
서비스 메타 정보.

```json
{
  "service": "SenSa AI Server",
  "version": "0.1.0",
  "status": "running",
  "started_at": "2026-05-12T10:00:00"
}
```

### GET /health
헬스체크. SenSa Django 가 서버 가용성 확인 시 호출.

```json
{
  "status": "ok",
  "model_loaded": false,
  "uptime_sec": 123.45
}
```

### GET /docs
FastAPI 자동 생성 Swagger UI.

## 검증

서버 기동 후:

```bash
# 다른 터미널에서
curl http://localhost:8002/
curl http://localhost:8002/health
```

또는 브라우저에서:
- http://localhost:8002/        — 서비스 정보
- http://localhost:8002/health  — 헬스체크
- http://localhost:8002/docs    — Swagger UI

## 다음 단계 (E-2)

- TTM 모델 라이프사이클 훅에서 로딩
- POST /predict/ttm 엔드포인트
- 시계열 입력 → 96 step forecast + 잔차 + anomaly 응답
- ai_lab 의 ttm_baseline_v2.ipynb 로직을 서버 코드로 이식
