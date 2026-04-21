/**
 * section_12_13_gas.js — ⑫ 가스 테이블(9종) + ⑬ 가스 차트
 *
 * 구독: sensa:gasData → 9종 테이블 값 갱신 + 차트 push
 *
 * IIFE로 감싸서 전역 변수 충돌 방지
 */
(function () {

  var TH = {
    co:  { w: 25,   d: 200  },
    h2s: { w: 10,   d: 15   },
    co2: { w: 1000, d: 5000 },
    no2: { w: 3,    d: 5    },
    so2: { w: 2,    d: 5    },
    o3:  { w: 0.06, d: 0.12 },
    nh3: { w: 25,   d: 35   },
    voc: { w: 0.5,  d: 1.0  },
  };
  var LABELS = { normal: '정상', caution: '주의', danger: '위험' };

  function gasFieldStatus(key, val) {
    if (val === undefined || val === null) return 'normal';
    if (key === 'o2') {
      if (val < 16 || val >= 23.5) return 'danger';
      if (val < 18 || val > 21.5)  return 'caution';
      return 'normal';
    }
    var t = TH[key];
    if (!t) return 'normal';
    return val >= t.d ? 'danger' : val >= t.w ? 'caution' : 'normal';
  }

  // ─── 센서 탭 전환 ───
  var primaryGas = 'sensor_01';

  document.querySelectorAll('.sensor-tab').forEach(function (btn) {
    btn.addEventListener('click', function () {
      primaryGas = this.dataset.sensor;
      document.querySelectorAll('.sensor-tab').forEach(function (b) { b.classList.remove('active'); });
      this.classList.add('active');
    });
  });

  // ─── ⑬ 차트 초기화 (IIFE 수준에서 한 번만) ───
  var GAS_CHART_MAX = 20;
  var gasBuf = { labels: [], co: [] };

  var chartGas = new Chart(document.getElementById('chart-gas'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'CO',   data: [], borderColor: '#00c8ff', backgroundColor: 'rgba(0,200,255,0.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 1 },
        { label: '주의', data: [], borderColor: '#ffcc00', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
        { label: '위험', data: [], borderColor: '#ff4444', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
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

  function pushChart(gas) {
    var now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    gasBuf.labels.push(now);
    gasBuf.co.push(gas.co);
    if (gasBuf.labels.length > GAS_CHART_MAX) {
      gasBuf.labels.shift();
      gasBuf.co.shift();
    }
    chartGas.data.labels = gasBuf.labels;
    chartGas.data.datasets[0].data = gasBuf.co;
    chartGas.data.datasets[1].data = Array(gasBuf.labels.length).fill(25);
    chartGas.data.datasets[2].data = Array(gasBuf.labels.length).fill(200);
    chartGas.update();
  }

  // ─── ⑫ 가스 테이블 갱신 ───
  SenSa.on('gasData', function (d) {
    if (d.device_id !== primaryGas) return;
    var gas = d.gas;
    ['o2', 'co', 'co2', 'h2s', 'no2', 'so2', 'o3', 'nh3', 'voc'].forEach(function (k) {
      var el = document.getElementById('val-' + k);
      if (el) el.textContent = gas[k];
      var badge = document.getElementById('badge-' + k);
      if (badge) {
        var s = gasFieldStatus(k, gas[k]);
        badge.className = 'status-badge status-' + s;
        badge.textContent = LABELS[s];
      }
    });
    pushChart(gas);
  });

})();
