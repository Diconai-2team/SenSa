#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
패치: 알람 패널 UX 재설계 — 위험 우선순위 (평시 관제 한눈에 인지)
============================================================================

대상 파일 3개:
  1. SenSa/templates/dashboard/sections/section_10_events.html  — 위험 배지 추가
  2. SenSa/static/css/dashboard/section_10_events.css           — 위험 시각 강조
  3. SenSa/static/js/dashboard/section_10_events.js             — 정렬·sticky·배너 영속

변경 요약 (4가지 핵심):
  A. 위험 sticky pin   : 위험·심각 알람 항상 최상단, 30개 한도 제외
  B. 위험 시각 강조    : 빨간 배경 + 글로우 펄스 + 큰 폰트 + 5px 좌측 라인
  C. 위험 배너 영속    : 위험은 자동 닫기 ❌ (X 클릭 시만 닫힘)
  D. 위험 카운트 분리  : 빨간 큰 배지 (위험 미읽음만) + 기존 회색 배지

특성:
  - 멱등성: 'unreadDangerCount' 토큰으로 검출
  - 백업: 각 파일별 timestamp
  - HTML/CSS는 정적 파일 → docker compose up -d --build django 필요
"""

import sys
import re
import shutil
from datetime import datetime
from pathlib import Path


IDEMPOTENT_MARKER_JS = "unreadDangerCount"


def find_files():
    for root in [Path.cwd(), Path(__file__).resolve().parent]:
        html = root / "SenSa" / "templates" / "dashboard" / "sections" / "section_10_events.html"
        css = root / "SenSa" / "static" / "css" / "dashboard" / "section_10_events.css"
        js = root / "SenSa" / "static" / "js" / "dashboard" / "section_10_events.js"
        if all(p.exists() for p in [html, css, js]):
            return html, css, js
    return None, None, None


# ─────────────────────────────────────────────────────────────────────
# 1) HTML — 위험 배지 추가
# ─────────────────────────────────────────────────────────────────────
HTML_OLD = '    <span>이벤트 현황 <span id="alarm-badge">0</span></span>\n'
HTML_NEW = (
    '    <span>\n'
    '      이벤트 현황\n'
    '      <span id="alarm-badge-danger">🔴 0</span>\n'
    '      <span id="alarm-badge">0</span>\n'
    '    </span>\n'
)


# ─────────────────────────────────────────────────────────────────────
# 2) CSS — 위험 시각 강조 + 배지 스타일 추가
# ─────────────────────────────────────────────────────────────────────
CSS_OLD = ".alarm-item.level-danger   { border-left-color: var(--color-danger); }\n"

CSS_NEW = (
    ".alarm-item.level-danger   { border-left-color: var(--color-danger); }\n"
    "\n"
    "/* ═══ 위험 알람 강한 시각 강조 — 평시 관제 한눈에 인지 ═══ */\n"
    ".alarm-item.level-danger,\n"
    ".alarm-item.level-critical {\n"
    "  border-left-width: 5px;\n"
    "  background: linear-gradient(90deg, #2a0f0f 0%, #1a0a0a 100%);\n"
    "  box-shadow: 0 0 10px rgba(239, 68, 68, 0.4);\n"
    "  animation: danger-glow 1.6s ease-in-out infinite;\n"
    "}\n"
    ".alarm-item.level-danger.unread,\n"
    ".alarm-item.level-critical.unread {\n"
    "  background: linear-gradient(90deg, #3a1010 0%, #2a0a0a 100%);\n"
    "}\n"
    ".alarm-item.level-danger .alarm-msg,\n"
    ".alarm-item.level-critical .alarm-msg {\n"
    "  font-size: 13px;\n"
    "  font-weight: 700;\n"
    "  color: #ffb4b4;\n"
    "}\n"
    "@keyframes danger-glow {\n"
    "  0%, 100% { box-shadow: 0 0 10px rgba(239, 68, 68, 0.4); }\n"
    "  50%      { box-shadow: 0 0 18px rgba(239, 68, 68, 0.7); }\n"
    "}\n"
    "/* 위험과 일반 알람 사이 시각적 구분선 */\n"
    ".alarm-item.level-danger + .alarm-item:not(.level-danger):not(.level-critical),\n"
    ".alarm-item.level-critical + .alarm-item:not(.level-danger):not(.level-critical) {\n"
    "  margin-top: 8px;\n"
    "  border-top: 1px dashed var(--border);\n"
    "  padding-top: 12px;\n"
    "}\n"
    "/* 위험 미읽음 큰 배지 */\n"
    "#alarm-badge-danger {\n"
    "  display: none;\n"
    "  background: var(--color-danger);\n"
    "  color: #fff;\n"
    "  font-size: 11px;\n"
    "  font-weight: 800;\n"
    "  padding: 2px 8px;\n"
    "  border-radius: 10px;\n"
    "  margin-left: 6px;\n"
    "  animation: danger-glow 1.6s ease-in-out infinite;\n"
    "}\n"
)


# ─────────────────────────────────────────────────────────────────────
# 3) JS — 카운터 분리 + sticky pin + 배너 영속
# ─────────────────────────────────────────────────────────────────────
JS_VAR_OLD = "var unreadCount = 0;\nvar dangerCount24h  = 0;\n"
JS_VAR_NEW = "var unreadCount = 0;\nvar unreadDangerCount = 0;   // v3: 위험 미읽음 분리\nvar dangerCount24h  = 0;\n"

JS_BADGE_OLD = """function updateBadge() {
  var b = document.getElementById('alarm-badge');
  if (!b) return;
  b.textContent = unreadCount;
  b.style.display = unreadCount > 0 ? 'inline' : 'none';
}
"""

JS_BADGE_NEW = """function updateBadge() {
  // v3: 위험 배지 + 일반 배지 분리
  var b  = document.getElementById('alarm-badge');
  var bd = document.getElementById('alarm-badge-danger');
  if (b) {
    b.textContent = unreadCount;
    b.style.display = unreadCount > 0 ? 'inline' : 'none';
  }
  if (bd) {
    bd.textContent = '🔴 ' + unreadDangerCount;
    bd.style.display = unreadDangerCount > 0 ? 'inline' : 'none';
  }
}
"""

JS_INSERT_OLD = """  // 실시간 이벤트는 앞에, DB 로드는 뒤에 삽입
  if (fromDB) {
    list.appendChild(item);
  } else {
    list.insertBefore(item, list.firstChild);
  }

  // 최대 30개 유지
  var all = list.querySelectorAll('.alarm-item');
  if (all.length > 30) all[all.length - 1].remove();

  if (isUnread) { unreadCount++; updateBadge(); }
