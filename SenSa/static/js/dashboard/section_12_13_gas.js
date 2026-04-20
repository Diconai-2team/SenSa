/**
 * section_12_13_gas.js — ⑫ 가스 테이블 + ⑬ 가스 차트
 * 구독: sensa:gasData → 테이블 값 갱신 + 차트 push
 */

// ─── 임계치 (테이블 배지용) ───
var TH = { co: { w: 25, d: 200 }, h2s: { w: 10, d: 50 }, co2: { w: 1000, d: 5000 } };
var LABELS = { normal: '정상', caution: '주의', danger: '위험' };

function gasFieldStatus(key, val) {
  if (key === 'o2') return (val < 18 || val > 25) ? 'danger' : (val < 19.5 || val > 23.5) ? 'caution' : 'normal';
  var t = TH[key]; if (!t) return 'normal';
  return val >= t.d ? 'danger' : val >= t.w ? 'caution' : 'normal';
}

var primaryGas = 'sensor_01';

document.querySelectorAll('.sensor-tab').forEach(function (btn) {
  btn.addEventListener('click', function () {
    primaryGas = this.dataset.sensor;
    document.querySelectorAll('.sensor-tab').forEach(function (b) { b.classList.remove('active'); });
    this.classList.add('active');
  });
});

SenSa.on('gasData', function (d) {
  if (d.device_id !== primaryGas) return;
  var gas = d.gas;
  ['o2', 'co', 'co2', 'h2s'].forEach(function (k) {
    var el = document.getElementById('val-' + k); if (el) el.textContent = gas[k];
    var badge = document.getElementById('badge-' + k);
    if (badge) { var s = gasFieldStatus(k, gas[k]); badge.className = 'status-badge status-' + s; badge.textContent = LABELS[s]; }
  });
  pushChart(gas);
});

// ─── ⑬ 차트 ───
var CHART_MAX = 20, buf = { labels: [], co: [] };
var chartGas = new Chart(document.getElementById('chart-gas'), {
  type: 'line',
  data: { labels: [], datasets: [
    { label: 'CO', data: [], borderColor: '#00c8ff', backgroundColor: 'rgba(0,200,255,0.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 1 },
    { label: '주의', data: [], borderColor: '#ffcc00', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
    { label: '위험', data: [], borderColor: '#ff4444', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
  ] },
  options: { responsive: true, maintainAspectRatio: false, animation: { duration: 200 }, plugins: { legend: { display: false } },
    scales: { x: { ticks: { color: '#406080', font: { size: 8 }, maxTicksLimit: 5 }, grid: { color: '#1a2040' } }, y: { ticks: { color: '#406080', font: { size: 8 } }, grid: { color: '#1a2040' } } } },
});

function pushChart(gas) {
  var now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  buf.labels.push(now); buf.co.push(gas.co);
  if (buf.labels.length > CHART_MAX) { buf.labels.shift(); buf.co.shift(); }
  chartGas.data.labels = buf.labels;
  chartGas.data.datasets[0].data = buf.co;
  chartGas.data.datasets[1].data = Array(buf.labels.length).fill(25);
  chartGas.data.datasets[2].data = Array(buf.labels.length).fill(200);
  chartGas.update();
}
