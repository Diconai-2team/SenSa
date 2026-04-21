/**
 * base.js — SenSa 공통 모듈
 *
 * 역할: 이벤트 버스, 센서/작업자 정의, 데이터 생성, 시뮬레이션 루프
 * 각 섹션 JS는 SenSa.on() 으로 이벤트를 구독하여 독립 동작
 *
 * 이벤트 목록:
 *   sensa:gasData      { device_id, gas, status }
 *   sensa:powerData    { device_id, power, status }
 *   sensa:sensorUpdate { device, data }          → section_09 마커 갱신
 *   sensa:workerMove   { workers }               → section_09 마커 이동
 *   sensa:alarm        { alarm_level, message, ...}  → section_10 알람 표시
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

window.WORKERS = [
  { worker_id: 'worker_01', name: '작업자 A', x: 300, y: 250, dx: 2.5, dy: 1.5 },
  { worker_id: 'worker_02', name: '작업자 B', x: 500, y: 400, dx: -2.0, dy: 2.0 },
];

window.ZONE_COLORS   = { danger: '#e74c3c', caution: '#f1c40f', restricted: '#9b59b6' };
window.SENSOR_COLORS  = { gas: '#e74c3c', power: '#f39c12', temperature: '#3498db', motion: '#2ecc71' };
window.SENSOR_ICONS   = { gas: '💨', power: '⚡', temperature: '🌡️', motion: '🔊' };

// ─── 임계치 — 9종 가스 (실제 센서 스펙 기준) ───
var GAS_TH = {
  co:  { w: 25,   d: 200  },
  h2s: { w: 10,   d: 15   },
  co2: { w: 1000, d: 5000 },
  no2: { w: 3,    d: 5    },
  so2: { w: 2,    d: 5    },
  o3:  { w: 0.06, d: 0.12 },
  nh3: { w: 25,   d: 35   },
  voc: { w: 0.5,  d: 1.0  },
};

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
  var g = {
    co:  gauss(12,   3,    0,   500),
    h2s: gauss(5,    2,    0,   20),
    co2: gauss(600,  80,   300, 10000),
    o2:  gauss(20.9, 0.2,  15,  25),
    no2: gauss(1.5,  0.5,  0,   10),
    so2: gauss(1.0,  0.3,  0,   10),
    o3:  gauss(0.03, 0.01, 0,   0.5),
    nh3: gauss(10,   3,    0,   100),
    voc: gauss(0.3,  0.1,  0,   5),
  };
  if (mode === 'mixed') {
    if (tick % 30 === 0 && tick) g.co  = 30 + Math.random() * 50;
    if (tick % 60 === 0 && tick) g.h2s = 11 + Math.random() * 5;
    if (tick % 45 === 0 && tick) g.o2  = 17 + Math.random() * 2;
  } else if (mode === 'danger') {
    g.co  = 200 + Math.random() * 150;
    g.h2s = 15  + Math.random() * 10;
    g.co2 = 5000 + Math.random() * 3000;
    g.o2  = 15  + Math.random() * 2;
    g.no2 = 5   + Math.random() * 3;
    g.nh3 = 35  + Math.random() * 10;
  }
  return {
    co:  +g.co.toFixed(2),  h2s: +g.h2s.toFixed(2),
    co2: +g.co2.toFixed(1), o2:  +g.o2.toFixed(1),
    no2: +g.no2.toFixed(3), so2: +g.so2.toFixed(2),
    o3:  +g.o3.toFixed(3),  nh3: +g.nh3.toFixed(1),
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
  try {
    var res = await fetch('/dashboard/api/check-geofence/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({
        workers: WORKERS.map(function (w) { return { worker_id: w.worker_id, name: w.name, x: Math.round(w.x), y: Math.round(w.y) }; }),
        sensors: sensorList.map(function (s) { return { device_id: s.device_id, sensor_type: s.sensor_type, gas: s.gas || null, power: s.power || null }; }),
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

  WORKERS.forEach(function (w) { moveWorker(w); });
  SenSa.emit('workerMove', { workers: WORKERS });

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
