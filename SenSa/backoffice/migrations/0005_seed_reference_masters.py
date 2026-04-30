"""
0005_seed_reference_masters — 코어 마스터 시드 데이터

내용:
  - 공통 코드 그룹 7종 + 각 그룹의 기본 코드들
  - 위험 분류 7종 + 핵심 위험 유형들
  - 위험 기준 (알람 단계) 4종 — 정상/주의/경고/위험
  - 임계치 분류 4종 + GAS 분류의 임계치 9종 (현행 GAS_THRESHOLDS 와 100% 일치)

원칙:
  - 모두 idempotent (get_or_create) — 운영 DB 사용자 데이터 보존
  - 시스템 시드는 is_system=True 로 표시 (UI 에서 삭제 불가 처리)
  - **임계치 시드는 fastapi_generator/generators.py 의 GAS_THRESHOLDS 와 정확히 일치해야 함**
    배포 직후 시스템 동작이 절대 바뀌지 않음 (값을 DB 로 옮기기만 함)
"""

from django.db import migrations


# ───────────────────────────────────────────────────────────
# 공통 코드
# ───────────────────────────────────────────────────────────
CODE_GROUPS = [
    # (code, name, sort_order, codes)
    (
        "DEVICE_TYPE",
        "장비 유형",
        10,
        [
            ("GAS_SENSOR", "유해가스 센서"),
            ("SMART_POWER", "스마트 전력 시스템"),
            ("LOCATION_NODE", "위치 노드"),
            ("FACILITY", "설비"),
        ],
    ),
    (
        "COMM_METHOD",
        "통신 방식",
        20,
        [
            ("TCP", "TCP"),
            ("MQTT", "MQTT"),
            ("MODBUS", "Modbus"),
            ("HTTP", "HTTP"),
        ],
    ),
    (
        "GAS_TYPE",
        "가스 종류",
        30,
        [
            ("CO", "일산화탄소"),
            ("H2S", "황화수소"),
            ("CO2", "이산화탄소"),
            ("O2", "산소"),
            ("NO2", "이산화질소"),
            ("SO2", "이산화황"),
            ("O3", "오존"),
            ("NH3", "암모니아"),
            ("VOC", "휘발성 유기화합물"),
            ("CH4", "메탄"),
        ],
    ),
    (
        "UNIT_CODE",
        "측정 단위",
        40,
        [
            ("ppm", "ppm (백만분의 일)"),
            ("ppb", "ppb (십억분의 일)"),
            ("%", "% (퍼센트)"),
            ("%LEL", "%LEL (폭발하한)"),
            ("A", "A (전류)"),
            ("V", "V (전압)"),
            ("kW", "kW (전력)"),
        ],
    ),
    (
        "EVENT_TYPE",
        "이벤트 구분",
        50,
        [
            ("GAS_ALARM", "가스 경보"),
            ("POWER_ANOMALY", "전력 이상"),
            ("ZONE_ENTRY", "위험구역 진입"),
            ("PPE_VIOLATION", "PPE 미착용"),
            ("SAFETY_MISS", "안전 점검 미이행"),
            ("VR_INCOMPLETE", "VR 교육 미이수"),
        ],
    ),
    (
        "NOTIF_CHANNEL",
        "알림 채널",
        60,
        [
            ("APP", "앱 푸시"),
            ("REALTIME", "관제 실시간 알림"),
            ("SMS", "SMS"),
            ("EMAIL", "이메일"),
        ],
    ),
    (
        "WORK_TYPE",
        "작업 유형",
        70,
        [
            ("CONFINED", "밀폐공간 작업"),
            ("HEIGHT", "고소작업"),
            ("HOT", "용접 및 화기"),
            ("PIPE", "배관 작업"),
            ("NORMAL", "일반 작업"),
        ],
    ),
]


