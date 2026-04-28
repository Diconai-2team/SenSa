"""
scheduler.py — 1초 주기 시뮬레이션 루프 (Phase E5)
════════════════════════════════════════════════════════════
FastAPI 기동 시 lifespan 에서 백그라운드 태스크로 돌며 Django REST API 로
센서값/작업자 위치를 POST 한다. Django 가 판정해 돌려준 status 를
재활용해 /check-geofence/ 로 상태 전이 기반 알람 판정을 트리거한다.

설계 원칙:
  - FastAPI 는 판정을 하지 않는다 (알람 판정은 Django 단일 출처)
  - httpx.AsyncClient 는 루프 바깥에서 한 번만 생성 (TCP 핸드셰이크 절약)
  - asyncio.gather(return_exceptions=True) 로 센서·작업자 POST 를 병렬 실행
    (1건 실패가 나머지 POST 를 막지 않음)
  - 예외는 해당 틱만 스킵, 루프 자체는 지속
  - app_state.scenario 를 매 틱 읽어 런타임 시나리오 전환 반영

[E5 개정점 — 이전 '개념 스케치' 대비]
  1. base_url 파라미터 제거 (poster 가 config.DJANGO_BASE_URL 직접 사용)
  2. sensor_summary 의 status 를 "normal" 하드코딩하지 않고
     post_sensor_data 응답의 status 를 재활용 (설계 4.4 핵심)
  3. power 센서도 전송 (Django SensorDataView 가 이제 수용)
  4. sensors 각 요소에 x, y 추가 (근접 센서 판정 PROXIMITY_RADIUS 용)
  5. gather(return_exceptions=True) 로 부분 실패 격리

[P2+ 개정 — 5초 주기 동적 재로드]
  6. RELOAD_INTERVAL (5초) 마다 devices/workers 재로드.
     기존: 기동 시 1회만 로드 → 새 센서/작업자가 재시작 전까지 미반영
     현행: RELOAD_INTERVAL 틱마다 Django 에서 재로드하여 신규 추가 자동 인식.
     - devices: 통째 교체 (시뮬 상태 없음, x/y 는 DB 가 SoT)
     - workers: 신규만 추가, 기존은 in-memory 좌표 유지, 제거된 작업자는 빠짐
       (재로드 때마다 좌표 리셋되면 시뮬이 매번 점프하므로 보존이 필수)

[R1 개정 — 센서별 독립 시뮬 상태]
  7. 각 device 의 sim_state(평균회귀 prev + 이벤트 카운터) 보존.
     - _tick_once: device.setdefault('sim_state', {}) 로 dict 보유,
       generate_gas / generate_power 양쪽에 prev_state= 전달 → in-place 갱신.
       (v3 에서 power 도 동일 처방 적용)
     - _reload_devices_and_workers: 기존 센서의 sim_state 보존하며 메타만 갱신.
       (P2+ 의 통째 교체 로직을 diff 머지 방식으로 변경)

[Layer 3 — 알람 detail 라벨 동적화]
  8. 알람 메시지 detail 라벨에 **실제로 임계 넘긴 가스/항목** 표시.
     - v1: f"CO:{gas['co']}" 하드코딩 → CO 가 정상이어도 메시지에 [CO:8.79] 박힘
     - 현행: identify_worst_gas / identify_worst_power 로 worst 항목 식별
       → [H2S:18.2], [O2:17.3], [전류:22.5A] 등 진짜 원인이 박힘
     - 모든 항목이 정상 영역이면 fallback (정상 복귀 메시지 의미 유지)
"""
import asyncio
import httpx

from config import TICK_INTERVAL, DEFAULT_SCENARIO
from django_loader import load_devices, load_workers, load_thresholds
from generators import (
    generate_gas, generate_power, move_worker,
    identify_worst_gas, identify_worst_power,   # Layer 3 — 알람 detail 라벨용
    apply_thresholds,                            # v3 — Django DB 임계치 동기화
)
from poster import post_sensor_data, post_worker_location, post_check_geofence


# P2+ 동적 재로드 주기 (초)
# 5초: 사용자 체감상 "거의 즉시" 반영, DB 부하 무시 가능
RELOAD_INTERVAL_SEC = 5


# ═══════════════════════════════════════════════════════════
# 틱 1회 처리 — 루프와 분리해 예외 격리
# ═══════════════════════════════════════════════════════════

