/**
 * base.js — SenSa 공통 모듈
 *
 * [변경] WORKERS를 하드코딩 → Worker API(/dashboard/api/worker/)에서 동적 로드
 * [변경] Phase C4 — WebSocket 연결 추가 (alarm.new 수신)
 * [변경] 팀원 머지 — DB 에 Worker 가 없을 때 DEMO_WORKERS 폴백
 * [변경] Gas 병합 —
 *         1) GAS_TH 값을 section_12_13_gas.js 의 TH 와 일치시킴 (임계치 단일 출처)
 *         2) postSensorData() 추가 — 9종 가스를 Django 에 POST 해서 DB 시계열 축적
 *            (Phase E7 에서 FastAPI 가 역할 인계 시 제거 예정)
 * [변경] Power 병합 —
 *         3) postSensorData() 시그니처 확장: (device, gas, power)
 *            → power 센서의 current/voltage/watt 도 DB 시계열 축적
 *            → 서버 alerts.services.classify_power 의 24h 중앙값 동적 판정이
 *              이 POST 경로로 쌓인 데이터를 읽음.
 *
 * 이벤트 목록:
 *   sensa:gasData       { device_id, gas, status }
 *   sensa:powerData     { device_id, power, status }
 *   sensa:sensorUpdate  { device, data }
 *   sensa:workerMove    { workers }
 *   sensa:workersLoaded { workers }
 *   sensa:alarm         { alarm_level, message, ... }
 */

// ─── 이벤트 버스 ───
window.SenSa = {
  emit: function (name, data) {
    document.dispatchEvent(new CustomEvent('sensa:' + name, { detail: data }));
  },
  on: function (name, fn) {
    document.addEventListener('sensa:' + name, function (e) { fn(e.detail); });
  },
};

// ════════════════════════════════════════
// WebSocket 연결 — 실시간 수신 채널
// ════════════════════════════════════════
// Phase C: alarm.new 수신
// Phase D: worker.position, sensor.update 수신 예정
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

    // 메시지 타입별 디스패치
    if (msg.type === 'alarm.new') {
      SenSa.emit('alarm', msg.payload);
    } else if (msg.type === 'connection.established') {
      console.log('[WS] auth ok, groups:', msg.payload || msg.groups);
    }
    // 그 외 타입은 조용히 무시 (Phase D 에서 추가)
  };

  ws.onclose = function (e) {
    console.warn('[WS] closed:', e.code, e.reason);
    // Phase F 에서 재접속 로직 추가 예정
  };

  ws.onerror = function (e) {
    console.error('[WS] error:', e);
  };
}

connectWebSocket();


// ─── CSRF 유틸 ───
function getCsrfToken() {
  var c = document.cookie.split(';').find(function (c) { return c.trim().startsWith('csrftoken='); });
  return c ? c.split('=')[1] : '';
}
window.getCsrfToken = getCsrfToken;

// ─── 센서 장비 정의 ───
window.SENSOR_DEVICES = [
  { device_id: 'sensor_01', device_name: '가스센서 A', sensor_type: 'gas',   location: { x: 200, y: 150 } },
  { device_id: 'sensor_02', device_name: '가스센서 B', sensor_type: 'gas',   location: { x: 500, y: 180 } },
  { device_id: 'sensor_03', device_name: '가스센서 C', sensor_type: 'gas',   location: { x: 350, y: 390 } },
  { device_id: 'power_01',  device_name: '스마트파워 A', sensor_type: 'power', location: { x: 620, y: 100 } },
  { device_id: 'power_02',  device_name: '스마트파워 B', sensor_type: 'power', location: { x: 130, y: 390 } },
];

