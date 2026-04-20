/**
 * section_09_map.js — ⑨ 탭 + Leaflet 지도 + 지오펜스 + 마커 + 업로드
 *
 * [변경] 작업자 마커를 workersLoaded 이벤트 수신 후 동적 생성
 *
 * 구독 이벤트:
 *   sensa:sensorUpdate  → 센서 마커 갱신
 *   sensa:workerMove    → 작업자 마커 이동
 *   sensa:workersLoaded → 작업자 마커 최초 생성  ← [신규]
 *   sensa:alarm         → 토스트 표시
 */

// ─── 탭 전환 ───
document.querySelectorAll('.tab-btn').forEach(function (btn) {
  btn.addEventListener('click', function () {
    document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
  });
});

// ─── Leaflet 초기화 ───
var map = null, imageOverlay = null;
var geofenceLayerGroup = null, sensorLayerGroup = null, workerLayerGroup = null;

function initMap(W, H) {
  window.updateMapBounds(W, H);
  if (map) { map.remove(); map = null; }
  map = L.map('map', { crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, zoomSnap: 0.25 });
  map.fitBounds([[0, 0], [H, W]]);
  geofenceLayerGroup = L.layerGroup().addTo(map);
  sensorLayerGroup = L.layerGroup().addTo(map);
  workerLayerGroup = L.layerGroup().addTo(map);
  map.on('mousemove', function (e) { document.getElementById('coord-display').textContent = 'x: ' + Math.round(e.latlng.lng) + ', y: ' + Math.round(e.latlng.lat); });
  map.on('click', function (e) { if (isDrawing) addDrawPoint(e.latlng); });
  loadGeoFences();
  initSensorMarkers();

  // [변경] WORKERS가 이미 로드됐으면 마커 생성, 아니면 이벤트로 대기
  if (WORKERS.length > 0) {
    initWorkerMarkers();
  }

  var ph = document.getElementById('map-placeholder'); if (ph) ph.style.display = 'none';
  var uo = document.getElementById('upload-overlay'); if (uo) uo.style.display = 'none';
}

// ─── 센서 마커 ───
var sensorMarkerCache = {};

function makeSensorIcon(device, status) {
  var color = SENSOR_COLORS[device.sensor_type] || '#aaa', icon = SENSOR_ICONS[device.sensor_type] || '📡';
  var border = status === 'danger' ? '#e74c3c' : status === 'caution' ? '#f1c40f' : color;
  var glow = status === 'danger' ? 'box-shadow:0 0 8px ' + border + ';' : '';
  return L.divIcon({ className: '', html: '<div style="background:' + color + '22;border:2px solid ' + border + ';border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-size:14px;' + glow + '">' + icon + '</div>', iconSize: [30, 30], iconAnchor: [15, 15] });
}

function initSensorMarkers() {
  SENSOR_DEVICES.forEach(function (d) {
    var m = L.marker([d.location.y, d.location.x], { icon: makeSensorIcon(d, 'normal') });
    m.device = d; m.currentData = null;
    m.on('click', function () {
      if (!m.currentData) return;
      var data = m.currentData, sc = 'status-' + data.status, rows = '';
      if (data.gas) rows = Object.entries(data.gas).map(function (e) { return '<div class="popup-row"><span class="label">' + e[0].toUpperCase() + '</span><span class="value">' + e[1] + (e[0] === 'o2' ? ' %' : ' ppm') + '</span></div>'; }).join('');
      else if (data.power) rows = '<div class="popup-row"><span class="label">전류</span><span class="value">' + data.power.current + ' A</span></div><div class="popup-row"><span class="label">전압</span><span class="value">' + data.power.voltage + ' V</span></div><div class="popup-row"><span class="label">전력</span><span class="value">' + data.power.watt + ' W</span></div>';
      m.bindPopup('<div class="popup-title">' + SENSOR_ICONS[d.sensor_type] + ' ' + d.device_name + '</div><div class="popup-row"><span class="label">상태</span><span class="value"><span class="status-badge ' + sc + '">' + data.status + '</span></span></div>' + rows, { maxWidth: 220 }).openPopup();
    });
    sensorLayerGroup.addLayer(m); sensorMarkerCache[d.device_id] = m;
  });
}