async def _tick_once(
    client: httpx.AsyncClient,
    devices: list[dict],
    workers: list[dict],
    scenario: str,
    tick: int,
) -> None:
    """
    한 틱 분량의 작업 (센서 POST + 작업자 POST + check-geofence).

    분리 근거:
      - 예외 격리: 여기서 raise 해도 바깥 루프가 잡아 다음 틱으로 진행
      - 테스트 용이: 단일 틱 단위로 검증 가능
    """
    # ═══════════════════════════════════════════════════════
    # 1. 센서 POST 태스크 구성 (gas + power)
    # ═══════════════════════════════════════════════════════
    sensor_tasks: list = []
    sensor_refs:  list = []   # gather 결과를 device 와 zip 하려고 순서 보존

    for d in devices:
        device_id = d["device_id"]
        sensor_type = d.get("sensor_type", "gas")

        if sensor_type == "gas":
            # R1: 센서별 시뮬 상태(평균회귀 prev + 이벤트 카운터)를 device dict 에 보관.
            # generate_gas 가 in-place 로 sim_state 갱신 + 새 가스값 반환.
            sim_state = d.setdefault("sim_state", {})
            gas = generate_gas(tick, scenario, prev_state=sim_state)
            sensor_tasks.append(
                post_sensor_data(client, device_id, "gas", gas)
            )
            # Layer 3: 알람 메시지 detail 에 "실제로 임계 넘긴 가스" 박기.
            # 모든 가스가 정상이면 fallback 으로 CO 표시 (회복 메시지 등에서 의미 유지).
            worst_label, worst_val = identify_worst_gas(gas)
            if worst_label is None:
                detail = f"CO:{gas['co']}"   # 정상 시 fallback (관례)
            else:
                detail = f"{worst_label}:{worst_val}"
            sensor_refs.append({
                "device": d,
                "sensor_type": "gas",
                "detail": detail,
            })

        elif sensor_type == "power":
            # R1 v3: 전력도 sim_state(평균회귀 prev + 이벤트 카운터) 보존.
            sim_state = d.setdefault("sim_state", {})
            power = generate_power(tick, scenario, prev_state=sim_state)
            sensor_tasks.append(
                post_sensor_data(client, device_id, "power", power)
            )
            # Layer 3: 전력도 worst 항목 동적 식별
            worst_label, worst_val = identify_worst_power(power)
            if worst_label is None:
                detail = f"전류:{power['current']}A"   # 정상 시 fallback
            elif worst_label == "전류":
                detail = f"전류:{worst_val}A"
            else:   # 전압
                detail = f"전압:{worst_val}V"
            sensor_refs.append({
                "device": d,
                "sensor_type": "power",
                "detail": detail,
            })
        # 다른 sensor_type (temperature/motion) 은 현재 미지원 → 스킵

    # ═══════════════════════════════════════════════════════
    # 2. 작업자 이동 + 위치 POST 태스크 구성
    # ═══════════════════════════════════════════════════════
    #
    # move_worker 는 in-place 로 x/y 업데이트.
    # 작업자 목록은 기동 시 한 번만 로드하고 프로세스 메모리에서 좌표 상태 유지.
    # 재기동 시 Django 의 latest 위치에서 이어받음 (django_loader 책임).
    worker_tasks: list = []
    worker_summary: list[dict] = []
    for w in workers:
        move_worker(w)
        worker_tasks.append(
            post_worker_location(client, w["worker_db_pk"], w["x"], w["y"])
        )
        worker_summary.append({
            "worker_id": w["worker_id"],
            "name":      w["name"],
            "x": round(w["x"]),
            "y": round(w["y"]),
        })

    # ═══════════════════════════════════════════════════════
    # 3. 저장 POST 병렬 실행
    # ═══════════════════════════════════════════════════════
    #
    # return_exceptions=True: 한 태스크가 실패해도 나머지는 그대로 진행.
    # 언패킹 순서가 sensor → worker 이므로 슬라이스 인덱스도 그 순서.
    results = await asyncio.gather(
        *sensor_tasks, *worker_tasks, return_exceptions=True
    )
    sensor_results = results[:len(sensor_tasks)]
    # worker_results = results[len(sensor_tasks):]  # 현재 후처리 없음

    # ═══════════════════════════════════════════════════════
    # 4. check-geofence 용 sensor_summary 구성
    # ═══════════════════════════════════════════════════════
    #
    # 각 센서 POST 응답에서 Django 가 판정한 status 를 그대로 재활용.
    # FastAPI 자체 판정은 금지 (원칙 3, 통합결정 4.4).
    #
    # 응답 실패(res is None or Exception)인 센서는 이번 틱 복합 판정에서 제외.
    # 해당 틱에 잠시 알람 안 떠도 다음 틱에 다시 시도되므로 무해.
    sensor_summary: list[dict] = []
    for ref, res in zip(sensor_refs, sensor_results):
        if isinstance(res, Exception) or res is None:
            continue
        status = res.get("status", "normal")
        device = ref["device"]
        sensor_summary.append({
            "device_id":   device["device_id"],
            "sensor_type": ref["sensor_type"],
            "status":      status,
            "detail":      ref["detail"],
            "x": device.get("x", 0),   # CheckGeofenceView 의 PROXIMITY_RADIUS 판정용
            "y": device.get("y", 0),
        })

    # ═══════════════════════════════════════════════════════
    # 5. 알람 판정 트리거
    # ═══════════════════════════════════════════════════════
    #
    # 작업자 0명이면 스킵 — evaluate_worker 호출할 대상 없음.
    # sensor_summary 가 비어도 POST 는 보냄 (작업자-지오펜스 진입 알람은 생성됨).
    if worker_summary:
        await post_check_geofence(client, worker_summary, sensor_summary)


