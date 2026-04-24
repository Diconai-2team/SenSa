/**
 * base.js — SenSa 공통 모듈
 *
 * [이력]
 *   Phase A    : WORKERS/SENSOR_DEVICES 정의, 로컬 시뮬 + HTTP POST
 *   Phase C4   : WebSocket 연결 추가 (alarm.new 수신)
 *   Phase D    : 작업자 API 동적 로드 + workersLoaded 이벤트
 *   Gas 병합   : 9종 가스 임계치(GAS_TH), classifyGas, genGas
 *   Power 병합 : classifyPower, genPower
 *   Phase E5   : FastAPI scheduler 기동 → 브라우저와 중복 POST 상태
 *   Phase E7   : 브라우저 시뮬 로직 제거 (본 커밋)
 *                → 데이터 생성·POST 는 FastAPI 전담
 *                → base.js 는 "수신 + UI 이벤트 dispatch" 만
 *
 * 이벤트 목록 (SenSa.on 으로 다른 section_*.js 가 구독):
 *   sensa:gasData       { device_id, gas, status }
 *   sensa:powerData     { device_id, power, status }
 *   sensa:sensorUpdate  { device, data }
 *   sensa:workerMove    { workers }
 *   sensa:workersLoaded { workers }
 *   sensa:alarm         { alarm_level, message, ... }
 *
 * [E7 아키텍처]
 *
 *   FastAPI scheduler ─ POST ─► Django ─► DB 저장 + 판정
 *                                   │
 *                                   └─► WS broadcast ─► 브라우저(이 파일)
 *                                                            │
 *                                                            └─► SenSa.emit
 *                                                                 │
 *                                                                 └─► section_*.js
 */

// ═══════════════════════════════════════════════════════════
// 이벤트 버스
// ═══════════════════════════════════════════════════════════
window.SenSa = {
  emit: function (name, data) {
    document.dispatchEvent(new CustomEvent('sensa:' + name, { detail: data }));
  },
  on: function (name, fn) {
    document.addEventListener('sensa:' + name, function (e) { fn(e.detail); });
  },
};

// ─── CSRF 유틸 ───
function getCsrfToken() {
  var c = document.cookie.split(';').find(function (c) { return c.trim().startsWith('csrftoken='); });
  return c ? c.split('=')[1] : '';
}
window.getCsrfToken = getCsrfToken;


// ═══════════════════════════════════════════════════════════
// 센서 장비 정의 (지도 마커 초기화용)
// ═══════════════════════════════════════════════════════════
//
// DB 의 Device 테이블, FastAPI scheduler 의 load_devices, 그리고 이 배열
// 세 곳이 일치해야 함. 기준은 DB. 여기는 UI 배치 좌표까지 포함한 복제.
window.SENSOR_DEVICES = [
  { device_id: 'sensor_01', device_name: '가스센서 A', sensor_type: 'gas',   location: { x: 200, y: 150 } },
  { device_id: 'sensor_02', device_name: '가스센서 B', sensor_type: 'gas',   location: { x: 500, y: 180 } },
  { device_id: 'sensor_03', device_name: '가스센서 C', sensor_type: 'gas',   location: { x: 350, y: 390 } },
  { device_id: 'power_01',  device_name: '스마트파워 A', sensor_type: 'power', location: { x: 620, y: 100 } },
  { device_id: 'power_02',  device_name: '스마트파워 B', sensor_type: 'power', location: { x: 130, y: 390 } },
];


// ═══════════════════════════════════════════════════════════
// WORKERS — API 에서 동적 로드
// ═══════════════════════════════════════════════════════════
//
// 초기 좌표(x, y) 는 지도 마커 배치용 임시값. WS worker.position 이 들어오기
// 시작하면 즉시 실제 좌표로 갱신됨 (handleWorkerPosition 이 WORKERS 배열 동기화).
// E7 부터 dx/dy (이동 속도) 는 브라우저에서 쓰이지 않아 제거.
window.WORKERS = [];

