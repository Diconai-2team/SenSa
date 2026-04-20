/**
 * SenSa 공장 관제 시스템 — 관제 지도 JavaScript
 *
 * 섹션 구성:
 *  1. 상수 / 설정
 *  2. 센서 고정 위치
 *  3. 임계치
 *  4. 상태 판별
 *  5. 데이터 생성
 *  6. 작업자 이동
 *  7. Leaflet 초기화
 *  8. 센서 마커
 *  9. 작업자 마커
 * 10. 센서 카드 (사이드바)
 * 11. 알람
 * 12. 지오펜스 판별 API
 * 13. 시뮬레이션 루프
 * 14. 이미지 업로드
 * 15. 지오펜스 그리기
 * 16. 모달
 * 17. 지오펜스 API
 * 18. 레이어 토글
 * 19. 유틸리티
 * 20. Chart.js
 */

// ════════════════════════════════════════
// 1. 상수
// ════════════════════════════════════════
const ZONE_COLORS   = { danger: '#e74c3c', caution: '#f1c40f', restricted: '#9b59b6' };
const SENSOR_COLORS = { gas: '#e74c3c', power: '#f39c12', temperature: '#3498db', motion: '#2ecc71' };
const SENSOR_ICONS  = { gas: '💨', power: '⚡', temperature: '🌡️', motion: '🔊' };
let IMG_W = 1360, IMG_H = 960;
const MARGIN = 40;

// ════════════════════════════════════════
// 2. 센서 고정 위치
// ════════════════════════════════════════
const SENSOR_DEVICES = [
  { device_id: 'sensor_01', device_name: '가스센서 A', sensor_type: 'gas',   location: { x: 200, y: 150 } },
  { device_id: 'sensor_02', device_name: '가스센서 B', sensor_type: 'gas',   location: { x: 500, y: 180 } },
  { device_id: 'sensor_03', device_name: '가스센서 C', sensor_type: 'gas',   location: { x: 350, y: 390 } },
  { device_id: 'power_01',  device_name: '스마트파워 A', sensor_type: 'power', location: { x: 620, y: 100 } },
  { device_id: 'power_02',  device_name: '스마트파워 B', sensor_type: 'power', location: { x: 130, y: 390 } },
];

// ════════════════════════════════════════
// 3. 임계치
// ════════════════════════════════════════
const GAS_THRESHOLDS = {
  co:  { normal: 25, danger: 200 },
  h2s: { normal: 10, danger: 50 },
  co2: { normal: 1000, danger: 5000 },
  o2:  { low: 19.5, high: 23.5 },
  no2: { normal: 0.1, danger: 1.0 },
  so2: { normal: 0.5, danger: 2.0 },
  o3:  { normal: 0.05, danger: 0.1 },
  nh3: { normal: 25, danger: 50 },
  voc: { normal: 0.5, danger: 2.0 },
};
const GAS_NORMAL_CENTER = {
  co: 12, h2s: 0.3, co2: 600, o2: 20.9,
  no2: 0.04, so2: 0.2, o3: 0.02, nh3: 8, voc: 0.15,
};

// ════════════════════════════════════════
// 4. 상태 판별
// ════════════════════════════════════════
function classifyGasStatus(gas) {
  let worst = 'normal';
  for (const [key, value] of Object.entries(gas)) {
    const t = GAS_THRESHOLDS[key];
    if (!t) continue;
    let s;
    if (key === 'o2') {
      s = (value < 18 || value > 25) ? 'danger' : (value < t.low || value > t.high) ? 'caution' : 'normal';
    } else {
      s = value >= t.danger ? 'danger' : value >= t.normal ? 'caution' : 'normal';
    }
    if (s === 'danger') { worst = 'danger'; break; }
    if (s === 'caution' && worst === 'normal') worst = 'caution';
  }
  return worst;
}

function classifyPowerStatus(p) {
  if (p.current >= 30 || p.watt >= 8000) return 'danger';
  if (p.current >= 20 || p.voltage < 200 || p.voltage > 240) return 'caution';
  return 'normal';
}

// ════════════════════════════════════════
// 5. 데이터 생성
// ════════════════════════════════════════
function gauss(c, s, mn, mx) {
  const z = Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
  return Math.min(mx, Math.max(mn, c + z * s));
}