# ═══════════════════════════════════════════════════════════
# P2+ — 동적 재로드 헬퍼
# ═══════════════════════════════════════════════════════════

async def _reload_devices_and_workers(
    client: httpx.AsyncClient,
    devices: list[dict],
    workers: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Django 에서 devices/workers 재로드.
    devices 는 통째 교체. workers 는 기존 in-memory 좌표 유지하며 diff 적용.

    Returns:
        (new_devices, new_workers) — 호출자가 자기 변수에 재할당.
    """
    try:
        fresh_devices = await load_devices(client)
        fresh_workers = await load_workers(client)
    except Exception as e:
        print(f"[scheduler] 동적 재로드 실패 (이번 사이클 스킵): {e!r}")
        return devices, workers

    # devices: x/y 는 DB 가 SoT 이지만 sim_state(R1 평균회귀 prev) 는 in-memory 보존
    prev_dev_by_id = {d["device_id"]: d for d in devices}
    prev_dev_ids  = set(prev_dev_by_id)
    fresh_dev_ids = {d["device_id"] for d in fresh_devices}
    added_dev   = fresh_dev_ids - prev_dev_ids
    removed_dev = prev_dev_ids - fresh_dev_ids
    if added_dev or removed_dev:
        print(
            f"[scheduler] device 갱신: +{len(added_dev)} -{len(removed_dev)} "
            f"/ 총 {len(fresh_devices)} (신규: {sorted(added_dev) or '-'})"
        )

    # 기존 센서는 sim_state 보존하면서 메타(x, y, device_name, sensor_type) 갱신.
    # sim_state 가 매번 리셋되면 평균회귀가 무의미해지고 매번 normal center 에서 시작.
    new_devices: list[dict] = []
    for fd in fresh_devices:
        did = fd["device_id"]
        if did in prev_dev_by_id:
            existing = prev_dev_by_id[did]
            existing["device_name"] = fd["device_name"]
            existing["sensor_type"] = fd["sensor_type"]
            existing["x"] = fd["x"]
            existing["y"] = fd["y"]
            new_devices.append(existing)
        else:
            new_devices.append(fd)

    # workers: in-memory 좌표 보존 + diff 적용
    # 매번 좌표 리셋되면 시뮬이 매번 점프하므로 보존이 필수
    prev_workers_by_id = {w["worker_id"]: w for w in workers}
    new_workers: list[dict] = []
    for fw in fresh_workers:
        wid = fw["worker_id"]
        if wid in prev_workers_by_id:
            # 기존 작업자 — in-memory 좌표(x, y, dx, dy) 유지, 메타만 갱신
            existing = prev_workers_by_id[wid]
            existing["worker_db_pk"] = fw["worker_db_pk"]
            existing["name"]         = fw["name"]
            new_workers.append(existing)
        else:
            # 신규 작업자 — fresh 그대로 추가 (load_workers 가 latest 좌표 채워줌)
            new_workers.append(fw)

    added_w   = {fw["worker_id"] for fw in fresh_workers} - set(prev_workers_by_id)
    removed_w = set(prev_workers_by_id) - {fw["worker_id"] for fw in fresh_workers}
    if added_w or removed_w:
        print(
            f"[scheduler] worker 갱신: +{len(added_w)} -{len(removed_w)} "
            f"/ 총 {len(new_workers)} (신규: {sorted(added_w) or '-'})"
        )

    return new_devices, new_workers


# ═══════════════════════════════════════════════════════════
# 메인 루프
# ═══════════════════════════════════════════════════════════

async def run_simulation_loop(app_state) -> None:
    """
    FastAPI lifespan 에서 asyncio.create_task 로 기동되는 백그라운드 태스크.

    루프 수명:
      1. httpx.AsyncClient 1개를 열고 shutdown 까지 재사용
      2. Django 에서 devices / workers 1회 로드
      3. 무한 루프 — 매 틱마다 _tick_once() 호출
      4. RELOAD_INTERVAL_SEC 마다 _reload_devices_and_workers() 호출 (P2+)
      5. shutdown 신호 시 CancelledError 로 빠져나오며 client 자동 정리

    Args:
        app_state: FastAPI 의 app.state.
            scenario 를 매 틱 읽어 런타임 전환 반영 (Phase E6 에서 엔드포인트 추가).
    """
    # timeout 은 AsyncClient 기본값. 개별 요청은 poster 에서 3초 명시.
    async with httpx.AsyncClient() as client:
        # ─── 초기 로드 — fail-fast ───
        #
        # 로드 실패 시 조용한 폴백을 두지 않는다 (통합결정 2.2).
        # Django 가 안 켜져 있으면 로그 남기고 루프 자체를 종료.
        try:
            devices = await load_devices(client)
            workers = await load_workers(client)
        except Exception as e:
            print(f"[scheduler] 초기 로드 실패 — Django 기동 여부 확인: {e!r}")
            return

        # ─── v3 신규 — 임계치 동기화 (fail-soft) ───
        # 실패해도 generators.py 의 fallback 임계치(KOSHA 표준 하드코딩)로 동작.
        # Django 미기동 / 신규 배포 등에서 안전 마진 확보.
        loaded = await load_thresholds(client)
        n_thresholds = apply_thresholds(loaded)
        if n_thresholds == 0:
            print("[scheduler] 임계치 DB 로드 실패 또는 미설정 — fallback 사용")

        print(
            f"[scheduler] 장비 {len(devices)}개 (가스 "
            f"{sum(1 for d in devices if d.get('sensor_type')=='gas')}, 전력 "
            f"{sum(1 for d in devices if d.get('sensor_type')=='power')}), "
            f"작업자 {len(workers)}명 로드 완료 "
            f"(tick_interval={TICK_INTERVAL}s, reload={RELOAD_INTERVAL_SEC}s, "
            f"scenario={getattr(app_state, 'scenario', DEFAULT_SCENARIO)})"
        )

        # P2+ 재로드 시점 추적 — TICK_INTERVAL 단위로 환산
        # 예: TICK_INTERVAL=1, RELOAD_INTERVAL_SEC=5 → 5틱마다 재로드
        reload_every_n_ticks = max(1, int(RELOAD_INTERVAL_SEC / max(TICK_INTERVAL, 0.1)))

        # ─── 무한 루프 ───
        tick = 0
        while True:
            tick += 1
            # getattr 폴백 — main.py 에서 app.state.scenario 초기화 누락 시에도
            # 루프가 죽지 않음
            scenario = getattr(app_state, "scenario", DEFAULT_SCENARIO)

            # P2+ 주기 재로드 — _tick_once 보다 먼저 수행해서
            # 신규 센서/작업자가 즉시 이번 틱부터 시뮬에 포함되도록 함.
            if tick % reload_every_n_ticks == 0:
                devices, workers = await _reload_devices_and_workers(
                    client, devices, workers,
                )
                # v3 — 임계치도 동시 재로드. 백오피스에서 임계치 변경 시 5초 안에 반영.
                # 실패해도 기존 GAS_THRESHOLDS 유지 (apply_thresholds 가 None 받으면 no-op).
                loaded = await load_thresholds(client)
                apply_thresholds(loaded)

            try:
                await _tick_once(client, devices, workers, scenario, tick)
            except asyncio.CancelledError:
                # shutdown 시 여기로 빠져나옴 — 정상 종료 경로
                print("[scheduler] 종료 신호 수신, 루프 중단")
                raise
            except Exception as e:
                # 일반 예외는 이번 틱만 버리고 다음 틱 진행
                print(f"[scheduler] tick {tick} 에러 (스킵): {e!r}")

            await asyncio.sleep(TICK_INTERVAL)