async function loadWorkersFromAPI() {
  try {
    var res = await fetch('/dashboard/api/worker/', { credentials: 'include' });
    if (!res.ok) {
      console.error('Worker API 호출 실패:', res.status);
      return;
    }
    var data = await res.json();
    var list = data.results || data;

    window.WORKERS = list.map(function (worker, index) {
      return {
        worker_id:  worker.worker_id,
        name:       worker.name,
        department: worker.department || '',
        // 임시 초기 배치 — WS 첫 수신 전까지만 의미
        x: 200 + (index % 3) * 200 + Math.random() * 50,
        y: 200 + Math.floor(index / 3) * 150 + Math.random() * 50,
      };
    });

    console.log('Worker ' + window.WORKERS.length + '명 로드 완료:',
      window.WORKERS.map(function (w) { return w.name; }).join(', '));

    SenSa.emit('workersLoaded', { workers: window.WORKERS });
  } catch (e) {
    console.error('Worker 로드 에러:', e);
  }
}

loadWorkersFromAPI();


// ═══════════════════════════════════════════════════════════
// 색상/아이콘 상수
// ═══════════════════════════════════════════════════════════
window.ZONE_COLORS   = { danger: '#e74c3c', caution: '#f1c40f', restricted: '#9b59b6' };
window.SENSOR_COLORS = { gas: '#e74c3c', power: '#f39c12', temperature: '#3498db', motion: '#2ecc71' };
window.SENSOR_ICONS  = { gas: '💨', power: '⚡', temperature: '🌡️', motion: '🔊' };


// ═══════════════════════════════════════════════════════════
// 9종 가스 임계치 + 판정 헬퍼
// ═══════════════════════════════════════════════════════════
//
// E7 이후 브라우저는 판정을 하지 않지만, 이 값은 아래 용도로 유지:
//   - section_12_13_gas.js 가 자체 TH 와 비교 (뱃지 색 계산)
//   - 다른 모듈이 classifyGas/classifyPower 를 호출할 가능성
// 임계치 3곳 동기화 원칙 유지 (section_12_13_gas.js / base.js / alerts.services.py).
var GAS_TH = {
  co:  { w: 25,   d: 200  },   // ACGIH TWA / NIOSH Ceiling
  h2s: { w: 10,   d: 50   },   // KOSHA 적정공기 / IDLH
  co2: { w: 1000, d: 5000 },   // 실내공기질 / TWA
  no2: { w: 3,    d: 5    },   // 고용노동부 TWA / STEL
  so2: { w: 2,    d: 5    },   // 고용노동부 TWA / STEL
  o3:  { w: 0.05, d: 0.1  },   // ACGIH TLV
  nh3: { w: 25,   d: 50   },   // ACGIH TWA
  voc: { w: 0.5,  d: 2.0  },   // TVOC 실내기준
};

function classifyGas(g) {
  var worst = 'normal';
  if (g.o2 !== undefined) {
    if (g.o2 < 16 || g.o2 >= 23.5) return 'danger';
    if (g.o2 < 18 || g.o2 > 21.5) worst = 'caution';
  }
  for (var k in GAS_TH) {
    if (g[k] === undefined) continue;
    if (g[k] >= GAS_TH[k].d) return 'danger';
    if (g[k] >= GAS_TH[k].w && worst === 'normal') worst = 'caution';
  }
  return worst;
}

function classifyPower(p) {
  if (p.current >= 30 || p.watt >= 8000) return 'danger';
  if (p.current >= 20 || p.voltage < 200 || p.voltage > 240) return 'caution';
  return 'normal';
}
window.classifyGas = classifyGas;
window.classifyPower = classifyPower;


// ═══════════════════════════════════════════════════════════
// updateMapBounds — section_09_map.js 의 호환 껍데기
// ═══════════════════════════════════════════════════════════
//
// Phase E7 이전에는 브라우저가 작업자 이동을 직접 계산했고, 이 함수가
// 이미지 경계 (IMG_W, IMG_H) 를 알려주는 역할이었음.
// 지금은 이동을 FastAPI 가 하므로 값이 쓰이지 않지만, section_09_map.js 가
// 기동 시 호출하기 때문에 함수 자체는 남겨둠 (빈 no-op).
window.updateMapBounds = function (W, H) { /* no-op: E7 에서 시뮬 제거 */ };


