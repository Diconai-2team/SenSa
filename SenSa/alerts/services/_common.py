"""
alerts/services/_common.py — 알람 서비스 모듈들이 공유하는 상수.

분리 이력 (Phase 3):
  원래 alerts/services.py 상단에 있던 알람 주기 상수를 분리.
  worker_evaluator, sensor_evaluator 둘 다 import.
"""
from django.conf import settings


# ═══════════════════════════════════════════════════════════
# 알람 타이밍 상수
# ═══════════════════════════════════════════════════════════

# 지속 상태 재알림 주기 (초)
RE_ALARM_INTERVAL_SEC = getattr(settings, 'ALARM_RE_ALARM_INTERVAL_SEC', 60)

# 회복(recovery) 상태로 전이를 확정하기까지 필요한 연속 tick 수
# (잠깐의 측정 노이즈로 인한 false recovery 방지)
RECOVERY_CONFIRM_TICKS = getattr(settings, 'ALARM_RECOVERY_CONFIRM_TICKS', 5)

# caution 격상 확정에 필요한 연속 tick 수
# (스파이크 노이즈로 인한 false alarm 방지 — danger는 즉시 발화 유지)
# v1 잔존 — v2 윈도우 로직이 sensor 쪽 대체. worker_evaluator 호환 유지용.
CAUTION_CONFIRM_TICKS = getattr(settings, 'ALARM_CAUTION_CONFIRM_TICKS', 5)


# ═══════════════════════════════════════════════════════════
# v2: 윈도우 누적 (V자 진동 환경 대응 — Celery/generator 신호 충돌)
# ═══════════════════════════════════════════════════════════

# 격상 (caution/danger): 윈도우 안 observed_status별 누적 임계 도달 시 확정.
# 평상시(시나리오 OFF) 노이즈 1~2회로는 절대 채울 수 없음.
# 시나리오 작동 시 (Celery 0.5s 주기) ~2.5초만에 5회 도달.
CAUTION_WINDOW_SEC       = getattr(settings, 'ALARM_CAUTION_WINDOW_SEC', 10.0)
CAUTION_COUNT_THRESHOLD  = getattr(settings, 'ALARM_CAUTION_COUNT_THRESHOLD', 5)
DANGER_COUNT_THRESHOLD   = getattr(settings, 'ALARM_DANGER_COUNT_THRESHOLD', 5)

# 격하 (recovery): 더 보수적 — 윈도우 안 normal 7회 누적 시 확정.
RECOVERY_WINDOW_SEC      = getattr(settings, 'ALARM_RECOVERY_WINDOW_SEC', 10.0)
RECOVERY_COUNT_THRESHOLD = getattr(settings, 'ALARM_RECOVERY_COUNT_THRESHOLD', 7)
