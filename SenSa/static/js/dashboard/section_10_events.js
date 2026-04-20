/**
 * section_10_events.js — ⑩ 이벤트 현황
 * 구독: sensa:alarm → 알람 패널에 추가
 */
var unreadCount = 0;
var EMOJI = { info: 'ℹ️', caution: '⚠️', danger: '🔴', critical: '🚨' };

SenSa.on('alarm', function (alarm) {
  var list = document.getElementById('alarm-list');
  var empty = list.querySelector('.alarm-empty'); if (empty) empty.remove();
  var item = document.createElement('div');
  item.className = 'alarm-item unread level-' + alarm.alarm_level;
  item.innerHTML = '<div class="alarm-msg">' + (EMOJI[alarm.alarm_level] || '⚠️') + ' ' + alarm.message + '</div><div class="alarm-meta">' + new Date().toLocaleTimeString('ko-KR') + '</div>';
  item.onclick = function () { item.classList.remove('unread'); markRead(alarm.alarm_id); unreadCount = Math.max(0, unreadCount - 1); updateBadge(); };
  list.insertBefore(item, list.firstChild);
  var all = list.querySelectorAll('.alarm-item'); if (all.length > 30) all[all.length - 1].remove();
  unreadCount++; updateBadge();
});

function updateBadge() { var b = document.getElementById('alarm-badge'); b.textContent = unreadCount; b.style.display = unreadCount > 0 ? 'inline' : 'none'; }
async function markRead(id) { try { await fetch('/dashboard/api/alarm/' + id + '/read/', { method: 'PATCH', headers: { 'X-CSRFToken': getCsrfToken() } }); } catch (e) {} }

window.readAllAlarms = async function () {
  try { await fetch('/dashboard/api/alarm/read_all/', { method: 'PATCH', headers: { 'X-CSRFToken': getCsrfToken() } });
    document.querySelectorAll('.alarm-item.unread').forEach(function (el) { el.classList.remove('unread'); });
    unreadCount = 0; updateBadge();
  } catch (e) {}
};