function generateGasValues(tick, mode) {
  const g = {
    co:  gauss(GAS_NORMAL_CENTER.co, 3, 0, 500),
    h2s: gauss(GAS_NORMAL_CENTER.h2s, 0.1, 0, 20),
    co2: gauss(GAS_NORMAL_CENTER.co2, 80, 300, 10000),
    o2:  gauss(GAS_NORMAL_CENTER.o2, 0.2, 15, 25),
    no2: gauss(GAS_NORMAL_CENTER.no2, 0.01, 0, 5),
    so2: gauss(GAS_NORMAL_CENTER.so2, 0.05, 0, 10),
    o3:  gauss(GAS_NORMAL_CENTER.o3, 0.005, 0, 0.5),
    nh3: gauss(GAS_NORMAL_CENTER.nh3, 2, 0, 100),
    voc: gauss(GAS_NORMAL_CENTER.voc, 0.03, 0, 5),
  };
  if (mode === 'mixed') {
    if (tick % 30 === 0 && tick > 0) g.co = 30 + Math.random() * 50;
    if (tick % 60 === 0 && tick > 0) g.h2s = 5 + Math.random() * 7;
    if (tick % 45 === 0 && tick > 0) g.o2 = 17 + Math.random() * 2;
    if (Math.random() < 0.05) g.voc = 0.6 + Math.random() * 1.0;
  } else if (mode === 'danger') {
    g.co = 200 + Math.random() * 150;
    g.h2s = 5 + Math.random() * 10;
    g.co2 = 5000 + Math.random() * 3000;
    g.o2 = 15 + Math.random() * 3;
  }
  return Object.fromEntries(Object.entries(g).map(([k, v]) => [k, +v.toFixed(2)]));
}

function generatePowerValues(tick, mode) {
  let cur = gauss(12, 2, 0, 50), vol = gauss(220, 3, 190, 250);
  if (mode === 'danger') { cur = 30 + Math.random() * 15; vol = 195 + Math.random() * 10; }
  else if (mode === 'mixed' && tick % 50 === 0 && tick > 0) cur = 22 + Math.random() * 8;
  return { current: +cur.toFixed(2), voltage: +vol.toFixed(2), watt: +(cur * vol).toFixed(1) };
}

// ════════════════════════════════════════
// 6. 작업자 이동
// ════════════════════════════════════════
const WORKERS = [
  { worker_id: 'worker_01', name: '작업자 A', x: 300, y: 250, dx: 2.5, dy: 1.5 },
  { worker_id: 'worker_02', name: '작업자 B', x: 500, y: 400, dx: -2.0, dy: 2.0 },
];

function moveWorker(w) {
  w.dx += (Math.random() - 0.5) * 0.6;
  w.dy += (Math.random() - 0.5) * 0.6;
  w.dx = Math.max(-4, Math.min(4, w.dx));
  w.dy = Math.max(-4, Math.min(4, w.dy));
  w.x += w.dx;
  w.y += w.dy;
  if (w.x < MARGIN || w.x > IMG_W - MARGIN) { w.dx = -w.dx; w.x = Math.max(MARGIN, Math.min(IMG_W - MARGIN, w.x)); }
  if (w.y < MARGIN || w.y > IMG_H - MARGIN) { w.dy = -w.dy; w.y = Math.max(MARGIN, Math.min(IMG_H - MARGIN, w.y)); }
}

// ════════════════════════════════════════
// 7. Leaflet
// ════════════════════════════════════════
let map = null, imageOverlay = null;
let geofenceLayerGroup = null, sensorLayerGroup = null, workerLayerGroup = null;

function initMap(W, H) {
  IMG_W = W; IMG_H = H;
  if (map) { map.remove(); map = null; }
  map = L.map('map', { crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, zoomSnap: 0.25 });
  map.fitBounds([[0, 0], [H, W]]);
  geofenceLayerGroup = L.layerGroup().addTo(map);
  sensorLayerGroup = L.layerGroup().addTo(map);
  workerLayerGroup = L.layerGroup().addTo(map);
  map.on('mousemove', function (e) {
    document.getElementById('coord-display').textContent =
      'x: ' + Math.round(e.latlng.lng) + ', y: ' + Math.round(e.latlng.lat);
  });
  map.on('click', function (e) { if (isDrawing) addDrawPoint(e.latlng); });
  loadGeoFences();
  initSensorMarkers();
  initWorkerMarkers();
  var ph = document.getElementById('map-placeholder');
  if (ph) ph.style.display = 'none';
}