// ════════════════════════════════════════
// WORKERS — 빈 배열로 시작, API에서 동적 로드
// ════════════════════════════════════════
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
        x: 200 + (index % 3) * 200 + Math.random() * 50,
        y: 200 + Math.floor(index / 3) * 150 + Math.random() * 50,
        dx: (Math.random() - 0.5) * 4,
        dy: (Math.random() - 0.5) * 4,
      };
    });

    console.log('Worker ' + window.WORKERS.length + '명 로드 완료:',
      window.WORKERS.map(function(w) { return w.name; }).join(', '));

    SenSa.emit('workersLoaded', { workers: window.WORKERS });
  } catch (e) {
    console.error('Worker 로드 에러:', e);
  }
}

loadWorkersFromAPI();

// ─── 색상/아이콘 상수 ───
window.ZONE_COLORS   = { danger: '#e74c3c', caution: '#f1c40f', restricted: '#9b59b6' };
window.SENSOR_COLORS  = { gas: '#e74c3c', power: '#f39c12', temperature: '#3498db', motion: '#2ecc71' };
window.SENSOR_ICONS   = { gas: '💨', power: '⚡', temperature: '🌡️', motion: '🔊' };

// ════════════════════════════════════════
// 임계치 — 9종 가스 (Gas 전담 팀원 공식 기준)
// ════════════════════════════════════════
// 출처: section_12_13_gas.js 의 TH
// UI 뱃지(section_12_13_gas.js) + 서버 알람(alerts/services.GAS_THRESHOLDS) +
// 이 파일이 모두 같은 값을 써야 상태 표시 ↔ 알람이 일치함.
//
// 철학: danger = IDLH 수준 (즉시 대피 필요), caution = STEL 수준 (단기 노출 허용)
var GAS_TH = {
  co:  { w: 25,   d: 200  },   // ACGIH TWA / NIOSH Ceiling
  h2s: { w: 10,   d: 50   },   // KOSHA 적정공기 / IDLH
  co2: { w: 1000, d: 5000 },   // 실내공기질 / TWA
  no2: { w: 3,    d: 5    },   // 고용노동부 TWA / STEL
  so2: { w: 2,    d: 5    },   // 고용노동부 TWA / STEL
  o3:  { w: 0.05, d: 0.1  },   // ACGIH TLV (light / heavy work)
  nh3: { w: 25,   d: 50   },   // ACGIH TWA / 고노출 기준
  voc: { w: 0.5,  d: 2.0  },   // TVOC 실내기준
};

// ════════════════════════════════════════
// classifyGas — O2 구간형 + 나머지 8종 단방향
// ════════════════════════════════════════
// 근거: 산업안전보건기준에 관한 규칙 제618조
//   적정공기: O2 18% 이상 ~ 23.5% 미만
//   산소결핍: O2 18% 미만
//   O2 16% 이하: 두통·구토·호흡증가 등 자각증상 (KOSHA)
//   O2 10% 이하: 의식상실·경련·사망 위험 (KOSHA)
function classifyGas(g) {
  var worst = 'normal';

  // O2: 양쪽 임계 (저산소 = 질식, 고산소 = 화재 위험)
  //   위험: 16% 미만(자각증상+의식상실 구간) 또는 23.5% 이상(산소과잉, 화재·폭발)
  //   주의: 16~18%(산소결핍 접근) 또는 21.5~23.5%(과잉 접근)
  //   정상: 18~21.5%(정상 대기 20.9% 중심)
  if (g.o2 !== undefined) {
    if (g.o2 < 16 || g.o2 >= 23.5) return 'danger';
    if (g.o2 < 18 || g.o2 > 21.5) worst = 'caution';
  }

  // 나머지 8종: 단방향 (높을수록 위험)
  for (var k in GAS_TH) {
    if (g[k] === undefined) continue;
    if (g[k] >= GAS_TH[k].d) return 'danger';
    if (g[k] >= GAS_TH[k].w && worst === 'normal') worst = 'caution';
  }
  return worst;
}


