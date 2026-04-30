/**
 * section_14_15_power.js — ⑭ 전력 테이블 + ⑮ 전력 차트
 *
 * 구독: sensa:powerData → 테이블 갱신 + 차트 push
 *       sensa:sensorListChanged → 페이지네이션 갱신 (P2+ 5초 폴링)
 *
 * IIFE로 감싸서 전역 변수 충돌 방지
 *
 * [Step 1B — 전력 패널 페이지네이션화]
 *   기존 : 하드코딩 행 2개(스마트파워 A/B) — DB의 실제 전력 센서 수와 무관
 *   현행 : 페이지 로드 시 /dashboard/api/device/?sensor_type=power 호출하여
 *          DB의 전력 센서 목록을 받아오고, ‹ / › 버튼으로 순회.
 *
 *   설계 결정 (가스 패턴과 일치):
 *     - lastValueByDevice 캐시 — 페이지 전환 시 즉시 이전 값 표시
 *     - chartBufByDevice — 디바이스별 차트 히스토리 분리
 *     - sensorListChanged 구독 — 새 전력 센서 추가 시 자동 N+1
 *
 *   B-3 헤더 (사용자 결정):
 *     - 큰 글씨: 모든 전력 센서의 합산 와트 (공장 전력 사용량 한눈)
 *     - 작은 글씨: 현재 보고 있는 설비의 와트 (페이지네이션 일관성)
 */