// ════════════════════════════════════════
// 8. 센서 마커
// ════════════════════════════════════════
var sensorMarkerCache = {};

function makeSensorIcon(device, status) {
  var color = SENSOR_COLORS[device.sensor_type] || '#aaa';
  var icon = SENSOR_ICONS[device.sensor_type] || '📡';
  var border = status === 'danger' ? '#e74c3c' : status === 'caution' ? '#f1c40f' : color;
  var glow = status === 'danger' ? 'box-shadow:0 0 8px ' + border + ';' : '';
  return L.divIcon({
    className: '',
    html: '<div style="background:' + color + '22;border:2px solid ' + border + ';border-radius:50%;' +
      'width:30px;height:30px;display:flex;align-items:center;justify-content:center;' +
      'font-size:14px;cursor:pointer;' + glow + '">' + icon + '</div>',
    iconSize: [30, 30], iconAnchor: [15, 15],
  });
}

function initSensorMarkers() {
  SENSOR_DEVICES.forEach(function (device) {
    var marker = L.marker([device.location.y, device.location.x], { icon: makeSensorIcon(device, 'normal') });
    marker.device = device;
    marker.currentData = null;
    marker.on('click', function () { openSensorPopup(marker); });
    sensorLayerGroup.addLayer(marker);
    sensorMarkerCache[device.device_id] = marker;
  });
}

function openSensorPopup(marker) {
  var device = marker.device, data = marker.currentData;
  if (!data) return;
  var icon = SENSOR_ICONS[device.sensor_type] || '📡';
  var sc = 'status-' + data.status;
  var rows = '';
  if (data.gas) {
    rows = Object.entries(data.gas).map(function (entry) {
      return '<div class="popup-row"><span class="label">' + entry[0].toUpperCase() +
        '</span><span class="value">' + entry[1] + ' ' + (entry[0] === 'o2' ? '%' : 'ppm') + '</span></div>';
    }).join('');
  } else if (data.power) {
    rows = '<div class="popup-row"><span class="label">전류</span><span class="value">' + data.power.current + ' A</span></div>' +
      '<div class="popup-row"><span class="label">전압</span><span class="value">' + data.power.voltage + ' V</span></div>' +
      '<div class="popup-row"><span class="label">전력</span><span class="value">' + data.power.watt + ' W</span></div>';
  }
  marker.bindPopup(
    '<div class="popup-title">' + icon + ' ' + device.device_name + '</div>' +
    '<div class="popup-row"><span class="label">상태</span><span class="value"><span class="status-badge ' + sc + '">' + data.status + '</span></span></div>' +
    rows +
    '<div class="popup-row"><span class="label">위치</span><span class="value">x:' + device.location.x + ',y:' + device.location.y + '</span></div>',
    { maxWidth: 220 }
  ).openPopup();
}

function updateSensorMarker(device, data) {
  var m = sensorMarkerCache[device.device_id];
  if (!m) return;
  m.setIcon(makeSensorIcon(device, data.status));
  m.currentData = data;
}

// ════════════════════════════════════════
// 9. 작업자 마커
// ════════════════════════════════════════
var workerMarkerCache = {};
var WORKER_ICON = L.divIcon({
  className: '',
  html: '<div style="background:#2ecc7122;border:2px solid #2ecc71;border-radius:50%;' +
    'width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:13px;">👷</div>',
  iconSize: [28, 28], iconAnchor: [14, 14],
});

function initWorkerMarkers() {
  WORKERS.forEach(function (w) {
    var m = L.marker([w.y, w.x], { icon: WORKER_ICON }).bindTooltip(w.name, { permanent: false, direction: 'top' });
    workerLayerGroup.addLayer(m);
    workerMarkerCache[w.worker_id] = m;
  });
}

function updateWorkerMarkers() {
  WORKERS.forEach(function (w) {
    moveWorker(w);
    var m = workerMarkerCache[w.worker_id];
    if (m) m.setLatLng([w.y, w.x]);
  });
}

