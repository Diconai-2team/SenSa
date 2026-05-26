/**
 * section_14_15_power.js — ⑭ 전력 테이블 + ⑮ AI 예측 전력
 *
 * 구독: sensa:powerData → 테이블 갱신 + 차트 push + AI 카드 갱신
 *
 * IIFE로 감싸서 전역 변수 충돌 방지
 *
 * [G3 — AI 예측 전력 (G2 가스 패턴 그대로 적용)]
 *   전력 변수 캐러셀 (⑮ 헤더) — 4가지 변수 (전류/전압/전력/온도) 중 선택
 *   - 차트: 선택 변수의 시계열 + 임계선 (변수 별 caution/danger) + AI 예측 점선
 *   - 카드 "현재 값": WebSocket 최신값
 *   - 카드 "🤖 AI 예측 — 위험 분석": /api/ai-forecast/ 의 risk_message
 *     - 색상: success(녹) / caution(황) / failure(적) / accuracy(파)
 *   buf 구조 확장: device × variable 별 누적
 */
(function () {

  var LABELS = { normal: '정상', caution: '주의', danger: '위험' };

  // ─── [G3] 전력 변수 정의 ───
  var POWER_KEYS = ['current', 'voltage', 'watt', 'temp'];
  var POWER_LABELS = {
    current: '전류(A)',
    voltage: '전압(V)',
    watt:    '전력(W)',
    temp:    '온도(°C)',
  };
  var POWER_UNITS = {
    current: 'A',
    voltage: 'V',
    watt:    'W',
    temp:    '°C',
  };
  // [G3] 임계 — G1 forecast API 의 THRESHOLDS 와 동기
  var POWER_TH = {
    current: { w: 15,    d: 25   },
    voltage: { w: 240,   d: 250  },
    watt:    { w: 5000,  d: 8000 },
    temp:    { w: 80,    d: 120  },
  };

  // ═════════════════════════════════════════════════════════
  // state
  // ═════════════════════════════════════════════════════════
  var devices = [];
  var currentIndex = 0;
  var currentDeviceId = null;
  var currentPowerKey = 'current';   // [G3] 변수 캐러셀 — 기본 전류

  var lastValueByDevice = {};
  // [G3] buf 구조 변경: device × variable 별 누적
  //   기존: chartBufByDevice[device] = { labels:[], current:[] }
  //   현행: chartBufByDevice[device] = { labels:[], values:{current:[], voltage:[], watt:[], temp:[]} }
  var chartBufByDevice = {};
  var currentForecast = null;        // [G3] /api/ai-forecast/ 응답 캐시

  // ─── DOM — 14번 sensor 캐러셀 ───
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

  // ─── DOM — [G3] 15번 변수 캐러셀 + 카드 ───
  var aiPrev       = document.getElementById('power-ai-prev');
  var aiNext       = document.getElementById('power-ai-next');
  var aiNameEl     = document.getElementById('power-ai-name');
  var aiCurEl      = document.getElementById('power-ai-cur');
  var aiTotalEl    = document.getElementById('power-ai-total');
  var aiCurrentEl  = document.getElementById('power-ai-current');
  var aiForecastEl = document.getElementById('power-ai-forecast');

  // ─── 14번 sensor 캐러셀 (기존) ───
  if (prevBtn) prevBtn.addEventListener('click', function () {
    if (currentIndex > 0) selectDevice(currentIndex - 1);
  });
  if (nextBtn) nextBtn.addEventListener('click', function () {
    if (currentIndex < devices.length - 1) selectDevice(currentIndex + 1);
  });

  // ─── [G3] 15번 변수 캐러셀 ───
  if (aiTotalEl) aiTotalEl.textContent = String(POWER_KEYS.length);
  if (aiPrev) aiPrev.addEventListener('click', function () {
    var idx = POWER_KEYS.indexOf(currentPowerKey);
    if (idx > 0) selectPowerVar(POWER_KEYS[idx - 1]);
  });
  if (aiNext) aiNext.addEventListener('click', function () {
    var idx = POWER_KEYS.indexOf(currentPowerKey);
    if (idx < POWER_KEYS.length - 1) selectPowerVar(POWER_KEYS[idx + 1]);
  });

  function selectPowerVar(key) {
    currentPowerKey = key;
    var idx = POWER_KEYS.indexOf(key);
    if (aiNameEl) aiNameEl.textContent = POWER_LABELS[key] || key;
    if (aiCurEl)  aiCurEl.textContent  = String(idx + 1);
    if (aiPrev)   aiPrev.disabled = (idx === 0);
    if (aiNext)   aiNext.disabled = (idx === POWER_KEYS.length - 1);
    refreshChartFromBuf();
    refreshAiCards();
    // [G2.3] 변수 변경 시 fetch 응답까지 loading 표시
    showAiLoading();
    if (typeof loadForecast === 'function') loadForecast();
  }
  // 초기 변수 표시는 chartPower 정의 후 (파일 하단) 호출 — [G3] 순서 안전

  // ─── 전력 sensor 목록 적용 (초기 fetch + sensorListChanged) ───
  function applyDeviceList(arr) {
    var fresh = arr
      .filter(function (d) { return d.sensor_type === 'power'; })
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

          // powerData 이벤트와 동일 shape: { device_id, power:{}, status }
          var rec = {
            device_id: dev.device_id,
            power: {
              current: row.current,
              voltage: row.voltage,
              watt:    row.watt,
              temp:    row.temp,
            },
            status: row.status || 'normal',
          };
          lastValueByDevice[dev.device_id] = rec;
          pushBuf(dev.device_id, rec.power);

          // 헤더 합산 와트
          var total = 0;
          for (var k in lastValueByDevice) {
            total += (lastValueByDevice[k].power && lastValueByDevice[k].power.watt) || 0;
          }
          if (totalWattEl) {
            var first = totalWattEl.firstChild;
            if (first && first.nodeType === Node.TEXT_NODE) {
              first.nodeValue = total.toFixed(0) + ' ';
            }
          }

          if (dev.device_id === currentDeviceId) {
            renderRow(rec);
            refreshChartFromBuf();
            refreshAiCards();
          }
        })
        .catch(function () { /* silent */ });
    });
  }

  fetch('/dashboard/api/device/?sensor_type=power')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var arr = Array.isArray(data) ? data : (data.results || []);
      applyDeviceList(arr);
    })
    .catch(function (e) {
      console.error('전력 센서 목록 로드 실패', e);
      if (nameEl) nameEl.textContent = '로드 실패';
    });

  SenSa.on('sensorListChanged', function (d) {
    if (!d || !d.all) return;
    applyDeviceList(d.all);
  });

  // ─── sensor 선택 (14번 캐러셀) ───
  function selectDevice(idx) {
    currentIndex = idx;
    currentDeviceId = devices[idx].device_id;

    if (nameEl)  nameEl.textContent  = devices[idx].device_name || devices[idx].device_id;
    if (curEl)   curEl.textContent   = String(idx + 1);
    if (totalEl) totalEl.textContent = String(devices.length);
    if (prevBtn) prevBtn.disabled = (idx === 0);
    if (nextBtn) nextBtn.disabled = (idx === devices.length - 1);

    if (lastValueByDevice[currentDeviceId]) {
      renderRow(lastValueByDevice[currentDeviceId]);
    } else {
      renderEmpty();
    }
    refreshChartFromBuf();
    refreshAiCards();
    // [G2.3] sensor 변경 시 fetch 응답까지 loading 표시
    showAiLoading();
    if (typeof loadForecast === 'function') loadForecast();
  }

  // ─── 행 렌더 (14번 테이블) ───
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
  // powerData 이벤트 수신 (실시간 WebSocket)
  // ═════════════════════════════════════════════════════════
  SenSa.on('powerData', function (d) {
    if (!d || !d.device_id || !d.power) return;

    lastValueByDevice[d.device_id] = d;
    pushBuf(d.device_id, d.power);

    // B-3 헤더 — 전체 합산 와트
    var total = 0;
    for (var k in lastValueByDevice) {
      total += (lastValueByDevice[k].power && lastValueByDevice[k].power.watt) || 0;
    }
    if (totalWattEl) {
      var first = totalWattEl.firstChild;
      if (first && first.nodeType === Node.TEXT_NODE) {
        first.nodeValue = total.toFixed(0) + ' ';
      }
    }

    // B-3 헤더 — 현재 설비 와트
    if (curWattEl) {
      var curWatt = (lastValueByDevice[currentDeviceId] &&
                     lastValueByDevice[currentDeviceId].power.watt) || 0;
      curWattEl.textContent = curWatt.toFixed(0);
    }

    if (d.device_id !== currentDeviceId) return;
    renderRow(d);
    refreshChartFromBuf();
    refreshAiCards();   // [G3] 현재값 카드 실시간 갱신
  });

  // ARIMA 예측값 수신 → 전류(current) 예측이면 점선으로 오버레이
  SenSa.on('aiPrediction', function (d) {
    if (!d || !d.device_id || !d.predicted_values) return;
    if (d.metric !== 'current') return;  // 전력 차트는 전류 기준

    predBufByDevice[d.device_id] = { values: d.predicted_values, ts: Date.now() };

    if (d.device_id === currentDeviceId) {
      refreshChartFromBuf();
    }
  });

  // ═════════════════════════════════════════════════════════
  // ⑮ 차트 — [G3] 변수 동적 (선택 변수만 표시) + AI 예측 점선
  // ═════════════════════════════════════════════════════════
  var POWER_CHART_MAX = 20;
  var FORECAST_HORIZON = 10;   // [G3] 차트에 표시할 예측 horizon

  function bufFor(deviceId) {
    if (!chartBufByDevice[deviceId]) {
      chartBufByDevice[deviceId] = { labels: [], values: {} };
      POWER_KEYS.forEach(function (k) {
        chartBufByDevice[deviceId].values[k] = [];
      });
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
        // [G3] AI 예측 라인 (마젠타 점선)
        { label: '예측',    data: [], borderColor: '#ff66ff', borderDash: [3, 3], borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.3, spanGaps: false },
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
    POWER_KEYS.forEach(function (k) {
      buf.values[k].push(power[k] !== undefined && power[k] !== null ? power[k] : null);
    });
    if (buf.labels.length > POWER_CHART_MAX) {
      buf.labels.shift();
      POWER_KEYS.forEach(function (k) { buf.values[k].shift(); });
    }
  }

  function refreshChartFromBuf() {
    if (typeof chartPower === 'undefined' || !chartPower) return;

    if (!currentDeviceId) {
      chartPower.data.labels = [];
      chartPower.data.datasets.forEach(function (d) { d.data = []; });
      chartPower.update();
      return;
    }
    var buf = bufFor(currentDeviceId);
    var key = currentPowerKey;
    var th = POWER_TH[key] || { w: null, d: null };
    var bufLen = buf.labels.length;

    // [G3] forecast 데이터 매칭
    var fc = null;
    if (currentForecast
        && currentForecast.metric === key
        && currentForecast.device_id === currentDeviceId
        && Array.isArray(currentForecast.predicted)) {
      fc = currentForecast.predicted.slice(0, FORECAST_HORIZON);
    }
    var fcLen = fc ? fc.length : 0;
    var totalLen = bufLen + fcLen;

    // 미래 시점 라벨
    var futureLabels = [];
    for (var i = 1; i <= fcLen; i++) futureLabels.push('+' + i);
    chartPower.data.labels = buf.labels.concat(futureLabels);

    // dataset[0] 실제값 — buf + null padding
    var actualData = (buf.values[key] || []).slice();
    for (var j = 0; j < fcLen; j++) actualData.push(null);
    chartPower.data.datasets[0].label = POWER_LABELS[key] || key;
    chartPower.data.datasets[0].data = actualData;

    // dataset[1, 2] 임계선
    if (th.w !== null && th.w !== undefined) {
      chartPower.data.datasets[1].data = Array(totalLen).fill(th.w);
    } else {
      chartPower.data.datasets[1].data = [];
    }
    if (th.d !== null && th.d !== undefined) {
      chartPower.data.datasets[2].data = Array(totalLen).fill(th.d);
    } else {
      chartPower.data.datasets[2].data = [];
    }

    // [G3] dataset[3] AI 예측
    if (fcLen > 0 && bufLen > 0) {
      var forecastData = Array(bufLen - 1).fill(null);
      var lastActual = buf.values[key][bufLen - 1];
      forecastData.push(lastActual !== undefined && lastActual !== null ? lastActual : null);
      forecastData = forecastData.concat(fc);
      chartPower.data.datasets[3].data = forecastData;
    } else {
      chartPower.data.datasets[3].data = [];
    }

    chartPower.update();
  }

  // [G3] 변수 캐러셀 초기화 — chartPower 정의 이후
  selectPowerVar(currentPowerKey);

  // ═════════════════════════════════════════════════════════
  // [G3] AI 카드 — forecast API 기반 + 위험도 색상 동적
  // ═════════════════════════════════════════════════════════
  function riskClassFromMessage(msg) {
    if (!msg) return 'accuracy';
    if (msg === '정상') return 'success';
    if (msg.indexOf('즉시 조치') !== -1
        || msg.indexOf('이상 급증') !== -1
        || msg.indexOf('산소 농도 이상') !== -1) return 'failure';
    if (msg.indexOf('주의') !== -1
        || msg.indexOf('위험 가능성') !== -1
        || msg.indexOf('위험 도달') !== -1
        || msg.indexOf('상승 추세') !== -1
        || msg.indexOf('시간 내 위험') !== -1) return 'caution';
    return 'accuracy';
  }

  function refreshAiCards() {
    var unit = POWER_UNITS[currentPowerKey] || '';

    // 현재 값 — WS 캐시 우선
    if (aiCurrentEl) {
      var rec = lastValueByDevice[currentDeviceId];
      var v = (rec && rec.power && rec.power[currentPowerKey] !== undefined && rec.power[currentPowerKey] !== null)
        ? rec.power[currentPowerKey] : null;
      // fallback forecast.current_value
      if (v === null && currentForecast
          && currentForecast.device_id === currentDeviceId
          && currentForecast.metric === currentPowerKey
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

    // AI 예측 메시지 + 색상
    if (aiForecastEl) {
      var card = aiForecastEl.closest('.ai-perf-card');
      var msg = (currentForecast
                 && currentForecast.device_id === currentDeviceId
                 && currentForecast.metric === currentPowerKey
                 && currentForecast.risk_message) ? currentForecast.risk_message : null;

      aiForecastEl.textContent = msg || '—';

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
    if (!currentDeviceId || !currentPowerKey) {
      currentForecast = null;
      refreshAiCards();
      refreshChartFromBuf();
      return;
    }
    var url = '/dashboard/api/ai-forecast/'
            + '?device_id=' + encodeURIComponent(currentDeviceId)
            + '&metric=' + encodeURIComponent(currentPowerKey)
            + '&horizon=20';
    fetch(url, { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        currentForecast = d;
        refreshAiCards();
        refreshChartFromBuf();
      })
      .catch(function () { /* silent */ });
  }

  loadForecast();
  setInterval(loadForecast, 10000);

})();
