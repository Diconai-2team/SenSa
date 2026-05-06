/**
 * safety/checklist.js — 작업 전 안전 확인 체크리스트 클라이언트 로직
 *
 * [변경 이력]
 *   v1: 초기 구현
 *   v2: 완료 모달 "확인" 버튼 → VR 교육 페이지로 이동 (Figma 흐름 부합)
 *
 * [책임]
 *   1. 체크박스 상태 → "다음" 버튼 활성/비활성 토글
 *   2. 취소 버튼 → 모든 체크 해제 후 대시보드 복귀
 *   3. 다음 버튼 → 서버에 POST 제출, 성공 시 완료 모달 표시
 *   4. 유효성 오류 — 미체크 항목 속한 카테고리에 .has-error 클래스 부여
 *   5. 완료 모달 "확인" → VR 교육 페이지로 이동
 *   6. 시스템 시간 표시
 */
(function () {
  'use strict';

  var init = window.SAFETY_CHECKLIST_INIT || {};
  if (!init.submitUrl || !init.dashboardUrl || !init.vrTrainingUrl) {
    console.error('[safety] SAFETY_CHECKLIST_INIT 이 불완전합니다. 템플릿 확인 필요.');
    return;
  }

  // ─────────────────────────────────────────────────────────
  // DOM 캐시
  // ─────────────────────────────────────────────────────────
  var panel   = document.getElementById('checklist-panel');
  var checkboxes = Array.prototype.slice.call(
    document.querySelectorAll('.checklist-checkbox')
  );
  var btnNext   = document.getElementById('btn-next');
  var btnCancel = document.getElementById('btn-cancel');
  var modal     = document.getElementById('complete-modal');
  var btnConfirm = document.getElementById('btn-complete-confirm');

  if (!panel || checkboxes.length === 0) {
    console.warn('[safety] 체크리스트 DOM 을 찾지 못함.');
    return;
  }

  // ─────────────────────────────────────────────────────────
  // 1. 체크 상태 → 다음 버튼 활성화 동기화
  // ─────────────────────────────────────────────────────────
  function syncNextButtonState() {
    var allChecked = checkboxes.every(function (cb) { return cb.checked; });
    btnNext.disabled = !allChecked;

    if (allChecked) {
      clearAllErrors();
    } else {
      refreshCategoryErrors();
    }
  }

  function clearAllErrors() {
    document.querySelectorAll('.checklist-category.has-error')
      .forEach(function (c) { c.classList.remove('has-error'); });
  }

  function refreshCategoryErrors() {
    document.querySelectorAll('.checklist-category.has-error')
      .forEach(function (cat) {
        var boxes = cat.querySelectorAll('.checklist-checkbox');
        var allOk = Array.prototype.every.call(boxes, function (b) { return b.checked; });
        if (allOk) cat.classList.remove('has-error');
      });
  }

  checkboxes.forEach(function (cb) {
    cb.addEventListener('change', syncNextButtonState);
  });

  syncNextButtonState();

  // ─────────────────────────────────────────────────────────
  // 2. 취소 버튼
  // ─────────────────────────────────────────────────────────
  btnCancel.addEventListener('click', function () {
    checkboxes.forEach(function (cb) { cb.checked = false; });
    hideModal();
    window.location.href = init.dashboardUrl;
  });

  // ─────────────────────────────────────────────────────────
  // 3. 다음 버튼 — 서버 제출
  // ─────────────────────────────────────────────────────────
  btnNext.addEventListener('click', function () {
    var unchecked = checkboxes.filter(function (cb) { return !cb.checked; });
    if (unchecked.length > 0) {
      markMissingCategories(unchecked);
      var first = document.querySelector('.checklist-category.has-error');
      if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    submitChecklist();
  });

  function markMissingCategories(uncheckedBoxes) {
    uncheckedBoxes.forEach(function (cb) {
      var cat = cb.closest('.checklist-category');
      if (cat) cat.classList.add('has-error');
    });
  }

  function submitChecklist() {
    var checkedKeys = checkboxes
      .filter(function (cb) { return cb.checked; })
      .map(function (cb) { return cb.dataset.key; });

    btnNext.disabled = true;
    btnNext.textContent = '제출 중...';

    fetch(init.submitUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ checked_items: checkedKeys }),
    })
      .then(function (res) {
        return res.json().then(function (body) { return { ok: res.ok, body: body }; });
      })
      .then(function (r) {
        if (r.ok) {
          showModal();
        } else if (r.body && r.body.status === 'incomplete') {
          highlightMissingByKeys(r.body.missing_keys || []);
          alert(r.body.message || '모든 항목을 체크해주세요.');
        } else {
          alert((r.body && r.body.message) || '제출 중 오류가 발생했습니다.');
        }
      })
      .catch(function (err) {
        console.error('[safety] submit error:', err);
        alert('네트워크 오류로 제출에 실패했습니다.');
      })
      .finally(function () {
        btnNext.textContent = '다음';
        syncNextButtonState();
      });
  }

  function highlightMissingByKeys(keys) {
    keys.forEach(function (key) {
      var cb = document.querySelector(
        '.checklist-checkbox[data-key="' + key + '"]'
      );
      if (cb) {
        var cat = cb.closest('.checklist-category');
        if (cat) cat.classList.add('has-error');
      }
    });
  }

  // ─────────────────────────────────────────────────────────
  // 4. 완료 모달 — "확인" → VR 교육 페이지로 이동
  // ─────────────────────────────────────────────────────────
  function showModal() {
    modal.hidden = false;
    btnConfirm.focus();
  }
  function hideModal() {
    modal.hidden = true;
  }

  btnConfirm.addEventListener('click', function () {
    // v2 변경점: 대시보드 대신 VR 교육 페이지로
    window.location.href = init.vrTrainingUrl;
  });

  // ESC / 백드롭 클릭으로 모달 닫기 (이동은 안 함 — 사용자가 모달에서 직접 나갔으니)
  modal.addEventListener('click', function (e) {
    if (e.target === modal) hideModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.hidden) hideModal();
  });

  // ─────────────────────────────────────────────────────────
  // 5. CSRF / 6. 시스템 시간
  // ─────────────────────────────────────────────────────────
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var c = document.cookie.split(';').find(function (c) {
      return c.trim().startsWith('csrftoken=');
    });
    return c ? c.split('=')[1] : '';
  }

  var nowEl  = document.getElementById('system-time-now');
  var lastEl = document.getElementById('system-time-last');
  if (nowEl) {
    var started = formatTime(new Date());
    if (lastEl) lastEl.textContent = started;
    setInterval(function () {
      nowEl.textContent = formatTime(new Date());
    }, 1000);
    nowEl.textContent = started;
  }

  function formatTime(d) {
    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

})();