SenSa.on('sensorUpdate', function (d) {
  var m = sensorMarkerCache[d.device.device_id]; if (!m) return;
  m.setIcon(makeSensorIcon(d.device, d.data.status)); m.currentData = d.data;
});

// ─── 작업자 마커 ───
var workerMarkerCache = {};
var WORKER_ICON = L.divIcon({ className: '', html: '<div style="background:#2ecc7122;border:2px solid #2ecc71;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:13px;">👷</div>', iconSize: [28, 28], iconAnchor: [14, 14] });

/**
 * [변경] WORKERS 배열 기반으로 마커 생성
 * 하드코딩이 아니라 API에서 로드된 WORKERS를 사용
 */
function initWorkerMarkers() {
  // 기존 마커 전부 제거 (재호출 대비)
  workerLayerGroup.clearLayers();
  workerMarkerCache = {};

  WORKERS.forEach(function (w) {
    var m = L.marker([w.y, w.x], { icon: WORKER_ICON })
      .bindTooltip(w.name + (w.department ? ' (' + w.department + ')' : ''), { permanent: false, direction: 'top' });
    workerLayerGroup.addLayer(m);
    workerMarkerCache[w.worker_id] = m;
  });

  console.log('작업자 마커 ' + WORKERS.length + '개 생성');
}

/**
 * [신규] workersLoaded 이벤트 수신 → 지도가 있으면 마커 생성
 *
 * 타이밍 문제 해결:
 *   - 지도가 먼저 로드 → initMap()에서 WORKERS.length > 0이면 마커 생성
 *   - API가 먼저 응답 → 여기서 map 존재 확인 후 마커 생성
 */
SenSa.on('workersLoaded', function (d) {
  if (map && workerLayerGroup) {
    initWorkerMarkers();
  }
});

// [기존] 매 초 위치 갱신
SenSa.on('workerMove', function (d) {
  d.workers.forEach(function (w) {
    var m = workerMarkerCache[w.worker_id];
    if (m) {
      m.setLatLng([w.y, w.x]);
    } else {
      // 아직 마커가 없는 신규 작업자 → 마커 추가
      var newM = L.marker([w.y, w.x], { icon: WORKER_ICON })
        .bindTooltip(w.name, { permanent: false, direction: 'top' });
      workerLayerGroup.addLayer(newM);
      workerMarkerCache[w.worker_id] = newM;
    }
  });
});

// ─── 토스트 ───
var EMOJI = { info: 'ℹ️', caution: '⚠️', danger: '🔴', critical: '🚨' };
SenSa.on('alarm', function (alarm) {
  var c = document.getElementById('alarm-toast-container'), t = document.createElement('div');
  t.className = 'alarm-toast toast-' + alarm.alarm_level;
  t.textContent = (EMOJI[alarm.alarm_level] || '⚠️') + ' ' + alarm.message;
  t.onclick = function () { t.remove(); }; c.appendChild(t);
  setTimeout(function () { if (t.parentNode) t.remove(); }, 5000);
});

// ─── 이미지 업로드 ───
function displayMap(url, W, H, name) {
  initMap(W, H);
  if (imageOverlay) imageOverlay.remove();
  /* 이미지 로드 가능한지 먼저 확인 */
  var testImg = new Image();
  testImg.onload = function () {
    /* ✅ 이미지 로드 성공 → 정상적으로 지도에 표시 */
    imageOverlay = L.imageOverlay(url, [[0, 0], [H, W]]).addTo(map);
    map.fitBounds([[0, 0], [H, W]]);
    document.getElementById('upload-area').classList.add('has-image');
    document.getElementById('upload-label').textContent = name || '지도 로드됨';
  };
  testImg.onerror = function () {
    /* ❌ 이미지 404/손상 → 업로드 UI 다시 표시 */
    console.warn('[Map] 이미지 파일을 찾을 수 없습니다: ' + url);

    /* 업로드 오버레이 다시 표시 */
    var uo = document.getElementById('upload-overlay');
    if (uo) uo.style.display = '';

    /* 안내 메시지 표시 */
    var label = document.getElementById('upload-label');
    if (label) label.textContent = '평면도 재업로드 필요';
    var area = document.getElementById('upload-area');
    if (area) {
      area.classList.remove('has-image');
      var p = area.querySelector('p');
      if (p) p.textContent = '이전 파일 누락';
    }
    /* placeholder 다시 표시 */
    var ph = document.getElementById('map-placeholder');
    if (ph) ph.style.display = '';
  };
  testImg.src = url;
}

