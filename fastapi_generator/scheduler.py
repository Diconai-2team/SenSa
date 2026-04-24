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
"""
import asyncio
import httpx

from config import TICK_INTERVAL, DEFAULT_SCENARIO
from django_loader import load_devices, load_workers
from generators import generate_gas, generate_power, move_worker
from poster import post_sensor_data, post_worker_location, post_check_geofence


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
            gas = generate_gas(tick, scenario)
            sensor_tasks.append(
                post_sensor_data(client, device_id, "gas", gas)
            )
            # detail 은 서버 알람 메시지에 붙음 — 대표값 CO 관례 (Phase A 결정 유지)
            # TODO(Phase F): status 에 기여한 실제 worst 가스명 추적
            sensor_refs.append({
                "device": d,
                "sensor_type": "gas",
                "detail": f"CO:{gas['co']}",
            })

        elif sensor_type == "power":
            power = generate_power(tick, scenario)
            sensor_tasks.append(
                post_sensor_data(client, device_id, "power", power)
            )
            sensor_refs.append({
                "device": d,
                "sensor_type": "power",
                "detail": f"전류:{power['current']}A",
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
# 메인 루프
# ═══════════════════════════════════════════════════════════

async def run_simulation_loop(app_state) -> None:
    """
    FastAPI lifespan 에서 asyncio.create_task 로 기동되는 백그라운드 태스크.

    루프 수명:
      1. httpx.AsyncClient 1개를 열고 shutdown 까지 재사용
      2. Django 에서 devices / workers 1회 로드 (4차에서 동적 갱신 예정)
      3. 무한 루프 — 매 틱마다 _tick_once() 호출
      4. shutdown 신호 시 CancelledError 로 빠져나오며 client 자동 정리

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

        print(
            f"[scheduler] 장비 {len(devices)}개 (가스 "
            f"{sum(1 for d in devices if d.get('sensor_type')=='gas')}, 전력 "
            f"{sum(1 for d in devices if d.get('sensor_type')=='power')}), "
            f"작업자 {len(workers)}명 로드 완료 "
            f"(tick_interval={TICK_INTERVAL}s, scenario={getattr(app_state, 'scenario', DEFAULT_SCENARIO)})"
        )

        # ─── 무한 루프 ───
        tick = 0
        while True:
            tick += 1
            # getattr 폴백 — main.py 에서 app.state.scenario 초기화 누락 시에도
            # 루프가 죽지 않음
            scenario = getattr(app_state, "scenario", DEFAULT_SCENARIO)

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