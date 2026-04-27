/**
 * vr_training/player.js — VR 안전 교육 가짜 플레이어 로직
 *
 * [동작 요약]
 *   - "재생" 버튼 클릭 → 가짜 재생 시작 (1초 간격 setInterval 로 현재 위치 증가)
 *   - 진행바는 pointer-events: none 이라 스킵 불가 (CSS 에서 차단)
 *   - 진행률 = currentTime / totalDuration × 100
 *   - currentTime 이 totalDuration 도달 → 완료 버튼 활성화
 *   - "이전" 버튼: 확인 모달 띄우고 서버에 현재 위치 저장 후 대시보드로
 *   - "완료" 버튼: 서버에 완료 API 호출 → 완료 모달 표시 → 대시보드로
 *   - beforeunload / visibilitychange: 자동 저장 (이탈 시점만)
 *
 * [불변식]
 *   currentTime 은 단조 증가만 (되감기 불가).
 *   페이지 재진입 시 서버 last_position 에서 이어서 재생.
 */
(function () {
  'use strict';

  var init = window.VR_TRAINING_INIT || {};
  if (!init.progressUrl || !init.completeUrl || !init.dashboardUrl) {
    console.error('[vr] VR_TRAINING_INIT 이 불완전합니다.');
    return;
  }

  // ─────────────────────────────────────────────────────────
  // 상태
  // ─────────────────────────────────────────────────────────
  var total = Math.max(1, Number(init.totalDuration) || 60);
  var current = Math.min(total, Math.max(0, Number(init.lastPosition) || 0));
  var isPlaying = false;
  var isCompleted = !!init.alreadyCompleted;
  var playTimer = null;        // setInterval 핸들
  var saveInFlight = false;    // 중복 저장 방지

  // ─────────────────────────────────────────────────────────
  // DOM
  // ─────────────────────────────────────────────────────────
  var $stage = document.getElementById('vr-stage');
  var $placeholder = document.getElementById('vr-stage-placeholder');
  var $playing = document.getElementById('vr-stage-playing');
  var $playBtn = document.getElementById('vr-play-btn');
  var $progressFill = document.getElementById('vr-progress-fill');
  var $timeCurrent = document.getElementById('vr-time-current');
  var $timeTotal = document.getElementById('vr-time-total');

  var $btnBack = document.getElementById('vr-btn-back');
  var $btnComplete = document.getElementById('vr-btn-complete');

  var $confirmModal = document.getElementById('vr-confirm-modal');
  var $confirmNo = document.getElementById('vr-confirm-no');
  var $confirmYes = document.getElementById('vr-confirm-yes');

  var $completeModal = document.getElementById('vr-complete-modal');
  var $completeConfirm = document.getElementById('vr-complete-confirm');

  var $todayDate = document.getElementById('vr-today-date');

  // ─────────────────────────────────────────────────────────
  // 초기 렌더
  // ─────────────────────────────────────────────────────────
  function init_render() {
    $timeTotal.textContent = formatSec(total);
    updateProgressUI();
    if (isCompleted) {
      // 이미 완료한 경우 — 완료 버튼 활성, 상태도 재생종료 형태로 표시
      current = total;
      $btnComplete.disabled = false;
      updateProgressUI();
      showPlayingStage();
      $playBtn.hidden = true;
    } else if (current > 0) {
      // 일부 시청 후 이어보기 — placeholder 대신 재생씬 미리 노출
      showPlayingStage();
      $playBtn.hidden = false;
    }
    renderTodayDate();
  }

  function renderTodayDate() {
    if (!$todayDate) return;
    var d = new Date();
    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    $todayDate.textContent = d.getFullYear() + ' / ' + pad(d.getMonth() + 1) + ' / ' + pad(d.getDate());
  }

  function updateProgressUI() {
    var pct = Math.min(100, (current / total) * 100);
    $progressFill.style.width = pct + '%';
    $timeCurrent.textContent = formatSec(current);

    // 100% 도달하면 완료 버튼 활성화
    if (current >= total) {
      $btnComplete.disabled = false;
    }
  }

  function formatSec(sec) {
    sec = Math.max(0, Math.floor(sec));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function showPlayingStage() {
    $placeholder.hidden = true;
    $playing.hidden = false;
  }

  function showPlaceholderStage() {
    $placeholder.hidden = false;
    $playing.hidden = true;
  }

  // ─────────────────────────────────────────────────────────
  // 재생/일시정지
  // ─────────────────────────────────────────────────────────
  function play() {
    if (isPlaying || current >= total) return;
    isPlaying = true;
    showPlayingStage();
    $playBtn.hidden = true;

    playTimer = setInterval(function () {
      current += 1;
      if (current >= total) {
        current = total;
        updateProgressUI();
        pause();   // 자동 정지
        return;
      }
      updateProgressUI();
    }, 1000);
  }

  function pause() {
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = null;
    }
    isPlaying = false;
    // 완료 지점이 아니면 재생버튼 다시 노출
    if (current < total) {
      $playBtn.hidden = false;
    }
  }

  $playBtn.addEventListener('click', play);

  // 스테이지 클릭으로도 일시정지 가능 — 버튼 외 영역
  $stage.addEventListener('click', function (e) {
    if (e.target === $playBtn || $playBtn.contains(e.target)) return;
    if (isPlaying) {
      pause();
      // 재생 중 일시정지는 서버 저장 타이밍 중 하나
      saveProgress();
    }
  });

  // ─────────────────────────────────────────────────────────
  // 서버 저장 (이탈 시점만)
  // ─────────────────────────────────────────────────────────
  function saveProgress() {
    if (saveInFlight) return;
    if (current <= 0) return;   // 의미 없는 0초 저장 생략
    saveInFlight = true;

    fetch(init.progressUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ position_sec: current }),
    })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .catch(function (e) { console.warn('[vr] progress save failed', e); })
      .finally(function () { saveInFlight = false; });
  }

  // sendBeacon 용 동기 저장 — 페이지 닫힐 때
  function saveProgressBeacon() {
    if (current <= 0) return;
    try {
      var blob = new Blob(
        [JSON.stringify({ position_sec: current })],
        { type: 'application/json' }
      );
      navigator.sendBeacon(init.progressUrl, blob);
    } catch (e) {
      // 일부 브라우저에서 sendBeacon 실패 가능 — 조용히 무시
    }
  }

  // ─────────────────────────────────────────────────────────
  // 이전 버튼 (확인 모달)
  // ─────────────────────────────────────────────────────────
  $btnBack.addEventListener('click', function () {
    pause();
    $confirmModal.hidden = false;
    $confirmYes.focus();
  });

  $confirmNo.addEventListener('click', function () {
    $confirmModal.hidden = true;
    // 계속 시청 — 상태 그대로 유지
  });

  $confirmYes.addEventListener('click', function () {
    // 중단 확정 — 현재 위치 저장 후 대시보드로
    $confirmYes.disabled = true;
    $confirmYes.textContent = '저장 중...';
    fetch(init.progressUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ position_sec: current }),
    })
      .catch(function () { /* 실패해도 이동은 강행 */ })
      .finally(function () {
        window.location.href = init.dashboardUrl;
      });
  });

  $confirmModal.addEventListener('click', function (e) {
    if (e.target === $confirmModal) {
      $confirmModal.hidden = true;
    }
  });

  // ─────────────────────────────────────────────────────────
  // 완료 버튼
  // ─────────────────────────────────────────────────────────
  $btnComplete.addEventListener('click', function () {
    if ($btnComplete.disabled) return;

    $btnComplete.disabled = true;
    $btnComplete.textContent = '처리 중...';

    // 1단계: 서버 last_position 을 total 로 끌어올리기 (서버 재검증 통과용)
    fetch(init.progressUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ position_sec: total }),   // 끝 지점 명시
    })
    // 2단계: 그 다음 complete 호출
    .then(function () {
      return fetch(init.completeUrl, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({}),
      });
    })
    .then(function (res) {
      return res.json().then(function (body) { return { ok: res.ok, body: body }; });
    })
    .then(function (r) {
      if (r.ok) {
        isCompleted = true;
        $completeModal.hidden = false;
        $completeConfirm.focus();
      } else {
        alert((r.body && r.body.message) || '완료 처리에 실패했습니다.');
        $btnComplete.disabled = false;
        $btnComplete.textContent = '완료';
      }
    })
    .catch(function (err) {
      console.error('[vr] complete error', err);
      alert('네트워크 오류로 완료 처리에 실패했습니다.');
      $btnComplete.disabled = false;
      $btnComplete.textContent = '완료';
    });
  });

  $completeConfirm.addEventListener('click', function () {
    window.location.href = init.dashboardUrl;
  });

  // ─────────────────────────────────────────────────────────
  // 자동 저장 — 페이지 이탈 시점
  // ─────────────────────────────────────────────────────────
  window.addEventListener('pagehide', function () {
    if (!isCompleted) saveProgressBeacon();
  });
  window.addEventListener('beforeunload', function () {
    if (!isCompleted) saveProgressBeacon();
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      if (!isCompleted) saveProgress();
    }
  });

  // ─────────────────────────────────────────────────────────
  // CSRF / 시스템 시간
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

  // 초기화 실행
  init_render();

})();