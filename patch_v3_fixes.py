#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
패치 v3: 알람 중복·미실시간·확산 부족 동시 해결
============================================================================

대상 파일 2개:
  1. SenSa/alerts/services/sensor_evaluator.py
     (a) observed==official 시 격하 카운터 리셋 → V자 진동 차단
     (b) Alarm 생성 직후 publish_alarm() 호출 → WebSocket 실시간 push

  2. SenSa/geofence/scenarios/operational_multi.py
     LEAK_ELAPSED_SEC 15 → 45 (시작 반경 30→91px, sensor_05/06 포함)

전제: 모든 이전 패치 적용된 상태 (alarm_window_v2 포함).

해결되는 문제:
  - 위험 알람 7~10초 주기 반복 발화 → 60초 throttle 정상 작동
  - 새로고침해야 위험 알람 보임 → 실시간 push
  - 좌측 토스트에 위험 없음 → publish_alarm으로 자동 해결
  - sensor_05/06 변동성 없음 → 확산 반경 확대
"""

import sys
import re
import shutil
import ast
from datetime import datetime
from pathlib import Path


IDEMPOTENT_MARKER = "V자 진동 차단"


def find_files():
    for root in [Path.cwd(), Path(__file__).resolve().parent]:
        evaluator = root / "SenSa" / "alerts" / "services" / "sensor_evaluator.py"
        multi = root / "SenSa" / "geofence" / "scenarios" / "operational_multi.py"
        if all(p.exists() for p in [evaluator, multi]):
            return evaluator, multi
    return None, None


# ─────────────────────────────────────────────────────────────────────
# 1) sensor_evaluator.py
# ─────────────────────────────────────────────────────────────────────

# import에 publish_alarm + logger 추가
EVAL_IMPORT_OLD = """from ..state_store import (
    get_sensor_snapshot, commit_sensor_state,
    set_sensor_pending, clear_sensor_pending,
    # v2: 윈도우 카운터
    set_sensor_window_counter, clear_sensor_window_counters,
)
"""

EVAL_IMPORT_NEW = """from ..state_store import (
    get_sensor_snapshot, commit_sensor_state,
    set_sensor_pending, clear_sensor_pending,
    # v2: 윈도우 카운터
    set_sensor_window_counter, clear_sensor_window_counters,
)
# v3: 알람 실시간 WebSocket push
from realtime.publishers import publish_alarm
import logging
logger = logging.getLogger(__name__)

# v3: 상태 순위 (V자 진동 차단용)
_STATE_RANK = {'normal': 0, 'caution': 1, 'danger': 2}
"""

# observed==official 분기에 격하 카운터 리셋 추가
EVAL_SAME_STATE_OLD = """    if observed_status == official_state:
        # observed가 official과 같으면 카운터 건드리지 않음
        # (윈도우는 시간 만료로 자연 처리됨)
        pass
"""

EVAL_SAME_STATE_NEW = """    if observed_status == official_state:
        # v3: V자 진동 차단 — 격하 방향 카운터들 리셋
        # observed==official 신호가 들어오면 \"상태 유지\" 의미.
        # 격하 카운터(official보다 안전한 상태)를 0으로 리셋해서
        # 반대 source(예: generator normal)가 누적시킨 false 격하 진행을 차단.
        # 격상 카운터는 그대로 — 진짜 격상 진행은 보호.
        official_rank = _STATE_RANK.get(official_state, 0)
        for st in ('normal', 'caution', 'danger'):
            if _STATE_RANK[st] < official_rank:
                set_sensor_window_counter(device_id, st, 0, 0)
"""

# Alarm 생성 직후 publish_alarm 호출 추가
EVAL_PUBLISH_OLD = """        created.append({
            'alarm_id':      alarm.id,
            'alarm_type':    alarm_type,
            'alarm_level':   alarm_level,
            'device_id':     device_id,
            'sensor_type':   sensor_type,
            'geofence_id':   fence.id if fence else None,
            'geofence_name': fence.name if fence else '',
            'message':       message,
            'reason':        reason,
            'state_from':    official_state,
            'state_to':      target_state,
            'is_ai':         is_ai,
        })