// ════════════════════════════════════════
// 10. 센서 카드
// ════════════════════════════════════════
function updateSensorCard(device, data) {
  var id = 'card-' + device.device_id;
  var card = document.getElementById(id);
  var icon = SENSOR_ICONS[device.sensor_type] || '📡';
  var sc = 'status-' + data.status;
  var summary = data.gas
    ? 'CO:' + data.gas.co + ' H2S:' + data.gas.h2s + ' O2:' + data.gas.o2 + ' CO2:' + data.gas.co2
    : data.power
      ? data.power.current + 'A/' + data.power.voltage + 'V/' + data.power.watt + 'W'
      : '';
  if (!card) {
    card = document.createElement('div');
    card.id = id;
    card.onclick = function () {
      var m = sensorMarkerCache[device.device_id];
      if (m && map) { map.setView(m.getLatLng(), map.getZoom()); openSensorPopup(m); }
    };
    document.getElementById('sensor-list').appendChild(card);
  }
  card.className = 'sensor-card ' + sc;
  card.innerHTML =
    '<div class="sensor-card-header"><span class="sensor-card-name">' + icon + ' ' + device.device_name +
    '</span><span class="status-badge ' + sc + '">' + data.status + '</span></div>' +
    '<div class="sensor-card-vals">' + summary + '</div>';
}

// ════════════════════════════════════════
// 11. 알람
// ════════════════════════════════════════
var unreadCount = 0;
var EMOJI = { info: 'ℹ️', caution: '⚠️', danger: '🔴', critical: '🚨' };

function addAlarmToPanel(alarm) {
  var list = document.getElementById('alarm-list');
  var empty = list.querySelector('.alarm-empty');
  if (empty) empty.remove();
  var emoji = EMOJI[alarm.alarm_level] || '⚠️';
  var item = document.createElement('div');
  item.className = 'alarm-item unread level-' + alarm.alarm_level;
  item.dataset.id = alarm.alarm_id;
  item.innerHTML = '<div class="alarm-msg">' + emoji + ' ' + alarm.message + '</div>' +
    '<div class="alarm-meta">' + new Date().toLocaleTimeString('ko-KR') + '</div>';
  item.onclick = function () {
    item.classList.remove('unread');
    markAlarmRead(alarm.alarm_id);
    unreadCount = Math.max(0, unreadCount - 1);
    updateUnreadBadge();
  };
  list.insertBefore(item, list.firstChild);
  var all = list.querySelectorAll('.alarm-item');
  if (all.length > 30) all[all.length - 1].remove();
  unreadCount++;
  updateUnreadBadge();
}

function updateUnreadBadge() {
  var b = document.getElementById('alarm-badge');
  b.textContent = unreadCount;
  b.style.display = unreadCount > 0 ? 'inline' : 'none';
}

function showAlarmToast(alarm) {
  var c = document.getElementById('alarm-toast-container');
  var emoji = EMOJI[alarm.alarm_level] || '⚠️';
  var t = document.createElement('div');
  t.className = 'alarm-toast toast-' + alarm.alarm_level;
  t.textContent = emoji + ' ' + alarm.message;
  t.onclick = function () { t.remove(); };
  c.appendChild(t);
  setTimeout(function () { if (t.parentNode) t.remove(); }, 5000);
}

async function markAlarmRead(id) {
  try { await fetch('/dashboard/api/alarm/' + id + '/read/', { method: 'PATCH', headers: { 'X-CSRFToken': getCsrfToken() } }); } catch (e) { }
}

async function readAllAlarms() {
  try {
    await fetch('/dashboard/api/alarm/read_all/', { method: 'PATCH', headers: { 'X-CSRFToken': getCsrfToken() } });
    document.querySelectorAll('.alarm-item.unread').forEach(function (el) { el.classList.remove('unread'); });
    unreadCount = 0;
    updateUnreadBadge();
  } catch (e) { console.error(e); }
}

// ════════════════════════════════════════
// 12. 지오펜스 판별 API
// ════════════════════════════════════════
var recentAlarmKeys = new Map();

function isAlarmDuplicate(key) {
  var now = Date.now(), last = recentAlarmKeys.get(key);
  if (last && now - last < 30000) return true;
  recentAlarmKeys.set(key, now);
  return false;
}

