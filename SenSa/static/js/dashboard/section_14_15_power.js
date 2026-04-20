/**
 * section_14_15_power.js — ⑭ 전력 테이블 + ⑮ 전력 차트
 *
 * 구독: sensa:powerData → 테이블 갱신 + 차트 push
 *
 * IIFE로 감싸서 전역 변수 충돌 방지
 * (section_12_13_gas.js도 같은 이름의 변수를 쓰기 때문)
 */
(function () {

  var LABELS = { normal: '정상', caution: '주의', danger: '위험' };
  var DEVICE_NAMES = { power_01: '스마트파워 A', power_02: '스마트파워 B' };
  var DEVICE_ROWS  = { power_01: 'power-row-1', power_02: 'power-row-2' };
  var powerCache = {};

  SenSa.on('powerData', function (d) {
    powerCache[d.device_id] = d;

    // 테이블 행 업데이트
    var row = document.getElementById(DEVICE_ROWS[d.device_id]);
    if (row) {
      var sc = 'status-' + d.status;

      // 해당 행(<tr>)에 위험도 클래스 적용 (id는 유지, className만 갱신)
      row.className = 'row-' + d.status;

      row.innerHTML = '<td class="gas-name">' + (DEVICE_NAMES[d.device_id] || d.device_id) + '</td>' +
        '<td class="gas-value">' + d.power.current + ' A</td>' +
        '<td class="gas-value">' + d.power.voltage + ' V</td>' +
        '<td><span class="status-badge ' + sc + '">' + LABELS[d.status] + '</span></td>';
    }

    // 총 전력
    var total = 0;
    for (var k in powerCache) total += powerCache[k].power.watt || 0;
    var el = document.getElementById('power-total-watt');
    if (el) el.innerHTML = total.toFixed(0) + ' <span class="unit">W</span>';

    // 차트 (첫 번째 전력 센서 기준)
    if (d.device_id === 'power_01') pushPowerChart(d.power);
  });

  // ─── ⑮ 차트 ───
  var POWER_CHART_MAX = 20;
  var powerBuf = { labels: [], current: [] };

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

  function pushPowerChart(power) {
    var now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    powerBuf.labels.push(now);
    powerBuf.current.push(power.current);
    if (powerBuf.labels.length > POWER_CHART_MAX) {
      powerBuf.labels.shift();
      powerBuf.current.shift();
    }
    chartPower.data.labels = powerBuf.labels;
    chartPower.data.datasets[0].data = powerBuf.current;
    chartPower.data.datasets[1].data = Array(powerBuf.labels.length).fill(15);
    chartPower.data.datasets[2].data = Array(powerBuf.labels.length).fill(25);
    chartPower.update();
  }

})();