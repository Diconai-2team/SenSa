/**
 * section_12_13_gas.js — ⑫ 가스 테이블(9종) + ⑬ AI 예측 가스
 *
 * 구독: sensa:gasData → 9종 테이블 값 갱신 + 차트 push + AI 카드 갱신
 *
 * IIFE로 감싸서 전역 변수 충돌 방지
 * (section_14_15_power.js도 'buf', 'CHART_MAX' 이름을 쓰기 때문)
 *
 * [F3 — AI 예측 가스 동적 캐러셀]
 *   가스 캐러셀 (⑬ 헤더) → 9가지 가스 중 선택
 *   - 차트: 선택 가스의 시계열 + 임계선 (가스 별 caution/danger)
 *   - 카드 "현재 농도": WebSocket 최신값
 *   - 카드 "12시간 내 최대 예상": /dashboard/api/ai-predictions/ 의 predicted_value
 *   buf 구조 확장: device × gas 별 누적 (이전 device 만 → device.values[gas])
 *
 * [Step 1A — 가스 패널 페이지네이션화]  (기존 그대로)
 *   ‹ / › 버튼으로 sensor 순회. DB 의 실제 가스 sensor 목록 사용.
 *
 * [P2+ — 새 센서 자동 인식]  (기존 그대로)
 *   sensa:sensorListChanged 구독으로 5초 폴링 결과 반영.
 */