// classifyPower — 클라 사이드 간이 판정
// 서버 alerts.services.classify_power 가 24h 중앙값 기반 동적 판정을 하므로
// 클라는 UI 표시용 간이 판정만 수행. 최종 권위는 서버 응답 / WS sensor.update.
function classifyPower(p) {
  if (p.current >= 30 || p.watt >= 8000) return 'danger';
  if (p.current >= 20 || p.voltage < 200 || p.voltage > 240) return 'caution';
  return 'normal';
}
window.classifyGas = classifyGas;
window.classifyPower = classifyPower;

// ─── 데이터 생성 ───
function gauss(c, s, mn, mx) {
  var z = Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
  return Math.min(mx, Math.max(mn, c + z * s));
}

// ════════════════════════════════════════
// genGas — 9종 가스 시뮬레이션 데이터 생성
// ════════════════════════════════════════
function genGas(tick, mode) {
  var g = {
    co:  gauss(12,    3,     0, 500),
    h2s: gauss(2,     1,     0, 100),     // 정상 중심값 2ppm (w:10 대비 안전)
    co2: gauss(600,   80,    300, 10000),
    o2:  gauss(20.9,  0.2,   10, 25),
    no2: gauss(0.04,  0.01,  0, 5),
    so2: gauss(0.2,   0.05,  0, 10),
    o3:  gauss(0.02,  0.005, 0, 0.5),
    nh3: gauss(8,     2,     0, 100),
    voc: gauss(0.15,  0.03,  0, 5),
  };

  if (mode === 'mixed') {
    if (tick % 30 === 0 && tick) g.co = 30 + Math.random() * 50;
    if (tick % 60 === 0 && tick) g.h2s = 12 + Math.random() * 15;   // 12~27ppm → w:10 주의 구간
    if (tick % 45 === 0 && tick) g.o2 = 16 + Math.random() * 2;     // 16~18% → 주의 구간
    if (Math.random() < 0.05) g.voc = 0.6 + Math.random() * 1.0;
    if (tick % 90 === 0 && tick) g.nh3 = 30 + Math.random() * 25;
  } else if (mode === 'danger') {
    g.co  = 200 + Math.random() * 150;
    g.h2s = 50 + Math.random() * 30;     // 50~80ppm → d:50 위험 구간
    g.co2 = 5000 + Math.random() * 3000;
    g.o2  = 12 + Math.random() * 4;      // 12~16% → <16 위험 구간
    g.no2 = 1.0 + Math.random() * 2;
    g.voc = 2.0 + Math.random() * 2;
  }

  return {
    co:  +g.co.toFixed(2),
    h2s: +g.h2s.toFixed(2),
    co2: +g.co2.toFixed(1),
    o2:  +g.o2.toFixed(1),
    no2: +g.no2.toFixed(3),
    so2: +g.so2.toFixed(2),
    o3:  +g.o3.toFixed(3),
    nh3: +g.nh3.toFixed(1),
    voc: +g.voc.toFixed(2),
  };
}

function genPower(tick, mode) {
  var cur = gauss(12, 2, 0, 50), vol = gauss(220, 3, 190, 250);
  if (mode === 'danger') { cur = 30 + Math.random() * 15; vol = 195 + Math.random() * 10; }
  else if (mode === 'mixed' && tick % 50 === 0 && tick) cur = 22 + Math.random() * 8;
  return { current: +cur.toFixed(2), voltage: +vol.toFixed(2), watt: +(cur * vol).toFixed(1) };
}

// ─── 작업자 이동 ───
var IMG_W = 1360, IMG_H = 960, MG = 40;
function moveWorker(w) {
  w.dx += (Math.random() - 0.5) * 0.6; w.dy += (Math.random() - 0.5) * 0.6;
  w.dx = Math.max(-4, Math.min(4, w.dx)); w.dy = Math.max(-4, Math.min(4, w.dy));
  w.x += w.dx; w.y += w.dy;
  if (w.x < MG || w.x > IMG_W - MG) { w.dx = -w.dx; w.x = Math.max(MG, Math.min(IMG_W - MG, w.x)); }
  if (w.y < MG || w.y > IMG_H - MG) { w.dy = -w.dy; w.y = Math.max(MG, Math.min(IMG_H - MG, w.y)); }
}
window.updateMapBounds = function (W, H) { IMG_W = W; IMG_H = H; };

