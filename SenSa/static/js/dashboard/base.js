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
  if (WORKERS.length === 0) return;
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

    // 서버가 분류한 센서 데이터 → 화면 emit (JS 직접 분류 대신 서버 기준 사용)
    (data.sensors || []).forEach(function (s) {
      var device = SENSOR_DEVICES.find(function (d) { return d.device_id === s.device_id; });
      if (s.sensor_type === 'gas' && s.gas) {
        SenSa.emit('gasData', { device_id: s.device_id, gas: s.gas, status: s.status });
      } else if (s.sensor_type === 'power' && s.power) {
        SenSa.emit('powerData', { device_id: s.device_id, power: s.power, status: s.status });
      }
      if (device) {
        SenSa.emit('sensorUpdate', { device: device, data: s });
      }
    });

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
      var gas = genGas(simTick, window.simMode);
      data = { gas: gas, device_id: device.device_id, sensor_type: 'gas' };
    } else {
      var power = genPower(simTick, window.simMode);
      data = { power: power, device_id: device.device_id, sensor_type: 'power' };
    }
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

// ─── ⑤ 시스템 시간 → header.js로 이동 완료 ───