async function checkGeofence(sensorDataList) {
  if (!map) return;
  try {
    var res = await fetch('/dashboard/api/check-geofence/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({
        workers: WORKERS.map(function (w) { return { worker_id: w.worker_id, name: w.name, x: Math.round(w.x), y: Math.round(w.y) }; }),
        sensors: sensorDataList.filter(function (s) { return s.status !== 'normal'; }).map(function (s) {
          return { device_id: s.device_id, sensor_type: s.sensor_type, status: s.status, detail: s.detail || '' };
        }),
      }),
    });
    if (!res.ok) return;
    var data = await res.json();
    data.alarms.forEach(function (alarm) {
      var key = [alarm.alarm_type, alarm.worker_id || '', alarm.geofence_id || '', alarm.device_id || ''].join('-');
      if (isAlarmDuplicate(key)) return;
      addAlarmToPanel(alarm);
      showAlarmToast(alarm);
    });
  } catch (e) { console.warn(e); }
}

// ════════════════════════════════════════
// 13. 시뮬레이션 루프
// ════════════════════════════════════════
var simTick = 0, simMode = 'mixed';

function setScenario(mode) {
  simMode = mode;
  document.querySelectorAll('.scenario-btn').forEach(function (b) { b.classList.remove('active'); });
  document.querySelector('.scenario-btn.' + mode).classList.add('active');
  var labels = { normal: '정상', mixed: '혼합', danger: '위험' };
  document.getElementById('sim-mode-label').textContent = '모드: ' + labels[mode];
}

function runSimTick() {
  if (!map) return;
  var list = [];
  SENSOR_DEVICES.forEach(function (device) {
    var data;
    if (device.sensor_type === 'gas') {
      var gas = generateGasValues(simTick, simMode);
      var status = classifyGasStatus(gas);
      data = { gas: gas, status: status, device_id: device.device_id, sensor_type: device.sensor_type, detail: 'CO:' + gas.co + ',H2S:' + gas.h2s };
      if (device.device_id === 'sensor_01') pushToChart(gas);
    } else {
      var power = generatePowerValues(simTick, simMode);
      var status = classifyPowerStatus(power);
      data = { power: power, status: status, device_id: device.device_id, sensor_type: device.sensor_type, detail: '전류:' + power.current + 'A' };
    }
    updateSensorMarker(device, data);
    updateSensorCard(device, data);
    list.push(data);
  });
  updateWorkerMarkers();
  checkGeofence(list);
  simTick++;
  document.getElementById('sim-tick').textContent = simTick;
}

setInterval(runSimTick, 1000);

// ════════════════════════════════════════
// 14. 이미지 업로드
// ════════════════════════════════════════
function displayMap(url, W, H, name) {
  initMap(W, H);
  if (imageOverlay) imageOverlay.remove();
  imageOverlay = L.imageOverlay(url, [[0, 0], [H, W]]).addTo(map);
  map.fitBounds([[0, 0], [H, W]]);
  document.getElementById('upload-area').classList.add('has-image');
  document.getElementById('upload-label').textContent = name || '지도 로드됨';
  document.querySelector('#upload-area p').textContent = W + ' × ' + H + ' px';
}

document.getElementById('file-input').addEventListener('change', function (e) {
  var file = e.target.files[0];
  if (!file) return;
  var reader = new FileReader();
  reader.onload = function (evt) {
    var img = new Image();
    img.onload = async function () {
      var W = img.naturalWidth, H = img.naturalHeight;
      var fd = new FormData();
      fd.append('image', file);
      fd.append('name', file.name);
      fd.append('width', W);
      fd.append('height', H);
      try {
        var res = await fetch('/dashboard/api/map/', {
          method: 'POST',
          headers: { 'X-CSRFToken': getCsrfToken() },
          credentials: 'include',
          body: fd,
        });
        if (!res.ok) throw new Error(await res.text());
        var d = await res.json();
        displayMap(d.image, d.width, d.height, d.name);
      } catch (err) { alert('업로드 실패: ' + err.message); }
    };
    img.src = evt.target.result;
  };
  reader.readAsDataURL(file);
});

