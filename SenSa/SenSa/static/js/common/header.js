/**
 * common/header.js — 공통 헤더 동작
 *
 * [책임]
 *   1. 햄버거 버튼 ↔ 사이드메뉴 토글 (백드롭 클릭/ESC/닫기 버튼 모두 닫기)
 *   2. 시스템 시간 1초 갱신 (#system-time-now, #system-time-last)
 *
 * [왜 이 파일로 통합했나?]
 *   이전에 checklist.js / player.js / dashboard/base.js 가 각자 시스템 시간
 *   갱신 코드를 중복 갖고 있었음. 공통 헤더 도입을 계기로 단일 출처로 이관.
 *   페이지별 JS 는 시스템 시간 관련 코드를 제거해도 됨 (충돌 X. 다만 중복).
 */
(function () {
  'use strict';

  // ─────────────────────────────────────────────────────────
  // 1. 사이드메뉴 토글
  // ─────────────────────────────────────────────────────────
  var btnToggle = document.getElementById('btn-sidemenu-toggle');
  var btnClose  = document.getElementById('btn-sidemenu-close');
  var menu      = document.getElementById('app-sidemenu');
  var backdrop  = document.getElementById('app-sidemenu-backdrop');

  function openMenu() {
    if (!menu || !backdrop) return;
    menu.hidden = false;
    backdrop.hidden = false;
    if (btnToggle) btnToggle.setAttribute('aria-expanded', 'true');
    // 포커스 이동 — 접근성
    if (btnClose) btnClose.focus();
  }

  function closeMenu() {
    if (!menu || !backdrop) return;
    menu.hidden = true;
    backdrop.hidden = true;
    if (btnToggle) {
      btnToggle.setAttribute('aria-expanded', 'false');
      btnToggle.focus();
    }
  }

  if (btnToggle) btnToggle.addEventListener('click', openMenu);
  if (btnClose)  btnClose.addEventListener('click',  closeMenu);
  if (backdrop)  backdrop.addEventListener('click',  closeMenu);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && menu && !menu.hidden) {
      closeMenu();
    }
  });

  // ─────────────────────────────────────────────────────────
  // 2. 시스템 시간 1초 갱신
  // ─────────────────────────────────────────────────────────
  var nowEl  = document.getElementById('system-time-now');
  var lastEl = document.getElementById('system-time-last');

  if (nowEl) {
    var initial = formatTime(new Date());
    nowEl.textContent = initial;
    if (lastEl) lastEl.textContent = initial;

    setInterval(function () {
      nowEl.textContent = formatTime(new Date());
    }, 1000);
  }

  function formatTime(d) {
    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

})();