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
 *   sensa:workersLoaded { workers }        ← [신규] API 로드 완료 시 발행
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
// [변경] WORKERS — 빈 배열로 시작, API에서 동적 로드
// ════════════════════════════════════════
window.WORKERS = [];

/**
 * Worker API에서 작업자 목록을 가져와 WORKERS 배열을 채움
 *
 * 흐름:
 *   1. GET /dashboard/api/worker/  →  DB의 활성 작업자 목록
 *   2. 각 작업자에 시뮬레이션용 필드(x, y, dx, dy) 추가
 *   3. window.WORKERS에 저장
 *   4. 'workersLoaded' 이벤트 발행 → section_09(마커 생성), section_11(도넛 갱신)
 */
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

// ─── 임계치 ───
var GAS_TH = { co: { w: 25, d: 200 }, h2s: { w: 1, d: 5 }, co2: { w: 1000, d: 5000 } };

function classifyGas(g) {
  var worst = 'normal';
  if (g.o2 < 18 || g.o2 > 25) return 'danger';
  if (g.o2 < 19.5 || g.o2 > 23.5) worst = 'caution';
  for (var k in GAS_TH) { if (g[k] >= GAS_TH[k].d) return 'danger'; if (g[k] >= GAS_TH[k].w && worst === 'normal') worst = 'caution'; }
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

function genGas(tick, mode) {
  var g = { co: gauss(12, 3, 0, 500), h2s: gauss(0.3, 0.1, 0, 20), co2: gauss(600, 80, 300, 10000), o2: gauss(20.9, 0.2, 15, 25) };
  if (mode === 'mixed') { if (tick % 30 === 0 && tick) g.co = 30 + Math.random() * 50; if (tick % 60 === 0 && tick) g.h2s = 5 + Math.random() * 7; if (tick % 45 === 0 && tick) g.o2 = 17 + Math.random() * 2; }
  else if (mode === 'danger') { g.co = 200 + Math.random() * 150; g.h2s = 5 + Math.random() * 10; g.co2 = 5000 + Math.random() * 3000; g.o2 = 15 + Math.random() * 3; }
  return { co: +g.co.toFixed(2), h2s: +g.h2s.toFixed(2), co2: +g.co2.toFixed(1), o2: +g.o2.toFixed(1) };
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

setInterval(runSimTick, 1000);

// ─── ⑤ 시스템 시간 ───
function updateClock() {
  var now = new Date().toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  var el1 = document.getElementById('system-time-now'), el2 = document.getElementById('system-time-last');
  if (el1) el1.textContent = now;
  if (el2) el2.textContent = now;
}
setInterval(updateClock, 1000);
updateClock();