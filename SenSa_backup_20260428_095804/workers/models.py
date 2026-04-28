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

[변경 이력]
  v1 : worker_id, name, department, is_active
  v2 (Phase 4A):
       - Worker: position, email, phone, last_seen_at 필드 추가
       - NotificationLog 모델 신규 (관리자 → 작업자 푸시 이력)
"""
from django.conf import settings
from django.db import models


MOVEMENT_STATUS_CHOICES = [
    ('moving', '이동'),
    ('stationary', '정지'),
]


class Worker(models.Model):
    """
    현장 작업자 — 관제 추적 대상
    """

    worker_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="작업자 식별자 (worker_01 등)",
    )
    name = models.CharField(
        max_length=100,
        help_text="작업자명",
    )
    department = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="소속 부서",
    )
    # ─── Phase 4A 신규 ───
    position = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="직급 (사원/대리/과장 등)",
    )
    email = models.EmailField(
        blank=True,
        default='',
        help_text="이메일",
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="연락처",
    )
    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "마지막 heartbeat 시각. "
            "WorkerLocation 가 들어올 때마다 갱신되어 '연결 상태' 판정에 쓰임."
        ),
    )
    # ─────────────────────

    is_active = models.BooleanField(
        default=True,
        help_text="활성 여부",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['worker_id']
        verbose_name = '작업자'
        verbose_name_plural = '작업자 목록'

    def __str__(self):
        return f"{self.name} ({self.worker_id})"


class WorkerLocation(models.Model):
    """작업자 위치 시계열"""

    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name='locations',
        help_text="소속 작업자",
    )
    x = models.FloatField(help_text="평면도 X 좌표")
    y = models.FloatField(help_text="평면도 Y 좌표")
    movement_status = models.CharField(
        max_length=20,
        choices=MOVEMENT_STATUS_CHOICES,
        default='moving',
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '작업자 위치'
        verbose_name_plural = '작업자 위치 이력'
        indexes = [
            models.Index(fields=['worker', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.worker.name} @ ({self.x}, {self.y})"


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

    SEND_TYPE_CHOICES = [
        ('single', '개별'),
        ('selected', '선택'),
        ('all', '전체'),
    ]

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_notifications',
        help_text="알림을 보낸 관리자 (로그인 사용자)",
    )
    send_type = models.CharField(
        max_length=20,
        choices=SEND_TYPE_CHOICES,
        help_text="전송 유형",
    )
    recipients = models.ManyToManyField(
        Worker,
        related_name='received_notifications',
        help_text="수신 대상 작업자 (스냅샷)",
    )
    message = models.TextField(
        max_length=200,
        help_text="메시지 본문 (최대 100자 권장)",
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = '알림 전송 이력'
        verbose_name_plural = '알림 전송 이력 목록'
        indexes = [
            models.Index(fields=['-sent_at']),
        ]

    def __str__(self):
        return f'[{self.get_send_type_display()}] {self.message[:30]}'