"""

EVAL_PUBLISH_NEW = """        alarm_payload = {
            'alarm_id':      alarm.id,
            'alarm_type':    alarm_type,
            'alarm_level':   alarm_level,
            'device_id':     device_id,
            'sensor_type':   sensor_type,
            'geofence_id':   fence.id if fence else None,
            'geofence_name': fence.name if fence else '',
            'message':       message,
            'reason':        reason,
            'state_from':    official_state,
            'state_to':      target_state,
            'is_ai':         is_ai,
            'created_at':    alarm.created_at.isoformat(),
        }
        created.append(alarm_payload)

        # v3: WebSocket 실시간 push (frontend 알람 패널 + 좌측 토스트 즉시 갱신)
        # devices/views.py 경로의 publish_alarm과 동일 페이로드.
        # 시나리오 sustain_spike_task가 직접 evaluate_sensor 호출하는 경로에서
        # 이전엔 DB 저장만 하고 push 누락 → frontend 새로고침해야만 보였음.
        try:
            publish_alarm(alarm_payload)
        except Exception as e:
            logger.warning('[evaluate_sensor] publish_alarm 실패: %s', e)
"""


# ─────────────────────────────────────────────────────────────────────
# 2) operational_multi.py — LEAK_ELAPSED_SEC 확대
# ─────────────────────────────────────────────────────────────────────
MULTI_OLD = """    LEAK_ELAPSED_SEC = 15        # 초기 누출 직후 시점 — zone 작게 시작 (반경 ~30px)
"""

MULTI_NEW = """    LEAK_ELAPSED_SEC = 45        # v3: 30→91px 시작 반경 — 인접 sensor (05/06 등) 영향 sensor 포함
"""


def patch_file(path, replacements, label):
    src = path.read_text(encoding="utf-8")
    out = src
    for old, new in replacements:
        if old not in out:
            return False, f"[{label}] 패턴 매칭 실패 — 이전 패치 미적용 또는 수동 편집"
        out = out.replace(old, new, 1)
    try:
        ast.parse(out)
    except SyntaxError as e:
        return False, f"[{label}] AST 파싱 실패: {e}"
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
    evaluator, multi = find_files()
    if evaluator is None:
        print("[실패] 2개 대상 파일을 찾을 수 없습니다.", file=sys.stderr)
        return 1

    print(f"[대상1] {evaluator}")
    print(f"[대상2] {multi}")

    if IDEMPOTENT_MARKER in evaluator.read_text(encoding="utf-8"):
        print(f"[스킵] 이미 v3 패치돼 있습니다 (marker='{IDEMPOTENT_MARKER}').")
        return 0

    # v2 적용 확인
    if "CAUTION_WINDOW_SEC" not in evaluator.read_text(encoding="utf-8"):
        print("[실패] v2(윈도우 누적) 미적용 상태.", file=sys.stderr)
        print("       alarm_window_patch_v2.zip 먼저 적용 후 v3 실행.", file=sys.stderr)
        return 2

    applied = []

    ok, msg = patch_file(evaluator, [
        (EVAL_IMPORT_OLD, EVAL_IMPORT_NEW),
        (EVAL_SAME_STATE_OLD, EVAL_SAME_STATE_NEW),
        (EVAL_PUBLISH_OLD, EVAL_PUBLISH_NEW),
    ], "evaluator")
    if not ok:
        print(f"[실패] {msg}", file=sys.stderr)
        return 3
    applied.append((evaluator, msg))
    print(f"[적용1] sensor_evaluator.py — V자 진동 차단 + publish_alarm 호출 (백업 {msg})")

    ok, msg = patch_file(multi, [(MULTI_OLD, MULTI_NEW)], "multi")
    if not ok:
        print(f"[실패] {msg}", file=sys.stderr)
        rollback(applied)
        return 4
    applied.append((multi, msg))
    print(f"[적용2] operational_multi.py — LEAK_ELAPSED_SEC 15→45 (백업 {msg})")

    print()
    print("=" * 70)
    print("[성공] v3 패치 완료 (2 파일)")
    print("       다음 단계:")
    print("         docker compose up -d --build django celery")
    print("       시연 후 기대:")
    print("         - 위험 알람 transition 1회 + ongoing 60초마다 1회 (중복 사라짐)")
    print("         - 알람 즉시 우측 패널 + 좌측 토스트 표시 (새로고침 불필요)")
    print("         - sensor_05/06 시계열에 spike 변동성 등장")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