async function loadSavedMap() {
  try {
    var res = await fetch('/dashboard/api/map/current/', { credentials: 'include' });
    if (res.ok) {
      var d = await res.json();
      displayMap(d.image, d.width, d.height, d.name);
    }
  } catch (e) { console.error(e); }
}
document.addEventListener('DOMContentLoaded', loadSavedMap);

// ════════════════════════════════════════
// 15. 지오펜스 그리기
// ════════════════════════════════════════
var isDrawing = false, drawPoints = [], drawMarkers = [], drawPolyline = null;
var pendingPolygon = null, pendingCoords = [];

function toggleDrawMode() {
  if (!map) { alert('먼저 평면도를 업로드하세요.'); return; }
  isDrawing = !isDrawing;
  var btn = document.getElementById('draw-fence-btn');
  var hint = document.getElementById('draw-hint');
  if (isDrawing) {
    btn.textContent = '✔ 그리기 완료';
    btn.classList.add('drawing');
    hint.style.display = 'block';
    map.getContainer().style.cursor = 'crosshair';
  } else {
    if (drawPoints.length >= 3) finishPolygon();
    else { alert('최소 3개 이상 찍어야 합니다.'); resetDraw(); }
  }
}

function addDrawPoint(latlng) {
  drawPoints.push(latlng);
  var m = L.circleMarker(latlng, { radius: 5, color: '#e67e22', fillColor: '#e67e22', fillOpacity: 1, weight: 2 }).addTo(map);
  drawMarkers.push(m);
  if (drawPoints.length >= 3 && map.distance(latlng, drawPoints[0]) < 15) { finishPolygon(); return; }
  if (drawPolyline) drawPolyline.remove();
  drawPolyline = L.polyline(drawPoints, { color: '#e67e22', weight: 2, dashArray: '5,5' }).addTo(map);
}

function finishPolygon() {
  if (drawPoints.length < 3) return;
  if (pendingPolygon) pendingPolygon.remove();
  pendingPolygon = L.polygon(drawPoints, { color: '#e67e22', fillColor: '#e67e22', fillOpacity: 0.25, weight: 2 }).addTo(map);
  pendingCoords = drawPoints.map(function (p) { return [Math.round(p.lng), Math.round(p.lat)]; });
  drawMarkers.forEach(function (m) { m.remove(); });
  drawMarkers = [];
  if (drawPolyline) { drawPolyline.remove(); drawPolyline = null; }
  drawPoints = [];
  isDrawing = false;
  document.getElementById('draw-fence-btn').textContent = '✏️ 지오펜스 그리기';
  document.getElementById('draw-fence-btn').classList.remove('drawing');
  document.getElementById('draw-hint').style.display = 'none';
  map.getContainer().style.cursor = '';
  openModal();
}

function clearCurrentDraw() {
  resetDraw();
  if (pendingPolygon) { pendingPolygon.remove(); pendingPolygon = null; }
  pendingCoords = [];
}

function resetDraw() {
  isDrawing = false;
  drawPoints = [];
  drawMarkers.forEach(function (m) { m.remove(); });
  drawMarkers = [];
  if (drawPolyline) { drawPolyline.remove(); drawPolyline = null; }
  document.getElementById('draw-fence-btn').textContent = '✏️ 지오펜스 그리기';
  document.getElementById('draw-fence-btn').classList.remove('drawing');
  document.getElementById('draw-hint').style.display = 'none';
  if (map) map.getContainer().style.cursor = '';
}

// ════════════════════════════════════════
// 16. 모달
// ════════════════════════════════════════
function openModal() {
  document.getElementById('fence-modal').classList.add('open');
  document.getElementById('fence-name').focus();
}

function closeModal() {
  document.getElementById('fence-modal').classList.remove('open');
  if (pendingPolygon) { pendingPolygon.remove(); pendingPolygon = null; }
  pendingCoords = [];
  document.getElementById('fence-name').value = '';
  document.getElementById('fence-desc').value = '';
}