# ───────────────────────────────────────────────────────────
# 위험 유형
# ───────────────────────────────────────────────────────────
RISK_CATEGORIES = [
    # (code, name, applies_to, sort_order, types)
    (
        "RISK_GAS",
        "유해가스",
        "realtime,event,alarm",
        10,
        [
            ("GAS_LEAK", "가스 누출 위험", True),
            ("OXYGEN_DEFICIT", "산소 결핍 위험", True),
            ("TOXIC_EXPOSURE", "유독가스 노출", True),
        ],
    ),
    (
        "RISK_POWER",
        "전력",
        "realtime,event,alarm",
        20,
        [
            ("POWER_OVERLOAD", "전력 과부하 위험", True),
            ("CURRENT_SPIKE", "전류 급증", True),
            ("VOLTAGE_DROP", "전압 강하", True),
        ],
    ),
    (
        "RISK_LOCATION",
        "위치",
        "realtime,event,alarm",
        30,
        [
            ("LOCATION_OUT", "위치 이탈 위험", True),
            ("ZONE_VIOLATION", "위험구역 진입", True),
        ],
    ),
    (
        "RISK_WORK",
        "작업 안전",
        "event,alarm",
        40,
        [
            ("FALL_RISK", "추락 위험", True),
            ("PPE_MISSING", "PPE 미착용", False),
            ("SAFETY_BYPASS", "안전 절차 우회", False),
        ],
    ),
    (
        "RISK_COMPLEX",
        "복합 위험",
        "realtime,event,alarm",
        50,
        [
            ("MULTI_HAZARD", "복합 위험 상황", True),
        ],
    ),
    (
        "RISK_SYSTEM",
        "시스템",
        "event",
        60,
        [
            ("DEVICE_OFFLINE", "장비 오프라인", False),
            ("DATA_LOSS", "데이터 수신 실패", False),
        ],
    ),
    (
        "RISK_COMMON",
        "공통",
        "event",
        70,
        [
            ("OTHER", "기타", False),
        ],
    ),
]


# ───────────────────────────────────────────────────────────
# 위험 기준 (알람 단계)
# ───────────────────────────────────────────────────────────
ALARM_LEVELS = [
    # (code, name, color, intensity, priority)
    ("NORMAL", "정상", "green", "normal", 10),
    ("CAUTION", "주의", "yellow", "caution", 30),
    ("WARNING", "경고", "orange", "warning", 60),
    ("DANGER", "위험", "red", "danger", 90),
]


# ───────────────────────────────────────────────────────────
# 임계치 분류 + 임계치 기준
# ───────────────────────────────────────────────────────────
# 핵심: GAS 임계치는 generators.py 의 GAS_THRESHOLDS 와 100% 일치.
#   - over  : caution_value 초과 시 주의, danger_value 초과 시 위험
#   - under : caution_value 미만 시 주의, danger_value 미만 시 위험 (산소 등)
THRESHOLD_CATEGORIES = [
    # (code, name, applies_to, sort_order, thresholds)
    (
        "TH_GAS",
        "유해가스",
        "realtime,alarm",
        10,
        [
            # (item_code, item_name, unit, operator, caution_value, danger_value)
            # 하기 값들은 generators.py 의 GAS_THRESHOLDS 와 동일.
            ("co", "일산화탄소", "ppm", "over", 25.0, 200.0),
            ("h2s", "황화수소", "ppm", "over", 10.0, 50.0),
            ("co2", "이산화탄소", "ppm", "over", 1000.0, 5000.0),
            (
                "o2",
                "산소 (저산소)",
                "%",
                "under",
                18.0,
                16.0,
            ),  # under: 18%↓ 주의, 16%↓ 위험
            (
                "o2_high",
                "산소 (과산소)",
                "%",
                "over",
                21.5,
                23.5,
            ),  # over: 21.5%↑ 주의, 23.5%↑ 위험
            ("no2", "이산화질소", "ppm", "over", 3.0, 5.0),
            ("so2", "이산화황", "ppm", "over", 2.0, 5.0),
            ("o3", "오존", "ppm", "over", 0.05, 0.1),
            ("nh3", "암모니아", "ppm", "over", 25.0, 50.0),
            ("voc", "휘발성유기화합물", "ppm", "over", 0.5, 2.0),
        ],
    ),
    (
        "TH_POWER",
        "전력",
        "realtime,alarm",
        20,
        [
            ("current", "전류", "A", "over", 18.0, 25.0),
            ("voltage_low", "저전압", "V", "under", 200.0, 180.0),
            ("voltage_high", "고전압", "V", "over", 240.0, 260.0),
        ],
    ),
    (
        "TH_AI",
        "AI 예측",
        "ai_predict",
        30,
        [
            ("anomaly_score", "이상 점수", "점", "over", 0.7, 0.9),
        ],
    ),
    ("TH_COMMON", "공통", "realtime,alarm", 40, []),
]


