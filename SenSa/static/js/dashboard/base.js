/**
 * base.js — SenSa 공통 모듈
 *
 * [변경] WORKERS를 하드코딩 → Worker API(/dashboard/api/worker/)에서 동적 로드
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
// 임계치 — 9종 가스
// ════════════════════════════════════════
// 근거:
//   CO  — ACGIH TWA 25ppm, NIOSH Ceiling 200ppm
//   H2S — KOSHA 적정공기 10ppm 미만, NIOSH IDLH 50ppm
//   CO2 — 실내공기질 1,000ppm, TWA 5,000ppm
//   NO2 — 고용노동부고시 TWA 3ppm, STEL 5ppm
//   SO2 — 고용노동부고시 TWA 2ppm, STEL 5ppm
//   O3  — ACGIH TLV-TWA 0.05ppm (경작업), 0.1ppm (중작업)
//   NH3 — ACGIH TWA 25ppm, STEL 35ppm
//   VOC — TVOC 실내공기질 기준 (단일 법적 기준 없음)
//   O2  — 양쪽 임계이므로 classifyGas에서 별도 처리
var GAS_TH = {
  co:  { w: 25,   d: 200  },   // 일산화탄소 (ppm)
  h2s: { w: 10,   d: 50   },   // 황화수소 (ppm)
  co2: { w: 1000, d: 5000 },   // 이산화탄소 (ppm)
  no2: { w: 3,    d: 5    },   // 이산화질소 (ppm)
  so2: { w: 2,    d: 5    },   // 이산화황 (ppm)
  o3:  { w: 0.05, d: 0.1  },   // 오존 (ppm)
  nh3: { w: 25,   d: 50   },   // 암모니아 (ppm)
  voc: { w: 0.5,  d: 2.0  },   // 휘발성유기화합물 (ppm)
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

// ─── 지오펜스 API 호출 ───
var recentAlarmKeys = new Map();
async function checkGeofence(sensorList) {
  if (WORKERS.length === 0) return;
  try {
    var res = await fetch('/dashboard/api/check-geofence/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({
        workers: WORKERS.map(function (w) { return { worker_id: w.worker_id, name: w.name, x: Math.round(w.x), y: Math.round(w.y) }; }),
        sensors: sensorList.filter(function (s) { return s.status !== 'normal'; }).map(function (s) { return { device_id: s.device_id, sensor_type: s.sensor_type, status: s.status, detail: s.detail || '' }; }),
      }),
    });
    if (!res.ok) return;
    var data = await res.json();
    (data.alarms || []).forEach(function (alarm) {
      var key = [alarm.alarm_type, alarm.worker_id || '', alarm.geofence_id || '', alarm.device_id || ''].join('-');
      var now = Date.now(), last = recentAlarmKeys.get(key);
      if (last && now - last < 30000) return;
      recentAlarmKeys.set(key, now);
      SenSa.emit('alarm', alarm);
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
    } else {
      var power = genPower(simTick, window.simMode), status = classifyPower(power);
      data = { power: power, status: status, device_id: device.device_id, sensor_type: 'power', detail: '전류:' + power.current + 'A' };
      SenSa.emit('powerData', { device_id: device.device_id, power: power, status: status });
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