// ════════════════════════════════════════
// 17. 지오펜스 API
// ════════════════════════════════════════
async function saveGeoFence() {
  var name = document.getElementById('fence-name').value.trim();
  if (!name) { alert('구역명을 입력하세요.'); return; }
  if (pendingCoords.length < 3) { alert('다시 그려주세요.'); return; }
  try {
    var res = await fetch('/dashboard/api/geofence/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({
        name: name,
        zone_type: document.getElementById('fence-type').value,
        risk_level: document.getElementById('fence-risk').value,
        description: document.getElementById('fence-desc').value.trim(),
        polygon: pendingCoords,
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    var d = await res.json();
    document.getElementById('fence-modal').classList.remove('open');
    document.getElementById('fence-name').value = '';
    document.getElementById('fence-desc').value = '';
    pendingCoords = [];
    renderGeoFence(d);
    addToSidebarList(d);
    if (pendingPolygon) { pendingPolygon.remove(); pendingPolygon = null; }
  } catch (err) { alert('저장 실패: ' + err.message); }
}

async function loadGeoFences() {
  try {
    var res = await fetch('/dashboard/api/geofence/');
    var data = await res.json(), list = data.results || data;
    if (!list.length) return;
    document.getElementById('geofence-list').innerHTML = '';
    list.forEach(function (f) { renderGeoFence(f); addToSidebarList(f); });
  } catch (e) { console.error(e); }
}

function renderGeoFence(fence) {
  var latlngs = fence.polygon.map(function (p) { return [p[1], p[0]]; });
  var color = ZONE_COLORS[fence.zone_type] || '#aaa';
  var poly = L.polygon(latlngs, { color: color, fillColor: color, fillOpacity: 0.2, weight: 2 });
  poly.bindPopup(
    '<div class="popup-title">' + fence.name + '</div>' +
    '<div class="popup-row"><span class="label">유형</span><span class="value">' + fence.zone_type + '</span></div>' +
    '<div class="popup-row"><span class="label">위험도</span><span class="value">' + fence.risk_level + '</span></div>' +
    '<div class="popup-row"><span class="label">설명</span><span class="value">' + (fence.description || '–') + '</span></div>'
  );
  poly.fenceId = fence.id;
  geofenceLayerGroup.addLayer(poly);
}

function addToSidebarList(fence) {
  var list = document.getElementById('geofence-list');
  var empty = list.querySelector('p');
  if (empty) empty.remove();
  var color = ZONE_COLORS[fence.zone_type] || '#aaa';
  var item = document.createElement('div');
  item.className = 'geofence-item';
  item.dataset.id = fence.id;
  item.innerHTML =
    '<div class="geofence-dot" style="background:' + color + '"></div>' +
    '<div class="geofence-info"><div class="name">' + fence.name + '</div>' +
    '<div class="meta">' + fence.zone_type + ' · ' + fence.risk_level + '</div></div>' +
    '<button class="delete-btn" onclick="deleteGeoFence(' + fence.id + ')">✕</button>';
  item.addEventListener('click', function (e) {
    if (e.target.classList.contains('delete-btn')) return;
    geofenceLayerGroup.eachLayer(function (l) {
      if (l.fenceId === fence.id) { map.fitBounds(l.getBounds()); l.openPopup(); }
    });
  });
  list.appendChild(item);
}

async function deleteGeoFence(id) {
  if (!confirm('삭제하시겠습니까?')) return;
  try {
    var res = await fetch('/dashboard/api/geofence/' + id + '/', { method: 'DELETE', headers: { 'X-CSRFToken': getCsrfToken() } });
    if (res.status === 204) {
      geofenceLayerGroup.eachLayer(function (l) { if (l.fenceId === id) geofenceLayerGroup.removeLayer(l); });
      var item = document.querySelector('.geofence-item[data-id="' + id + '"]');
      if (item) item.remove();
      if (!document.getElementById('geofence-list').children.length)
        document.getElementById('geofence-list').innerHTML = '<p style="font-size:10px;color:#3a3f55;text-align:center;padding:10px;">지오펜스가 없습니다.</p>';
    }
  } catch (err) { alert('삭제 실패: ' + err.message); }
}

// ════════════════════════════════════════
// 18. 레이어 토글
// ════════════════════════════════════════
document.getElementById('layer-geofence').addEventListener('change', function () {
  if (!map) return;
  this.checked ? map.addLayer(geofenceLayerGroup) : map.removeLayer(geofenceLayerGroup);
});
document.getElementById('layer-sensor').addEventListener('change', function () {
  if (!map) return;
  this.checked ? map.addLayer(sensorLayerGroup) : map.removeLayer(sensorLayerGroup);
});
document.getElementById('layer-worker').addEventListener('change', function () {
  if (!map) return;
  this.checked ? map.addLayer(workerLayerGroup) : map.removeLayer(workerLayerGroup);
});

// ════════════════════════════════════════
// 19. 유틸리티
// ════════════════════════════════════════
function getCsrfToken() {
  var c = document.cookie.split(';').find(function (c) { return c.trim().startsWith('csrftoken='); });
  return c ? c.split('=')[1] : '';
}

(function () {
  var ph = document.createElement('div');
  ph.id = 'map-placeholder';
  ph.innerHTML = '<div class="icon">📐</div><p>왼쪽에서 공장 평면도 이미지를 업로드하면<br>이 화면에 지도가 표시됩니다.</p>';
  document.getElementById('map-container').appendChild(ph);
})();

// ════════════════════════════════════════
// 20. Chart.js
// ════════════════════════════════════════
var CHART_MAX_POINTS = 20;

function makeChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: { display: false },
      tooltip: {
        mode: 'index', intersect: false,
        backgroundColor: '#1a1d27', titleColor: '#5a6080',
        bodyColor: '#e0e0e0', borderColor: '#2a2d3a', borderWidth: 1,
      },
    },
    scales: {
      x: { ticks: { color: '#406080', font: { size: 9 }, maxTicksLimit: 6 }, grid: { color: '#1a2040' } },
      y: { ticks: { color: '#406080', font: { size: 9 } }, grid: { color: '#1a2040' } },
    },
  };
}