"""

JS_INSERT_NEW = """  // v3: 위험은 sticky pin (항상 최상단, 30개 한도 제외)
  var isDanger = (alarm.alarm_level === 'danger' || alarm.alarm_level === 'critical');

  if (isDanger) {
    // 위험·심각 → 최상단 sticky
    list.insertBefore(item, list.firstChild);
  } else if (fromDB) {
    // DB 로드(과거) → 뒤로
    list.appendChild(item);
  } else {
    // 실시간 비-위험 → 위험 영역 아래, 일반 영역 최상단
    var firstNonDanger = list.querySelector(
      '.alarm-item:not(.level-danger):not(.level-critical)'
    );
    if (firstNonDanger) list.insertBefore(item, firstNonDanger);
    else list.appendChild(item);
  }

  // 30개 한도 — 단 위험 알람은 항상 유지 (제거 대상에서 제외)
  var nonDanger = list.querySelectorAll(
    '.alarm-item:not(.level-danger):not(.level-critical)'
  );
  if (nonDanger.length > 30) nonDanger[nonDanger.length - 1].remove();

  if (isUnread) {
    unreadCount++;
    if (isDanger) unreadDangerCount++;
    updateBadge();
  }
"""

JS_CLICK_OLD = """    if (isUnread) { isUnread = false; unreadCount = Math.max(0, unreadCount - 1); updateBadge(); }
  };
"""

JS_CLICK_NEW = """    if (isUnread) {
      isUnread = false;
      unreadCount = Math.max(0, unreadCount - 1);
      // v3: 위험 카운터도 감소
      if (alarm.alarm_level === 'danger' || alarm.alarm_level === 'critical') {
        unreadDangerCount = Math.max(0, unreadDangerCount - 1);
      }
      updateBadge();
    }
  };
"""

JS_READALL_OLD = """    unreadCount = 0;
    updateBadge();