document.getElementById('file-input').addEventListener('change', function (e) {
  var file = e.target.files[0]; if (!file) return;
  var reader = new FileReader();
  reader.onload = function (evt) {
    var img = new Image();
    img.onload = async function () {
      var fd = new FormData(); fd.append('image', file); fd.append('name', file.name); fd.append('width', img.naturalWidth); fd.append('height', img.naturalHeight);
      try { var res = await fetch('/dashboard/api/map/', { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() }, credentials: 'include', body: fd }); if (!res.ok) throw new Error(await res.text()); var d = await res.json(); displayMap(d.image, d.width, d.height, d.name); } catch (err) { alert('업로드 실패: ' + err.message); }
    }; img.src = evt.target.result;
  }; reader.readAsDataURL(file);
});

(async function () {
  try { var r = await fetch('/dashboard/api/map/current/', { credentials: 'include' }); if (r.ok) { var d = await r.json(); displayMap(d.image, d.width, d.height, d.name); } } catch (e) {}
  var ph = document.createElement('div'); ph.id = 'map-placeholder';
  ph.innerHTML = '<div class="icon">📐</div><p>평면도 이미지를 업로드하면<br>여기에 지도가 표시됩니다.</p>';
  document.getElementById('map-area').appendChild(ph);
})();

// ─── 지오펜스 그리기 ───
var isDrawing = false, drawPoints = [], drawMarkers = [], drawPolyline = null;
var pendingPolygon = null, pendingCoords = [];

window.toggleDrawMode = function () {
  if (!map) { alert('먼저 평면도를 업로드하세요.'); return; }
  isDrawing = !isDrawing;
  var btn = document.getElementById('draw-fence-btn'), hint = document.getElementById('draw-hint');
  if (isDrawing) { btn.textContent = '✔ 그리기 완료'; btn.classList.add('drawing'); hint.style.display = 'block'; map.getContainer().style.cursor = 'crosshair'; }
  else { if (drawPoints.length >= 3) finishPolygon(); else { alert('최소 3개 이상 찍어야 합니다.'); resetDraw(); } }
};

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
  drawMarkers.forEach(function (m) { m.remove(); }); drawMarkers = [];
  if (drawPolyline) { drawPolyline.remove(); drawPolyline = null; } drawPoints = [];
  isDrawing = false;
  document.getElementById('draw-fence-btn').textContent = '✏️ 지오펜스 그리기';
  document.getElementById('draw-fence-btn').classList.remove('drawing');
  document.getElementById('draw-hint').style.display = 'none'; map.getContainer().style.cursor = '';
  openModal();
}

window.clearCurrentDraw = function () { resetDraw(); if (pendingPolygon) { pendingPolygon.remove(); pendingPolygon = null; } pendingCoords = []; };
function resetDraw() {
  isDrawing = false; drawPoints = [];
  drawMarkers.forEach(function (m) { m.remove(); }); drawMarkers = [];
  if (drawPolyline) { drawPolyline.remove(); drawPolyline = null; }
  document.getElementById('draw-fence-btn').textContent = '✏️ 지오펜스 그리기';
  document.getElementById('draw-fence-btn').classList.remove('drawing');
  document.getElementById('draw-hint').style.display = 'none'; if (map) map.getContainer().style.cursor = '';
}

function openModal() { document.getElementById('fence-modal').classList.add('open'); document.getElementById('fence-name').focus(); }
window.closeModal = function () { document.getElementById('fence-modal').classList.remove('open'); if (pendingPolygon) { pendingPolygon.remove(); pendingPolygon = null; } pendingCoords = []; document.getElementById('fence-name').value = ''; document.getElementById('fence-desc').value = ''; };

