/**
 * section_12_13_gas.js — ⑫ 가스 테이블(9종) + ⑬ 가스 차트
 *
 * 구독: sensa:gasData → 9종 테이블 값 갱신 + 차트 push
 *
 * IIFE로 감싸서 전역 변수 충돌 방지
 * (section_14_15_power.js도 'buf', 'CHART_MAX' 이름을 쓰기 때문)
 *
 * [Step 1A — 가스 패널 페이지네이션화]
 *   기존 : 하드코딩 탭 3개(sensor_01/02/03) — DB의 실제 가스 센서 수와 무관
 *   현행 : 페이지 로드 시 /dashboard/api/device/?sensor_type=gas 호출하여
 *          DB의 가스 센서 목록을 받아오고, ‹ / › 버튼으로 순회.
 *
 * [Step 2 — 메트릭 선택 버튼]
 *   차트 위 버튼(CO / O₂ / CO₂ / H₂S / …)으로 표시 가스 종류 전환.
 *   모든 가스 버퍼를 동시에 쌓아두므로 전환 즉시 히스토리가 표시됨.
 *   ARIMA 예측선도 선택된 메트릭에 맞춰 전환.
 *
 * [P2+ — 새 센서 자동 인식]
 *   sensa:sensorListChanged 구독으로 5초 폴링 결과 반영.
 */