var chartCO = new Chart(document.getElementById('chart-co'), {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      { label: 'CO', data: [], borderColor: '#00c8ff', backgroundColor: 'rgba(0,200,255,0.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 2 },
      { label: '주의(35)', data: [], borderColor: '#ffcc00', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
      { label: '위험(70)', data: [], borderColor: '#ff4444', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
    ],
  },
  options: makeChartOptions(),
});

var chartH2S = new Chart(document.getElementById('chart-h2s'), {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      { label: 'H2S', data: [], borderColor: '#00e676', backgroundColor: 'rgba(0,230,118,0.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 2 },
      { label: '주의(15)', data: [], borderColor: '#ffcc00', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
      { label: '위험(35)', data: [], borderColor: '#ff4444', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
    ],
  },
  options: makeChartOptions(),
});

var chartCO2 = new Chart(document.getElementById('chart-co2'), {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      { label: 'CO₂', data: [], borderColor: '#ffaa00', backgroundColor: 'rgba(255,170,0,0.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 2 },
      { label: '주의(600)', data: [], borderColor: '#ffcc00', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
      { label: '위험(800)', data: [], borderColor: '#ff4444', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
    ],
  },
  options: makeChartOptions(),
});

var chartBuffer = { labels: [], co: [], h2s: [], co2: [] };

function pushToChart(gas) {
  var now = new Date().toLocaleTimeString('ko-KR');

  chartBuffer.labels.push(now);
  chartBuffer.co.push(gas.co);
  chartBuffer.h2s.push(gas.h2s);
  chartBuffer.co2.push(gas.co2);

  if (chartBuffer.labels.length > CHART_MAX_POINTS) {
    chartBuffer.labels.shift();
    chartBuffer.co.shift();
    chartBuffer.h2s.shift();
    chartBuffer.co2.shift();
  }

  var len = chartBuffer.labels.length;

  chartCO.data.labels = chartBuffer.labels;
  chartCO.data.datasets[0].data = chartBuffer.co;
  chartCO.data.datasets[1].data = Array(len).fill(25);
  chartCO.data.datasets[2].data = Array(len).fill(200);
  chartCO.update();

  chartH2S.data.labels = chartBuffer.labels;
  chartH2S.data.datasets[0].data = chartBuffer.h2s;
  chartH2S.data.datasets[1].data = Array(len).fill(10);
  chartH2S.data.datasets[2].data = Array(len).fill(50);
  chartH2S.update();

  chartCO2.data.labels = chartBuffer.labels;
  chartCO2.data.datasets[0].data = chartBuffer.co2;
  chartCO2.data.datasets[1].data = Array(len).fill(1000);
  chartCO2.data.datasets[2].data = Array(len).fill(5000);
  chartCO2.update();
}
