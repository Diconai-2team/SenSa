/**
 * section_11_workers.js — ⑪ 작업자 현황 (실시간 지오펜스 연동)
 *
 * 기능:
 *   - Worker API 로드 → 도넛 차트 + 목록 초기화
 *   - 매 초 workerMove 수신 → 클라이언트 point-in-polygon 으로 지오펜스 판별
 *   - 도넛 차트 & 개별 목록 실시간 갱신
 *
 * 구독 이벤트:
 *   sensa:workersLoaded → 초기 목록 생성
 *   sensa:workerMove    → 매 초 위치 갱신 → 지오펜스 체크 → 차트 갱신
 */
(function () {

  // ─── 도넛 차트 초기화 ───
  var workerDonut = new Chart(document.getElementById('worker-donut'), {
    type: 'doughnut',
    data: {
      labels: ['정상', '주의', '위험'],
      datasets: [{
        data: [0, 0, 0],
        backgroundColor: ['#2ecc71', '#f1c40f', '#e74c3c'],
        borderWidth: 0,
        hoverBorderWidth: 2,
        hoverBorderColor: '#fff',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: '68%',
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      animation: { duration: 400, easing: 'easeOutQuart' },
    },
  });

  // ─── 지오펜스 데이터 (API에서 1회 로드) ───
  var fences = [];

  async function loadFences() {
    try {
      var res = await fetch('/dashboard/api/geofence/');
      var data = await res.json();
      fences = data.results || data;
      console.log('[section_11] 지오펜스 로드:', fences.length, '개');
      console.log('[section_11] 첫 번째 펜스:', JSON.stringify(fences[0]));
    } catch (e) {
      console.warn('[section_11] 지오펜스 로드 실패:', e);
    }
  }
  loadFences();

  // ─── 클라이언트 point-in-polygon (Ray Casting) ───
  function pointInPolygon(x, y, polygon) {
    var n = polygon.length;
    if (n < 3) return false;
    var inside = false, j = n - 1;
    for (var i = 0; i < n; i++) {
      var xi = polygon[i][0], yi = polygon[i][1];
      var xj = polygon[j][0], yj = polygon[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
        inside = !inside;
      }
      j = i;
    }
    return inside;
  }

  // ─── 작업자별 지오펜스 상태 판별 ───
  function classifyWorkerZone(w) {
    if (fences.length === 0) {
      console.warn('[section_11] fences 비어있음!');
      return { status: 'normal', zone: '' };
    }
    var worst = 'normal';
    var zoneName = '';

    for (var i = 0; i < fences.length; i++) {
      var f = fences[i];
      if (!f.polygon || f.polygon.length < 3) continue;

      if (pointInPolygon(w.x, w.y, f.polygon)) {
        var level = f.zone_type === 'danger' ? 'danger'
                  : f.zone_type === 'restricted' ? 'danger'
                  : f.zone_type === 'caution' ? 'caution'
                  : 'caution';

        if (level === 'danger') {
          return { status: 'danger', zone: f.name };
        }
        if (level === 'caution' && worst === 'normal') {
          worst = 'caution';
          zoneName = f.name;
        }
      }
    }
    return { status: worst, zone: zoneName };
  }

  // ─── 작업자 상태 캐시 ───
  var workerStatuses = {};
  var ZONE_LABELS = { normal: '안전', caution: '주의구역', danger: '위험구역' };

  // ─── 목록 렌더링 ───
  function renderWorkerList(workers) {
    var list = document.getElementById('worker-status-list');
    if (!list) return;

    list.innerHTML = workers.map(function (w) {
      var info = workerStatuses[w.worker_id] || { status: 'normal', zone: '' };
      var s = info.status;
      var zoneText = info.zone || ZONE_LABELS[s];

      return '<div class="worker-row status-' + s + '" data-worker="' + w.worker_id + '">' +
        '<div class="worker-icon">👷</div>' +
        '<span class="worker-name">' + w.name + '</span>' +
        '<span class="worker-dept">' + (w.department || '') + '</span>' +
        '<span class="worker-zone-badge zone-' + s + '">' + zoneText + '</span>' +
      '</div>';
    }).join('');
  }

  // ─── 차트 + 카운트 갱신 ───
  function updateChart(workers) {
    var counts = { normal: 0, caution: 0, danger: 0 };

    workers.forEach(function (w) {
      var info = classifyWorkerZone(w);
      workerStatuses[w.worker_id] = info;
      counts[info.status]++;
    });

    // 도넛 데이터
    workerDonut.data.datasets[0].data = [counts.normal, counts.caution, counts.danger];
    workerDonut.update();

    // 숫자 표시
    var elNormal  = document.getElementById('worker-normal-count');
    var elCaution = document.getElementById('worker-caution-count');
    var elDanger  = document.getElementById('worker-danger-count');
    var elTotal   = document.getElementById('worker-total');

    if (elNormal)  elNormal.textContent  = counts.normal;
    if (elCaution) elCaution.textContent = counts.caution;
    if (elDanger)  elDanger.textContent  = counts.danger;
    if (elTotal)   elTotal.textContent   = workers.length;

    // 개별 목록
    renderWorkerList(workers);
  }

  // ─── 이벤트 구독 ───

  // 초기 로드: 전원 정상으로 표시
  SenSa.on('workersLoaded', function (d) {
    updateChart(d.workers);
  });

  // 매 초 위치 갱신: 지오펜스 체크 후 차트 갱신
  SenSa.on('workerMove', function (d) {
    updateChart(d.workers);
  });

})();