// ═══════════════════════════════════════════════════════════
// 시나리오 전환
// ═══════════════════════════════════════════════════════════
//
// 기존 window.simMode 는 브라우저 내부 루프가 읽던 값. E7 에서 루프 제거.
// setScenario 는 이제 FastAPI 의 /api/scenario 엔드포인트 호출 + 버튼 UI 상태만.
// 버튼이 대시보드에 있다면 여기서 자동 동작, 없다면 콘솔에서 setScenario('danger') 직접 호출.
//
// FastAPI URL 은 기본 포트 8001 가정. 운영 환경에서 다르면 이 상수만 수정.
var FASTAPI_PORT = 8001;
window.simMode = 'mixed';   // 버튼 하이라이트용 상태

window.setScenario = function (mode) {
  // 1) 버튼 UI 토글
  window.simMode = mode;
  document.querySelectorAll('.scenario-btn').forEach(function (b) { b.classList.remove('active'); });
  var el = document.querySelector('.scenario-btn.' + mode);
  if (el) el.classList.add('active');

  // 2) FastAPI 로 시나리오 전환 요청
  //    scheduler 가 매 틱 app.state.scenario 를 읽으므로 다음 틱부터 반영.
  //    FastAPI 가 꺼져 있거나 CORS 미허용이면 조용히 실패 (UI 버튼만 바뀜).
  var fastapiUrl = 'http://' + window.location.hostname + ':' + FASTAPI_PORT +
                   '/api/scenario?mode=' + encodeURIComponent(mode);
  fetch(fastapiUrl, { method: 'POST' })
    .then(function (res) {
      if (res.ok) {
        console.log('[scenario] FastAPI 전환 성공:', mode);
      } else {
        console.warn('[scenario] FastAPI 응답 비정상:', res.status);
      }
    })
    .catch(function (e) {
      console.warn('[scenario] FastAPI 연결 실패 (FastAPI 기동 여부 / CORS 확인):', e.message);
    });
};


// ═══════════════════════════════════════════════════════════
// WebSocket 연결 + 수신 디스패치 (E7 핵심)
// ═══════════════════════════════════════════════════════════
//
// 수신하는 메시지 3종:
//   alarm.new        — 기존 (Phase C4)
//   worker.position  — 신규 수신 (E7)
//   sensor.update    — 신규 수신 (E7)
//
// 각 WS 메시지를 기존 SenSa 이벤트 형식으로 변환하여 dispatch.
// section_09_map.js, section_11_workers.js, section_12_13_gas.js 등
// 구독자 모듈은 코드 변경 없음.
window.sensaWS = null;

function connectWebSocket() {
  var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  var url = protocol + '//' + window.location.host + '/ws/dashboard/';

  var ws = new WebSocket(url);
  window.sensaWS = ws;

  ws.onopen = function () {
    console.log('[WS] connected');
  };

  ws.onmessage = function (event) {
    var msg;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      console.error('[WS] invalid JSON:', event.data);
      return;
    }

    switch (msg.type) {
      case 'alarm.new':
        handleAlarmNew(msg.payload);
        break;

      case 'worker.position':
        handleWorkerPosition(msg.payload);
        break;

      case 'sensor.update':
        handleSensorUpdate(msg.payload);
        break;

      case 'connection.established':
        console.log('[WS] auth ok, groups:', msg.payload || msg.groups);
        break;

      default:
        // 알 수 없는 타입은 조용히 무시
        break;
    }
  };

  ws.onclose = function (e) {
    console.warn('[WS] closed:', e.code, e.reason);
    // Phase F 에서 재접속 로직 추가 예정
  };

  ws.onerror = function (e) {
    console.error('[WS] error:', e);
  };
}

// ─── WS 메시지 → SenSa 이벤트 변환 ───────────────────────────

/**
 * alarm.new payload → sensa:alarm
 *
 * payload 구조:
 *   { alarm_id, alarm_type, alarm_level, worker_id, worker_name,
 *     geofence_id, geofence_name, device_id, sensor_type, message, ... }
 *
 * 기존 Phase C4 에서 구현된 로직과 동일.
 */