"""

JS_READALL_NEW = """    unreadCount = 0;
    unreadDangerCount = 0;   // v3: 위험 카운터 리셋
    updateBadge();
"""

JS_BANNER_OLD = """  clearTimeout(bannerTimer);
  // 위험/심각은 10초, 주의는 6초 후 자동 닫힘
  var duration = (alarm.alarm_level === 'caution') ? 6000 : 10000;
  bannerTimer = setTimeout(closeBanner, duration);
"""

JS_BANNER_NEW = """  clearTimeout(bannerTimer);
  // v3: 위험·심각은 자동 닫기 ❌ (사용자가 X 눌러야 닫힘) — 평시 관제 우선순위
  if (alarm.alarm_level === 'danger' || alarm.alarm_level === 'critical') {
    // bannerTimer 설정 안 함 — 영속 유지
  } else {
    var duration = (alarm.alarm_level === 'caution') ? 6000 : 10000;
    bannerTimer = setTimeout(closeBanner, duration);
  }
"""


def patch_file(path, replacements, label):
    src = path.read_text(encoding="utf-8")
    out = src
    for old, new in replacements:
        if old not in out:
            return False, f"[{label}] 패턴 매칭 실패 — 수동 편집 가능성"
        out = out.replace(old, new, 1)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{ts}")
    shutil.copy2(path, backup)
    path.write_text(out, encoding="utf-8")
    return True, backup.name


def rollback(applied):
    for path, backup_name in applied:
        b = path.with_name(backup_name)
        if b.exists():
            shutil.copy2(b, path)
            print(f"[롤백] {path.name} ← {backup_name}", file=sys.stderr)


def main():
    html, css, js = find_files()
    if html is None:
        print("[실패] 3개 대상 파일을 모두 찾을 수 없습니다.", file=sys.stderr)
        return 1

    print(f"[대상1] {html}")
    print(f"[대상2] {css}")
    print(f"[대상3] {js}")

    if IDEMPOTENT_MARKER_JS in js.read_text(encoding="utf-8"):
        print(f"[스킵] 이미 패치돼 있습니다 (marker='{IDEMPOTENT_MARKER_JS}').")
        return 0

    applied = []

    ok, msg = patch_file(html, [(HTML_OLD, HTML_NEW)], "html")
    if not ok:
        print(f"[실패] {msg}", file=sys.stderr)
        return 2
    applied.append((html, msg))
    print(f"[적용1] section_10_events.html — 위험 배지 추가 (백업 {msg})")

    ok, msg = patch_file(css, [(CSS_OLD, CSS_NEW)], "css")
    if not ok:
        print(f"[실패] {msg}", file=sys.stderr)
        rollback(applied)
        return 3
    applied.append((css, msg))
    print(f"[적용2] section_10_events.css — 위험 시각 강조 + 배지 스타일 (백업 {msg})")

    ok, msg = patch_file(js, [
        (JS_VAR_OLD, JS_VAR_NEW),
        (JS_BADGE_OLD, JS_BADGE_NEW),
        (JS_INSERT_OLD, JS_INSERT_NEW),
        (JS_CLICK_OLD, JS_CLICK_NEW),
        (JS_READALL_OLD, JS_READALL_NEW),
        (JS_BANNER_OLD, JS_BANNER_NEW),
    ], "js")
    if not ok:
        print(f"[실패] {msg}", file=sys.stderr)
        rollback(applied)
        return 4
    applied.append((js, msg))
    print(f"[적용3] section_10_events.js — sticky pin + 카운터 분리 + 배너 영속 (백업 {msg})")

    print()
    print("=" * 70)
    print("[성공] 알람 패널 UX 재설계 완료 (3 파일)")
    print("       다음 단계 (정적 파일 변경 → 재빌드 필수):")
    print("         docker compose up -d --build django")
    print("       검증:")
    print("         브라우저에서 Ctrl+F5 (강제 새로고침으로 캐시 클리어)")
    print("         R&D 패널 '다중 누출' 시연 시:")
    print("         - 위험 알람은 패널 최상단 sticky (안 밀림)")
    print("         - 위험 알람은 빨간 배경 + 글로우 펄스")
    print("         - 위험 배너는 X 누를 때까지 표시")
    print("         - 우상단 '이벤트 현황' 옆 빨간 배지 '🔴 N'")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