// ─── 지오펜스 API ───
window.saveGeoFence = async function () {
  var name = document.getElementById('fence-name').value.trim(); if (!name) { alert('구역명을 입력하세요.'); return; } if (pendingCoords.length < 3) { alert('다시 그려주세요.'); return; }
  try { var res = await fetch('/dashboard/api/geofence/', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() }, body: JSON.stringify({ name: name, zone_type: document.getElementById('fence-type').value, risk_level: document.getElementById('fence-risk').value, description: document.getElementById('fence-desc').value.trim(), polygon: pendingCoords }) });
    if (!res.ok) throw new Error(await res.text()); var d = await res.json(); closeModal(); pendingCoords = []; renderGeoFence(d); addToSidebarList(d); if (pendingPolygon) { pendingPolygon.remove(); pendingPolygon = null; }
  } catch (err) { alert('저장 실패: ' + err.message); }
};

async function loadGeoFences() {
  try { var res = await fetch('/dashboard/api/geofence/'); var data = await res.json(), list = data.results || data; if (!list.length) return; document.getElementById('geofence-list').innerHTML = ''; list.forEach(function (f) { renderGeoFence(f); addToSidebarList(f); }); } catch (e) {}
}

function renderGeoFence(fence) {
  var latlngs = fence.polygon.map(function (p) { return [p[1], p[0]]; }), color = ZONE_COLORS[fence.zone_type] || '#aaa';
  var poly = L.polygon(latlngs, { color: color, fillColor: color, fillOpacity: 0.2, weight: 2 });
  poly.bindPopup('<div class="popup-title">' + fence.name + '</div><div class="popup-row"><span class="label">유형</span><span class="value">' + fence.zone_type + '</span></div><div class="popup-row"><span class="label">위험도</span><span class="value">' + fence.risk_level + '</span></div>');
  poly.fenceId = fence.id; geofenceLayerGroup.addLayer(poly);
}

function addToSidebarList(fence) {
  var list = document.getElementById('geofence-list'), empty = list.querySelector('p'); if (empty) empty.remove();
  var color = ZONE_COLORS[fence.zone_type] || '#aaa', item = document.createElement('div');
  item.className = 'geofence-item'; item.dataset.id = fence.id;
  item.innerHTML = '<div class="geofence-dot" style="background:' + color + '"></div><div class="geofence-info"><div class="name">' + fence.name + '</div><div class="meta">' + fence.zone_type + ' · ' + fence.risk_level + '</div></div><button class="delete-btn" onclick="deleteGeoFence(' + fence.id + ')">✕</button>';
  item.addEventListener('click', function (e) { if (e.target.classList.contains('delete-btn')) return; geofenceLayerGroup.eachLayer(function (l) { if (l.fenceId === fence.id) { map.fitBounds(l.getBounds()); l.openPopup(); } }); });
  list.appendChild(item);
}

window.deleteGeoFence = async function (id) {
  if (!confirm('삭제하시겠습니까?')) return;
  try { var res = await fetch('/dashboard/api/geofence/' + id + '/', { method: 'DELETE', headers: { 'X-CSRFToken': getCsrfToken() } });
    if (res.status === 204) { geofenceLayerGroup.eachLayer(function (l) { if (l.fenceId === id) geofenceLayerGroup.removeLayer(l); }); var item = document.querySelector('.geofence-item[data-id="' + id + '"]'); if (item) item.remove(); if (!document.getElementById('geofence-list').children.length) document.getElementById('geofence-list').innerHTML = '<p style="font-size:10px;color:#3a3f55;text-align:center;padding:10px;">지오펜스가 없습니다.</p>'; }
  } catch (err) { alert('삭제 실패: ' + err.message); }
};

// ─── 레이어 토글 ───
document.getElementById('layer-geofence').addEventListener('change', function () { if (!map) return; this.checked ? map.addLayer(geofenceLayerGroup) : map.removeLayer(geofenceLayerGroup); });
document.getElementById('layer-sensor').addEventListener('change', function () { if (!map) return; this.checked ? map.addLayer(sensorLayerGroup) : map.removeLayer(sensorLayerGroup); });
document.getElementById('layer-worker').addEventListener('change', function () { if (!map) return; this.checked ? map.addLayer(workerLayerGroup) : map.removeLayer(workerLayerGroup); });