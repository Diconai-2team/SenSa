/**
 * section_11_workers.js — ⑪ 작업자 현황 도넛 차트
 */
var workerDonut = new Chart(document.getElementById('worker-donut'), {
  type: 'doughnut',
  data: { labels: ['정상', '주의', '위험'], datasets: [{ data: [2, 0, 0], backgroundColor: ['#2ecc71', '#f1c40f', '#e74c3c'], borderWidth: 0 }] },
  options: { responsive: true, maintainAspectRatio: true, cutout: '65%', plugins: { legend: { display: false } } },
});
