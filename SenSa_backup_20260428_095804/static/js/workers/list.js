/**
 * workers/list.js — 작업자 현황 페이지 클라이언트 로직
 *
 * [책임]
 *   1. 페이지 진입 시 /workers/api/list/ 호출해 목록+요약 렌더
 *   2. 상태 필터 (위험/주의/정상 토글)
 *   3. 행 선택 체크박스 + "선택 알림 전송" 버튼 활성
 *   4. 행 클릭 → 우측 상세 패널 표시
 *   5. 알림 모달 (단일/선택/전체 3가지 진입)
 *   6. 발송 → POST + 완료 토스트
 */
(function () {
  'use strict';

  var init = window.WORKERS_INIT || {};
  if (!init.dataUrl || !init.notifyUrl) {
    console.error('[workers] WORKERS_INIT 미정의');
    return;
  }

  // ─────────────────────────────────────────────────────────
  // 상태
  // ─────────────────────────────────────────────────────────
  var allWorkers = [];                       // 서버에서 받은 전체 목록
  var selectedIds = new Set();                // 체크된 worker_id
  var activeFilters = new Set(['danger', 'caution', 'safe']);
  var currentDetailId = null;                 // 상세 패널에 표시 중인 worker_id
  var notifyContext = null;                   // {type, targetIds, targetLabel}

  // ─────────────────────────────────────────────────────────
  // DOM
  // ─────────────────────────────────────────────────────────
  var $tbody = document.getElementById('workers-tbody');
  var $total = document.getElementById('workers-total');
  var $checkedIn = document.getElementById('workers-checked-in');
  var $countDanger  = document.getElementById('count-danger');
  var $countCaution = document.getElementById('count-caution');
  var $countSafe    = document.getElementById('count-safe');
  var $checkAll     = document.getElementById('check-all');
  var $btnSelected  = document.getElementById('btn-notify-selected');
  var $btnAll       = document.getElementById('btn-notify-all');
  var $selectedCount = document.getElementById('selected-count');

  var $detailEmpty   = document.getElementById('detail-empty');
  var $detailContent = document.getElementById('detail-content');
  var $btnSingle     = document.getElementById('btn-notify-single');

  // 모달
  var $modal       = document.getElementById('notify-modal');
  var $modalTarget = document.getElementById('notify-target-display');
  var $modalInput  = document.getElementById('notify-message');
  var $modalCount  = document.getElementById('notify-char-count');
  var $btnCancel   = document.getElementById('btn-notify-cancel');
  var $btnSend     = document.getElementById('btn-notify-send');
  var $toast       = document.getElementById('notify-toast');
  var $toastText   = document.getElementById('notify-toast-text');

  // ─────────────────────────────────────────────────────────
  // 초기 로드
  // ─────────────────────────────────────────────────────────
  loadData();

  function loadData() {
    fetch(init.dataUrl, { credentials: 'include' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        allWorkers = data.workers || [];
        renderSummary(data.summary || {});
        renderTable();
      })
      .catch(function (err) {
        console.error('[workers] load error', err);
        $tbody.innerHTML =
          '<tr class="workers-empty"><td colspan="7">데이터를 불러올 수 없습니다.</td></tr>';
      });
  }

  // ─────────────────────────────────────────────────────────
  // 렌더
  // ─────────────────────────────────────────────────────────
  function renderSummary(sum) {
    $total.textContent     = sum.total || 0;
    $checkedIn.textContent = sum.checked_in || 0;
    var bs = sum.by_status || {};
    $countDanger.textContent  = bs.danger  || 0;
    $countCaution.textContent = bs.caution || 0;
    $countSafe.textContent    = bs.safe    || 0;
  }

  function renderTable() {
    var filtered = allWorkers.filter(function (w) {
      return activeFilters.has(w.status);
    });

    if (filtered.length === 0) {
      $tbody.innerHTML =
        '<tr class="workers-empty"><td colspan="7">표시할 작업자가 없습니다.</td></tr>';
      syncCheckAll();
      return;
    }

    var rows = filtered.map(function (w) {
      var isChecked = selectedIds.has(w.worker_id);
      var isSelectedRow = currentDetailId === w.worker_id;
      var connBadge = w.connection_ok
        ? '<span class="conn-badge ok"><span class="conn-badge-dot"></span>연결 정상</span>'
        : '<span class="conn-badge off"><span class="conn-badge-dot"></span>연결 끊김</span>';
      var statusLabel = { danger: '위험', caution: '주의', safe: '정상' }[w.status] || w.status;

      return (
        '<tr data-worker-id="' + escapeAttr(w.worker_id) + '"' +
        (w.connection_ok ? '' : ' class="is-disconnected"') +
        (isSelectedRow ? ' class="is-selected"' : '') + '>' +
          '<td class="col-select">' +
            '<input type="checkbox" class="row-check"' +
              (isChecked ? ' checked' : '') +
              ' aria-label="선택">' +
          '</td>' +
          '<td class="col-id">' +
            '<div style="font-weight:600;color:var(--text-strong)">' + escapeHtml(w.name) + '</div>' +
            '<div style="font-size:11px;color:var(--text-dim)">' + escapeHtml(w.worker_id) + '</div>' +
          '</td>' +
          '<td class="col-dept">' + escapeHtml(w.department || '-') + '</td>' +
          '<td class="col-zone">' + escapeHtml(w.zone_name || '-') + '</td>' +
          '<td class="col-seen">' + formatLastSeen(w.last_seen_at) + '</td>' +
          '<td class="col-conn">' + connBadge + '</td>' +
          '<td class="col-status">' +
            '<span class="status-badge ' + w.status + '">' + statusLabel + '</span>' +
          '</td>' +
        '</tr>'
      );
    });

    $tbody.innerHTML = rows.join('');
    syncCheckAll();
  }

  function formatLastSeen(iso) {
    if (!iso) return '-';
    try {
      var d = new Date(iso);
      function pad(n) { return n < 10 ? '0' + n : n; }
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
             ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    } catch (e) { return '-'; }
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function escapeAttr(s) { return escapeHtml(s); }

  // ─────────────────────────────────────────────────────────
  // 필터 칩
  // ─────────────────────────────────────────────────────────
  document.querySelectorAll('.workers-filter-chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var key = chip.dataset.filter;
      if (activeFilters.has(key)) {
        activeFilters.delete(key);
        chip.classList.remove('is-active');
      } else {
        activeFilters.add(key);
        chip.classList.add('is-active');
      }
      renderTable();
    });
  });

  // ─────────────────────────────────────────────────────────
  // 체크박스 (개별 / 전체)
  // ─────────────────────────────────────────────────────────
  $tbody.addEventListener('change', function (e) {
    if (!e.target.classList.contains('row-check')) return;
    var tr = e.target.closest('tr');
    if (!tr) return;
    var wid = tr.dataset.workerId;
    if (!wid) return;
    if (e.target.checked) {
      selectedIds.add(wid);
    } else {
      selectedIds.delete(wid);
    }
    updateSelectedButton();
    syncCheckAll();
  });

  $checkAll.addEventListener('change', function () {
    var boxes = $tbody.querySelectorAll('.row-check');
    boxes.forEach(function (cb) {
      var tr = cb.closest('tr');
      var wid = tr && tr.dataset.workerId;
      if (!wid) return;
      cb.checked = $checkAll.checked;
      if ($checkAll.checked) selectedIds.add(wid);
      else selectedIds.delete(wid);
    });
    updateSelectedButton();
  });

  function syncCheckAll() {
    var boxes = $tbody.querySelectorAll('.row-check');
    if (boxes.length === 0) {
      $checkAll.checked = false;
      $checkAll.indeterminate = false;
      return;
    }
    var checkedCount = 0;
    boxes.forEach(function (b) { if (b.checked) checkedCount++; });
    $checkAll.checked = checkedCount > 0 && checkedCount === boxes.length;
    $checkAll.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
  }

  function updateSelectedButton() {
    var n = selectedIds.size;
    $selectedCount.textContent = n;
    $btnSelected.disabled = n === 0;
  }

  // ─────────────────────────────────────────────────────────
  // 행 클릭 → 상세 패널
  // ─────────────────────────────────────────────────────────
  $tbody.addEventListener('click', function (e) {
    // 체크박스/라벨 클릭은 선택 전환으로만
    if (e.target.closest('.col-select')) return;
    var tr = e.target.closest('tr');
    if (!tr || !tr.dataset.workerId) return;
    var wid = tr.dataset.workerId;
    showDetail(wid);
  });

  function showDetail(workerId) {
    var w = allWorkers.find(function (x) { return x.worker_id === workerId; });
    if (!w) return;
    currentDetailId = workerId;

    // 제목 영역 (3 곳)
    document.getElementById('detail-worker-name').textContent   = w.name;
    document.getElementById('detail-worker-name-2').textContent = w.name;
    document.getElementById('detail-worker-name-3').textContent = w.name;

    // 위치
    document.getElementById('detail-zone-name').textContent = w.zone_name || '지정된 구역 외';

    // 프로필
    document.getElementById('detail-name').textContent     = w.name || '-';
    document.getElementById('detail-id').textContent       = w.worker_id;
    document.getElementById('detail-dept').textContent     = w.department || '-';
    document.getElementById('detail-position').textContent = w.position || '-';
    document.getElementById('detail-email').textContent    = w.email || '-';
    document.getElementById('detail-phone').textContent    = w.phone || '-';

    $detailEmpty.hidden = true;
    $detailContent.hidden = false;

    // 행 하이라이트 갱신
    renderTable();
  }

  // ─────────────────────────────────────────────────────────
  // 알림 모달 — 3가지 진입
  // ─────────────────────────────────────────────────────────
  $btnSelected.addEventListener('click', function () {
    if (selectedIds.size === 0) return;
    openNotifyModal({
      type: 'selected',
      targetIds: Array.from(selectedIds),
      targetLabel: '선택된 작업자 ' + selectedIds.size + '명',
    });
  });

  $btnAll.addEventListener('click', function () {
    openNotifyModal({
      type: 'all',
      targetIds: [],   // 서버가 전체 조회
      targetLabel: '전체 작업자 ' + (allWorkers.length) + '명',
    });
  });

  $btnSingle.addEventListener('click', function () {
    if (!currentDetailId) return;
    var w = allWorkers.find(function (x) { return x.worker_id === currentDetailId; });
    if (!w) return;
    openNotifyModal({
      type: 'single',
      targetIds: [currentDetailId],
      targetLabel: w.name + ' (' + w.worker_id + ')',
    });
  });

  function openNotifyModal(ctx) {
    notifyContext = ctx;
    $modalTarget.textContent = ctx.targetLabel;
    $modalInput.value = '';
    $modalCount.textContent = '0';
    $modal.hidden = false;
    setTimeout(function () { $modalInput.focus(); }, 50);
  }

  function closeNotifyModal() {
    $modal.hidden = true;
    notifyContext = null;
  }

  $btnCancel.addEventListener('click', closeNotifyModal);
  $modal.addEventListener('click', function (e) {
    if (e.target === $modal) closeNotifyModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !$modal.hidden) closeNotifyModal();
  });

  // 글자수 카운터
  $modalInput.addEventListener('input', function () {
    $modalCount.textContent = $modalInput.value.length;
  });

  // 발송
  $btnSend.addEventListener('click', function () {
    if (!notifyContext) return;
    var msg = $modalInput.value.trim();
    if (!msg) {
      alert('메시지를 입력해주세요.');
      $modalInput.focus();
      return;
    }

    $btnSend.disabled = true;
    $btnSend.textContent = '발송 중...';

    fetch(init.notifyUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({
        send_type: notifyContext.type,
        recipients: notifyContext.targetIds,
        message: msg,
      }),
    })
      .then(function (res) {
        return res.json().then(function (body) { return { ok: res.ok, body: body }; });
      })
      .then(function (r) {
        if (r.ok) {
          closeNotifyModal();
          showToast('알림이 발송되었습니다. (수신 ' + r.body.recipient_count + '명)');
          // 선택 해제
          if (notifyContext && notifyContext.type === 'selected') {
            selectedIds.clear();
            updateSelectedButton();
            renderTable();
          }
        } else {
          alert((r.body && r.body.message) || '발송에 실패했습니다.');
        }
      })
      .catch(function (err) {
        console.error('[workers] notify error', err);
        alert('네트워크 오류로 발송에 실패했습니다.');
      })
      .finally(function () {
        $btnSend.disabled = false;
        $btnSend.textContent = '발송';
      });
  });

  // ─────────────────────────────────────────────────────────
  // 토스트
  // ─────────────────────────────────────────────────────────
  var toastTimer = null;
  function showToast(msg) {
    $toastText.textContent = msg;
    $toast.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      $toast.hidden = true;
    }, 3000);
  }

  // ─────────────────────────────────────────────────────────
  // CSRF
  // ─────────────────────────────────────────────────────────
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var c = document.cookie.split(';').find(function (c) {
      return c.trim().startsWith('csrftoken=');
    });
    return c ? c.split('=')[1] : '';
  }

})();