(function () {

  // ─── 임계치 (테이블 배지 + 차트 임계선) ───
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
  };
  var LABELS = { normal: '정상', caution: '주의', danger: '위험' };

  // 9종 가스 키 목록
  var GAS_KEYS = ['o2', 'co', 'co2', 'h2s', 'no2', 'so2', 'o3', 'nh3', 'voc'];

  // ─── [F3] 가스 캐러셀용 라벨/단위 ───
  var GAS_LABELS = {
    o2:  'O₂(산소)',     co:  'CO(일산화탄소)',  co2: 'CO₂(이산화탄소)',
    h2s: 'H₂S(황화수소)', no2: 'NO₂(이산화질소)',  so2: 'SO₂(이산화황)',
    o3:  'O₃(오존)',     nh3: 'NH₃(암모니아)',    voc: 'VOC(휘발성유기)',
  };
  var GAS_UNITS = {
    o2: '%', co: 'ppm', co2: 'ppm', h2s: 'ppm', no2: 'ppm',
    so2: 'ppm', o3: 'ppm', nh3: 'ppm', voc: 'ppm',
  };

  // ─── 개별 가스 상태 판별 ───
  // O2는 양쪽 임계 (저산소=질식, 고산소=화재), 나머지는 단방향
  function gasFieldStatus(key, val) {
    if (val === undefined || val === null) return 'normal';
    if (key === 'o2') {
      if (val < 16 || val >= 23.5) return 'danger';
      if (val < 18 || val > 21.5) return 'caution';
      return 'normal';
    }
    var t = TH[key];
    if (!t) return 'normal';
    return val >= t.d ? 'danger' : val >= t.w ? 'caution' : 'normal';
  }

  // ═════════════════════════════════════════════════════════
  // state
  // ═════════════════════════════════════════════════════════
  var devices = [];
  var currentIndex = 0;
  var currentDeviceId = null;
  var currentGasKey = 'co';   // [F3] 가스 캐러셀 — 기본 CO

  var lastValueByDevice = {};
  // [F3] buf 구조 변경: device × gas 별 누적
  //   기존: chartBufByDevice[device] = { labels: [], co: [] }
  //   현행: chartBufByDevice[device] = { labels: [], values: { co: [], h2s: [], ... } }
  var chartBufByDevice = {};
  var aiPredictionsCache = [];   // (deprecated, G2 에서 안 씀)
  var currentForecast = null;    // [G2] /api/ai-forecast/ 응답 캐시 (현재 sensor+metric 기준)

  // ─── DOM 참조 — 12번 sensor 캐러셀 ───
  var prevBtn = document.getElementById('gas-pager-prev');
  var nextBtn = document.getElementById('gas-pager-next');
  var nameEl  = document.getElementById('gas-current-name');
  var curEl   = document.getElementById('gas-pager-cur');
  var totalEl = document.getElementById('gas-pager-total');

  // ─── DOM 참조 — [F3] 13번 가스 캐러셀 + 카드 ───
  var aiPrev       = document.getElementById('gas-ai-prev');
  var aiNext       = document.getElementById('gas-ai-next');
  var aiNameEl     = document.getElementById('gas-ai-name');
  var aiCurEl      = document.getElementById('gas-ai-cur');
  var aiTotalEl    = document.getElementById('gas-ai-total');
  var aiCurrentEl  = document.getElementById('gas-ai-current');
  var aiForecastEl = document.getElementById('gas-ai-forecast');

  // ─── 12번 sensor 캐러셀 버튼 (기존) ───
  if (prevBtn) prevBtn.addEventListener('click', function () {
    if (currentIndex > 0) selectDevice(currentIndex - 1);
  });
  if (nextBtn) nextBtn.addEventListener('click', function () {
    if (currentIndex < devices.length - 1) selectDevice(currentIndex + 1);
  });

  // ─── [F3] 13번 가스 캐러셀 버튼 ───
  if (aiTotalEl) aiTotalEl.textContent = String(GAS_KEYS.length);
  if (aiPrev) aiPrev.addEventListener('click', function () {
    var idx = GAS_KEYS.indexOf(currentGasKey);
    if (idx > 0) selectGas(GAS_KEYS[idx - 1]);
  });
  if (aiNext) aiNext.addEventListener('click', function () {
    var idx = GAS_KEYS.indexOf(currentGasKey);
    if (idx < GAS_KEYS.length - 1) selectGas(GAS_KEYS[idx + 1]);
  });

  function selectGas(key) {
    currentGasKey = key;
    var idx = GAS_KEYS.indexOf(key);
    if (aiNameEl) aiNameEl.textContent = GAS_LABELS[key] || key.toUpperCase();
    if (aiCurEl)  aiCurEl.textContent  = String(idx + 1);
    if (aiPrev)   aiPrev.disabled = (idx === 0);
    if (aiNext)   aiNext.disabled = (idx === GAS_KEYS.length - 1);
    refreshChartFromBuf();
    refreshAiCards();
    // [G2.3] 캐러셀 클릭 직후 fetch 응답까지 loading 표시
    showAiLoading();
    // [G2] 가스 변경 시 forecast API 재호출 (function hoisting 으로 안전)
    if (typeof loadForecast === 'function') loadForecast();
  }

  // 초기 가스 표시는 chartGas 정의 후 (파일 하단) 에서 호출.
  // [F3.1] selectGas 안의 refreshChartFromBuf 가 chartGas 참조하므로 순서 중요.

  // ─── 가스 sensor 목록 적용 (초기 fetch + sensorListChanged) ───
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
      if (nameEl) nameEl.textContent = '센서 없음';
      if (curEl)  curEl.textContent  = '0';
      if (totalEl) totalEl.textContent = '0';
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      renderEmpty();
      refreshChartFromBuf();
      refreshAiCards();
      return;
    }
    selectDevice(keepIdx);
    backfillFromHistory();
  }

  // ─── 페이지 첫 로드: 디바이스별 최신 SensorData 1건씩 백필 ───
  function backfillFromHistory() {
    devices.forEach(function (dev) {
      if (lastValueByDevice[dev.device_id]) return;
      var qs = '?device_id=' + encodeURIComponent(dev.device_id) + '&limit=1';
      fetch('/dashboard/api/sensor-data/' + qs)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var arr = Array.isArray(data) ? data : (data.results || []);
          if (arr.length === 0) return;
          var row = arr[0];

          var gas = {};
          GAS_KEYS.forEach(function (k) {
            if (row[k] !== undefined && row[k] !== null) gas[k] = row[k];
          });

          lastValueByDevice[dev.device_id] = gas;
          pushBuf(dev.device_id, gas);

          if (dev.device_id === currentDeviceId) {
            renderTable(gas);
            refreshChartFromBuf();
            refreshAiCards();
          }
        })
        .catch(function () { /* silent */ });
    });
  }

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

  SenSa.on('sensorListChanged', function (d) {
    if (!d || !d.all) return;
    applyDeviceList(d.all);
  });

  // ─── sensor 선택 (12번 캐러셀) ───
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
    refreshAiCards();   // [F3] sensor 바뀌면 카드도 갱신
    // [G2.3] sensor 변경 시 forecast 응답까지 loading 표시
    showAiLoading();
    // [G2] sensor 변경 시 forecast API 재호출
    if (typeof loadForecast === 'function') loadForecast();
  }

  // ─── 테이블 렌더 (12번) ───
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
  // gasData 이벤트 수신 (실시간 WebSocket)
  // ═════════════════════════════════════════════════════════
  SenSa.on('gasData', function (d) {
    if (!d || !d.device_id || !d.gas) return;

    lastValueByDevice[d.device_id] = d.gas;
    pushBuf(d.device_id, d.gas);

    if (d.device_id !== currentDeviceId) return;
    renderTable(d.gas);
    refreshChartFromBuf();
    refreshAiCards();   // [F3] 현재값 카드 실시간 갱신
  });

  // ═════════════════════════════════════════════════════════
  // ⑬ 차트 — [F3] 가스 동적 (선택 가스만 표시)
  // ═════════════════════════════════════════════════════════
  var GAS_CHART_MAX = 20;

  function bufFor(deviceId) {
    if (!chartBufByDevice[deviceId]) {
      chartBufByDevice[deviceId] = { labels: [], values: {} };
      GAS_KEYS.forEach(function (k) {
        chartBufByDevice[deviceId].values[k] = [];
      });
    }
    return chartBufByDevice[deviceId];
  }

  var chartGas = new Chart(document.getElementById('chart-gas'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'CO',   data: [], borderColor: '#00c8ff', backgroundColor: 'rgba(0,200,255,0.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 1 },
        { label: '주의', data: [], borderColor: '#ffcc00', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
        { label: '위험', data: [], borderColor: '#ff4444', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
        // [G2] AI 예측 라인 (점선 마젠타, 미래 horizon 외삽)
        { label: '예측', data: [], borderColor: '#ff66ff', borderDash: [3, 3], borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.3, spanGaps: false },
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
      buf.values[k].push(gas[k] !== undefined && gas[k] !== null ? gas[k] : null);
    });
    if (buf.labels.length > GAS_CHART_MAX) {
      buf.labels.shift();
      GAS_KEYS.forEach(function (k) { buf.values[k].shift(); });
    }
  }

  // [G2] AI 예측 horizon (chart 에 표시할 미래 틱 수)
  var FORECAST_HORIZON = 10;

  function refreshChartFromBuf() {
    // [F3.1] chartGas 정의 전 호출되면 안전 종료 (selectGas 의 초기 호출 등)
    if (typeof chartGas === 'undefined' || !chartGas) return;

    if (!currentDeviceId) {
      chartGas.data.labels = [];
      chartGas.data.datasets.forEach(function (d) { d.data = []; });
      chartGas.update();
      return;
    }
    var buf = bufFor(currentDeviceId);
    var key = currentGasKey;
    var th = TH[key] || { w: null, d: null };
    var bufLen = buf.labels.length;

    // [G2] forecast 데이터 (currentForecast 가 현재 sensor+gas 와 매치되는 경우만)
    var fc = null;
    if (currentForecast
        && currentForecast.metric === key
        && currentForecast.device_id === currentDeviceId
        && Array.isArray(currentForecast.predicted)) {
      fc = currentForecast.predicted.slice(0, FORECAST_HORIZON);
    }
    var fcLen = fc ? fc.length : 0;
    var totalLen = bufLen + fcLen;

    // 미래 시점 라벨 (단순 "+1", "+2", ...)
    var futureLabels = [];
    for (var i = 1; i <= fcLen; i++) futureLabels.push('+' + i);
    chartGas.data.labels = buf.labels.concat(futureLabels);

    // dataset[0] 실제값 — buf + null padding (미래는 비움)
    var actualData = (buf.values[key] || []).slice();
    for (var j = 0; j < fcLen; j++) actualData.push(null);
    chartGas.data.datasets[0].label = key.toUpperCase();
    chartGas.data.datasets[0].data = actualData;

    // dataset[1, 2] 임계선 — 전체 길이 (현재 + 미래) 채움
    if (key !== 'o2' && th.w !== null && th.w !== undefined) {
      chartGas.data.datasets[1].data = Array(totalLen).fill(th.w);
    } else {
      chartGas.data.datasets[1].data = [];
    }
    if (key !== 'o2' && th.d !== null && th.d !== undefined) {
      chartGas.data.datasets[2].data = Array(totalLen).fill(th.d);
    } else {
      chartGas.data.datasets[2].data = [];
    }

    // [G2] dataset[3] AI 예측 — buf 마지막 점 + forecast 미래
    if (fcLen > 0 && bufLen > 0) {
      var forecastData = Array(bufLen - 1).fill(null);
      var lastActual = buf.values[key][bufLen - 1];
      forecastData.push(lastActual !== undefined && lastActual !== null ? lastActual : null);
      forecastData = forecastData.concat(fc);
      chartGas.data.datasets[3].data = forecastData;
    } else {
      chartGas.data.datasets[3].data = [];
    }

    chartGas.update();
  }

  // [F3.1] 가스 캐러셀 초기화 — chartGas 정의 이후에 호출되어야 안전
  selectGas(currentGasKey);

  // ═════════════════════════════════════════════════════════
  // [F3] AI 카드 — 현재 농도 + 12시간 내 최대 예상
  //   - 현재 농도: lastValueByDevice 캐시
  //   - 12h 예상: /dashboard/api/ai-predictions/ 의 predicted_value
  // ═════════════════════════════════════════════════════════
  // ═════════════════════════════════════════════════════════
  // [G2] AI 카드 — forecast API 기반
  //   카드 1 "현재 농도": WebSocket 캐시 우선, fallback forecast.current_value
  //   카드 2 "AI 예측": forecast API 의 운영자 메시지 (risk_message)
  //   차트 forecast 라인: refreshChartFromBuf 내부에서 currentForecast 활용
  // ═════════════════════════════════════════════════════════
  // [G2.1] 위험 메시지 → 카드 클래스 (success/caution/failure/accuracy)
  function riskClassFromMessage(msg) {
    if (!msg) return 'accuracy';
    if (msg === '정상') return 'success';
    // 즉시 위험
    if (msg.indexOf('즉시 조치') !== -1
        || msg.indexOf('이상 급증') !== -1
        || msg.indexOf('산소 농도 이상') !== -1) return 'failure';
    // 예측/주의 단계
    if (msg.indexOf('주의') !== -1
        || msg.indexOf('위험 가능성') !== -1
        || msg.indexOf('위험 도달') !== -1
        || msg.indexOf('상승 추세') !== -1
        || msg.indexOf('시간 내 위험') !== -1) return 'caution';
    return 'accuracy';
  }

  function refreshAiCards() {
    var unit = GAS_UNITS[currentGasKey] || '';

    // 현재 농도 — WS 캐시 우선
    if (aiCurrentEl) {
      var gas = lastValueByDevice[currentDeviceId];
      var v = (gas && gas[currentGasKey] !== undefined && gas[currentGasKey] !== null)
        ? gas[currentGasKey] : null;
      // fallback — forecast API 의 current_value (페이지 로드 직후 WS 미수신 시)
      if (v === null && currentForecast
          && currentForecast.device_id === currentDeviceId
          && currentForecast.metric === currentGasKey
          && currentForecast.current_value !== undefined
          && currentForecast.current_value !== null) {
        v = currentForecast.current_value;
      }
      if (v !== null && v !== undefined) {
        aiCurrentEl.textContent = (typeof v === 'number' ? v.toFixed(1) : v) + ' ' + unit;
      } else {
        aiCurrentEl.textContent = '—';
      }
    }

    // AI 예측 메시지 + 색상 동적 적용
    if (aiForecastEl) {
      var card = aiForecastEl.closest('.ai-perf-card');
      var msg = (currentForecast
                 && currentForecast.device_id === currentDeviceId
                 && currentForecast.metric === currentGasKey
                 && currentForecast.risk_message) ? currentForecast.risk_message : null;

      aiForecastEl.textContent = msg || '—';

      // [G2.1] 카드 클래스 swap — risk level 시각화
      if (card) {
        card.classList.remove('success', 'caution', 'failure', 'accuracy');
        card.classList.add(riskClassFromMessage(msg));
      }
    }
  }

  // [G2.3] 캐러셀 클릭 시 fetch 응답 전까지 "분석 중..." 표시 (accuracy 클래스로 reset)
  function showAiLoading() {
    if (!aiForecastEl) return;
    aiForecastEl.textContent = '분석 중...';
    var card = aiForecastEl.closest('.ai-perf-card');
    if (card) {
      card.classList.remove('success', 'caution', 'failure');
      card.classList.add('accuracy');
    }
  }

  function loadForecast() {
    if (!currentDeviceId || !currentGasKey) {
      currentForecast = null;
      refreshAiCards();
      refreshChartFromBuf();
      return;
    }
    var url = '/dashboard/api/ai-forecast/'
            + '?device_id=' + encodeURIComponent(currentDeviceId)
            + '&metric=' + encodeURIComponent(currentGasKey)
            + '&horizon=20';
    fetch(url, { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        currentForecast = d;
        refreshAiCards();
        refreshChartFromBuf();   // forecast 라인 차트 반영
      })
      .catch(function () { /* silent */ });
  }

  loadForecast();
  setInterval(loadForecast, 10000);   // 10초 polling

})();
