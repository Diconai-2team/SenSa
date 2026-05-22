"""
ai_test.py — AI 조기 탐지 성능 시나리오 테스트

실행:
    cd /root/SenSa/fastapi_generator
    python ai_test.py [--device gas-001] [--scenario gradual|spike|drift|all]

시나리오:
    gradual  — 정상 → 점진적 증가 → 임계치 초과 → 회복
               AI가 임계치 초과 전에 경고했는지 확인 (조기 탐지 TP)
    spike    — 정상 → 즉각 임계치 초과
               갑작스러운 스파이크에서 AI 한계 확인 (구조적 FN)
    drift    — 아주 느리게 증가 (CUSUM 탐지 목적)
    all      — 3가지 순서대로 실행

결과 해석:
    ML 알람이 sensor_danger 보다 먼저 발생 → TP (조기 탐지 성공)
    sensor_danger만 발생, ML 알람 없음      → FN (미탐)
    sensor_danger 없이 ML 알람만 발생      → FP (오탐)
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone

import httpx

# config에서 환경변수 로드
try:
    from config import DJANGO_BASE_URL, INTERNAL_HEADERS
except RuntimeError as e:
    print(f"[오류] {e}")
    sys.exit(1)

# ── 가스 임계치 (alerts/services.py GAS_THRESHOLDS 와 동기화) ──
GAS_THRESHOLDS = {
    'co':  {'caution': 25,   'danger': 200  },
    'h2s': {'caution': 10,   'danger': 50   },
    'co2': {'caution': 1000, 'danger': 5000 },
    'o2':  {'caution': 19.5, 'danger': 18.0 },  # 구간형: 18미만/23.5이상 → danger
    'no2': {'caution': 3,    'danger': 5    },
    'so2': {'caution': 2,    'danger': 5    },
    'o3':  {'caution': 0.05, 'danger': 0.1  },
    'nh3': {'caution': 25,   'danger': 50   },
    'voc': {'caution': 0.5,  'danger': 2.0  },  # mg/m³ TVOC 실내기준
}

# 기본 정상값 (서버 단위 기준)
NORMAL_GAS = {
    'co': 5.0, 'h2s': 1.0, 'co2': 400.0, 'o2': 20.9,
    'no2': 0.1, 'so2': 0.2, 'o3': 0.02, 'nh3': 2.0, 'voc': 0.05,
}

ALARM_API = f"{DJANGO_BASE_URL}/dashboard/api/alarm/"


# ── 유틸리티 ──────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


async def post_gas(client: httpx.AsyncClient, device_id: str, values: dict) -> str:
    """가스 데이터 1건 전송 → 판정 상태 반환"""
    payload = {'device_id': device_id, 'sensor_type': 'gas', **values}
    try:
        r = await client.post(
            f"{DJANGO_BASE_URL}/dashboard/api/sensor-data/",
            json=payload, headers=INTERNAL_HEADERS, timeout=10.0,
        )
        return r.json().get('status', '?') if r.status_code < 400 else f'HTTP{r.status_code}'
    except httpx.HTTPError as e:
        return f'ERR({type(e).__name__})'


async def fetch_recent_alarms(client: httpx.AsyncClient, device_id: str, since_ts: float, count: int = 200) -> list:
    """테스트 시작 이후 발생한 알람 조회"""
    # since_ts(Unix timestamp)를 ISO8601로 변환하여 API에 전달
    since_iso = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        r = await client.get(
            ALARM_API, headers=INTERNAL_HEADERS,
            params={
                'device_id': device_id,
                'created_after': since_iso,
                'limit': count,
            },
            timeout=10.0,
        )
        if r.status_code >= 400:
            return []
        data = r.json()
        # DRF PageNumberPagination: {"results": [...]} / 또는 직접 리스트
        return data.get('results', data) if isinstance(data, dict) else data
    except Exception:
        return []


# ── 시나리오 ──────────────────────────────────────────────────────

async def scenario_gradual(client: httpx.AsyncClient, device_id: str, target_gas: str = 'co'):
    """
    점진적 증가 시나리오
    정상(30초) → 완만한 증가(60초) → 임계치 초과(10초) → 정상 복귀(20초)
    """
    print(f"\n{'='*60}")
    print(f"[시나리오 1] 점진적 증가  |  센서: {device_id}  |  타겟: {target_gas.upper()}")
    print(f"  목표: AI가 임계치({GAS_THRESHOLDS[target_gas]['danger']}ppm) 초과 전에 경고 발생 여부 확인")
    print('='*60)

    normal_val  = NORMAL_GAS[target_gas]
    danger_val  = GAS_THRESHOLDS[target_gas]['danger']
    caution_val = GAS_THRESHOLDS[target_gas]['caution']
    start_time  = time.time()
    alarm_log   = []   # (elapsed, alarm_type, alarm_level)
    threshold_crossed_at = None
    first_ml_alarm_at    = None

    def make_gas(val):
        g = dict(NORMAL_GAS)
        g[target_gas] = round(val, 2)
        return g

    async def send_and_log(val, phase):
        status = await post_gas(client, device_id, make_gas(val))
        elapsed = time.time() - start_time
        marker = '🔴' if status == 'danger' else ('⚠️ ' if status == 'caution' else '✅')
        print(f"  [{ts()}] {phase:8s}  {target_gas.upper()}={val:7.1f}ppm  상태={status}  {marker}  (+{elapsed:.0f}s)")
        return elapsed, status

    # 1단계: 정상 (30초)
    print(f"\n[1단계] 정상 데이터 전송 (30초)")
    for i in range(30):
        await send_and_log(normal_val, '정상')
        await asyncio.sleep(1)

    # 2단계: 점진적 증가 (60초, caution~danger 사이)
    print(f"\n[2단계] 점진적 증가 (60초, {normal_val:.0f}→{danger_val*0.95:.0f}ppm)")
    for i in range(60):
        progress = i / 59
        val = normal_val + (danger_val * 0.95 - normal_val) * progress
        elapsed, status = await send_and_log(round(val, 1), '증가중')
        await asyncio.sleep(1)

    # 3단계: 임계치 초과
    print(f"\n[3단계] 임계치 초과 ({danger_val * 1.1:.0f}ppm)")
    for i in range(10):
        elapsed, status = await send_and_log(danger_val * 1.1, '위험!')
        if status == 'danger' and threshold_crossed_at is None:
            threshold_crossed_at = elapsed
        await asyncio.sleep(1)

    # 4단계: 정상 복귀
    print(f"\n[4단계] 정상 복귀")
    for i in range(20):
        await send_and_log(normal_val, '복귀')
        await asyncio.sleep(1)

    # 결과 분석 — 알람 조회
    print(f"\n{'─'*60}")
    print(f"[결과 분석]  총 소요: {time.time()-start_time:.0f}초")
    alarms = await fetch_recent_alarms(client, device_id, start_time)

    ml_alarms = [a for a in alarms if a.get('alarm_type', '').startswith('ai_')]
    th_alarms = [a for a in alarms if a.get('alarm_type') in ('sensor_danger', 'sensor_caution')]

    print(f"  ML 알람:     {len(ml_alarms)}건")
    print(f"  임계치 알람: {len(th_alarms)}건")

    if ml_alarms:
        print(f"\n  ML 알람 목록:")
        for a in ml_alarms[:5]:
            print(f"    [{a.get('alarm_level')}] {a.get('alarm_type')}  {a.get('created_at','')[:19]}")
            print(f"      → {a.get('message','')[:80]}")

    if th_alarms and ml_alarms:
        print(f"\n  ✅ TP 가능성 있음 — 임계치 알람 전에 ML 알람이 발생했는지 백오피스에서 확인하세요.")
        print(f"     /backoffice/ai-metrics/ → AI 성능 평가 섹션")
    elif th_alarms and not ml_alarms:
        print(f"\n  ❌ FN 의심 — 임계치 초과했지만 ML 알람 없음")
        print(f"     → contamination 값을 0.01보다 높게 조정 권장")
    elif not th_alarms:
        print(f"\n  ℹ️  임계치 알람 미발생 — 임계치 설정 또는 데이터 값 확인 필요")


async def scenario_spike(client: httpx.AsyncClient, device_id: str, target_gas: str = 'co'):
    """
    즉각 스파이크 시나리오
    정상(20초) → 즉각 임계치 2배(5초) → 정상 복귀
    AI는 구조적으로 사전 감지 불가 → FN이 정상
    """
    print(f"\n{'='*60}")
    print(f"[시나리오 2] 즉각 스파이크  |  센서: {device_id}  |  타겟: {target_gas.upper()}")
    print(f"  목표: 갑작스러운 스파이크는 AI 사전 감지 한계 확인 (FN이 정상 결과)")
    print('='*60)

    normal_val = NORMAL_GAS[target_gas]
    danger_val = GAS_THRESHOLDS[target_gas]['danger']
    start_time = time.time()

    def make_gas(val):
        g = dict(NORMAL_GAS)
        g[target_gas] = round(val, 2)
        return g

    print(f"\n[1단계] 정상 (20초)")
    for _ in range(20):
        status = await post_gas(client, device_id, make_gas(normal_val))
        print(f"  [{ts()}] 정상  {target_gas.upper()}={normal_val}ppm  {status}")
        await asyncio.sleep(1)

    print(f"\n[2단계] 즉각 스파이크 ({danger_val*2:.0f}ppm, 5초)")
    for _ in range(5):
        status = await post_gas(client, device_id, make_gas(danger_val * 2))
        marker = '🔴' if status == 'danger' else '?'
        print(f"  [{ts()}] 스파이크!  {target_gas.upper()}={danger_val*2}ppm  {status}  {marker}")
        await asyncio.sleep(1)

    print(f"\n[3단계] 정상 복귀 (15초)")
    for _ in range(15):
        status = await post_gas(client, device_id, make_gas(normal_val))
        print(f"  [{ts()}] 복귀  {target_gas.upper()}={normal_val}ppm  {status}")
        await asyncio.sleep(1)

    alarms = await fetch_recent_alarms(client, device_id, start_time)
    ml_alarms = [a for a in alarms if a.get('alarm_type', '').startswith('ai_')]
    th_alarms = [a for a in alarms if a.get('alarm_type') in ('sensor_danger', 'sensor_caution')]
    print(f"\n[결과]  ML={len(ml_alarms)}건  임계치={len(th_alarms)}건  (스파이크는 FN이 정상)")


async def scenario_drift(client: httpx.AsyncClient, device_id: str, target_gas: str = 'co'):
    """
    느린 드리프트 시나리오 (CUSUM 탐지 목적)
    정상(30초) → 매우 느린 증가(120초, caution 미만) → 복귀
    CUSUM은 누적 편차를 보므로 작은 변화도 감지해야 함
    """
    print(f"\n{'='*60}")
    print(f"[시나리오 3] 느린 드리프트  |  센서: {device_id}  |  타겟: {target_gas.upper()}")
    print(f"  목표: 작은 변화 누적을 CUSUM이 감지하는지 확인 (임계치 미달)")
    print('='*60)

    normal_val  = NORMAL_GAS[target_gas]
    caution_val = GAS_THRESHOLDS[target_gas]['caution']
    drift_target = caution_val * 0.8  # caution의 80%까지만
    start_time = time.time()

    def make_gas(val):
        g = dict(NORMAL_GAS)
        g[target_gas] = round(val, 2)
        return g

    print(f"\n[1단계] 정상 (30초)")
    for _ in range(30):
        status = await post_gas(client, device_id, make_gas(normal_val))
        print(f"  [{ts()}] {target_gas.upper()}={normal_val:.1f}ppm  {status}")
        await asyncio.sleep(1)

    print(f"\n[2단계] 느린 드리프트 ({normal_val:.1f}→{drift_target:.1f}ppm, 120초)")
    for i in range(120):
        progress = i / 119
        val = normal_val + (drift_target - normal_val) * progress
        status = await post_gas(client, device_id, make_gas(round(val, 1)))
        if i % 10 == 0:
            print(f"  [{ts()}] {target_gas.upper()}={val:.1f}ppm  {status}")
        await asyncio.sleep(1)

    print(f"\n[3단계] 복귀 (20초)")
    for _ in range(20):
        await post_gas(client, device_id, make_gas(normal_val))
        await asyncio.sleep(1)

    alarms = await fetch_recent_alarms(client, device_id, start_time)
    ml_alarms = [a for a in alarms if a.get('alarm_type', '').startswith('ai_')]
    drift_alarms = [a for a in ml_alarms if a.get('alarm_type') in ('ai_drift_alert', 'ai_trend_shift')]

    print(f"\n[결과]  ML 알람={len(ml_alarms)}건  드리프트/급변={len(drift_alarms)}건")
    if drift_alarms:
        print(f"  ✅ CUSUM/ChangePoint 정상 동작")
        for a in drift_alarms[:3]:
            print(f"    [{a.get('alarm_level')}] {a.get('alarm_type')}  {a.get('created_at','')[:19]}")
    else:
        print(f"  ℹ️  드리프트 알람 없음 — 변화 폭이 작거나 CUSUM 기준값 재학습 필요")


# ── 메인 ──────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description='AI 조기 탐지 성능 테스트')
    parser.add_argument('--device',   default='gas-001',  help='테스트할 가스 센서 device_id')
    parser.add_argument('--gas',      default='co',       help='타겟 가스 종류 (co/h2s/co2/...)')
    parser.add_argument('--scenario', default='gradual',
                        choices=['gradual', 'spike', 'drift', 'all'],
                        help='실행할 시나리오')
    args = parser.parse_args()

    print(f"\n{'#'*60}")
    print(f"# AI 조기 탐지 테스트")
    print(f"# 센서: {args.device}  가스: {args.gas.upper()}  시나리오: {args.scenario}")
    print(f"# 서버: {DJANGO_BASE_URL}")
    print(f"{'#'*60}")
    print(f"\n⚠️  실행 중 백오피스 알람 목록이 오염될 수 있습니다.")
    print(f"   테스트 후 /backoffice/ai-metrics/ 에서 결과를 확인하세요.\n")

    async with httpx.AsyncClient() as client:
        # 서버 연결 확인
        try:
            r = await client.get(f"{DJANGO_BASE_URL}/dashboard/api/alarm/stats/",
                                 headers=INTERNAL_HEADERS, timeout=5.0)
            print(f"✅ 서버 연결 확인  (현재 24h 알람: {r.json().get('total', '?')}건)\n")
        except Exception as e:
            print(f"❌ 서버 연결 실패: {e}")
            return

        if args.scenario in ('gradual', 'all'):
            await scenario_gradual(client, args.device, args.gas)
        if args.scenario in ('spike', 'all'):
            await scenario_spike(client, args.device, args.gas)
        if args.scenario in ('drift', 'all'):
            await scenario_drift(client, args.device, args.gas)

    print(f"\n{'='*60}")
    print(f"테스트 완료. 백오피스에서 결과 확인:")
    print(f"  AI 지표: {DJANGO_BASE_URL}/backoffice/ai-metrics/")
    print(f"  알람 목록: {DJANGO_BASE_URL}/dashboard/alarms/")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    asyncio.run(main())
