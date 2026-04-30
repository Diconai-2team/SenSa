from django.db import models
# 모델 필드 타입(CharField, ForeignKey 등)을 정의하기 위한 ORM 모듈이야


ALARM_TYPE_CHOICES = [
# alarm_type 필드의 선택 가능한 값 목록 — 알람의 발생 원인을 분류해
    ('geofence_enter', '위험구역 진입'),
    # 작업자가 위험/주의 지오펜스에 진입했을 때
    ('sensor_caution', '센서 주의'),
    # 가스/전력 센서가 caution 임계치를 넘었을 때
    ('sensor_danger',  '센서 위험'),
    # 가스/전력 센서가 danger 임계치를 넘었을 때
    ('combined',       '복합 위험'),
    # 지오펜스 + 센서 조건이 동시에 발생한 경우 (실제 services.py에선 별도 type 사용 중)
]
# ⚠️ 리뷰: services.py는 'state_danger_enter', 'state_ongoing', 'state_recover_partial',
#         'sensor_caution', 'sensor_danger', 'sensor_recover_normal' 등 6+종 사용 — choices와 불일치

ALARM_LEVEL_CHOICES = [
# alarm_level 필드의 선택 가능한 값 — 심각도 단계
    ('info',     '정보'),
    # 회복/복귀 알람 (위험 상황 종료) — services.py의 state_recover_*에 매핑돼
    ('caution',  '주의'),
    # 주의 수준 — STEL 등 단시간 노출 한계 초과
    ('danger',   '위험'),
    # 위험 수준 — IDLH 등 즉시 대피 필요
    ('critical', '심각'),
    # 심각 수준 — restricted(출입금지) 구역 진입 (Gas 병합 v3 신규)
]


class Alarm(models.Model):
    # 알람 1건을 저장하는 엔티티 — 작업자/센서/지오펜스 3축 모두를 한 테이블에 담는 통합 모델
    """
    알람 기록
    - 작업자가 지오펜스에 진입했거나
    - 센서가 임계치를 초과했거나
    - 두 조건이 동시에 발생했을 때 생성
    """
    alarm_type  = models.CharField(max_length=30, choices=ALARM_TYPE_CHOICES)
    # 알람 발생 원인 분류 — 통계/필터링의 기준이 돼
    alarm_level = models.CharField(max_length=20, choices=ALARM_LEVEL_CHOICES, default='caution')
    # 심각도 단계 — UI 색상/뱃지 분기와 ISA-18.2 우선순위 정렬의 기준

    # 관련 작업자 정보
    worker_id   = models.CharField(max_length=50, blank=True, default='')
    # 작업자 식별자 — 센서 알람일 땐 빈 문자열 (FK 아니라 문자열로 느슨하게 연결)
    worker_name = models.CharField(max_length=100, blank=True, default='')
    # 작업자 표시명 — denormalize 저장 (작업자 정보 변경 시에도 알람 기록은 그대로 유지)
    worker_x    = models.FloatField(null=True, blank=True)
    # 알람 발생 순간의 작업자 X 좌표 — 사고 조사 시 위치 추적용 (스냅샷)
    worker_y    = models.FloatField(null=True, blank=True)
    # 알람 발생 순간의 작업자 Y 좌표

    # 관련 지오펜스 (다른 앱의 모델을 문자열로 참조)
    geofence    = models.ForeignKey(
        'geofence.GeoFence', on_delete=models.SET_NULL,
        # 지오펜스 삭제돼도 알람 기록은 보존 — 감사 추적 우선
        null=True, blank=True, related_name='alarms'
        # 역참조: geofence.alarms.all()로 해당 지오펜스에서 발생한 알람 조회 가능
    )

    # 관련 센서
    device_id   = models.CharField(max_length=50, blank=True, default='')
    # 알람을 일으킨 센서 식별자 — 작업자 알람일 땐 빈 문자열
    sensor_type = models.CharField(max_length=20, blank=True, default='')
    # 센서 종류 ('gas' | 'power') — services.py의 _build_sensor_message에서 라벨 매핑에 사용

    # 알람 메시지
    message     = models.TextField()
    # 사람이 읽는 알람 본문 — services.py의 _build_message가 조립한 결과 저장

    # 읽음 여부
    is_read     = models.BooleanField(default=False)
    # 운영자 확인 여부 — 미확인 알람 카운트/필터링의 기준
    created_at  = models.DateTimeField(auto_now_add=True)
    # 알람 발생 시각 — auto_now_add로 INSERT 시 자동 채움 (수정 불가)

    class Meta:
        ordering = ['-created_at']
        # 기본 정렬: 최신 알람이 위 — 단, views.py에선 ISA-18.2 §7 우선순위 정렬로 오버라이드

    def __str__(self):
        # admin/shell에서 객체 표현 — 레벨과 메시지 앞 40자 표시
        return f"[{self.alarm_level}] {self.message[:40]}"