(function () {

  // ─── 임계치 (테이블 배지용) ───
  // 근거: 고용노동부고시 (화학물질 및 물리적 인자의 노출기준)
  var TH = {
    co:  { w: 25,   d: 200  },   // ACGIH TWA 25ppm, NIOSH C 200ppm
    h2s: { w: 10,   d: 50   },   // KOSHA 적정공기 10ppm, IDLH 50ppm
    co2: { w: 1000, d: 5000 },   // 실내공기질 1,000ppm, TWA 5,000ppm
    no2: { w: 3,    d: 5    },   // 고용노동부 TWA 3ppm, STEL 5ppm
    so2: { w: 2,    d: 5    },   // 고용노동부 TWA 2ppm, STEL 5ppm
    o3:  { w: 0.05, d: 0.1  },   // ACGIH TLV 0.05~0.1ppm
    nh3: { w: 25,   d: 50   },   // ACGIH TWA 25ppm, STEL 35ppm
    voc: { w: 0.5,  d: 2.0  },   // TVOC 실내기준
    // O2: 낮을수록 위험 — 차트에는 하한 임계만 표시
    o2:  { w: 18,   d: 16   },
  };
  var LABELS = { normal: '정상', caution: '주의', danger: '위험' };

  // 차트 레이블 (표시용)
  var GAS_CHART_LABEL = {
    o2: 'O₂(%)', co: 'CO(ppm)', co2: 'CO₂(ppm)', h2s: 'H₂S(ppm)',
    no2: 'NO₂(ppm)', so2: 'SO₂(ppm)', o3: 'O₃(ppm)', nh3: 'NH₃(ppm)', voc: 'VOC(ppm)',
  };

  // 9종 가스 키 목록
  var GAS_KEYS = ['o2', 'co', 'co2', 'h2s', 'no2', 'so2', 'o3', 'nh3', 'voc'];

  // ─── 개별 가스 상태 판별 ───
  // O2는 양쪽 임계 (저산소=질식, 고산소=화재), 나머지는 단방향
  // 근거: 산업안전보건기준에 관한 규칙 제618조, KOSHA 산소농도별 인체영향
  function gasFieldStatus(key, val) {
    if (val === undefined || val === null) return 'normal';
    if (key === 'o2') {
      if (val < 16 || val >= 23.5) return 'danger';    // KOSHA 16% 자각증상, 제618조 23.5% 적정상한
      if (val < 18 || val > 21.5) return 'caution';    // 제618조 18% 산소결핍 기준선
      return 'normal';                                  // 18~21.5% (정상 대기 20.9% 중심)
    }
    var t = TH[key];
    if (!t) return 'normal';
    return val >= t.d ? 'danger' : val >= t.w ? 'caution' : 'normal';
  }

  // ═════════════════════════════════════════════════════════
  // 페이지네이션 state + 디바이스별 캐시
  // ═════════════════════════════════════════════════════════
  var devices = [];                  // 가스 센서 메타 [{device_id, device_name, ...}, ...]
  var currentIndex = 0;
  var currentDeviceId = null;

  var lastValueByDevice = {};        // device_id → 최신 gas 값 객체
  var chartBufByDevice = {};         // device_id → { labels: [], o2: [], co: [], ... }

  // ─── DOM 참조 ───
  var prevBtn = document.getElementById('gas-pager-prev');
  var nextBtn = document.getElementById('gas-pager-next');
  var nameEl  = document.getElementById('gas-current-name');
  var curEl   = document.getElementById('gas-pager-cur');
  var totalEl = document.getElementById('gas-pager-total');

  // ─── 페이지네이션 버튼 ───
  if (prevBtn) prevBtn.addEventListener('click', function () {
    if (currentIndex > 0) selectDevice(currentIndex - 1);
  });
  if (nextBtn) nextBtn.addEventListener('click', function () {
    if (currentIndex < devices.length - 1) selectDevice(currentIndex + 1);
  });

  // ─── 가스 센서 목록 적용 (초기 fetch + sensorListChanged 양쪽에서 재사용) ───
  function applyDeviceList(arr) {
    var fresh = arr
      .filter(function (d) { return d.sensor_type === 'gas'; })
      .sort(function (a, b) { return a.device_id.localeCompare(b.device_id); });

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

  // ─── 가스 센서 목록 로드 (페이지 첫 진입 시 1회) ───
  fetch('/dashboard/api/device/?sensor_type=gas')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var arr = Array.isArray(data) ? data : (data.results || []);
      applyDeviceList(arr);
    })
    .catch(function (e) {
      console.error('가스 센서 목록 로드 실패', e);
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

    if (lastValueByDevice[currentDeviceId]) {
      renderTable(lastValueByDevice[currentDeviceId]);
    } else {
      renderEmpty();
    }
    refreshChartFromBuf();
  }

  // ─── 테이블 렌더 ───
  function renderTable(gas) {
    GAS_KEYS.forEach(function (k) {
      var el = document.getElementById('val-' + k);
      if (el && gas[k] !== undefined && gas[k] !== null) el.textContent = gas[k];

      var badge = document.getElementById('badge-' + k);
      if (badge && gas[k] !== undefined && gas[k] !== null) {
        var s = gasFieldStatus(k, gas[k]);
        badge.className = 'status-badge status-' + s;
        badge.textContent = LABELS[s];

        var tr = badge.closest('tr');
        if (tr) {
          tr.classList.remove('row-normal', 'row-caution', 'row-danger');
          tr.classList.add('row-' + s);
        }
      }
    });
  }

  function renderEmpty() {
    GAS_KEYS.forEach(function (k) {
      var el = document.getElementById('val-' + k);
      if (el) el.textContent = '—';
      var badge = document.getElementById('badge-' + k);
      if (badge) {
        badge.className = 'status-badge status-normal';
        badge.textContent = '—';
      }
      var tr = badge && badge.closest('tr');
      if (tr) tr.classList.remove('row-normal', 'row-caution', 'row-danger');
    });
  }

  // ═════════════════════════════════════════════════════════
  // gasData 이벤트 수신
  // ═════════════════════════════════════════════════════════
  SenSa.on('gasData', function (d) {
    if (!d || !d.device_id || !d.gas) return;

    lastValueByDevice[d.device_id] = d.gas;
    pushBuf(d.device_id, d.gas);

    if (d.device_id !== currentDeviceId) return;
    renderTable(d.gas);
    refreshChartFromBuf();
  });

  // ═════════════════════════════════════════════════════════
  // ⑬ 차트 — 메트릭 선택 버튼 + ARIMA 예측 오버레이
  // ═════════════════════════════════════════════════════════
  var GAS_CHART_MAX = 20;
  var selectedMetric = 'co';   // 현재 차트에 표시 중인 가스 종류

  // 디바이스별, 메트릭별 ARIMA 예측값 저장 { device_id: { metric: [...] } }
  var predByDevice = {};

  // ─── 메트릭 선택 버튼 이벤트 ───
  var metricBtns = document.querySelectorAll('#section-13-gas-chart .gas-metric-btn');
  metricBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      metricBtns.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      selectedMetric = btn.dataset.metric;
      refreshChartFromBuf();
    });
  });

  function bufFor(deviceId) {
    if (!chartBufByDevice[deviceId]) {
      var init = { labels: [] };
      GAS_KEYS.forEach(function (k) { init[k] = []; });
      chartBufByDevice[deviceId] = init;
    }
    return chartBufByDevice[deviceId];
  }

  var chartGas = new Chart(document.getElementById('chart-gas'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'CO(ppm)',    data: [], borderColor: '#00c8ff', backgroundColor: 'rgba(0,200,255,0.08)', fill: true,  tension: 0.4, borderWidth: 2,   pointRadius: 1 },
        { label: '주의',       data: [], borderColor: '#ffcc00', borderWidth: 1,   borderDash: [4, 3], pointRadius: 0, fill: false },
        { label: '위험',       data: [], borderColor: '#ff4444', borderWidth: 1,   borderDash: [4, 3], pointRadius: 0, fill: false },
        { label: 'CO(ppm) 예측', data: [], borderColor: 'rgba(0,200,255,0.45)', borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, fill: false, tension: 0.4, spanGaps: false },
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

  function pushBuf(deviceId, gas) {
    var buf = bufFor(deviceId);
    var now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    buf.labels.push(now);
    GAS_KEYS.forEach(function (k) {
      buf[k].push(gas[k] !== undefined && gas[k] !== null ? gas[k] : null);
    });
    if (buf.labels.length > GAS_CHART_MAX) {
      buf.labels.shift();
      GAS_KEYS.forEach(function (k) { buf[k].shift(); });
    }
  }

  function refreshChartFromBuf() {
    if (!currentDeviceId) {
      chartGas.data.labels = [];
      chartGas.data.datasets.forEach(function (ds) { ds.data = []; });
      chartGas.update();
      return;
    }
    var buf    = bufFor(currentDeviceId);
    var devPreds = predByDevice[currentDeviceId];
    var preds  = devPreds && devPreds[selectedMetric];
    var steps  = (preds && preds.length) ? preds.length : 0;

    // 라벨: 실측 + 예측 슬롯
    var allLabels = buf.labels.slice();
    for (var i = 1; i <= steps; i++) allLabels.push('예측+' + i);

    // dataset[0] 실측
    var metricBuf = buf[selectedMetric] || [];
    var realData  = metricBuf.concat(new Array(steps).fill(null));

    // dataset[3] 예측: 마지막 실측값에서 매끄럽게 연결
    var predData = [];
    if (steps > 0) {
      var lastReal = metricBuf.length > 0 ? metricBuf[metricBuf.length - 1] : null;
      predData = new Array(metricBuf.length - 1).fill(null)
                   .concat([lastReal])
                   .concat(preds);
    }

    // 선택된 메트릭 임계치 + 레이블 반영
    var th    = TH[selectedMetric] || {};
    var lbl   = GAS_CHART_LABEL[selectedMetric] || selectedMetric;

    chartGas.data.labels              = allLabels;
    chartGas.data.datasets[0].label   = lbl;
    chartGas.data.datasets[0].data    = realData;
    chartGas.data.datasets[1].data    = th.w !== undefined ? Array(allLabels.length).fill(th.w) : [];
    chartGas.data.datasets[2].data    = th.d !== undefined ? Array(allLabels.length).fill(th.d) : [];
    chartGas.data.datasets[3].label   = lbl + ' 예측';
    chartGas.data.datasets[3].data    = predData;
    chartGas.update();
  }

  // ARIMA 예측값 수신 — 모든 가스 메트릭 처리
  SenSa.on('aiPrediction', function (d) {
    if (!d || !d.device_id || !d.metric || !d.predicted_values) return;
    if (!predByDevice[d.device_id]) predByDevice[d.device_id] = {};
    predByDevice[d.device_id][d.metric] = d.predicted_values;
    if (d.device_id === currentDeviceId && d.metric === selectedMetric) refreshChartFromBuf();
  });

})();
