/**
 * section_10_events.js — ⑩ 이벤트 현황
 *
 * 기능:
 *   - 페이지 로드 시 DB에서 최근 알람 50건 불러오기
 *   - 24시간 위험/주의 카운트 표시 (stats API)
 *   - sensa:alarm 실시간 구독 → 패널에 즉시 추가 + 경고 배너 표시
 *   - 읽음 처리 (단건 / 전체)
 */

var unreadCount = 0;
var dangerCount24h  = 0;
var cautionCount24h = 0;
var EMOJI = { info: 'ℹ️', caution: '⚠️', danger: '🔴', critical: '🚨' };
var bannerTimer = null;

// ── 배너 ──────────────────────────────────────────
function showBanner(alarm) {
  var banner  = document.getElementById('alert-banner');
  var content = document.getElementById('alert-banner-content');
  if (!banner || !content) return;

  banner.className = (alarm.alarm_level === 'caution') ? 'level-caution' : '';
  content.innerHTML =
    '<strong>' + (EMOJI[alarm.alarm_level] || '⚠️') + ' ' +
    (alarm.alarm_level === 'critical' ? '심각' :
     alarm.alarm_level === 'danger'   ? '위험' :
     alarm.alarm_level === 'caution'  ? '주의' : '정보') +
    '</strong>&nbsp;' + alarm.message;

  banner.style.display = 'flex';

  clearTimeout(bannerTimer);
  // 위험/심각은 10초, 주의는 6초 후 자동 닫힘
  var duration = (alarm.alarm_level === 'caution') ? 6000 : 10000;
  bannerTimer = setTimeout(closeBanner, duration);
}

window.closeBanner = function () {
  var banner = document.getElementById('alert-banner');
  if (banner) banner.style.display = 'none';
  clearTimeout(bannerTimer);
};

// ── 카운터 업데이트 ────────────────────────────────
function updateBadge() {
  var b = document.getElementById('alarm-badge');
  if (!b) return;
  b.textContent = unreadCount;
  b.style.display = unreadCount > 0 ? 'inline' : 'none';
}

function updateSummary() {
  var d = document.querySelector('.count-danger');
  var c = document.querySelector('.count-caution');
  if (d) d.textContent = '위험 ' + dangerCount24h  + ' 건';
  if (c) c.textContent = '주의 ' + cautionCount24h + ' 건';
}

// ── 패널에 알람 아이템 추가 ───────────────────────
function addAlarmToPanel(alarm, fromDB) {
  var list  = document.getElementById('alarm-list');
  if (!list) return;
  var empty = list.querySelector('.alarm-empty');
  if (empty) empty.remove();

  var item = document.createElement('div');
  var isUnread = !alarm.is_read;
  item.className = 'alarm-item' + (isUnread ? ' unread' : '') + ' level-' + alarm.alarm_level;
  item.dataset.alarmId = alarm.alarm_id || alarm.id || '';

  var ts = alarm.created_at
    ? new Date(alarm.created_at).toLocaleTimeString('ko-KR')
    : new Date().toLocaleTimeString('ko-KR');

  item.innerHTML =
    '<div class="alarm-msg">' + (EMOJI[alarm.alarm_level] || '⚠️') + ' ' + alarm.message + '</div>' +
    '<div class="alarm-meta">' + ts + (alarm.worker_name ? ' · ' + alarm.worker_name : '') + '</div>';

  item.onclick = function () {
    item.classList.remove('unread');
    var id = item.dataset.alarmId;
    if (id) markRead(id);
    if (isUnread) { isUnread = false; unreadCount = Math.max(0, unreadCount - 1); updateBadge(); }
  };

  // 실시간 이벤트는 앞에, DB 로드는 뒤에 삽입
  if (fromDB) {
    list.appendChild(item);
  } else {
    list.insertBefore(item, list.firstChild);
  }

  // 최대 30개 유지
  var all = list.querySelectorAll('.alarm-item');
  if (all.length > 30) all[all.length - 1].remove();

  if (isUnread) { unreadCount++; updateBadge(); }
}

// ── DB에서 최근 알람 로드 ─────────────────────────
async function loadAlarmsFromDB() {
  try {
    var res = await fetch('/dashboard/api/alarm/', { credentials: 'include' });
    if (!res.ok) return;
    var data = await res.json();
    var alarms = (data.results || data).slice().reverse(); // 오래된 순 → 아래 쌓임
    alarms.forEach(function (a) { addAlarmToPanel(a, true); });
    updateBadge();
  } catch (e) {}
}

// ── 24시간 통계 ───────────────────────────────────
async function refresh24hStats() {
  try {
    var res = await fetch('/dashboard/api/alarm/stats/', { credentials: 'include' });
    if (!res.ok) return;
    var data = await res.json();
    dangerCount24h  = data.danger  || 0;
    cautionCount24h = data.caution || 0;
    updateSummary();
  } catch (e) {}
}

// ── 읽음 처리 ─────────────────────────────────────
async function markRead(id) {
  if (!id) return;
  try {
    await fetch('/dashboard/api/alarm/' + id + '/read/', {
      method: 'PATCH',
      headers: { 'X-CSRFToken': getCsrfToken() },
      credentials: 'include',
    });
  } catch (e) {}
}

window.readAllAlarms = async function () {
  try {
    await fetch('/dashboard/api/alarm/read_all/', {
      method: 'PATCH',
      headers: { 'X-CSRFToken': getCsrfToken() },
      credentials: 'include',
    });
    document.querySelectorAll('.alarm-item.unread').forEach(function (el) {
      el.classList.remove('unread');
    });
    unreadCount = 0;
    updateBadge();
  } catch (e) {}
};

// ── 실시간 알람 구독 ──────────────────────────────
SenSa.on('alarm', function (alarm) {
  addAlarmToPanel(alarm, false);

  // 위험/심각/주의 카운터 즉시 반영
  if (alarm.alarm_level === 'danger' || alarm.alarm_level === 'critical') {
    dangerCount24h++;
  } else if (alarm.alarm_level === 'caution') {
    cautionCount24h++;
  }
  updateSummary();

  // 임계치 초과 시 경고 배너 표시
  if (alarm.alarm_level !== 'info') {
    showBanner(alarm);
  }
});

// ── 초기화 ────────────────────────────────────────
loadAlarmsFromDB();
refresh24hStats();

// 5분마다 24h 통계 갱신
setInterval(refresh24hStats, 5 * 60 * 1000);