(function () {

  var LABELS = { normal: '정상', caution: '주의', danger: '위험' };

  // ═════════════════════════════════════════════════════════
  // 페이지네이션 state + 디바이스별 캐시
  // ═════════════════════════════════════════════════════════
  var devices = [];                  // 전력 센서 메타 [{device_id, device_name, ...}, ...]
  var currentIndex = 0;
  var currentDeviceId = null;

  var lastValueByDevice = {};        // device_id → 최신 power 데이터 + status
  var chartBufByDevice = {};         // device_id → { labels: [], current: [] }

  // ─── DOM 참조 ───
  var prevBtn  = document.getElementById('power-pager-prev');
  var nextBtn  = document.getElementById('power-pager-next');
  var nameEl   = document.getElementById('power-current-name');
  var curEl    = document.getElementById('power-pager-cur');
  var totalEl  = document.getElementById('power-pager-total');
  var totalWattEl = document.getElementById('power-total-watt');
  var curWattEl   = document.getElementById('power-cur-watt');

  var rowNameEl    = document.getElementById('power-row-name');
  var rowCurrentEl = document.getElementById('power-row-current-val');
  var rowVoltageEl = document.getElementById('power-row-voltage-val');
  var rowBadgeEl   = document.getElementById('power-row-badge');
  var rowEl        = document.getElementById('power-row-current');

  // ─── 페이지네이션 버튼 ───
  if (prevBtn) prevBtn.addEventListener('click', function () {
    if (currentIndex > 0) selectDevice(currentIndex - 1);
  });
  if (nextBtn) nextBtn.addEventListener('click', function () {
    if (currentIndex < devices.length - 1) selectDevice(currentIndex + 1);
  });

  // ─── 전력 센서 목록 적용 (초기 fetch + sensorListChanged 양쪽에서 재사용) ───
  // [P2+] 5초 폴링으로 새 전력 센서가 추가되면 페이지네이션이 자동 확장.
  //       현재 보고 있는 센서가 제거되면 0번으로 복귀.
  function applyDeviceList(arr) {
    var fresh = arr
      .filter(function (d) { return d.sensor_type === 'power'; })
      .sort(function (a, b) { return a.device_id.localeCompare(b.device_id); });

    // 보고 있던 센서가 새 목록에도 있으면 그 인덱스 유지, 없으면 0 으로 복귀
    var keepIdx = 0;
    if (currentDeviceId) {
      var found = fresh.findIndex(function (d) { return d.device_id === currentDeviceId; });
      if (found >= 0) keepIdx = found;
    }

    devices = fresh;

    if (devices.length === 0) {
      currentDeviceId = null;
      if (nameEl)  nameEl.textContent  = '센서 없음';
      if (curEl)   curEl.textContent   = '0';
      if (totalEl) totalEl.textContent = '0';
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      renderEmpty();
      refreshChartFromBuf();
      return;
    }
    selectDevice(keepIdx);
  }

  // ─── 전력 센서 목록 로드 (페이지 첫 진입 시 1회) ───
  fetch('/dashboard/api/device/?sensor_type=power')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      // DRF 페이지네이션 on/off 양쪽 호환
      var arr = Array.isArray(data) ? data : (data.results || []);
      applyDeviceList(arr);
    })
    .catch(function (e) {
      console.error('전력 센서 목록 로드 실패', e);
      if (nameEl) nameEl.textContent = '로드 실패';
    });

  // [P2+] 5초 폴링으로 base.js 가 SENSOR_DEVICES 갱신을 알리면 페이지네이션도 갱신
  SenSa.on('sensorListChanged', function (d) {
    if (!d || !d.all) return;
    applyDeviceList(d.all);
  });

  // ─── 디바이스 선택 ───
  function selectDevice(idx) {
    currentIndex = idx;
    currentDeviceId = devices[idx].device_id;

    if (nameEl)  nameEl.textContent  = devices[idx].device_name || devices[idx].device_id;
    if (curEl)   curEl.textContent   = String(idx + 1);
    if (totalEl) totalEl.textContent = String(devices.length);
    if (prevBtn) prevBtn.disabled = (idx === 0);
    if (nextBtn) nextBtn.disabled = (idx === devices.length - 1);

    // 캐시된 최신값이 있으면 즉시 렌더, 없으면 dash
    if (lastValueByDevice[currentDeviceId]) {
      renderRow(lastValueByDevice[currentDeviceId]);
    } else {
      renderEmpty();
    }
    refreshChartFromBuf();
  }

  // ─── 행 렌더 (현재 보고 있는 1개 설비) ───
  function renderRow(d) {
    var s = d.status || 'normal';

    if (rowNameEl)    rowNameEl.textContent    = devices[currentIndex] && devices[currentIndex].device_name || d.device_id;
    if (rowCurrentEl) rowCurrentEl.textContent = d.power.current + ' A';
    if (rowVoltageEl) rowVoltageEl.textContent = d.power.voltage + ' V';

    if (rowBadgeEl) {
      rowBadgeEl.className = 'status-badge status-' + s;
      rowBadgeEl.textContent = LABELS[s] || s;
    }

    if (rowEl) {
      rowEl.classList.remove('row-normal', 'row-caution', 'row-danger');
      rowEl.classList.add('row-' + s);
    }

    // B-3: 현재 설비 와트 (작은 글씨)
    if (curWattEl) curWattEl.textContent = (d.power.watt || 0).toFixed(0);
  }

  function renderEmpty() {
    if (rowNameEl)    rowNameEl.textContent    = '—';
    if (rowCurrentEl) rowCurrentEl.textContent = '—';
    if (rowVoltageEl) rowVoltageEl.textContent = '—';
    if (rowBadgeEl) {
      rowBadgeEl.className = 'status-badge status-normal';
      rowBadgeEl.textContent = '—';
    }
    if (rowEl) rowEl.classList.remove('row-normal', 'row-caution', 'row-danger');
    if (curWattEl) curWattEl.textContent = '0';
  }

  // ═════════════════════════════════════════════════════════
  // powerData 이벤트 수신
  //   - 모든 센서 데이터를 캐시에 저장
  //   - 차트 buf 도 디바이스별로 누적
  //   - 화면 갱신은 현재 보고 있는 센서만
  //   - 헤더 합산 와트는 모든 센서 데이터로 갱신
  // ═════════════════════════════════════════════════════════
  SenSa.on('powerData', function (d) {
    if (!d || !d.device_id || !d.power) return;

    lastValueByDevice[d.device_id] = d;
    pushBuf(d.device_id, d.power);

    // B-3 헤더: 전체 합산 와트 (큰 글씨 — 모든 센서 합산)
    var total = 0;
    for (var k in lastValueByDevice) {
      total += (lastValueByDevice[k].power && lastValueByDevice[k].power.watt) || 0;
    }
    if (totalWattEl) {
      // textContent 가 아닌 직접 자식 노드 갱신 — innerHTML 재작성 회피 (성능 + ref 유지)
      // 첫 텍스트 노드(합산 숫자) 만 갱신
      var firstNode = totalWattEl.firstChild;
      if (firstNode && firstNode.nodeType === Node.TEXT_NODE) {
        firstNode.nodeValue = total.toFixed(0) + ' ';
      }
    }

    // B-3 헤더: 현재 설비 와트 (작은 글씨)
    if (curWattEl) {
      var curWatt = (lastValueByDevice[currentDeviceId] &&
                     lastValueByDevice[currentDeviceId].power.watt) || 0;
      curWattEl.textContent = curWatt.toFixed(0);
    }

    // 화면 갱신은 현재 보고 있는 센서일 때만
    if (d.device_id !== currentDeviceId) return;
    renderRow(d);
    refreshChartFromBuf();
  });

  // ═════════════════════════════════════════════════════════
  // ⑮ 차트 — 디바이스별 buf
  // ═════════════════════════════════════════════════════════
  var POWER_CHART_MAX = 20;

  function bufFor(deviceId) {
    if (!chartBufByDevice[deviceId]) {
      chartBufByDevice[deviceId] = { labels: [], current: [] };
    }
    return chartBufByDevice[deviceId];
  }

  var chartPower = new Chart(document.getElementById('chart-power'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: '전류(A)', data: [], borderColor: '#ffaa00', backgroundColor: 'rgba(255,170,0,0.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 1 },
        { label: '주의',    data: [], borderColor: '#ffcc00', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
        { label: '위험',    data: [], borderColor: '#ff4444', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 200 },
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#406080', font: { size: 8 }, maxTicksLimit: 5 }, grid: { color: '#1a2040' } },
        y: { ticks: { color: '#406080', font: { size: 8 } }, grid: { color: '#1a2040' } },
      }
    },
  });

  function pushBuf(deviceId, power) {
    var buf = bufFor(deviceId);
    var now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    buf.labels.push(now);
    buf.current.push(power.current);
    if (buf.labels.length > POWER_CHART_MAX) {
      buf.labels.shift();
      buf.current.shift();
    }
  }

  function refreshChartFromBuf() {
    if (!currentDeviceId) {
      chartPower.data.labels = [];
      chartPower.data.datasets[0].data = [];
      chartPower.data.datasets[1].data = [];
      chartPower.data.datasets[2].data = [];
      chartPower.update();
      return;
    }
    var buf = bufFor(currentDeviceId);
    chartPower.data.labels = buf.labels;
    chartPower.data.datasets[0].data = buf.current;
    chartPower.data.datasets[1].data = Array(buf.labels.length).fill(15);   // caution 임계 근사
    chartPower.data.datasets[2].data = Array(buf.labels.length).fill(25);   // danger 임계 근사
    chartPower.update();
  }

})();