// ════════════════════════════════════════
// postSensorData — 센서 데이터를 Django 로 POST (DB 시계열 축적)
// ════════════════════════════════════════
// 서버(devices/views.py SensorDataView.post)가:
//   1) 센서 타입별 필드 저장 (gas 9종 / power 3종)
//   2) 서버 기준으로 status 판정 (alerts.services.classify_*)
//   3) publish_sensor_update 로 WS 브로드캐스트
// 수행.
//
// 특히 power 의 경우, 24시간 중앙값 기반 동적 판정이 돌려면
// DB 시계열이 쌓여 있어야 함. 이 함수가 그 데이터 공급원.
//
// Phase E7 에서 FastAPI scheduler 가 역할 인계 예정 — 그때 이 함수는 제거.
async function postSensorData(device, gas, power) {
  var body = { device_id: device.device_id, sensor_type: device.sensor_type };

  if (device.sensor_type === 'gas' && gas) {
    body.co  = gas.co;  body.h2s = gas.h2s; body.co2 = gas.co2; body.o2  = gas.o2;
    body.no2 = gas.no2; body.so2 = gas.so2; body.o3  = gas.o3;
    body.nh3 = gas.nh3; body.voc = gas.voc;
  } else if (device.sensor_type === 'power' && power) {
    body.current = power.current;
    body.voltage = power.voltage;
    body.watt    = power.watt;
  } else {
    return;  // 알려지지 않은 타입은 전송 스킵
  }

  try {
    await fetch('/dashboard/api/sensor-data/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify(body),
    });
    // 서버 응답 status 는 WS sensor.update 로 다시 돌아옴 — 여기서는 사용 안 함
  } catch (e) {
    // 네트워크 순단은 조용히 무시 — 다음 틱에 재시도
  }
}

// ─── 지오펜스 API 호출 ───
async function checkGeofence(sensorList) {
  if (WORKERS.length === 0) return;
  try {
    // POST는 그대로 — 서버가 알람 생성 + DB 저장 + WS push를 수행
    // 응답 body는 이제 무시 (알람은 WS 로 받음 - Phase C4)
    await fetch('/dashboard/api/check-geofence/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({
        workers: WORKERS.map(function (w) {
          return {
            worker_id: w.worker_id, name: w.name, x: Math.round(w.x), y: Math.round(w.y) }; }),
        sensors: sensorList.map(function (s) {
          // SENSOR_DEVICES 에서 좌표 찾기
          var device = SENSOR_DEVICES.find(function(d) { return d.device_id === s.device_id; });
          return {
            device_id: s.device_id,
            sensor_type: s.sensor_type,
            status: s.status,
            detail: s.detail || '',
            x: device ? device.location.x : 0,
            y: device ? device.location.y : 0,
          };
        }),
      }),
    });
  } catch (e) {}
}

// ─── 시뮬레이션 루프 ───
var simTick = 0;
window.simMode = 'mixed';

window.setScenario = function (mode) {
  window.simMode = mode;
  document.querySelectorAll('.scenario-btn').forEach(function (b) { b.classList.remove('active'); });
  var el = document.querySelector('.scenario-btn.' + mode);
  if (el) el.classList.add('active');
};

