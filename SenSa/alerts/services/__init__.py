"""
alerts/services/ — 상태 전이 기반 알람 서비스 패키지.

[Phase 3 분리 — 2026-05-06]
  원본: 단일 alerts/services.py (647줄, 6개 섹션 혼재)
  현행: 도메인별 5개 모듈

4가지 알람 규칙 (원본 docstring 그대로):
  1. 특이점 발생 시 즉시 알람 (전이 감지 시 디바운스 우회)
  2. 같은 사건 중복 억제 (상태 유지 중에는 재생성 안 함)
  3. 미해결 상태 60초 지속 시 재알림 (지속 경고)
  4. 국면 전환 알람 (악화/회복 모두)

상태 정의 (엄격도 순):
  'safe' < 'caution' < 'danger' < 'critical'
  critical = restricted(출입금지) 구역 안

호환성 — 외부 4개 public API 그대로 유지:
  from alerts.services import classify_gas, classify_power      # devices/views.py
  from alerts.services import evaluate_worker, evaluate_sensor  # dashboard/views.py

모듈 매핑:
  _common.py          — 알람 타이밍 상수 (RE_ALARM_INTERVAL_SEC, RECOVERY_CONFIRM_TICKS)
  classifiers.py      — classify_gas, classify_power, _get_24h_avg_watt
  geofence_utils.py   — _find_containing_geofences, _find_sensor_geofence
  worker_evaluator.py — evaluate_worker + 5개 helper (작업자 axis)
  sensor_evaluator.py — evaluate_sensor + 3개 helper (센서 axis)
"""
# ─── classifiers (외부 직접 사용) ───
from .classifiers import classify_gas, classify_power

# ─── 메인 진입점 (외부 직접 사용) ───
from .worker_evaluator import evaluate_worker
from .sensor_evaluator import evaluate_sensor


__all__ = [
    'classify_gas',
    'classify_power',
    'evaluate_worker',
    'evaluate_sensor',
]
