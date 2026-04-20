/**
 * section_11_workers.js — ⑪ 작업자 현황 도넛 차트
 *
 * [변경] workersLoaded 이벤트 수신 → DB의 작업자 수로 도넛 차트 갱신
 */

// ─── 도넛 차트 초기화 (0명으로 시작) ───
var workerDonut = new Chart(document.getElementById('worker-donut'), {
  type: 'doughnut',
  data: {
    labels: ['정상', '주의', '위험'],
    datasets: [{
      data: [0, 0, 0],
      backgroundColor: ['#2ecc71', '#f1c40f', '#e74c3c'],
      borderWidth: 0
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: true,
    cutout: '65%',
    plugins: { legend: { display: false } }
  },
});

/**
 * [신규] workersLoaded 이벤트 수신 → 작업자 수 반영
 * 초기 상태에서는 전원 '정상'으로 표시
 */
SenSa.on('workersLoaded', function (d) {
  var total = d.workers.length;

  // 도넛 차트: 전원 정상으로 초기화
  workerDonut.data.datasets[0].data = [total, 0, 0];
  workerDonut.update();

  // 숫자 표시 갱신
  var elNormal  = document.getElementById('worker-normal-count');
  var elCaution = document.getElementById('worker-caution-count');
  var elDanger  = document.getElementById('worker-danger-count');
  var elTotal   = document.getElementById('worker-total');

  if (elNormal)  elNormal.textContent  = total;
  if (elCaution) elCaution.textContent = 0;
  if (elDanger)  elDanger.textContent  = 0;
  if (elTotal)   elTotal.textContent   = total;
});