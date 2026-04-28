/**
 * section_11_workers.js — ⑪ 작업자 현황 (실시간 지오펜스 연동)
 *
 * [변경 이력]
 *   v1 (원형):
 *     workersLoaded 시 차트 그리고, workerMove 시 받은 workers 배열로 전체 재렌더.
 *     하지만 workerMove 는 개별 작업자 1명을 {workers: [w]} 형태로 발사
 *     (base.js L330 의 SenSa.emit('workerMove', { workers: [w] })).
 *     매 초마다 1명짜리 배열로 updateChart 가 호출되어 화면 전체가 1명만 표시되는 버그.
 *
 *   v2 (본 변경):
 *     workersMaster 배열로 마스터 목록 유지.
 *     workerMove 도착 시 해당 작업자의 x, y, movement_status 만 갱신.
 *     updateChart 는 항상 마스터 목록 전체로 호출 → 모든 작업자가 항상 표시됨.
 *
 *     마스터에 없는 worker_id 의 movement 가 도착하면 새 작업자로 간주하고 push.
 *     (FastAPI 재시작 등으로 신규 작업자가 합류한 케이스 대비)
 *
 * 기능:
 *   - Worker API 로드 → 도넛 차트 + 목록 초기화
 *   - 매 초 workerMove 수신 → 해당 작업자 좌표 갱신 → 전체 목록 기준 차트/목록 재렌더
 *
 * 구독 이벤트:
 *   sensa:workersLoaded { workers } → 초기 목록 생성 + 마스터 목록 보존
 *   sensa:workerMove    { workers: [w] } → 단일 작업자 부분 갱신
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

  // ═════════════════════════════════════════════════════════
  // 작업자 마스터 목록 + 상태 캐시 (v2)
  //   - workersLoaded 시 초기화
  //   - workerMove 시 해당 작업자의 좌표/상태만 갱신
  //   - updateChart 는 항상 마스터 목록 전체로 호출
  // ═════════════════════════════════════════════════════════
  var workersMaster = [];
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

  // 초기 로드: 마스터 목록 보존 + 전원 정상으로 표시
  SenSa.on('workersLoaded', function (d) {
    workersMaster = (d.workers || []).slice();
    console.log('[section_11] 마스터 목록 초기화:', workersMaster.length, '명');
    updateChart(workersMaster);
  });

  // 매 초 위치 갱신: 마스터 목록의 해당 작업자만 좌표 갱신 후 전체 다시 그림
  SenSa.on('workerMove', function (d) {
    if (!d || !d.workers || d.workers.length === 0) return;

    // workerMove 는 개별 작업자 1명을 [w] 형태로 보냄 (base.js L330)
    var moved = d.workers[0];
    var found = false;

    for (var i = 0; i < workersMaster.length; i++) {
      if (workersMaster[i].worker_id === moved.worker_id) {
        workersMaster[i].x = moved.x;
        workersMaster[i].y = moved.y;
        if (moved.movement_status !== undefined) {
          workersMaster[i].movement_status = moved.movement_status;
        }
        found = true;
        break;
      }
    }

    // 마스터에 없는 작업자가 도착 → 신규 합류로 간주하여 push
    // (FastAPI 재시작 등으로 새 작업자 인식 케이스)
    if (!found) {
      workersMaster.push(moved);
      console.log('[section_11] 신규 작업자 합류:', moved.worker_id);
    }

    updateChart(workersMaster);
  });

})();