"""
alerts/services/classifiers.py — 센서값 → 상태 판정 함수.

순수/준-순수 판정 로직만 담당. 외부 호출 가능 (`devices/views.py` 가 직접 사용).

  - classify_gas(gas)            — 9종 가스 worst 상태 ('normal'/'caution'/'danger')
  - classify_power(power, dev)   — 전력 동적 임계치 (24h 중앙값 기반)
  - _get_24h_avg_watt(dev)       — 내부 헬퍼 (24시간 watt 중앙값)

GAS_THRESHOLDS 의 값은 UI (static/js/dashboard/section_12_13_gas.js, base.js) 의
GAS_TH 와 일치해야 뱃지/알람 레벨이 같음.
"""
import statistics
from datetime import timedelta

from django.utils import timezone


# ═══════════════════════════════════════════════════════════
# 가스 판정 — 9종 (Gas 전담 팀원 공식 기준)
# ═══════════════════════════════════════════════════════════
# 출처: static/js/dashboard/section_12_13_gas.js 의 TH
#       static/js/dashboard/base.js 의 GAS_TH
# 세 곳 모두 동일한 값을 써야 UI 뱃지와 서버 알람 레벨이 일치함.
#
# 철학: danger = IDLH 수준 (즉시 대피 필요)
#       caution = STEL 수준 (단시간 노출 허용 한계)
GAS_THRESHOLDS = {
    'co':  {'caution': 25,    'danger': 200  },  # ACGIH TWA / NIOSH Ceiling
    'h2s': {'caution': 10,    'danger': 50   },  # KOSHA 적정공기 / IDLH
    'co2': {'caution': 1000,  'danger': 5000 },  # 실내공기질 / TWA
    'no2': {'caution': 3,     'danger': 5    },  # 고용노동부 TWA / STEL
    'so2': {'caution': 2,     'danger': 5    },  # 고용노동부 TWA / STEL
    'o3':  {'caution': 0.05,  'danger': 0.1  },  # ACGIH TLV (light / heavy work)
    'nh3': {'caution': 25,    'danger': 50   },  # ACGIH TWA / 고노출 기준
    'voc': {'caution': 0.5,   'danger': 2.0  },  # TVOC 실내기준
    # o2 는 구간형 — classify_gas 내부 처리
}


def classify_gas(gas: dict) -> str:
    """
    9종 가스 측정값 dict 를 받아 worst 상태 반환 ('normal'/'caution'/'danger').

    O2 는 구간형 (양방향 임계) — 근거: 산업안전보건기준 제618조 + KOSHA
      < 16% 또는 >= 23.5% → danger
      < 18% 또는 > 21.5%  → caution
      18 ~ 21.5%          → normal
    나머지 8종: 단방향 (높을수록 위험)
    """
    worst = 'normal'
    for key, val in gas.items():
        if val is None:
            continue
        if key == 'o2':
            v = float(val)
            if v < 16 or v >= 23.5:
                return 'danger'
            if v < 18 or v > 21.5:
                worst = 'caution'
            continue
        t = GAS_THRESHOLDS.get(key)
        if not t:
            continue
        v = float(val)
        if v >= t['danger']:
            return 'danger'
        if v >= t['caution'] and worst == 'normal':
            worst = 'caution'
    return worst


# ═══════════════════════════════════════════════════════════
# 전력 판정 — 동적 24h 중앙값 기반 (Power 병합)
# ═══════════════════════════════════════════════════════════
# 근거:
#   산업용 설비의 전력 임계치는 설비마다 정격이 달라 고정값으로 판정하기 어려움.
#   평상시 평균의 배수로 이상 감지하는 것이 운영 표준.
#
# 중앙값(median) 사용 이유:
#   기동전류(정격의 5~8배) 같은 순간 스파이크에 강건함.
#   평균(mean) 대신 중앙값을 쓰면 극단값 영향을 받지 않음.
#
# 계수 산출:
#   산업용 설비 기준: 정격 = 평상시 평균 × 1.5 (여유율)
#   과부하 주의: 정격 × 1.1 → 평균 × 1.65
#   과부하 위험: 정격 × 1.5 → 평균 × 2.25

_POWER_RATED_RATIO   = 1.5
_POWER_CAUTION_MULT  = _POWER_RATED_RATIO * 1.1   # 1.65
_POWER_DANGER_MULT   = _POWER_RATED_RATIO * 1.5   # 2.25

# 동적 판정에 필요한 최소 샘플 수
# 개발/테스트: 초당 1건 × 180초 = 3분 치
# 운영 환경 : 초당 1건 × 86400 = 24시간 치 (상수 조정 필요)
_POWER_MIN_SAMPLES   = 180


def _get_24h_avg_watt(device_id: str) -> float | None:
    """
    최근 24시간 전력(watt) 측정값의 중앙값 반환.

    샘플이 _POWER_MIN_SAMPLES 미만이면 None 반환 → 호출자가 고정 임계치로 fallback.
    기동직후·리셋직후에 잘못된 동적 판정이 쌓이지 않도록 방어.
    """
    # 순환 import 방지 — 함수 내부 import
    from devices.models import SensorData

    cutoff = timezone.now() - timedelta(hours=24)
    values = list(
        SensorData.objects.filter(
            device__device_id=device_id,
            timestamp__gte=cutoff,
            watt__isnull=False,
        ).values_list('watt', flat=True)
    )
    if len(values) < _POWER_MIN_SAMPLES:
        return None
    return statistics.median(values)


def classify_power(power: dict, device_id: str = '') -> str:
    """
    전력 측정값 동적 임계치 분류.

    판정 순서:
      1. 전압 이상 (200V 미만 or 240V 초과) → danger (설비 안전 기준, 항상 고정)
      2. 24h 중앙값 기반 동적 판정 (샘플 충분할 때)
      3. 고정 임계치 fallback (샘플 부족 / device_id 미지정)

    Args:
        power: {'current': float, 'voltage': float, 'watt': float}
        device_id: 동적 판정 시 24h 중앙값 조회용. 빈 값이면 fallback.
    """
    watt = float(power.get('watt', 0))
    vol  = float(power.get('voltage', 220))
    cur  = float(power.get('current', 0))

    # 1. 전압 이상 — 항상 고정
    if vol < 200 or vol > 240:
        return 'danger'

    # 2. 동적 판정
    if device_id:
        avg = _get_24h_avg_watt(device_id)
        if avg and avg > 0:
            if watt > avg * _POWER_DANGER_MULT:
                return 'danger'
            if watt > avg * _POWER_CAUTION_MULT:
                return 'caution'
            return 'normal'

    # 3. 고정 임계치 fallback
    if cur >= 25 or watt >= 4500:
        return 'danger'
    if cur >= 15 or watt >= 3000:
        return 'caution'
    return 'normal'
