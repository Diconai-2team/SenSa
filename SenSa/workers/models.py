"""
workers/models.py — 현장 작업자 + 위치 시계열 + 알림 로그

┌─────────────────────────────────────────────────────┐
│  accounts.User  = "시스템을 조작하는 사람" (로그인 O)   │
│  workers.Worker = "시스템이 감시하는 사람" (로그인 X)   │
│                                                     │
│  Worker(정보 - 거의 불변)                              │
│    └→ WorkerLocation(위치 - 1초마다 쌓임)              │
│    └→ NotificationLog(관리자가 보낸 푸시 알림 기록)     │
└─────────────────────────────────────────────────────┘
"""
# ⭐ 핵심 설계 결정: User와 Worker는 다른 엔티티
#    User = 백오피스/대시보드 로그인하는 운영자/관리자
#    Worker = 현장에서 추적되는 대상 (모바일 앱이나 웨어러블에서 위치 송신)
#    같은 사람이라도 두 역할을 하면 두 row가 만들어짐

from django.conf import settings
# settings.AUTH_USER_MODEL 참조용 — accounts.User와의 FK 연결 시 사용
from django.db import models


MOVEMENT_STATUS_CHOICES = [
# WorkerLocation.movement_status 필드의 선택지 — 단순 2-state
    ('moving', '이동'),
    # 좌표가 변하고 있음 — 일반 작업 중
    ('stationary', '정지'),
    # 같은 자리에 머무름 — 휴식이거나 이상 상황(쓰러짐 등)일 가능성
    # ⚠️ 'stationary' 자체는 알람 트리거 아님 — 향후 확장 여지
]


class Worker(models.Model):
    """
    현장 작업자 — 관제 추적 대상
    """
    # 거의 불변 정보 (이름, 부서 등)는 여기에, 매 초 변하는 위치는 WorkerLocation에 분리
    # 정규화 결정: 시계열을 별 테이블로 빼서 Worker row 자체는 가볍게 유지

    worker_id = models.CharField(
        max_length=50,
        unique=True,
        # DB 레벨 중복 차단 + 자동 인덱스 — alerts.evaluate_worker가 이 값으로 조회
        help_text="작업자 식별자 (worker_01 등)",
    )
    # 사람이 읽는 ID — alerts.state_store의 Redis 키에도 사용됨
    name = models.CharField(
        max_length=100,
        help_text="작업자명",
    )
    # 알람 메시지에 노출되는 이름 — alerts._build_message가 사용
    department = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="소속 부서",
    )
    # 부서 — 작업자 현황 페이지에서 그룹별 조회용

    # ─── Phase 4A 신규 ───
    position = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="직급 (사원/대리/과장 등)",
    )
    # 직급 — 작업자 현황 페이지 표시용
    # ⚠️ accounts.User에도 동일한 position 필드 존재 — 운영자/작업자 모두에게 공통 개념
    email = models.EmailField(
        blank=True,
        default='',
        help_text="이메일",
    )
    # EmailField — 이메일 형식 자동 검증 (vs CharField + 수동 검증)
    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="연락처",
    )
    # 향후 SMS 알림 발송 시 사용될 채널 정보
    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "마지막 heartbeat 시각. "
            "WorkerLocation 가 들어올 때마다 갱신되어 '연결 상태' 판정에 쓰임."
        ),
    )
    # ⭐ Phase 4A 핵심 필드 — 연결 상태 판정의 단일 출처(SSOT)
    # WorkerLocation INSERT마다 같이 UPDATE되어 "30초 이내 데이터 들어왔는지" 판정 가능
    # null=True 허용 — 등록만 되고 한 번도 송신 없는 신규 작업자 표현
    # ─────────────────────

    is_active = models.BooleanField(
        default=True,
        help_text="활성 여부",
    )
    # 퇴사/장기 휴직 시 False 처리 — 물리 삭제하면 과거 위치 이력 모두 CASCADE 삭제됨
    created_at = models.DateTimeField(auto_now_add=True)
    # 작업자 등록 시각 — auto_now_add로 INSERT 시 자동
    # ⚠️ updated_at 부재 — 부서/직급 변경 이력 추적 불가

    class Meta:
        ordering = ['worker_id']
        # 기본 정렬 — worker_01, worker_02 ... 순서로 자연스러움
        verbose_name = '작업자'
        verbose_name_plural = '작업자 목록'

    def __str__(self):
        return f"{self.name} ({self.worker_id})"
        # '김재승 (worker_01)' 형태