function runSimTick() {
  var list = [];
  SENSOR_DEVICES.forEach(function (device) {
    var data;
    if (device.sensor_type === 'gas') {
      var gas = genGas(simTick, window.simMode), status = classifyGas(gas);
      data = { gas: gas, status: status, device_id: device.device_id, sensor_type: 'gas', detail: 'CO:' + gas.co };
      SenSa.emit('gasData', { device_id: device.device_id, gas: gas, status: status });

      // ★ 9종 가스 DB 저장 — Django 가 status 재판정 + WS 브로드캐스트
      postSensorData(device, gas, null);

    } else if (device.sensor_type === 'power') {
      var power = genPower(simTick, window.simMode), status = classifyPower(power);
      data = { power: power, status: status, device_id: device.device_id, sensor_type: 'power', detail: '전류:' + power.current + 'A' };
      SenSa.emit('powerData', { device_id: device.device_id, power: power, status: status });

      // ★ 전력 3종 DB 저장 — 24h 중앙값 동적 판정의 데이터 공급원
      postSensorData(device, null, power);
    }
    SenSa.emit('sensorUpdate', { device: device, data: data });
    list.push(data);
  });

  if (WORKERS.length > 0) {
    WORKERS.forEach(function (w) { moveWorker(w); });
    SenSa.emit('workerMove', { workers: WORKERS });
  }

  checkGeofence(list);
  simTick++;
  var el = document.getElementById('sim-tick');
  if (el) el.textContent = simTick;
}

// ─── WebSocket 실시간 연결 ───
var wsSimInterval = null;
var wsReconnectTimer = null;
var wsConnected = false;

function startSimFallback() {
  if (!wsSimInterval) {
    console.log('[SenSa] WebSocket 없음 → 시뮬레이션 모드');
    wsSimInterval = setInterval(runSimTick, 1000);
  }
}

function stopSimFallback() {
  if (wsSimInterval) {
    clearInterval(wsSimInterval);
    wsSimInterval = null;
  }
}

function updateWsStatus(status) {
  var el = document.getElementById('ws-status');
  if (!el) return;
  var labels = {
    connecting:   '🟡 연결 중...',
    connected:    '🟢 실시간 연결됨',
    disconnected: '🔴 연결 끊김',
    reconnecting: '🟠 재연결 시도 중...',
  };
  el.textContent = labels[status] || status;
}

function connectWebSocket() {
  updateWsStatus('connecting');
  var ws = new WebSocket('ws://127.0.0.1:8001/ws/sensors/');

  ws.onopen = function () {
    console.log('[SenSa] WebSocket 연결됨');
    wsConnected = true;
    stopSimFallback();
    updateWsStatus('connected');
    if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
  };

  ws.onmessage = function (event) {
    try {
      var msg = JSON.parse(event.data);

      if (msg.type === 'update') {
        (msg.sensors || []).forEach(function (sensor) {
          if (sensor.sensor_type === 'gas') {
            SenSa.emit('gasData', { device_id: sensor.device_id, gas: sensor.gas, status: sensor.status });
          } else {
            SenSa.emit('powerData', { device_id: sensor.device_id, power: sensor.power, status: sensor.status });
          }
          var device = SENSOR_DEVICES.find(function (d) { return d.device_id === sensor.device_id; });
          if (device) SenSa.emit('sensorUpdate', { device: device, data: sensor });
        });

        if (msg.workers && msg.workers.length > 0) {
          msg.workers.forEach(function (wData) {
            var w = WORKERS.find(function (w) { return w.worker_id === wData.worker_id; });
            if (w) { w.x = wData.x; w.y = wData.y; }
          });
          SenSa.emit('workerMove', { workers: WORKERS });
        }

        simTick++;
        var el = document.getElementById('sim-tick');
        if (el) el.textContent = simTick;
      }

      if (msg.type === 'alert') {
        console.log('[SenSa] 알람 수신:', msg);
        SenSa.emit('alarm', msg);
      }

    } catch (e) {
      console.error('[SenSa] 메시지 파싱 오류:', e);
    }
  };

  ws.onclose = function () {
    console.log('[SenSa] WebSocket 연결 종료 → 재연결 시도');
    wsConnected = false;
    updateWsStatus('reconnecting');
    startSimFallback();
    wsReconnectTimer = setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = function (err) {
    console.error('[SenSa] WebSocket 오류:', err);
    updateWsStatus('disconnected');
  };
}

connectWebSocket();
setTimeout(function () { if (!wsConnected) startSimFallback(); }, 3000);

// ─── ⑤ 시스템 시간 → header.js로 이동 완료 ───