def seed(apps, schema_editor):
    CodeGroup = apps.get_model("backoffice", "CodeGroup")
    Code = apps.get_model("backoffice", "Code")
    RiskCategory = apps.get_model("backoffice", "RiskCategory")
    RiskType = apps.get_model("backoffice", "RiskType")
    AlarmLevel = apps.get_model("backoffice", "AlarmLevel")
    ThCategory = apps.get_model("backoffice", "ThresholdCategory")
    Threshold = apps.get_model("backoffice", "Threshold")

    # 공통 코드
    for grp_code, grp_name, sort_order, codes in CODE_GROUPS:
        grp, _ = CodeGroup.objects.get_or_create(
            code=grp_code,
            defaults={"name": grp_name, "sort_order": sort_order, "is_system": True},
        )
        for idx, (c, n) in enumerate(codes, start=1):
            Code.objects.get_or_create(
                group=grp,
                code=c,
                defaults={"name": n, "sort_order": idx * 10},
            )

    # 위험 분류
    for cat_code, cat_name, applies, sort_order, types in RISK_CATEGORIES:
        cat, _ = RiskCategory.objects.get_or_create(
            code=cat_code,
            defaults={
                "name": cat_name,
                "applies_to": applies,
                "sort_order": sort_order,
                "is_system": True,
            },
        )
        for idx, (t_code, t_name, on_map) in enumerate(types, start=1):
            RiskType.objects.get_or_create(
                category=cat,
                code=t_code,
                defaults={
                    "name": t_name,
                    "show_on_map": on_map,
                    "sort_order": idx * 10,
                },
            )

    # 알람 단계
    for code, name, color, intensity, priority in ALARM_LEVELS:
        AlarmLevel.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "color": color,
                "intensity": intensity,
                "priority": priority,
                "is_system": True,
            },
        )

    # 임계치
    for cat_code, cat_name, applies, sort_order, items in THRESHOLD_CATEGORIES:
        cat, _ = ThCategory.objects.get_or_create(
            code=cat_code,
            defaults={
                "name": cat_name,
                "applies_to": applies,
                "sort_order": sort_order,
                "is_system": True,
            },
        )
        for ic, iname, unit, op, caution, danger in items:
            Threshold.objects.get_or_create(
                category=cat,
                item_code=ic,
                defaults={
                    "item_name": iname,
                    "unit": unit,
                    "operator": op,
                    "caution_value": caution,
                    "danger_value": danger,
                    "applies_to": applies,
                },
            )


def unseed(apps, schema_editor):
    """롤백. 시스템 시드만 제거. 사용자 추가 데이터는 보존."""
    apps.get_model("backoffice", "Code").objects.filter(group__is_system=True).delete()
    apps.get_model("backoffice", "CodeGroup").objects.filter(is_system=True).delete()

    apps.get_model("backoffice", "RiskType").objects.filter(
        category__is_system=True
    ).delete()
    apps.get_model("backoffice", "RiskCategory").objects.filter(is_system=True).delete()

    apps.get_model("backoffice", "AlarmLevel").objects.filter(is_system=True).delete()

    apps.get_model("backoffice", "Threshold").objects.filter(
        category__is_system=True
    ).delete()
    apps.get_model("backoffice", "ThresholdCategory").objects.filter(
        is_system=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("backoffice", "0004_reference_masters")]
    operations = [migrations.RunPython(seed, reverse_code=unseed)]