class WorkerLocation(models.Model):
    """작업자 위치 시계열"""
    # 초당 1건 누적되는 시계열 테이블 — 누적량이 가장 큰 모델 중 하나
    # 100명 × 86400초 = 일 864만 row, 30일이면 2.6억 row
    # ⚠️ 운영 환경에서 파티셔닝/아카이빙 전략 필수

    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        # Worker 삭제 시 위치 이력도 함께 삭제 — 정규화 우선
        # ⚠️ 실제 운영에선 SET_NULL로 이력 보존이 안전 (퇴사자 위치 추적 보존)
        related_name='locations',
        # 역참조: worker.locations.all()로 모든 위치 이력 조회
        # WorkerSerializer.get_location_count도 이 이름 사용
        help_text="소속 작업자",
    )
    x = models.FloatField(help_text="평면도 X 좌표")
    # 픽셀 좌표 — devices.Device.x, geofence.GeoFence.polygon과 동일 좌표계
    y = models.FloatField(help_text="평면도 Y 좌표")
    movement_status = models.CharField(
        max_length=20,
        choices=MOVEMENT_STATUS_CHOICES,
        default='moving',
    )
    # 이 측정치 시점의 이동/정지 상태
    timestamp = models.DateTimeField(auto_now_add=True)
    # 측정 시각 — auto_now_add (서버 수신 시각, 디바이스 발신 시각 아님)

    class Meta:
        ordering = ['-timestamp']
        # 최신 먼저 — 차트/조회 기본 정렬
        verbose_name = '작업자 위치'
        verbose_name_plural = '작업자 위치 이력'
        indexes = [
            models.Index(fields=['worker', '-timestamp']),
            # 복합 인덱스 — "특정 작업자의 최근 N건" 핫쿼리 최적화
            # WorkerViewSet.latest 액션 / 차트 데이터 조회 모두 커버
        ]

    def __str__(self):
        return f"{self.worker.name} @ ({self.x}, {self.y})"
        # ⚠️ self.worker.name 접근 — N+1 위험 (admin 목록에서 select_related 필요)


# ═══════════════════════════════════════════════════════════
# Phase 4A 신규 — 관리자 → 작업자 푸시 알림 로그
# ═══════════════════════════════════════════════════════════

class NotificationLog(models.Model):
    """
    관리자가 작업자에게 보낸 푸시 알림 이력.

    실제 모바일 푸시 전송은 Phase 4B+ 범위.
    4A 는 로그 저장과 '발송됨' UI 피드백까지만 처리.

    [선택 알림 / 전체 알림 / 개별 알림 모두 같은 테이블에 기록]
      - 선택/개별: workers 에 1~N 명
      - 전체: workers 에 전체 (당시 스냅샷)
    """
    # 한 테이블에 3가지 유형 다 담는 결정 — send_type으로 구분
    # M2M 스냅샷 — '전체' 알림 시점에 활성화된 작업자 목록을 그대로 저장
    # 향후 작업자가 추가/퇴사해도 과거 알림 수신자 명단은 보존됨

    SEND_TYPE_CHOICES = [
        ('single', '개별'),
        # 1명 대상 알림
        ('selected', '선택'),
        # 운영자가 체크박스로 골라낸 N명 알림
        ('all', '전체'),
        # 활성 작업자 전원
    ]

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # accounts.User — 알림을 보낸 운영자/관리자
        on_delete=models.SET_NULL,
        # 운영자가 삭제돼도 알림 이력은 보존 (감사 추적성)
        null=True,
        related_name='sent_notifications',
        # user.sent_notifications.all()로 특정 운영자가 보낸 모든 알림 조회
        help_text="알림을 보낸 관리자 (로그인 사용자)",
    )
    send_type = models.CharField(
        max_length=20,
        choices=SEND_TYPE_CHOICES,
        help_text="전송 유형",
    )
    recipients = models.ManyToManyField(
        Worker,
        # M2M — 한 알림의 다수 수신자 표현
        related_name='received_notifications',
        # worker.received_notifications.all()로 작업자가 받은 모든 알림 조회 가능
        help_text="수신 대상 작업자 (스냅샷)",
    )
    message = models.TextField(
        max_length=200,
        # ⚠️ TextField에 max_length 지정 — Django 폼/admin엔 영향, DB엔 영향 없음
        #    실제 길이 제한은 views.WorkerNotifyView가 200자 검증
        help_text="메시지 본문 (최대 100자 권장)",
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    # 발송 시각

    class Meta:
        ordering = ['-sent_at']
        verbose_name = '알림 전송 이력'
        verbose_name_plural = '알림 전송 이력 목록'
        indexes = [
            models.Index(fields=['-sent_at']),
            # 시간순 조회용 — 최근 N건 알림 빠르게 조회
        ]

    def __str__(self):
        return f'[{self.get_send_type_display()}] {self.message[:30]}'