function handleAlarmNew(payload) {
  SenSa.emit('alarm', payload);
}

/**
 * worker.position payload → sensa:workerMove
 *
 * payload 구조 (workers/views.py WorkerLocationViewSet.perform_create):
 *   { worker_id, worker_name, x, y, movement_status, timestamp }
 *
 * 변환 내용:
 *   1. 'worker_name' → 'name' 키 이름 변환 (기존 SenSa 이벤트 규약)
 *   2. 1명짜리 배열 {workers: [w]} 로 래핑
 *      → section_09_map.js 의 SenSa.on('workerMove') 핸들러가
 *        d.workers.forEach 로 처리하도록 되어 있어 배열 형태 필수.
 *        1명이든 N명이든 동일 경로로 처리됨.
 *   3. WORKERS 전역 배열의 해당 엔트리 좌표 동기화
 *      → section_11_workers.js 등 WORKERS 를 직접 읽는 모듈에 반영
 */
function handleWorkerPosition(payload) {
  var w = {
    worker_id: payload.worker_id,
    name:      payload.worker_name,
    x:         payload.x,
    y:         payload.y,
  };

  // WORKERS 전역 배열 동기화
  var entry = window.WORKERS.find(function (it) { return it.worker_id === w.worker_id; });
  if (entry) {
    entry.x = w.x;
    entry.y = w.y;
  } else {
    // 드물게 API 로드 전에 WS 가 먼저 도착할 경우의 보정
    window.WORKERS.push({
      worker_id: w.worker_id,
      name:      w.name,
      department: '',
      x: w.x, y: w.y,
    });
  }

  SenSa.emit('workerMove', { workers: [w] });
}

/**
 * sensor.update payload → sensa:sensorUpdate + sensa:gasData | sensa:powerData
 *
 * payload 구조 (devices/views.py SensorDataView.post):
 *   { device_id, sensor_type, status, values: {...}, timestamp }
 *
 * 변환 내용:
 *   - gas   → sensa:gasData   { device_id, gas: values, status }
 *   - power → sensa:powerData { device_id, power: values, status }
 *   - 공통   → sensa:sensorUpdate { device: SENSOR_DEVICES 매칭, data: {...} }
 *             (section_09_map.js 의 센서 마커 아이콘 갱신용)
 *
 * data 오브젝트는 기존 runSimTick 이 만들던 형식 그대로 복원.
 */
function handleSensorUpdate(payload) {
  var deviceId   = payload.device_id;
  var sensorType = payload.sensor_type;
  var status     = payload.status;
  var values     = payload.values || {};

  var device = window.SENSOR_DEVICES.find(function (d) { return d.device_id === deviceId; });
  if (!device) {
    // DB 에는 있는데 UI 배열엔 없는 센서 → 그릴 수 없음
    return;
  }

  // 타입별 세부 이벤트
  if (sensorType === 'gas') {
    SenSa.emit('gasData', { device_id: deviceId, gas: values, status: status });
  } else if (sensorType === 'power') {
    SenSa.emit('powerData', { device_id: deviceId, power: values, status: status });
  }

  // 공통 sensorUpdate 이벤트 (지도 마커용)
  var data = { status: status, device_id: deviceId, sensor_type: sensorType };
  if (sensorType === 'gas')   data.gas   = values;
  if (sensorType === 'power') data.power = values;

  SenSa.emit('sensorUpdate', { device: device, data: data });
}

// 페이지 로드 직후 연결
connectWebSocket();


// ═══════════════════════════════════════════════════════════
// [E7 삭제] 이전 코드
// ═══════════════════════════════════════════════════════════
//
// 다음 기능들은 FastAPI scheduler 가 전담하므로 제거됨:
//   - gauss, genGas, genPower, moveWorker
//   - postSensorData, checkGeofence
//   - runSimTick, setInterval(runSimTick, 1000)
//   - IMG_W, IMG_H, MG, simTick
//
// 시뮬 로직은 fastapi_generator/generators.py 참조.
// Django POST 는 fastapi_generator/scheduler.py 의 _tick_once 참조.