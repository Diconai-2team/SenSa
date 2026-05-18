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
RECOVERY_CONFIRM_TICKS = getattr(settings, 'ALARM_RECOVERY_CONFIRM_TICKS', 3)
